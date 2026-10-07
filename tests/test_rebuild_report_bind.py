#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _gate as _x
from _gate import check, done
import glob
import hashlib
import json
import os
import subprocess
import time
import common
import core
assert _x.TMP in common.STATE_DIR
core.dm = lambda *a, **k: None
c = core.Core(common.load_config())
S = common.STATE_DIR
REJ = os.path.join(S, "rebuild_rejected")
APV = os.path.join(S, "rebuild_pnl_approve.json")
GATE = os.path.join(S, "rebuild_pnl_gate.json")


def rep(months_b, months_s, ocb=None, ocs=None, extra=None, no_open=False):
    g4 = {"realized_by_month_baseline": months_b, "realized_by_month_shadow": months_s,
          "unverified_baseline": {"sum": 0, "rows": 0}, "unverified_shadow": {"sum": 0, "rows": 0}}
    if not no_open:
        g4["open_cost_baseline"] = ocb or {}
        g4["open_cost_shadow"] = ocs or {}
        g4["open_cost_held_cards"] = [len(ocb or {}), len(ocs or {})]
        g4["open_cost_missing_groups"] = [0, 0]
    d = {"G4_vs_baseline": g4, "cost_lost": {"n": 0, "usd": 0, "top": []}, "decimals_unresolved": [], "meta": extra or {}}
    p = os.path.join(_x.TMP, "r_%d_%d.report.json" % (time.time_ns() % 10 ** 9, len(glob.glob(os.path.join(_x.TMP, "r_*")))))
    json.dump(d, open(p, "w"))
    return p


def gate(p):
    return c._ext_pnl_gate(p, {}, "시험")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def tool(*a):
    return subprocess.run([sys.executable, os.path.join(_x.TREE, "tools", "rebuild_approve.py"), *a], env=dict(os.environ, TJ_BASE=_x.TMP),
                          capture_output=True, text=True, timeout=60)


A = rep({"2026-01": 100.0}, {"2026-01": 900.0}, extra={"took_s": 1})
g1 = gate(A)
rs1 = g1.get("report_sha")
pres = glob.glob(os.path.join(REJ, "*"))
check("[1] 보류 + 게이트 기록에 report_sha", (not g1["ok"]) and isinstance(rs1, str) and len(rs1) == 64, g1)
check("[1] 거부 보고서 보존(파일 sha256 = report_sha · 0600)", any(sha(p) == rs1 and (os.stat(p).st_mode & 0o077) == 0 for p in pres), (pres, rs1))
check("[1] 게이트 기록 파일에도 report_sha", rs1 is not None and (common.read_json(GATE, {}) or {}).get("report_sha") == rs1)

json.dump({"until": int(time.time()) + 3600, "at": int(time.time()), "by": "옛 형식"}, open(APV, "w"))
g2 = gate(rep({"2026-01": 100.0}, {"2026-01": 900.0}))
check("[2] 옛 승인(해시 없음) → 승인 아님", not g2.get("approved"), g2)
os.remove(APV)

g2b = gate(A)
t3 = tool("--yes")
ap = common.read_json(APV, {}) if os.path.exists(APV) else {}
check("[3] 도구 --yes → 승인 파일에 마지막 보고서 해시", t3.returncode == 0 and ap.get("report_sha") is not None and ap.get("report_sha") == g2b.get("report_sha"), (t3.returncode, t3.stdout[-300:], t3.stderr[-300:], ap))
A2 = rep({"2026-01": 100.0}, {"2026-01": 900.4}, extra={"took_s": 2})
g3 = gate(A2)
check("[3] 승인한 결과와 같은 차이의 다음 재계산 = 승인 통과(해시 묶인 승인으로)", g3.get("approved") is True and ap.get("report_sha") is not None, g3)

