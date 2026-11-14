import sys, time, tempfile, json
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/backend")
import numpy as np
from astropy.table import Table
from app import gaia
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
def tab():
    return Table(dict(source_id=[1, 2], ra=[269.4521, 269.46], dec=[4.6934, 4.70], pmra=[-801.6, 1.0], pmdec=[10362.4, 1.0], parallax=[547.0, 1.0], phot_g_mean_mag=[8.19, 12.0]))
def boom(c, r): raise ConnectionError("down")
slow = lambda c, r: (time.sleep(3), tab())[1]
calls = []
def mast(c, r): calls.append("MAST"); return tab()

gaia.DR3_SERVICES = {"IRSA": slow, "ESA": lambda c, r: tab(), "VizieR": boom}; gaia._from_mast_dr2 = mast
t, ep, rel = gaia._query(None, None)
ok(ep == 2016.0 and rel == "Gaia DR3 (ESA)" and not calls, f"fastest DR3 service wins ({rel}); MAST not asked")
gaia.DR3_SERVICES = {"IRSA": boom, "ESA": boom, "VizieR": boom}
t, ep, rel = gaia._query(None, None)
ok(ep == 2015.5 and rel == "Gaia DR2 (MAST)" and calls == ["MAST"], f"all DR3 down -> {rel}, epoch {ep}")
gaia._from_mast_dr2 = boom
try: gaia._query(None, None); ok(False, "raises")
except RuntimeError as e: ok("IRSA" in str(e) and "MAST" in str(e), f"everything down -> {str(e)[:90]}...")
gaia.QUERY_TIMEOUT_S = 1; gaia.DR3_SERVICES = {"IRSA": slow}; gaia._from_mast_dr2 = mast
t, ep, rel = gaia._query(None, None); ok(rel == "Gaia DR2 (MAST)", "DR3 too slow -> MAST after timeout")

# epoch handling: same star, DR2 vs DR3 epoch -> 0.5 yr of motion difference (~5.2 arcsec for Barnard)
m = dict(target=dict(ra=269.44627, dec=4.76820), fov_deg=0.1)
out = {}
for name, epoch in (("dr3", 2016.0), ("dr2", 2015.5)):
    gaia._query = lambda c, r, e=epoch: (tab(), e, f"x{e}")
    d = Path(tempfile.mkdtemp()); out[name] = gaia._build(d, m, d / "gaia.json")
b3, b2 = out["dr3"][0], out["dr2"][0]
shift = np.hypot(b3["x"] - b2["x"], b3["y"] - b2["y"]) * 6.15
ok(abs(shift - 0.5 * 10.393) < 0.3 and b3["release"] == "x2016.0", f"epoch honoured: DR2 vs DR3 start date moves Barnard's Star by {shift:.1f} arcsec (expected 5.2)")
print("all tests passed")
