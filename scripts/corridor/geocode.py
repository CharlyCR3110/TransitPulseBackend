"""Nominatim geocoder for corridor stops.

Behavior:
- Honors Nominatim usage policy: ≤1 req/sec, descriptive User-Agent, single
  threaded.
- Only queries non-corner stops (anchor / landmark / mid) — corner stops
  (random local references) are skipped.
- Results saved to a small JSON cache at scripts/corridor/out/geocode_cache.json
  so re-runs are cheap and re-entrant.
- Country filter: countrycodes=cr. Bounding box loosely around the GAM.
- Each result gets a confidence label: high (importance ≥ 0.4 OR class in
  {amenity, building}), medium (>= 0.2), low (else).

This does NOT mutate heredia-routes-lat-lng.md. That file is user-curated; we
emit machine-geocoded results into the build pipeline directly and surface
them in the seed-build report so the user can promote good ones.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from scripts.corridor.dict_builder import build_canonical_stops, CanonicalStop
from scripts.corridor.parse import load_route_directions

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_PATH = REPO_ROOT / "TransitPulseBackend/scripts/corridor/out/geocode_cache.json"

# Loose GAM bounding box: (left=lng_min, top=lat_max, right=lng_max, bottom=lat_min)
GAM_VIEWBOX = "-84.30,10.10,-83.95,9.85"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "TransitPulse/0.1 (charlygg@; M2 Heredia corridor seed)"
RATE_LIMIT_SECONDS = 1.1


@dataclass
class GeocodeResult:
    stop_id: str
    query: str
    lat: float | None
    lng: float | None
    confidence: str | None    # "high" | "medium" | "low" | None (no hit)
    osm_type: str | None
    osm_id: str | None
    display_name: str | None
    importance: float | None


def _load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _confidence_for(result: dict) -> str:
    importance = result.get("importance", 0.0) or 0.0
    klass = result.get("class", "")
    if importance >= 0.4 or klass in {"amenity", "building", "tourism", "shop"}:
        return "high"
    if importance >= 0.2:
        return "medium"
    return "low"


def _query_nominatim(client: httpx.Client, q: str) -> dict | None:
    params = {
        "q": q,
        "format": "jsonv2",
        "countrycodes": "cr",
        "limit": 1,
        "viewbox": GAM_VIEWBOX,
        "bounded": 1,
        "addressdetails": 1,
    }
    r = client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None


def geocode_canonical(stops: list[CanonicalStop], *, only_tiers: set[str] | None = None) -> list[GeocodeResult]:
    only_tiers = only_tiers or {"anchor", "landmark", "mid"}
    cache = _load_cache()
    results: list[GeocodeResult] = []
    queried = 0

    with httpx.Client() as client:
        for cs in stops:
            if cs.tier not in only_tiers or not cs.geocode_query:
                continue
            key = f"{cs.id}::{cs.geocode_query}"
            if key in cache:
                cached = cache[key]
                results.append(GeocodeResult(**cached))
                continue

            try:
                hit = _query_nominatim(client, cs.geocode_query)
            except Exception as e:
                print(f"  [error] {cs.id}: {e}", file=sys.stderr)
                hit = None
            queried += 1

            if hit:
                gr = GeocodeResult(
                    stop_id=cs.id,
                    query=cs.geocode_query,
                    lat=float(hit["lat"]),
                    lng=float(hit["lon"]),
                    confidence=_confidence_for(hit),
                    osm_type=hit.get("osm_type"),
                    osm_id=str(hit.get("osm_id")) if hit.get("osm_id") is not None else None,
                    display_name=hit.get("display_name"),
                    importance=hit.get("importance"),
                )
            else:
                gr = GeocodeResult(
                    stop_id=cs.id,
                    query=cs.geocode_query,
                    lat=None, lng=None, confidence=None,
                    osm_type=None, osm_id=None,
                    display_name=None, importance=None,
                )

            cache[key] = gr.__dict__
            results.append(gr)
            _save_cache(cache)  # save after each — survives Ctrl-C
            time.sleep(RATE_LIMIT_SECONDS)

    print(f"  queried {queried} new (rest from cache)")
    return results


def main() -> None:
    directions = load_route_directions()
    canonical = build_canonical_stops(directions)
    stops = sorted(canonical.values(), key=lambda x: x.id)

    targets = [s for s in stops if s.tier in {"anchor", "landmark", "mid"}]
    print(f"Geocoding {len(targets)} non-corner stops (anchor + landmark + mid)…")
    results = geocode_canonical(stops)

    hits = [r for r in results if r.lat is not None]
    by_conf: dict[str, int] = {}
    for r in hits:
        by_conf[r.confidence or "?"] = by_conf.get(r.confidence or "?", 0) + 1
    print(f"  hits: {len(hits)}/{len(results)}")
    print(f"  by confidence: {by_conf}")
    print(f"  cache at: {CACHE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
