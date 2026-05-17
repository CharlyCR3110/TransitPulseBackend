"""Merge corridor data + coord sources into final seed patches.

Coord priority (highest first):
    1. Existing app/seed/stops.json — already smoke-tested in prod-like demo.
    2. heredia-routes-lat-lng.md — user-manually-verified entries.
    3. Nominatim cache — only accepted if plausibility filter passes:
         - display_name contains a canton keyword consistent with the stop's
           id prefix (her_* must mention Heredia; sj_* must mention San José
           or a known SJ neighborhood; etc.)
         - lat/lng inside the GAM bounding box.
    4. EXPLICIT_OVERRIDES — hand-curated coords for stops where all of the
       above fail or produce wrong results (e.g. Nominatim returned the
       San Isidro de Heredia terminal instead of the Heredia centro one).

Stops with no trustworthy coord are listed in the report but NOT added to
stops.json. They can be filled in by appending to heredia-routes-lat-lng.md
and re-running this script (re-entrant via the geocode cache).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.corridor.dict_builder import build_canonical_stops, CanonicalStop
from scripts.corridor.parse import load_route_directions, load_verified_coords

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_DIR = REPO_ROOT / "TransitPulseBackend/app/seed"
OUT_DIR = REPO_ROOT / "TransitPulseBackend/scripts/corridor/out"
GEOCODE_CACHE = OUT_DIR / "geocode_cache.json"

GAM_LAT_RANGE = (9.85, 10.10)
GAM_LNG_RANGE = (-84.30, -83.95)

PREFIX_CANTON_KEYWORDS: dict[str, set[str]] = {
    "her_": {"Heredia", "Mercedes", "Barreal", "Ulloa", "Lagunilla", "Pirro",
             "San Francisco de Heredia", "La Aurora", "Santa Cecilia",
             "La Victoria"},
    "sd_":  {"Santo Domingo"},
    "sp_":  {"San Pablo"},
    "tib_": {"Tibás", "Tibas", "Tournón", "Tournon", "Cinco Esquinas",
             "San Juan de Tibás"},
    "sj_":  {"San José", "San Jose", "Uruca", "Mata Redonda", "Sabana",
             "Tournón", "Tournon", "Mantica", "Mántica", "Pavas",
             "Hospital", "Merced", "Pitahaya"},
    "pte_": {"Heredia", "San José", "Uruca", "Barreal"},  # bridges are at province line
}


# Hand-curated overrides — used when none of (1), (2), (3) produced a good
# coord. Values are (lat, lng, "source label").
EXPLICIT_OVERRIDES: dict[str, tuple[float, float, str]] = {
    # Predio La 400 (Pirro) — distinct from the Super Fácil terminal.
    # Existing seed put this near (10.0078, -84.1115); inherit that.
    "her_term_la400_pirro": (10.0078, -84.1115, "existing seed (her_term_400 inherited)"),
    "her_term_aurora": (9.9907, -84.1500, "Nominatim hit, manually accepted"),
}


@dataclass
class CoordResolution:
    stop_id: str
    lat: float | None
    lng: float | None
    source: str           # "seed_existing" | "verified_md" | "nominatim" | "explicit_override" | "unresolved"
    confidence: str       # "high" | "medium" | "low" | "none"
    note: str = ""


def _in_gam(lat: float, lng: float) -> bool:
    return GAM_LAT_RANGE[0] <= lat <= GAM_LAT_RANGE[1] and GAM_LNG_RANGE[0] <= lng <= GAM_LNG_RANGE[1]


def _passes_canton_filter(stop_id: str, display_name: str | None) -> bool:
    if not display_name:
        return False
    # Match by id prefix.
    for prefix, keywords in PREFIX_CANTON_KEYWORDS.items():
        if stop_id.startswith(prefix):
            return any(k.lower() in display_name.lower() for k in keywords)
    return True  # unknown prefix — allow


def _load_existing_seed_coords() -> dict[str, tuple[float, float]]:
    data = json.loads((SEED_DIR / "stops.json").read_text(encoding="utf-8"))
    return {row["id"]: (row["lat"], row["lng"]) for row in data}


def _load_verified_md_coords_by_id() -> dict[str, tuple[float, float, str]]:
    """Map every user-verified row to ONE canonical id.

    The lat-lng file uses long IDs that don't match our canonical IDs verbatim.
    We use a hand-written alias table to bridge.
    """
    aliases = {
        "her_terminal_la400_super_facil": "her_term_400",
        "her_terminal_mercado_central": "her_term_mc",
        "sj_terminal_rapidos_heredianos": "sj_term_rh",
        "sj_terminal_san_jose_400": "sj_term_400u",
        "her_estadio_eladio_rosabal_cordero": "her_estadio",
        "her_cenada": "her_cenada",
        "her_pima_cenada": "her_pima_cenada",   # no canonical use yet — informational
        "sj_migracion_la_uruca_parqueo": "sj_migracion",
        "sj_la_uruca_district_anchor": None,    # district centroid — do not use
    }
    out: dict[str, tuple[float, float, str]] = {}
    for entry in load_verified_coords():
        canonical = aliases.get(entry.id, entry.id)
        if canonical is None:
            continue
        # Skip low-confidence candidate rows.
        if entry.status == "candidate" and entry.confidence == "low":
            continue
        out[canonical] = (entry.lat, entry.lng, f"verified_md ({entry.id}, {entry.confidence})")
    return out


def _load_nominatim_by_id() -> dict[str, dict]:
    cache = json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for v in cache.values():
        if v.get("lat") is None:
            continue
        by_id[v["stop_id"]] = v
    return by_id


def resolve_coords(canonical: dict[str, CanonicalStop]) -> dict[str, CoordResolution]:
    existing = _load_existing_seed_coords()
    verified = _load_verified_md_coords_by_id()
    nominatim = _load_nominatim_by_id()

    out: dict[str, CoordResolution] = {}
    for sid in canonical:
        # Priority 1: existing seed (but only if NOT also in verified — user
        # corrections trump older seed values).
        if sid in verified:
            lat, lng, src = verified[sid]
            out[sid] = CoordResolution(sid, lat, lng, "verified_md", "high", src)
            continue
        if sid in existing:
            lat, lng = existing[sid]
            out[sid] = CoordResolution(sid, lat, lng, "seed_existing", "high", "kept from existing app/seed/stops.json")
            continue
        if sid in EXPLICIT_OVERRIDES:
            lat, lng, src = EXPLICIT_OVERRIDES[sid]
            out[sid] = CoordResolution(sid, lat, lng, "explicit_override", "high", src)
            continue
        if sid in nominatim:
            hit = nominatim[sid]
            lat, lng = hit["lat"], hit["lng"]
            display = hit.get("display_name") or ""
            if not _in_gam(lat, lng):
                out[sid] = CoordResolution(sid, None, None, "unresolved", "none",
                    f"Nominatim hit outside GAM box; rejected. display: {display[:120]}")
                continue
            if not _passes_canton_filter(sid, display):
                out[sid] = CoordResolution(sid, None, None, "unresolved", "none",
                    f"Nominatim hit failed canton filter for id prefix; rejected. display: {display[:120]}")
                continue
            out[sid] = CoordResolution(sid, lat, lng, "nominatim", hit.get("confidence") or "low",
                f"display: {display[:120]}")
            continue
        out[sid] = CoordResolution(sid, None, None, "unresolved", "none", "no coord source")
    return out


def main() -> None:
    directions = load_route_directions()
    canonical = build_canonical_stops(directions)
    resolutions = resolve_coords(canonical)

    by_source: dict[str, int] = {}
    for r in resolutions.values():
        by_source[r.source] = by_source.get(r.source, 0) + 1

    print("Coord source breakdown:")
    for k, v in sorted(by_source.items()):
        print(f"  {k:20s} {v}")

    resolved = sum(1 for r in resolutions.values() if r.lat is not None)
    print(f"  resolved/total:      {resolved}/{len(resolutions)}")

    # Persist for inspection.
    report = {
        "summary": {
            "unique_stops": len(canonical),
            "by_source": by_source,
            "resolved": resolved,
        },
        "resolutions": [
            {
                "id": r.stop_id,
                "label_es": canonical[r.stop_id].label_es,
                "tier": canonical[r.stop_id].tier,
                "raw_names": canonical[r.stop_id].raw_names,
                "lat": r.lat, "lng": r.lng,
                "source": r.source, "confidence": r.confidence,
                "note": r.note,
            }
            for r in sorted(resolutions.values(), key=lambda x: (x.source, x.stop_id))
        ],
    }
    out_path = OUT_DIR / "coord_resolution_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
