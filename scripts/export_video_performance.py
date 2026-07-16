import csv
import os
from datetime import date, timedelta

import isodate
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

TOKEN_FILE = "token.json"
OUTPUT_FILE = "jimports_video_performance.csv"

credentials = None

if os.path.exists(TOKEN_FILE):
    credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

if not credentials or not credentials.valid:
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json",
            SCOPES,
        )
        credentials = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as token:
        token.write(credentials.to_json())

youtube = build("youtube", "v3", credentials=credentials)
analytics = build("youtubeAnalytics", "v2", credentials=credentials)

start_date = "2024-01-01"
end_date = (date.today() - timedelta(days=1)).isoformat()

report = analytics.reports().query(
    ids="channel==MINE",
    startDate=start_date,
    endDate=end_date,
    dimensions="video",
    metrics=(
        "views,estimatedMinutesWatched,averageViewDuration,"
        "averageViewPercentage,subscribersGained,subscribersLost"
    ),
    sort="-views",
    maxResults=200,
).execute()

headers = [column["name"] for column in report.get("columnHeaders", [])]

analytics_rows = [
    dict(zip(headers, row))
    for row in report.get("rows", [])
]

video_ids = [row["video"] for row in analytics_rows]
metadata = {}

for index in range(0, len(video_ids), 50):
    batch = video_ids[index:index + 50]

    response = youtube.videos().list(
        part="snippet,contentDetails",
        id=",".join(batch),
    ).execute()

    for item in response.get("items", []):
        duration = isodate.parse_duration(
            item["contentDetails"]["duration"]
        ).total_seconds()

        metadata[item["id"]] = {
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "duration_seconds": int(duration),
        }

output_rows = []

for row in analytics_rows:
    video_id = row["video"]
    info = metadata.get(video_id, {})

    output_rows.append({
        "video_id": video_id,
        "title": info.get("title", "Unknown or deleted video"),
        "published_at": info.get("published_at", ""),
        "duration_seconds": info.get("duration_seconds", ""),
        "views": row.get("views", 0),
        "watch_hours": round(
            row.get("estimatedMinutesWatched", 0) / 60,
            2,
        ),
        "average_view_duration_seconds": round(
            row.get("averageViewDuration", 0),
            1,
        ),
        "average_percentage_viewed": round(
            row.get("averageViewPercentage", 0),
            2,
        ),
        "subscribers_gained": row.get("subscribersGained", 0),
        "subscribers_lost": row.get("subscribersLost", 0),
        "net_subscribers": (
            row.get("subscribersGained", 0)
            - row.get("subscribersLost", 0)
        ),
    })

fieldnames = [
    "video_id",
    "title",
    "published_at",
    "duration_seconds",
    "views",
    "watch_hours",
    "average_view_duration_seconds",
    "average_percentage_viewed",
    "subscribers_gained",
    "subscribers_lost",
    "net_subscribers",
]

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as csv_file:
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(output_rows)

print()
print(f"Exported {len(output_rows)} videos to:")
print(os.path.abspath(OUTPUT_FILE))
print()
print("Top 10 videos by views:")
print()

for row in output_rows[:10]:
    print(
        f'{row["views"]:>9,} views | '
        f'{row["average_percentage_viewed"]:>5.1f}% viewed | '
        f'{row["net_subscribers"]:>5} net subs | '
        f'{row["title"]}'
    )
