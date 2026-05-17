"""Linear-interpolate coords for stops that have no other coord source.

Strategy per direction:
1. Build the ordered sequence of canonical stop IDs.
2. Mark each as resolved (has coord) or pending.
3. For each contiguous run of pending stops between two resolved anchors,
   linearly interpolate lat/lng by sequence position.
4. For pending runs at the start/end of a direction (before first anchor or
   after last), pin to the boundary anchor.

This is NOT road-snapped — straight-line interpolation between sequence
anchors. Good enough for "show plausible pin near where the stop is" UX in
the route detail map, not for precise nearest-stop matching. Stops produced
this way are flagged ``source = "interpolated"`` so the resolver can
de-weight them later if needed.

A stop visited in multiple directions can get multiple interpolated estimates;
we keep the median.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from scripts.corridor.dict_builder import build_canonical_stops
from scripts.corridor.merge import CoordResolution, resolve_coords
from scripts.corridor.parse import Direction, load_route_directions


def interpolate_unresolved(
    directions: list[Direction],
    resolutions: dict[str, CoordResolution],
    canonical_id_for: dict[str, str],
) -> dict[str, CoordResolution]:
    # Collect interpolation candidates per stop id.
    candidates: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for d in directions:
        sequence_ids = [canonical_id_for[raw] for raw in d.stops]
        # Walk through the sequence; for each pending stop, find the prev/next
        # anchor and interpolate.
        n = len(sequence_ids)
        for i, sid in enumerate(sequence_ids):
            res = resolutions[sid]
            if res.lat is not None:
                continue  # already resolved

            # Find previous anchor.
            prev_i = None
            for j in range(i - 1, -1, -1):
                if resolutions[sequence_ids[j]].lat is not None:
                    prev_i = j
                    break
            # Find next anchor.
            next_i = None
            for j in range(i + 1, n):
                if resolutions[sequence_ids[j]].lat is not None:
                    next_i = j
                    break

            if prev_i is None and next_i is None:
                continue  # whole direction has no resolved stops; nothing to do
            if prev_i is None:
                anchor = resolutions[sequence_ids[next_i]]
                candidates[sid].append((anchor.lat, anchor.lng))
                continue
            if next_i is None:
                anchor = resolutions[sequence_ids[prev_i]]
                candidates[sid].append((anchor.lat, anchor.lng))
                continue

            a = resolutions[sequence_ids[prev_i]]
            b = resolutions[sequence_ids[next_i]]
            t = (i - prev_i) / (next_i - prev_i)
            lat = a.lat + t * (b.lat - a.lat)
            lng = a.lng + t * (b.lng - a.lng)
            candidates[sid].append((lat, lng))

    # Apply median estimate per stop.
    for sid, options in candidates.items():
        if not options:
            continue
        lat = median(o[0] for o in options)
        lng = median(o[1] for o in options)
        resolutions[sid] = CoordResolution(
            stop_id=sid,
            lat=lat,
            lng=lng,
            source="interpolated",
            confidence="low",
            note=f"linear interpolation, {len(options)} direction sample(s)",
        )

    return resolutions


def main() -> None:
    directions = load_route_directions()
    canonical = build_canonical_stops(directions)
    # Build raw_name → canonical_id for the interpolator.
    canonical_id_for: dict[str, str] = {}
    for cs in canonical.values():
        for raw in cs.raw_names:
            canonical_id_for[raw] = cs.id

    resolutions = resolve_coords(canonical)
    resolutions = interpolate_unresolved(directions, resolutions, canonical_id_for)

    by_source: dict[str, int] = {}
    for r in resolutions.values():
        by_source[r.source] = by_source.get(r.source, 0) + 1

    print("Coord source breakdown after interpolation:")
    for k, v in sorted(by_source.items()):
        print(f"  {k:20s} {v}")
    resolved = sum(1 for r in resolutions.values() if r.lat is not None)
    print(f"  resolved/total:      {resolved}/{len(resolutions)}")


if __name__ == "__main__":
    main()
