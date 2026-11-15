import runpy, sys, json
repo = sys.argv[1]; sys.path.insert(0, repo + "/backend")
from app import pipeline, gaia
jobs = {}
def start_view(q, fov, per_group):
    jobs[q] = {"status": "error", "message": "IRSA 502"} if q == "bad" else {"status": "done", "message": "Ready", "manifest": {"frames": [1, 2], "diffs": [1]}}
    return q
pipeline.start_view = start_view; pipeline.job = lambda k: jobs[k]
gaia.sources_for_view = lambda d, m: [1, 2, 3]
for argv in (["precache.py", "good", "--gaia"], ["precache.py", "good", "bad", "--gaia"]):
    sys.argv = argv
    import os; os._exit = lambda c: (_ for _ in ()).throw(SystemExit(c))
    try: runpy.run_path(repo + "/scripts/precache.py", run_name="__main__"); code = 0
    except SystemExit as e: code = e.code
    print(f"--> {argv[1:]} exit code {code}")
