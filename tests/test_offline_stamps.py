"""IRSA search down + no saved exposure list -> rebuild the list from stamps already on disk.

Run: python tests/test_offline_stamps.py <repo>
"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/backend")
import numpy as np
from astropy.io import fits
from app import config, archive

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
tmp = Path(tempfile.mkdtemp())
config.SIA_DIR, config.STAMP_DIR, config.VIEW_DIR = tmp / "sia", tmp / "stamps", tmp / "views"
config.STAMP_DIR.mkdir(parents=True)
archive.time.sleep = lambda s: None
calls = []
def down(*a, **k):
    calls.append(1)
    raise RuntimeError("502 Server Error: Proxy Error for url: https://irsa.ipac.caltech.edu/SIA?POS=...")
archive.Irsa.query_sia = down

ra, dec = 269.45, 4.69
def stamp(key, mjd, half=50, empty=False, r=ra, d=dec):
    path = config.STAMP_DIR / f"{key}_{r:.5f}_{d:.5f}_{half}.npz"
    if empty:
        np.savez_compressed(path)
        return
    h = fits.Header(); h["MJD-AVG"] = mjd
    np.savez_compressed(path, image=np.zeros((3, 3)), header=np.array(h.tostring()))

stamp("2025W19_1B_0116_1_D3", 60800.7)
stamp("2025W19_1B_0116_1_D3", 60800.7, half=25)          # same exposure, smaller stamp: counted once
stamp("2025W45_2A_0007_2_D6", 60990.1)
stamp("2026W18_2A_0424_2_D1", 61162.3)
stamp("2025W20_1C_0001_1_D2", 60805.0, empty=True)       # off-detector: skipped
stamp("2025W20_1C_0002_1_D2", 60805.0, r=10.0, d=20.0)  # another position: ignored
(config.VIEW_DIR / "v").mkdir(parents=True)
(config.VIEW_DIR / "v" / "manifest.json").write_text(json.dumps(
    {"exposures": [{"key": "2025W45_2A_0007_2_D6", "collection": "spherex_qr3"}]}))

exps = archive.find_exposures(ra, dec)
ok(len(calls) == config.SIA_RETRIES, f"IRSA tried {len(calls)} times first")
ok([e.key for e in exps] == ["2025W19_1B_0116_1_D3", "2025W45_2A_0007_2_D6", "2026W18_2A_0424_2_D1"],
   f"3 exposures from disk, sorted by time: {[e.key for e in exps]}")
ok([e.visit for e in exps] == [0, 1, 2], "visits assigned (gaps > 30 days)")
ok(exps[1].collection == "spherex_qr3" and exps[0].collection == config.COLLECTIONS[0],
   "release taken from built views when known")
ok(exps[0].obs_id == "2025W19_1B_0116_1" and exps[0].detector == 3 and exps[0].wl_min == 1.63,
   "obs_id, detector and band parsed")
ok(not any(config.SIA_DIR.glob("*.json")), "offline list not saved as if it were an IRSA answer")

try:
    archive.find_exposures(1.0, 2.0)
    ok(False, "nothing on disk should still fail")
except archive.ArchiveUnavailable as err:
    ok("IRSA" in str(err), "nothing on disk -> friendly IRSA error as before")
