#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import paths, statefile  # noqa: E402
import health  # noqa: E402
import health_ack  # noqa: E402

chk = T.chk
S = paths.STATE_DIR
NOW = time.time()
UNITS = ["tj-core", "tj-web", "tj-exf", "tj-sol"]
HS = health.settings({"health": {"units": UNITS}})


def obs_of(now, **kw):
    o = {"now": now, "pm2": {u: {"status": "online", "restarts": 0, "pid": 1} for u in UNITS}, "bal_mem": {}, "prev_inc": {}, "sources": []}
    o.update(kw)
    return o


def wd(now, unpriced=(), **kw):
    d = {"ts": now, "unpriced_held": list(unpriced), "ex_dead_held": [], "proof_div": []}
    d.update(kw)
    return d


def uph(sym, cost, ent=None, where="지갑"):
    x = {"sym": sym, "where": where, "qty": 1.0, "cost": float(cost), "ref": 0.0}
    if ent:
        x["ent"] = ent
    return x


OLD = uph("OLDX", 900, "eth:0x" + "01" * 20)
NEW = uph("NEWX", 100000, "base:0x" + "02" * 20)


def run(st, now, **wkw):
    ob = obs_of(now, webdiag=wd(now, **wkw))
    cs = health.evaluate(ob, HS, open_ids={k: v.get("unit") for k, v in (st.get("incidents") or {}).items()})
    health.step(st, cs, now, HS)
    statefile.atomic_write_json(paths.state("health_status.json"), health.build_status(st, ob, cs, now, HS))
    return cs


def item(view, check):
    for x in (view or {}).get("open") or []:
        if isinstance(x, dict) and x.get("check") == check:
            return x
    return None


def vis(view, check):
    x = item(view, check)
    return bool(x) and not x.get("acked") and not x.get("known")


print("[D1] 오래된 '시세 없는 실보유' 사건 + 새 코인 — 시간만으로 접지 않음")
st = {}
T0 = NOW - 3 * 86400
for k in range(3):
    run(st, T0 + k * 1900, unpriced=[OLD])
inc = (st.get("incidents") or {}).get("price:unpriced")
chk(isinstance(inc, dict), "D1 사건 열림(OLD · 지속 1시간)", list((st.get("incidents") or {}).keys()))
T2 = T0 + 2 * 86400
run(st, T2, unpriced=[OLD, NEW])
inc = (st.get("incidents") or {}).get("price:unpriced") or {}
v1 = health._inc_view(inc, T2) if inc else {}
chk(bool(inc) and inc.get("opened") and T2 - float(inc["opened"]) > 86400 and "known" not in v1,
    "D1 이틀 된 사건에 NEW 가 더해져도 오너 확인 없이 '알려진 사항'으로 접히지 않음", v1.get("known"))
vv = health.web_view(T2)
chk(vis(vv, "price:unpriced"), "D1b 화면(/api/health)에서도 보이는 주의(접힌 목록이 아님)", item(vv, "price:unpriced"))
chk(health.known_note("price:unpriced", "warn", "x", T2 - 10 * 86400, T2) is None, "D1c 열흘 된 '시세 없는 실보유'도 시간만으로 known 아님")

print("[D2] 판정 재료 = 전체 + 자산 신원")
import web  # noqa: E402
ws = [{"sym": f"T{i}", "qty": 1.0, "cost": 2000.0 + i, "ref": 0.0, "where": "지갑", "ent": f"eth:0x{i:040x}"} for i in range(10)]
ws.append({"sym": "ELEVEN", "qty": 1.0, "cost": 999.0, "ref": 0.0, "where": "지갑", "ent": "arbitrum:0x" + "0b" * 20})
ws.append({"sym": "DUST", "qty": 1.0, "cost": 0.4, "ref": 0.0, "where": "지갑", "ent": "eth:0x" + "0d" * 20})
fx = T.safe(getattr(web, "unpriced_facts", None) or (lambda w: None), ws)
fx = fx if isinstance(fx, list) else []
chk(any(x.get("sym") == "ELEVEN" and x.get("ent") == "arbitrum:0x" + "0b" * 20 for x in fx) and len(fx) == 11,
    "D2 11번째 새 자산(원가 $999)이 판정 재료에 남음 · 자산 신원(ent) 실림 · $1 미만 먼지는 뺌", [x.get("sym") for x in fx])
wsrc = T.web_src()
chk('"unpriced_held": diag_out["unpriced_held"]' not in wsrc and '"unpriced_held": unpriced_facts(unpriced_w)' in wsrc,
    "D2b 생산 경로: web_diag(헬스 입력)는 전체 재료 · 화면 진단(_diag)의 상위 10개 미리보기와 분리")
cs2 = health.evaluate(obs_of(NOW, webdiag=wd(NOW, unpriced=fx)), HS)
c2 = next((c for c in cs2 if c["id"] == "price:unpriced"), {})
chk(c2.get("level") == "warn" and "arbitrum:0x" + "0b" * 20 in (c2.get("ack") or {}),
    "D2c 판정 사실(항목 단위)에 11번째 자산이 있음(상세 문장은 3개까지만이어도)", sorted((c2.get("ack") or {}))[:12])
