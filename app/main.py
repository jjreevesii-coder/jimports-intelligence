import json
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import isodate
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

ROOT_DIR = Path(__file__).resolve().parents[1]

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

ANALYTICS_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,subscribersGained,subscribersLost"
)

security = HTTPBearer(auto_error=False)

app = FastAPI(
    title="Jimports Intelligence API",
    description="Read-only YouTube and YouTube Analytics data for Jimports.",
    version="1.1.0",
    servers=[
        {"url": "https://jimports-intelligence.onrender.com"}
    ],
)


def require_api_key(
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    expected = os.getenv("JIMPORTS_API_KEY", "").strip()

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="JIMPORTS_API_KEY is not configured.",
        )

    if (
        authorization is None
        or authorization.scheme.lower() != "bearer"
        or not secrets.compare_digest(authorization.credentials, expected)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def load_local_client_credentials() -> Tuple[str, str]:
    client_file = ROOT_DIR / "client_secret.json"

    if not client_file.exists():
        raise RuntimeError(
            "No Google client credentials found in environment variables "
            "or client_secret.json."
        )

    payload = json.loads(client_file.read_text(encoding="utf-8"))
    config = payload.get("installed") or payload.get("web")

    if not config:
        raise RuntimeError("Unrecognized Google client-secret file format.")

    return config["client_id"], config["client_secret"]


def get_google_credentials() -> Credentials:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()

    if client_id and client_secret and refresh_token:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        credentials.refresh(Request())
        return credentials

    token_file = ROOT_DIR / "token.json"

    if not token_file.exists():
        raise RuntimeError(
            "token.json is missing. Run the local authorization/export "
            "process before starting the API."
        )

    credentials = Credentials.from_authorized_user_file(
        str(token_file),
        SCOPES,
    )

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_file.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

    if not credentials.valid:
        raise RuntimeError("Google credentials are not valid.")

    return credentials


def get_services():
    credentials = get_google_credentials()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    analytics = build(
        "youtubeAnalytics",
        "v2",
        credentials=credentials,
        cache_discovery=False,
    )

    return youtube, analytics


def report_values(report: Dict) -> Dict:
    headers = [
        column["name"]
        for column in report.get("columnHeaders", [])
    ]
    rows = report.get("rows", [])

    if not rows:
        return {
            "views": 0,
            "estimatedMinutesWatched": 0,
            "averageViewDuration": 0,
            "averageViewPercentage": 0,
            "subscribersGained": 0,
            "subscribersLost": 0,
        }

    return dict(zip(headers, rows[0]))


def normalized_metrics(values: Dict) -> Dict:
    subscribers_gained = int(values.get("subscribersGained", 0))
    subscribers_lost = int(values.get("subscribersLost", 0))
    views = int(values.get("views", 0))

    net_subscribers = subscribers_gained - subscribers_lost
    subscribers_per_1000_views = (
        round(net_subscribers / views * 1000, 2)
        if views
        else 0
    )

    return {
        "views": views,
        "watch_hours": round(
            float(values.get("estimatedMinutesWatched", 0)) / 60,
            2,
        ),
        "average_view_duration_seconds": round(
            float(values.get("averageViewDuration", 0)),
            1,
        ),
        "average_percentage_viewed": round(
            float(values.get("averageViewPercentage", 0)),
            2,
        ),
        "subscribers_gained": subscribers_gained,
        "subscribers_lost": subscribers_lost,
        "net_subscribers": net_subscribers,
        "subscribers_per_1000_views": subscribers_per_1000_views,
    }


def get_video_metadata(youtube, video_ids: List[str]) -> Dict[str, Dict]:
    metadata: Dict[str, Dict] = {}

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        if not batch:
            continue

        response = youtube.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(batch),
        ).execute()

        for item in response.get("items", []):
            duration_seconds = int(
                isodate.parse_duration(
                    item["contentDetails"]["duration"]
                ).total_seconds()
            )

            metadata[item["id"]] = {
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"],
                "duration_seconds": duration_seconds,
                "runtime_minutes": round(duration_seconds / 60, 1),
                "privacy_status": item["status"]["privacyStatus"],
                "thumbnail_url": (
                    item["snippet"]
                    .get("thumbnails", {})
                    .get("high", {})
                    .get("url")
                ),
            }

    return metadata


