"""Parse the SJ↔Heredia research .md files into Python data structures.

The research files live under .sop/planning/transitpulse-m2/research/ and use
a `.md`-with-TS-`export const` convention (intentional — we read them as text,
never import them). This module turns them into ordinary Python lists/dicts so
the rest of the corridor seed pipeline can work without re-parsing.

Outputs
-------
- ``load_route_directions()`` → list of (route_id, direction_id, from_, to_,
  duration_min, ordered_stop_names) tuples. Applies the 400p loop split:
  400p outbound = stops 1–11 of the loop PDF only; SJ→Heredia uses the
  dedicated 24-stop inbound list.
- ``load_verified_coords()`` → list of {id, name, lat, lng, status, source}
  dicts straight from heredia-routes-lat-lng.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_DIR = REPO_ROOT / ".sop/planning/transitpulse-m2/research"

ROUTES_FILE = RESEARCH_DIR / "heredia-routes.md"
COORDS_FILE = RESEARCH_DIR / "heredia-routes-lat-lng.md"

# Per project memory: 400p outbound PDF is a 32-stop Heredia→SJ→Heredia loop.
# We treat only stops 1..11 as the user-facing Heredia→SJ leg. Stops 12..32 are
# operator-internal loop-back and ignored; SJ→Heredia uses the dedicated 24-stop
# `400p_sanjose_heredia` direction from the separate inbound PDF.
LOOP_SPLIT_OUTBOUND_LAST_STOP_INDEX = 11  # 1-indexed, inclusive


@dataclass
class Direction:
    route_id: str
    direction_id: str
    from_: str
    to_: str
    headsign: str
    duration_min: int
    stops: list[str]


@dataclass
class VerifiedCoord:
    id: str
    name: str
    lat: float
    lng: float
    status: str       # "verified" | "candidate"
    confidence: str   # "high" | "medium" | "low"
    source: str
    note: str | None = None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------- heredia-routes.md ----------

_ROUTE_HEADER_RE = re.compile(
    r'^\s*\{\s*\n'
    r'\s*id:\s*"(?P<id>[^"]+)",\s*\n'
    r'\s*name:\s*"(?P<name>[^"]+)",',
    re.MULTILINE,
)

_DIRECTION_HEADER_RE = re.compile(
    r'^\s*\{\s*\n'
    r'\s*id:\s*"(?P<dir_id>[^"]+)",\s*\n'
    r'\s*from:\s*"(?P<from>[^"]+)",\s*\n'
    r'\s*to:\s*"(?P<to>[^"]+)",\s*\n'
    r'\s*headsign:\s*"(?P<headsign>[^"]+)",\s*\n'
    r'\s*estimatedDurationMinutes:\s*(?P<dur>\d+),\s*\n'
    r'\s*stops:\s*\[',
    re.MULTILINE,
)


def load_route_directions() -> list[Direction]:
    """Parse heredia-routes.md and return one Direction per route+direction.

    Applies the 400p loop-split rule: the 32-stop outbound loop is truncated
    to its first 11 stops (Terminal Heredia → Repuestos Gigante La Valencia).
    """
    text = _read(ROUTES_FILE)
    directions: list[Direction] = []

    # Find each route block by id.
    route_matches = list(_ROUTE_HEADER_RE.finditer(text))
    for i, route_m in enumerate(route_matches):
        route_id = route_m.group("id")
        block_start = route_m.start()
        block_end = route_matches[i + 1].start() if i + 1 < len(route_matches) else len(text)
        block = text[block_start:block_end]

        for dir_m in _DIRECTION_HEADER_RE.finditer(block):
            dir_id = dir_m.group("dir_id")
            from_ = dir_m.group("from")
            to_ = dir_m.group("to")
            headsign = dir_m.group("headsign")
            duration = int(dir_m.group("dur"))

            # Extract the stops array contents — from after `stops: [` to the
            # matching `]`. Stops are double-quoted strings separated by commas.
            stops_start = dir_m.end()
            depth = 1
            j = stops_start
            while j < len(block) and depth > 0:
                ch = block[j]
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                j += 1
            stops_block = block[stops_start: j - 1]
            stops = [m.group(1) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', stops_block)]

            if route_id == "400p" and dir_id == "400p_heredia_sanjose":
                stops = stops[:LOOP_SPLIT_OUTBOUND_LAST_STOP_INDEX]

            directions.append(
                Direction(
                    route_id=route_id,
                    direction_id=dir_id,
                    from_=from_,
                    to_=to_,
                    headsign=headsign,
                    duration_min=duration,
                    stops=stops,
                )
            )

    return directions


# ---------- heredia-routes-lat-lng.md ----------

_COORD_ENTRY_RE = re.compile(
    r'\{\s*\n'
    r'\s*id:\s*"(?P<id>[^"]+)",\s*\n'
    r'\s*name:\s*"(?P<name>[^"]+)",\s*\n'
    r'\s*lat:\s*(?P<lat>-?\d+\.\d+),\s*\n'
    r'\s*lng:\s*(?P<lng>-?\d+\.\d+),\s*\n'
    r'\s*geocodeStatus:\s*"(?P<status>[^"]+)",\s*\n'
    r'\s*geocodeConfidence:\s*"(?P<conf>[^"]+)",\s*\n'
    r'\s*source:\s*"(?P<source>[^"]+)",'
    r'(?:\s*\n\s*note:\s*"(?P<note>[^"]+)",)?',
    re.MULTILINE,
)


def load_verified_coords() -> list[VerifiedCoord]:
    text = _read(COORDS_FILE)
    out: list[VerifiedCoord] = []
    for m in _COORD_ENTRY_RE.finditer(text):
        out.append(
            VerifiedCoord(
                id=m.group("id"),
                name=m.group("name"),
                lat=float(m.group("lat")),
                lng=float(m.group("lng")),
                status=m.group("status"),
                confidence=m.group("conf"),
                source=m.group("source"),
                note=m.group("note"),
            )
        )
    return out


if __name__ == "__main__":
    dirs = load_route_directions()
    coords = load_verified_coords()
    print(f"Loaded {len(dirs)} directions:")
    for d in dirs:
        print(f"  {d.route_id:6s} {d.direction_id:30s} {d.from_:10s} → {d.to_:10s} "
              f"{d.duration_min:>3d}min  {len(d.stops):>2d} stops")
    print(f"Loaded {len(coords)} verified coord entries:")
    for c in coords:
        print(f"  {c.id:40s} {c.status:9s} {c.confidence:6s} ({c.lat:.5f}, {c.lng:.5f})")
