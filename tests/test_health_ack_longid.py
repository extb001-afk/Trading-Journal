#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import hashlib  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import paths, statefile  # noqa: E402
import health  # noqa: E402
import health_ack  # noqa: E402

chk = T.chk
NOW = time.time()
UNITS = ["tj-core", "tj-web", "tj-exf", "tj-sol"]
HS = health.settings({"health": {"units": UNITS}})
CK = "price:unpriced"


def sui_key(name):
    t9 = f"0x{'ab' * 32}::pool::LP<0x{'cd' * 32}::coin::{name}>"
    return "sui:mv_" + t9.encode("utf-8").hex()


A = sui_key("SYNTHASSETA_01")
B = sui_key("SYNTHASSETB_01")
C = sui_key("SYNTHASSETC_01")


def uph(sym, cost, ent):
    return {"sym": sym, "where": "지갑", "qty": 1.0, "cost": float(cost), "ref": 0.0, "ent": ent}


def obs_of(now, unpriced):
    return {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {},
            "sources": [], "webdiag": {"ts": now, "unpriced_held": list(unpriced), "ex_dead_held": [], "proof_div": []}}


def run(st, now, unpriced):
    ob = obs_of(now, unpriced)
    cs = health.evaluate(ob, HS, open_ids={k: v.get("unit") for k, v in (st.get("incidents") or {}).items()})
    health.step(st, cs, now, HS)
    statefile.atomic_write_json(paths.state("health_status.json"), health.build_status(st, ob, cs, now, HS))
    return cs


def item(view, check=CK):
    return next((x for x in (view or {}).get("open") or [] if isinstance(x, dict) and x.get("check") == check), None)


def vis(view, check=CK):
    x = item(view, check)
    return bool(x) and not x.get("acked") and not x.get("known")


def fp_of(view, check=CK):
    return ((item(view, check) or {}).get("ack") or {}).get("fp")


def apx(check, fp, now):
    r9 = T.safe(health.ack_apply, check, fp, now)
    return r9 if isinstance(r9, tuple) else (None, r9)


def fresh():
    for p9 in (health_ack.path(), paths.state("health_status.json")):
        if os.path.exists(p9):
            os.remove(p9)
    health._ACK_VIEWS.clear()


def opened(unpriced, t0):
    st = {}
    for k in range(3):
        run(st, t0 + k * 1900, unpriced)
    t9 = t0 + 3 * 1900
    run(st, t9, unpriced)
    return st, t9


ENT_ID = getattr(health_ack, "ent_id", None)
ENT_IDS = getattr(health_ack, "ent_ids", None)
SHA = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731

print("[R] 같은 200자 접두의 339자 신원 A·B — A 를 닫은 뒤 A+B")
chk(len(A) == 339 and len(B) == 339 and A[:200] == B[:200] and A != B, "R0 합성 신원 A·B = 339자 · 앞 200자 같음 · 서로 다름", (len(A), len(B)))
fresh()
st, TA = opened([uph("SYNA", 900, A)], NOW - 9000)
v = health.web_view(TA)
chk(vis(v) and fp_of(v), "R1 A $900 주의 열림 · 닫기 지문", item(v))
r = apx(CK, fp_of(v), TA)
chk(r[0] is True and not vis(health.web_view(TA + 1)), "R2 A 닫기 = 숨김", r)
run(st, TA + 60, [uph("SYNA", 900, A), uph("SYNB", 900, B)])
v = health.web_view(TA + 61)
x = item(v) or {}
chk(vis(v) and x.get("ackChanged") and not x.get("acked"), "R3 ★A+B(새 B $900) = 다시 보임(닫은 A 기록이 B 를 가리지 않음)★",
    {k: x.get(k) for k in ("acked", "ackChanged")})
inc = (st.get("incidents") or {}).get(CK) or {}
chk(len(inc.get("ack") or {}) == 2, "R4 판정 사실(항목 단위)에 A·B 둘 — 하나로 덮지 않음", list((inc.get("ack") or {}).keys()))
cp = health.compact(v)
chk(cp.get("warn") == 1 and not cp.get("acked"), "R5 상태 요약(상단 칩·감시 요약 재료)도 주의 1 · 닫음 0", cp)
chk(health.inc_acked(inc, health.ack_doc()) is False, "R6 텔레그램·하루 요약 기준(inc_acked)도 닫힘 아님")

