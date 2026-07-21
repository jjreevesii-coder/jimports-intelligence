from statistics import median
from typing import Iterable, Optional


def percentile_rank(
    target: float,
    peers: Iterable[float],
) -> Optional[float]:
    values = [float(value) for value in peers]

    if not values:
        return None

    below = sum(value < target for value in values)
    equal = sum(
        abs(value - target) < 1e-9
        for value in values
    )

    return round(
        (below + 0.5 * equal) / len(values) * 100,
        1,
    )


def channel_band(
    percentile: Optional[float],
) -> Optional[str]:
    if percentile is None:
        return None

    if percentile >= 75:
        return "top_quartile"

    if percentile >= 50:
        return "above_channel_median"

    if percentile >= 25:
        return "below_channel_median"

    return "bottom_quartile"


def summarize_checkpoint(
    target_retention_percent: float,
    peer_retention_values: Iterable[float],
) -> dict:
    peers = [
        float(value)
        for value in peer_retention_values
    ]

    target = float(target_retention_percent)

    if not peers:
        return {
            "target_retention_percent": round(
                target,
                2,
            ),
            "peer_sample_size": 0,
            "peer_median_retention_percent": None,
            "difference_from_peer_median_points": None,
            "channel_percentile": None,
            "channel_band": None,
        }

    peer_median = float(median(peers))
    percentile = percentile_rank(
        target,
        peers,
    )

    return {
        "target_retention_percent": round(
            target,
            2,
        ),
        "peer_sample_size": len(peers),
        "peer_median_retention_percent": round(
            peer_median,
            2,
        ),
        "difference_from_peer_median_points": round(
            target - peer_median,
            2,
        ),
        "channel_percentile": percentile,
        "channel_band": channel_band(percentile),
    }