def video_performance(
    video_id: str,
    window: str,
) -> Dict:
    youtube, analytics = get_services()

    metadata = get_video_metadata(youtube, [video_id]).get(video_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Video not found.")

    published_date = date.fromisoformat(
        metadata["published_at"][:10]
    )
    yesterday = date.today() - timedelta(days=1)

    if window == "7":
        target_end = published_date + timedelta(days=6)
    elif window == "28":
        target_end = published_date + timedelta(days=27)
    elif window == "lifetime":
        target_end = yesterday
    else:
        raise HTTPException(
            status_code=400,
            detail="Window must be 7, 28, or lifetime.",
        )

    actual_end = min(target_end, yesterday)
    complete = yesterday >= target_end

    if actual_end < published_date:
        values = {}
    else:
        report = analytics.reports().query(
            ids="channel==MINE",
            startDate=published_date.isoformat(),
            endDate=actual_end.isoformat(),
            metrics=ANALYTICS_METRICS,
            filters=f"video=={video_id}",
        ).execute()

        values = report_values(report)

    return {
        **metadata,
        "window": window,
        "period_start": published_date.isoformat(),
        "period_end": actual_end.isoformat(),
        "window_complete": complete,
        **normalized_metrics(values),
    }


@app.get(
    "/health",
    operation_id="getHealth",
    summary="Confirm that the Jimports API is online",
)
def health():
    return {
        "status": "ok",
        "service": "Jimports Intelligence API",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get(
    "/channel-summary",
    operation_id="getChannelSummary",
    summary="Get current Jimports channel performance",
    dependencies=[Depends(require_api_key)],
)
def channel_summary(
    days: int = Query(default=28, ge=1, le=3650),
):
    youtube, analytics = get_services()

    yesterday = date.today() - timedelta(days=1)
    start_date = yesterday - timedelta(days=days - 1)

    channel_response = youtube.channels().list(
        part="snippet,statistics",
        mine=True,
    ).execute()

    items = channel_response.get("items", [])

    if not items:
        raise HTTPException(
            status_code=404,
            detail="No authorized YouTube channel found.",
        )

    channel = items[0]

    report = analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=yesterday.isoformat(),
        metrics=ANALYTICS_METRICS,
    ).execute()

    return {
        "channel_id": channel["id"],
        "channel_name": channel["snippet"]["title"],
        "current_subscribers": int(
            channel["statistics"].get("subscriberCount", 0)
        ),
        "lifetime_channel_views": int(
            channel["statistics"].get("viewCount", 0)
        ),
        "public_video_count": int(
            channel["statistics"].get("videoCount", 0)
        ),
        "period_days": days,
        "period_start": start_date.isoformat(),
        "period_end": yesterday.isoformat(),
        **normalized_metrics(report_values(report)),
    }


@app.get(
    "/videos",
    operation_id="getVideoPerformanceList",
    summary="List Jimports videos and performance for a date range",
    dependencies=[Depends(require_api_key)],
)
def videos(
    days: int = Query(
        default=0,
        ge=0,
        le=3650,
        description=(
            "Use 0 for all available history since 2024-01-01, "
            "or specify the number of recent days."
        ),
    ),
    limit: int = Query(default=100, ge=1, le=200),
):
    youtube, analytics = get_services()
    yesterday = date.today() - timedelta(days=1)

    if days:
        start_date = yesterday - timedelta(days=days - 1)
    else:
        start_date = date(2024, 1, 1)

    report = analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=yesterday.isoformat(),
        dimensions="video",
        metrics=ANALYTICS_METRICS,
        sort="-views",
        maxResults=limit,
    ).execute()

    headers = [
        column["name"]
        for column in report.get("columnHeaders", [])
    ]

    rows = [
        dict(zip(headers, row))
        for row in report.get("rows", [])
    ]

    video_ids = [row["video"] for row in rows]
    metadata = get_video_metadata(youtube, video_ids)

    results = []

    for row in rows:
        video_id = row["video"]
        results.append({
            **metadata.get(
                video_id,
                {
                    "video_id": video_id,
                    "title": "Unknown or deleted video",
                },
            ),
            **normalized_metrics(row),
        })

    return {
        "period_start": start_date.isoformat(),
        "period_end": yesterday.isoformat(),
        "days": days if days else None,
        "video_count": len(results),
        "videos": results,
    }


