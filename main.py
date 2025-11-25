import argparse
import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


DEFAULT_INTERVAL = 180
MAC_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}")


@dataclass
class MonitorConfig:
    router_url: str
    username: str
    password: str
    interval_seconds: int = DEFAULT_INTERVAL
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
    return MonitorConfig(
        router_url=data["router_url"],
        username=data["username"],
        password=data["password"],
        interval_seconds=data.get("interval_seconds", DEFAULT_INTERVAL),
        verify_tls=data.get("verify_tls", False),
    )


def fetch_router_page(url: str, username: str, password: str, verify_tls: bool) -> str:
    if not url:
        raise ValueError("Router URL is not configured")
    logging.debug("Fetching router page %s", url)
    response = requests.get(url, auth=(username, password), timeout=15, verify=verify_tls)
    response.raise_for_status()
    return response.text


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
    ) -> None:
        self.config = config
        self.members = members
        self.log_dir = log_dir
        self.unknown_log = unknown_log
        self.wireless_log = wireless_log
        self.member_index = {member["mac"]: member["name"] for member in members}
        logging.debug("Loaded %d members", len(self.members))

    def run_once(self, html_override: Optional[str] = None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if html_override is None:
            html = fetch_router_page(
                self.config.router_url,
                self.config.username,
                self.config.password,
                self.config.verify_tls,
            )
        else:
            html = html_override
        clients = parse_clients(html)
        self._log_snapshot(timestamp, clients)

    def run_forever(self, interval: Optional[int] = None, html_override: Optional[str] = None) -> None:
        interval_seconds = interval or self.config.interval_seconds
        logging.info("Starting monitor loop (interval=%ss)", interval_seconds)
        while True:
            try:
                self.run_once(html_override=html_override)
            except Exception as exc:  # pylint: disable=broad-except
                logging.exception("Failed to record snapshot: %s", exc)
            time.sleep(interval_seconds)

    def _log_snapshot(self, timestamp: str, clients: List[Dict[str, Optional[str]]]) -> None:
        active_macs = {client["mac"] for client in clients}
        log_file = self.log_dir / f"{datetime.now():%Y-%m-%d}.csv"
        rows = []
        for member in self.members:
            mac = member["mac"]
            connected = 1 if mac in active_macs else 0
            rows.append([timestamp, mac, connected])
        append_rows(log_file, rows)
        logging.info("Logged %d members to %s", len(rows), log_file)

        unknown_clients = [client for client in clients if client["mac"] not in self.member_index]
        if self.unknown_log and unknown_clients:
            append_unknown_rows(self.unknown_log, unknown_clients, timestamp)
            logging.info("Recorded %d unknown clients", len(unknown_clients))

        if self.wireless_log:
            wireless_clients = [client for client in clients if client.get("connection_type") == "wireless"]
            append_wireless_rows(self.wireless_log, wireless_clients, timestamp)
            logging.info("Logged %d wireless clients", len(wireless_clients))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NETGEAR router client monitor")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="Path to config JSON")
    parser.add_argument("--members", type=Path, default=Path("data/members.json"), help="Path to members JSON")
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"), help="Directory for CSV logs")
    parser.add_argument("--unknown-log", type=Path, default=None, help="Optional CSV for unknown clients")
    parser.add_argument("--wireless-log", type=Path, default=None, help="Optional CSV for wireless client snapshots")
    parser.add_argument("--interval", type=int, default=None, help="Override interval seconds")
    parser.add_argument("--once", action="store_true", help="Run one snapshot and exit")
    parser.add_argument("--html-file", type=Path, default=None, help="Use local HTML file instead of router access")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
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
    )

    html_override = None
    if args.html_file:
        html_override = args.html_file.read_text(encoding="utf-8")

    if args.once:
        monitor.run_once(html_override=html_override)
    else:
        monitor.run_forever(interval=args.interval, html_override=html_override)


if __name__ == "__main__":
    main()