chk(len(c2.get("ack") or {}) == 11, "D2d 기준($500) 넘는 11개 전부 항목으로", len(c2.get("ack") or {}))
ow = {"sym": "OLDENT", "qty": 1.0, "cost": 900.0, "ref": 0.0, "where": "지갑"}
c3 = next((c for c in health.evaluate(obs_of(NOW, webdiag=wd(NOW, unpriced=[ow])), HS) if c["id"] == "price:unpriced"), {})
chk(list((c3.get("ack") or {}).keys()) == ["sym:OLDENT|지갑"], "D2e 신원 없는 옛 재료 = 심볼·위치 키(판정은 그대로)", c3.get("ack"))
same = [uph("SAME", 700, "eth:0x" + "5a" * 20), uph("SAME", 800, "base:0x" + "5b" * 20)]
c4 = next((c for c in health.evaluate(obs_of(NOW, webdiag=wd(NOW, unpriced=same)), HS) if c["id"] == "price:unpriced"), {})
chk(len(c4.get("ack") or {}) == 2, "D2g 같은 심볼 다른 자산(체인·컨트랙트 다름) = 항목 둘", c4.get("ack"))
chk(health_ack.fp("price:unpriced", "warn", {"a": 1.0, "b": 2.0}) == health_ack.fp("price:unpriced", "warn", {"b": 999.0, "a": None})
    and health_ack.fp("price:unpriced", "warn", {"a": 1}) != health_ack.fp("price:unpriced", "warn", {"a": 1, "c": 1}),
    "D2h 지문 = 항목 집합(순서·금액·문장 바뀜 무시 · 항목이 늘면 다름)")
ent_fn = getattr(web, "unpriced_ent", None)
chk(callable(ent_fn) and ent_fn([("base", "0xB"), ("arbitrum", "0xA")], None, "SYM") == "arbitrum:0xA"
    and ent_fn([], "binance", "SYM") == "ex:binance:SYM" and ent_fn([], None, "SYM") == "sym:SYM"
    and ent_fn([("sol", "So1AbCdEf")], None, "X") == "sol:So1AbCdEf",
    "D2f 자산 신원 = 체인:컨트랙트(정렬 첫 쌍 · 솔라나 대소문자 보존) · 거래소:심볼 · 그 밖 심볼")

print("[A] 닫기 — 같은 내용 숨김 · 바뀌면 다시")
for f9 in (health_ack.path(),):
    if os.path.exists(f9):
        os.remove(f9)
st = {}
T0 = NOW - 7200
for k in range(3):
    run(st, T0 + k * 1900, unpriced=[OLD])
TA = T0 + 3 * 1900
run(st, TA, unpriced=[OLD])
v = health.web_view(TA)
x = item(v, "price:unpriced") or {}
fp0 = (x.get("ack") or {}).get("fp")
chk(vis(v, "price:unpriced") and isinstance(fp0, str) and len(fp0) == 16 and "ackEnts" not in x,
    "A1 열린 주의에 닫기 지문(fp) · 내부 항목 사실은 화면에 안 냄", {k: x.get(k) for k in ("ack", "acked", "ackEnts")})
ap = getattr(health, "ack_apply", None)


def apx(*a):
    if not callable(ap):
        return (None, "ack_apply 없음")
    r9 = T.safe(ap, *a)
    return r9 if isinstance(r9, tuple) else (None, r9)


r_bad = apx("price:unpriced", "0" * 16, TA)
chk(r_bad[0] is False, "A2 지문이 다르면(그 사이 내용이 바뀜) 닫기 거절", r_bad)
r_ok = apx("price:unpriced", fp0, TA)
chk(r_ok[0] is True, "A3 지금 지문으로 닫기", r_ok)
v = health.web_view(TA + 1)
x = item(v, "price:unpriced") or {}
chk(bool(x.get("acked")) and not vis(v, "price:unpriced"), "A3b 닫은 주의 = 숨김(닫은 시각 표시)", x.get("acked"))
cp = health.compact(v)
chk(cp.get("warn") == 0 and cp.get("acked") == 1, "A3c 상태 요약(상단 칩 재료) 주의 0 · 닫음 1", cp)
chk(any(e.get("check") == "price:unpriced" for e in (v.get("acks") or [])), "A3d '닫은 주의' 목록에 있음(되살리기 재료)", v.get("acks"))
uw = next((u for u in v.get("units") or [] if u.get("unit") == "tj-web"), {})
chk(uw.get("level") == "ok" and any(o.get("id") == "price:unpriced" and o.get("acked") for o in uw.get("other") or []),
    "A3f 유닛 표도 같은 기준(그 유닛의 열린 문제가 닫은 주의뿐 = 점 정상 · 칩 흐리게)", {k: uw.get(k) for k in ("level", "other")})
inc = (st.get("incidents") or {}).get("price:unpriced") or {}
chk(bool(inc) and not inc.get("resolved"), "A3e 닫기 = 표시만(판정 사건은 그대로 열림)", inc.get("resolved"))
run(st, TA + 60, unpriced=[dict(OLD, cost=1000.0)])
chk(not vis(health.web_view(TA + 61), "price:unpriced"), "A4 작은 금액 변동(+$100 · 11%) = 그대로 숨김")
run(st, TA + 120, unpriced=[OLD, NEW])
v = health.web_view(TA + 121)
x = item(v, "price:unpriced") or {}
chk(vis(v, "price:unpriced") and x.get("ackChanged"), "A5 새 코인(NEW) = 다시 보임('바뀌어서 다시' 표시)", {k: x.get(k) for k in ("acked", "ackChanged")})
fp1 = (x.get("ack") or {}).get("fp")
chk(fp1 and fp1 != fp0, "A5b 지문 = 항목 집합(새 코인이면 다른 지문)", (fp0, fp1))
chk(apx("price:unpriced", fp0, TA + 121)[0] is False,
    "A5c 예전 화면(OLD 만 본 지문)으로 누른 닫기 = 새 위험에 적용 안 됨(거절)")
