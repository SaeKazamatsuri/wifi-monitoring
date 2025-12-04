import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .wifi_log_utils import load_logs


def build_heatmap_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    df["time"] = df["timestamp"].dt.strftime("%H:%M")
    connected = df[df["connected"] == 1]
    counts = connected.groupby(["date", "time"]).size().reset_index(name="count")
    pivot = counts.pivot(index="date", columns="time", values="count").fillna(0)
    pivot.sort_index(inplace=True)
    pivot = pivot.reindex(sorted(pivot.columns, key=lambda x: pd.to_datetime(x, format="%H:%M")), axis=1)
    return pivot


def render_heatmap(pivot: pd.DataFrame, output_path: Path, max_members: int) -> None:
    plt.figure(figsize=(max(8, pivot.shape[1] * 0.4), max(4, pivot.shape[0] * 0.5)))
    sns.heatmap(
        pivot,
        cmap="YlGnBu",
        vmin=0,
        vmax=max_members,
        cbar_kws={"label": "Connected members"},
        linewidths=0.5,
        linecolor="white",
    )
    plt.ylabel("Date")
    plt.xlabel("Time")
    plt.xticks(rotation=45, ha="right")
    plt.title("Wi-Fi Utilization (Mode A)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate utilization heatmap (Mode A)")
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"), help="Directory containing log CSVs")
    parser.add_argument("--output", type=Path, default=Path("output/heatmap_total.png"), help="Output image path")
    parser.add_argument("--max-members", type=int, default=30, help="Maximum number of members for color scaling")
    args = parser.parse_args()

    df = load_logs(args.log_dir)
    pivot = build_heatmap_dataframe(df)
    render_heatmap(pivot, args.output, args.max_members)


if __name__ == "__main__":
    main()