B = rep({"2026-01": 100.0, "2026-02": 0.0}, {"2026-01": 900.0, "2026-02": 500.0})
g4 = gate(B)
check("[4] 승인한 보고서와 다른 결과(새 달 차이) → 승인 아님", not g4.get("approved") and not g4["ok"], g4)
check("[4] B 도 보존 · 승인한 A 보존본 그대로", any(sha(p) == g4.get("report_sha") for p in glob.glob(os.path.join(REJ, "*")))
      and any(sha(p) == ap.get("report_sha") for p in glob.glob(os.path.join(REJ, "*"))), sorted(os.listdir(REJ)) if os.path.isdir(REJ) else None)

for p in glob.glob(os.path.join(REJ, "*")):
    if ap.get("report_sha") and sha(p) == ap.get("report_sha"):
        os.remove(p)
g5 = gate(rep({"2026-01": 100.0}, {"2026-01": 900.0}))
check("[5] 승인한 보고서 보존본이 없으면 승인 아님", not g5.get("approved"), g5)

try:
    os.remove(APV)
except OSError:
    pass
json.dump({"ok": False, "approved": False, "reason": "옛 기록", "months": [], "ts": int(time.time())}, open(GATE, "w"))
t6 = tool("--yes")
check("[6] 게이트 기록에 보고서 없음 → 도구 --yes 거절 · 승인 파일 없음", t6.returncode != 0 and not os.path.exists(APV), (t6.returncode, t6.stdout[-300:]))

g7 = gate(rep({"2026-01": 100.0}, {"2026-01": 100.0}, ocb={"12": 1000.0, "13": 50.0}, ocs={"12": 1500.0, "13": 50.0}))
check("[7] 안 판 포지션 원가가 임계 넘게 바뀜 → 보류", not g7["ok"] and "원가" in str(g7.get("reason")), g7)
g7b = gate(rep({"2026-01": 100.0}, {"2026-01": 100.0}, ocb={"12": 1000.0}, ocs={"12": 1003.0}))
check("[7] 임계 이내(±$50 · 1%) 원가 흔들림은 통과", g7b["ok"], g7b)

g8 = gate(rep({"2026-01": 100.0}, {"2026-01": 100.0}, no_open=True))
check("[8] 열린 원가 칸 없는 보고서 → 보류(fail-closed)", not g8["ok"], g8)

for i in range(25):
    gate(rep({"2026-01": 100.0}, {"2026-01": 1000.0 + i * 100}))
n9 = len(os.listdir(REJ)) if os.path.isdir(REJ) else 0
check("[9] 보존본 개수 상한(≤ 20)", 0 < n9 <= 20, n9)

calls = []
c._ext_rebuild = lambda need, ex_done: calls.append(dict(need))
c._ext_items = lambda now: ([], [], [])
NOW = time.time()


def pass10(fail_ago):
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_prewindow:decimals_fix', '1')")
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fail_at', ?)", (str(int(time.time() - fail_ago)),))
    c.conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('ext_rebuild_fails', '3')")
    c.conn.execute("DELETE FROM meta WHERE k IN ('ext_rebuild_started_at', 'ext_rebuilt_at', 'rebuild_not_before')")
    c.conn.commit()
    c._last_ext_check = 0
    n0 = len(calls)
    c.ext_rebuild_pass(set(c.EXT_STREAMS))
    return len(calls) > n0


gx = gate(rep({"2026-03": 0.0}, {"2026-03": 700.0}))
try:
    os.remove(APV)
except OSError:
    pass