r2 = apx("price:unpriced", fp1, TA + 122)
chk(r2[0] is True and not vis(health.web_view(TA + 123), "price:unpriced"), "A6 다시 닫기 = OLD+NEW 기억 · 숨김", r2)
run(st, TA + 180, unpriced=[OLD])
chk(not vis(health.web_view(TA + 181), "price:unpriced"), "A6b NEW 가 빠져도(부분 집합) 숨김 유지")
run(st, TA + 240, unpriced=[dict(OLD, cost=1600.0), NEW])
chk(vis(health.web_view(TA + 241), "price:unpriced"), "A7 금액 크게 늚(50% 그리고 $200 넘게) = 다시 보임")
e9 = {"ents": {"k": 1000.0}}
chk(health_ack.covered(e9, "warn", {"k": 1150.0}) and not health_ack.covered(e9, "warn", {"k": 1600.0})
    and health_ack.covered({"ents": {"k": 100.0}}, "warn", {"k": 280.0}) and not health_ack.covered(e9, "crit", {"k": 1000.0})
    and health_ack.covered({"ents": {"k": None}}, "warn", {"k": None}),
    "A7b 늚 판정 = 비율·금액 둘 다(1000→1150 숨김 · →1600 보임 · 100→280 숨김(+$180)) · 빨강 = 늘 보임 · 금액 없는 항목 = 항목만")
chk(health_ack.ack("ledger:neg", "warn", {"a": 1}, now=TA)[0] is False and health_ack.ack("price:unpriced", "crit", {"a": 1}, now=TA)[0] is False,
    "A8 닫기 대상 아님(원장 음수 보유 등 돈 숫자 무결성) · 오류(빨강) = 닫기 불가")
rr = T.safe(health_ack.restore, "price:unpriced")
run(st, TA + 300, unpriced=[OLD, NEW])
chk(isinstance(rr, tuple) and rr[0] and vis(health.web_view(TA + 301), "price:unpriced") and not (health.web_view(TA + 301).get("acks") or []),
    "A9 되살리기 = 다시 보임 · 닫은 목록에서 빠짐", rr)
x = item(health.web_view(TA + 301), "price:unpriced") or {}
apx("price:unpriced", (x.get("ack") or {}).get("fp"), TA + 302)
open(health_ack.path(), "w").write("{깨짐")
v = health.web_view(TA + 303)
chk(vis(v, "price:unpriced") and v.get("ackErr"), "A10 닫은 기록 손상 = 아무것도 숨기지 않음 + 안내", v.get("ackErr"))
r3 = apx("price:unpriced", (x.get("ack") or {}).get("fp"), TA + 304)
chk(r3[0] is False and open(health_ack.path()).read() == "{깨짐", "A10b 손상 파일 = 닫기 거절 · 덮어쓰지 않음", r3)
statefile.atomic_write_json(health_ack.path(), {"v": 99, "items": {"price:unpriced": {"ents": {}}}})
chk(vis(health.web_view(TA + 305), "price:unpriced"), "A10c 모르는 판(v99) = 숨기지 않음")
if os.path.exists(health_ack.path()):
    os.remove(health_ack.path())

print("[T] 텔레그램·요약 = 같은 기준")
HT = health.settings({"health": {"units": UNITS, "telegram_min_level": "warn", "tg_min_age_sec": 0, "digest_hour": 0, "flap_hold_sec": 0}})


def cs_obs(now, fs):
    return obs_of(now, chainsweep={"findings": fs, "chains": 30, "checkedAt": now})


F1 = {"chain": "polygon", "name": "Polygon", "wallet": "0x" + "c1" * 20, "label": "w1", "usd": 120.0}
F2 = {"chain": "gnosis", "name": "Gnosis", "wallet": "0x" + "c2" * 20, "label": "w2", "usd": 40.0}


def tg_round(st, now, fs, plan_it=True):
    ob = cs_obs(now, fs)
    cs = health.evaluate(ob, HT, open_ids={k: v.get("unit") for k, v in (st.get("incidents") or {}).items()})
    ev = health.step(st, cs, now, HT)
    if plan_it:
        health.plan(st, ev, now, HT, True)
    statefile.atomic_write_json(paths.state("health_status.json"), health.build_status(st, ob, cs, now, HT))


def opens_of(st):
    return [o for o in st.get("outbox") or [] if o.get("kind") in ("open", "group") and any("chainsweep" in str(i) for i in o.get("incs") or [])]


