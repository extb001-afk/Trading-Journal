#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
REF = len(sys.argv) > 4 and sys.argv[1] == "--ref"
import _harness as T  # noqa: E402
import datetime as _dt  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

_MODE = os.environ.get("TJ_TEST_FORK", "")
if not REF and not (sys.platform.startswith("linux") or _MODE == "force"):
    T.chk(True, "F0 리눅스 아님(%s) — 포크 빌드 시험 건너뜀(맥 시스템 sqlite 는 fork 뒤 죽음 · 공개 CI ubuntu 가 돌림 · 강제 = TJ_TEST_FORK=force)"
          % sys.platform)
    T.finish()
NOW = int(sys.argv[3]) if REF else int(time.time())
if REF:
    os.environ["TJ_BASE"] = sys.argv[2]
time.time = lambda: float(NOW)
time.time_ns = lambda: int(NOW * 1e9)
_RDT = _dt.datetime


class _FrozenDT(_RDT):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(NOW, tz)

    @classmethod
    def utcnow(cls):
        return cls.utcfromtimestamp(NOW)

    @classmethod
    def today(cls):
        return cls.fromtimestamp(NOW)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return cls.fromtimestamp(NOW)


_dt.datetime, _dt.date = _FrozenDT, _FrozenDate
os.environ["TJ_BUILD_PROC"] = "off" if REF else "fork"

import _ingest  # noqa: E402,F401
from _ingest import W, SOLW, Reader  # noqa: E402

import _golden_fp as FP  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

BASE = sys.argv[2] if REF else T.TMP
if not REF:
    json.dump({"chains": {"eth": {"blockscout": "https://bs.invalid", "etherscan_chainid": 1, "conf_depth": 12, "blocks_per_day": 7200,
                                  "rpcs": ["https://rpc.invalid"]}},
               "wallets": [{"type": "evm", "chain": "eth", "address": W, "label": "w"},
                           {"type": "sol", "chain": "sol", "address": SOLW, "label": "s"}],
               "native_symbol": {"eth": "ETH"}, "backfill_months": 5, "sol": {"rpcs": ["https://solrpc.invalid"]}},
              open(os.path.join(BASE, "config.json"), "w"))
os.environ["TJ_CONFIG"] = os.path.join(BASE, "config.json")
import buildproc  # noqa: E402
import calcguard  # noqa: E402
import config, paths, statefile  # noqa: E402
import core  # noqa: E402
import db as dbm  # noqa: E402
import histcurve  # noqa: E402
import web  # noqa: E402

chk = T.chk
DAY = 86400
T0 = NOW - 25 * DAY
X = "0x" + "b7" * 20
PX = {"ETH": 2000.0, "SOL": 100.0}
DC = histcurve.DAYCLOSE
PARENT = os.getpid()

for _m in ("_sale_worker", "_xchain_worker", "_lp_worker", "_origin_worker", "_flow_worker", "_rabby_worker"):
    if hasattr(web.StateBuilder, _m):
        setattr(web.StateBuilder, _m, lambda self: None)


def fake_lookup(spec, iso, now=None, w=0.0, ask=True, old=False):
    for s9, p9 in PX.items():
        if s9 in str(spec).upper():
            return p9, "ok"
    return None, "pending"


fake_lookup._tj_test_mock = True
DC.lookup = fake_lookup
json.dump({"usd": dict(PX), "usd_ts": {k: NOW for k in PX}, "rate": 1400.0, "updated": NOW, "dex_usd": {}, "dex_ts": {}, "dex_res": {}, "dex_res_ts": {},
           "fx_basis": 1400.0, "ex_usd": {}, "ex_ts": {}}, open(paths.state("spot.json"), "w"))
web.pricing.PxCache.candle_usd = lambda self, sym, ms: PX.get(str(sym).upper())
web.pricing._gj = lambda url, timeout=10.0: None
web.pricing.PxCache.fx_at = lambda self, ms: 1400.0
open(os.path.join(paths.STATE_DIR, "backfill_done"), "w").write("1")