@app.get(
    "/video/{video_id}",
    operation_id="getVideoPerformance",
    summary="Get a video's first 7 days, first 28 days, or lifetime data",
    dependencies=[Depends(require_api_key)],
)
def video(
    video_id: str,
    window: str = Query(default="28", pattern="^(7|28|lifetime)$"),
):
    try:
        return video_performance(video_id, window)
    except HttpError as error:
        raise HTTPException(
            status_code=502,
            detail=f"YouTube API error: {error}",
        ) from error


@app.get(
    "/compare",
    operation_id="compareVideos",
    summary="Compare multiple Jimports videos using the same window",
    dependencies=[Depends(require_api_key)],
)
def compare(
    video_ids: str = Query(
        description="Comma-separated YouTube video IDs, maximum 10."
    ),
    window: str = Query(default="28", pattern="^(7|28|lifetime)$"),
):
    ids = [
        value.strip()
        for value in video_ids.split(",")
        if value.strip()
    ]

    if not ids:
        raise HTTPException(
            status_code=400,
            detail="At least one video ID is required.",
        )

    if len(ids) > 10:
        raise HTTPException(
            status_code=400,
            detail="A maximum of 10 videos may be compared.",
        )

    return {
        "window": window,
        "video_count": len(ids),
        "videos": [
            video_performance(video_id, window)
            for video_id in ids
        ],
    }


# --- JIMPORTS DIAGNOSTICS V2 ---

TRAFFIC_SOURCE_LABELS = {
    "RELATED_VIDEO": "Suggested videos",
    "YT_SEARCH": "YouTube Search",
    "SUBSCRIBER": "Browse features",
    "EXT_URL": "External websites and apps",
    "NOTIFICATION": "Notifications",
    "PLAYLIST": "Playlists",
    "YT_CHANNEL": "Channel pages",
    "END_SCREEN": "End screens",
    "SHORTS": "Shorts feed",
    "NO_LINK_OTHER": "Direct or unknown",
    "NO_LINK_EMBEDDED": "Embedded players",
    "YT_OTHER_PAGE": "Other YouTube features",
    "ADVERTISING": "YouTube advertising",
    "HASHTAGS": "Hashtag pages",
    "SOUND_PAGE": "Sound pages",
    "VIDEO_REMIXES": "Video remixes",
}


def resolve_video_window(
    youtube,
    video_id: str,
    window: str,
):
    metadata = get_video_metadata(
        youtube,
        [video_id],
    ).get(video_id)

    if not metadata:
        raise HTTPException(
            status_code=404,
            detail="Video not found.",
        )

    published_date = date.fromisoformat(
        metadata["published_at"][:10]
    )
    yesterday = date.today() - timedelta(days=1)

    if window == "7":
        target_end = published_date + timedelta(days=6)
    elif window == "28":
        target_end = published_date + timedelta(days=27)
    elif window == "lifetime":
        target_end = yesterday
    else:
        raise HTTPException(
            status_code=400,
            detail="Window must be 7, 28, or lifetime.",
        )

    actual_end = min(target_end, yesterday)
    complete = yesterday >= target_end

    return (
        metadata,
        published_date,
        actual_end,
        complete,
    )