st1 = {"digest_date": "x"}
tg_round(st1, NOW, [F1])
tg_round(st1, NOW + 60, [F1])
chk(len(opens_of(st1)) == 1, "T1 (대조) 닫기 전 = 주의 알림 1통(알림 수준 '주의'로 둔 설치)", st1.get("outbox"))
st2 = {"digest_date": "x"}
tg_round(st2, NOW, [F1], plan_it=False)
tg_round(st2, NOW + 60, [F1], plan_it=False)
x = item(health.web_view(NOW + 61), "chainsweep:untracked") or {}
ra = apx("chainsweep:untracked", (x.get("ack") or {}).get("fp"), NOW + 61)
chk(ra[0] is True, "T2 미추적 체인 주의 닫기", ra)
health.plan(st2, [], NOW + 62, HT, True)
chk(not opens_of(st2), "T2b 닫은 주의 = 텔레그램 안 보냄", st2.get("outbox"))
st2.pop("digest_date", None)
health.plan(st2, [], NOW + 63, HT, True)
chk(not [o for o in st2.get("outbox") or [] if o.get("kind") == "digest"], "T3 하루 요약에도 안 실림(닫은 주의뿐)", st2.get("outbox"))
tg_round(st2, NOW + 120, [F1, F2])
chk(len(opens_of(st2)) == 1, "T4 새 지갑·체인(F2) = 다시 알림", st2.get("outbox"))
os.remove(health_ack.path())
st3 = {"digest_date": "x"}
tg_round(st3, NOW, [F1], plan_it=False)
tg_round(st3, NOW + 60, [F1], plan_it=False)
st3.pop("digest_date", None)
health.plan(st3, [], NOW + 63, HT, False)
st3.pop("digest_date", None)
health.plan(st3, [], NOW + 64, HT, True)
chk(any(o.get("kind") == "digest" for o in st3.get("outbox") or []), "T3b (대조) 안 닫은 주의 = 하루 요약에 실림", st3.get("outbox"))
import alert_bot  # noqa: E402
p5 = T.safe(alert_bot._open_problems, st3)
chk(isinstance(p5, list) and any("미추적 체인" in t for t in p5), "T5 (대조) tj-alert 하루 요약 재료에 안 닫은 주의 있음", p5)
x = item(health.web_view(NOW + 65), "chainsweep:untracked") or {}
apx("chainsweep:untracked", (x.get("ack") or {}).get("fp"), NOW + 65)
p6 = T.safe(alert_bot._open_problems, st3)
chk(isinstance(p6, list) and not any("미추적 체인" in t for t in p6), "T5b 닫은 주의 = tj-alert 하루 요약 재료에서도 빠짐", p6)
if os.path.exists(health_ack.path()):
    os.remove(health_ack.path())

print("[C] 기준 재정비")
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, debt=[("okx", "loan", "USDT", -1000.0, 1000.0)]), HS)}
d1 = ev.get("debt:margin") or {}
chk(d1.get("level") == "ok" and "1,000" in str(d1.get("chip")) and "차감" in str(d1.get("detail")),
    "C1 차입 부채(달러 값 있음 = 총자산에서 이미 차감) = 주의 아님 · 칩 '부채 $1,000' 은 유지", {k: d1.get(k) for k in ("level", "chip", "detail")})
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, debt=[("okx", "margin", "ZZZ", -5.0, None)]), HS)}
d2 = ev.get("debt:margin") or {}
chk(d2.get("level") == "warn" and "okx:margin:ZZZ" in (d2.get("ack") or {}), "C2 시세 모르는 부채(차감액 미상) = 주의 · 닫기 가능", {k: d2.get(k) for k in ("level", "title", "ack")})
chk(health.known_note("debt:margin", "warn", "x", NOW - 999999, NOW) is None, "C2b 부채 주의는 '알려진 사항'으로 자동 접지 않음(닫기로)")
disc = {"pairs": 3, "done": 0, "failPairs": 3, "failBy": {"eth": 2, "base": 1}, "skip": 0, "hold": 0, "chains": {}, "noOld": []}
bc = {"checkedAt": NOW, "confirmed": 0, "watch": 0, "resolving": 0, "errors": 0, "top": None, "items": [], "unchecked": 0, "capped": False, "pairs": 3, "disc": disc}
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, balcheck=bc), HS)}
d3 = ev.get("balcheck:disc") or {}
chk(d3.get("level") == "warn" and float(d3.get("persist") or 0) >= 86400 and not d3.get("ack"),
    "C3 토큰 발견 실패(자동 재시도) = 24시간 넘게 이어질 때만 주의(그 전엔 '관찰 중') · 요약 집계만 있고 항목 재료 없으면 닫기 없음(쌍 단위는 K2)",
    {k: d3.get(k) for k in ("level", "persist", "ack")})
st4 = {}
for k in range(3):
    ob4 = obs_of(NOW + k * 600, balcheck=bc)
    cs4 = health.evaluate(ob4, HS)
    health.step(st4, cs4, NOW + k * 600, HS)
b4 = health.build_status(st4, ob4, cs4, NOW + 1200, HS)
chk("balcheck:disc" not in (st4.get("incidents") or {}) and any(w.get("id") == "balcheck:disc" for w in b4.get("watching") or []),
    "C3b 20분째 = 열린 주의 아님 · '관찰 중'에 보임", list((st4.get("incidents") or {}).keys()))
st7 = {"incidents": {"balcheck:disc": {"id": "balcheck:disc@1", "check": "balcheck:disc", "unit": "tj-web", "title": "토큰 발견 실패 3쌍", "detail": "",
                                        "action": "", "level": "warn", "peak": "warn", "opened": NOW - 12 * 3600, "since": NOW - 12 * 3600, "notify": False,
                                        "remind": False, "msg_id": None, "announced": None, "kind": "balcheck"}}}
ev7 = health.step(st7, health.evaluate(obs_of(NOW, balcheck=bc), HS), NOW, HS)
h7 = [x for x in st7.get("history") or [] if x.get("check") == "balcheck:disc"]
chk("balcheck:disc" not in st7["incidents"] and h7 and h7[0].get("quiet") and not ev7,
    "C3c 일회 이행: 옛 기준(지속 0)으로 12시간 전 열린 주의 = 조용히 '관찰 중'으로(알림·복구 이벤트 없음)", (list(st7["incidents"]), ev7))
