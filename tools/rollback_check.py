#!/usr/bin/env python3
import argparse
import glob
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_RE = re.compile(r"core(_[A-Za-z0-9_]+)?\.py")


def rawskip_readers(text):
    import ast
    import re as _re
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    pat = _re.compile(r"exf_rawskip:\{\}:(deposit|withdraw):\{\}")
    sel = _re.compile(r"\s*SELECT\s[^;]*?\sFROM\s+meta\s+WHERE\s+k\s*=\s*\?\s*(LIMIT\s+1\s*)?", _re.I)
    par, dead = {}, set()
    for n in ast.walk(tree):
        for ch in ast.iter_child_nodes(n):
            par[id(ch)] = n
        if isinstance(n, (ast.If, ast.While)) and isinstance(n.test, ast.Constant):
            for st in (n.orelse if n.test.value else n.body):
                dead.update(map(id, ast.walk(st)))
        elif isinstance(n, ast.IfExp) and isinstance(n.test, ast.Constant):
            dead.update(map(id, ast.walk(n.orelse if n.test.value else n.body)))
        elif isinstance(n, ast.BoolOp):
            for i, v in enumerate(n.values[:-1]):
                if isinstance(v, ast.Constant) and bool(v.value) == isinstance(n.op, ast.Or):
                    for rest in n.values[i + 1:]:
                        dead.update(map(id, ast.walk(rest)))
                    break
    kinds = set()
    for call in ast.walk(tree):
        if id(call) in dead or not (isinstance(call, ast.Call) and len(call.args) == 2 and getattr(call.func, "attr", getattr(call.func, "id", "")) == "execute"):
            continue
        sql, prm = call.args
        if not (isinstance(sql, ast.Constant) and isinstance(sql.value, str) and sel.fullmatch(sql.value)):
            continue
        if not (isinstance(prm, (ast.Tuple, ast.List)) and len(prm.elts) == 1 and isinstance(prm.elts[0], ast.JoinedStr)):
            continue
        at, fc = par.get(id(call)), None
        if isinstance(at, ast.Attribute) and at.attr in ("fetchone", "fetchall") and isinstance(par.get(id(at)), ast.Call):
            fc = par[id(at)]
        if fc is None or isinstance(par.get(id(fc)), ast.Expr):
            continue
        s = "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}" for v in prm.elts[0].values)
        m = pat.fullmatch(s)
        if m:
            kinds.add(m.group(1))
    return kinds


def ledger_marks(db):
    if not os.path.isfile(db):
        return None
    c = sqlite3.connect("file:" + urllib.parse.quote(db, safe="/:\\") + "?mode=ro", uri=True, timeout=30)
    try:
        try:
            ks = [r[0] for r in c.execute("SELECT k FROM meta WHERE k >= 'exf_rawskip:' AND k < 'exf_rawskip;'")]
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            ks = []
    finally:
        c.close()
    out = {}
    for k in ks:
        p = k.split(":", 3)
        kd = p[2] if len(p) == 4 and p[2] in ("deposit", "withdraw") else "?"
        out[kd] = out.get(kd, 0) + 1
    return out


def ledger_data_rev(db):
    if not os.path.isfile(db):
        return 0
    c = sqlite3.connect("file:" + urllib.parse.quote(db, safe="/:\\") + "?mode=ro", uri=True, timeout=30)
    try:
        try:
            r = c.execute("SELECT v FROM meta WHERE k='data_rev'").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            r = None
    finally:
        c.close()
    return int(str(r[0]).strip()) if r else 0


_REV_RE = re.compile(r"^DATA_REV = (\d+)", re.M)


def target_data_rev(ref, tree):
    if tree:
        p = os.path.join(tree, "src", "db.py")
        if not os.path.isfile(p):
            return 0
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        r = _git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if r.returncode != 0 or not r.stdout.strip():
            raise ValueError("git 커밋·태그를 못 찾음: %s" % ref)
        b = _git("show", "%s:src/db.py" % r.stdout.strip())
        if b.returncode != 0:
            return 0
        text = b.stdout
    m = _REV_RE.search(text)
    return int(m.group(1)) if m else 0


def _git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True, timeout=120)


