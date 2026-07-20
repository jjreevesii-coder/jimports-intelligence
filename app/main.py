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
    version="1.0.0",
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