st8 = {"incidents": {"balcheck:disc": dict(st7["history"][0], resolved=None, quiet=None, opened=NOW - 30 * 3600, since=NOW - 30 * 3600)}}
health.step(st8, health.evaluate(obs_of(NOW, balcheck=bc), HS), NOW, HS)
chk("balcheck:disc" in st8["incidents"], "C3d 새 기준(24시간)도 넘긴 사건 = 그대로 열림", list(st8["incidents"]))
sol = {"sol": {"sources": {"sol": {"helius_daycap_until": NOW + 3600, "helius_continue": True, "head_rpc_on": True, "head_rpc_open_until": NOW + 600}}}}
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, hb=sol), HS)}
chk((ev.get("quota:helius") or {}).get("level") == "warn" and float((ev.get("quota:helius") or {}).get("persist") or 0) >= 21600
    and float((ev.get("rpc:sol_head") or {}).get("persist") or 0) >= 21600,
    "C4 Helius 하루 예산 소진·공개 노드 이상(저절로 회복 · 대체 노드로 계속) = 6시간 넘게 이어질 때만 주의",
    {k: (ev.get(k) or {}).get("persist") for k in ("quota:helius", "rpc:sol_head")})
gw = wd(NOW, goplus={"lastOk": NOW - 7200, "pendingNew": 3, "started": NOW - 9000})
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, webdiag=gw), HS)}
chk((ev.get("goplus:queue") or {}).get("level") == "warn" and float((ev.get("goplus:queue") or {}).get("persist") or 0) >= 21600,
    "C5 고플러스 확증 조회 정체(스캠 라벨만 늦어짐 · 저절로 회복) = 6시간 넘게 이어질 때만", (ev.get("goplus:queue") or {}).get("persist"))
bw = wd(NOW, build={"n": 9, "p50": 70000, "p95": 90000, "last_ms": 80000})
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, webdiag=bw), HS)}
chk((ev.get("web:build") or {}).get("level") == "warn" and float((ev.get("web:build") or {}).get("persist") or 0) >= 21600,
    "C5b 웹 빌드 느림(화면 신선도만 · 저절로 회복) = 6시간 넘게 이어질 때만", (ev.get("web:build") or {}).get("persist"))
pd = wd(NOW, proof_div=[{"gid": 7, "sym": "PRF", "ex": "bybit", "cex": 1.0, "dex": 1.3, "res": 9e5, "pair": "eth:0x" + "e1" * 20, "diff": 0.3, "usd": 800.0}])
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, webdiag=pd), HS)}
chk((ev.get("price:proof") or {}).get("level") == "warn" and (ev.get("price:proof") or {}).get("ack") == {"bybit:eth:0x" + "e1" * 20: 800.0},
    "C6 시세 괴리 = 주의 유지(평가 숫자) · 거래소+DEX 쌍 단위 닫기(보유 금액 기준)", (ev.get("price:proof") or {}).get("ack"))
rb = wd(NOW, rabby={"wallets": [{"addr": "0x" + "d1" * 20, "label": "rw", "bot": 1000.0, "rabby": 3000.0, "only": 500.0, "rest": 1500.0,
                                 "fetchedAt": NOW, "top": [], "gapSince": NOW - 2 * 86400}], "status": "ok"})
ev = {c["id"]: c for c in health.evaluate(obs_of(NOW, webdiag=rb), HS)}
r6 = ev.get("rabby:gap") or {}
chk(r6.get("level") == "warn" and r6.get("ack") == {"0x" + "d1" * 20: 1500.0} and "빠져 있을 수" in str(r6.get("action")) and "1,500" in str(r6.get("detail")),
    "C7 Rabby 남은 차이(총자산에 안 들어간 몫) = 주의 유지 · 지갑 단위 닫기 · 문구가 남은 차이를 '이미 포함'이라 하지 않고 그 금액을 보임", {k: r6.get(k) for k in ("ack", "action", "detail")})
ev = {c["id"]: c for c in health.evaluate(cs_obs(NOW, [F1]), HS)}
chk((ev.get("chainsweep:untracked") or {}).get("ack") == {"polygon:" + "0x" + "c1" * 20: 120.0}, "C8 미추적 체인 = 체인·지갑 단위 닫기", (ev.get("chainsweep:untracked") or {}).get("ack"))

print("[K] 코덱스 hl925 — 돈 숫자가 틀릴 수 있는 새 위험은 숨기지 않음")
SP = os.path.join(S, "spot.json")
EXB = os.path.join(S, "exf_balances_okx.json")


def debt_rows(spot, debts):
    statefile.atomic_write_json(SP, spot)
    statefile.atomic_write_json(EXB, {"debts": debts})
    r9 = T.safe(health.collect_debt, None, NOW, HS)
    os.remove(SP)
    os.remove(EXB)
    return r9 if isinstance(r9, list) else []


rk1 = debt_rows({"usd": {"NEO": 10.0}, "ex_usd": {}, "ex_ts": {}}, {"NEO": -100})
ek1 = {c["id"]: c for c in health.evaluate(obs_of(NOW, debt=rk1), HS)}
chk(rk1 and rk1[0][4] is None and (ek1.get("debt:margin") or {}).get("level") == "warn",
    "K1 그 거래소 시세 없음(전역 심볼 시세만) = 총자산 차감 0 → 값 모름 주의(정보로 내리지 않음)", (rk1, (ek1.get("debt:margin") or {}).get("level")))