@app.get(
    "/video/{video_id}/retention",
    operation_id="getVideoRetention",
    summary="Get the detailed audience-retention curve for one video",
    dependencies=[Depends(require_api_key)],
)
def video_retention(
    video_id: str,
    window: str = Query(
        default="lifetime",
        pattern="^(7|28|lifetime)$",
    ),
):
    try:
        youtube, analytics = get_services()

        (
            metadata,
            start_date,
            end_date,
            complete,
        ) = resolve_video_window(
            youtube,
            video_id,
            window,
        )

        if end_date < start_date:
            return {
                **metadata,
                "window": window,
                "window_complete": complete,
                "points": [],
                "summary": {},
            }

        report = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            dimensions="elapsedVideoTimeRatio",
            metrics=(
                "audienceWatchRatio,"
                "relativeRetentionPerformance"
            ),
            filters=f"video=={video_id}",
        ).execute()

        headers = [
            column["name"]
            for column in report.get("columnHeaders", [])
        ]

        raw_rows = [
            dict(zip(headers, row))
            for row in report.get("rows", [])
        ]

        duration_seconds = metadata["duration_seconds"]
        points = []

        for row in raw_rows:
            elapsed_ratio = float(
                row.get("elapsedVideoTimeRatio", 0)
            )
            audience_ratio = float(
                row.get("audienceWatchRatio", 0)
            )
            relative_score = float(
                row.get("relativeRetentionPerformance", 0)
            )

            points.append({
                "elapsed_ratio": round(elapsed_ratio, 4),
                "elapsed_seconds": round(
                    elapsed_ratio * duration_seconds,
                    1,
                ),
                "audience_retention_percent": round(
                    audience_ratio * 100,
                    2,
                ),
                "relative_retention_score": round(
                    relative_score,
                    4,
                ),
            })

        points.sort(key=lambda value: value["elapsed_ratio"])

        def nearest_point(target_ratio: float):
            if not points:
                return None

            return min(
                points,
                key=lambda value: abs(
                    value["elapsed_ratio"] - target_ratio
                ),
            )

        thirty_second_ratio = min(
            30 / duration_seconds,
            1,
        ) if duration_seconds else 0

        summary = {
            "start": nearest_point(0),
            "thirty_seconds": nearest_point(
                thirty_second_ratio
            ),
            "quarter": nearest_point(0.25),
            "midpoint": nearest_point(0.50),
            "three_quarters": nearest_point(0.75),
            "ending": nearest_point(0.95),
        }

        return {
            **metadata,
            "window": window,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "window_complete": complete,
            "summary": summary,
            "points": points,
        }

    except HttpError as error:
        raise HTTPException(
            status_code=502,
            detail=f"YouTube API error: {error}",
        ) from error


@app.get(
    "/video/{video_id}/traffic-sources",
    operation_id="getVideoTrafficSources",
    summary="Get the traffic sources for one video",
    dependencies=[Depends(require_api_key)],
)
def video_traffic_sources(
    video_id: str,
    window: str = Query(
        default="lifetime",
        pattern="^(7|28|lifetime)$",
    ),
):
    try:
        youtube, analytics = get_services()

        (
            metadata,
            start_date,
            end_date,
            complete,
        ) = resolve_video_window(
            youtube,
            video_id,
            window,
        )

        if end_date < start_date:
            return {
                **metadata,
                "window": window,
                "window_complete": complete,
                "sources": [],
            }

        report = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            dimensions="insightTrafficSourceType",
            metrics="views,estimatedMinutesWatched",
            filters=f"video=={video_id}",
            sort="-views",
            maxResults=50,
        ).execute()

        headers = [
            column["name"]
            for column in report.get("columnHeaders", [])
        ]

        rows = [
            dict(zip(headers, row))
            for row in report.get("rows", [])
        ]

        total_views = sum(
            int(row.get("views", 0))
            for row in rows
        )

        sources = []

        for row in rows:
            source_type = str(
                row.get("insightTrafficSourceType", "")
            )
            views = int(row.get("views", 0))

            sources.append({
                "source_type": source_type,
                "source_label": TRAFFIC_SOURCE_LABELS.get(
                    source_type,
                    source_type.replace("_", " ").title(),
                ),
                "views": views,
                "share_of_views_percent": (
                    round(views / total_views * 100, 2)
                    if total_views
                    else 0
                ),
                "watch_hours": round(
                    float(
                        row.get(
                            "estimatedMinutesWatched",
                            0,
                        )
                    ) / 60,
                    2,
                ),
            })

        return {
            **metadata,
            "window": window,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "window_complete": complete,
            "total_views_in_report": total_views,
            "sources": sources,
        }

    except HttpError as error:
        raise HTTPException(
            status_code=502,
            detail=f"YouTube API error: {error}",
        ) from error