def target_sources(ref, tree):
    out = {}
    if tree:
        src = os.path.join(tree, "src")
        for p in sorted(glob.glob(os.path.join(glob.escape(src), "core*.py"))):
            if CORE_RE.fullmatch(os.path.basename(p)):
                with open(p, encoding="utf-8", errors="replace") as f:
                    out[os.path.basename(p)] = f.read()
    else:
        r = _git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if r.returncode != 0 or not r.stdout.strip():
            raise ValueError("git 커밋·태그를 못 찾음: %s(이 폴더가 git 저장소인지 · 이름 확인 · 필요하면 git fetch --tags)" % ref)
        sha = r.stdout.strip()
        r = _git("ls-tree", "--name-only", sha, "src/")
        if r.returncode != 0:
            raise ValueError("git ls-tree 실패: %s" % (r.stderr.strip() or r.returncode))
        for line in r.stdout.splitlines():
            name = line.strip().rsplit("/", 1)[-1]
            if CORE_RE.fullmatch(name):
                b = _git("show", "%s:src/%s" % (sha, name))
                if b.returncode != 0:
                    raise ValueError("git show 실패: src/%s" % name)
                out[name] = b.stdout
    if "core.py" not in out:
        raise ValueError("되돌릴 판에 src/core.py 가 없음 — tj-bot 판이 아님")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rollback_check.py", description="코드만 되돌리기 전 점검 — 되돌릴 판이 원장의 1회 정정 표식을 읽는지")
    ap.add_argument("ref", nargs="?", help="되돌릴 git 커밋·태그")
    ap.add_argument("--tree", help="되돌릴 판을 풀어 둔 폴더(src/ 가 든 곳)")
    ap.add_argument("--ledger", help="원장 경로(기본 $TJ_BASE/state/ledger.db)")
    a = ap.parse_args(argv)
    if bool(a.ref) == bool(a.tree):
        ap.print_usage(sys.stderr)
        print("rollback_check: 되돌릴 판을 하나만 — <커밋·태그> 또는 --tree <폴더>", file=sys.stderr)
        return 2
    base = os.environ.get("TJ_BASE") or ROOT
    db = a.ledger or os.path.join(base, "state", "ledger.db")
    try:
        marks = ledger_marks(db)
    except sqlite3.Error as e:
        print("★확인 불가(되돌리지 말 것): 원장 읽기 실패 %s — %s★" % (db, e))
        return 2
    try:
        srcs = target_sources(a.ref, a.tree)
        code_rev = target_data_rev(a.ref, a.tree)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        print("★확인 불가(되돌리지 말 것): %s★" % e)
        return 2
    try:
        led_rev = ledger_data_rev(db)
    except (sqlite3.Error, ValueError) as e:
        print("★확인 불가(되돌리지 말 것): 원장 데이터 개정 번호(meta data_rev) 읽기 실패 %s — %s★" % (db, e))
        return 2
    if led_rev > code_rev:
        print("★거부(코드만 되돌리면 안 됨): 원장 데이터 개정(meta data_rev) %d > 되돌릴 판(%s)의 코드 DATA_REV %d — 그 판은 자동 처리(autofix) 등 한 방향 변환을"
              " 모른다(core 시작 거부 또는 바뀐 내용 모른 채 기장)★" % (led_rev, a.ref or a.tree, code_rev))
        if led_rev >= 3 > code_rev:
            print("   개정 3(업비트 분할 체결 레그) 먼저: pm2 stop ecosystem.config.js → python3 tools/ledger_rowfix.py --upbit-split-down --apply --backup-now(분할 레그를 한 줄로 · 3 → 분할 전 개정)")
        if code_rev < 2:
            print("   먼저(지금 코드 그대로 · checkout 전에) 자동 처리를 되돌리기: pm2 stop ecosystem.config.js → python3 tools/ledger_rowfix.py --undo-autofix <거래소>:<심볼> --apply"
                  " (칸마다 전부) → python3 tools/ledger_rowfix.py --data-rev-down 1 --apply")
        print("   → 이 점검을 다시(통과하면 checkout) · 또는 그 변환 전 백업으로 원장째: python3 tools/ledger_restore.py list")
        return 1
    if not marks:
        print("통과: 원장에 1회 정정 표식 없음(%s)" % ("원장 없음" if marks is None else db))
        return 0
    readers = set()
    for t in srcs.values():
        readers |= rawskip_readers(t)
    name = {"deposit": "입금", "withdraw": "출금", "?": "모르는 꼴"}
    miss = sorted(k for k in marks if k not in readers)
    got = " · ".join("%s %d개" % (name[k], marks[k]) for k in sorted(marks))
    if not miss:
        print("통과: 원장 정정 표식 %s — 되돌릴 판의 core 가 모두 읽음" % got)
        return 0
    print("★거부(코드만 되돌리면 안 됨): 원장에 1회 정정 표식 exf_rawskip %s — 되돌릴 판(%s)의 core 는 %s 표식을 읽지 않는다 →"
          " 정상 재대사가 지운 입출금을 원본에서 다시 기장한다★" % (got, a.ref or a.tree, "·".join(name[k] for k in miss)))
    undos = sorted(glob.glob(os.path.join(os.path.dirname(db), "ledger_rowfix_undo_*.json")))
    print("   먼저(지금 코드 그대로 · checkout 전에) 정정을 되돌리기: pm2 stop ecosystem.config.js → python3 tools/ledger_rowfix.py --undo <undo 파일> --apply"
          " → 이 점검을 다시(통과하면 checkout)")
    for u in undos:
        print("     undo 파일: %s" % u)
    if not undos:
        print("     (state/ 에 ledger_rowfix_undo_*.json 이 없음 — 그 정정 전 백업으로 원장째 되돌리기: python3 tools/ledger_restore.py list → restore <번호>)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
