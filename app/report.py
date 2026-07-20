from pathlib import Path
import pandas as pd

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "jimports_video_performance.csv"


def print_section(title, rows, columns):
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)

    for _, row in rows.iterrows():
        parts = [f"{column}: {row[column]}" for column in columns]
        print(" | ".join(parts))


def main():
    if not DATA_FILE.exists():
        raise SystemExit(
            f"Missing data file: {DATA_FILE}\n"
            "Run the YouTube export script first."
        )

    df = pd.read_csv(DATA_FILE)

    numeric_columns = [
        "views",
        "average_percentage_viewed",
        "net_subscribers",
        "duration_seconds",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    df["subs_per_1000_views"] = (
        df["net_subscribers"] / df["views"].replace(0, pd.NA) * 1000
    ).fillna(0).round(2)

    df["runtime_minutes"] = (df["duration_seconds"] / 60).round(1)

    print()
    print("JIMPORTS CHANNEL REPORT")
    print(f"Videos analyzed: {len(df)}")
    print(f"Total views represented: {int(df['views'].sum()):,}")
    print(f"Net subscribers represented: {int(df['net_subscribers'].sum()):,}")

    top_views = df.nlargest(10, "views").copy()
    top_views["views"] = top_views["views"].map(lambda x: f"{int(x):,}")

    print_section(
        "TOP 10 BY VIEWS",
        top_views,
        ["views", "average_percentage_viewed", "net_subscribers", "title"],
    )

    top_subs = df.nlargest(10, "net_subscribers").copy()
    top_subs["views"] = top_subs["views"].map(lambda x: f"{int(x):,}")

    print_section(
        "TOP 10 SUBSCRIBER GENERATORS",
        top_subs,
        ["net_subscribers", "views", "subs_per_1000_views", "title"],
    )

    established = df[df["views"] >= 10000].copy()

    efficient = established.nlargest(10, "subs_per_1000_views")

    print_section(
        "BEST SUBSCRIBER CONVERSION — MINIMUM 10,000 VIEWS",
        efficient,
        ["subs_per_1000_views", "views", "net_subscribers", "title"],
    )

    long_form = established[df["duration_seconds"] >= 300].copy()
    retention = long_form.nlargest(10, "average_percentage_viewed")

    print_section(
        "BEST LONG-FORM RETENTION — MINIMUM 10,000 VIEWS",
        retention,
        ["average_percentage_viewed", "runtime_minutes", "views", "title"],
    )

    weakest = long_form.nsmallest(10, "average_percentage_viewed")

    print_section(
        "WEAKEST LONG-FORM RETENTION — MINIMUM 10,000 VIEWS",
        weakest,
        ["average_percentage_viewed", "runtime_minutes", "views", "title"],
    )


if __name__ == "__main__":
    main()
