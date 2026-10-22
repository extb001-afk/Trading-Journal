#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

WEB = os.path.join(T.SRC, "web.py")
APP = T.app_js_path()

print("[1] 서버 _receipt_eval_post 자동 가드")
src = T.web_src()
tree = ast.parse(src)


def _method(name):
    for c in tree.body:
        if isinstance(c, ast.ClassDef):
            for n in c.body:
                if isinstance(n, ast.FunctionDef) and n.name == name:
                    n.decorator_list = []
                    return n
    raise SystemExit("web.py 에서 못 찾음: " + name)


METHODS = [_method(n) for n in ("_chart_args", "_receipt_eval_post", "_dex_later")]
D = "2026-10-11"


def run_post(side, body, *, deferred=True, auto_eval=True, old=None, used=0, memo=False):
    calls, sched, resp = [], [], []

    class Store:
        mu = threading.Lock()

        def __init__(self):
            self.running, self.errors = {}, {}

        def _budget_read(self, day):
            return {"used": used}

        def find(self, *a):
            return old

    sell, buy = Store(), Store()

    class Thr:
        def __init__(self, target, **kw):
            self.t = target

        def start(self):
            self.t()

    chart = {"ok": True, "sym": "SYN", "autoEval": auto_eval, "evalFp": "fp-x", "chart": {"ok": True}}
    key = (("buy",) if side == "buy" else ()) + (D, "SYN", "fp-x")
    builder = types.SimpleNamespace(cfg={}, snapshot=lambda: None, chart_request=lambda *a, **k: (chart, "ok"),
                                    kick_refresh=lambda: None, _eval_inputs={key: {"synthetic": 1}})

    def run_eval(*a, **k):
        calls.append(a[2:5])
        return {}, None

    class Reeval:
        HOURLY_MAX, HOURLY_MSG = 6, "시간당 {n}"

        @staticmethod
        def schedule(*a, **k):
            sched.append((a, k))
            return True

        @staticmethod
        def hour_left():
            return 5

        @staticmethod
        def runner(*a):
            return None

    ns = {"datetime": datetime, "KST": timezone(timedelta(hours=9)), "time": time, "BUILDER": builder, "BUY_EVALS": buy, "SELL_EVALS": sell,
          "threading": types.SimpleNamespace(Thread=Thr),
          "sellchart": types.SimpleNamespace(daily_max=lambda *a: 20, run_eval=run_eval, dex_later_mark=lambda *a: None),
          "memo_driven": (lambda *a: "SYN") if memo else (lambda *a: None), "DAY_MEMO_REEVAL": Reeval,
          "MemoHourly": type("MemoHourly", (Exception,), {}), "log": types.SimpleNamespace(warning=lambda *a: None),
          "StateBuilder": types.SimpleNamespace(_eval_rec=lambda rec, s="sell": {"fp": rec.get("fp")}),
          "_eval_budget_msg": lambda *a: "한도"}
    ns["web_ctx"] = types.SimpleNamespace(builder=lambda: ns["BUILDER"], day_memo=lambda: ns["DAY_MEMO_REEVAL"],
                                          memo_driven=lambda *a, **k: ns["memo_driven"](*a, **k))
    exec(compile(ast.fix_missing_locations(ast.Module(body=list(METHODS), type_ignores=[])), WEB, "exec"), ns)
    if deferred:
        ns["_dex_later"](chart, D, "SYN", side, "deferred", listed=False)

    class H:
        _DAY_RE = re.compile(r"20\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
        _IV_OK, _AFTER_OK = ("1m", "5m"), ("1h", "6h", "24h")
        _chart_args, _receipt_eval_post = ns["_chart_args"], ns["_receipt_eval_post"]

        def _write_guard(self):
            return True

        def _send(self, st, b):
            resp.append((st, b))

    b = dict({"date": D, "sym": "SYN", "side": side}, **body)
    H()._receipt_eval_post(b)
    return calls, sched, resp[-1] if resp else None, chart


for side in ("sell", "buy"):
    calls, _s, r, ch = run_post(side, {"auto": True, "iv": "1m", "after": "24h", "venue": "dex:base:t"})
    T.chk(ch.get("autoEval") is False and ch.get("dexLater") == "deferred" and not calls and r and r[0] == 409 and r[1].get("ok") is False,
          f"{side}: auto + 미룬 DEX(대체 봉) 차트 = 모델 실행 0 · 409 자동 금지", {"calls": calls, "resp": r})
    calls, sched, r, _c = run_post(side, {"auto": True}, memo=True)
    T.chk(not calls and not sched and r and r[0] == 409, f"{side}: auto + 미룬 차트 + 근거 메모 = 메모 큐 등록도 0", {"sched": len(sched), "resp": r})
    calls, _s, r, _c = run_post(side, {"auto": True}, deferred=False, auto_eval=False)
    T.chk(not calls and r and r[0] == 409, f"{side}: auto + autoEval=false 차트 = 실행 0 · 409", {"calls": calls, "resp": r})
    calls, _s, r, _c = run_post(side, {"iv": "1m", "after": "24h"})
    T.chk(len(calls) == 1 and r and r[0] == 202 and r[1].get("status") == "running", f"{side}: 버튼(auto 없음) + 미룬 차트 = 종전대로 실행", {"resp": r})
    calls, _s, r, _c = run_post(side, {"auto": True}, old={"fp": "fp-x"})
    T.chk(not calls and r and r[0] == 200 and r[1].get("cached") is True, f"{side}: auto + 미룬 차트라도 저장 평가 = 그대로 200", {"resp": r})
    calls, _s, r, _c = run_post(side, {"auto": True}, deferred=False)
    T.chk(len(calls) == 1 and r and r[0] == 202, f"{side}: auto + 정상 차트(autoEval) = 종전대로 실행", {"resp": r})
    calls, _s, r, _c = run_post(side, {}, used=99)
    T.chk(not calls and r and r[0] == 429, f"{side}: 일일 한도 = 429 그대로", {"resp": r})

print("[2] 화면 rcEvalPost 202 재시도 보기 고정(node)")
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const code = cut('  function openReceipt(iso, sym, rank) {', '  function topRcptSym(iso)') + '\n' + cut('  const RC_TRIES =', '  function rcTicks(a, b, n)');
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, d]);
const resp = (status, data) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
const flush = async () => { for (let n = 0; n < 40; n++) await Promise.resolve(); };
function harness() {
  const S = { D: { builtAt: 1 }, drawer: null }, writes = [], timers = [];
  const deps = { S, num: x => Number(x) || 0, arr: x => Array.isArray(x) ? x : [],
    fetch: async (url, o) => { if (o && o.method === 'POST') { writes.push(JSON.parse(o.body)); return resp(202, { ok: true, status: 'preparing', retryAfter: 3 }); } return resp(200, { ok: true }); },
    csrf: async () => '', onUnauthorized: () => {}, renderOverlay: () => {}, setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    document: { activeElement: null }, $: () => null, drawerHist: () => {}, isISO: s => /^\d{4}-\d{2}-\d{2}$/.test(s) };
  const api = new Function(...Object.keys(deps), code + '\nreturn {rcEvalPost, rcAuto, rcV, rcK, rcBK, rcSK};')(...Object.values(deps));
  S.drawer = 'rcpt'; S.rcpt = { key: '2026-10-11|SYN', iso: '2026-10-11', sym: 'SYN' }; S.rcptE = {}; S.rcptX = {}; S.rcptB = {};
  // 202 재시도 타이머만 돌린다(평가 상태 GET 폴링 등 다른 타이머는 이 시험 밖)
  const fire = async () => { const t = timers.shift(); if (t) t.fn(); await flush(); };
  return { S, writes, timers, api, fire };
}
(async () => {
  for (const side of [undefined, 'buy']) {
    const nm = side || 'sell';
    for (const [f, val] of [['iv', '1m'], ['after', '24h'], ['venue', 'dex:base:t'], ['bvenue', 'dex:base:b']]) {
      const h = harness(), k = h.api.rcSK(h.S.rcpt, side);
      // 실제 자동 진입(rcAuto) — 기본 보기 · autoEval 차트 · 저장 평가 없음
      h.S.rcptE[k] = { st: 'ready', ev: null, budget: { left: 20 } };
      (side === 'buy' ? h.S.rcptB : h.S.rcptX)[side === 'buy' ? h.api.rcBK(h.S.rcpt) : h.api.rcK(h.S.rcpt)] = { st: 'ok', at: 1, d: { autoEval: true, evalFp: 'fp0' } };
      h.api.rcAuto(h.S.rcpt, side); await flush();
      h.api.rcV(h.S.rcpt)[f] = val;
      await h.fire();
      chk(h.writes.length === 1 && h.writes[0].auto === true && h.S.rcptE[k].st === 'idle',
        nm + ': 202 뒤 ' + f + ' 바꿈 = 재시도 POST 0 · idle', { writes: h.writes, st: h.S.rcptE[k].st });
    }
    { // 같은 보기 유지 = 재시도 계속(같은 본문)
      const h = harness(), k = h.api.rcSK(h.S.rcpt, side);
      await h.api.rcEvalPost(false, 0, side, true);
      await h.fire(); await h.fire();
      chk(h.writes.length === 3 && JSON.stringify(h.writes[1]) === JSON.stringify(h.writes[0]) && JSON.stringify(h.writes[2]) === JSON.stringify(h.writes[0]) && h.S.rcptE[k].st === 'post',
        nm + ': 같은 보기 = 재시도 계속(같은 본문)', h.writes);
    }
    { // 바꿨다가 되돌림(같은 값) = 계속
      const h = harness();
      await h.api.rcEvalPost(false, 0, side, true);
      h.S.rcpt.cv = Object.assign({}, h.api.rcV(h.S.rcpt));
      await h.fire();
      chk(h.writes.length === 2, nm + ': 보기 객체만 새로(같은 값) = 재시도 계속', h.writes.length);
    }
    { // 서랍 닫기 · 다른 영수증 · 같은 영수증 새로 열기 = 취소
      for (const [why, act] of [['닫기', S => { S.drawer = null; }], ['다른 영수증', S => { S.rcpt = { key: '2026-10-11|OTH', iso: '2026-10-11', sym: 'OTH' }; }],
                                ['같은 영수증 새 객체', S => { S.rcpt = { key: '2026-10-11|SYN', iso: '2026-10-11', sym: 'SYN' }; }]]) {
        const h = harness(), k = h.api.rcSK(h.S.rcpt, side);
        await h.api.rcEvalPost(false, 0, side, true);
        act(h.S); await h.fire();
        chk(h.writes.length === 1 && h.S.rcptE[k].st === 'idle', nm + ': ' + why + ' = 재시도 취소 · idle', { n: h.writes.length, st: h.S.rcptE[k].st });
      }
    }
  }
  for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d).slice(0, 600)));
  console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
})().catch(e => { console.log('FAIL 실행 오류 ' + (e && e.stack || e)); console.log('RESULT 0/1'); });
'''
NODE = T.node_bin("화면 함수 동작 시험")
if NODE:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