print("[B] 199/200/201자 경계 · 재정규화 멱등 · 짧은 신원 지문 불변")
k199, k200, k201 = "s:" + "x" * 197, "s:" + "x" * 198, "s:" + "x" * 199
ids = {k: (ENT_ID(k) if callable(ENT_ID) else None) for k in (k199, k200, k201)}
chk(ids[k199] == k199, "B1 199자 = 종전 그대로(기존 확인 기록 유지)", ids[k199])
chk(isinstance(ids[k200], str) and ids[k200] != k200 and SHA(k200) in ids[k200] and len(ids[k200]) < 200,
    "B2 200자 = 전체 신원 SHA-256 ID(옛 절단 키와 같은 문자열이 될 수 없음)", ids[k200])
chk(isinstance(ids[k201], str) and SHA(k201) in ids[k201] and ids[k201] != ids[k200], "B3 201자 = 전체 신원 ID · 200자와 다름", ids[k201])
chk(callable(ENT_ID) and all(ENT_ID(i9) == i9 for i9 in ids.values() if i9), "B4 ID 재정규화 = 그대로(멱등)")
e1 = T.safe(ENT_IDS, {A: 900, B: 900.004, k199: None}) if callable(ENT_IDS) else {}
e1 = e1 if isinstance(e1, dict) else {}
chk(len(e1) == 3 and T.safe(ENT_IDS, e1) == e1 and health_ack.norm_ents(e1) == e1,
    "B5 생산(ent_ids)·소비(norm_ents) 재정규화 멱등", e1)
chk(health_ack.fp("price:unpriced", "warn", {"eth:0x" + "01" * 20: 900.0, "sym:OLDENT|지갑": None, "x" * 199: 1.0}) == "6114edeef71be0da"
    and health_ack.fp("chainsweep:untracked", "warn", {"base:0x" + "02" * 20: 5.0}) == "e1c824dc110eb797",
    "B6 짧은 신원 지문 = 수정 전 값과 같음(고정값)")
chk(all(len(k9) < 200 for k9 in health_ack.norm_ents({A: 1, k200: 2, k201: 3})), "B7 어떤 입력이든 정규 키 < 200자(저장·지문 재료)")

print("[P/O] 같은 접두 다른 타입 · 입력 순서 · 충돌")
cs = health.evaluate(obs_of(NOW, [uph("SYNA", 900, A), uph("SYNB", 900, B)]), HS)
c9 = next((c for c in cs if c["id"] == CK), {})
ak = c9.get("ack") or {}
chk(len(ak) == 2 and callable(ENT_ID) and set(ak) == {ENT_ID(A), ENT_ID(B)} and all(v9 == 900.0 for v9 in ak.values()),
    "P1 producer(evaluate) = A·B 각자의 ID · 금액 각자", ak)
cs2 = health.evaluate(obs_of(NOW, [uph("SYNB", 900, B), uph("SYNA", 900, A)]), HS)
c92 = next((c for c in cs2 if c["id"] == CK), {})
chk(c92.get("ack") == ak, "O1 입력 순서 바꿔도 같은 사실", c92.get("ack"))
if callable(ENT_ID):
    lit = ENT_ID(A)
    o1 = T.safe(ENT_IDS, {A: 900.0, lit: 50.0})
    o2 = T.safe(ENT_IDS, {lit: 50.0, A: 900.0})
    o1 = o1 if isinstance(o1, dict) else {}
    chk(o1 == o2 and len(o1) == 1 and lit not in o1 and list(o1.values()) == [900.0],
        "O2 충돌 = 순서 무관 · 충돌 전용 키(어느 한쪽 ID 아님) · 금액은 큰 쪽", (o1, o2))
    chk(health_ack.covered({"ents": {lit: 900.0}}, "warn", o1) is False, "O3 충돌 항목 = A 만 닫은 기록으로 가려지지 않음(보이는 쪽)")
else:
    chk(False, "O2 ent_ids 없음")
    chk(False, "O3 ent_ids 없음")

