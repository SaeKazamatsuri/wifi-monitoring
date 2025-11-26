from __future__ import annotations

import csv
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator

from main import RouterMonitor, load_config


DATA_DIR = Path("data")
MEMBERS_PATH = DATA_DIR / "members.json"
LOG_DIR = DATA_DIR / "logs"
TEMPLATES_DIR = Path(__file__).parent / "templates"
CONFIG_PATH = Path("config.json")
OUTPUT_DIR = Path("output")
HEATMAP_OUTPUT_PATH = OUTPUT_DIR / "heatmap_total.png"
UNKNOWN_LOG_PATH = DATA_DIR / "unknown.csv"
WIRELESS_LOG_PATH = DATA_DIR / "wireless.csv"

MAC_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")
MEMBERS_LOCK = threading.Lock()

app = FastAPI(title="Wi-Fi Monitor Admin API", version="1.0.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
logger = logging.getLogger("wifi_monitor.server")

MONITOR_THREAD: Optional[threading.Thread] = None
MONITOR_INSTANCE: Optional[RouterMonitor] = None
MONITOR_LOCK = threading.Lock()


class MemberRecord(BaseModel):
    student_id: Optional[str] = Field(default=None, description="Student identifier")
    name: str
    mac: str


class MemberCreate(BaseModel):
    student_id: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    mac: str

    @validator("mac")
    def validate_mac(cls, value: str) -> str:
        normalized = normalize_mac(value)
        return normalized


class HeatmapResponse(BaseModel):
    dates: List[str]
    times: List[str]
    matrix: List[List[int]]
    max_value: int


def normalize_mac(mac: str) -> str:
    cleaned = mac.strip().replace("-", ":").upper()
    if not MAC_PATTERN.fullmatch(cleaned):
        raise ValueError(f"Invalid MAC address: {mac}")
    return cleaned


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MEMBERS_PATH.touch(exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_monitor_running() -> None:
    global MONITOR_THREAD, MONITOR_INSTANCE
    with MONITOR_LOCK:
        if MONITOR_THREAD and MONITOR_THREAD.is_alive():
            return
        try:
            config = load_config(CONFIG_PATH)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("監視スレッドの初期化に失敗しました: %s", exc)
            return
        members = read_members()
        monitor = RouterMonitor(
            config=config,
            members=members,
            log_dir=LOG_DIR,
            unknown_log=UNKNOWN_LOG_PATH,
            wireless_log=WIRELESS_LOG_PATH,
            members_loader=read_members,
            heatmap_output=HEATMAP_OUTPUT_PATH,
        )
        thread = threading.Thread(target=monitor.run_forever, daemon=True, name="router-monitor")
        thread.start()
        MONITOR_THREAD = thread
        MONITOR_INSTANCE = monitor
        logger.info("監視スレッドを開始しました（間隔: %ss）", monitor.config.interval_seconds)


def read_members() -> List[Dict[str, str]]:
    ensure_data_dirs()
    if MEMBERS_PATH.stat().st_size == 0:
        return []
    with MEMBERS_PATH.open(encoding="utf-8-sig") as f:
        data = json.load(f)
    members: List[Dict[str, str]] = []
    for entry in data:
        record = {
            "student_id": entry.get("student_id"),
            "name": entry.get("name", ""),
            "mac": normalize_mac(entry["mac"]),
        }
        members.append(record)
    return members


def write_members(members: List[Dict[str, str]]) -> None:
    MEMBERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MEMBERS_PATH.open("w", encoding="utf-8") as f:
        json.dump(members, f, indent=2, ensure_ascii=False)


def upsert_member(new_member: MemberCreate) -> Dict[str, str]:
    with MEMBERS_LOCK:
        members = read_members()
        existing = None
        for entry in members:
            if entry["mac"] == new_member.mac:
                existing = entry
                break
        if existing:
            existing["name"] = new_member.name
            existing["student_id"] = new_member.student_id
        else:
            members.append(new_member.dict())
        members.sort(key=lambda item: item["name"].lower())
        write_members(members)
        return new_member.dict()


def iter_log_rows() -> List[Dict[str, str]]:
    ensure_data_dirs()
    csv_files = sorted(LOG_DIR.glob("*.csv"))
    rows: List[Dict[str, str]] = []
    for csv_file in csv_files:
        with csv_file.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamp = row.get("timestamp")
                mac = row.get("mac")
                connected = row.get("connected")
                if not timestamp or not mac or connected is None:
                    continue
                try:
                    normalized_mac = normalize_mac(mac)
                except ValueError:
                    continue
                rows.append(
                    {
                        "timestamp": timestamp,
                        "mac": normalized_mac,
                        "connected": int(connected),
                    }
                )
    return rows


def build_latest_snapshot() -> Optional[Dict[str, object]]:
    csv_files = sorted(LOG_DIR.glob("*.csv"))
    if not csv_files:
        return None
    latest_file = csv_files[-1]
    rows: List[Dict[str, str]] = []
    with latest_file.open(newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        if not reader:
            return None
        last_timestamp = reader[-1]["timestamp"]
        for row in reader:
            if row["timestamp"] == last_timestamp:
                try:
                    normalized_mac = normalize_mac(row["mac"])
                except ValueError:
                    continue
                rows.append(
                    {
                        "timestamp": row["timestamp"],
                        "mac": normalized_mac,
                        "connected": int(row["connected"]),
                    }
                )
    members_by_mac = {member["mac"]: member for member in read_members()}
    enriched = []
    for row in rows:
        member = members_by_mac.get(row["mac"])
        enriched.append(
            {
                "mac": row["mac"],
                "connected": row["connected"],
                "name": member["name"] if member else None,
                "student_id": member.get("student_id") if member else None,
            }
        )
    return {"timestamp": rows[0]["timestamp"] if rows else None, "entries": enriched}


def build_heatmap_payload() -> HeatmapResponse:
    rows = iter_log_rows()
    if not rows:
        return HeatmapResponse(dates=[], times=[], matrix=[], max_value=0)
    counts: Dict[str, Dict[str, int]] = {}
    all_times: set[str] = set()
    max_value = 0
    for row in rows:
        if row["connected"] != 1:
            continue
        try:
            ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        date_key = ts.date().isoformat()
        time_key = ts.strftime("%H:%M")
        all_times.add(time_key)
        counts.setdefault(date_key, {})
        counts[date_key][time_key] = counts[date_key].get(time_key, 0) + 1
        if counts[date_key][time_key] > max_value:
            max_value = counts[date_key][time_key]
    if not counts:
        return HeatmapResponse(dates=[], times=[], matrix=[], max_value=0)
    dates = sorted(counts.keys())
    times = sorted(all_times)
    matrix: List[List[int]] = []
    for date in dates:
        row_values = []
        for time in times:
            row_values.append(counts.get(date, {}).get(time, 0))
        matrix.append(row_values)
    return HeatmapResponse(dates=dates, times=times, matrix=matrix, max_value=max_value)


@app.on_event("startup")
async def on_startup() -> None:
    ensure_data_dirs()
    ensure_monitor_running()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/members", response_model=List[MemberRecord])
async def api_get_members() -> List[MemberRecord]:
    return [MemberRecord(**member) for member in read_members()]


@app.post("/api/members", status_code=status.HTTP_201_CREATED, response_model=MemberRecord)
async def api_create_member(payload: MemberCreate) -> MemberRecord:
    try:
        saved = upsert_member(payload)
        if MONITOR_INSTANCE:
            MONITOR_INSTANCE.refresh_members()
        return MemberRecord(**saved)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.get("/api/logs/latest")
async def api_latest_snapshot() -> Dict[str, object]:
    snapshot = build_latest_snapshot()
    if not snapshot:
        return {"timestamp": None, "entries": []}
    return snapshot


@app.get("/api/heatmap", response_model=HeatmapResponse)
async def api_heatmap() -> HeatmapResponse:
    return build_heatmap_payload()


@app.get("/api/health")
async def api_health() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
