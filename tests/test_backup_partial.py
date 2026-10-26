#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
from datetime import datetime  # noqa: E402

json.dump({"wallets": [], "chains": {}}, open(os.path.join(T.TMP, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(T.TMP, "config.json")
sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import paths  # noqa: E402
import db as D  # noqa: E402
import health as H  # noqa: E402
import backup_complete as bc  # noqa: E402
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


ATT = os.path.join(SD, "att_frozen.json")
with open(ATT, "wb") as f:
    f.write(b'{"v":1,"synthetic":"FROZEN"}')
wj("buy_evals.json", {"synthetic": "CONTROL"})
wj(os.path.join("candles", "tkdex", "a.json"), {"k": 1})
wj(os.path.join("candles", "tkcg", "b.json"), {"k": 2})


def obs_of(st, now):
    return {"now": now, "pm2": {"tj-core": {"status": "online", "restarts": 0, "pid": 1}}, "bal_mem": {}, "prev_inc": {}, "sources": [], "backup": st}


def hcheck(st, now, cid):
    checks = H.evaluate(obs_of(st, now), H.settings({"health": {"units": ["tj-core"]}}))
    return next((x for x in checks if x["id"] == cid), None)


NOW = datetime(2026, 1, 6, 5, 0, tzinfo=L.KST).timestamp()
DAY = "20260106"


os.chmod(ATT, 0)
try:
    st = L.run_once(now=NOW)
finally:
    os.chmod(ATT, 0o600)
fs = st.get("files_state") or {}
fdir = os.path.join(SD, "backups", "files_" + DAY)
chk(st.get("last_ok") and st.get("err") is None and st.get("last_date") == DAY, "P1a 원장 백업 자체는 성공(원장 무결 · 상태 last_ok)", st)
chk(fs.get("ok") is False and "att_frozen.json" in (fs.get("failed") or {}) and "buy_evals.json" in (fs.get("copied") or [])
    and "att_frozen.json" in (fs.get("expected") or []) and st.get("files_err"),
    "P1b 원장 밖 사본 = 불완전(expected/copied/failed · files_err 문구) — 종전 files_err=None 성공", {"fs": fs, "files_err": st.get("files_err")})
fst = json.load(open(os.path.join(fdir, "files_status.json"), encoding="utf-8")) if os.path.isfile(os.path.join(fdir, "files_status.json")) else {}
chk(fst.get("ok") is False and "att_frozen.json" in (fst.get("failed") or {}), "P1c 사본 폴더 files_status.json = 불완전 기록", fst)
hf, ha = hcheck(st, NOW + 60, "backup:files"), hcheck(st, NOW + 60, "backup:age")
chk(hf is not None and hf["level"] == "warn" and "att_frozen.json" in (hf.get("detail") or "") and ha and ha["level"] == "ok",
    "P1d 상태 패널 backup:files 주황(빠진 이름) · backup:age 는 정상", {"files": hf, "age": ha and ha["level"]})
chk(L.due(NOW + 60, st) is False and L.due(NOW + L.RETRY_S + 1, st) is True, "P1e 같은 날 1시간 뒤 다시(종전 = 다음 날까지 안 함)",
    [L.due(NOW + 60, st), L.due(NOW + L.RETRY_S + 1, st)])
dbp = st["last_path"]
m0 = os.stat(dbp).st_mtime_ns
st2 = L.run_once(now=NOW + L.RETRY_S + 1)
fs2 = st2.get("files_state") or {}
chk(fs2.get("ok") is True and not fs2.get("failed") and st2.get("files_err") is None and os.path.isfile(os.path.join(fdir, "att_frozen.json"))
    and os.stat(dbp).st_mtime_ns == m0 and st2.get("last_ok") == st.get("last_ok"),
    "P1f 다시 하기 = 원장 밖 사본만(원장 백업 다시 안 뜸) → 완전으로 회복", {"fs": fs2, "same_db": os.stat(dbp).st_mtime_ns == m0})
hf2 = hcheck(st2, NOW + L.RETRY_S + 60, "backup:files")
chk(hf2 is not None and hf2["level"] == "ok" and L.due(NOW + 2 * L.RETRY_S + 2, st2) is False, "P1g 회복 뒤 backup:files 정상 · 오늘 더 안 함",
    hf2)

NOW2 = NOW + 86400
DAY2 = "20260107"
bad_dst = os.path.join(SD, "backups", "files_" + DAY2, "att_frozen.json", "x")
os.makedirs(bad_dst)
st3 = L.run_once(now=NOW2)
fs3 = st3.get("files_state") or {}
chk(st3.get("last_date") == DAY2 and st3.get("err") is None and fs3.get("ok") is False and "att_frozen.json" in (fs3.get("failed") or {}),
    "P2 사본 쓰기 실패(자리 교체 불가) = 원장 성공 · 원장 밖 사본 불완전 — ENOSPC 는 외부 재현기 copy", fs3)

CG = os.path.join(SD, "candles", "tkcg")
os.chmod(CG, 0)
try:
    out4 = L.backup_files("20260108", SD)
finally:
    os.chmod(CG, 0o700)
st4 = L.files_state_of(out4, "20260108")
chk(st4["ok"] is False and any("tkcg" in k for k in st4["failed"]) and os.path.isfile(os.path.join(SD, "backups", "files_20260108", "candles", "tkdex", "a.json")),
    "P3 봉 출처 폴더 열거 실패 = 실패로 셈(다른 출처는 사본) — 종전 조용히 건너뜀", st4)

man4 = O.build(now=NOW2 + 7200, log=lambda *a: None)
cmp4 = (man4.get("files") or {}).get("complete") or {}
inc4 = (man4.get("files") or {}).get("includes") or []
chk("files_20260108" in inc4 and (cmp4.get("files_20260108") or {}).get("ok") is False and "files_20260106" in inc4
    and (cmp4.get("files_20260106") or {}).get("ok") is True,
    "P4a manifest 에 사본 완전성 · 가장 새 사본이 불완전 = 마지막 완전 사본도 같이 묶음", {"inc": inc4, "complete": cmp4})
chk("prefs_20260106.json" in inc4, "P4c 마지막 완전 사본 날의 오너 입력 덤프(prefs)도 같이", inc4)
S.verify(man4, S.load_key(O.AUTH_KEY))
bad4 = json.loads(json.dumps(man4))
bad4["files"]["complete"]["files_20260108"]["ok"] = True
try:
    S.verify(bad4, S.load_key(O.AUTH_KEY))
    sealed = False
except S.AuthError:
    sealed = True
chk(sealed, "P4b 완전성 칸 = 봉인 안(HMAC — 바꾸면 인증 실패)", None)

rs5 = os.path.join(T.TMP, "restore_state5")
os.makedirs(os.path.join(rs5, "backups"))
O.unpack_files(O.OUT_DIR, man4["stamp"], S.load_key(O.AUTH_KEY), dst_dir=os.path.join(rs5, "backups"), log=lambda *a: None)
chk(os.path.isfile(os.path.join(rs5, "backups", "files_20260106", "candles", "tkdex", "a.json"))
    and os.path.isfile(os.path.join(rs5, "backups", "files_20260108", "candles", "tkdex", "a.json")),
    "P4d 두 사본이 나눠 쓰는 봉 하드 링크 = 풀면 두 날짜 모두 파일(종전 = 뒤 사본은 링크 항목이라 건너뜀)", None)
fp5 = R.files_plan("20260108", rs5)
w5 = " | ".join(fp5.get("warn") or [])
chk("tkcg" in w5 and "20260106" in w5, "P5a 불완전 사본(풀린 묶음) 되돌리기 계획 = 빠진 이름 경고 + 마지막 완전 사본 날짜", fp5.get("warn"))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc5 = R.main(["files", DAY2])
chk(rc5 == 0 and "att_frozen.json" in buf.getvalue() and "불완전" in buf.getvalue(), "P5b files 미리보기 출력에 불완전 경고(빠진 이름)",
    buf.getvalue()[-400:])
buf6 = io.StringIO()
with contextlib.redirect_stdout(buf6):
    O.main(["open", O.OUT_DIR, man4["stamp"], "--auth-key", O.AUTH_KEY])
chk("불완전" in buf6.getvalue() and "files_20260108" in buf6.getvalue() and "ledger_restore.py files 20260108" in buf6.getvalue(), "P5c 서버 밖 묶음 열기 출력에 불완전 사본 경고", buf6.getvalue()[-500:])
chk("ledger_restore.py files 20260106" not in buf6.getvalue(),
    "P5c2 같이 온 마지막 완전 사본을 통째 적용하라는 안내 없음(최신 오너 입력을 옛 값으로 덮지 않게)", buf6.getvalue()[-500:])

os.makedirs(os.path.join(rs5, "backups", "files_20251201"))
with open(os.path.join(rs5, "backups", "files_20251201", "daily_px.json"), "w", encoding="utf-8") as f:
    json.dump({"d": 1}, f)
fp5d = R.files_plan("20251201", rs5)
chk(not fp5d.get("warn") and [r for _s, r in fp5d["items"]] == ["daily_px.json"], "P5d 옛 형식 사본(완전성 기록 없음) = 경고 없이 종전 계획", fp5d)

bdir = os.path.join(SD, "backups")
for i in range(L.KEEP_FILES + 2):
    d9 = os.path.join(bdir, "files_2026%04d" % (300 + i))
    os.makedirs(d9, exist_ok=True)
    with open(os.path.join(d9, "files_status.json"), "w", encoding="utf-8") as f:
        json.dump({"v": 1, "ok": False, "failed": {"x.json": "err"}}, f)
L._rotate_dirs(L._FD_RX, L.KEEP_FILES)
left = sorted(n for n in os.listdir(bdir) if L._FD_RX.match(n))
chk("files_20260106" in left and len(left) == L.KEEP_FILES + 1, "P6 회전 = 새 사본 30개 + 마지막 완전 사본(불완전만 30개여도 지우지 않음)", left[:3])

for i in range(L.KEEP_JSON + 2):
    with open(os.path.join(bdir, "prefs_2026%04d.json" % (300 + i)), "w", encoding="utf-8") as f:
        json.dump({"ts": 1}, f)
L._rotate(L._JS_RX, L.KEEP_JSON)
chk(os.path.isfile(os.path.join(bdir, "prefs_20260106.json")), "P6b prefs 회전 = 마지막 완전 사본 날의 덤프는 남김", None)

d7 = os.path.join(bdir, "files_20260120")
os.makedirs(os.path.join(d7, "files_status.json", "x"))
out7 = L.backup_files("20260120", SD)
left7 = os.listdir(d7)
shutil.rmtree(os.path.join(d7, "files_status.json"))
chk(list(out7) == ["files_status.json"] and str(out7["files_status.json"]).startswith("err") and left7 == ["files_status.json"],
    "P7a 완전성 표식을 못 쓰는 폴더 = 사본 안 바꿈 · 실패로 셈(기록 없는 폴더가 옛 완전 사본으로 보이지 않게)", {"out": out7, "left": left7})
pend = bc.mark_pending(d7, "20260120") and bc.files_dir_state(d7)
chk(isinstance(pend, dict) and pend.get("ok") is False and bc.last_complete_dir(bdir) != "files_20260120",
    "P7b 작성 중 표식 = 불완전(끝 기록을 못 써도 완전으로 안 보임)", pend)
fp7 = R.files_plan("20260120", SD)
chk(not fp7["items"] and fp7.get("warn") and "20260106" in " | ".join(fp7["warn"]), "P7c 작성 중 표식만 남은 사본 = 계획 거부 대신 불완전 경고·마지막 완전 사본 안내", fp7)

T.finish()
