"""Monitor de actividad open source: una fotografía real por día (UTC).

Solo usa la biblioteca estándar de Python. No genera actividad artificial.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("date", "repo", "stars", "forks", "open_issues_and_prs")


def fetch_repo(repo: str, token: str | None = None) -> dict[str, int]:
    url = f"https://api.github.com/repos/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-activity-lab/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
            payload = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"No se pudo consultar {repo}: {exc}") from exc

    try:
        return {
            "stars": int(payload["stargazers_count"]),
            "forks": int(payload["forks_count"]),
            # GitHub cuenta también PRs en open_issues_count.
            "open_issues_and_prs": int(payload["open_issues_count"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Respuesta inesperada de la API para {repo}") from exc


def read_history(file_path: Path) -> list[dict[str, str]]:
    if not file_path.exists() or file_path.stat().st_size == 0:
        return []
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Formato de data/history.csv incompatible")
        rows = list(reader)
    if any(not all(row.get(field) is not None for field in FIELDS) for row in rows):
        raise ValueError("Histórico CSV incompleto")
    return rows


def to_csv(rows: list[dict[str, str]]) -> str:
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda row: (row["date"], row["repo"])))
    return target.getvalue()


def build_summary(rows: list[dict[str, str]], targets: list[str], day: str) -> str:
    out = [
        "# Open Source Radar — último snapshot",
        "",
        f"**Fecha de observación (UTC): {day}** · Origen: [API pública de GitHub](https://docs.github.com/rest/repos/repos#get-a-repository).",
        "",
        "| Repositorio | Estrellas | Variación vs. snapshot anterior | Forks | Issues + PRs abiertos |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for repo in targets:
        history = [r for r in rows if r["repo"] == repo]
        current = history[-1]
        if len(history) > 1:
            difference = int(current["stars"]) - int(history[-2]["stars"])
            delta = f"{difference:+,}"
        else:
            delta = "—"
        out.append(
            f"| [{repo}](https://github.com/{repo}) | {int(current['stars']):,} | {delta} | "
            f"{int(current['forks']):,} | {int(current['open_issues_and_prs']):,} |"
        )
    out.extend([
        "", "> Actualización generada **automáticamente** por GitHub Actions. No representa trabajo manual diario.",
        "", "`open_issues_count` incluye pull requests abiertos, según la API de GitHub.", "",
    ])
    return "\n".join(out)


def build_svg(rows: list[dict[str, str]], targets: list[str], day: str) -> str:
    width = 960
    height = 120 + 78 * len(targets)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Tendencias de estrellas en proyectos open source">',
        '<rect width="100%" height="100%" fill="#0d1117" rx="16"/>',
        '<text x="28" y="39" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#e6edf3">Open Source Radar</text>',
        f'<text x="28" y="62" font-family="Arial,sans-serif" font-size="12" fill="#8b949e">Snapshots reales de GitHub · {html.escape(day)}</text>',
    ]
    palette = ("#58a6ff", "#3fb950", "#d2a8ff", "#f2cc60", "#ff7b72", "#79c0ff")
    for index, repo in enumerate(targets):
        history = [int(row["stars"]) for row in rows if row["repo"] == repo]
        left, right = 335, 905
        top = 91 + index * 78
        bot = top + 35
        low, high = min(history), max(history)
        span = max(1, high - low)
        coords = []
        for position, value in enumerate(history):
            x = left + (right - left) * (position / max(len(history) - 1, 1))
            y = bot - (value - low) / span * 28 if len(history) > 1 else top + 18
            coords.append((x, y))
        color = palette[index % len(palette)]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        parts.extend([
            f'<text x="28" y="{top+14}" fill="#e6edf3" font-family="Arial,sans-serif" font-size="15">{html.escape(repo)}</text>',
            f'<text x="28" y="{top+35}" fill="#8b949e" font-family="Arial,sans-serif" font-size="12">{history[-1]:,} estrellas</text>',
            f'<line x1="{left}" y1="{bot+8}" x2="{right}" y2="{bot+8}" stroke="#30363d"/>',
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>',
        ])
        if len(coords) == 1:
            x, y = coords[0]
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
    parts.append(f'<text x="28" y="{height-17}" fill="#8b949e" font-family="Arial,sans-serif" font-size="12">Datos generados automáticamente; cada repositorio usa su propia escala vertical.</text>')
    parts.append("</svg>\n")
    return "\n".join(parts)


def run(
    root: Path = ROOT,
    day: str | None = None,
    collector: Callable[[str, str | None], dict[str, int]] = fetch_repo,
) -> bool:
    today = day or datetime.now(timezone.utc).date().isoformat()
    if datetime.strptime(today, "%Y-%m-%d").date().isoformat() != today:
        raise ValueError("La fecha debe estar en formato YYYY-MM-DD")

    targets = json.loads((root / "config/repos.json").read_text(encoding="utf-8"))
    if not isinstance(targets, list) or not targets or any(not isinstance(item, str) or item.count("/") != 1 for item in targets):
        raise ValueError("config/repos.json debe contener owner/repo válidos")
    if len(set(targets)) != len(targets):
        raise ValueError("Hay repositorios repetidos")

    history_file = root / "data/history.csv"
    rows = read_history(history_file)
    if any(row["date"] == today for row in rows):
        print(f"Snapshot de {today} ya existente; no se generan cambios")
        return False
    token = os.environ.get("GH_API_TOKEN") or None
    fresh = []
    for repo in targets:
        metrics = collector(repo, token)
        if any(not isinstance(metrics.get(key), int) or metrics[key] < 0 for key in FIELDS[2:]):
            raise ValueError(f"Métricas inválidas para {repo}")
        fresh.append({"date": today, "repo": repo, **{k: str(metrics[k]) for k in FIELDS[2:]}})
    rows.extend(fresh)
    rows = sorted(rows, key=lambda row: (row["date"], row["repo"]))
    latest = {"date_utc": today, "source": "https://api.github.com/repos/{owner}/{repo}", "automated": True,
              "repositories": [{"repo": r["repo"], **{k: int(r[k]) for k in FIELDS[2:]}} for r in fresh]}
    outputs = {
        root / "data/history.csv": to_csv(rows),
        root / "reports/summary.md": build_summary(rows, targets, today),
        root / "reports/stars.svg": build_svg(rows, targets, today),
        root / "reports/latest.json": json.dumps(latest, indent=2, ensure_ascii=False) + "\n",
    }
    for path, contents in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    print(f"Snapshot real de {today}: {len(targets)} repositorios; archivos actualizados")
    return True


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
