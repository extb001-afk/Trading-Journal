from __future__ import annotations

import ast
import os
import re

from _arch_hyg import _MMDD, _static_text
from _arch_hyg_patch import _name_of

_LEDGER_TABLES = frozenset("meta raw_txs raw_ex raw_observations decisions wallets assets asset_groups exchange_addresses "
                           "postings tx_class transfers positions snapshots journal alerts_sent inbox_offsets raw_rewrites "
                           "exf_late_pending exf_adj_tomb".split())
_SQL_W = re.compile(r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM|ALTER\s+TABLE"
                    r"|DROP\s+(?:TABLE|INDEX)(?:\s+IF\s+EXISTS)?|CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)(?:\s+IF\s+NOT\s+EXISTS)?)"
                    r"\s+(?:[\"`\[]?\w+[\"`\]]?\.)?[\"`\[]?(\w+|\{)", re.I)
DATED = re.compile(r"(?<!\d)(?:20\d\d" + _MMDD + "|" + _MMDD + r")(?!\d)")


def ledger_tables(root: str) -> frozenset:
    p = os.path.join(root, "src", "db.py")
    found = set()
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            found = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", f.read()))
    return _LEDGER_TABLES | found


def writes_ledger(text: str, tables: frozenset) -> bool:
    tree = ast.parse(text)
    for n in ast.walk(tree):
        s = _static_text(n) if isinstance(n, (ast.Constant, ast.JoinedStr)) else None
        if s and any(m.group(1) == "{" or m.group(1).lower() in tables for m in _SQL_W.finditer(s)):
            return True
    calls = {_name_of(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return "Core" in calls and "commit" in calls


def tools_hygiene(root: str) -> dict:
    d = os.path.join(root, "tools")
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    tables = ledger_tables(root)
    writers = []
    for fn in names:
        p = os.path.join(d, fn)
        if fn.endswith(".py") and os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                if writes_ledger(f.read(), tables):
                    writers.append("tools/" + fn)
    dated = ["tools/" + fn for fn in names if os.path.isfile(os.path.join(d, fn)) and DATED.search(fn)]
    return {"ledger_writers": writers, "dated": dated}


def _texts(root: str, top: str, exts: tuple, skip=("__pycache__", "fonts", "tests", "screenshots", "screenshots_v3")) -> list:
    out = []
    for dp, dn, fns in os.walk(os.path.join(root, top)):
        dn[:] = sorted(d for d in dn if d not in skip)
        for fn in sorted(fns):
            if fn.endswith(exts):
                p = os.path.join(dp, fn)
                with open(p, encoding="utf-8", errors="replace") as f:
                    out.append((os.path.relpath(p, root).replace(os.sep, "/"), f.read()))
    return out


def tool_pins(root: str, keys) -> dict:
    live = _texts(root, "src", (".py",)) + _texts(root, "web", (".js", ".html"))
    live += [(r, t) for r, t in _texts(root, "public", (".md",)) if r != "public/CHANGELOG.md"]
    tools = _texts(root, "tools", (".py", ".sh", ".files", ".json", ".txt"))
    pat = {k: re.compile(r"(?<![\w])" + re.escape(os.path.splitext(os.path.basename(k))[0]) + r"(?![\w])") for k in keys}
    why = {k: [r for r, t in live if pat[k].search(t)] for k in keys}
    why = {k: v + [r for r, t in tools if r != k and not DATED.search(os.path.basename(r)) and pat[k].search(t)] for k, v in why.items()}
    changed = True
    while changed:
        changed = False
        for k in keys:
            via = [r for r, t in tools if r != k and r in why and why[r] and r not in why[k] and pat[k].search(t)]
            if via:
                why[k] += via
                changed = True
    return {k: ("이름 고정 — 부르는 곳 " + str(len(v)) + ": " + " · ".join(sorted(v)[:5]) + (" …" if len(v) > 5 else "")) if v else None
            for k, v in why.items()}


def docs_sizes(root: str, readme: str) -> dict:
    out = {"readme": os.path.getsize(readme) if os.path.isfile(readme) else 0, "docs_md": 0, "docs_img": 0}
    d = os.path.join(root, "public", "docs")
    for dp, dn, fns in os.walk(d):
        dn.sort()
        for fn in fns:
            if fn == "CODEMAP.md":
                continue
            out["docs_md" if fn.endswith(".md") else "docs_img"] += os.path.getsize(os.path.join(dp, fn))
    return out
