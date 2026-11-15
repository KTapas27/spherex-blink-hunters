"""Pre-build views for the demo targets so the live demo never waits on the archive.

Usage (from the project root):
    .venv/bin/python scripts/precache.py                 # all presets, defaults
    .venv/bin/python scripts/precache.py "R Dra" --per-group 3 --fov 0.1
    .venv/bin/python scripts/precache.py --gaia          # also save the Gaia overlay for each view

Exits with status 1 if any view failed, after trying all of them.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config, gaia, pipeline  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("queries", nargs="*", help="names/coordinates (default: the presets)")
parser.add_argument("--fov", type=float, default=0.1)
parser.add_argument("--per-group", type=int, default=6)
parser.add_argument("--gaia", action="store_true", help="fetch and save the Gaia DR3 overlay too")
args = parser.parse_args()
failed = []

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
    if state["status"] == "done":
        try:  # save the target's own spectrum, so the first click on a slow server is instant
            pts, _ = pipeline.view_spectrum(key, m["target"]["ra"], m["target"]["dec"])
            print(f"  target spectrum: {len(pts)} points saved")
        except Exception as err:
            print(f"  target spectrum not saved ({err}); it will be measured live")
    if state["status"] == "error":
        failed.append(q)
    elif args.gaia:
        try:
            n = len(gaia.sources_for_view(config.VIEW_DIR / key, m))
            print(f"  Gaia DR3: {n} stars saved")
        except Exception as err:  # the overlay is optional; the view still works
            print(f"  Gaia DR3 not saved ({err}); it will be fetched live")
    print(f"{q}: {state['status']} in {time.time() - t0:.0f}s, key={key}, "
          f"frames={len(m.get('frames', []))}, diffs={len(m.get('diffs', []))}, "
          f"exposures used={m.get('n_exposures_used')}/{m.get('n_available')}")

if failed:
    print("FAILED: " + ", ".join(failed))
# Exit at once: background Gaia threads stuck on a slow catalogue service must not keep us alive.
# os._exit skips the normal flush, so flush first or piped output (e.g. into a log) is lost.
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if failed else 0)
