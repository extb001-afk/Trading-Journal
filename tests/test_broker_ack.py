#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, T.SRC)
import brokers  # noqa: E402
import other_assets as oa  # noqa: E402
import alert_watch as aw  # noqa: E402

chk = T.chk
NOW = 1_790_000_000.0
CALLS = []


def fake_http(method, url, headers=None, body=None, timeout=15.0, verify=True):
    CALLS.append(url.split("/v2/")[-1])
    if url.endswith("/v2/positions"):
        return 200, [{"symbol": "TKJ", "qty": "100", "avg_entry_price": "1", "current_price": "1", "side": "long", "asset_class": "us_equity"}], {}
    return 200, {"cash": "0", "currency": "USD", "account_number": "SYN"}, {}


SYNC = ["positions", "account"]


def quoter(cfg, tag, store=None):
    d = os.path.join(T.TMP, tag)
    os.makedirs(d, exist_ok=True)
    sp = os.path.join(d, "other_assets.json")
    if store is not None:
        with open(sp, "w", encoding="utf-8") as f:
            f.write(store if isinstance(store, str) else json.dumps(store))
    return oa.Quoter(cfg_fn=lambda: cfg, now=lambda: NOW, store_path=sp, px_path=os.path.join(d, "px.json"), http_json=fake_http)


def cfg_of(ack=None, keys=("alpaca",)):
    c = {"brokers": {k: {"enabled": True, "key_id": "x", "secret_key": "y"} for k in keys}, "other_assets": {"broker_every_sec": 3600}}
    if ack is not None:
        c["other_assets"]["brokers"] = {"experimental_ack": ack}
    return c


ON = {"alpaca": {"enabled": True}, "kis": {"enabled": False}, "zzz": {"enabled": True}}
NOLOAD = lambda: {"v": 1, "items": [], "bst": {}}   # noqa: E731
chk(brokers.gate({"brokers": {"experimental_ack": True}}, ON, {}, NOLOAD) == (True, frozenset()), "[1] true = 확인 · 막을 것 없음")
for bad in ({}, None, [], {"brokers": None}, {"brokers": True}, {"brokers": {"experimental_ack": "true"}},
            {"brokers": {"experimental_ack": 1}}, {"brokers": {}}, {"experimental_ack": True}):
    chk(brokers.gate(bad, ON, {}, NOLOAD) == (False, frozenset({"alpaca"})), "[1] 확인 아님 = 켜진 아는 증권사만 막음: %s" % json.dumps(bad))
chk(brokers.gate({}, {}, {}, NOLOAD) == (False, frozenset()), "[1] 켜진 증권사 없음 = 막을 것 없음")


def boom():
    raise ValueError("손상")


chk(brokers.gate({}, ON, {}, boom) == (False, frozenset()), "[1] 저장본 못 읽음 = 막지 않음")
chk(brokers.gate({}, ON, {"alpaca": {"at": 1, "ok": False}}, boom) == (False, frozenset()), "[1] 이 프로세스 동기화 기록 = 저장본 안 읽고 통과")

for tag, ack in (("none", None), ("str", "true"), ("one", 1), ("false", False)):
    CALLS.clear()
    q = quoter(cfg_of(ack), "g_" + tag)
    q.broker_cycle(force=True)
    chk(CALLS == [], "[2] 확인(%s) 없이 처음 켠 연결 = 증권사 호출 0" % tag, CALLS)
    chk(q.bst.get("alpaca") == {"gate": "ack"}, "[2] 상태 gate=ack (%s)" % tag, q.bst)
    d = oa.load_store(q.store_path)
    chk(not [x for x in d["items"] if x.get("broker")], "[2] 저장본에 증권사 항목 없음 (%s)" % tag)
