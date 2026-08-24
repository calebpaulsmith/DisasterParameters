"""Re-render out/board.html from the existing out/board_data.json (no re-parse).

Use after template-only edits: python rehtml.py
"""
from pathlib import Path

base = Path(__file__).resolve().parent
data = (base / "out" / "board_data.json").read_text(encoding="utf-8")
tpl = (base / "templates" / "board.html").read_text(encoding="utf-8")
(base / "out" / "board.html").write_text(
    tpl.replace("/*__BOARD_DATA__*/null", data), encoding="utf-8")
print("re-rendered out/board.html")
