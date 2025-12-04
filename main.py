import argparse
import csv
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Callable, Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_DEVICE_PATH = "DEV_device.htm"
MAC_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}")


@dataclass
class MonitorConfig:
    router_url: str
    username: str
    password: str
    device_path: str = DEFAULT_DEVICE_PATH
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    verify_tls: bool = False


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def load_members(path: Path) -> List[Dict[str, str]]:
    raw_members = load_json(path)
    normalized = []
    for member in raw_members:
        mac = normalize_mac(member["mac"])
        normalized.append({"name": member["name"], "mac": mac})
    return normalized


def normalize_mac(mac: str) -> str:
    cleaned = mac.strip().replace("-", ":").upper()
    if not MAC_PATTERN.fullmatch(cleaned):
        raise ValueError(f"Invalid MAC address: {mac}")
    return cleaned


def load_config(path: Path) -> MonitorConfig:
    data = load_json(path)
    interval_minutes = data.get("interval_minutes")
    if interval_minutes is None:
        legacy_seconds = data.get("interval_seconds")
        if legacy_seconds is not None:
            interval_minutes = max(1, (int(legacy_seconds) + 59) // 60)
    if interval_minutes is None:
        interval_minutes = DEFAULT_INTERVAL_MINUTES
    return MonitorConfig(
        router_url=data["router_url"],
        device_path=data.get("device_path", DEFAULT_DEVICE_PATH),
        username=data["username"],
        password=data["password"],
        interval_minutes=interval_minutes,
        verify_tls=data.get("verify_tls", False),
    )


def fetch_router_page(url: str, username: str, password: str, verify_tls: bool) -> str:
    if not url:
        raise ValueError("Router URL is not configured")
    logging.debug("Fetching router page %s", url)
    response = requests.get(url, auth=(username, password), timeout=15, verify=verify_tls)
    response.raise_for_status()
    return response.text


def resolve_router_url(router_url: str, device_path: str) -> str:
    if not router_url:
        raise ValueError("Router URL is not configured")
    parsed = urlparse(router_url)
    path = parsed.path
    has_file_component = bool(Path(path).suffix) if path else False
    if has_file_component:
        return router_url
    base = router_url if router_url.endswith("/") else f"{router_url}/"
    resolved = urljoin(base, device_path.lstrip("/"))
    logging.debug("Resolved router URL: %s", resolved)
    return resolved


def parse_clients(html: str) -> List[Dict[str, Optional[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    client_rows: List[Dict[str, Optional[str]]] = []
    target_form = soup.find(id="target")
    search_root = target_form or soup
    for table in search_root.find_all("table"):
        header = table.find("tr")
        if header is None:
            continue
        header_text = " ".join(header.stripped_strings).upper()
        if "MAC" not in header_text:
            continue
        section_label = find_section_label(table)
        connection_type = classify_connection(section_label)
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            mac = cells[3].get_text(strip=True)
            if not MAC_PATTERN.fullmatch(mac):
                continue
            client_rows.append(
                {
                    "mac": normalize_mac(mac),
                    "ip": sanitize_cell(cells[1].get_text(strip=True)),
                    "device_name": sanitize_cell(cells[2].get_text(strip=True)),
                    "section": section_label,
                    "connection_type": connection_type,
                }
            )
    return client_rows


def find_section_label(table: Tag) -> Optional[str]:
    heading = table.find_previous("b")
    if heading:
        return heading.get_text(strip=True)
    return None


def classify_connection(section_label: Optional[str]) -> str:
    if not section_label:
        return "unknown"
    label = section_label.strip()
    if "無線" in label:
        return "wireless"
    if "有線" in label:
        return "wired"
    return "unknown"


def sanitize_cell(value: str) -> Optional[str]:
    value = value.strip()
    if value == "--" or value == "":
        return None
    return value


def ensure_log_header(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "mac", "connected"])


def append_rows(path: Path, rows: Iterable[List[str]]) -> None:
    ensure_log_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def append_unknown_rows(path: Path, rows: Iterable[Dict[str, Optional[str]]], timestamp: str) -> None:
    if not rows:
        return
    new_path = Path(path)
    file_exists = new_path.exists()
    new_path.parent.mkdir(parents=True, exist_ok=True)
    with new_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "mac", "ip", "device_name"])
        for row in rows:
            writer.writerow([timestamp, row["mac"], row.get("ip") or "", row.get("device_name") or ""])


def append_wireless_rows(path: Path, rows: Iterable[Dict[str, Optional[str]]], timestamp: str) -> None:
    buffered = list(rows)
    if not buffered:
        return
    new_path = Path(path)
    file_exists = new_path.exists()
    new_path.parent.mkdir(parents=True, exist_ok=True)
    with new_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "mac", "ip", "device_name", "section"])
        for row in buffered:
            writer.writerow(
                [
                    timestamp,
                    row["mac"],
                    row.get("ip") or "",
                    row.get("device_name") or "",
                    row.get("section") or "",
                ]
            )


