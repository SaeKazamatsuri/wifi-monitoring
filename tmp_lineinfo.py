from pathlib import Path


def show_lines(path: str, targets: list[str]) -> None:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for target in targets:
        for idx, line in enumerate(lines, start=1):
            if target in line:
                print(f"{path}: {target} -> {idx}")
                break


show_lines(
    "templates/index.html",
    [
        "Wi-Fiモニターダッシュボード",
        "メンバー登録",
        "登録済みメンバー",
        "最新スナップショット",
        "ヒートマップ",
        "登録処理中...",
        "ログがまだありません。",
        "ヒートマップを描画できるデータがありません。",
    ],
)