if not REF:
    c = core.Core(config.load_config())
    c._drain_stream("evm", Reader([{"v": 1, "kind": "evm_tx", "chain": "eth", "txhash": "0x" + "%064x" % 1, "wallets": [W], "ts": 1, "snapshot": {
        "tx": {"hash": "0x" + "%064x" % 1, "from": X, "to": W, "value": str(10 ** 18), "fee": {"value": "0"}, "status": "ok", "raw_input": "0x",
               "timestamp": T0, "block_number": 1500, "block_hash": "0x" + "d" * 64}, "token_transfers": [], "internal": []}}]), 0, 0)
    c._drain_stream("sol", Reader([{"v": 1, "kind": "sol_tx", "chain": "sol", "txhash": "solbase1", "slot": 800, "ts": T0, "fee_lamports": 0,
                                    "fee_payer_mine": False, "fee_payer": None, "wallets": [SOLW], "counterparties": [], "has_program": False, "err": False,
                                    "deltas": [{"asset": "native", "symbol": "SOL", "decimals": 9, "delta": str(10 * 10 ** 9), "owner": SOLW}]}]), 0, 0)
    c.conn.close()


def san(o, depth=0):
    if depth > 40:
        return "<deep>"
    if o is None or isinstance(o, (bool, int, str)):
        return o
    if isinstance(o, float):
        return "NaN" if math.isnan(o) else ("Inf" if o > 0 else "-Inf") if math.isinf(o) else o
    if isinstance(o, dict):
        return {str(k): san(v, depth + 1) for k, v in sorted(o.items(), key=lambda kv: str(kv[0]))}
    if isinstance(o, (list, tuple)):
        return [san(v, depth + 1) for v in o]
    if isinstance(o, (set, frozenset)):
        return sorted((san(v, depth + 1) for v in o), key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return "<%s>" % type(o).__name__


def diff(a, b, path="$", out=None):
    out = [] if out is None else out
    if len(out) >= 12:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s.%s: %s" % (path, k, "포크에만" if k not in a else "웹 안에만"))
            else:
                diff(a[k], b[k], "%s.%s" % (path, k), out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append("%s: 웹 안 %s · 포크 %s" % (path, json.dumps(a, ensure_ascii=False)[:80], json.dumps(b, ensure_ascii=False)[:80]))
    return out


def ledger_stamp():
    if not hasattr(dbm, "daily_inval_state"):
        return None
    r = dbm.open_db(paths.DB_PATH, readonly=True)
    try:
        st = dbm.daily_inval_state(r)
    finally:
        r.close()
    return f"{st[0]}:{'' if st[1] is None else st[1]}" if (st[0] or st[1] is not None) else None


def builder():
    try:
        os.remove(paths.state("daily_cache.json"))
    except FileNotFoundError:
        pass
    b = web.StateBuilder()
    b.skip_gen_check = True
    return b


def read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


FP_BASE = tuple(sorted({paths.BASE_DIR.rstrip("/"), os.path.realpath(paths.BASE_DIR)}, key=len, reverse=True))


SKIP_HIDDEN = {"lock", "build_lock", "snaps", "spot", "px", "_pxq", "_rtx", "cfg", "_cfg_hot_sig", "cache", "cache_at",
               "_build_hist", "_build_ex", "_ph_t", "_ph_hist", "_ph_last", "_ph_cur", "_ph_gen0", "_last_out", "_last_out_at",
               "_bp_threads", "_bp_shm", "_g4_probe", "_daily_series",
               "_built_sig"}


def extras(b) -> dict:
    raw = {k: v for k, v in b.__dict__.items() if k not in SKIP_HIDDEN and not callable(v)}
    hid = san(raw)
    enc = FP.Encoder(builder_cls=web.StateBuilder, base=FP_BASE)
    p_hid = {k: enc.fingerprint("hidden." + k, v, FP.norm_for("hidden." + k)) for k, v in raw.items()}
    api, p_api = {}, {}

    def call(name, fn):
        try:
            r = fn()
            api[name] = san(r)
            p_api[name] = enc.fingerprint("api." + name, r)
        except Exception as e:   # noqa: BLE001
            api[name] = p_api[name] = {"_error": type(e).__name__}
    idx = b.__dict__.get("_day_idx") or {}
    days = sorted((idx.get("ix") or {}).keys())
    if days:
        call("day_events", lambda: b.day_events(days[0], days[-1]))
    yms = sorted({str(r.get("sold") or "")[:7] for r in (idx.get("tax") or []) if r.get("sold")})
    call("tax_rows", lambda: {ym: b.tax_rows(ym, "") for ym in yms})
    to9 = time.strftime("%Y-%m-%d", time.gmtime(NOW + 9 * 3600))
    fr9 = time.strftime("%Y-%m-%d", time.gmtime(NOW + 9 * 3600 - 40 * DAY))
    call("att_detail", lambda: b.att_detail(fr9, to9))
    return {"hidden": hid, "api": api, "days": len(days),
            "precise": {"hidden": p_hid, "api": p_api, "opaque": sorted(enc.opaque), "fails": enc.fails}}


def precise_out(o) -> dict:
    enc = FP.Encoder(builder_cls=web.StateBuilder, base=FP_BASE)
    return {"fp": enc.fingerprint("out", o), "opaque": sorted(enc.opaque), "fails": enc.fails}


if REF:
    b0 = builder()
    o0 = b0.build()
    with open(sys.argv[4], "w", encoding="utf-8") as f:
        json.dump({"out": san(o0), "p_out": precise_out(o0), "extras": extras(b0), "inval": b0.daily.get("_inval"), "n_fork": buildproc._ST.get("n_fork"),
                   "n_inproc": buildproc._ST.get("n_inproc")}, f, ensure_ascii=False, sort_keys=True)
    sys.exit(0)
RB = tempfile.mkdtemp(prefix="tj_fork_ref_")
try:
    shutil.copytree(BASE, os.path.join(RB, "b"), symlinks=True)
    pr = subprocess.run([sys.executable, os.path.abspath(__file__), "--ref", os.path.join(RB, "b"), str(NOW), os.path.join(RB, "out.json")],
                        capture_output=True, text=True, timeout=600, env={k: v for k, v in os.environ.items() if k != "TJ_TEST_FORK"})
    try:
        with open(os.path.join(RB, "out.json"), encoding="utf-8") as f:
            REFD = json.load(f)
    except (OSError, ValueError):
        REFD = {}
finally:
    shutil.rmtree(RB, ignore_errors=True)
chk(pr.returncode == 0 and REFD.get("out") and REFD.get("n_inproc") == 1 and not REFD.get("n_fork"),
    "F2 기준 빌드(새 프로세스 · 같은 사본 · 웹 안) 끝남", {"rc": pr.returncode, "err": pr.stderr[-600:]})
out_ref = REFD.get("out") or {}

SPEC_NOTE, SPEC_WANT = "G4NOTE", "G4WANT"
D_NOTE = time.strftime("%Y-%m-%d", time.gmtime(NOW - 9 * DAY))
D_WANT = time.strftime("%Y-%m-%d", time.gmtime(NOW - 8 * DAY))
SET_KEY, DICT_KEY = "g4-modset-probe", ("g4-moddict-probe",)
OTHER = os.path.join(paths.STATE_DIR, "g4_probe_other.json")
CG_PARENT = calcguard.path_of()
CG_CHILD = calcguard.path_of(suffix="build")
BF = builder()
orig = BF._daily_series


def probe(*a, **k):
    if not getattr(probe, "fired", False):
        probe.fired = True
        rec = {"pid": os.getpid()}
        for mn, nm in buildproc.MODSET:
            getattr(sys.modules[mn], nm).add(SET_KEY)
        for mn, nm, _cap in buildproc.MODDICT:
            getattr(sys.modules[mn], nm)[DICT_KEY] = "g4"
        dc0 = read(DC.path)
        rec["aw_ret"] = statefile.atomic_write_json(DC.path, {"g4probe": 1})
        rec["aw_dc_same"] = read(DC.path) == dc0
        statefile.atomic_write_json(OTHER, {"g4": 1})
        rec["aw_other"] = read(OTHER) is not None
        px0 = read(BF.px.path)
        BF.px._dirty = max(int(getattr(BF.px, "_dirty", 0) or 0), 1)
        BF.px._save()
        rec["px_own"] = "_save" in BF.px.__dict__
        rec["px_same"] = read(BF.px.path) == px0
        rec["note_n"] = DC.note_change(SPEC_NOTE, [D_NOTE])
        rec["note_dc_same"] = read(DC.path) == dc0
        calcguard.swallowed("g4:probe", OSError("g4 probe"))
        rec["cg_suffix"] = calcguard._SUFFIX[0]
        with DC.lock:
            DC.want.setdefault(SPEC_WANT, {"days": set(), "w": 0.0, "t0": NOW})["days"].add(D_WANT)
        BF.__dict__["_g4_probe"] = rec
    return orig(*a, **k)


BF._daily_series = probe
st0 = dict(buildproc._ST)
nf0 = int(st0.get("n_fork") or 0)
try:
    out_fork_raw = BF.build()
    out_fork = san(out_fork_raw)
finally:
    del BF._daily_series
P = BF.__dict__.get("_g4_probe") or {}
stats = {k: buildproc._ST.get(k) for k in ("n_fork", "n_inproc", "last", "why_in", "last_err", "skipped")}

chk(int(buildproc._ST.get("n_fork") or 0) == nf0 + 1 and buildproc.plan().get("on"), "F1 포크 자식이 빌드(n_fork +1 · 계획 on)", stats)
chk(P.get("pid") not in (None, PARENT), "F1 탐침이 다른 프로세스(자식 pid ≠ 부모)에서 돌았고 그 기록이 부모 빌더로 옴", P)

d = diff(out_ref, out_fork)
chk(not d and out_ref.get("fields"), "F2 포크 빌드 결과 = 웹 안 빌드 결과(같은 원장 · 화면 계약 전체)", d)

WANT_SET, WANT_DICT = ("_PERP_BAD_WARNED",), ("_GSYM_MEMO", "_IMP_MEMO", "_CS_MEMO")
reg_set = [getattr(sys.modules.get(mn), nm, None) for mn, nm in buildproc.MODSET]
reg_dict = [getattr(sys.modules.get(mn), nm, None) for mn, nm, _c in buildproc.MODDICT]
srcdir = os.path.realpath(T.SRC) + os.sep
holders = {}
for mn, m in list(sys.modules.items()):
    if m is None or not os.path.realpath(getattr(m, "__file__", "") or "/").startswith(srcdir):
        continue
    for nm in WANT_SET + WANT_DICT:
        if nm in vars(m):
            holders.setdefault(nm, []).append((mn, vars(m)[nm]))
unreg = ["%s.%s" % (mn, nm) for nm, hs in holders.items() for mn, o in hs
         if not any(o is r for r in (reg_set if nm in WANT_SET else reg_dict))]
chk(not unreg and set(holders) == set(WANT_SET + WANT_DICT),
    "F3 메모·표식을 쥔 모든 src 모듈 전역 = 회수 목록(MODSET/MODDICT)의 같은 객체(목록 밖 사본·빠진 줄 0)",
    {"목록 밖": unreg, "못 찾은 이름": sorted(set(WANT_SET + WANT_DICT) - set(holders))})
miss_set = [f"{mn}.{nm}" for mn, nm in buildproc.MODSET if SET_KEY not in getattr(sys.modules[mn], nm)]
miss_dict = [f"{mn}.{nm}" for mn, nm, _c in buildproc.MODDICT if getattr(sys.modules[mn], nm).get(DICT_KEY) != "g4"]
chk(buildproc.MODSET and not miss_set, "F3 MODSET — 자식이 늘린 표식이 부모 모듈 전역에(목록 %d줄 전부)" % len(buildproc.MODSET), miss_set)
chk(buildproc.MODDICT and not miss_dict, "F3 MODDICT — 자식이 채운 메모 새 키가 부모 모듈 전역에(목록 %d줄 전부)" % len(buildproc.MODDICT), miss_dict)

chk(P.get("aw_ret") is None and P.get("aw_dc_same") is True and P.get("aw_other") is True,
    "F4① 자식의 statefile.atomic_write_json = 그날 마감가 저장본만 막음(다른 파일은 씀)", P)
chk(P.get("px_own") is True and P.get("px_same") is True, "F4② 자식의 px._save = 안 씀(1분봉 캐시 파일은 부모가 반영 뒤)", P)
dc_after = json.loads(read(DC.path) or "{}")
chk(P.get("note_n") == 1 and P.get("note_dc_same") is True and D_NOTE in ((dc_after.get("chg") or {}).get(SPEC_NOTE) or {}),
    "F4③ DAYCLOSE.note_change — 자식은 파일 안 씀 · 부모가 같은 인자로 다시 불러 저장본에 변경 기록", {"probe": P, "chg": dc_after.get("chg")})
cg_child = json.loads(read(CG_CHILD) or "{}")
cg_parent = json.loads(read(CG_PARENT) or "{}")
chk(P.get("cg_suffix") == "build" and "g4:probe" in (cg_child.get("sites") or {}) and cg_child.get("pid") == P.get("pid")
    and "g4:probe" not in (cg_parent.get("sites") or {}) and "g4:probe" not in calcguard.snapshot() and calcguard._SUFFIX[0] == "",
    "F4④ calcguard — 자식 기록은 '<프로세스>_build' 파일로만(부모 파일·부모 메모리 기록 무접촉)",
    {"child": cg_child.get("sites", {}).get("g4:probe"), "child_pid": cg_child.get("pid"), "parent_has": "g4:probe" in calcguard.snapshot()})

w9 = DC.want.get(SPEC_WANT) or {}
chk(D_WANT in set(w9.get("days") or ()), "F5 DayClose — 자식이 넣은 그날 마감가 조회 요청이 부모 DAYCLOSE.want 에", w9)

chk(isinstance(BF.__dict__.get("_g4_probe"), dict) and not buildproc._ST.get("skipped"),
    "F6 자식 빌드가 새로 묶은 빌더 칸이 부모에 · 보낼 수 없어 뺀 칸 0", stats.get("skipped"))

ex_ref, ex_fork = REFD.get("extras") or {}, extras(BF)
d_hid = diff(ex_ref.get("hidden"), ex_fork["hidden"], "$.hidden")
d_api = diff(ex_ref.get("api"), ex_fork["api"], "$.api")
chk(ex_ref.get("hidden") and (ex_ref.get("hidden") or {}).get("_day_idx") and not d_hid,
    "F6 빌더 숨은 출력(_day_idx 등 상세 API·POST 검증 재료 — golden_dump hidden 규칙) = 웹 안 기준 빌드(부모 반영 뒤)", d_hid)
chk(ex_ref.get("days") and not d_api, "F6 상세 API(day_events·tax_rows·att_detail) = 웹 안 기준 빌드", d_api)

pr_ref, pr_fork = ex_ref.get("precise") or {}, ex_fork["precise"]
po_ref, po_fork = REFD.get("p_out") or {}, precise_out(out_fork_raw)
fails = (pr_ref.get("fails") or []) + pr_fork["fails"] + (po_ref.get("fails") or []) + po_fork["fails"]
chk(not fails and po_ref.get("fp", {}).get("d") and po_ref == po_fork,
    "F8 정밀 지문 — 화면 계약(out) 값 동등(Decimal·날짜·dict 순서까지 · 직렬화 실패 0)", fails[:5] or (po_ref.get("fp"), po_fork.get("fp")))
d_ph = diff(pr_ref.get("hidden"), pr_fork["hidden"], "$.precise.hidden")
d_pa = diff(pr_ref.get("api"), pr_fork["api"], "$.precise.api")
chk(pr_ref.get("hidden") and not d_ph and pr_ref.get("opaque") == pr_fork["opaque"],
    "F8 정밀 지문 — 빌더 숨은 출력 값 동등(객체 내부 · 표식으로 줄인 칸 목록 같음)", d_ph or (pr_ref.get("opaque"), pr_fork["opaque"]))
chk(pr_ref.get("api") and not d_pa, "F8 정밀 지문 — 상세 API 값 동등", d_pa)

st_now = ledger_stamp()
if st_now is None:
    chk(True, "F7 원장 표식 없는 판(R1 전) — 도장 비교 건너뜀")
else:
    chk(BF.daily.get("_inval") == st_now and REFD.get("inval") == st_now,
        "F7 R1 일별 캐시 도장 — 포크 자식이 찍은 daily['_inval'] 이 부모 빌더에 · 원장 표식과 같음", (BF.daily.get("_inval"), st_now))
T.finish()
