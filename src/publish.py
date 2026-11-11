"""Publica snapshots automáticos en commits con cambios reales."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "data/history.csv",
    "reports/latest.json",
    "reports/summary.md",
    "reports/stars.svg",
    "reports/deltas.json",
)


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=check)


def publish(root: Path, day: str, branch: str, *, push: bool = True) -> int:
    target = 1 + date.fromisoformat(day).toordinal() % 5
    if bool(os.environ.get("AUTO_AUTHOR_NAME")) != bool(os.environ.get("AUTO_AUTHOR_EMAIL")):
        raise ValueError("Define ambas variables de autor, o ninguna")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise ValueError("Hay cambios preparados ajenos al snapshot")
    # Verificar la base antes de crear commits; un push normal rechaza carreras posteriores.
    if push:
        git(root, "fetch", "origin", branch)
        if git(root, "rev-parse", "HEAD").stdout != git(root, "rev-parse", "FETCH_HEAD").stdout:
            raise RuntimeError("La rama remota avanzó; ejecuta de nuevo el workflow")

    changed = []
    for path in FILES:
        git(root, "add", "--", path)
        if git(root, "diff", "--cached", "--quiet", "--", path, check=False).returncode == 1:
            changed.append(path)
    git(root, "reset", "--quiet", "--", *FILES)
    if not changed:
        print("Sin cambios: no se crea commit")
        return 0

    groups = [[] for _ in range(min(target, len(changed)))]
    for index, path in enumerate(changed):
        groups[index % len(groups)].append(path)
    for group in groups:
        git(root, "add", "--", *group)
        label = ", ".join(Path(path).stem for path in group)
        command = [
            "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", f"data(auto): snapshot {day} {label} [automated]",
            "-m", "Generated-by: GitHub Actions",
            "-m", "Disclosure: Automated data update, not manual coding activity.",
        ]
        if os.environ.get("AUTO_AUTHOR_NAME"):
            command += ["--author", f"{os.environ['AUTO_AUTHOR_NAME']} <{os.environ['AUTO_AUTHOR_EMAIL']}>"]
        git(root, *command)

    if push:
        git(root, "push", "origin", f"HEAD:refs/heads/{branch}")
    print(f"Publicados {len(groups)} commits automáticos para {day}")
    return len(groups)


if __name__ == "__main__":
    try:
        publish(ROOT, sys.argv[1], sys.argv[2])
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
