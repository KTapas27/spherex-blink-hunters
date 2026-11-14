"""Pre-build views for the demo targets so the live demo never waits on the archive.

Usage (from the project root):
    .venv/bin/python scripts/precache.py                 # all presets, defaults
    .venv/bin/python scripts/precache.py "R Dra" --per-group 3 --fov 0.1
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import pipeline  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("queries", nargs="*", help="names/coordinates (default: the presets)")
parser.add_argument("--fov", type=float, default=0.1)
parser.add_argument("--per-group", type=int, default=6)
args = parser.parse_args()

queries = args.queries or [p["query"] for p in pipeline.PRESETS]
for q in queries:
    t0 = time.time()
    key = pipeline.start_view(q, args.fov, args.per_group)
    last = None
    while True:
        state = pipeline.job(key)
        line = f"  {state['status']}: {state.get('message', '')} {state.get('done', '')}/{state.get('total', '')}"
        if line != last:
            print(line, flush=True)
            last = line
        if state["status"] in ("done", "error"):
            break
        time.sleep(2)
    m = state.get("manifest") or {}
    print(f"{q}: {state['status']} in {time.time() - t0:.0f}s, key={key}, "
          f"frames={len(m.get('frames', []))}, diffs={len(m.get('diffs', []))}, "
          f"exposures used={m.get('n_exposures_used')}/{m.get('n_available')}")
