#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as H

import json
import os
import time

os.environ["TJ_HEALTH"] = "0"
os.environ["TJ_TG_API"] = "http://127.0.0.1:9/never"
S = os.path.join(H.TMP, "state")
with open(os.path.join(H.TMP, "config.json"), "w") as f:
    json.dump({}, f)
with open(os.path.join(H.TMP, ".env"), "w") as f:
    f.write("TJ_TG_TOKEN=000000:fake-test-token\nTJ_TG_CHAT=12345\nTJ_TG_API=http://127.0.0.1:9/never\n")
import common
import alert_prefs as AP
import alert_bot as ab


def check(name, ok, detail=""):
    H.chk(bool(ok), name, None if ok else str(detail)[:400])


FQ = getattr(AP, "FAST_QUEUE", "alerts_fast.jsonl")


def setup(lines):
    for fn in ("alerts_web.jsonl", "pending_dm.jsonl", FQ, "tg_cursor.json", "alert_hold.json", "alert_stats.json"):
        try:
            os.remove(os.path.join(S, fn))
        except FileNotFoundError:
            pass
    with open(os.path.join(S, "alerts_web.jsonl"), "w", encoding="utf-8") as f:
        for d in lines:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: AP.preset_doc("rec")})
    common.atomic_write_json(os.path.join(H.TMP, "config.json"), {})


def run_chunk(turn_off):
    sent = []
    now = int(time.time())
    setup([{"ts": now, "kind": "DEPEG", "text": "🔴 일반 A\n확인하세요."}, {"ts": now, "kind": "TARGET_HIT", "text": "🔴 일반 B\n확인하세요."},
           {"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": "🔴 청산 C\n증거금을 넣으세요."}])

    def fsend(token, chat, text):
        sent.append(text.split("\n")[0])
        return True
    o_send, o_sleep, o_hook = ab.send, ab.time.sleep, ab._urgent_hook
    flag = [0]

    def hook():
        if not flag[0]:
            flag[0] = 1
            turn_off()
            time.sleep(0.02)
        o_hook()
    ab.send = fsend
    ab._urgent_hook = hook
    ab.time.sleep = lambda x: None
    try:
        cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
        st, hold = ab.load_stats(), ab.load_hold()
        doc = AP.load()
        if hasattr(ab, "_URG"):
            ab._URG.update(token="t", chat="c", cursor=cursor, doc=doc, conn=None, st=st, hold=hold)
            ab._URG["pos"].clear()
        ab._SENT_TIMES.clear()
        ab.run_source("alerts_web.jsonl", "t", "c", cursor, doc, None, st, hold, {}, None)
        return sent, cursor["alerts_web.jsonl"], os.path.getsize(os.path.join(S, "alerts_web.jsonl"))
    finally:
        ab.send, ab.time.sleep, ab._urgent_hook = o_send, o_sleep, o_hook


def off_cat():
    d = AP.preset_doc("rec")
    d["cats"]["liq"] = "off"
    common.atomic_write_json(os.path.join(S, "ui_prefs.json"), {AP.PREF_KEY: d})


def off_cfg():
    common.atomic_write_json(os.path.join(H.TMP, "config.json"), {"alerts": {"liq_fast": False}})


sent, cur, size = run_chunk(off_cat)
check("B1 일반 발송 중 '청산 근접' 끔 → 같은 청크의 긴급 줄 안 보냄 · 커서는 끝까지", "🔴 청산 C" not in sent and cur == size, (sent, cur, size))
sent, cur, size = run_chunk(off_cfg)
check("B2 config alerts.liq_fast=false 로 꺼도 같음", "🔴 청산 C" not in sent and cur == size, (sent, cur, size))
sent, cur, size = run_chunk(lambda: None)
check("B0 (대조) 안 끄면 긴급 줄 1통", sent.count("🔴 청산 C") == 1, sent)

now = int(time.time())
p = os.path.join(S, FQ)
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps({"ts": now - 7200, "kind": "LIQ_NEAR", "text": "🔴 옛 줄 1"}, ensure_ascii=False) + "\n")
    f.write(json.dumps({"ts": now - 4000, "kind": "LIQ_NEAR", "text": "🔴 옛 줄 2"}, ensure_ascii=False) + "\n")
    f.write(json.dumps({"ts": now - 30, "kind": "LIQ_NEAR", "text": "🔴 최근 줄"}, ensure_ascii=False) + "\n")
cur = {}
ab.init_cursor(cur)
with open(p, "rb") as f:
    rest = f.read()[cur.get(FQ, 0):].decode("utf-8")
check("B3 긴급 큐 커서 새로 만들 때 — 1시간 넘은 옛 줄 건너뛰고 최근 줄부터", "옛 줄" not in rest and "최근 줄" in rest, (cur.get(FQ), rest[:80]))
def urgent_two(between):
    sent = []
    now = int(time.time())
    setup([])
    with open(os.path.join(S, FQ), "w", encoding="utf-8") as f:
        for t in ("🔴 긴급 1", "🔴 긴급 2"):
            f.write(json.dumps({"ts": now, "kind": "LIQ_NEAR", "cat": "liq", "text": t + "\n증거금을 넣으세요."}, ensure_ascii=False) + "\n")
    o_send, o_sleep = ab.send, ab.time.sleep
    ab.send = lambda tok, chat, text: sent.append(text.split("\n")[0]) or True
    ab.time.sleep = lambda x: between() if x == 0.3 else None
    try:
        cursor = {"alerts_web.jsonl": 0, "pending_dm.jsonl": 0, FQ: 0}
        ab._URG.update(token="t", chat="c", cursor=cursor, doc=AP.load(), conn=None, st=ab.load_stats(), hold=ab.load_hold(), prefs_m=None)
        ab._URG["pos"].clear()
        ab.urgent_pass()
        return sent
    finally:
        ab.send, ab.time.sleep = o_send, o_sleep


sent = urgent_two(off_cat)
check("B4 연속 발송 사이(0.3초 쉼) '청산 근접' 끔 → 두 번째 긴급 줄 안 보냄", sent == ["🔴 긴급 1"], sent)
envp = os.path.join(H.TMP, ".env")
env0 = open(envp).read()


def unlink_tg():
    open(envp, "w").write("")


sent = urgent_two(unlink_tg)
open(envp, "w").write(env0)
check("B5 연속 발송 사이 텔레그램 연결 해제 → 두 번째 긴급 줄 안 보냄(받아 둔 자격 증명으로 보내지 않음)", sent == ["🔴 긴급 1"], sent)
H.finish()
