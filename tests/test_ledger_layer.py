#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import glob  # noqa: E402
import hashlib  # noqa: E402
import re  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
os.makedirs(os.path.join(T.TMP, "seed"), exist_ok=True)
json.dump([], open(os.path.join(T.TMP, "seed", "bridge_contracts.json"), "w"))
json.dump({}, open(os.path.join(T.TMP, "seed", "lp_managers.json"), "w"))
json.dump({"chains": {}, "wallets": [], "backfill_months": 5}, open(os.path.join(T.TMP, "config.json"), "w"))
import config, paths  # noqa: E402
import core  # noqa: E402

assert T.TMP in paths.STATE_DIR
T.patch_moved("dm", lambda *a, **k: None)
chk = T.chk
LAYER = {"_post_leg", "_post_legs_strict", "_amend_leg", "_unpost_source"}

bad = []
for f in sorted(glob.glob(os.path.join(T.SRC, "*.py"))):
    tree = ast.parse(open(f, encoding="utf-8").read(), f)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_bump_position":
                if not (os.path.basename(f) == "core_post.py" and fn.name in LAYER):
                    bad.append(f"{os.path.basename(f)}:{n.lineno} {fn.name}")
chk(not bad, "L1 _bump_position 호출 = 원장 계층 함수 안에만", bad)

LEDGER_MODS = {"core_post.py", "core_post_cols.py"}
ALLOW_MODS = {"demo_data.py": "데모 원장(빈 임시 원장에 견본 줄 · 실원장 아님)"}
SUCCESSION = (
    ("core", "Core._stable_regroup", 381, "_stable_regroup.1", "a8610def8cd523d4"),
    ("core", "Core._stable_regroup", 384, "_stable_regroup.2", "7470eee823854b47"),
    ("core", "Core._stable_regroup", 386, "_stable_regroup.3", "b0f402d81066603c"),
    ("core_exf", "ExfMixin._exf_fix_place_apply", 439, "_exf_fix_place_apply.1", "7dc3192d2b86cd40"),
    ("core_exf", "ExfMixin._exf_fix_place_apply", 442, "_exf_fix_place_apply.2", "c3364bf736f15cf1"),
    ("core_exf", "ExfMixin._exf_fix_place_apply", 447, "_exf_fix_place_apply.3", "15b9684e5682a164"),
    ("core_exf_late", "ExfLateMixin._exf_debt_redate_once", 647, "_exf_debt_redate_once.1", "c3364bf736f15cf1"),
    ("core_exf_late", "ExfLateMixin._exf_debt_redate_once", 650, "_exf_debt_redate_once.2", "db82b30827b5ab8e"),
    ("core_pricing", "PricingMixin._out_px_band_fix_once", 315, "_out_px_band_fix_once.1", "72e28f3ca8699a2e"),
    ("core_pricing", "PricingMixin._price_tx", 416, "_price_tx.1", "8220551838867e03"),
    ("core_pricing", "PricingMixin.krw_fill_pass", 554, "krw_fill_pass.1", "d66be81f20fc1c5f"),
    ("core_pricing", "PricingMixin.price_pass", 638, "price_pass.1", "50b661d4eef1e527"),
    ("core_pricing", "PricingMixin.price_pass", 668, "price_pass.2", "400fe1d132f6432c"),
    ("core_pricing", "PricingMixin._price_upbit_quote_fills", 708, "_price_upbit_quote_fills.1", "72dd996b64fd360c"),
    ("core_exf", "ExfMixin._exf_ext_settle_repair", 806, "_exf_ext_settle_repair.1", "d25a95227036e8b1"),
    ("core_exf", "ExfMixin._exf_ext_redate", 843, "_exf_ext_redate.1", "38f567b6f33328fc"),
    ("core_exf_late", "ExfLateMixin._exf_redate_once", 509, "_exf_redate_once.1", "38f567b6f33328fc"),
    ("core_classify", "ClassifyMixin._reclass_plain_xfer_once", 411, "_reclass_plain_xfer_once.1", "7edd3100f71369d5"),
    ("core_classify", "ClassifyMixin._reclass_added_lp_mgrs_once", 489, "_reclass_added_lp_mgrs_once.1", "7edd3100f71369d5"),
)
W_RX = re.compile(r"\b(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+(postings|positions)\b", re.I | re.S)


