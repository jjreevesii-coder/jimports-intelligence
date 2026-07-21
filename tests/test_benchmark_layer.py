from app.benchmark_layer import (
    channel_band,
    percentile_rank,
    summarize_checkpoint,
)


def test_percentile_rank():
    assert percentile_rank(
        50,
        [40, 50, 60],
    ) == 50.0


def test_channel_bands():
    assert channel_band(80) == "top_quartile"
    assert (
        channel_band(60)
        == "above_channel_median"
    )
    assert (
        channel_band(30)
        == "below_channel_median"
    )
    assert channel_band(10) == "bottom_quartile"


def test_checkpoint_summary():
    result = summarize_checkpoint(
        60,
        [40, 50, 70, 80],
    )

    assert result[
        "peer_median_retention_percent"
    ] == 60.0

    assert result[
        "difference_from_peer_median_points"
    ] == 0.0

    assert result["peer_sample_size"] == 4
