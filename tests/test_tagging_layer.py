from app.tagging_layer import (
    classify_video,
    infer_format,
    infer_topics,
    shared_topics,
)


def test_manual_origin_override():
    result = classify_video({
        "video_id": "Y8JFlS089VA",
        "title": (
            "This is the Weirdest Car I’ve Ever "
            "Imported | Toyota Origin"
        ),
    })

    assert result["format"] == "ownership_story"
    assert result["classification_source"] == "manual_override"


def test_buyer_guide_rule():
    format_name, confidence, _ = infer_format(
        "Top 5 Cars to Import from Japan"
    )

    assert format_name == "buyer_guide_list"
    assert confidence >= 0.8


def test_topic_detection():
    topics = infer_topics(
        "Why This Tiny Toyota JDM Car Is Perfect"
    )

    assert "toyota" in topics
    assert "jdm" in topics


def test_shared_topics():
    first = {"topics": ["toyota", "jdm"]}
    second = {"topics": ["jdm", "nissan"]}

    assert shared_topics(first, second) == ["jdm"]
