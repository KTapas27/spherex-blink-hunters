import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/backend")
import numpy as np
from PIL import Image
from astropy.wcs import WCS
from app import frames, combine, astrometry, config

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
RA, DEC, FOV = 150.0, 10.0, 41 * 6.15 / 3600
rng = np.random.default_rng(3)
n = 41
w = WCS(naxis=2); w.wcs.ctype = ["RA---TAN", "DEC--TAN"]; w.wcs.crval = [RA, DEC]; w.wcs.crpix = [(n+1)/2, (n+1)/2]
w.wcs.cdelt = [-6.15/3600, 6.15/3600]
hdr = np.array(w.to_header().tostring())
yy, xx = np.indices((n, n))
def blob(x, y, a): return a * np.exp(-((xx-x)**2 + (yy-y)**2) / (2*1.1**2))
BLUE = (10, 30)    # bright at short wavelengths
RED = (30, 30)     # brown dwarf: bright only at D5/D6
FIXED = (20, 10)   # grey reference star
def scene(det, visit):
    blue_amp = {1: 80, 2: 60, 3: 30, 4: 12, 5: 6, 6: 4}[det]
    red_amp = {1: 0.5, 2: 1, 3: 3, 4: 10, 5: 50, 6: 70}[det]
    mover = (16 + 3 * visit, 24)  # moves 3 px per visit
    img = blob(*BLUE, blue_amp) + blob(*RED, red_amp) + blob(*FIXED, 30) + blob(*mover, 40)
    return img
class Exp:
    def __init__(s, i, det, visit): s.key = f"e{i}_D{det}"; s.detector = det; s.visit = visit; s.mjd = 60900 + 180*visit + i*0.01; s.collection = "spherex_qr3"
exps, stamps = [], {}
i = 0
for visit in range(3):
    for det in range(1, 7):
        for rep in range(2 if visit != 1 else 4):   # visit 2 (index 1) has twice the exposures
            e = Exp(i, det, visit); i += 1; exps.append(e)
            lo, hi = config.DETECTOR_BANDS[det]
            stamps[e.key] = dict(image=(scene(det, visit) + rng.normal(0, 1.0, (n, n))).astype(np.float32),
                                 zodi=np.zeros((n, n), np.float32), variance=np.ones((n, n), np.float32),
                                 flags=np.zeros((n, n), np.int32), wave=np.full((n, n), (lo*hi)**0.5, np.float32), header=hdr)
class T:
    ra, dec = RA, DEC
    def as_dict(s): return dict(ra=RA, dec=DEC)
visits = [dict(visit=v, start=f"2026-0{v+1}-01", end=f"2026-0{v+1}-20", mid_mjd=60900+180*v, n=1) for v in range(3)]
vd = Path(tempfile.mkdtemp())
m = frames.build_frames(vd, T(), exps, stamps, FOV, visits)

rgbf = [f for f in m["frames"] if f["group"] == "rgb"]
ok(len(rgbf) == 3 and m["frames"][0]["group"] == "rgb" and m["groups"]["rgb"]["kind"] == "rgb",
   f"colour composite: 3 RGB frames, listed first, groups={sorted(m['groups'])[:4]}...")
img = np.flipud(np.asarray(Image.open(vd / "RGB_v0.png")).astype(int))   # back to FITS orientation
px = lambda xy: img[xy[1], xy[0]]
r_, b_ = px(RED), px(BLUE)
ok(r_[0] > 1.5 * r_[2] and r_[0] > r_[1], f"brown dwarf comes out red  RGB={tuple(r_)}")
ok(b_[2] > b_[0], f"hot star comes out blue-white  RGB={tuple(b_)}")
ok(Image.open(vd / "RGB_v0.png").mode == "RGB" and (vd / "mask_RGB_v0.png").exists(), "RGB PNG + flag mask written")