a10 = pass10(700)
json.dump({"report_sha": gx.get("report_sha") or "",  "until": int(time.time()) + 3600, "at": int(time.time()), "by": "시험"}, open(APV, "w"))
b10 = pass10(700)
c10 = pass10(300)
json.dump({"report_sha": "0" * 64, "until": int(time.time()) + 3600, "at": int(time.time()), "by": "시험"}, open(APV, "w"))
d10 = pass10(700)
import rebuild2
F = {"positions": [{"key": "g12", "held": 3.0, "cost": 300.0, "sym": "AAA"}, {"key": "g12f0", "held": 0, "cost": 50.0, "sym": "AAA"},
                   {"key": "g13", "held": 1.0, "cost": 10.0, "sym": "BBB"}, {"key": "s14", "held": 0, "cost": 0, "kind": "stable", "sym": "USDT"},
                   {"key": "g15", "held": 2.0, "cost": 99.0, "kind": "quarantined", "sym": "SCAM"}],
     "coins": [{"key": "g12", "qty": 3.0, "avg": 80.0, "kqty": 2.0, "sym": "AAA"}, {"key": "g13", "qty": 1.0, "avg": 10.0, "kqty": 1.0, "sym": "BBB"},
               {"key": "g16", "qty": 5.0, "avg": 2.0, "kqty": 5.0, "sym": "CCC"}]}
oc11 = rebuild2.open_cost_of(F)
check("[11] open_cost_of: 남은 원가 = coins avg×kqty(카드 누적 매수 cost 아님) · 카드 컷 밖 보유 그룹도 · 스테이블·격리 제외",
      oc11[0] == {"12": 160.0, "13": 10.0, "16": 10.0} and oc11[2] == 2 and oc11[3] == 0, oc11)
F2 = dict(F, coins=[c for c in F["coins"] if c["key"] != "g13"])
check("[11] 보유 카드 그룹이 남은 원가 목록에 없음 → 빠진 그룹 1", rebuild2.open_cost_of(F2)[3] == 1, rebuild2.open_cost_of(F2))
F4 = dict(F, positions=F["positions"] + [{"key": "g17", "held": 5e-10, "cost": 9.0, "sym": "DUST"}])
check("[11] 원장 1e-9 이하 잔여 카드(web 보유 목록 밖) = 빠진 그룹 아님(실제 모양)", rebuild2.open_cost_of(F4)[3] == 0, rebuild2.open_cost_of(F4))
F3 = {"positions": [{"key": "g12", "held": 3.0}], "coins": [{"key": "g12", "qty": 3.0, "avg": float("nan"), "kqty": 2.0}]}
check("[11] 비유한 원가 = 빠진 그룹(fail-closed 재료)", rebuild2.open_cost_of(F3)[3] >= 1, rebuild2.open_cost_of(F3))
g11c = gate(rep({"2026-01": 1.0}, {"2026-01": 1.0}, ocb={"12": 200.0}, ocs={"12": 800.0}))
check("[11] 남은 원가 200→800 = 막음", not g11c["ok"] and g11c.get("open_cost"), g11c)
g11 = gate(rep({"2026-01": 1.0}, {"2026-01": 1.0}, extra=None))
rp11 = os.path.join(_x.TMP, "r11.report.json")
json.dump({"G4_vs_baseline": {"realized_by_month_baseline": {}, "realized_by_month_shadow": {}, "unverified_baseline": {"sum": 0}, "unverified_shadow": {"sum": 0},
                              "open_cost_baseline": {}, "open_cost_shadow": {}, "open_cost_held_cards": [5, 5], "open_cost_missing_groups": [0, 0]},
           "cost_lost": {"n": 0, "usd": 0, "top": []}, "decimals_unresolved": []}, open(rp11, "w"))
g11b = gate(rp11)
check("[11] 보유 카드 5개인데 열린 원가 그룹 0 = fail-closed", not g11b["ok"] and "open_cost" in (g11b.get("missing") or []), g11b)
def rep_raw(d):
    p12 = os.path.join(_x.TMP, "r12_%d.report.json" % time.time_ns())
    open(p12, "w").write(json.dumps(d))
    return p12


base12 = {"realized_by_month_baseline": {}, "realized_by_month_shadow": {}, "unverified_baseline": {"sum": 0}, "unverified_shadow": {"sum": 0},
          "open_cost_baseline": {}, "open_cost_shadow": {}, "open_cost_held_cards": [0, 0], "open_cost_missing_groups": [0, 0]}