class RouterMonitor:
    def __init__(
        self,
        config: MonitorConfig,
        members: List[Dict[str, str]],
        log_dir: Path,
        unknown_log: Optional[Path] = None,
        wireless_log: Optional[Path] = None,
        members_loader: Optional[Callable[[], List[Dict[str, str]]]] = None,
        heatmap_output: Optional[Path] = None,
        heatmap_max_members: Optional[int] = None,
    ) -> None:
        self.config = config
        self.log_dir = log_dir
        self.unknown_log = unknown_log
        self.wireless_log = wireless_log
        self.members_loader = members_loader
        self.heatmap_output = heatmap_output
        self.heatmap_max_members = heatmap_max_members
        self._members_lock = threading.Lock()
        self.members: List[Dict[str, str]] = []
        self.member_index: Dict[str, str] = {}
        self.refresh_members(members=members)
        logging.debug("Loaded %d members", len(self.members))

    def refresh_members(self, members: Optional[List[Dict[str, str]]] = None) -> None:
        try:
            if members is None and self.members_loader:
                members = self.members_loader()
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Failed to refresh members: %s", exc)
            return
        if members is None:
            return
        normalized = []
        for member in members:
            mac = member.get("mac")
            name = member.get("name", "")
            if not mac:
                continue
            normalized.append({"mac": mac, "name": name})
        with self._members_lock:
            self.members = normalized
            self.member_index = {member["mac"]: member["name"] for member in normalized}
        logging.debug("Member list refreshed (%d entries)", len(self.members))

    def run_once(self, html_override: Optional[str] = None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if html_override is None:
            resolved_url = resolve_router_url(self.config.router_url, self.config.device_path)
            html = fetch_router_page(
                resolved_url,
                self.config.username,
                self.config.password,
                self.config.verify_tls,
            )
        else:
            html = html_override
        clients = parse_clients(html)
        self._log_snapshot(timestamp, clients)

    def run_forever(self, interval_minutes: Optional[int] = None, html_override: Optional[str] = None) -> None:
        period_minutes = interval_minutes or self.config.interval_minutes
        if period_minutes <= 0:
            raise ValueError("Interval minutes must be positive")
        logging.info("Starting monitor loop (interval=%smin)", period_minutes)
        while True:
            now = datetime.now()
            next_run_at = self._calculate_next_run(now, period_minutes)
            wait_seconds = max((next_run_at - now).total_seconds(), 0)
            if wait_seconds > 0:
                logging.debug("Sleeping %.2fs until next slot %s", wait_seconds, next_run_at)
                time.sleep(wait_seconds)
            try:
                self.run_once(html_override=html_override)
            except Exception as exc:  # pylint: disable=broad-except
                logging.exception("Failed to record snapshot: %s", exc)

    @staticmethod
    def _calculate_next_run(now: datetime, interval_minutes: int) -> datetime:
        remainder = now.minute % interval_minutes
        at_boundary = remainder == 0 and now.second == 0 and now.microsecond == 0
        if at_boundary:
            return now.replace(second=0, microsecond=0)
        minutes_to_add = interval_minutes - remainder
        base = now.replace(second=0, microsecond=0)
        return base + timedelta(minutes=minutes_to_add)

    def _log_snapshot(self, timestamp: str, clients: List[Dict[str, Optional[str]]]) -> None:
        self.refresh_members()
        with self._members_lock:
            members = list(self.members)
            member_index = dict(self.member_index)
        active_macs = {client["mac"] for client in clients if client.get("mac")}
        log_file = self.log_dir / f"{datetime.now():%Y-%m-%d}.csv"
        rows: List[List[str]] = []
        for member in members:
            mac = member["mac"]
            connected = "1" if mac in active_macs else "0"
            rows.append([timestamp, mac, connected])
        append_rows(log_file, rows)
        logging.info("Logged %d members to %s", len(rows), log_file)

        unknown_clients = [client for client in clients if client["mac"] not in member_index]
        if self.unknown_log and unknown_clients:
            append_unknown_rows(self.unknown_log, unknown_clients, timestamp)
            logging.info("Recorded %d unknown clients", len(unknown_clients))

        if self.wireless_log:
            wireless_clients = [client for client in clients if client.get("connection_type") == "wireless"]
            append_wireless_rows(self.wireless_log, wireless_clients, timestamp)
            logging.info("Logged %d wireless clients", len(wireless_clients))
        self._render_heatmap()

    def _render_heatmap(self) -> None:
        if not self.heatmap_output:
            return
        try:
            from scripts.wifi_log_utils import load_logs  # type: ignore
            from scripts.generate_heatmap_total import build_heatmap_dataframe, render_heatmap  # type: ignore
            df = load_logs(self.log_dir)
        except FileNotFoundError:
            logging.debug("Skip heatmap update: no logs yet in %s", self.log_dir)
            return
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Failed to load logs for heatmap: %s", exc)
            return
        if df.empty:
            logging.debug("Skip heatmap update: empty dataframe")
            return
        try:
            pivot = build_heatmap_dataframe(df)
            max_members = self.heatmap_max_members or len(df["mac"].unique()) or len(self.members) or 1
            render_heatmap(pivot, self.heatmap_output, max_members)
            logging.info("Heatmap image updated at %s", self.heatmap_output)
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Failed to render heatmap: %s", exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NETGEAR router client monitor")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config JSON")
    parser.add_argument("--members", type=Path, default=Path("data/members.json"), help="Path to members JSON")
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"), help="Directory for CSV logs")
    parser.add_argument("--unknown-log", type=Path, default=None, help="Optional CSV for unknown clients")
    parser.add_argument("--wireless-log", type=Path, default=None, help="Optional CSV for wireless client snapshots")
    parser.add_argument(
        "--interval-minutes",
        "--interval",
        dest="interval_minutes",
        type=int,
        default=None,
        help="Override interval minutes (aligned to 00 minute cycle)",
    )
    parser.add_argument("--once", action="store_true", help="Run one snapshot and exit")
    parser.add_argument("--html-file", type=Path, default=None, help="Use local HTML file instead of router access")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    parser.add_argument("--heatmap-output", type=Path, default=None, help="Render heatmap PNG after each snapshot")
    parser.add_argument("--heatmap-max-members", type=int, default=None, help="Color scale upper bound for heatmap")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    config: MonitorConfig
    if not args.config.exists():
        if args.html_file:
            logging.warning("Using HTML override without config file %s", args.config)
            config = MonitorConfig(router_url="", username="", password="")
        else:
            raise FileNotFoundError(f"Config file {args.config} not found")
    else:
        config = load_config(args.config)
    members = load_members(args.members)
    monitor = RouterMonitor(
        config=config,
        members=members,
        log_dir=args.log_dir,
        unknown_log=args.unknown_log,
        wireless_log=args.wireless_log,
        members_loader=lambda: load_members(args.members),
        heatmap_output=args.heatmap_output,
        heatmap_max_members=args.heatmap_max_members,
    )

    html_override = None
    if args.html_file:
        html_override = args.html_file.read_text(encoding="utf-8")

    if args.once:
        monitor.run_once(html_override=html_override)
    else:
        monitor.run_forever(interval_minutes=args.interval_minutes, html_override=html_override)


if __name__ == "__main__":
    main()