key = m["key"] if "key" in m else None
m["key"] = "x"
# --- combine: difference against visit 2 (not visit 1)
r = combine.combine(vd, m, "6", plus=[0], minus=[1])
d = np.flipud(np.asarray(Image.open(vd / r["file"])).astype(int))
old_pos, new_pos = (16 + 3*0, 24), (16 + 3*1, 24)
ok(d[old_pos[1], old_pos[0]] > 200 and d[new_pos[1], new_pos[0]] < 55 and abs(d[FIXED[1], FIXED[0]] - 128) < 25,
   f"Visit 1 − Visit 2: mover bright where it was ({d[old_pos[1], old_pos[0]]}), dark where it went ({d[new_pos[1], new_pos[0]]}), fixed star cancels ({d[FIXED[1], FIXED[0]]})")
ok(r["label"] == "Visit 1 − Visit 2" and r["kind"] == "difference", f"label: {r['label']}")

# --- previous-visit difference visit3 - visit2
r = combine.combine(vd, m, "all", plus=[2], minus=[1]); ok(r["label"] == "Visit 3 − Visit 2", f"consecutive difference: {r['label']}")
# --- each visit vs mean of others
r = combine.combine(vd, m, "6", plus=[1], minus=[0, 2]); ok(r["label"] == "Visit 2 − Visits 1+3", f"vs others: {r['label']}")

# --- deep stack is less noisy, weights honoured
st, wt = combine._load(vd, "D6")
single = st["v0"]; deep = combine._weighted_mean(st, wt, [0, 1, 2], lambda v: f"v{v}")
corner = (slice(0, 6), slice(30, 41))
ok(np.nanstd(deep[corner]) < 0.75 * np.nanstd(single[corner]), f"deep stack of 3 visits: noise {np.nanstd(deep[corner]):.3f} vs single visit {np.nanstd(single[corner]):.3f}")
ok(np.allclose(np.nanmedian(wt["v1"]) / np.nanmedian(wt["v0"]), 2, rtol=0.05), "visit with 2x exposures gets 2x weight")
manual = (st["v0"]*wt["v0"] + st["v2"]*wt["v2"]) / (wt["v0"] + wt["v2"])
ok(np.allclose(combine._weighted_mean(st, wt, [0, 2], lambda v: f"v{v}"), manual, equal_nan=True), "weighted mean matches hand calculation")
r = combine.combine(vd, m, "all", plus=[0, 1, 2]); ok(r["label"] == "Visits 1+2+3 added" and r["kind"] == "stack", f"stack label: {r['label']}")

# --- colour combine: deep colour + colour difference
r = combine.combine(vd, m, "rgb", plus=[0, 1, 2]); ok(Image.open(vd / r["file"]).mode == "RGB", "deep colour stack renders")
r = combine.combine(vd, m, "rgb", plus=[2], minus=[0]); c = np.flipud(np.asarray(Image.open(vd / r["file"])).astype(int))
ok(abs(c[FIXED[1], FIXED[0]] - 128).max() < 30 and c[24, 22].mean() > 170, f"colour difference: fixed star grey {tuple(c[FIXED[1], FIXED[0]])}, mover's new spot bright {tuple(c[24, 22])}")

# --- cache + errors
mt = (vd / r["file"]).stat().st_mtime_ns; combine.combine(vd, m, "rgb", plus=[2], minus=[0]); ok((vd / r["file"]).stat().st_mtime_ns == mt, "second request served from cached PNG")
for args, want in [(dict(group="6", plus=[0], minus=[0]), "both"), (dict(group="6", plus=[0], minus=[7]), "no data"),
                   (dict(group="zz", plus=[0]), "No frames"), (dict(group="6", plus=[]), "at least one")]:
    try: combine.combine(vd, m, **args); ok(False, str(args))
    except combine.CombineError as e: ok(want in str(e), f"rejects {args}: {e}")

# --- astrometry unaffected by the new weight files
(vd / "manifest.json").write_text(json.dumps(m))
pts = astrometry.positions(vd, RA, DEC)
ok(len(pts) > 0 and all(isinstance(p["visit"], int) for p in pts), f"positions() still works ({len(pts)} points)")
print("all tests passed")