rk2 = debt_rows({"usd": {"NEO": 10.0}, "ex_usd": {"okx:NEO": 9.5}, "ex_ts": {"okx:NEO": NOW - 60}}, {"NEO": -100})
chk(rk2 and abs(float(rk2[0][4] or 0) - 950.0) < 1e-6, "K1b 그 거래소 신선 시세 = 그 값으로(총자산과 같은 금액)", rk2)
rk3 = debt_rows({"usd": {"NEO": 10.0}, "ex_usd": {"okx:NEO": 9.5}, "ex_ts": {"okx:NEO": NOW - 7200}}, {"NEO": -100})
chk(rk3 and rk3[0][4] is None, "K1c 그 거래소 시세가 1시간 넘게 낡음 = 값 모름(총자산도 평가 제외)", rk3)
rk4 = debt_rows({"usd": {}, "ex_usd": {}, "ex_ts": {}}, {"USDT": -500})
chk(rk4 and abs(float(rk4[0][4] or 0) - 500.0) < 1e-6, "K1d 스테이블 부채 = $1 그대로(정보)", rk4)

import token_discovery as TD  # noqa: E402
WA, WB = "0x" + "aa" * 20, "0x" + "bb" * 20
CFGD = {"wallets": [{"type": "evm", "chain": "eth", "address": WA}, {"type": "evm", "chain": "base", "address": WB}]}


def disc_round(pairs):
    statefile.atomic_write_json(TD.state_path(), {"pairs": pairs})
    statefile.atomic_write_json(os.path.join(S, "onchain_check.json"), {"checkedAt": NOW, "mismatches": [], "disc": TD.summary(CFGD, {"pairs": pairs}, {})})
    try:
        b9 = health.collect_balcheck(CFGD)
    except TypeError:
        b9 = health.collect_balcheck()
    return next((c for c in health.evaluate(obs_of(NOW, balcheck=b9), HS) if c["id"] == "balcheck:disc"), {})


PA = {TD.pair_key("eth", WA): {"at": NOW, "fail": {"etherscan": "429 한도"}}}
k2a = disc_round(PA)
r9 = health_ack.ack("balcheck:disc", "warn", k2a.get("ack") or {}, now=NOW) if k2a.get("ack") else (False, "닫기 재료 없음")
dk = health_ack.load()[0]
k2b = disc_round(dict(PA, **{TD.pair_key("base", WB): {"at": NOW, "fail": {"etherscan": "429 한도"}}}))
chk(r9[0] and k2b.get("level") == "warn" and health_ack.state(dk, "balcheck:disc", "warn", k2b.get("ack") or {}) != "acked",
    "K2 같은 출처(etherscan)의 다른 지갑·체인 새 실패 = 닫은 기록 밖(다시 보임)", (k2a.get("ack"), k2b.get("ack")))
PH = {TD.pair_key("eth", WA): {"at": NOW, "skip": {"0x" + "c1" * 20: "일시 보류 — 덱스 판정 장애"}}}
k2c = disc_round(PH)
health_ack.ack("balcheck:disc", "warn", k2c.get("ack") or {"x": None}, now=NOW)
dk = health_ack.load()[0]
k2d = disc_round({TD.pair_key("eth", WA): {"at": NOW, "skip": {"0x" + "c1" * 20: "일시 보류 — 덱스 판정 장애", "0x" + "c2" * 20: "일시 보류 — 덱스 판정 장애"}}})
chk(k2d.get("level") == "warn" and health_ack.state(dk, "balcheck:disc", "warn", k2d.get("ack") or {}) != "acked",
    "K2b 판정 대기 토큰이 새로 늘면 다시 보임(토큰 단위)", (k2c.get("ack"), k2d.get("ack")))
statefile.atomic_write_json(os.path.join(S, "onchain_check.json"), {"checkedAt": NOW, "mismatches": [],
                                                                  "disc": dict(TD.summary(CFGD, {"pairs": PA}, {}), failPairs=5)})
try:
    b9 = health.collect_balcheck(CFGD)
except TypeError:
    b9 = health.collect_balcheck()
k2e = next((c for c in health.evaluate(obs_of(NOW, balcheck=b9), HS) if c["id"] == "balcheck:disc"), {})
chk(k2e.get("level") == "warn" and not k2e.get("ack"), "K2c 요약 건수와 발견 상태가 다르면(갱신 사이) 닫기 재료 없음 = 보이는 쪽", k2e.get("ack"))
PM = {TD.pair_key("eth", WA): {"at": NOW, "fail": {"etherscan": "more: 한 실행 몫 — 다음 실행에서 이어서"}},
      TD.pair_key("base", WB): {"at": NOW, "fail": {"alchemy": "http: 503"}}}
k2f = disc_round(PM)
ents9 = (health.collect_balcheck(CFGD).get("disc") or {}).get("ackEnts") or {}
chk(TD.summary(CFGD, {"pairs": PM}, {}).get("failPairs") == 1 and k2f.get("level") == "warn" and k2f.get("ack")
    and set(ents9) == {"fail:" + TD.pair_key("base", WB) + ":alchemy"},
    "K2d 한 지갑 '이어 받는 중(more)' + 다른 지갑 실제 실패 = 요약 1쌍 · 닫기 재료도 그 1쌍(more 는 실패 아님)", (k2f.get("ack"), sorted(ents9)))
r9d = health_ack.ack("balcheck:disc", "warn", k2f.get("ack") or {}, now=NOW) if k2f.get("ack") else (False, "닫기 재료 없음")
dk = health_ack.load()[0]
k2g = disc_round(PM)
chk(r9d[0] and health_ack.state(dk, "balcheck:disc", "warn", k2g.get("ack") or {}) == "acked",
    "K2d' 닫은 뒤 같은 상태 = 닫힘 유지(다시 드러나지 않음)", (r9d, k2g.get("ack")))