ok12 = gate(rep_raw({"G4_vs_baseline": base12, "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []}))
check("[12] 재료가 다 있는 빈 보고서 = 통과(기준)", ok12["ok"], ok12)
cases = {
    "codex 재현(원가미상 sum·원가 소실 n/usd·자리수·보유 카드 수 없음)": {"G4_vs_baseline": {"realized_by_month_baseline": {}, "realized_by_month_shadow": {},
                                                                                     "open_cost_baseline": {}, "open_cost_shadow": {}}, "cost_lost": {}},
    "원가미상 sum 없음": {"G4_vs_baseline": dict(base12, unverified_shadow={}), "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []},
    "원가 소실 usd 없음": {"G4_vs_baseline": base12, "cost_lost": {"n": 0}, "decimals_unresolved": []},
    "자리수 미해결 칸 없음": {"G4_vs_baseline": base12, "cost_lost": {"n": 0, "usd": 0}},
    "월별 실현 null": {"G4_vs_baseline": dict(base12, realized_by_month_shadow={"2026-01": None}), "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []},
    "열린 원가 빠진 그룹 1": {"G4_vs_baseline": dict(base12, open_cost_missing_groups=[0, 1]), "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []},
    "빠진 그룹 칸 없음": {"G4_vs_baseline": {k: v for k, v in base12.items() if k != "open_cost_missing_groups"}, "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []},
}
bad12 = {k: gate(rep_raw(v)) for k, v in cases.items()}
check("[12] 빠진 재료마다 보류(fail-closed)", all(not g["ok"] and g.get("missing") for g in bad12.values()), {k: (g["ok"], g.get("missing")) for k, g in bad12.items()})
nanrep = os.path.join(_x.TMP, "r12nan.report.json")
open(nanrep, "w").write(json.dumps({"G4_vs_baseline": dict(base12, realized_by_month_shadow={"2026-01": 1.0}), "cost_lost": {"n": 0, "usd": 0},
                                    "decimals_unresolved": []}).replace('"2026-01": 1.0', '"2026-01": NaN'))
gnan = gate(nanrep)
check("[12] 비유한(NaN) 월별 실현 = 보류", not gnan["ok"] and "months" in (gnan.get("missing") or []), gnan)

import ops_requests
ev_a = ops_requests.gate_eval({"G4_vs_baseline": dict(base12, unverified_baseline={"sum": 500, "by": {"5": 500}}, unverified_shadow={"sum": 600, "by": {"5": 600}}),
                               "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []}, 50, 0.01)
ev_b = ops_requests.gate_eval({"G4_vs_baseline": dict(base12, unverified_baseline={"sum": 0, "by": {}}, unverified_shadow={"sum": 600, "by": {"5": 600}}),
                               "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []}, 50, 0.01)
ev_c = ops_requests.gate_eval({"G4_vs_baseline": dict(base12, unverified_baseline={"sum": 900, "by": {"5": 900}}, unverified_shadow={"sum": 1010, "by": {"5": 1010}}),
                               "cost_lost": {"n": 0, "usd": 0}, "decimals_unresolved": []}, 50, 0.01)
check("[13] 승인 증가분 100 · 새 증가분 600(뒤 값은 같음) = 다른 결과", ops_requests.covers(ev_a, ev_b, 50, 0.01) != "", ops_requests.covers(ev_a, ev_b, 50, 0.01))
check("[13] 증가분 같음(기준선이 함께 커짐) = 같은 결과", ops_requests.covers(ev_a, ev_c, 50, 0.01) == "", ops_requests.covers(ev_a, ev_c, 50, 0.01))
check("[10] 승인 없음 = 백오프 유지 · 그 보고서 승인 = 10분 뒤 다시 · 10분 전 = 기다림 · 다른 해시 = 백오프 유지", (a10, b10, c10, d10) == (False, True, False, False), (a10, b10, c10, d10))
done()
