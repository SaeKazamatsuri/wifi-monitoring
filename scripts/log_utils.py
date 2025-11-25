from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pandas as pd


def load_logs(log_dir: Path) -> pd.DataFrame:
    csv_files = sorted(log_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV logs found in {log_dir}")

    frames: List[pd.DataFrame] = []
    for csv_file in csv_files:
        frame = pd.read_csv(csv_file, parse_dates=["timestamp"])
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    data["mac"] = data["mac"].str.strip().str.upper()
    return data


def load_members(members_path: Path) -> pd.DataFrame:
    with members_path.open(encoding="utf-8-sig") as f:
        data = json.load(f)
    frame = pd.DataFrame(data)
    frame["mac"] = frame["mac"].str.strip().str.upper()
    return frame