def _sql(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        a9, b9 = _sql(n.left), _sql(n.right)
        return a9 + b9 if a9 is not None and b9 is not None else None
    return None


class _L4(ast.NodeVisitor):
    def __init__(self):
        self.st, self.writes, self.legs, self.ports = [], [], [], []

    def _scope(self, n):
        self.st.append(n.name)
        self.generic_visit(n)
        self.st.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def visit_Call(self, n):
        if isinstance(n.func, ast.Attribute) and n.func.attr == "_leg_sql":
            a0 = n.args[0] if n.args else None
            if isinstance(a0, ast.Starred) and self.st[-1:] == ["_leg_sql"]:
                self.ports.append(".".join(self.st))
                return self.generic_visit(n)
            self.legs.append((".".join(self.st), a0.value if isinstance(a0, ast.Constant) and isinstance(a0.value, str) else None, n.lineno))
        self.generic_visit(n)

    def generic_visit(self, n):
        s9 = _sql(n) if isinstance(n, (ast.Constant, ast.JoinedStr, ast.BinOp)) else None
        if s9 and W_RX.search(s9):
            self.writes.append((".".join(self.st) or "<모듈>", getattr(n, "lineno", 0), s9))
            return
        super().generic_visit(n)


outside, legs, leg_tab, ports = [], [], None, []
for f in sorted(glob.glob(os.path.join(T.SRC, "*.py"))):
    fn = os.path.basename(f)
    tree = ast.parse(open(f, encoding="utf-8").read(), f)
    w = _L4()
    w.visit(tree)
    legs += [(fn[:-3], q, nm, ln) for q, nm, ln in w.legs]
    ports += ["%s.%s" % (fn[:-3], q) for q in w.ports]
    if fn not in LEDGER_MODS and fn not in ALLOW_MODS:
        outside += ["%s:%d %s" % (fn, ln, q) for q, ln, _s in w.writes]
    if fn == "core_post_cols.py":
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "LEG_SQL" for x in n.targets) and isinstance(n.value, ast.Dict):
                leg_tab = {k.value: _sql(v) for k, v in zip(n.value.keys, n.value.values) if isinstance(k, ast.Constant)}
chk(not outside, "L4 postings·positions 쓰기 SQL 글 = 원장 계층(core_post·core_post_cols) + 허용 표(demo_data) 밖 0", outside[:20])
names = [x[3] for x in SUCCESSION]
chk(leg_tab is not None and list(leg_tab) == names and len(set(names)) == 19,
    "L4 LEG_SQL 열쇠 = 9막 원장 승계 표 19 이름(차례 그대로 · 늘거나 빠지면 실패)", sorted(set(leg_tab or {}) ^ set(names)))
fp_bad = [nm for _m, _q, _l, nm, fp in SUCCESSION if hashlib.sha256((leg_tab or {}).get(nm, "").encode("utf-8")).hexdigest()[:16] != fp]
chk(leg_tab is not None and not fp_bad, "L4 LEG_SQL 글자 지문 = 승계 표(옛 자리 SQL 글자 그대로 · 한 글자라도 바뀌면 실패)", fp_bad)
want = {nm: (m9, q9) for m9, q9, _l, nm, _fp in SUCCESSION}
use = {}
for m9, q9, nm, ln in legs:
    use.setdefault(nm, []).append((m9, q9, ln))
dyn = [u for k, v in use.items() if k is None or k not in want for u in v]
mis = {nm: use.get(nm) for nm, mq in want.items() if [x[:2] for x in use.get(nm, [])] != [mq]}
chk(not dyn and not mis, "L4 이름마다 승계 표의 함수 안 self._leg_sql(\"이름\", …) 한 자리 · 첫 인자 = 표의 글자 상수만", (dyn, mis))
chk(sorted(ports) == ["core_svc.ExfService._leg_sql", "core_svc.PriceService._leg_sql"],
    "L4 _leg_sql 포트 위임 = ExfService·PriceService 둘(core._leg_sql 로 · 같은 연결)", ports)
chk(all(W_RX.search(s9 or "") for s9 in (leg_tab or {}).values()), "L4 LEG_SQL 문장 = 모두 postings·positions 쓰기(다른 표 문장 0)")

