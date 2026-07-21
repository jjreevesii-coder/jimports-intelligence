import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


OVERRIDE_PATH = Path("data/video_tags.json")


FORMAT_LABELS = {
    "ownership_story": "Ownership or import story",
    "vehicle_documentary": "Vehicle documentary or profile",
    "buyer_guide_list": "Buyer guide or ranked list",
    "travel_guide_list": "Travel or destination guide",
    "event_or_museum": "Event, museum, factory, or tour coverage",
    "comparison_review": "Comparison or review",
    "unclassified": "Unclassified",
}


TOPIC_KEYWORDS = {
    "toyota": ["toyota", "lexus", "land cruiser", "crown"],
    "nissan": ["nissan", "skyline", "gt-r", "gtr"],
    "porsche": ["porsche", "911"],
    "bmw": ["bmw"],
    "mercedes": ["mercedes", "g-wagen", "g wagen"],
    "subaru": ["subaru", "sambar"],
    "suzuki": ["suzuki"],
    "honda": ["honda", "acura"],
    "mitsubishi": ["mitsubishi"],
    "mazda": ["mazda"],
    "jdm": ["jdm", "japan", "japanese", "import"],
    "kei_car": ["kei", "tiny car", "microcar"],
    "military_vehicle": [
        "military",
        "army",
        "war",
        "tank",
        "pinzgauer",
    ],
    "car_event": [
        "meeting",
        "show",
        "rally",
        "concours",
        "festival",
    ],
    "museum": ["museum", "collection"],
    "travel": [
        "tokyo",
        "japan",
        "things to do",
        "visit",
        "travel",
    ],
    "import": ["import", "imported", "auction", "jdm"],
}


@lru_cache(maxsize=1)
def load_overrides() -> dict[str, dict[str, Any]]:
    if not OVERRIDE_PATH.exists():
        return {}

    return json.loads(
        OVERRIDE_PATH.read_text(encoding="utf-8")
    )


def normalize(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        text.lower().replace("–", "-").replace("—", "-"),
    ).strip()


def infer_topics(title: str) -> list[str]:
    normalized = normalize(title)
    topics = []

    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            topics.append(topic)

    return sorted(set(topics))


def infer_format(title: str) -> tuple[str, float, str]:
    normalized = normalize(title)

    ownership_markers = [
        "i imported",
        "i've ever imported",
        "i bought",
        "i own",
        "my car",
        "my toyota",
        "my porsche",
        "my bmw",
        "owning",
        "ownership",
        "perfect island car",
    ]

    if any(marker in normalized for marker in ownership_markers):
        return (
            "ownership_story",
            0.95,
            "Title contains a strong ownership or import marker.",
        )

    if (
        " vs " in normalized
        or " versus " in normalized
        or "review" in normalized
        or "tested" in normalized
    ):
        return (
            "comparison_review",
            0.90,
            "Title contains a comparison or review marker.",
        )

    buyer_markers = [
        "top 5",
        "top five",
        "top 10",
        "top ten",
        "best cars",
        "worst cars",
        "cars to import",
        "should you buy",
        "buying guide",
        "under $",
    ]

    if any(marker in normalized for marker in buyer_markers):
        return (
            "buyer_guide_list",
            0.90,
            "Title contains a ranked-list or buyer-guide marker.",
        )

    travel_markers = [
        "things to do",
        "places to visit",
        "free car things",
        "car attractions",
    ]

    if any(marker in normalized for marker in travel_markers):
        return (
            "travel_guide_list",
            0.90,
            "Title contains a travel-guide marker.",
        )

    event_markers = [
        "meeting",
        "car show",
        "museum",
        "factory",
        "workshop",
        "rally",
        "collection",
        "inside the world's",
        "inside the world’s",
    ]

    if any(marker in normalized for marker in event_markers):
        return (
            "event_or_museum",
            0.85,
            "Title contains an event, museum, factory, or tour marker.",
        )

    documentary_markers = [
        "why did",
        "why this",
        "the real",
        "history of",
        "forgotten",
        "built for",
        "this is the",
        "ultimate",
    ]

    if any(marker in normalized for marker in documentary_markers):
        return (
            "vehicle_documentary",
            0.72,
            "Title suggests a vehicle profile or documentary.",
        )

    return (
        "unclassified",
        0.0,
        "No sufficiently reliable title-based format rule matched.",
    )


def classify_video(video: dict[str, Any]) -> dict[str, Any]:
    video_id = str(video.get("video_id", ""))
    title = str(video.get("title", ""))
    override = load_overrides().get(video_id)

    if override:
        return {
            "video_id": video_id,
            "title": title,
            "format": override["format"],
            "format_label": FORMAT_LABELS.get(
                override["format"],
                override["format"],
            ),
            "topics": sorted(set(override.get("topics", []))),
            "classification_source": "manual_override",
            "classification_confidence": 1.0,
            "classification_reason": override.get(
                "notes",
                "Manually classified.",
            ),
        }

    inferred_format, confidence, reason = infer_format(title)

    return {
        "video_id": video_id,
        "title": title,
        "format": inferred_format,
        "format_label": FORMAT_LABELS[inferred_format],
        "topics": infer_topics(title),
        "classification_source": "automatic_title_rule",
        "classification_confidence": confidence,
        "classification_reason": reason,
    }


def shared_topics(
    first: dict[str, Any],
    second: dict[str, Any],
) -> list[str]:
    return sorted(
        set(first.get("topics", []))
        & set(second.get("topics", []))
    )
