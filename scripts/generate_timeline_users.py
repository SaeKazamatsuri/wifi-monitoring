import argparse
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .wifi_log_utils import load_logs, load_members


def build_timeline_matrix(df: pd.DataFrame, members_df: pd.DataFrame) -> tuple[np.ndarray, List[str], List[str]]:
    timestamps = sorted(df["timestamp"].unique())
    timestamp_labels = [pd.to_datetime(ts).strftime("%H:%M") for ts in timestamps]

    member_order = members_df["mac"].tolist()
    member_labels = members_df["name"].tolist()

    matrix = np.zeros((len(member_order), len(timestamps)))
    pivot = df.pivot_table(index="mac", columns="timestamp", values="connected", fill_value=0)

    for row_idx, mac in enumerate(member_order):
        if mac in pivot.index:
            matrix[row_idx, :] = pivot.loc[mac, timestamps].to_numpy()

    return matrix, member_labels, timestamp_labels


def render_timeline(matrix: np.ndarray, member_labels: List[str], time_labels: List[str], output_path: Path) -> None:
    height = max(6, len(member_labels) * 0.4)
    width = max(8, len(time_labels) * 0.3)
    fig, ax = plt.subplots(figsize=(width, height))
    im = ax.imshow(matrix, aspect="auto", cmap="Blues", vmin=0, vmax=1)
    ax.set_yticks(range(len(member_labels)))
    ax.set_yticklabels(member_labels)
    step = max(1, len(time_labels) // 12)
    x_ticks = list(range(0, len(time_labels), step))
    ax.set_xticks(x_ticks)
    ax.set_xticklabels([time_labels[i] for i in x_ticks], rotation=45, ha="right")
    ax.set_xlabel("Time")
    ax.set_ylabel("Members")
    ax.set_title("Member Connectivity Timeline (Mode B)")
    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.04)
    cbar.set_ticks([0, 1])
    cbar.set_ticklabels(["Offline", "Online"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate member timeline (Mode B)")
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"), help="Directory containing log CSVs")
    parser.add_argument("--members", type=Path, default=Path("data/members.json"), help="Members JSON")
    parser.add_argument("--output", type=Path, default=Path("output/timeline_users.png"), help="Output image path")
    args = parser.parse_args()

    logs = load_logs(args.log_dir)
    members = load_members(args.members)
    merged = logs.merge(members, on="mac", how="left").sort_values("timestamp")
    merged["name"] = merged["name"].fillna(merged["mac"])
    matrix, member_labels, time_labels = build_timeline_matrix(merged, members)
    render_timeline(matrix, member_labels, time_labels, args.output)


if __name__ == "__main__":
    main()
