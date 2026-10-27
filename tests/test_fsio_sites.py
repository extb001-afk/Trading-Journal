#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _gate as _x  # noqa: E402
import ast  # noqa: E402
import errno  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

import config, paths, statefile  # noqa: E402
import fsio  # noqa: E402

S = paths.STATE_DIR
D = os.path.join(T.TMP, "sites")
os.makedirs(D, exist_ok=True)
OBJ = {"한글": "값", "f": [1e-7, 2.5, 10 ** 30, -0.0], "s": "a\"b\\c ", "n": None, "b": [True, False], "d": {"z": 1, "a": {}}}
WEIRD = dict(OBJ, nan=float("nan"))


def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def pair(old_fn, new_fn, obj, name, umask=0o022):
    a, b = os.path.join(D, name + ".old"), os.path.join(D, name + ".new")
    um = os.umask(umask)
    try:
        old_fn(a, obj)
        new_fn(b, obj)
    finally:
        os.umask(um)
    ra, rb = (open(a, "rb").read(), mode_of(a)), (open(b, "rb").read(), mode_of(b))
    return ra == rb, (ra[1], rb[1], len(ra[0]), len(rb[0]))


def old_common(path, obj):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def old_settings_text(path, text, mode=0o600):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp_set_")
    os.fchmod(fd, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def old_nft(path, obj):
    tmp = os.path.join(os.path.dirname(path), ".nft_%s_%s.tmp" % (os.getpid(), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def old_umask_json(path, obj, **kw):
    with open(path + ".otmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, **kw)
    os.replace(path + ".otmp", path)


def old_pricing(path, d):
    s9 = json.dumps(d, separators=(",", ":"))
    with open(path + ".otmp", "w", encoding="utf-8") as f:
        f.write(s9)
    os.replace(path + ".otmp", path)


import settings_store as ss  # noqa: E402
import nft  # noqa: E402
import other_assets  # noqa: E402
import review_progress  # noqa: E402
import rabby  # noqa: E402
import pricing  # noqa: E402
import flow_trace  # noqa: E402
import xchain_match  # noqa: E402

for um in (0o022, 0o077):
    ok9, det9 = pair(old_common, statefile.atomic_write_json, WEIRD, "common%o" % um, um)
    T.chk(ok9, "S1 statefile.atomic_write_json = 종전 바이트·권한(NaN 허용 · umask %03o)" % um, det9)
    ok9, det9 = pair(old_nft, nft.atomic_write, OBJ, "nft%o" % um, um)
    ok8, det8 = pair(old_nft, other_assets.atomic_write, OBJ, "oa%o" % um, um)
    T.chk(ok9 and ok8, "S2 nft·other_assets.atomic_write = 종전 바이트·권한(umask %03o)" % um, (det9, det8))
    ok9, det9 = pair(lambda p, o: old_common(p, o), review_progress._write, OBJ, "rp%o" % um, um)
    T.chk(ok9, "S3 review_progress._write = 종전 바이트·권한(umask %03o)" % um, det9)
    ok9, det9 = pair(lambda p, o: old_umask_json(p, o, ensure_ascii=False, separators=(",", ":")), rabby._write, OBJ, "rabby%o" % um, um)
    T.chk(ok9, "S4 rabby._write = 종전 바이트·권한(umask 기본 · %03o)" % um, det9)
    txt = json.dumps(OBJ, ensure_ascii=False, indent=2) + "\n"
    ok9, det9 = pair(lambda p, o: old_settings_text(p, o, 0o600), lambda p, o: ss._atomic_write_text(p, o, 0o600), txt, "set%o" % um, um)
    ok8, det8 = pair(lambda p, o: old_settings_text(p, o, 0o640), lambda p, o: ss._atomic_write_text(p, o, 0o640), txt, "set640%o" % um, um)
    T.chk(ok9 and ok8, "S5 settings_store._atomic_write_text = 종전 바이트·권한 그대로(mode 인자 · umask %03o)" % um, (det9, det8))
for nm, fn in (("nft", nft.atomic_write), ("oa", other_assets.atomic_write)):
    p9 = os.path.join(D, nm + "_nan.json")
    fn(p9, {"v": 1})
    try:
        fn(p9, WEIRD)
        r9 = "written"
    except ValueError:
        r9 = "ValueError"
    T.chk(r9 == "ValueError" and json.load(open(p9)) == {"v": 1} and not [n for n in os.listdir(D) if n.startswith(".tmp_")],
          "S6 %s: NaN = ValueError(종전) · 대상 그대로 · 임시 없음" % nm, r9)
real_fsync = os.fsync


def fsync_dir_fails(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        raise OSError(errno.EIO, "시험: 폴더 fsync 실패")
    return real_fsync(fd)


os.fsync = fsync_dir_fails
res7 = {}
try:
    for nm, fn in (("common", statefile.atomic_write_json), ("nft", nft.atomic_write), ("oa", other_assets.atomic_write),
                   ("settings", lambda p, o: ss._atomic_write_text(p, json.dumps(o)))):
        try:
            fn(os.path.join(D, nm + "_dsync.json"), {"k": nm})
            res7[nm] = "삼킴"
        except OSError:
            res7[nm] = "올림"
finally:
    os.fsync = real_fsync
T.chk(res7 == {"common": "올림", "nft": "삼킴", "oa": "삼킴", "settings": "올림"}
      and all(json.load(open(os.path.join(D, n + "_dsync.json")))["k"] == n for n in res7),
      "S7 교체 뒤 폴더 fsync 실패 = common·settings_store 올림 · nft·other_assets 삼킴(종전 계약) · 대상은 새 내용", res7)
cfg9 = {"wallets": [{"type": "evm", "chain": "eth", "address": "0x" + "ab" * 20, "label": "지갑"}], "x": "한글"}
os.chmod(paths.CONFIG_PATH, 0o644)
ref9 = os.path.join(D, "config_ref.json")
open(ref9, "w").close()
old_settings_text(ref9, json.dumps(cfg9, ensure_ascii=False, indent=2) + "\n", (0o644 & 0o700) or 0o600)
with ss.LOCK:
    ss.write_config_raw(cfg9)
T.chk(open(paths.CONFIG_PATH, "rb").read() == open(ref9, "rb").read() and mode_of(paths.CONFIG_PATH) == 0o600,
      "S8 write_config_raw = 들여쓰기 2·끝 줄바꿈·권한(주인 비트만) 종전 그대로")
_x.write_cfg()
px = pricing.PxCache(os.path.join(D, "px.json"))
px.d["candle"]["BTC:60000"] = 123.45
px.d["fx"]["60000"] = 1385.5
px.d["note"] = "한글"
px._save()
old_pricing(os.path.join(D, "px_old.json"), px.d)
T.chk(open(os.path.join(D, "px.json"), "rb").read() == open(os.path.join(D, "px_old.json"), "rb").read() and px._dirty == 0,
      "S9 PxCache._save = 종전 바이트(ensure_ascii 켬 — \\uXXXX)")
cache9 = {"v": 1, "dest": {"a": {"amt": Decimal("1.50"), "t": "한"}}}
flow_trace.save_cache(D, cache9)
xchain_match._save(D, cache9)
old_umask_json(os.path.join(D, "fc_old.json"), cache9, ensure_ascii=False, separators=(",", ":"), default=str)
ref9 = open(os.path.join(D, "fc_old.json"), "rb").read()
T.chk(open(os.path.join(D, flow_trace.CACHE_NAME), "rb").read() == ref9 and open(os.path.join(D, xchain_match.CACHE_NAME), "rb").read() == ref9
      and mode_of(os.path.join(D, flow_trace.CACHE_NAME)) == mode_of(os.path.join(D, "fc_old.json")),
      "S10 flow_trace·xchain_match 캐시 = 종전 바이트(default=str)·권한(umask 기본)")
try:
    flow_trace.save_cache(os.path.join(D, "없는폴더"), cache9)
    r9 = "made"
except FileNotFoundError:
    r9 = "FileNotFoundError"
T.chk(r9 == "FileNotFoundError", "S11 캐시 쓰기는 폴더를 만들지 않음(종전과 같음)", r9)
import calcguard  # noqa: E402
calcguard.swallowed("test:fsio_sites", ValueError("한글 사유"), expected=True)
calcguard.flush(now=time.time())
raw9 = open(calcguard.path_of(), encoding="utf-8").read()
T.chk(raw9 == json.dumps(json.loads(raw9), ensure_ascii=False) and "한글 사유" in raw9 and mode_of(calcguard.path_of()) == 0o600
      and not [n for n in os.listdir(S) if ".tmp" in n], "S12 calcguard 저장 = 종전 직렬화(기본 구분자·한글 그대로)·0600 · 임시 이름 규칙(.tmp<pid> 아님)")
import ledger_backup  # noqa: E402
open(os.path.join(S, "settings.json"), "w").write('{"x": "한글"}')
open(os.path.join(S, "reviews_llm.json"), "w").write("[1]")
r9 = ledger_backup.backup_files("20260101", S, paths.CONFIG_PATH)
fd9 = os.path.join(S, "backups", "files_20260101")
T.chk(open(os.path.join(fd9, "settings.json"), "rb").read() == open(os.path.join(S, "settings.json"), "rb").read()
      and open(os.path.join(fd9, "config_subset.json"), "rb").read()
      == json.dumps({"wallets": config.load_config()["wallets"]}, ensure_ascii=False, indent=1).encode()
      and all(mode_of(os.path.join(fd9, n)) == 0o600 for n in os.listdir(fd9)) and not [n for n in os.listdir(fd9) if "tmp" in n],
      "S13 정기 백업 원장 밖 사본 = 원본 바이트·0600 · 임시 없음", r9)

SRC = T.SRC


def calls_in(tree, owner=None):
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner] if owner else [tree]
    out = []
    for nd in nodes:
        for n in ast.walk(nd):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                out.append(n.func.value.id + "." + n.func.attr)
    return out


hct = ast.parse(open(os.path.join(SRC, "histcurve.py"), encoding="utf-8").read())
hc9 = calls_in(hct, "DayClose")
T.chk(hc9.count("statefile.atomic_write_json") >= 2 and not [c for c in calls_in(hct) if c.startswith("fsio.")],
      "P1 histcurve 그날 마감가 쓰기 = statefile.atomic_write_json(부를 때 찾음 · buildproc 이 바꿔 끼우는 이름) · fsio 직접 호출 없음", hc9.count("statefile.atomic_write_json"))
ct9 = ast.parse(open(os.path.join(SRC, "statefile.py"), encoding="utf-8").read())
fns = {n.name: n for n in ct9.body if isinstance(n, ast.FunctionDef)}
wjc = [n.func.id for n in ast.walk(fns["write_json_if_changed"]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
awj = [n.func.value.id + "." + n.func.attr for n in ast.walk(fns["atomic_write_json"]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
T.chk("atomic_write_json" in wjc and awj == ["fsio.atomic_write_json"],
      "P2 statefile.write_json_if_changed → 모듈 전역 atomic_write_json(바꿔 끼움이 먹음) · 래퍼 → fsio.atomic_write_json(부를 때 찾음)", (wjc, awj))
T.chk(sum(c == "statefile.atomic_write_json" for c in calls_in(ast.parse(open(os.path.join(SRC, "histmark.py"), encoding="utf-8").read()))) == 2,
      "P2b histmark 표식 쓰기 2곳 = statefile.atomic_write_json(부를 때 찾음 · 바꿔 끼움이 먹음 — 4-2 전 common 안 맨 이름과 같음)")
import histcurve  # noqa: E402
import buildproc  # noqa: E402
real_aw = statefile.atomic_write_json
dc = histcurve.DAYCLOSE
hs = buildproc._hist_begin()
try:
    r1 = statefile.atomic_write_json(dc.path, {"x": 1})
    statefile.write_json_if_changed(dc.path, {"y": 2})
    statefile.atomic_write_json(os.path.join(D, "other.json"), {"z": 3})
    p3 = not os.path.exists(dc.path) and r1 is None and json.load(open(os.path.join(D, "other.json"))) == {"z": 3}
finally:
    statefile.atomic_write_json = real_aw
    dc.__dict__.pop("note_change", None)
T.chk(hs is not None and p3, "P3 buildproc._hist_begin = 그날 마감가 파일 쓰기만 막음(write_json_if_changed 경유 포함) · 다른 파일은 씀")
pxt = ast.parse(open(os.path.join(SRC, "pricing.py"), encoding="utf-8").read())
bpt = ast.parse(open(os.path.join(SRC, "buildproc.py"), encoding="utf-8").read())
T.chk("self._save" in calls_in(pxt, "PxCache"), "P4 PxCache 저장 = self._save(포크 자식 px._save = 무동작이 먹음)")
T.chk("calcguard.flush_as" in calls_in(bpt) and callable(getattr(calcguard, "flush_as", None)), "P5 calcguard.flush_as(\"build\") 그대로")

import core  # noqa: E402
import ops_requests as O  # noqa: E402
c = core.Core(config.load_config())
recs = [{"kind": "evm_tx", "chain": "base", "hash": "0x" + h * 32} for h in ("ab", "cd", "ef")]
open(c.POISON_PATH, "w").write("".join(json.dumps({"ts": 1, "err": "x", "rec": r}) + "\n" for r in recs))
ids = [c.poison_id({"rec": r}) for r in recs]
seen = []
c._consume_record = lambda rec: seen.append(rec["hash"][:4])
real_rcj, real_claim = statefile.read_control_json, fsio.claim
O._poison_req_write(False, [ids[0]], "시험")
fired = []


def rcj_then_writer(path, default=None):
    v = real_rcj(path, default)
    if path == c.POISON_REQ_PATH and not fired:
        fired.append(1)
        O._poison_req_write(False, [ids[1]], "시험2")
    return v


statefile.read_control_json = rcj_then_writer
try:
    c.poison_replay_pass()
finally:
    statefile.read_control_json = real_rcj
T.chk(sorted(seen) == ["0xab", "0xcd"] and not os.path.exists(c.POISON_REQ_PATH) and not [n for n in os.listdir(S) if ".claim." in n],
      "R1 격리 재처리: 읽은 뒤 작성자가 합쳐 쓴 요청도 같은 판에 처리(종전 = 지워져 유실) · 차지 파일 안 남음", seen)


def claim_then_writer(path):
    got = real_claim(path)
    O._poison_req_write(False, [ids[2]], "시험3")
    return got


O._poison_req_write(False, [ids[0]], "시험")
fsio.claim = claim_then_writer
try:
    c.poison_replay_pass()
finally:
    fsio.claim = real_claim
left9 = json.load(open(c.POISON_REQ_PATH)) if os.path.exists(c.POISON_REQ_PATH) else None
T.chk(isinstance(left9, dict) and left9.get("ids") == [ids[2]], "R2 차지 뒤 온 새 요청 = 새 파일로 남음(다음 판 처리)", left9)
seen.clear()
c.poison_replay_pass()
T.chk(seen == ["0xef"] and not os.path.exists(c.POISON_REQ_PATH), "R3 다음 판 = 남은 요청 처리", seen)
def dec_write(aid, seen9):
    with fsio.locked(c.DEC_REQ_PATH):
        cur9 = O._safe_read(c.DEC_REQ_PATH, None)
        it9 = cur9.get("items") if isinstance(cur9, dict) and isinstance(cur9.get("items"), dict) else {}
        it9[str(aid)] = {"stored": 18, "seen": seen9}
        statefile.atomic_write_json(c.DEC_REQ_PATH, {"items": it9, "ts": 1})


def rj(p, d=None):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return d


dec_write(11, 6)
fired.clear()


def rcj_then_dec(path, default=None):
    v = real_rcj(path, default)
    if path == c.DEC_REQ_PATH and not fired:
        fired.append(1)
        dec_write(22, 8)
    return v


statefile.read_control_json = rcj_then_dec
try:
    c.decimals_resolve_pass()
finally:
    statefile.read_control_json = real_rcj
res9 = rj(c.DEC_RES_PATH, {}) or {}
T.chk({"11", "22"} <= set(res9) and not os.path.exists(c.DEC_REQ_PATH), "R4 자리수 요청: 읽은 뒤 합쳐 쓴 요청도 같은 판에 처리(종전 = 지워져 유실)", sorted(res9))


def claim_then_dec(path):
    got = real_claim(path)
    dec_write(33, 9)
    return got


dec_write(11, 6)
fsio.claim = claim_then_dec
try:
    c.decimals_resolve_pass()
finally:
    fsio.claim = real_claim
left9 = rj(c.DEC_REQ_PATH)
T.chk(isinstance(left9, dict) and set(left9.get("items") or {}) == {"33"}, "R5 차지 뒤 온 자리수 요청 = 새 파일로 남음", left9)
c.decimals_resolve_pass()
T.chk("33" in (rj(c.DEC_RES_PATH, {}) or {}) and not os.path.exists(c.DEC_REQ_PATH), "R6 다음 판 = 남은 자리수 요청 처리")

import core_ext  # noqa: E402
import health  # noqa: E402
IP = os.path.join(S, "intentional_restart.json")
core_ext.ExtMixin._ext_mark_intent()
d9 = json.load(open(IP))
T.chk(list(d9) == ["unit", "ts", "reason"] and open(IP, "rb").read() == json.dumps(d9, ensure_ascii=False, separators=(",", ":")).encode(),
      "I1 core 재구축 표식(다른 표식 없음) = 종전 단일 형식·바이트", d9)
dl = os.path.join(T.ROOT, "tools", "deploy_lib.sh")
if os.path.isfile(dl):
    t9 = open(dl, encoding="utf-8").read().split("mark_intentional_restart() {", 1)[1]
    py9 = t9.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    r9 = subprocess.run([sys.executable, "-", IP, "배포", "1", "1800", "tj-web", "tj-exf"], input=py9, capture_output=True, text=True)
    T.chk(r9.returncode == 0, "I2 배포 도구(deploy_lib mark_intentional_restart — 손대지 않음) 표식 씀", r9.stderr[-300:])
else:
    print("(공개 배치 — tools/deploy_lib.sh 없음: I2 는 같은 형식을 직접 씀)")
    d9 = json.load(open(IP))
    d9["entries"] = [{"unit": "tj-web", "ts": int(time.time()), "n": 1, "win": 1800, "by": "배포"}]
    statefile.atomic_write_json(IP, d9)
wrw_p = os.path.join(T.ROOT, "tools", "wallet_reload_watch.py")
if os.path.isfile(wrw_p):
    sys.path.insert(0, os.path.join(T.ROOT, "tools"))
    import wallet_reload_watch as wrw  # noqa: E402
    wrw.INTENT_PATH = IP
    wrw.mark_intentional(["tj-evm"], by="시험")
core_ext.ExtMixin._ext_mark_intent()
d9 = json.load(open(IP))
units9 = sorted(e["unit"] for e in d9.get("entries") or [])
T.chk(d9.get("unit") == "tj-core" and d9.get("reason") == "ext_rebuild" and "tj-web" in units9 and ("tj-evm" in units9 or not os.path.isfile(wrw_p)),
      "I3 core 재구축 표식 = 배포·tj-reload 표식(entries)을 지우지 않고 합침(의도된 변경 — 종전 통째 덮어씀)", d9)
ents9 = health._intent_entries(d9)
done9 = {e[3] for e in ents9 if e[0] == "tj-web"}
now9 = time.time()
d9["entries"].append({"unit": "tj-sol", "ts": int(now9), "n": 1})
statefile.atomic_write_json(IP, d9)
health._intent_prune(IP, done9, set(), now9)
d10 = json.load(open(IP))
u10 = sorted(e["unit"] for e in d10["entries"])
T.chk("tj-web" not in u10 and "tj-sol" in u10 and "tj-core" in u10 and "unit" not in d10, "I4 헬스 정리 = 다 쓴 표식만 뺌 · 그 사이 더한 표식은 남김(단일 형식은 entries 로)", d10)
mt9 = os.stat(IP).st_mtime_ns
health._intent_prune(IP, {"없는:키"}, set(), now9)
T.chk(os.stat(IP).st_mtime_ns == mt9, "I5 뺄 것 없음 = 다시 쓰지 않음(내용 안 바뀐 재쓰기 없음)")
health._intent_prune(IP, {e[3] for e in health._intent_entries(d10)}, set(), now9)
T.chk(not os.path.exists(IP) and os.path.exists(IP + ".lock"), "I6 모두 다 씀 = 파일 삭제(잠금 파일은 남김)")

import login_auth  # noqa: E402
if os.geteuid() != 0:
    os.chmod(S, 0o500)
    try:
        a1 = login_auth._setup_code_locked(True)
    finally:
        os.chmod(S, 0o700)
    T.chk(a1 == "" and not os.path.exists(login_auth.SETUP_CODE_PATH), "A1 state 에 새 파일을 못 만듦 = 설정 코드 '' (종전과 같음 · 예외 안 냄)", a1)
a2 = login_auth._setup_code_locked(True)
T.chk(len(a2) == 16 and login_auth._setup_code_locked(False) == a2 and mode_of(login_auth.SETUP_CODE_PATH) == 0o600,
      "A2 만들면 16자 코드 · 다시 읽어 같음 · 0600", a2)

T.chk(isinstance(ss.LOCK, fsio.FileRLock) and ss.LOCK.path() == os.path.join(S, "config.json.lock") == ss.config_lock_path()
      and ss.config_lock_for(paths.CONFIG_PATH) == ss.config_lock_path(), "L1 settings_store.LOCK = state/config.json.lock(도구 규칙과 같은 파일)")
with ss.LOCK:
    with ss.LOCK:
        ss.update_settings(t_fsio=1)
T.chk(ss.read_settings().get("t_fsio") == 1 and ss.LOCK._depth == 0, "L2 재진입(설정 저장소 안 중첩 호출) 그대로")
flag = os.path.join(D, "child_holds")
child = subprocess.Popen([sys.executable, "-c",
                          "import sys, time; sys.path.insert(0, sys.argv[1]); import fsio\n"
                          "with fsio.locked(sys.argv[2], lock_file=sys.argv[3]):\n"
                          "    open(sys.argv[4], 'w').close(); time.sleep(1.0)",
                          SRC, paths.CONFIG_PATH, ss.config_lock_for(paths.CONFIG_PATH), flag])
t_end = time.time() + 10
while not os.path.exists(flag) and time.time() < t_end:
    time.sleep(0.01)
t0 = time.time()
with ss.LOCK:
    waited = time.time() - t0
child.wait(10)
T.chk(waited >= 0.5 and child.returncode == 0, "L3 웹 설정 저장소 잠금 = 도구(다른 프로세스 · fsio.locked + config_lock_for)가 쥔 동안 기다림", round(waited, 2))
T.chk(ss.config_mode(os.path.join(D, "없음.json")) == 0o600 and (os.chmod(paths.CONFIG_PATH, 0o640) or ss.config_mode() == 0o600),
      "L4 config 권한 규칙 = 주인 비트만(없으면 0600)")
real_cp = paths.CONFIG_PATH
moved = os.path.join(D, "conf", "config.json")
os.makedirs(os.path.dirname(moved), exist_ok=True)
open(moved, "w").write("{}")
os.symlink(moved, os.path.join(D, "conf_link.json"))
paths.CONFIG_PATH = moved
try:
    l5 = (ss.config_lock_for(moved), ss.config_lock_for(os.path.join(D, "conf_link.json")), ss.config_lock_path(),
          ss.config_lock_for(os.path.join(D, "other", "config.json")))
finally:
    paths.CONFIG_PATH = real_cp
T.chk(l5[0] == l5[1] == l5[2] == os.path.join(S, "config.json.lock") and l5[3] == os.path.join(D, "other", "state", "config.json.lock"),
      "L5 TJ_CONFIG 로 옮긴 설치 = 도구·웹 같은 잠금 파일(링크 경로도) · 다른 사본 = 그 폴더 state/", l5)
T.finish()
