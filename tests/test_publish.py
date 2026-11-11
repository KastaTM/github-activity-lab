import os
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src.publish import FILES, git, publish


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "work"
        self.remote = Path(self.tmp.name) / "remote.git"
        self.root.mkdir()
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        git(self.root, "init", "-b", "main")
        git(self.root, "remote", "add", "origin", str(self.remote))
        for path in FILES:
            file = self.root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("initial\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial")
        git(self.root, "push", "origin", "HEAD:refs/heads/main")
        self.base = git(self.root, "rev-parse", "HEAD").stdout.strip()
        self.author_env = patch.dict(os.environ, {"AUTO_AUTHOR_NAME": "", "AUTO_AUTHOR_EMAIL": ""})
        self.author_env.start()

    def tearDown(self):
        self.author_env.stop()
        self.tmp.cleanup()

    def day_for(self, count):
        start = date(2026, 10, 25)
        return next((start + timedelta(days=i)).isoformat() for i in range(5)
                    if 1 + (start + timedelta(days=i)).toordinal() % 5 == count)

    def change(self, count):
        for path in FILES[:count]:
            (self.root / path).write_text("changed\n", encoding="utf-8")

    def remote_head(self):
        return subprocess.run(["git", "--git-dir", str(self.remote), "rev-parse", "refs/heads/main"],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_commit_counts_and_no_empty_commits(self):
        for available, selected in ((5, 1), (5, 2), (5, 3), (5, 4), (5, 5), (2, 5)):
            with self.subTest(available=available, selected=selected):
                git(self.root, "reset", "--hard", self.base)
                self.change(available)
                count = publish(self.root, self.day_for(selected), "main", push=False)
                self.assertEqual(count, min(available, selected))
                self.assertEqual(int(git(self.root, "rev-list", "--count", f"{self.base}..HEAD").stdout), count)
                for commit in git(self.root, "rev-list", f"{self.base}..HEAD").stdout.splitlines():
                    self.assertTrue(git(self.root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).stdout.strip())
                    self.assertIn("[automated]", git(self.root, "show", "-s", "--format=%s", commit).stdout)
                    self.assertIn("github-actions[bot]", git(self.root, "show", "-s", "--format=%cn", commit).stdout)

    def test_unchanged_files_and_repeat_are_skipped(self):
        self.change(2)
        day = self.day_for(5)
        self.assertEqual(publish(self.root, day, "main"), 2)
        head = self.remote_head()
        self.assertEqual(publish(self.root, day, "main"), 0)
        self.assertEqual(self.remote_head(), head)

    def test_failure_before_push_leaves_remote_intact(self):
        self.change(5)
        original = git
        commits = 0

        def fail_second(root, *args, **kwargs):
            nonlocal commits
            if "commit" in args:
                commits += 1
                if commits == 2:
                    raise subprocess.CalledProcessError(1, ["git", *args])
            return original(root, *args, **kwargs)

        with patch("src.publish.git", side_effect=fail_second):
            with self.assertRaises(subprocess.CalledProcessError):
                publish(self.root, self.day_for(5), "main")
        self.assertEqual(self.remote_head(), self.base)
