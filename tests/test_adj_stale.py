#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402

os.environ["TJ_ALLOW_NEW_LEDGER"] = "1"
import paths  # noqa: E402
import health  # noqa: E402
import recon_adj  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
NOW = 1_800_000_000
DAY = 86400
HS = health.settings({"health": {"units": ["tj-core"]}})
LIM = float(HS["t"].get("adj_stale_sec") or 0) or None


def ev(doc, open_ids=(), unreadable=None, now=NOW):
    obs = {"now": now, "pm2": {"tj-core": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [],
           "hb": {"core": {"ts": now, "ok": True}}, "recon_adj": doc}
    if unreadable is not None:
        obs["unreadable"] = unreadable
    return {x["id"]: x for x in health.evaluate(obs, HS, open_ids)}.get("ledger:adj")


ok_doc = recon_adj.summarize([], now=NOW)
chk(ok_doc["check"]["level"] == "ok", "재료: 빈 원장 요약 = ok", ok_doc["check"])


def at(doc, ts):
    d = json.loads(json.dumps(doc))
    if ts is None:
        d.pop("ts", None)
    else:
        d["ts"] = ts
    return d


c = ev(ok_doc)
chk(c is not None and c["level"] == "ok" and "관측 지연" not in c["detail"], "A1 신선한 정상 = ok", c and (c["level"], c["title"]))
c = ev(at(ok_doc, NOW - 2 * 3600))
chk(c is not None and c["level"] == "ok", "A1 2시간 전(갱신 10분 · core 재구축으로 막힐 수 있는 시간 안) = ok", c and (c["level"], c["detail"]))
c = ev(at(ok_doc, NOW + 60))
chk(c is not None and c["level"] == "ok", "A1 시계 1분 앞섬 = ok(작은 시계 차이 허용)", c and (c["level"], c["detail"]))

old = recon_adj.summarize([], now=NOW - 30 * DAY)
c = ev(old)
chk(c is not None and c["level"] == "warn", "A2 30일 전 정상 = 주의(ok 아님)", c and (c["level"], c["title"]))
chk(c is not None and "관측 지연" in c["title"] and "마지막 확인" in c["detail"] and "30일" in c["detail"], "A2 제목 '관측 지연' · 상세 마지막 확인 시각·나이",
    c and (c["title"], c["detail"]))
chk(c is not None and not c["notify"] and not c.get("tg_force"), "A2 관측 지연 = 알림 없음(대시보드 주황)", c and (c["notify"], c.get("tg_force")))
c = ev(at(ok_doc, NOW - 12 * 3600))
chk(c is not None and c["level"] == "warn", "A2 12시간 전 정상 = 주의", c and (c["level"], c["detail"]))

crit = dict(ok_doc, check={"title": "보정 버그 꼴 2건", "level": "crit", "tg": True, "detail": "창 이전 원장 행을 되받는 앵커 2", "action": "점검"})
c = ev(at(crit, NOW - 30 * DAY))
chk(c is not None and c["level"] == "crit" and c["title"] == "보정 버그 꼴 2건" and c["notify"], "A3 오래된 빨강 = 빨강·제목·알림 성질 유지", c and (c["level"], c["title"], c["notify"]))
chk(c is not None and "관측 지연" in c["detail"] and "창 이전 원장 행" in c["detail"], "A3 오래된 빨강 상세 = 관측 지연 + 당시 판정", c and c["detail"])
warn = dict(ok_doc, check={"title": "설명 안 된 보정 7일 $1,200", "level": "warn", "tg": True, "detail": "7일 2건", "action": "확인"})
c = ev(at(warn, NOW - 30 * DAY))
chk(c is not None and c["level"] == "warn" and c["title"] == "설명 안 된 보정 7일 $1,200" and c.get("tg_force") is True and "관측 지연" in c["detail"],
    "A3 오래된 노랑 = 노랑·텔레그램 성질 유지 + 관측 지연", c and (c["level"], c["title"], c.get("tg_force"), c["detail"]))

for lbl, ts in (("미래 1일", NOW + DAY), ("시각 없음", None), ("글자", "abc"), ("참거짓", True), ("NaN", float("nan")), ("무한", float("inf")), ("0", 0), ("범위 밖 정수", 10 ** 400), ("음수", -5)):
    c = ev(at(ok_doc, ts))
    chk(c is not None and c["level"] == "warn" and "관측" in c["title"], f"A4 {lbl} = 주의(ok 아님)", c and (c["level"], c["title"], c["detail"]))

unr = {"files": {"recon_adj.json": "JSONDecodeError"}, "since": {"recon_adj.json": NOW - 60}, "rules": ["ledger:adj"], "fail_chains": []}
c = ev(None, open_ids={"ledger:adj": "tj-core"}, unreadable=unr)
chk(c is not None and c["level"] is None, "A5 손상 파일 + 열린 사건 = 판단 보류(직전 판정 유지)", c and (c["level"], c["detail"]))
chk(ev(None) is None and ev({"v": 1, "ts": NOW}) is None, "A5 파일 없음·check 칸 없음 = 항목 없음(정상 아님)")

conn = sqlite3.connect(":memory:")
import db  # noqa: E402
for ddl in db.DDL:
    conn.execute(ddl)
WT0 = lambda ref, sec: NOW - 100 * DAY  # noqa: E731
st = {}
d0 = recon_adj.tick(conn, WT0, None, NOW - 5 * 3600, st)
chk(isinstance(d0, dict) and os.path.exists(paths.state("recon_adj.json")), "A6 재료: 5시간 전 성공 판정 = 상태 파일")


class Broken:
    def execute(self, *a):
        raise sqlite3.OperationalError("database is locked")


chk(recon_adj.tick(Broken(), WT0, None, NOW, st) is None, "A6 감시 실패(tick 예외) = 삼킴(파일 그대로)")
disk = health._read(paths.state("recon_adj.json"), None)
c = ev(disk)
chk(c is not None and c["level"] == "warn" and "관측 지연" in c["title"], "A6 core 정상 + 감시 실패 5시간 = 관측 지연 주의", c and (c["level"], c["title"], c["detail"]))
st["checked"] = 0.0
d1 = recon_adj.tick(conn, WT0, None, NOW, st)
c = ev(health._read(paths.state("recon_adj.json"), None))
chk(isinstance(d1, dict) and c is not None and c["level"] == "ok" and "관측 지연" not in c["detail"], "A6 갱신 한 번 성공 = ok 복구", c and (c["level"], c["detail"]))
chk(LIM is None or LIM >= 2 * recon_adj.REFRESH_SEC, "A6 나이 상한 ≥ 갱신 주기 2배(설정했다면)", LIM)
T.finish()
