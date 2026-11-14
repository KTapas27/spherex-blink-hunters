# SPHEREx briefing: what we know (verified on 2026-11-14)

## The mission
- NASA SPHEREx, launched March 2025, survey since May 2025. Maps the whole sky about every 6 months.
- 0.75–5.0 µm with **6 detectors**, 2040×2040 px each, **6.15″/pixel**:

| Det | λ (µm) | R |
|---|---|---|
| D1 | 0.75–1.09 | 39 |
| D2 | 1.10–1.62 | 41 |
| D3 | 1.63–2.41 | 41 |
| D4 | 2.42–3.82 | 35 |
| D5 | 3.83–4.41 | 112 |
| D6 | 4.42–5.00 | 128 |

- **Linear variable filters:** wavelength changes smoothly across each detector, so every exposure
  sees a given star at a slightly different wavelength. "102 bands" = 17 channels × 6 detectors,
  built up over many exposures. Never ask for "band 47"; read each pixel's wavelength from `WCS-WAVE`.

## Data products (Level 2 spectral image, one FITS file per exposure per detector)

| HDU | Content |
|---|---|
| IMAGE | surface brightness, MJy/sr, **zodiacal light NOT subtracted** |
| FLAGS | bitmask (bits: 0 TRANSIENT, 1 OVERFLOW, 2 SUR_ERROR, 4 PHANTOM, 5 REFERENCE, 6 NONFUNC, 7 DICHROIC, 9 MISSING, 10 HOT, 11 COLD, 12 FULLSAMPLE, 14 PHANMISS, 15 NONLINEAR, 17 PERSIST, 19 OUTLIER, 21 SOURCE) |
| VARIANCE | (MJy/sr)² |
| ZODI | zodiacal light model, subtract it yourself |
| PSF (EPSF in newer files) | 101×101×121 cube, ~4–5 MB. We don't need it, but cutouts always include it |
| WCS-WAVE | lookup table: pixel → wavelength, bandwidth (use `WCS(header, fobj=hdul, key="W")`, then set `.sip = None`) |

Good pixels (per IRSA): flags of 0, OVERFLOW only, or SOURCE only. We drop the bits listed in `config.BAD_FLAG_BITS`.

## Releases & access (as of Nov 2026)
- **DR1 (Nov 2026)** + **QR3** supersede QR2. SIA collections: `spherex_dr1`, `spherex_qr3`
  (+ `_deep` variants and old `spherex_qr2`). List: `Irsa.list_collections(servicetype='SIA', filter='spherex')`.
- SIA results include `cloud_access` → public S3 bucket `nasa-irsa-spherex` (anonymous).
- TAP tables `spherex.artifact` ⋈ `spherex.plane` give immediate access to new weekly data (SIA lags ~1 day).
- Cutout service: append `?center=RA,DECd&size=DEG` to a file URL. It does **not** support range
  requests, so every cutout costs the full PSF cube.
- Solid-angle pixel maps (exact MJy/sr → Jy conversion): S3 `dr1/solid_angle_pixel_map/cal-sapm-v3-2026-191/{1..6}/`.
- IRSA's Mosaic tool (102-plane cubes) has **no API**, so it's not usable from the app.

## Measured on this Mac (M1, ~20 Mbps home internet, India)
- CPU and RAM are not a problem (peak < 1 GB). The network is the bottleneck.
- Cutout service: ~4–5 MB, 9–16 s each. **S3 partial read with 256 KB blocks: ~6 s, ~4× less data.**
  Default fsspec 5 MB blocks are slower than the cutout service, so the block size matters.
- Most of the 6 s is round trips to us-east-1. A server hosted in the US should be near-instant.
- A 36-stamp view builds in ~45 s; rebuilding from cached stamps takes ~5 s.

## Test targets (DR1 + QR3 coverage, positions moved to 2026.0)

| Target | pm (″/yr) | moved since J2000 | images | visits |
|---|---|---|---|---|
| Barnard's Star | 10.39 | 270″ (44 px) | 358 | 3 (2025-08, 2026-03, 2026-08) |
| Epsilon Indi B | 4.68 | 122″ (20 px) | 458 | 4 (2025-04, 2025-09, 2026-04, 2026-09) |
| WISE 0855 | 8.15 | 212″ (34 px) | 258 | 3 (2025-05, 2025-10, 2026-04) |
| RW Aurigae | 0.02 | 0.6″ | 335 | 3 |
| R Draconis | 0.02 | 0.6″ | 539 | 3 |

- **Catalogue (J2000) positions of fast stars are minutes of arc off. Always move them with proper motion.**
  The challenge's WISE 0855 coordinates (08h55m10.831s) are an older-epoch position; it is now ~1.6′ west of them.
- Barnard's Star saturates (core flagged in 35 of 36 exposures), so use a field star for spectra; difference mode shows its motion clearly in D5/D6.
- **WISE 0855 is detected, but only at 4–5 µm, and blended** (all 258 exposures, checked 2026-11-14):
  - A Gaia G = 16.3 background star lies 6.8″ (~1 pixel) from WISE 0855's 2026 position. It dominates D1–D4,
    where the light centre stays fixed at about (+5.6″ W, +3.6″ N) in every visit.
  - In D5/D6 the light centre drifts west: D6 −2.5″ → −0.3″ → +2.6″ (west), D5 −1.5″ → +1.8″ → +4.0″ between
    2025-05 and 2026-04. That's WISE 0855's motion (8.1″/yr), diluted to ~5″/yr by the blend.
  - The spectrum at that spot falls from 1 to 3.5 µm (the star), then rises sharply at 4–5 µm (WISE 0855's peak).
  - With only 6 exposures/visit it was not visible, so use `--per-group 0` (all exposures) for this target.
- Epsilon Indi B: methane absorption (≈1.6, 2.2, 3.3 µm) should show in its spectrum.
- **RW Aur varies strongly (measured 2026-11-14, median aperture flux per detector):** D2 252 → 405 → 538 mJy
  (brightening) while D6 2739 → 2012 → 1429 mJy (fading) across visits 1→3. That's a colour change typical of a
  young star with a variable dusty disk. D4 is saturated. Great demo material for a light-curve feature.
- **R Dra is saturated in all 105 exposures**, so aperture photometry can't measure it. Show its variability
  through the blink images instead, or measure flux in the PSF wings (stretch goal).

## External services and their reliability today
- **IRSA**: reliable (SIA, cutouts, Gaia DR3 cone search in ~7 s).
- **CDS (Sesame, VizieR, Aladin HiPS)**: degraded. Sesame redirects to a South-African mirror and is sometimes slow,
  VizieR returned 404, and the browser couldn't resolve one CDS host. The app therefore has built-in values for the 5
  test targets, caches every resolved name, and draws Gaia itself instead of relying on Aladin.
- **ESA Gaia archive**: timed out, so we use IRSA's copy (`gaia_dr3_source`, indexed cone search; ADQL CONTAINS on
  that table is very slow).
- SIMBAD TAP returned 404.

## Useful links
- IRSA SPHEREx: https://irsa.ipac.caltech.edu/Missions/spherex.html
- Tutorials: https://caltech-ipac.github.io/irsa-tutorials/spherex/
- WiseView (UI model): http://byw.tools/wiseview
- Gaia via IRSA: `Irsa.query_region(coord, catalog="gaia_dr3_source", spatial="Cone", radius=...)`
