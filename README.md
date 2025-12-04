# Wi-Fi Monitoring

Python製のWi-Fiクライアント監視ツールです。NETGEARルーターのステータスページから接続情報を取得し、CSVに蓄積した上で可視化・API提供を行います。

## セットアップ
- 推奨: Python 3.11 以降で仮想環境を作成 (`python -m venv .venv` → 有効化)。
- 依存関係をインストール: `pip install -r requirements.txt`
- 設定ファイルを用意: `config.example.json` を参考に `config.json` を配置。
  - `auth_method`: `basic` / `digest` / `auto` を選択可能。ルーターがDigest認証のみ受け付ける場合は `digest` か `auto` にする。
- メンバー一覧を準備: `data/members.json` を UTF-8 (BOM可) で作成。

## 使い方
- クライアント監視 (CLI): `python main.py --config config.json --members data/members.json`
  - `--once` で1回だけ取得、`--html-file` で保存済みHTMLを解析可能。
  - ログ取得間隔は分単位で00分起点の固定サイクル（デフォルト15分）。`--interval-minutes` で変更可能。
- Web API/管理画面 (FastAPI): `python server.py` → `http://localhost:8000` を開く。
- 解析スクリプト (scripts/):
  - `generate_heatmap_total.py` : 利用状況ヒートマップをPNG出力。
  - `generate_timeline_users.py` : ユーザー別タイムライン画像を出力。
  - `extract_router_table.py` : 保存したルーターHTMLからテーブルをCSV化。

## 主要な入出力
- ログ: `data/logs/*.csv` (timestamp, mac, connected)
- 未登録端末: `data/unknown.csv`
- 無線端末スナップショット: `data/wireless.csv`
- 画像出力: `output/` 以下にヒートマップ/タイムラインPNG

## 開発メモ
- 型チェック: `python -m mypy --ignore-missing-imports main.py server.py`
- テンプレート: `templates/index.html` を FastAPI の `Jinja2Templates` で配信。
- 依存ライブラリは `requirements.txt` を参照してください。