print("[N] 새 자산 추가 — 다시 보임 · 다시 닫으면 함께 기억")
r = apx(CK, fp_of(v), TA + 62)
chk(r[0] is True and not vis(health.web_view(TA + 63)), "N1 A+B 를 보고 닫기 = 숨김", r)
d9 = health_ack.load()[0] or {}
chk(len(((d9.get("items") or {}).get(CK) or {}).get("ents") or {}) == 2, "N2 기록 = A·B 두 항목")
run(st, TA + 120, [uph("SYNA", 900, A), uph("SYNB", 900, B), uph("SYNC", 900, C)])
chk(vis(health.web_view(TA + 121)), "N3 같은 접두의 셋째 C 추가 = 다시 보임")
run(st, TA + 180, [uph("SYNB", 900, B)])
chk(not vis(health.web_view(TA + 181)), "N4 B 만 남음(부분 집합) = 숨김 유지")

print("[S] 재시작 — 확인 기록은 파일 · 예전 표 거절")
fp_old = fp_of(health.web_view(TA + 182))
health._ACK_VIEWS.clear()
chk(apx(CK, fp_old, TA + 183)[0] is False, "S1 재시작 전 화면의 표로 닫기 = 거절(새로고침)")
chk(not vis(health.web_view(TA + 184)), "S2 재시작 뒤에도 닫은 기록(파일) 그대로 = B 숨김")
code = ("import sys; sys.path.insert(0, %r); import health_ack as H; d = H.load()[0]; ids = H.ent_ids;"
        "print(H.state(d, 'price:unpriced', 'warn', ids({%r: 900})), H.state(d, 'price:unpriced', 'warn', ids({%r: 900, %r: 900})))"
        % (T.SRC, B, B, C))
p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=dict(os.environ))
chk(p.returncode == 0 and p.stdout.split() == ["acked", "changed"], "S3 다른 프로세스(감시 유닛 재시작)도 같은 계약 = B acked · B+C changed",
    (p.returncode, p.stdout.strip(), p.stderr[-300:]))

print("[M] 구형 기록(200자 절단 키) — 추측 이행 없이 무효 · 짧은 키는 유지")
fresh()
SHORT = "eth:0x" + "0e" * 20
G = A[:200]
statefile.atomic_write_json(health_ack.path(), {"v": 1, "items": {CK: {"at": int(NOW - 99999), "level": "warn",
                                                                    "ents": {A[:200]: 900.0, SHORT: 600.0}, "title": "옛 기록", "detail": ""}}})
doc = health_ack.load()[0]
chk(health_ack.state(doc, CK, "warn", T.safe(ENT_IDS, {SHORT: 600.0}) if callable(ENT_IDS) else {SHORT: 600.0}) == "acked",
    "M1 짧은 신원의 옛 확인 기록 = 그대로 유지(숨김)")
for nm, ent9 in (("A(339자)", A), ("B(339자 · 같은 접두)", B), ("200자 G(옛 절단 키와 같은 문자열)", G)):
    cur9 = T.safe(ENT_IDS, {ent9: 900.0, SHORT: 600.0}) if callable(ENT_IDS) else None
    chk(isinstance(cur9, dict) and health_ack.state(doc, CK, "warn", cur9) == "changed",
        f"M2 {nm} = 옛 200자 절단 기록으로 추측 이행 안 함(다시 보임)", cur9)
legacy_cur = health_ack.norm_ents({A[:200]: 900.0, SHORT: 600.0})
chk(health_ack.state(doc, CK, "warn", legacy_cur) == "changed", "M3 옛 상태 파일의 절단 키 사실도 옛 기록과 맞춰 숨기지 않음")
chk(health_ack.ack(CK, "warn", legacy_cur, now=NOW)[0] is False, "M4 절단 키가 섞인 옛 사실로는 닫기 거절(다음 판정 뒤 다시)")
st, TM = opened([uph("SYNA", 900, A), uph("SHORT", 600, SHORT)], NOW - 9000)
v = health.web_view(TM)
chk(vis(v) and (item(v) or {}).get("ackChanged"), "M5 실제 경로: 옛 기록 있어도 A 주의 = 다시 보임('바뀌어서 다시')")
r = apx(CK, fp_of(v), TM)
d9 = (health_ack.load()[0] or {}).get("items", {}).get(CK) or {}
chk(r[0] is True and not vis(health.web_view(TM + 1)) and A[:200] not in (d9.get("ents") or {}) and SHORT in (d9.get("ents") or {})
    and callable(ENT_ID) and ENT_ID(A) in (d9.get("ents") or {}),
    "M6 다시 닫기 = 새 ID 로 기억 · 옛 절단 키는 지움(되살리지 않음) · 짧은 키 유지", sorted((d9.get("ents") or {}).keys()))
