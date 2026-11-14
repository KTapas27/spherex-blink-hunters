# Challenge resources: what each one gives us (read 2026-11-14)

Source: the challenge Resources tab. Each item was opened and, where possible, tested from this project's venv.

## NASA

### 1. IRSA SPHEREx page — <https://irsa.ipac.caltech.edu/Missions/spherex.html>
- **Releases:** QR1 (Jul 2025), QR2 (Oct 2025), QR3 (Sep 2026), **DR1 (Nov 2026)**. DR1 = reprocessed QR2;
  IRSA says use **DR1 + QR3 together** as one uniform set (that's what `config.COLLECTIONS` does).
- **Required acknowledgement** (put on the project page and the app's About):
  > "This publication makes use of data products from the Spectro-Photometer for the History of the Universe,
  > Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory
  > and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration."
  DOIs: DR1 spectral images 10.26131/IRSA678, Spectral All-Sky Cube 10.26131/IRSA679.
- **DR1 Spectral All-Sky Cube**: whole sky in all 102 channels (deep, time-combined). Via SIA/astroquery.
- **SPHEREx HiPS all-sky cube hosted by IRSA**: `https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube`
  (102 layers, frame = 17×(band−1) + (channel−1), frames 50–51 blank). FITS tiles at order 5 under
  `https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir{d}/Npix{n}_cube.fits`.
  Mosaic striping near Paα 1.88, PAH 3.3, Brα 4.05 µm is an artefact.
- **Moving Object Search Tool (MOST)** supports `catalog=spherex`. Tested: **4 Vesta → 319 SPHEREx DR1 images in
  7 s**, each with predicted `ra_obj/dec_obj`, `vmag`, `mjd_start`, `uri`. astroquery's wrapper is out of date
  (sends `nafid_input`); POST directly to `https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most` with
  `catalog, input_type=name_input|naifid_input, obj_name|obj_naifid, obj_type, obs_begin, obs_end, ephem_step,
  output_mode=Brief` and parse with `Table.read(..., format="ascii.ipac")`. Ambiguous names (e.g. "Vesta") need the
  NAIF ID (Vesta = 20000004). Example output: `explore/data/most_vesta.txt`.
- **Comet 3I/ATLAS** (interstellar comet): SPHEREx saw it Aug and Dec 2025. Ready-made table of **259 images with
  the comet's predicted `comet_ra/comet_dec`** per image: `explore/data/obscore_3I_Atlas.vot` (QR2 paths). It's
  extended at SPHEREx resolution, so don't use point-source photometry on it. Strong water-ice/CO₂ results (Lisse et al.).
- **Spectral calibrations**: official channel maps (pixel → channel at 17/34/51/68 sub-channels) and response curves
  (tar). Would replace our approximate log-spaced channels.
- **Data Explorer deep links**: `https://irsa.ipac.caltech.edu/applications/spherex/?api=spectral-images&ra=RA&dec=DEC&sr=30s&execute=true`
- Other tools: Spectrophotometry Tool (forced photometry, official spectra, GUI), Mosaic Tool (no API), Cutout Tool,
  Source Discovery Tool, SPLICES ice-source catalogue. IRSA banner today: "Some object lookup services are unavailable".

### 2. IRSA tutorial notebooks — <https://caltech-ipac.github.io/irsa-tutorials/spherex/>
Intro, Cutouts (run: `tutorials/`), PSF, Source Discovery Tool (S3 access, flux units via solid-angle maps, good-flag
logic), Mosaic cubes, HiPS cubes. Their key lessons are already in the app and in BRIEFING.md.

### 3. WiseView — <http://byw.tools/wiseview>
The model tool. Defaults to WISE 0855. Features worth copying:
- **W1+W2 colour composite** (red = long, blue = short, green = mean). For us: red = D5/D6, blue = D1/D2, so cold
  brown dwarfs pop out red.
- Click the image to recentre; drag to open a new field of view.
- Dashed border when the animation loops, so a loop reset isn't mistaken for motion.
- Epoch legend (+ added, − subtracted, . unused), difference imaging, sliding time window, Gaia overlay,
  synthetic-mover injection, all state in the URL hash.

### 4. Gaia DR3 (MAST page) — <https://archive.stsci.edu/missions-and-data/gaia>
Use DR3. Three routes tested: IRSA cone search (7 s, primary), **MAST `Catalogs.query_region(..., catalog="Gaia",
version=3)` (4.5 s, now the automatic fallback)**, ESA archive (timed out today).

## Space Agency Partner (CSA). Using it helps eligibility for "Space Agency Partner data"
### 5–8. NEOSSat page, CADC, NEOSSat tutorial, NEOSSat dataset
- NEOSSat: CSA's microsatellite (launched 2013, ~780 km orbit), optical, built for asteroids, comets, debris and
  exoplanet transits. Licence: **Open Government Licence – Canada**. FITS User's Guide PDF on the dataset page.
- Access: (a) CSA FTP `ftp.asc-csa.gc.ca/users/OpenData_DonneesOuvertes/pub/NEOSSAT/ASTRO/{year}/{doy}/` by date;
  (b) **CADC by sky position**: `Cadc().query_region(coord, radius=..., collection="NEOSSAT")` (note `radius=`
  keyword in current astroquery), then `get_image_list(results, coord, radius)` for cutout URLs.
- Tutorial 2: overscan correction, darks, stacking, streaklet (line-segment) detection, frame differencing for NEOs.
- **Tested: NEOSSat has images within 0.5° of all 5 targets**: Barnard's 662, ε Ind B 29, WISE 0855 7, RW Aur 5,
  R Dra 10, dated ~2019–2023 (MJD 58xxx–60xxx). Each CADC query took ~40 s, so cache results.
  Idea: an optical NEOSSat frame from ~2020 next to SPHEREx 2026 gives a ~6-year baseline (Barnard's moves ~60″).

## Ideas ranked by value for the remaining time
1. **Acknowledgement + DOIs** on the project page and an About box in the app (5 min, required-ish).
2. **"Open in IRSA SPHEREx Data Explorer"** link per view (5 min, credibility).
3. **Colour composite mode** (red D5+D6, green D3+D4, blue D1+D2) à la WiseView (~1 h; strong "use the 102 bands" story).
4. **Solar-system object mode via MOST** (asteroid/comet name → stamps centred on predicted positions) and a
   3I/ATLAS preset from the ready-made table (~2–3 h; directly answers "comets, asteroids").
5. **NEOSSat long-baseline panel** for the presets (~2 h; partner data, 6-year motion).
6. SPHEREx HiPS in the Aladin panel instead of CDS's allWISE (~30 min, if Aladin Lite accepts the IRSA HiPS URL).
7. Official channel maps instead of log-spaced channels (~1 h, accuracy).
