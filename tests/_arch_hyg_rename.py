from __future__ import annotations

import json
import os

__all__ = ["RENAME_FILE", "RENAME_SPECS", "renames", "renamed", "rename_ref_errors"]

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arch_baseline")


RENAME_FILE = "hyg_rename.json"
RENAME_SPECS = ("hyg_tests", "hyg_checks")


def renames() -> dict:
    p = os.path.join(BASE_DIR, RENAME_FILE)
    if os.path.islink(p):
        raise ValueError(f"{RENAME_FILE} 이 심볼릭 링크 — 실제 파일이어야 함")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        table = json.load(f).get("renames")
    bad = _rename_errors(table)
    if bad:
        raise ValueError(f"{RENAME_FILE} 표 오류(1:1 · 사슬 금지 · test_*.py): {bad[:4]}")
    return dict(table)


def _rename_errors(table) -> list[str]:
    if not isinstance(table, dict):
        return [f"표가 dict 아님: {type(table).__name__}"]
    news = list(table.values())
    ok = lambda x: isinstance(x, str) and x.startswith("test_") and x.endswith(".py") and "/" not in x  # noqa: E731
    return [f"{o} → {n}" for o, n in sorted(table.items(), key=str)
            if not (ok(o) and ok(n) and o != n and news.count(n) == 1 and n not in table and o not in news)]


def rename_ref_errors(table: dict, ref_table: dict | None, ref_tests: set) -> list[str]:
    bad = [f"기준 커밋 표 줄을 지우거나 바꿈: {o} → {n}" for o, n in sorted((ref_table or {}).items()) if table.get(o) != n]
    bad += [f"{o} → {n}: 새 이름이 기준 커밋에 이미 있는 파일(이름 바꾸기가 아님)" for o, n in sorted(table.items())
            if o in ref_tests and n in ref_tests]
    return bad


def renamed(spec, doc: dict, present: set, table: dict | None = None, absent: set | None = None) -> dict:
    if spec.name not in RENAME_SPECS:
        return doc
    table = renames() if table is None else table
    absent = present if absent is None else absent
    items = dict(doc["items"])
    for o, n in table.items():
        if o in items and n not in items and o not in absent and n in present:
            items[n] = items.pop(o)
    return dict(doc, items=items) if items != doc["items"] else doc