v = oa.view(oa.load_store(q.store_path), q, 1300.0, cfg_of()["brokers"], now=NOW)
row = [b for b in v.get("brokers") or [] if b.get("key") == "alpaca"]
chk(row and row[0]["enabled"] and row[0]["status"].get("gate") == "ack" and "ok" not in row[0]["status"], "[2] 화면 목록 status.gate · ok 없음", row)
chk(row and row[0]["ack"] == brokers.ACK_TXT["gate"] and "experimental_ack" in row[0]["ack"], "[2] 화면 목록 ack = 확인 필요 안내 글", row)
st = {}
res = aw.prod_oa({"oa": v}, None, st, NOW, None, True)
chk(not [r for r in res if "끊겼" in json.dumps(r, ensure_ascii=False)], "[2] gate 는 '연결 끊김' 알림 아님", res)

CALLS.clear()
q = quoter(cfg_of(True), "ok")
q.broker_cycle(force=True)
chk(CALLS == SYNC, "[3] 확인 있음 = 동기화 1번", CALLS)
chk(q.bst.get("alpaca", {}).get("ok") is True and "noack" not in q.bst["alpaca"] and "gate" not in q.bst["alpaca"], "[3] 상태 ok · noack/gate 없음", q.bst)
d = oa.load_store(q.store_path)
chk([x.get("ticker") for x in d["items"] if x.get("broker") == "alpaca" and x.get("cat") == "stock"] == ["TKJ"], "[3] 저장본에 증권사 보유 TKJ", [x.get("ticker") for x in d["items"]])

prev = {"v": oa.SCHEMA, "items": [], "bst": {"alpaca": {"at": int(NOW) - 7200, "ok": True, "n": 1}}}
CALLS.clear()
q = quoter(cfg_of(None, ("alpaca", "kis")), "legacy_bst", prev)
q.broker_cycle(force=True)
chk(CALLS == SYNC, "[4] 전에 동기화된 alpaca = 확인 없이도 동기화 · 처음 켠 kis = 막힘(호출 0)", CALLS)
chk(q.bst.get("alpaca", {}).get("noack") is True and q.bst["alpaca"].get("ok") is True, "[4] 상태 noack(노랑 안내) + ok", q.bst.get("alpaca"))
chk(q.bst.get("kis") == {"gate": "ack"}, "[4] kis gate", q.bst.get("kis"))
sb9 = oa.load_store(q.store_path)["bst"]
chk(sb9.get("alpaca", {}).get("ok") is True and "noack" not in sb9["alpaca"] and "kis" not in sb9, "[4] 저장본 bst = 동기화 결과만(noack·gate 저장 안 함)", sb9)
v = oa.view(oa.load_store(q.store_path), q, 1300.0, cfg_of(None, ("alpaca", "kis"))["brokers"], now=NOW)
row = {b["key"]: b for b in v.get("brokers") or []}
chk(row["alpaca"]["status"].get("noack") is True and row["alpaca"]["ack"] == brokers.ACK_TXT["noack"], "[4] 화면 목록 status.noack + 안내 글", row["alpaca"])
chk(row["kis"]["ack"] == brokers.ACK_TXT["gate"] and all(r["ack"] == "" for k, r in row.items() if k not in ("alpaca", "kis")), "[4] 안내 글 = 해당 증권사만", row)
CALLS.clear()
q0 = quoter(cfg_of(True), "seed")
q0.broker_cycle(force=True)
d0 = oa.load_store(q0.store_path)
d0["bst"] = {}
q = quoter(cfg_of(None), "legacy_item", d0)
q.broker_cycle(force=True)
chk(CALLS == SYNC + SYNC, "[4] 증권사 항목이 있는 저장본 = 끊지 않음", CALLS)
cfg9 = cfg_of(True)
q = quoter(cfg9, "flip")
q.broker_cycle(force=True)
cfg9["other_assets"].pop("brokers")
q.broker_cycle(force=True)
chk(q.bst["alpaca"].get("noack") is True and "gate" not in q.bst["alpaca"], "[4] 확인 빠짐 = 계속 · noack", q.bst)
cfg9["other_assets"]["brokers"] = {"experimental_ack": True}
q.broker_cycle(force=True)
chk("noack" not in q.bst["alpaca"], "[4] 확인 다시 = noack 사라짐", q.bst)
CALLS.clear()
q = quoter(cfg_of(None), "corrupt", "{not json")
q.broker_cycle(force=True)
chk(CALLS == SYNC, "[4] 저장본 못 읽음 = 끊지 않음", CALLS)
CALLS.clear()
c9 = cfg_of(None)
c9["brokers"]["alpaca"]["enabled"] = False
q = quoter(c9, "off")
q.broker_cycle(force=True)
chk(CALLS == [] and q.bst == {}, "[4] 꺼진 증권사 = 상태 없음", q.bst)