# --- JIMPORTS AUDIT LAYER V1 ---

from app.audit_layer import (
    TRAFFIC_SOURCE_MAPPING_VERSION,
    VALIDATED_TRAFFIC_SOURCE_LABELS,
    boolean_check,
    overall_status,
    reconciliation_check,
    traffic_source_label,
)


@app.get(
    "/video/{video_id}/subscribed-status",
    operation_id="getVideoSubscribedStatus",
    summary="Get views from subscribed and unsubscribed viewers",
    dependencies=[Depends(require_api_key)],
)
def video_subscribed_status(
    video_id: str,
    window: str = Query(
        default="lifetime",
        pattern="^(7|28|lifetime)$",
    ),
):
    try:
        youtube, analytics = get_services()

        (
            metadata,
            start_date,
            end_date,
            complete,
        ) = resolve_video_window(
            youtube,
            video_id,
            window,
        )

        if end_date < start_date:
            return {
                **metadata,
                "window": window,
                "window_complete": complete,
                "viewer_statuses": [],
            }

        report = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            dimensions="subscribedStatus",
            metrics=(
                "views,estimatedMinutesWatched,"
                "averageViewDuration,averageViewPercentage"
            ),
            filters=f"video=={video_id}",
        ).execute()

        headers = [
            column["name"]
            for column in report.get("columnHeaders", [])
        ]

        rows = [
            dict(zip(headers, row))
            for row in report.get("rows", [])
        ]

        total_views = sum(
            int(row.get("views", 0))
            for row in rows
        )

        viewer_statuses = []

        for row in rows:
            status = str(row.get("subscribedStatus", "UNKNOWN"))
            views = int(row.get("views", 0))

            viewer_statuses.append({
                "subscribed_status": status,
                "views": views,
                "share_of_views_percent": (
                    round(views / total_views * 100, 2)
                    if total_views
                    else 0
                ),
                "watch_hours": round(
                    float(
                        row.get("estimatedMinutesWatched", 0)
                    ) / 60,
                    2,
                ),
                "average_view_duration_seconds": round(
                    float(row.get("averageViewDuration", 0)),
                    1,
                ),
                "average_percentage_viewed": round(
                    float(row.get("averageViewPercentage", 0)),
                    2,
                ),
            })

        viewer_statuses.sort(
            key=lambda value: value["views"],
            reverse=True,
        )

        return {
            **metadata,
            "window": window,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "window_complete": complete,
            "total_views_in_report": total_views,
            "viewer_statuses": viewer_statuses,
        }

    except HttpError as error:
        raise HTTPException(
            status_code=502,
            detail=f"YouTube API error: {error}",
        ) from error


