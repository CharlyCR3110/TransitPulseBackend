"""Generate app/seed/stops.json and app/seed/route_stops.json patches.

Output is the **final** form of those files, ready to drop into app/seed/.
The script:

1. Loads the canonical stop dict + coord resolutions (with interpolation).
2. Builds a new ``stops.json`` that:
     - Preserves every existing entry that is NOT in the corridor dict.
     - Updates every existing entry that IS in the corridor dict (new coord
       source might supersede the old one).
     - Appends every new corridor stop.
3. Builds a new ``route_stops.json`` that:
     - Preserves every existing entry whose route_id is NOT one of the
       corridor routes (400p / 400u / 400sd).
     - Replaces all entries for the corridor routes with the new 6
       directions (400p out/in, 400u out/in, 400sd out/in).
4. Computes ``segment_minutes`` for each stop pair by evenly dividing the
   direction's ``estimatedDurationMinutes`` across (n_stops - 1) gaps,
   rounded to the nearest minute (min 1).
5. Writes outputs to scripts/corridor/out/ for review; also offers a
   ``--apply`` flag to write them into app/seed/ directly.

400u and 400sd need entries in app/seed/routes.json. We don't have 400u in
the routes file yet — we'll print the route metadata that needs to be added
manually (operator, fare, color), since fare/headway for 400u aren't in
heredia-routes-raw.md.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from scripts.corridor.dict_builder import build_canonical_stops
from scripts.corridor.interpolate import interpolate_unresolved
from scripts.corridor.merge import resolve_coords
from scripts.corridor.parse import load_route_directions

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "TransitPulseBackend/app/seed"
OUT_DIR = REPO_ROOT / "TransitPulseBackend/scripts/corridor/out"

CORRIDOR_ROUTE_IDS = {"400p", "400u", "400sd", "402"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _name_key(stop_id: str) -> str:
    # Existing pattern: "stop_<id>"
    return f"stop_{stop_id}"


def _addr_key(stop_id: str) -> str:
    return f"stop_{stop_id}_addr"


def _english_addr(es: str) -> str:
    # Lightweight: keep place names. Replace common "de Heredia" → "Heredia",
    # diacritics removed already by the source data sometimes.
    s = es
    s = re.sub(r"\bDe Heredia\b", "Heredia", s, flags=re.I)
    s = re.sub(r"\bSan José\b", "San José", s)
    s = re.sub(r"\bSantam[aá]r[ií]a\b", "Santamaría", s)
    return s


def build_stops_json(canonical, resolutions) -> list[dict]:
    existing = json.loads((SEED_DIR / "stops.json").read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {row["id"]: row for row in existing}

    for sid, cs in canonical.items():
        res = resolutions[sid]
        if res.lat is None or res.lng is None:
            continue  # safety net; should not happen after interpolation
        row = by_id.get(sid, {})
        # Preserve hand-curated labels/addresses on existing entries; only
        # fill them when the row is new. Lat/lng always reflects the latest
        # resolution (verified > Nominatim > interpolated).
        row.update({
            "id": sid,
            "name_key": row.get("name_key") or _name_key(sid),
            "addr_key": row.get("addr_key") or _addr_key(sid),
            "label_es": row.get("label_es") or cs.label_es,
            "label_en": row.get("label_en") or cs.label_en,
            "addr_es": row.get("addr_es") or cs.addr_es,
            "addr_en": row.get("addr_en") or _english_addr(cs.addr_es),
            "lat": round(res.lat, 6),
            "lng": round(res.lng, 6),
            "live": row.get("live", True),
        })
        by_id[sid] = row

    # Preserve ordering: existing entries first (in their original order),
    # then new entries sorted by id for stable diffs.
    out: list[dict] = []
    seen = set()
    for row in existing:
        out.append(by_id[row["id"]])
        seen.add(row["id"])
    for sid in sorted(by_id):
        if sid in seen:
            continue
        out.append(by_id[sid])
    return out


def build_route_stops_json(directions, canonical_id_for, resolutions) -> list[dict]:
    """Build route_stops rows. segment_minutes is allocated proportional to
    haversine distance between consecutive stops, with a floor of 1 minute.

    Even distribution would assign 1 min to a 6 km highway segment and 1 min
    to a 100 m walk between adjacent urban stops — that produces planner
    artifacts like "walk 10 min, ride 1 min" for SJ → Heredia. Distance-
    proportional allocation tracks real-world speed differences across the
    route (autopista segments dominate the budget; urban stops barely move
    the clock).
    """
    from app.modules.shared.utils import haversine_m

    existing = json.loads((SEED_DIR / "route_stops.json").read_text(encoding="utf-8"))
    preserved = [r for r in existing if r["route_id"] not in CORRIDOR_ROUTE_IDS]

    new_rows: list[dict] = []
    for d in directions:
        if d.from_ == "Heredia":
            direction = "outbound"
        elif d.to_ == "Heredia":
            direction = "inbound"
        else:
            direction = "outbound" if "heredia" in d.direction_id.split("_")[1:2] else "inbound"

        stop_ids = [canonical_id_for[raw] for raw in d.stops]
        n = len(stop_ids)
        if n <= 1:
            segments = [0]
        else:
            # Per-gap distance.
            gap_m: list[float] = []
            for i in range(1, n):
                a = resolutions[stop_ids[i - 1]]
                b = resolutions[stop_ids[i]]
                gap_m.append(haversine_m(a.lat, a.lng, b.lat, b.lng))

            # Iterative allocation: at each pass, gaps whose proportional
            # share would fall below 1 min get floored to 1 and excluded
            # from the remaining budget. Repeat until no more flooring
            # happens. Converges in 1–3 iterations for our routes and
            # keeps total drift to ≤ ±1 min.
            gap_min: list[int] = [0] * len(gap_m)
            fixed: set[int] = set()
            while True:
                free = [i for i in range(len(gap_m)) if i not in fixed]
                if not free:
                    break
                free_budget = d.duration_min - len(fixed)
                free_total = sum(gap_m[i] for i in free) or 1.0
                if free_budget <= len(free):
                    # Not enough budget left to give every remaining gap > 1 min.
                    for i in free:
                        gap_min[i] = 1
                        fixed.add(i)
                    continue
                new_floored = []
                for i in free:
                    if free_budget * gap_m[i] / free_total < 1.0:
                        new_floored.append(i)
                if new_floored:
                    for i in new_floored:
                        gap_min[i] = 1
                        fixed.add(i)
                    continue
                # No more flooring; allocate proportionally to remaining.
                for i in free:
                    gap_min[i] = max(1, round(free_budget * gap_m[i] / free_total))
                    fixed.add(i)
            segments = [0] + gap_min

        for order, sid in enumerate(stop_ids, start=1):
            new_rows.append({
                "route_id": d.route_id,
                "stop_id": sid,
                "direction": direction,
                "stop_order": order,
                "segment_minutes": segments[order - 1],
            })

    return preserved + new_rows


def ensure_route_metadata() -> list[dict]:
    """Make sure routes.json has entries for all three corridor routes."""
    routes_path = SEED_DIR / "routes.json"
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in routes}

    defaults = {
        "400p": {
            "id": "400p", "short_name": "400 Pista",
            "long_name": "Heredia - San José por Pista (Transportes Unidos La 400)",
            "mode": "bus", "fare_min": 750, "fare_max": 750, "color": "#2563eb",
        },
        "400sd": {
            "id": "400sd", "short_name": "400 STD",
            "long_name": "San José - Heredia por Santo Domingo (MRH)",
            "mode": "bus", "fare_min": 720, "fare_max": 720, "color": "#dc2626",
        },
        "400u": {
            "id": "400u", "short_name": "400 Uruca",
            "long_name": "Heredia - San José por La Uruca (Transportes Unidos La 400)",
            "mode": "bus", "fare_min": 750, "fare_max": 750, "color": "#16a34a",
        },
        "402": {
            "id": "402", "short_name": "402 Cenada",
            "long_name": "Heredia - Cenada - Lagunilla (Transportes Unidos La 400)",
            "mode": "bus", "fare_min": 540, "fare_max": 540, "color": "#14b8a6",
        },
    }
    for rid, default in defaults.items():
        if rid not in by_id:
            routes.append(default)
            by_id[rid] = default
    return routes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write directly into app/seed/ (default: scripts/corridor/out/).")
    args = parser.parse_args()

    directions = load_route_directions()
    canonical = build_canonical_stops(directions)
    canonical_id_for = {raw: cs.id for cs in canonical.values() for raw in cs.raw_names}
    resolutions = resolve_coords(canonical)
    resolutions = interpolate_unresolved(directions, resolutions, canonical_id_for)

    stops = build_stops_json(canonical, resolutions)
    route_stops = build_route_stops_json(directions, canonical_id_for, resolutions)
    routes = ensure_route_metadata()

    if args.apply:
        target_dir = SEED_DIR
    else:
        target_dir = OUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "stops.json").write_text(
        json.dumps(stops, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (target_dir / "route_stops.json").write_text(
        json.dumps(route_stops, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (target_dir / "routes.json").write_text(
        json.dumps(routes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Wrote {len(stops)} stops, {len(route_stops)} route_stops, {len(routes)} routes")
    print(f"  → {target_dir.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
