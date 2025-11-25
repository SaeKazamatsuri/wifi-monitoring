from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

from bs4 import BeautifulSoup
from bs4.element import Tag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NETGEARのクライアント一覧テーブル(#target > table > tbody > tr[2])をCSVへ出力します。"
    )
    parser.add_argument("--html", type=Path, required=True, help="NETGEAR管理画面のHTMLファイル")
    parser.add_argument("--output", type=Path, required=True, help="CSVの出力先パス")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html_text = args.html.read_text(encoding="utf-8")
    rows = extract_rows(html_text)
    if not rows:
        raise RuntimeError("有効な機器情報が見つかりませんでした。")
    write_csv(args.output, rows)


def extract_rows(html_text: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    target_form = soup.find(id="target")
    if target_form is None:
        raise ValueError("id='target' のフォームが見つかりません。")

    outer_table = target_form.find("table")
    if outer_table is None:
        raise ValueError("#target 直下にテーブルが存在しません。")

    tbody = outer_table.find("tbody") or outer_table
    rows = tbody.find_all("tr")
    if len(rows) < 2:
        raise ValueError("対象テーブルに2行目が存在しません。")

    target_row = rows[1]
    device_tables = target_row.find_all("table")
    extracted: List[Dict[str, str]] = []
    for table in device_tables:
        header = table.find("tr")
        if header is None:
            continue
        header_text = " ".join(header.stripped_strings)
        if "MAC" not in header_text.upper():
            continue
        section_label = find_section_label(table)
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            mac = normalize_mac_text(cells[3].get_text(strip=True))
            if not mac:
                continue
            extracted.append(
                {
                    "section": section_label,
                    "number": normalize_text(cells[0].get_text(strip=True)),
                    "ip": normalize_text(cells[1].get_text(strip=True)),
                    "device_name": normalize_text(cells[2].get_text(strip=True)),
                    "mac": mac,
                }
            )
    return extracted


def find_section_label(table: Tag) -> str:
    heading = table.find_previous("b")
    if heading:
        return heading.get_text(strip=True)
    return ""


def normalize_text(value: str) -> str:
    cleaned = value.strip()
    if cleaned in {"", "--", "&nbsp;"}:
        return ""
    return cleaned


def normalize_mac_text(value: str) -> str:
    cleaned = normalize_text(value).replace("-", ":").upper()
    return cleaned


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "number", "ip", "device_name", "mac"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