@app.get(
    "/video/{video_id}/audit",
    operation_id="auditVideo",
    summary=(
        "Audit one video's performance, traffic, subscriber status, "
        "and retention before strategic interpretation"
    ),
    dependencies=[Depends(require_api_key)],
)
def audit_video(
    video_id: str,
    window: str = Query(
        default="lifetime",
        pattern="^(7|28|lifetime)$",
    ),
):
    performance = video_performance(
        video_id=video_id,
        window=window,
    )

    traffic = video_traffic_sources(
        video_id=video_id,
        window=window,
    )

    retention = video_retention(
        video_id=video_id,
        window=window,
    )

    subscriber_status = video_subscribed_status(
        video_id=video_id,
        window=window,
    )

    performance_views = int(performance.get("views", 0))
    traffic_views = int(
        traffic.get("total_views_in_report", 0)
    )
    subscriber_status_views = int(
        subscriber_status.get("total_views_in_report", 0)
    )

    audited_sources = []
    unknown_source_codes = []

    for source in traffic.get("sources", []):
        raw_code = str(
            source.get("source_type", "")
        )

        if raw_code not in VALIDATED_TRAFFIC_SOURCE_LABELS:
            unknown_source_codes.append(raw_code)

        audited_sources.append({
            **source,
            "raw_source_code": raw_code,
            "studio_label": traffic_source_label(raw_code),
            "mapping_version": TRAFFIC_SOURCE_MAPPING_VERSION,
        })

    periods = {
        (
            performance.get("period_start"),
            performance.get("period_end"),
        ),
        (
            traffic.get("period_start"),
            traffic.get("period_end"),
        ),
        (
            retention.get("period_start"),
            retention.get("period_end"),
        ),
        (
            subscriber_status.get("period_start"),
            subscriber_status.get("period_end"),
        ),
    }

    retention_points = retention.get("points", [])

    relative_values = [
        point.get("relative_retention_score")
        for point in retention_points
        if point.get("relative_retention_score") is not None
    ]

    relative_values_valid = all(
        0 <= float(value) <= 1
        for value in relative_values
    )

    checks = [
        reconciliation_check(
            "Traffic-source views reconcile to video views",
            performance_views,
            traffic_views,
        ),
        reconciliation_check(
            "Subscribed-status views reconcile to video views",
            performance_views,
            subscriber_status_views,
        ),
        boolean_check(
            "Reporting periods match",
            len(periods) == 1,
            (
                f"Observed reporting periods: "
                f"{sorted(str(value) for value in periods)}"
            ),
        ),
        boolean_check(
            "Traffic-source codes are validated",
            not unknown_source_codes,
            (
                "Unknown codes: "
                + ", ".join(unknown_source_codes)
                if unknown_source_codes
                else (
                    "All traffic-source codes use the validated "
                    f"{TRAFFIC_SOURCE_MAPPING_VERSION} mapping."
                )
            ),
            failure_status="WARN",
        ),
        boolean_check(
            "Retention curve returned",
            bool(retention_points),
            f"Retention point count: {len(retention_points)}",
        ),
        boolean_check(
            "Relative-retention values are valid",
            bool(relative_values) and relative_values_valid,
            (
                "relativeRetentionPerformance values must be "
                "between 0 and 1."
            ),
        ),
    ]

    status = overall_status(checks)

    return {
        "audit_status": status,
        "video_id": video_id,
        "title": performance.get("title"),
        "window": window,
        "window_complete": performance.get("window_complete"),
        "period_start": performance.get("period_start"),
        "period_end": performance.get("period_end"),
        "data_quality_checks": checks,
        "verified_data": {
            "performance": performance,
            "traffic_sources": {
                "mapping_version": (
                    TRAFFIC_SOURCE_MAPPING_VERSION
                ),
                "total_views_in_report": traffic_views,
                "sources": audited_sources,
            },
            "viewer_subscription_status": subscriber_status,
            "retention_checkpoints": retention.get("summary", {}),
            "retention_point_count": len(retention_points),
        },
        "interpretation_rules": [
            (
                "Traffic-source code SUBSCRIBER means Browse "
                "features, including homepage feeds and subscription "
                "features. It does not identify whether the viewer "
                "was subscribed."
            ),
            (
                "Use viewer_subscription_status for subscribed versus "
                "unsubscribed viewers."
            ),
            (
                "Use relative_retention_score to benchmark a retention "
                "checkpoint against similarly sized YouTube videos. "
                "A value of 0.5 is the median."
            ),
            (
                "A retention curve identifies when viewers stopped, "
                "rewatched, or skipped. It does not prove why."
            ),
            (
                "Determining the likely editorial cause of a decline "
                "requires reviewing the footage at that timestamp."
            ),
        ],
        "recommendation_allowed": status in {"PASS", "WARN"},
    }
