import json, sys, tempfile, time, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/backend")
import numpy as np
from astropy.table import Table
from app import gaia, astrometry, frames, config, pipeline

ok = lambda c, msg: print(("PASS " if c else "FAIL ") + msg) or (c or sys.exit(1))

def table(n=3):
    return Table(dict(source_id=np.arange(n), ra=269.446 + np.arange(n) * 1e-3, dec=4.768 + np.zeros(n),
                      pmra=[-801.6] + [1.0] * (n - 1), pmdec=[10362.4] + [1.0] * (n - 1),
                      parallax=[547.0] + [1.0] * (n - 1), phot_g_mean_mag=[8.19] + [12.0] * (n - 1)))

# --- Gaia race (DR3 services only; MAST DR2 is the last resort, covered in test_gaia_release.py)
gaia._from_mast_dr2 = lambda c, r: (_ for _ in ()).throw(ConnectionError("mast down"))
gaia.DR3_SERVICES = {"IRSA": lambda c, r: (time.sleep(5), table())[1], "ESA": lambda c, r: table(2)}
t0 = time.time(); tab, ep, rel = gaia._query(None, None)
ok(len(tab) == 2 and time.time() - t0 < 1 and rel == "Gaia DR3 (ESA)", f"fast DR3 answer used while IRSA is slow ({time.time()-t0:.2f}s)")
def boom(c, r): raise ConnectionError("down")
gaia.DR3_SERVICES = {"IRSA": boom, "VizieR": lambda c, r: table(4)}
ok(len(gaia._query(None, None)[0]) == 4, "IRSA down -> VizieR result used")
gaia.DR3_SERVICES = {"IRSA": boom}
try: gaia._query(None, None); ok(False, "all down raises")
except RuntimeError as e: ok("IRSA" in str(e) and "MAST" in str(e), f"all down -> RuntimeError: {e}")
gaia.QUERY_TIMEOUT_S = 1; gaia.MAST_TIMEOUT_S = 1
gaia.DR3_SERVICES = {"IRSA": lambda c, r: (time.sleep(3), table())[1]}
try: gaia._query(None, None); ok(False, "timeout raises")
except RuntimeError as e: ok("no answer" in str(e), f"nobody answers in time -> {e}")
gaia.QUERY_TIMEOUT_S = 75

# --- sources_for_view: concurrent prefetch + click query only once, output + cache
calls = []
def counted(c, r): calls.append(1); time.sleep(0.5); return table(3)
gaia.DR3_SERVICES = {'IRSA': counted, 'ESA': counted}
d = Path(tempfile.mkdtemp()); manifest = dict(target=dict(ra=269.446, dec=4.768), fov_deg=0.1)
gaia.prefetch(d, manifest)
time.sleep(0.05)
res = gaia.sources_for_view(d, manifest)
time.sleep(0.6)
ok(len(calls) == 2 and (d / "gaia.json").exists(), f"prefetch + click share one query round (calls={len(calls)}: both DR3 services once)")
fast = [s for s in res if s["fast"]]
ok(len(fast) == 1 and abs(fast[0]["pm"] - 10393.4) < 1 and fast[0]["dy_per_yr"] > 1.6, f"Barnard flagged fast, pm={fast[0]['pm']}, dy/yr={fast[0]['dy_per_yr']:.2f} px")
calls.clear(); gaia.sources_for_view(d, manifest); ok(not calls, "second request served from cache")

# --- astrometry: saturated hole vs normal star
n = 59; yy, xx = np.indices((n, n)); c = n // 2
def star(cx, cy, amp=100.0): return amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.2 ** 2))
normal = star(c + 0.4, c - 0.3) + np.random.default_rng(1).normal(0, 0.05, (n, n))
x, y, m = astrometry._centroid(normal, c, c)
ok(abs(x - (c + 0.4)) < 0.15 and abs(y - (c - 0.3)) < 0.15 and m == 0, f"normal star centroid ({x - c:+.2f}, {y - c:+.2f}) px, masked {m}")
sat = star(c, c, 5000.0); sat[np.hypot(xx - c, yy - c) <= 1.6] = np.nan
x, y, m = astrometry._centroid(sat, c, c)
ok(m > astrometry.MAX_MASKED_FRACTION, f"saturated core detected: masked fraction {m:.2f} > {astrometry.MAX_MASKED_FRACTION}")

# --- positions(): end to end on a fake view
vd = Path(tempfile.mkdtemp())
w, shape = frames.grid_wcs(269.446, 4.768, 0.1)
(vd / "manifest.json").write_text(json.dumps(dict(target=dict(ra=269.446, dec=4.768), fov_deg=0.1,
    visits=[dict(visit=0, mid_mjd=60900.0), dict(visit=1, mid_mjd=61100.0)])))
np.savez(vd / "stack_D1.npz", v0=sat, v1=sat)
np.savez(vd / "stack_D6.npz", v0=normal, v1=normal)
pts = astrometry.positions(vd, 269.446, 4.768)
ok({p["detector"]: p["saturated"] for p in pts} == {1: True, 6: False} and all("masked_fraction" in p for p in pts),
   "positions(): D1 marked saturated, D6 kept")
print("all tests passed")
