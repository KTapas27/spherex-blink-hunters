"""On-the-fly spectrum: aperture photometry at one sky position in every cached stamp."""
import numpy as np
from astropy.coordinates import SkyCoord
from photutils.aperture import CircularAnnulus, CircularAperture, ApertureStats, aperture_photometry

from . import config
from .frames import channel_of, clean, fill_nans, stamp_wcs

# Nominal pixel solid angle in steradians. The SPHEREx solid-angle pixel maps
# (SAPM, on S3 under dr1/solid_angle_pixel_map) give the exact per-pixel value.
PIX_SR = (config.PIXEL_SCALE_ARCSEC / 206264.806) ** 2

# Allow a few flagged pixels (cosmic rays etc.) inside the aperture; they are filled
# from neighbours. Above this the measurement is dropped (saturated stars).
MAX_BAD_FRACTION = 0.2


def measure(stamps, exposures, ra, dec, r_ap=2.0, r_in=4.0, r_out=7.0):
    """Return (points sorted by wavelength, number of exposures skipped for flagged pixels)."""
    coord = SkyCoord(ra, dec, unit="deg")
    points, n_skipped = [], 0
    for exp in exposures:
        stamp = stamps.get(exp.key)
        if stamp is None:
            continue
        img, var = clean(stamp)
        x, y = (float(v) for v in stamp_wcs(stamp).world_to_pixel(coord))
        ny, nx = img.shape
        if not (r_out <= x < nx - r_out and r_out <= y < ny - r_out):
            continue
        ap = CircularAperture((x, y), r=r_ap)
        ap_mask = ap.to_mask()
        inside = ap_mask.cutout(img)
        weights = ap_mask.data > 0
        if inside is None or np.mean(~np.isfinite(inside[weights])) > MAX_BAD_FRACTION:
            n_skipped += 1
            continue  # too many flagged pixels (e.g. a saturated bright star)
        bkg = ApertureStats(img, CircularAnnulus((x, y), r_in, r_out)).median
        phot = aperture_photometry(np.nan_to_num(fill_nans(img) - bkg), ap,
                                   error=np.sqrt(np.nan_to_num(var, nan=0.0)))
        mjy_per_unit = PIX_SR * 1e9  # MJy/sr * sr -> MJy, then -> mJy
        wl = float(stamp["wave"][int(round(y)), int(round(x))])
        points.append(dict(
            key=exp.key, mjd=exp.mjd, visit=exp.visit, detector=exp.detector,
            wavelength_um=round(wl, 4), channel=channel_of(exp.detector, wl),
            flux_mjy=float(phot["aperture_sum"][0]) * mjy_per_unit,
            err_mjy=float(phot["aperture_sum_err"][0]) * mjy_per_unit,
        ))
    return sorted(points, key=lambda p: p["wavelength_um"]), n_skipped
