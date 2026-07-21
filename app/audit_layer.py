from typing import Iterable


TRAFFIC_SOURCE_MAPPING_VERSION = "youtube-docs-2026-07-20"

VALIDATED_TRAFFIC_SOURCE_LABELS = {
    "ADVERTISING": "YouTube advertising",
    "ANNOTATION": "Annotations",
    "CAMPAIGN_CARD": "Campaign cards",
    "END_SCREEN": "End screens",
    "EXT_URL": "External",
    "HASHTAGS": "Hashtag pages",
    "LIVE_REDIRECT": "Live redirect",
    "NO_LINK_EMBEDDED": "Embedded players",
    "NO_LINK_OTHER": "Direct or unknown",
    "NOTIFICATION": "Notifications",
    "PLAYLIST": "Playlists",
    "PRODUCT_PAGE": "Product pages",
    "PROMOTED": "YouTube promotions",
    "RELATED_VIDEO": "Suggested videos",
    "SHORTS": "Shorts feed",
    "SOUND_PAGE": "Sound pages",
    "SUBSCRIBER": "Browse features",
    "YT_CHANNEL": "Channel pages",
    "YT_OTHER_PAGE": "Other YouTube features",
    "YT_SEARCH": "YouTube Search",
    "VIDEO_REMIXES": "Video remixes",
}


def traffic_source_label(raw_code: str) -> str:
    return VALIDATED_TRAFFIC_SOURCE_LABELS.get(
        raw_code,
        raw_code.replace("_", " ").title(),
    )


def reconciliation_check(
    name: str,
    expected: int,
    observed: int,
) -> dict:
    difference = observed - expected

    if expected:
        absolute_difference_percent = round(
            abs(difference) / expected * 100,
            3,
        )
    else:
        absolute_difference_percent = 0.0 if observed == 0 else 100.0

    if absolute_difference_percent <= 1.0:
        status = "PASS"
    elif absolute_difference_percent <= 3.0:
        status = "WARN"
    else:
        status = "FAIL"

    return {
        "check": name,
        "status": status,
        "expected": expected,
        "observed": observed,
        "difference": difference,
        "absolute_difference_percent": absolute_difference_percent,
    }


def boolean_check(
    name: str,
    passed: bool,
    details: str,
    failure_status: str = "FAIL",
) -> dict:
    return {
        "check": name,
        "status": "PASS" if passed else failure_status,
        "details": details,
    }


def overall_status(checks: Iterable[dict]) -> str:
    statuses = {check.get("status") for check in checks}

    if "FAIL" in statuses:
        return "FAIL"

    if "WARN" in statuses:
        return "WARN"

    return "PASS"