CAQ = {"0x%040x" % (i + 1): ["etherscan"] for i in range(TD.MAX_QUERY + 1)}
PQ = {TD.pair_key("eth", WA): {"at": NOW, "cas": CAQ}}
k2h = disc_round(PQ)
ents9 = (health.collect_balcheck(CFGD).get("disc") or {}).get("ackEnts") or {}
chk(TD.summary(CFGD, {"pairs": PQ}, {}).get("failPairs") == 1 and k2h.get("level") == "warn" and k2h.get("ack")
    and set(ents9) == {"fail:" + TD.pair_key("eth", WA) + ":query"},
    "K2e 저장 실패 없이 후보 3,001개(질문 상한 초과) = 요약 1쌍 · 닫기 재료 'query' 1개", (k2h.get("ack"), sorted(ents9)))
SCAM = "0x" + "ee" * 20
PR = {TD.pair_key("eth", WA): {"at": NOW, "cas": dict(list(CAQ.items())[:TD.MAX_QUERY], **{SCAM: ["rabby"]}), "meta": {SCAM: {"rbscam": True}}}}
disc_round(PR)
ents9 = (health.collect_balcheck(CFGD).get("disc") or {}).get("ackEnts")
chk(TD.summary(CFGD, {"pairs": PR}, {}).get("failPairs") == 0 and ents9 == {},
    "K2f Rabby 스캠 단독 후보는 상한 셈에서 제외(요약·닫기 재료 둘 다 0)", sorted(ents9 or {}))
for f9 in (TD.state_path(), os.path.join(S, "onchain_check.json"), health_ack.path()):
    if os.path.exists(f9):
        os.remove(f9)

stk = {"digest_date": "x"}
tg_round(stk, NOW, [F1])
tg_round(stk, NOW + 60, [F1])
sent9 = []
health.deliver(stk, lambda text, reply: (sent9.append(text) or True, 77, None), NOW + 61, HT)
ann9 = bool(((stk.get("incidents") or {}).get("chainsweep:untracked") or {}).get("announced"))
xk = item(health.web_view(NOW + 62), "chainsweep:untracked") or {}
rk = apx("chainsweep:untracked", (xk.get("ack") or {}).get("fp"), NOW + 62)
tg_round(stk, NOW + 120, [F1, F2])
chk(len(sent9) == 1 and ann9 and rk[0] is True and len(opens_of(stk)) == 1,
    "K3 알린 뒤 닫은 주의에 새 지갑·체인(F2) = 다시 알림 대기열", (len(sent9), ann9, rk, stk.get("outbox")))
os.remove(health_ack.path())
stk2 = {"digest_date": "x"}
tg_round(stk2, NOW, [F1])
tg_round(stk2, NOW + 60, [F1])
health.deliver(stk2, lambda text, reply: (True, 78, None), NOW + 61, HT)
xk = item(health.web_view(NOW + 62), "chainsweep:untracked") or {}
apx("chainsweep:untracked", (xk.get("ack") or {}).get("fp"), NOW + 62)
tg_round(stk2, NOW + 120, [F1])
chk(not opens_of(stk2) and ((stk2.get("incidents") or {}).get("chainsweep:untracked") or {}).get("announced"),
    "K3b (대조) 알린 뒤 닫고 내용 그대로 = 다시 안 알림 · 보냄 표식 유지", stk2.get("outbox"))
if os.path.exists(health_ack.path()):
    os.remove(health_ack.path())

chk(not health_ack.covered({"ents": {"k": None}}, "warn", {"k": 10000.0}) and health_ack.covered({"ents": {"k": None}}, "warn", {"k": 150.0})
    and health_ack.covered({"ents": {"k": None}}, "warn", {"k": None}),
    "K4 금액 미상으로 닫음 → $10,000 = 다시 보임 · $150(기준 $200 미만)·여전히 미상 = 숨김")

st5k = {}
for k in range(3):
    run(st5k, NOW - 7000 + k * 1900, unpriced=[OLD])
run(st5k, NOW - 1000, unpriced=[OLD])
fp5 = ((item(health.web_view(NOW - 999), "price:unpriced") or {}).get("ack") or {}).get("fp")
run(st5k, NOW - 900, unpriced=[dict(OLD, cost=1600.0)])
r5k = apx("price:unpriced", fp5, NOW - 899)
chk(r5k[0] is False and not os.path.exists(health_ack.path()), "K5 화면에 $900 일 때 받은 닫기 → 그 사이 $1,600 = 거절(새로고침해서 보고 다시)", r5k)
run(st5k, NOW - 800, unpriced=[dict(OLD, cost=1000.0)])
fp6 = ((item(health.web_view(NOW - 799), "price:unpriced") or {}).get("ack") or {}).get("fp")
run(st5k, NOW - 700, unpriced=[dict(OLD, cost=1100.0)])
chk(apx("price:unpriced", fp6, NOW - 699)[0] is True, "K5b 작은 변동(+$100) 사이 닫기 = 그대로 됨")
if os.path.exists(health_ack.path()):
    os.remove(health_ack.path())
