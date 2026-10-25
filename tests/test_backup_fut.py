#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import builtins  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tarfile  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

json.dump({"wallets": [], "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths  # noqa: E402
import db as D  # noqa: E402
import fsio  # noqa: E402
import health as H  # noqa: E402
import ledger_backup as L  # noqa: E402
import ledger_restore as R  # noqa: E402
import offsite_backup as O  # noqa: E402
import offsite_seal as S  # noqa: E402

assert T.TMP in paths.STATE_DIR
chk = T.chk
SD = paths.STATE_DIR
paths.ensure_dirs()
c = D.open_db(paths.DB_PATH)
c.execute("INSERT INTO raw_txs VALUES('eth', 'synthetic_tx', 1, NULL, 1700000000, '{}', '[]', 1700000000)")
c.commit()
c.close()


def wj(rel, obj, sd=SD):
    p = os.path.join(sd, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def rj(rel, sd=SD):
    with open(os.path.join(sd, rel), encoding="utf-8") as f:
        return json.load(f)


def ev(uid, t, amt, sym="BTCUSDT", acct=None):
    r = {"uid": uid, "t": t, "symbol": sym, "kind": "REALIZED", "amount": amt}
    if acct:
        r["acct"] = acct
    return r


T0 = 1_767_600_000_000
CANON = {"ts": 1_767_600_100, "wallet": {"balance": 10.0, "note": None}, "positions": [{"symbol": "BTCUSDT", "qty": 1}],
         "events": [ev("w1", T0, 100.0, acct="s1"), ev("l1", T0 + 10_000, -100.0, "ETHUSDT", acct="s1")], "cursor": {"bill": "c-old"},
         "accts": ["main", "s1"]}
RAW_S1 = {"ts": 1_767_600_100, "events": [ev("w1", T0, 100.0), ev("l1", T0 + 10_000, -100.0, "ETHUSDT")], "cursor": {"bill": "c-s1"}}
RAW_MAIN = {"ts": 1_767_600_100, "events": [], "cursor": {"bill": "c-main"}}
RAW_ARCH = {"ts": 1_767_000_000, "events": [ev("a1", T0 - 99_000, 5.0)]}

wj("futures_tkx.json", CANON)
wj("futraw_tkx_main.json", RAW_MAIN)
wj("futraw_tkx_s1.json", RAW_S1)
wj("futraw_tkx_s1@u777.json", RAW_ARCH)
wj("futures_px_tkx.json", {"rows": []})
wj("futuresnot.json", {"x": 1})
out = L.backup_files("20260105", SD)
fd = os.path.join(SD, "backups", "files_20260105")
want = ("futures_tkx.json", "futraw_tkx_main.json", "futraw_tkx_s1.json", "futraw_tkx_s1@u777.json", "futures_px_tkx.json")
chk(all(isinstance(out.get(n), int) and os.path.isfile(os.path.join(fd, n)) for n in want) and "futuresnot.json" not in out,
    "F1 선물 정본·계정별 원본(보관 딱지 @ 포함)·가격 옆 파일 = 원장 밖 사본에 들어감(종전 = 정본·원본 빠짐)", sorted(out))

man = O.build(log=lambda *a: None)
arc = os.path.join(O.OUT_DIR, man["files"]["name"])
with tarfile.open(arc, "r:gz") as tf:
    mem = tf.getnames()
chk(all(f"files_20260105/{n}" in mem for n in want), "F2a 서버 밖 묶음에 선물 정본·원본이 들어감", [m for m in mem if "fut" in m])
key = S.load_key(O.AUTH_KEY)
rs = os.path.join(T.TMP, "restore_state")
os.makedirs(os.path.join(rs, "backups"))
placed = O.unpack_files(O.OUT_DIR, man["stamp"], key, dst_dir=os.path.join(rs, "backups"), log=lambda *a: None)
chk(all(os.path.isfile(os.path.join(rs, "backups", "files_20260105", n)) for n in want),
    "F2b 풀기 = 선물 정본·원본(보관 딱지 @ 이름 포함)을 제자리에", sorted(os.listdir(os.path.join(rs, "backups", "files_20260105"))))

fp = R.files_plan("20260105", rs)
rel = sorted(r for _s, r in fp["items"])
want3 = tuple(n for n in want if n != "futraw_tkx_s1.json")
chk(all(n in rel for n in want3) and "futraw_tkx_s1.json" not in rel and any("futraw_tkx_s1.json" in x and "커서" in x for x in fp["info"]),
    "F3a 빈 state = 선물 정본·메인 원본·보관 딱지 원본 되돌림 계획 · 활성 서브 칸 원본은 계정 확인 전이라 커서 안 되살림(안내)", fp)
res = R.files_apply(fp, proc_check=False, state_dir=rs, log=lambda *a: None)
chk(rj("futures_tkx.json", rs) == CANON and rj("futraw_tkx_s1@u777.json", rs) == RAW_ARCH and all(n in res["restored"] for n in want3)
    and not os.path.exists(os.path.join(rs, "futraw_tkx_s1.json")),
    "F3b 되돌린 정본 = 사본 그대로(정산 2건 · 계정 딱지 · 커서) · 서브 칸 원본 없음(그 칸은 처음 창부터)", res["restored"])
for n9 in ("futures_tkx.json", "futraw_tkx_s1.json"):
    os.remove(os.path.join(SD, n9))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc3 = R.main(["files", "20260105"])
chk(rc3 == 0 and "tj-exf" in buf.getvalue() and "futures_tkx.json" in buf.getvalue(), "F3c 선물 파일을 되돌릴 땐 tj-exf 도 멈춤 안내(적용은 tj-exf 떠 있으면 거부)",
    buf.getvalue()[-300:])

rs2 = os.path.join(T.TMP, "restore_state2")
shutil.copytree(os.path.join(rs, "backups"), os.path.join(rs2, "backups"))
CUR = {"ts": 1_799_000_000, "wallet": {"balance": 3.0, "note": "now"}, "positions": [],
       "events": [ev("n1", T0 + 9_000_000_000, 7.0, acct="s1"), ev("w1", T0, 100.0, acct="s1")], "cursor": {"bill": "c-new"},
       "accts": ["main", "s1"]}
CUR_RAW = {"ts": 1_799_000_000, "events": [ev("n1", T0 + 9_000_000_000, 7.0)], "cursor": {"bill": "c-s1-new"}}
wj("futures_tkx.json", CUR, rs2)
wj("futraw_tkx_s1.json", CUR_RAW, rs2)
fp2 = R.files_plan("20260105", rs2)
info2 = " | ".join(fp2["info"])
chk("futures_tkx.json" in [r for _s, r in fp2["items"]] and "futraw_tkx_s1.json" not in [r for _s, r in fp2["items"]]
    and "futraw_tkx_s1.json" in info2 and "1" in info2,
    "F4a 지금 정본 있음 = 합치기 계획(사본에만 있는 정산 수 안내) · 지금 계정별 원본 있음 = 그대로(안내)", {"items": fp2["items"], "info": fp2["info"]})
res2 = R.files_apply(fp2, proc_check=False, state_dir=rs2, log=lambda *a: None)
got = rj("futures_tkx.json", rs2)
uids = sorted((r.get("acct"), r["uid"]) for r in got["events"])
chk(uids == [("s1", "l1"), ("s1", "n1"), ("s1", "w1")] and got["wallet"] == CUR["wallet"] and got["positions"] == [] and got["ts"] == CUR["ts"]
    and got["cursor"] == CUR["cursor"] and rj("futraw_tkx_s1.json", rs2) == CUR_RAW,
    "F4b 합집합 = 지금 정산 + 사본에만 있는 정산(중복 없음) · 지금 지갑·포지션·시각·커서·원본 그대로(옛 관측 승격 없음)", {"ev": uids, "got": got})
kept = res2.get("kept") or ""
chk(os.path.isfile(os.path.join(kept, "futures_tkx.json")) and json.load(open(os.path.join(kept, "futures_tkx.json"))) == CUR,
    "F4c 합치기 전 지금 정본 = restore_files_<시각>/ 에 보존", kept)
fp2b = R.files_plan("20260105", rs2)
chk("futures_tkx.json" not in [r for _s, r in fp2b["items"]], "F4d 다시 계획 = 더 합칠 정산 없음(정보만 · 같은 결과 반복 안 씀)", fp2b["info"])

rs3 = os.path.join(T.TMP, "restore_state3")
os.makedirs(os.path.join(rs3, "backups", "files_20251201"))
wj(os.path.join("backups", "files_20251201", "daily_px.json"), {"d": 1}, rs3)
wj(os.path.join("backups", "files_20251201", "buy_evals.json"), {"b": 1}, rs3)
fp3 = R.files_plan("20251201", rs3)
chk(sorted(r for _s, r in fp3["items"]) == ["buy_evals.json", "daily_px.json"] and not fp3.get("warn"),
    "F5 옛 형식 사본(선물·상태 파일 없음) = 되돌리기 계획 종전 그대로 · 경고 없음", fp3)

rs6 = os.path.join(T.TMP, "restore_state6")
shutil.copytree(os.path.join(rs, "backups"), os.path.join(rs6, "backups"))
CUR6 = dict(CUR, events=[ev("w1", T0, 100.0, acct="s1@u111"), ev("n2", T0 + 5, 1.0, acct="s1")])
wj("futures_tkx.json", CUR6, rs6)
fp6 = R.files_plan("20260105", rs6)
rel6 = [r for _s, r in fp6["items"]]
chk("futures_tkx.json" not in rel6 and not any(r.startswith("futraw_tkx_") for r in rel6) and any("계정 교체" in x for x in fp6["info"]),
    "F6a 계정 교체 흔적(보관 딱지)이 사본과 다름 = 정본 합치기·계정별 원본 되살림 안 함(안내) — 옛 정산이 새 계정 딱지로 중복되지 않게", fp6)
m6, k6 = R.fut_union({"events": [ev("w1", T0, 100.0, acct="s2")]}, {"events": [ev("w1", T0, 100.0, acct="s1"), ev("z9", T0 + 1, 2.0, acct="s1")]})
m6c, k6c = R.fut_union({"events": [ev("a1", T0, 1.0, acct="s1@u111"), ev("n3", T0 + 9, 2.0, acct="s1")]},
                       {"events": [ev("a1", T0, 1.0, acct="s1@u111"), ev("a0", T0 - 9, 3.0, acct="s1@u111")]})
chk(k6c == 1 and [r["uid"] for r in m6c["events"]] == ["a0", "a1", "n3"],
    "F6c 보관 딱지 묶음이 같고 지금에만 활성 딱지(새 계정 정산)가 있음 = 정상 합집합(사본에만 있는 옛 계정 정산 되살림)", m6c)
chk(k6 == 2 and sorted((r["acct"], r["uid"]) for r in m6["events"]) == [("s1", "w1"), ("s1", "z9"), ("s2", "w1")],
    "F6b 같은 정산 번호라도 계정 모르는 다른 칸 = 다른 계정(번호는 계정 안에서만 유일) — 둘 다 남김(종전 = 사본 쪽 지움)", m6)
m6d, k6d = R.fut_union({"events": [ev("w1", T0, 100.0, acct="s2")]}, {"events": [ev("w1", T0, 100.0, acct="s1"), ev("z9", T0 + 1, 2.0, acct="s1")]},
                       {"s2": {"uid": "U9"}}, {"s1": {"uid": "U9"}})
e6 = R._new_rows([ev("w1", T0, 100.0, acct="s1@uU9")], [ev("w1", T0, 100.0, acct="s1"), ev("w2", T0, 1.0, acct="s1")], {}, {"s1": {"uid": "U9", "kfp": "abcd1234"}})
chk(k6d == 1 and [r["uid"] for r in m6d["events"]] == ["w1", "z9"] and [r["uid"] for r in e6] == ["w2"],
    "F6d 같은 계정(지금 칸·사본 지도 UID 같음 · 보관 딱지 이름 UID) = 칸·딱지가 달라도 같은 정산 번호는 한 번", {"d": m6d, "e": e6})

import envfile  # noqa: E402
import ex_foreign as XF  # noqa: E402
k7 = R._new_rows([ev("e7", T0, 7.0, acct="s1")], [ev("e7", T0, 7.0, acct="s1")], None, {"s1": {"uid": "UA"}})
chk(k7 == [], "F7a 같은 활성 칸 이름 + 같은 정산 번호 = 같은 정산(지금 칸 계정 모름 · 사본 지도 UID 앎) — 수집 상태 없이 같은 사본을 두 번 되돌려도 두 번 안 셈", k7)
rs7 = os.path.join(T.TMP, "restore_state7")
os.makedirs(os.path.join(rs7, "backups", "files_20260107"))
wj(os.path.join("backups", "files_20260107", "futraw_tkx_s1.json"), RAW_S1, rs7)
wj(os.path.join("backups", "files_20260107", "exf_ident.json"), {"v": 1, "ex": {"tkx": {"active": {"s1": {"uid": "UA"}}, "hist": {}}}}, rs7)
fp7 = R.files_plan("20260107", rs7)
R.files_apply(fp7, proc_check=False, state_dir=rs7, log=lambda *a: None)
got7 = rj("futures_tkx.json", rs7) if os.path.exists(os.path.join(rs7, "futures_tkx.json")) else {}
chk(sorted((r.get("acct"), r["uid"]) for r in got7.get("events") or []) == [("s1@uUA", "l1"), ("s1@uUA", "w1")] and not os.path.exists(os.path.join(rs7, "futraw_tkx_s1.json"))
    and os.path.exists(os.path.join(rs7, "futraw_tkx_s1@uUA.json")),
    "F7b 정본 없이 원본만 든 사본 + 지금 칸 계정 모름 = 활성 칸 원본(커서) 안 되살림 · 정산은 사본 계정 보관 딱지로 정본에(버리지 않음 · 다음 칸 계정에 안 섞임)", got7)
chk(R.fut_bind(None, {"seen": {"x": 1}, "backfilled_until": 5}, "s1") == ("fold", "s1") and R.fut_bind(None, {"kfp": "abcd1234"}, "s1") == ("hold", None)
    and R.fut_bind({"uid": "UA"}, {"uid": "UB"}, "s1") == ("move", "s1@uUA") and R.fut_bind({"uid": "UA"}, {"uid": "UA", "kfp": "0f0f0f0f"}, "s1") == ("same", "s1")
    and R.fut_bind({"uid": "UA"}, None, "s1") == ("move", "s1@uUA") and R.fut_bind({"uid": "UA"}, {"uid": "UC"}, "s1", True) == ("fold", "s1"),
    "F7c 칸 결합: 둘 다 모름 = 정산만 같은 칸 · 사본 계정 모름 + 지금 계정 앎 = 손으로 · 다른 UID 또는 지금 모름 = 사본 계정 보관 딱지 · 같은 UID = 그대로 ·"
    " 정체 모르는 줄기(fut_keep) = 칸 딱지 그대로", None)
sd7 = os.path.join(T.TMP, "ident7")
os.makedirs(sd7)
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UA", "seen": {"x": 1}}}}}, sd7)
ok7 = envfile.ident_snapshot(sd7)
with open(os.path.join(sd7, "exf_ident.json"), "w") as f:
    f.write("{broken")
bad7 = envfile.ident_snapshot(sd7)
os.remove(os.path.join(sd7, "exf_ident.json"))
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UB", "seen": {"x": 1}}}}}, sd7)
moved7 = envfile.ident_snapshot(sd7, ok7)
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UB", "seen": {"x": 1}}}, "fut_retag": [["s1", "s1@uUA"]]}}, sd7)
pend7 = envfile.ident_snapshot(sd7)
chk(ok7[0] and ok7[1] is None and bad7[0] is None and bad7[1] and moved7[0] is None and moved7[1] and pend7[0] is None and pend7[1],
    "F7d 계정 지도 사본 = 지난 지도 못 읽음 · 사본 앞뒤 계정 바뀜 · 계정 교체 일지 남음이면 오류(사본 불완전 · 이력 잃은 지도를 완전으로 안 씀)", [ok7[1], bad7[1], moved7[1], pend7[1]])
os.makedirs(os.path.join(T.TMP, "state"), exist_ok=True)
statefile_w = __import__("statefile").atomic_write_json
statefile_w(paths.state("exf_state.json"), {"tkx": {"accts": {"s1": {"uid": "UA", "seen": {"x": 1}}}}})
statefile_w(paths.state("futures_tkx.json"), {"ts": 1, "events": [ev("e9", T0, 3.0, acct="s1@uUA"), ev("e8", T0 - 5, 1.0, acct="s1@uUA")]})
statefile_w(paths.state("futraw_tkx_main.json"), {"ts": 2, "events": []})
statefile_w(paths.state("futraw_tkx_s1.json"), {"ts": 2, "events": [ev("e9", T0, 3.0)]})
XF._fut_merge("tkx", ["", "s1"])
m7 = sorted((r.get("acct"), r["uid"]) for r in rj("futures_tkx.json")["events"])
chk(m7 == [("s1", "e9"), ("s1@uUA", "e8")], "F7e 보관 딱지 계정(UA) = 지금 활성 칸 계정이고 같은 정산을 다시 받음 = 한 번(활성 칸 쪽) · 다시 안 받은 옛 정산은 보관 딱지 그대로", m7)

rs8 = os.path.join(T.TMP, "restore_state8")
os.makedirs(os.path.join(rs8, "backups", "files_20260108"))
wj(os.path.join("backups", "files_20260108", "futures_tkx.json"), {"ts": 5, "events": [ev("a8", T0, 3.0, acct="s1")]}, rs8)
wj(os.path.join("backups", "files_20260108", "exf_ident.json"), {"v": 1, "ex": {"tkx": {"active": {"s1": {"uid": "UA"}}, "hist": {}}}}, rs8)
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UB", "seen": {"y": 1}}}}}, rs8)
wj("futures_tkx.json", {"ts": 9, "events": [ev("b8", T0 + 1, 17.0, acct="s1")]}, rs8)
R.files_apply(R.files_plan("20260108", rs8), proc_check=False, state_dir=rs8, log=lambda *a: None)
m8 = sorted((r.get("acct"), r["uid"]) for r in rj("futures_tkx.json", rs8)["events"])
rs9 = os.path.join(T.TMP, "restore_state9")
os.makedirs(os.path.join(rs9, "backups", "files_20260109"))
wj(os.path.join("backups", "files_20260109", "futures_tkx.json"), {"ts": 5, "events": [ev("a9", T0, 3.0, acct="s1"), ev("b9", T0, 1.0, acct="s1")]}, rs9)
wj(os.path.join("backups", "files_20260109", "exf_ident.json"), {"v": 1, "ex": {"tkx": {"active": {"s1": {"uid": "UB"}}, "hist": {}, "fut_keep": ["s1"]}}}, rs9)
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UC", "seen": {"y": 1}, "fut_keep": 1}}}}, rs9)
wj("futures_tkx.json", {"ts": 9, "events": [ev("c9", T0 + 1, 17.0, acct="s1")]}, rs9)
R.files_apply(R.files_plan("20260109", rs9), proc_check=False, state_dir=rs9, log=lambda *a: None)
m9 = sorted((r.get("acct"), r["uid"]) for r in rj("futures_tkx.json", rs9)["events"])
chk(m8 == [("s1", "b8"), ("s1@uUA", "a8")] and m9 == [("s1", "a9"), ("s1", "b9"), ("s1", "c9")],
    "F7f 원본 없이 정본에만 있는 칸도 계정 결합(사본 UA ≠ 지금 UB = 보관 딱지) · 정체 모르는 줄기(사본 지도 fut_keep) 칸 = 여러 계정 정산이라 칸 딱지 그대로", {"m8": m8, "m9": m9})
m10, k10 = R.fut_union({"events": [ev("e1", T0, 3.0, acct="s1")]}, {"events": [ev("e1", T0, 3.0, acct="s1@uUA")], "bound": ["s1"]}, {}, {"s1": {"uid": "UA"}})
m11, k11 = R.fut_union({"events": [ev("e1", T0, 3.0, acct="s1")]}, {"events": [ev("e1", T0, 3.0, acct="s1@uUA")], "bound": ["s1"]},
                       {"s1": {"uid": "UA"}}, {"s1": {"uid": "UA"}})
chk(k10 == -1 and m10 is None and k11 == 0,
    "F7h 지도로 보관 딱지에 옮긴 칸 + 지금 정본에 그 칸 활성 정산 + 지금 칸 계정 모름(수집 상태만 잃음) = 안 합침(같은 정산 두 번 방지) · 지금 계정 같으면 한 번", [k10, k11])
rs7i = os.path.join(T.TMP, "restore_state7i")
os.makedirs(os.path.join(rs7i, "backups", "files_20260107"))
wj(os.path.join("backups", "files_20260107", "futures_tkx.json"), {"ts": 5, "events": [ev("a7i", T0, 3.0, acct="s1")]}, rs7i)
wj(os.path.join("backups", "files_20260107", "exf_ident.json"), {"v": 1, "ex": {"tkx": {"active": {"s1": {"uid": "UA"}}, "hist": {}}}}, rs7i)
wj("exf_state.json", {"tkx": {"accts": {"s1": {"uid": "UA", "seen": {"y": 1}}}}}, rs7i)
fp7i = R.files_plan("20260107", rs7i)
R.files_apply(fp7i, proc_check=False, state_dir=rs7i, log=lambda *a: None)
k7i = ((rj("exf_ident.json", rs7i) or {}).get("ex") or {}).get("tkx") or {}
chk(not (fp7i.get("fut_keep") or {}).get("tkx") and not k7i.get("fut_keep") and [r["uid"] for r in rj("futures_tkx.json", rs7i)["events"]] == ["a7i"],
    "F7i 정본에만 있는 칸이 사본 때와 같은 계정(UID 같음 = same) = 정체 모르는 줄기(fut_keep) 표식 안 함(다음 계정 교체 때 보관 딱지로 정상 이동) · 정산 그대로",
    {"plan": fp7i.get("fut_keep"), "map": k7i})
import hashlib  # noqa: E402
statefile_w(paths.state("exf_ident.json"), {"v": 1, "ex": {"tkx": {"active": {}, "hist": {}, "fut_keep": ["s1"]}}})
kb8, ka8 = hashlib.sha256(b"tk-b8").hexdigest()[:8], hashlib.sha256(b"tk-a8").hexdigest()[:8]
st8 = {"tkx": {"seen": {}, "accts": {}}}
XF.acct_ident(st8, "tkx", "s1", "tk-b8", {"tkx_sub1": {"uid": "UB", "kfp": kb8}}, 100)
st8["tkx"]["accts"]["s1"].update(seen={"y": 1}, backfilled_until=100)
st8["tkx"].pop("fut_retag", None)
XF.acct_ident(st8, "tkx", "s1", "tk-a8", {"tkx_sub1": {"uid": "UA", "kfp": ka8}}, 200)
ops8 = st8["tkx"].get("fut_retag")
os.remove(paths.state("exf_ident.json"))
u8 = R.ident_union({"v": 1, "ex": {}}, {"v": 1, "ex": {"tkx": {"active": {}, "hist": {}, "fut_keep": ["s1"], "hold": ["s2"]}}})["ex"]["tkx"]
chk(ops8 == [["s1", "s1", "unraw"]] and u8.get("fut_keep") == ["s1"] and u8.get("hold") == ["s2"],
    "F8a 되돌린 지도의 정체 모르는 줄기 칸(fut_keep) = 그 칸 새 계정 상태도 줄기로 → 다음 계정 교체 때 옛 정산을 한 계정 보관 딱지로 안 옮김(원본만 치움) ·"
    " 지도 합집합이 줄기·보류 표식을 지킴", {"ops": ops8, "union": u8})
rs8b = os.path.join(T.TMP, "restore_state8b")
os.makedirs(os.path.join(rs8b, "backups", "files_20260110"))
c8 = D.open_db(os.path.join(rs8b, "ledger.db"))
c8.execute("INSERT INTO raw_ex VALUES('bybit', 'fill', 'bybit:s1:p8', 1, '{}', 1700000000)")
c8.execute("INSERT INTO raw_ex VALUES('bybit', 'fill', 'bybit:s2:q8', 1, '{}', 1700000000)")
c8.commit()
c8.close()
wj(os.path.join("backups", "files_20260110", "exf_ident.json"), {"v": 1, "ex": {"bybit": {"active": {}, "hist": {"s2": [{"uid": "UQ"}]}}}}, rs8b)
h8 = R.files_plan("20260110", rs8b).get("hold")
wj(os.path.join("backups", "files_20260110", "exf_ident.json"), {"v": 1, "ex": {}}, rs8b)
h8e = R.files_plan("20260110", rs8b).get("hold")
chk(h8 == {"bybit": ["s1"]} and h8e == {"bybit": ["s1", "s2"]},
    "F8b 수집 상태 없는 전체 복구 + 지도 파일은 있지만 원장에 기록 있는 칸이 지도 이력에 없음(빈 지도 · 칸 빠짐) = 그 칸 보류(종전 = 지도 파일만 있으면 보류 없음)", {"part": h8, "empty": h8e})
rs9b = os.path.join(T.TMP, "restore_state9b")
os.makedirs(os.path.join(rs9b, "backups", "files_20260111"))
c9b = D.open_db(os.path.join(rs9b, "ledger.db"))
c9b.execute("INSERT INTO raw_ex VALUES('bybit', 'fill', 'bybit:s1:p9', 1, '{}', 1700000000)")
c9b.commit()
c9b.close()
wj(os.path.join("backups", "files_20260111", "buy_evals.json"), {"b": 1}, rs9b)
wj("exf_state.json", {}, rs9b)
h9a = R.files_plan("20260111", rs9b).get("hold")
wj("exf_state.json", {"bybit": {"accts": {"s1": {"seen": {"x": 1}, "backfilled_until": 5}}}}, rs9b)
h9b = R.files_plan("20260111", rs9b).get("hold")
chk(h9a == {"bybit": ["s1"]} and not h9b,
    "F9a 수집 상태 파일이 있어도(빈 상태 · 메인만) 원장에 기록 있는 서브 칸이 상태·지도 어디에도 없으면 보류 · 그 칸 상태에 이력 있으면 보류 없음", {"empty": h9a, "live": h9b})
cur9 = {"key_perm": {"bybit_sub1": {"at": 500, "kkfp": "bbbbbbbb"}}}
k9i = R.settings_keep_ident(cur9, b'{"key_perm": {"bybit_sub1": {"at": 1e309, "kkfp": "aaaaaaaa"}}, "x": 1}')
k9n = R.settings_keep_ident(cur9, b'{"key_perm": {"bybit_sub1": {"at": NaN, "kat": 10, "kkfp": "aaaaaaaa"}}, "x": 1}')
chk(k9i[1] == ["bybit_sub1"] and k9n[1] == ["bybit_sub1"] and json.loads(k9i[0])["key_perm"]["bybit_sub1"]["kkfp"] == "bbbbbbbb",
    "F9b 사본 키 저장 기록 시각이 비유한(1e309·NaN) = 세대 비교 우회 안 됨(지금 기록 유지)", [k9i[1], k9n[1]])
rs9c = os.path.join(T.TMP, "restore_state9c")
os.makedirs(os.path.join(rs9c, "backups", "files_20260112"))
wj(os.path.join("backups", "files_20260112", "futures_tkx.json"), {"ts": 5, "events": [ev("a9c", T0, 3.0, acct="s1"), ev("b9c", T0, 7.0, acct="s1")]}, rs9c)
R.files_apply(R.files_plan("20260112", rs9c), proc_check=False, state_dir=rs9c, log=lambda *a: None)
k9c = (envfile.ident_read(rs9c).get("ex") or {}).get("tkx") or {}
chk(k9c.get("fut_keep") == ["s1"],
    "F9c 지도 없는 옛 사본을 계정 모른 채 같은 칸 딱지로 되돌린 칸(fold) = 지도에 줄기(fut_keep) 표식 → 다음 계정 교체 때 섞인 정산을 한 계정 보관 딱지로 안 옮김", k9c)
ib = envfile.ident_build({"tkx": {"accts": {"s1": {"uid": "UB", "seen": {"x": 1}, "fut_keep": 1}}}}, {})["ex"]["tkx"]
chk(ib.get("fut_keep") == ["s1"], "F7g 계정 지도에 정체 모르는 줄기 칸(fut_keep) 기록", ib)

T.finish()
