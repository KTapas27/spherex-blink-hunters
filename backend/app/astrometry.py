"""Position over time: flux-weighted centroid near a clicked position in each visit's stack.

A moving object's centroid drifts between visits; a fixed background star's does not. Comparing
detectors also reveals blends: e.g. WISE 0855 sits ~7" from a background star that dominates the
short-wavelength detectors, while the brown dwarf dominates D5/D6 and drifts west there.
"""
import json

import numpy as np
from astropy.coordinates import SkyCoord

from . import config
from .frames import grid_wcs

RADIUS_PX = 3.0
BKG_RING_PX = (6.0, 15.0)
# If more than this fraction of the centroid aperture is masked (a saturated, flagged core), the
# light centre is meaningless: it snaps to the edge of the hole. Such points are marked saturated.
MAX_MASKED_FRACTION = 0.15


def _centroid(stack, x0, y0):
    yy, xx = np.indices(stack.shape)
    r = np.hypot(xx - x0, yy - y0)
    ring = (r > BKG_RING_PX[0]) & (r < BKG_RING_PX[1]) & np.isfinite(stack)
    if ring.sum() < 10:
        return None
    inside = r <= RADIUS_PX
    if inside.sum() == 0:
        return None
    masked = float((~np.isfinite(stack[inside])).mean())
    w = np.where(inside & np.isfinite(stack), np.clip(stack - np.median(stack[ring]), 0, None), 0.0)
    if w.sum() <= 0:
        return None
    return float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum()), masked


def positions(view_dir, ra, dec):
    """Offsets (arcsec, +east/+north) of the centroid from (ra, dec), per detector and visit."""
    m = json.loads((view_dir / "manifest.json").read_text())
    t = m["target"]
    w, _ = grid_wcs(t["ra"], t["dec"], m["fov_deg"])
    x0, y0 = (float(v) for v in w.world_to_pixel(SkyCoord(ra, dec, unit="deg")))
    scale = config.PIXEL_SCALE_ARCSEC
    mid = {v["visit"]: v["mid_mjd"] for v in m["visits"]}
    out = []
    for det in range(1, 7):
        path = view_dir / f"stack_D{det}.npz"
        if not path.exists():
            continue
        with np.load(path) as stacks:
            for k in stacks.files:
                c = _centroid(stacks[k], x0, y0)
                if c is None:
                    continue
                visit = int(k[1:])
                # Grid x grows westward (RA decreasing), y grows north.
                out.append(dict(detector=det, visit=visit, mjd=mid[visit],
                                east_arcsec=round(-(c[0] - x0) * scale, 2),
                                north_arcsec=round((c[1] - y0) * scale, 2),
                                masked_fraction=round(c[2], 2),
                                saturated=c[2] > MAX_MASKED_FRACTION))
    return out