run(st, TM + 60, [uph("SYNA", 900, A), uph("SHORT", 600, SHORT), uph("G", 900, G)])
chk(vis(health.web_view(TM + 61)), "M7 그 뒤 200자 G 등장 = 다시 보임")

print("[H] HTTP — 오래된 화면의 닫기 = 409 · 원장·커서 그대로")
fresh()
from http.server import ThreadingHTTPServer  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402
import web  # noqa: E402
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
CFG["web"] = {"port": 8023, "bind": "loopback", "login": {"enabled": False}}
CFG.setdefault("balance_check", {})["enabled"] = False
with open(paths.CONFIG_PATH, "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
web.BUILDER = onboarding.DemoBuilder()
SRV = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-health-ack-longid").start()
HOST = f"127.0.0.1:{PORT}"


def req(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if method == "POST":
        h.update({"Content-Type": "application/json", "Origin": f"http://{HOST}", "X-TJ-CSRF": ss.csrf_token()})
    c.request(method, path, body=json.dumps(body or {}).encode() if method == "POST" else None, headers=h)
    r9 = c.getresponse()
    raw = r9.read()
    c.close()
    try:
        return r9.status, json.loads(raw.decode() or "null")
    except ValueError:
        return r9.status, None


def snap():
    out = {}
    for root9, _d, fs9 in os.walk(T.TMP):
        for f9 in fs9:
            if not f9.startswith("health_") and not f9.endswith((".lock", ".log")):
                p9 = os.path.join(root9, f9)
                with open(p9, "rb") as fh:
                    out[p9] = hashlib.sha256(fh.read()).hexdigest()
    return out


stH = {}
for k in range(3):
    run(stH, time.time() - 4000 + k * 1900, [uph("SYNA", 900, A)])
run(stH, time.time(), [uph("SYNA", 900, A)])
s0, j0 = req("GET", "/api/health")
fpA = fp_of((j0 or {}).get("health"))
chk(s0 == 200 and fpA, "H1 A 주의 + 닫기 지문", s0)
run(stH, time.time(), [uph("SYNA", 900, A), uph("SYNB", 900, B)])
s1, j1 = req("POST", "/api/health/ack", {"check": CK, "fp": fpA})
chk(s1 == 409 and not (j1 or {}).get("ok") and vis((j1 or {}).get("health")), "H2 ★A 만 본 오래된 화면의 닫기 = 409 · B 가 보이는 그대로★", (s1, j1 and j1.get("error")))
s2, j2 = req("GET", "/api/health")
fpAB = fp_of((j2 or {}).get("health"))
health._ACK_VIEWS.clear()
s3, _j3 = req("POST", "/api/health/ack", {"check": CK, "fp": fpAB})
chk(s3 == 409, "H3 재시작 전 화면의 닫기 = 409", s3)
s4, j4 = req("GET", "/api/health")
pre = snap()
s5, j5 = req("POST", "/api/health/ack", {"check": CK, "fp": fp_of((j4 or {}).get("health"))})
chk(s5 == 200 and (j5 or {}).get("ok") and not vis((j5 or {}).get("health")), "H4 새로 받은 지문의 닫기 = 200 · 숨김", (s5, j5 and j5.get("msg")))
post = snap()
chk(pre == post, "H5 닫기 = 확인 기록 파일만(원장·커서·상태 파일은 그대로)", sorted(set(pre) ^ set(post)) or [k9 for k9 in pre if pre[k9] != post.get(k9)])
SRV.shutdown()
SRV.server_close()
T.finish()
