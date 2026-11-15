"""Settings that change with SPHEREx data releases live here, in one place."""
import os
from pathlib import Path

# IRSA SIA collections, newest first. When a new release lands (DR2, QR4...),
# add it here; nothing else needs to change.
COLLECTIONS = ["spherex_dr1", "spherex_qr3"]

# Native SPHEREx pixel scale (arcsec/pixel).
PIXEL_SCALE_ARCSEC = 6.15

# Wavelength coverage of the six detectors (microns), from the IRSA intro tutorial.
DETECTOR_BANDS = {
    1: (0.75, 1.09),
    2: (1.10, 1.62),
    3: (1.63, 2.41),
    4: (2.42, 3.82),
    5: (3.83, 4.41),
    6: (4.42, 5.00),
}

# Wavelength-matched blinking: each detector is split into this many channels, equal in
# log-wavelength (SPHEREx defines 17 per detector = 102 in total). Only exposures in the
# same channel are blinked against each other, so colour changes aren't mistaken for motion.
CHANNELS_PER_DETECTOR = 17

# Bump when the frame/manifest format changes so cached views are rebuilt (stamps are reused).
VIEW_VERSION = 3  # 3: colour composite + per-visit weights for add/subtract

# Exposures closer together than this belong to the same "visit" of the sky.
VISIT_GAP_DAYS = 30

# FLAGS bits that make a pixel unusable. SOURCE (21), FULLSAMPLE (12) and
# OVERFLOW (1, coincident with SUR_ERROR) are informational, so they are kept,
# following the IRSA Source Discovery Tool tutorial.
BAD_FLAG_BITS = (0, 2, 4, 5, 6, 7, 9, 10, 11, 14, 15, 17, 19)
BAD_FLAG_MASK = sum(1 << b for b in BAD_FLAG_BITS)

# Network behaviour.
FETCH_WORKERS = 16
FETCH_RETRIES = 3
S3_FSSPEC_KWARGS = {"anon": True, "default_block_size": 2**18, "default_cache_type": "bytes"}
CUTOUT_BASE = "https://irsa.ipac.caltech.edu/"
REMOTE_TIMEOUT_S = 120

# Name resolver (CDS Sesame; follows redirects to mirrors when Strasbourg is down).
SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?"

# Reference epoch the view grid is centred on (positions are moved here using proper motion).
VIEW_EPOCH = "2026-01-01"

ROOT = Path(__file__).resolve().parents[2]
# BLINK_CACHE_DIR lets a deployment (e.g. Cloud Run) put the cache somewhere else.
CACHE_DIR = Path(os.environ.get("BLINK_CACHE_DIR", ROOT / "cache"))
STAMP_DIR = CACHE_DIR / "stamps"
VIEW_DIR = CACHE_DIR / "views"
SIA_DIR = CACHE_DIR / "sia"  # exposure lists per position, so a new field of view needs no new search

# Exposure-list cache: re-search IRSA after this many hours (new SPHEREx data arrives weekly);
# if IRSA is down, an older list is used instead of failing.
SIA_CACHE_HOURS = 12
SIA_RETRIES = 4  # attempts per search; waits 2, 5, 10 s between them
FRONTEND_DIR = ROOT / "frontend"
