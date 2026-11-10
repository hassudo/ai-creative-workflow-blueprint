#!/usr/bin/env python3
"""Inject the pipeline output into the dashboard template.

Keeps index.html fully self-contained so it can be opened from disk (file://),
screen-shared, or published as a single file. No fetch(), no CDN, no build
tooling — a deliberate constraint for a demo that must never fail live.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "template.html"
OUTPUT = ROOT / "index.html"
DATA = ROOT / "data" / "toast_metrics.json"


def main() -> None:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = TEMPLATE.read_text(encoding="utf-8")
    if "__TOAST_DATA__" not in html:
        raise SystemExit("template placeholder __TOAST_DATA__ not found")

    html = html.replace("__TOAST_DATA__", json.dumps(payload, separators=(",", ":")))
    html = html.replace("__BUILD_STAMP__", payload["generated_at"])

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"built {OUTPUT} ({len(html) / 1024:.0f} KB) from {DATA.name}")


if __name__ == "__main__":
    main()
