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

## server.py の使い方
- 起動: `python server.py`
  - `http://localhost:8000` で管理画面を表示
  - 起動時に `config.json` と `data/members.json` を読み込み、バックグラウンドで監視を開始
  - `data/` と `output/` は自動作成されます
- 開発時の起動例: `uvicorn server:app --host 0.0.0.0 --port 8000 --reload`
- 主なAPI:
  - `GET /api/members` 登録メンバー一覧
  - `POST /api/members` メンバー追加/更新 (`mac` は `:`/`-` どちらでも可)
  - `GET /api/logs/latest` 最新スナップショット
  - `GET /api/heatmap` ヒートマップ用データ
  - `GET /api/health` ヘルスチェック

## Pythonファイルの役割
- `main.py` : ルーターHTMLの取得→接続端末の解析→ログCSV出力を行うCLI本体
- `server.py` : FastAPIの管理画面/API。起動時に監視スレッドを立ち上げ、メンバー管理やヒートマップを提供
- `scripts/wifi_log_utils.py` : ログ/メンバーJSONをpandasで読み込む共通ユーティリティ
- `scripts/generate_heatmap_total.py` : ログCSVから全体ヒートマップPNGを生成
- `scripts/generate_timeline_users.py` : ユーザー別の接続タイムラインPNGを生成
- `scripts/extract_router_table.py` : ルーター管理画面HTMLから端末一覧CSVを抽出
- `scripts/__init__.py` : scripts パッケージを示す空ファイル
- `tmp_lineinfo.py` : テンプレート内の文字列位置を探す一時スクリプト (開発補助)

## 主要な入出力
- ログ: `data/logs/*.csv` (timestamp, mac, connected)
- 未登録端末: `data/unknown.csv`
- 無線端末スナップショット: `data/wireless.csv`
- 画像出力: `output/` 以下にヒートマップ/タイムラインPNG