c = core.Core(config.load_config())
aid = c.asset_id("native", "eth", None, symbol="ETH", decimals=18)
LOC = "wallet:eth:0x00000000000000000000000000000000000000aa"
E18 = 10 ** 18


def pos():
    r = c.conn.execute("SELECT qty_norm FROM positions WHERE group_id=? AND location=?", (c._group_of(aid), LOC)).fetchone()
    return Decimal(r["qty_norm"]) if r else Decimal(0)


def led():
    s = sum(int(r[0]) for r in c.conn.execute("SELECT qty_base FROM postings WHERE asset_id=? AND location=?", (aid, LOC)))
    return Decimal(s) / Decimal(E18)


ok1 = c._post_leg("exchange", "t:trade", "f1", 0, 1000, aid, LOC, 3 * E18, None, None, "acq", "EXF_BUY")
ok2 = c._post_leg("exchange", "t:trade", "f1", 0, 1000, aid, LOC, 3 * E18, None, None, "acq", "EXF_BUY")
chk(ok1 is True and ok2 is False and pos() == 3 and led() == 3, "L2 _post_leg 두 번째 = 무동작(포지션 한 번)", (ok1, ok2, pos(), led()))
c._post_legs_strict([("chain_tx", "eth", "0xt1", 0, 1100, aid, LOC, 2 * E18, None, None, "in", "TRANSFER_IN"),
                     ("chain_tx", "eth", "0xt1", 1, 1100, aid, LOC, -1 * E18, None, None, "gas", "TRANSFER_IN")])
chk(pos() == 4 and led() == 4, "L2 _post_legs_strict 두 줄 = 포지션 +1", (pos(), led()))
c.conn.execute("SAVEPOINT l2")
try:
    c._post_legs_strict([("chain_tx", "eth", "0xt1", 0, 1100, aid, LOC, 2 * E18, None, None, "in", "TRANSFER_IN")])
    raised = False
except sqlite3.IntegrityError:
    raised = True
c.conn.execute("ROLLBACK TO l2")
c.conn.execute("RELEASE l2")
chk(raised and pos() == 4 and led() == 4, "L2 엄격 충돌 = IntegrityError(롤백 뒤 그대로)", (raised, pos(), led()))

c._post_leg_strict("opening", "eth", "op1", 0, 900, aid, LOC, 5 * E18, None, None, "opening", "OPENING", ver=4)
pid = c.conn.execute("SELECT posting_id, classifier_ver FROM postings WHERE source_id='op1'").fetchone()
chk(pid["classifier_ver"] == 4 and pos() == 9 and led() == 9, "L3 _post_leg_strict ver 그대로", (dict(pid), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, -2 * E18, qb_new=3 * E18, ts=950)
r = c.conn.execute("SELECT qty_base, event_ts FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone()
chk(r["qty_base"] == str(3 * E18) and r["event_ts"] == 950 and pos() == 7 and led() == 7, "L3 _amend_leg 수량·시각 = 포지션 짝", (dict(r), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, 1 * E18, qb_new=4 * E18)
r = c.conn.execute("SELECT qty_base, event_ts FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone()
chk(r["qty_base"] == str(4 * E18) and r["event_ts"] == 950 and pos() == 8 and led() == 8, "L3 _amend_leg 수량만(시각 그대로)", (dict(r), pos()))
c._amend_leg(pid["posting_id"], aid, LOC, -4 * E18)
chk(not c.conn.execute("SELECT 1 FROM postings WHERE posting_id=?", (pid["posting_id"],)).fetchone() and pos() == 4 and led() == 4,
    "L3 _amend_leg 삭제 = 포지션 짝", pos())
gone = c._unpost_source("chain_tx", "eth", "0xt1")
chk(len(gone) == 2 and {int(g["event_ts"]) for g in gone} == {1100} and pos() == 3 and led() == 3, "L3 _unpost_source 되감기 = 지운 줄 반환 · 포지션 짝",
    (len(gone), pos(), led()))
chk(c._unpost_source("chain_tx", "eth", "0xnone") == [] and pos() == 3, "L3 없는 출처 되감기 = 무동작")
c.conn.rollback()

T.finish()