JS = r"""
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a); return APP.slice(i, j); };
const R = []; const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
try {
  const B = cut('  const OA_UNVER = ', '\n') + '\n' + cut('  const oaBrkPend = ', '\n') + '\n' + cut('  function brokersBody() {', '  Object.assign(A, {');
  const S = { oa: { d: null, st: '' } };
  const deps = { S, arr: x => (Array.isArray(x) ? x : []), esc: x => String(x).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]),
    oaNeed: () => {}, fmtTs: t => 'T' + t, num: x => String(x), errTxt: x => String(x), TJDOM: { safeUrl: u => u } };
  const api = new Function(...Object.keys(deps), B + '\nreturn { brokersBody, oaBrkPend };')(...Object.values(deps));
  const one = (st, ack) => { S.oa.d = { brokers: [{ key: 'alpaca', name: 'Alpaca', enabled: true, configured: true, fields: [], docs: '', status: st, ack: ack || '' }] }; return [api.brokersBody(), api.oaBrkPend().length]; };
  const TX = JSON.parse(process.env.TJ_ACK_TXT);
  let [h, p] = one({ gate: 'ack' }, TX.gate);
  chk(h.includes('실험(미검증)') && h.includes('실험 확인 필요') && h.includes('experimental_ack') && h.includes('dot w') && !h.includes('첫 동기화 대기'), 'gate = 실험 딱지 + 확인 필요 안내 + 노랑', h);
  chk(p === 0, 'gate = 미확정 셈 밖', p);
  [h, p] = one({ at: 1, ok: true, n: 1, noack: true }, TX.noack);
  chk(h.includes('마지막 동기화 T1') && h.includes('실험 확인 없음') && h.includes('experimental_ack') && h.includes('dot w'), 'noack = 동기화 그대로 + 노랑 안내 줄', h);
  chk(p === 0, 'noack(성공) = 미확정 아님', p);
  [h, p] = one({ at: 1, ok: true, n: 1 });
  chk(h.includes('실험(미검증)') && !h.includes('실험 확인') && h.includes('<span class="dot"></span>'), '확인 있음 정상 = 안내 없음 · 초록', h);
  [h, p] = one({});
  chk(p === 1 && h.includes('첫 동기화 대기'), '반대 방향: 켜진 뒤 아직 동기화 전 = 미확정 그대로', [p, h]);
  [h, p] = one({ at: 1, ok: false, err: 'x' });
  chk(p === 1 && h.includes('동기화 실패'), '반대 방향: 실패 = 미확정 그대로', [p, h]);
} catch (e) { chk(false, '실행 오류', String((e && e.stack) || e).slice(0, 400)); }
console.log(JSON.stringify(R));
"""
node = T.node_bin("화면 JS 실행")
if node:
    p = subprocess.run([node, "--input-type=module", "-"], input=JS, capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, TJ_TEST_APP=T.app_js_path(), TJ_ACK_TXT=json.dumps(brokers.ACK_TXT)))
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        chk(False, "[5] node 실행", (p.stderr or "")[-1500:])
    else:
        for ok, msg, *dd in json.loads(out[-1]):
            chk(ok, "[5] " + msg, dd[0] if dd else None)
T.finish()