run(st5k, NOW - 600, unpriced=[dict(OLD, cost=10000.0)])
health.web_view(NOW - 599)
run(st5k, NOW - 500, unpriced=[dict(OLD, cost=1000.0)])
fp7 = ((item(health.web_view(NOW - 499), "price:unpriced") or {}).get("ack") or {}).get("fp")
run(st5k, NOW - 400, unpriced=[dict(OLD, cost=2000.0)])
r7 = apx("price:unpriced", fp7, NOW - 399)
chk(r7[0] is False and not os.path.exists(health_ack.path()), "K5c 하락 뒤 화면($1,000)의 닫기 → 그 사이 $2,000 = 거절", r7)
U9 = {"sym": "UNK", "where": "업비트", "qty": 1.0, "cost": 0.0, "ref": 1000.0, "ent": "ex:upbit:UNK"}
EX9 = {"ex": "binance", "sym": "DEADX", "qty": 10.0, "ref": 100.0}
run(st5k, NOW - 300, unpriced=[U9], ex_dead_held=[EX9])
health.web_view(NOW - 299)
run(st5k, NOW - 250, unpriced=[U9], ex_dead_held=[dict(EX9, ref=None)])
fp8 = ((item(health.web_view(NOW - 249), "price:unpriced") or {}).get("ack") or {}).get("fp")
run(st5k, NOW - 200, unpriced=[U9], ex_dead_held=[dict(EX9, ref=90.0)])
r8 = apx("price:unpriced", fp8, NOW - 199)
chk(r8[0] is False and not os.path.exists(health_ack.path()), "K5d 금액 미상으로 보인 화면의 닫기 → 그 사이 $900 = 거절", r8)
if os.path.exists(health_ack.path()):
    os.remove(health_ack.path())

print("[H] HTTP — 출처·CSRF · 409 · 바로 반영")
from http.server import ThreadingHTTPServer  # noqa: E402
import onboarding  # noqa: E402
import settings_store as ss  # noqa: E402
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
threading.Thread(target=SRV.serve_forever, daemon=True, name="t-health-ack").start()
ORIGIN, HOST = f"http://127.0.0.1:{PORT}", f"127.0.0.1:{PORT}"


def req(method, path, body=None, csrf=True, origin=True):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60)
    h = {"Host": HOST}
    if method == "POST":
        h["Content-Type"] = "application/json"
        if origin:
            h["Origin"] = ORIGIN
        if csrf:
            h["X-TJ-CSRF"] = ss.csrf_token()
    c.request(method, path, body=json.dumps(body or {}).encode() if method == "POST" else None, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw.decode() or "null")
    except ValueError:
        return r.status, None


st5 = {}
for k in range(3):
    run(st5, time.time() - 4000 + k * 1900, unpriced=[OLD])
run(st5, time.time(), unpriced=[OLD])
s0, j0 = req("GET", "/api/health")
x = item((j0 or {}).get("health"), "price:unpriced") or {}
fpH = (x.get("ack") or {}).get("fp")
chk(s0 == 200 and fpH and vis((j0 or {}).get("health"), "price:unpriced"), "H1 GET /api/health = 닫기 지문 실린 주의", (s0, x.get("ack")))
s1, _j1 = req("POST", "/api/health/ack", {"check": "price:unpriced", "fp": fpH}, csrf=False)
s2, _j2 = req("POST", "/api/health/ack", {"check": "price:unpriced", "fp": fpH}, origin=False)
chk(s1 == 403 and s2 == 403 and not os.path.exists(health_ack.path()), "H2 CSRF 없음·출처 없음 = 403 · 기록 없음", (s1, s2))
s3, j3 = req("POST", "/api/health/ack", {"check": "price:unpriced", "fp": "f" * 16})
chk(s3 == 409 and j3 and not j3.get("ok"), "H3 지문 다름 = 409(새로고침 뒤 다시)", (s3, j3))
s4, j4 = req("POST", "/api/health/ack", {"check": "price:unpriced", "fp": fpH})
chk(s4 == 200 and j4 and j4.get("ok") and not vis(j4.get("health"), "price:unpriced"), "H4 닫기 = 200 · 응답의 상태에 바로 반영(다음 판정 전)", (s4, (j4 or {}).get("msg")))
s5, j5 = req("GET", "/api/health")
chk(s5 == 200 and not vis((j5 or {}).get("health"), "price:unpriced"), "H4b 다시 받아도 닫힘")
s6, j6 = req("POST", "/api/health/restore", {"check": "price:unpriced"})
chk(s6 == 200 and vis((j6 or {}).get("health"), "price:unpriced"), "H5 되살리기 = 200 · 바로 보임", s6)
s7, _j7 = req("POST", "/api/health/ack", {"check": "x" * 500, "fp": fpH})
s8, _j8 = req("POST", "/api/health/ack", {"check": "price:unpriced", "fp": ["x"]})
chk(s7 in (400, 409) and s8 in (400, 409), "H6 이상한 값(긴 id · 문자열 아님) = 거절", (s7, s8))
SRV.shutdown()
SRV.server_close()

print("[U] 화면(health.js) — 닫기 · 닫은 주의 · 되살리기 · 바로가기")
HJ = open(os.path.join(T.ROOT, "web", "v2", "health.js"), encoding="utf-8").read()
chk("/api/health/ack" in HJ and "/api/health/restore" in HJ and "닫은 주의" in HJ and "되살리기" in HJ,
    "U1 닫기·되살리기 요청 · '닫은 주의' 목록")
chk("'chainsweep:untracked'" in HJ and "settings/wallets" in HJ, "U2 미추적 체인 = 닫기 옆 '지갑 추가' 바로가기")
chk("<select" not in HJ, "U3 브라우저 기본 컨트롤 없음")
T.finish()
