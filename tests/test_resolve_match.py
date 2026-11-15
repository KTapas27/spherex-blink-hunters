"""Typed coordinates of a known fast mover follow it to 2026; other coordinates stay put.

Run: python tests/test_resolve_match.py <repo>
"""
import sys
sys.path.insert(0, sys.argv[1] + "/backend")
from app import pipeline, resolve

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
wise = resolve.resolve("WISE J085510.83-071442.5")

# The challenge text gives WISE 0855 as RA 08h55m10.831s, Dec -7d14m42.53s (an older-epoch position).
for q in ["08h55m10.831s -7d14m42.53s", "08 55 10.83 -07 14 42.5", "133.79513 -7.24515"]:
    t = resolve.resolve(q)
    ok(abs(t.ra - wise.ra) < 1e-6 and abs(t.dec - wise.dec) < 1e-6 and "WISE" in t.note,
       f"'{q}' -> WISE 0855 at its 2026 position (moved {t.moved_arcsec:.0f}\")")
ok(pipeline.view_key(resolve.resolve("08h55m10.831s -7d14m42.53s"), 0.1, 0) == pipeline.view_key(wise, 0.1, 0),
   "same view (and saved data) as the WISE 0855 button")

barnard = resolve.resolve("17h57m48.5s +04d41m36s")  # J2000 catalogue position
ok("Barnard" in barnard.name and barnard.moved_arcsec > 250, "Barnard's Star J2000 coordinates are followed")

plain = resolve.resolve("133.9 -7.2")  # 8' away from WISE 0855: an ordinary field
ok(plain.note == "" and plain.moved_arcsec < 1e-6, "unrelated coordinates are not moved")
slow = resolve.resolve("76.9565 30.4014")  # RW Aur: slow mover, coordinates kept as typed
ok(slow.note == "" and abs(slow.ra - 76.9565) < 1e-9, "slow movers (< 100 mas/yr) are left as typed")
explicit = resolve.resolve("08h55m10.831s -7d14m42.53s", pmra=0.0, pmdec=0.0)
ok(explicit.note == "", "explicit proper motion overrides the match")
