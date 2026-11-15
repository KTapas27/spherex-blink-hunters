import json, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/backend")
import numpy as np
from astropy.table import Table
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
from app import config, archive, fetch
from requests.exceptions import HTTPError

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
tmp = Path(tempfile.mkdtemp()); config.SIA_DIR = tmp / "sia"; config.STAMP_DIR = tmp / "stamps"
archive.time.sleep = lambda s: None
ERR = HTTPError("502 Server Error: Proxy Error for url: https://irsa.ipac.caltech.edu/SIA?POS=...")
def table():
    rows = [dict(energy_bandpassname=f"SPHEREx-D{d}", cloud_access=json.dumps({"aws": {"bucket_name": "b", "key": f"k{i}{d}"}}),
                 obs_id=f"obs{i}", obs_collection="spherex_qr3", t_min=60900.0 + i * (100 if i > 2 else 1),
                 em_min=0.75e-6, em_max=1.1e-6, access_url="u") for i in range(5) for d in (1, 6)]
    return Table(rows=rows)
calls = []
def flaky(n_fail):
    def f(**kw):
        calls.append(1)
        if len(calls) <= n_fail: raise ERR
        return table()
    return f
RA, DEC = 133.76, -7.24218

archive.Irsa.query_sia = flaky(2); calls.clear()
ex = archive.find_exposures(RA, DEC)
ok(len(calls) == 3 and len(ex) == 10 and len({e.visit for e in ex}) == 3, f"two 502s then success -> retried ({len(calls)} calls), 10 exposures, 3 visits")

calls.clear(); archive.Irsa.query_sia = flaky(99)
ex2 = archive.find_exposures(RA, DEC)
ok(not calls and [e.key for e in ex2] == [e.key for e in ex], "second search (e.g. a 3' view) uses saved list: 0 IRSA calls")

f = archive._sia_cache_path(RA, DEC); d = json.loads(f.read_text()); d["fetched"] -= 13 * 3600; f.write_text(json.dumps(d))
calls.clear()
ex3 = archive.find_exposures(RA, DEC)
ok(len(calls) == config.SIA_RETRIES and len(ex3) == 10, f"list 13 h old + IRSA down -> {len(calls)} tries, then old list used")

calls.clear(); archive.Irsa.query_sia = flaky(0)
archive.find_exposures(RA, DEC)
ok(len(calls) == 1 and time.time() - json.loads(f.read_text())["fetched"] < 5, "list 13 h old + IRSA up -> refreshed (new data picked up)")

calls.clear(); archive.Irsa.query_sia = flaky(99)
try: archive.find_exposures(10.0, 10.0); ok(False, "raises")
except archive.ArchiveUnavailable as e:
    ok("IRSA" in str(e) and "502 Server Error: Proxy Error" in str(e) and "url" not in str(e), f"never-seen target + IRSA down -> friendly error:\n     {e}")

archive.Irsa.query_sia = lambda **kw: table()[:0]
try: archive.find_exposures(20.0, 20.0); ok(False, "raises")
except ValueError as e: ok("not observed" in str(e) and not archive._sia_cache_path(20.0, 20.0).exists(), "empty answer -> clear message, not cached")

# ---- stamp cropping == fresh small download
w = WCS(naxis=2); w.wcs.ctype = ["RA---TAN", "DEC--TAN"]; w.wcs.crval = [RA, DEC]; w.wcs.crpix = [1020.3, 1019.7]
w.wcs.cdelt = [-6.15 / 3600, 6.15 / 3600]; w.wcs.pc = [[0.94, -0.34], [0.34, 0.94]]
full = {k: np.random.default_rng(i).normal(size=(2040, 2040)).astype(np.float32) for i, k in enumerate(["image", "flags", "variance", "zodi", "wave"])}
def download(coord, half, wcs=w, n=2040):   # same window logic as _stamp_from_hdul(sliced=True)
    x, y = (float(v) for v in wcs.world_to_pixel(coord)); xi, yi = int(round(x)), int(round(y))
    y0, y1 = max(yi - half, 0), min(yi + half + 1, n); x0, x1 = max(xi - half, 0), min(xi + half + 1, n)
    out = {k: v[y0:y1, x0:x1] for k, v in full.items()}; out["header"] = np.array(wcs[y0:y1, x0:x1].to_header(relax=True).tostring()); return out
for name, coord in [("centre", SkyCoord(RA, DEC, unit="deg")),
                    ("detector edge", SkyCoord(*w.pixel_to_world_values(15.4, 1700.2), unit="deg"))]:
    big, small = download(coord, 50), download(coord, 30)
    crop = fetch._crop(big, coord, 30)
    same = all(np.array_equal(crop[k], small[k]) for k in full)
    wc, ws = WCS(fits_h := __import__("astropy.io.fits", fromlist=["Header"]).Header.fromstring(str(crop["header"]))), WCS(fits_h.__class__.fromstring(str(small["header"])))
    ok(same and np.allclose(wc.wcs.crpix, ws.wcs.crpix), f"crop of 6'-size stamp == fresh 3' download ({name}, shape {crop['image'].shape})")

# ---- get_stamp picks the cached larger stamp, no network
class E: key = "obsX_D3"; s3_path = "s3://x"; access_url = "u"
coord = SkyCoord(RA, DEC, unit="deg"); config.STAMP_DIR.mkdir(parents=True)
np.savez_compressed(fetch.stamp_path(E, RA, DEC, 50), **download(coord, 50))
np.savez_compressed(fetch.stamp_path(E, RA, DEC, 80), **download(coord, 80))
fetch._fetch_s3 = fetch._fetch_cutout = lambda *a: (_ for _ in ()).throw(AssertionError("network used"))
st = fetch.get_stamp(E, RA, DEC, 30)
ok(st["image"].shape == (61, 61) and fetch.stamp_path(E, RA, DEC, 30).exists() and fetch._larger_cached(E, RA, DEC, 30).name.endswith("_50.npz"),
   "3' stamp built from cached 6' stamp (smallest larger one), saved, no download")
np.savez_compressed(fetch.stamp_path(E, RA, DEC, 90))   # off-detector marker (empty file)
ok(fetch.get_stamp(E, RA, DEC, 85) is None, "off-detector large stamp -> small one is off-detector too")
print("all tests passed")
