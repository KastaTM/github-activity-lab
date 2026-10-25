import json
import tempfile
import unittest
from pathlib import Path

from src.monitor import build_svg, read_history, run


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "config/repos.json").write_text('["python/cpython", "pallets/flask"]', encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, repo, token):
        self.calls.append(repo)
        return {"stars": 100 + len(self.calls), "forks": 20, "open_issues_and_prs": 3}

    def test_creates_actual_files_and_once_per_day(self):
        self.assertTrue(run(root=self.root, day="2026-10-25", collector=self.fake))
        rows = read_history(self.root / "data/history.csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(run(root=self.root, day="2026-10-25", collector=self.fake))
        self.assertEqual(len(self.calls), 2)
        self.assertIn("automáticamente", (self.root / "reports/summary.md").read_text(encoding="utf-8"))
        payload = json.loads((self.root / "reports/latest.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["automated"])
        self.assertIn("<svg", (self.root / "reports/stars.svg").read_text(encoding="utf-8"))

    def test_subsequent_days_and_deltas(self):
        run(root=self.root, day="2026-10-25", collector=self.fake)
        self.calls.clear()
        run(root=self.root, day="2026-10-26", collector=lambda repo, token: {"stars": 150, "forks": 21, "open_issues_and_prs": 2})
        self.assertEqual(len(read_history(self.root / "data/history.csv")), 4)
        summary = (self.root / "reports/summary.md").read_text(encoding="utf-8")
        self.assertIn("+49", summary)
        self.assertIn("+48", summary)

    def test_api_failure_writes_nothing(self):
        def fail(repo, token):
            if repo == "pallets/flask":
                raise RuntimeError("API error")
            return {"stars": 4, "forks": 1, "open_issues_and_prs": 0}

        with self.assertRaises(RuntimeError):
            run(root=self.root, day="2026-10-25", collector=fail)
        self.assertFalse((self.root / "data/history.csv").exists())
        self.assertFalse((self.root / "reports/latest.json").exists())

    def test_svg_sanitizes_repo_name(self):
        svg = build_svg([{"repo": "x/<bad>", "stars": "1", "date": "2026-10-25"}], ["x/<bad>"], "2026-10-25")
        self.assertIn("x/&lt;bad&gt;", svg)
        self.assertNotIn("x/<bad>", svg)


if __name__ == "__main__":
    unittest.main()
