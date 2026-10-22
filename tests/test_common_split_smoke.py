#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk
LAYERS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arch_baseline", "layers.json")
try:
    with open(LAYERS, encoding="utf-8") as f:
        SPLIT = sorted(m for m, o in (json.load(f).get("split_of") or {}).items() if o == "common")
except (OSError, ValueError):
    SPLIT = []
if not SPLIT:
    SPLIT = [m for m in ("paths", "timeutil", "envfile", "runtime") if os.path.isfile(os.path.join(T.SRC, m + ".py"))]
HAVE = importlib.util.find_spec("common") is not None and len(SPLIT) >= 4
INTO = (["logs"] if "statefile" in SPLIT else []) + (["chaincatalog"] if "config" in SPLIT else [])


CHILD = r'''
import json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
base, base2 = sys.argv[2], sys.argv[3]
out = {}
import common
srcd = os.path.realpath(sys.argv[1])
out["src_loaded"] = sorted(n for n, m in list(sys.modules.items()) if getattr(m, "__file__", None)
                           and os.path.dirname(os.path.realpath(m.__file__)) == srcd)   # import common 직후(함수 안 늦은 import 전)
import importlib
SPL = {m: importlib.import_module(m) for m in sys.argv[4].split(",")}
import envfile, paths, runtime, timeutil
out["sqlite3"] = "sqlite3" in sys.modules or "_sqlite3" in sys.modules
out["db"] = "db" in sys.modules
out["paths"] = [paths.STATE_DIR, paths.ENV_PATH, paths.CONFIG_PATH, common.STATE_DIR, common.DB_PATH]
cfg = common.load_config()
out["cfg"] = [sorted({"chains", "wallets"} & set(cfg)), cfg.get("build_proc"), cfg.get("wallets")]
out["env"] = [common.read_env_file().get("TJ_BUILD_PROC"), common._env_file_value("TJ_BUILD_PROC"), envfile.parse_env_line("export A = 'b'")]
out["bpm"] = list(runtime.build_proc_mode())
p1 = runtime.cpu_plan()
out["plan"] = [sorted(p1), p1 is common.cpu_plan(), bool(p1.get("on"))]
out["gate0"] = common.gate_decisions(cfg)
out["es0"] = [common._es_key_or_collected("ethx", {}), common._es_key_or_collected("ethx", {"key": False})]
out["mark0"] = common.mark_hist_dirty(86400 * 20000)
out["mark0_at"] = os.path.isfile(os.path.join(base, "state", "hist_dirty.json"))
out["upd0"] = (common.hist_dirty_update(lambda cur: cur) or {}).get("from")
out["seed0"] = common.seed_json("smoke.json", default="없음", base_dir=base)
out["day0"] = [timeutil.kst_day0(86400 * 20000 + 3600), common.iso_epoch("1970-01-02T00:00:00")]
# K2 rebase
common.rebase_state(os.path.join(base2, "state"))
out["rb_paths"] = [paths.STATE_DIR, paths.INBOX_DIR, paths.DB_PATH, paths.ACTIVITY_GATE_PATH, paths.ENV_PATH, paths.CONFIG_PATH]
try:
    common.gate_decisions(cfg)
    out["gate1"] = "읽음"
except SystemExit as e:
    out["gate1"] = "손상:" + str(e)[:200]
out["es1"] = common._es_key_or_collected("ethx", {"key": False})
common.mark_hist_dirty(86400 * 20001)
out["mark1_at"] = os.path.isfile(os.path.join(base2, "state", "hist_dirty.json"))
out["upd1"] = (common.hist_dirty_update(lambda cur: cur) or {}).get("from")
out["seed1"] = common.seed_json("smoke.json", default="없음", base_dir=base)
# K3 대리 모듈
from unittest import mock
orig = paths.STATE_DIR
with mock.patch("common.STATE_DIR", os.path.join(base, "elsewhere")):
    out["in_patch"] = [paths.STATE_DIR == os.path.join(base, "elsewhere"), common.STATE_DIR == paths.STATE_DIR]
out["after_patch"] = [paths.STATE_DIR == orig, "STATE_DIR" in vars(common)]
common.ENV_PATH = os.path.join(base, "없는.env")
out["bpm_noenv"] = list(runtime.build_proc_mode())
common.CONFIG_PATH = os.path.join(base, "cfg2.json")
out["bpm_cfg2"] = list(common.build_proc_mode())
del common.SUB_MAX
out["del"] = [hasattr(envfile, "SUB_MAX"), hasattr(common, "SUB_MAX")]
envfile.SUB_MAX = 5
out["moved_in_dict"] = sorted(n for n in common._MOVED if n in vars(common))
out["dir"] = all(n in dir(common) for n in common._MOVED)
try:
    common.없는_이름_스모크
    out["missing"] = "없음 안 남"
except AttributeError as e:
    out["missing"] = str(e)
out["owners"] = sorted({m.__name__ for m in common._MOVED.values()})
out["n_moved"] = len(common._MOVED)
import dis, subprocess, types
def own(m):
    got = set()
    for k, v in vars(m).items():
        if k.startswith("__") or isinstance(v, types.ModuleType):
            continue
        if callable(v) and getattr(v, "__module__", m.__name__) != m.__name__:
            continue
        got.add(k)
    return got
out["own"] = {m.__name__: sorted(own(m) ^ {n for n, o in common._MOVED.items() if o is m}) for m in SPL.values()}
import logs
INTO_M = [importlib.import_module(m) for m in sys.argv[5].split(",") if m]
out["into_own"] = sorted(n for n, o in common._MOVED.items() if o in INTO_M and not (n in vars(o) and n in own(o)))
out["own"] = {k: v for k, v in out["own"].items() if v}
def codes(co):
    yield co
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            yield from codes(c)
bare = []
for k, v in vars(common).items():
    fns = [v] if isinstance(v, types.FunctionType) else [f for f in vars(v).values() if isinstance(f, types.FunctionType)] \
        if isinstance(v, type) and v.__module__ == "common" else []
    for fn in fns:
        if fn.__module__ != "common":
            continue
        for co in codes(fn.__code__):
            bare += ["%s:%s" % (co.co_name, i.argval) for i in dis.get_instructions(co)
                     if i.opname in ("LOAD_GLOBAL", "LOAD_NAME", "STORE_GLOBAL", "DELETE_GLOBAL") and i.argval in common._MOVED]
out["bare"] = bare
alone = subprocess.run([sys.executable, "-B", "-c", "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
                        "[importlib.import_module(m) for m in sys.argv[2].split(',')]; "
                        "print(sorted(m for m in ('common', 'db', 'sqlite3') if m in sys.modules))", sys.argv[1],
                        ",".join([sys.argv[4], "logs"] + [m for m in ("chaincatalog", "token_tables") if os.path.isfile(os.path.join(sys.argv[1], m + ".py"))])],
                       capture_output=True, text=True, timeout=120)
out["split_alone"] = alone.stdout.strip() if alone.stdout.strip() != "[]" else []
if "statefile" in SPL:   # K5 — 4-2
    import histmark, net_http, seeds, statefile, textutil
    st = os.path.join(base, "k5")
    os.makedirs(st, exist_ok=True)
    pj = os.path.join(st, "a.json")
    statefile.atomic_write_json(pj, {"한": 1, "b": [1, 2]})
    out["k5_aw"] = [open(pj, encoding="utf-8").read(), oct(os.stat(pj).st_mode & 0o777)]
    out["k5_wic"] = [common.write_json_if_changed(pj, {"x": 1}), common.write_json_if_changed(pj, {"x": 1})]
    jl = os.path.join(st, "q.jsonl")
    with open(jl, "wb") as f9:
        f9.write(b'{"a": 1}')   # 부분 줄(줄바꿈 없음)
    common.append_durable_jsonl(jl, {"b": 2})
    out["k5_jl"] = open(jl, encoding="utf-8").read()
    bad = os.path.join(st, "bad.json")
    with open(bad, "w", encoding="utf-8") as f9:
        f9.write("{깨짐")
    try:
        common.read_json(bad, {})
        out["k5_rj"] = "안 멈춤"
    except SystemExit as e:
        out["k5_rj"] = "멈춤" if "상태 파일 손상" in str(e) else str(e)
    out["k5_rcj"] = [common.read_control_json(bad, "기본"), os.path.exists(bad), os.path.exists(bad + ".bad")]
    # 포크 자식 쓰기 차단 길 — 대리 대입 = statefile 을 바꿈 · 호출 시점 조회하는 모든 길이 가짜에 닿음
    real = statefile.atomic_write_json
    seen = []
    common.atomic_write_json = lambda p9, o9: seen.append(os.path.basename(p9))
    try:
        out["k5_is"] = statefile.atomic_write_json is common.atomic_write_json
        common.write_json_if_changed(os.path.join(st, "w2.json"), {"y": 2})
        common.mark_hist_dirty(86400 * 20002, state_dir=st)
        sec = os.path.join(st, "sec.json")
        with open(sec, "w", encoding="utf-8") as f9:
            json.dump({"err": "token=" + "S" * 20 + " at https://rpc.invalid/v3/" + "k" * 24}, f9)
        out["k5_scrub_n"] = common.scrub_secret_file(sec)
        common.atomic_write_json(os.path.join(st, "via.json"), {})   # histcurve 꼴(common.X 로 부름)
    finally:
        common.atomic_write_json = real
    out["k5_seen"] = seen
    out["k5_restored"] = statefile.atomic_write_json is real and "atomic_write_json" not in vars(common)
    # BROWSER_UA_HOSTS 객체 정체성
    h0 = id(net_http.BROWSER_UA_HOSTS)
    with open(os.path.join(base, "cfg3.json"), "w", encoding="utf-8") as f9:
        json.dump({"chains": {"robx": {"browser_ua": True, "blockscout": "https://Scan.Robx.invalid/api"}}, "wallets": []}, f9)
    common.CONFIG_PATH = os.path.join(base, "cfg3.json")
    common.load_config()
    out["k5_ua"] = [id(net_http.BROWSER_UA_HOSTS) == h0, common.BROWSER_UA_HOSTS is net_http.BROWSER_UA_HOSTS, sorted(net_http.BROWSER_UA_HOSTS),
                    common.ua_for("https://scan.robx.invalid/x", "tj") == net_http.BROWSER_UA, common.ua_for("https://other.invalid/", "tj")]
    # HTTP_BODY_MAX 대입 = read_capped 기본 상한(호출 시점)
    class R9:
        length = None
        def read(self, n):
            return b"x" * min(n, 10)
    common.HTTP_BODY_MAX = 4
    try:
        common.read_capped(R9())
        out["k5_cap"] = "안 막음"
    except net_http.ResponseTooLarge:
        out["k5_cap"] = "막음"
    finally:
        common.HTTP_BODY_MAX = 32 * 1024 * 1024
    out["k5_cap2"] = [len(net_http.read_capped(R9())), net_http.HTTP_BODY_MAX]
    out["k5_txt"] = [common.strip_links("see https://x.invalid/a and pump.fun now"), common.log_word0("0x" + "0" * 63 + "5" + "ff" * 4)]
    with open(os.path.join(base, "state", "seed_local", "smoke2.json"), "w", encoding="utf-8") as f9:
        json.dump({"b": 2}, f9)
    os.makedirs(os.path.join(base, "seed"), exist_ok=True)
    with open(os.path.join(base, "seed", "smoke2.json"), "w", encoding="utf-8") as f9:
        json.dump({"a": 1, "b": 1}, f9)
    common.rebase_state(os.path.join(base, "state"))
    out["k5_seed"] = common.seed_json("smoke2.json", base_dir=base)
    out["k5_logs"] = [common.SECRET_FIELD_KEYS is logs.SECRET_FIELD_KEYS, common.setup_logging is logs.setup_logging,
                      common.scrub_secret_file is logs.scrub_secret_file]
    import sqlite3
    cx = sqlite3.connect(":memory:")
    cx.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    out["k5_late"] = [common.hist_late_put(cx, 86400 * 20000, now=86400 * 20001), len(histmark.hist_late_read(cx)), common.HIST_LATE_K]
if "config" in SPL:   # K6 — 4-3
    import builtins, config, chaincatalog, chainsweep, pricing, recon
    out["k6_id"] = [common.load_config is config.load_config, common._CFG_LOADED is config._CFG_LOADED, common.chain_enabled is config.chain_enabled,
                    common.EXTRA_CHAINS is chaincatalog.EXTRA_CHAINS, common.NATIVE_MIRROR is chaincatalog.NATIVE_MIRROR,
                    common.ZK_STACK is chaincatalog.ZK_STACK, common.DEFAULT_NATIVE_SYMBOL is chaincatalog.DEFAULT_NATIVE_SYMBOL]
    out["k6_left"] = [hasattr(chainsweep, "SWEEP_CHAINS"), hasattr(pricing, "STABLE_CAS"), hasattr(pricing, "DS_CHAIN"), hasattr(recon, "MULTICALL3"),
                      hasattr(pricing, "DOLLAR_NATIVES")]
    with open(os.path.join(base, "cfg6.json"), "w", encoding="utf-8") as f9:
        json.dump({"chains": {"monad": {}, "arc": {}, "stable": {}}, "wallets": [], "native_symbol": {"arc": "MYARC"}}, f9)
    common.CONFIG_PATH = os.path.join(base, "cfg6.json")
    c6 = common.load_config()
    out["k6_ns"] = [c6["native_symbol"].get(k) for k in ("monad", "arc", "stable")] + [sorted(c6.get("wrapped_native") or {})]
    real = config.load_config
    common.load_config = lambda: "가짜"
    out["k6_fake"] = [config.load_config(), common.load_config()]
    common.load_config = real
    out["k6_fake"].append(config.load_config is real and "load_config" not in vars(common))
    only = sorted(k for k in chaincatalog.SWEEP_CHAINS if k not in chaincatalog.EXTRA_CHAINS)[0]
    sw = chaincatalog.SWEEP_CHAINS[only]
    t0, t1, t2 = common.fill_chain_table({}), common.fill_chain_table({}, 1), common.fill_chain_table({"monad": "내 이름"}, 2)
    out["k6_fill"] = [t0.get("monad"), t1.get("monad"), t2.get("monad"), t0.get(only) == sw[0], t1.get(only) == sw[2], t2.get(only) == str(sw[1])]
    blk, why = chaincatalog.block_for(only, True, {"getLogsSpan": 1000, "blocksPerSec": 2.0})
    out["k6_cat"] = [list(chaincatalog.native_of("monad")), list(chaincatalog.native_of(only)) == [sw[2], None], why,
                     (blk or {}).get("chain_id") == int(sw[1]), list(chaincatalog.block_for("nochain_smoke", True, {}))]
    keep = chaincatalog.SWEEP_CHAINS
    chaincatalog.SWEEP_CHAINS = {only: keep[only]}
    try:
        out["k6_cl"] = sorted(chainsweep.chain_list({"chains": {}})) == [only]
    finally:
        chaincatalog.SWEEP_CHAINS = keep
    probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import %s as t; "
             "print(json.dumps([sorted(m for m in ('pricing', 'recon', 'common', 'config', 'chainsweep', 'chaincatalog', 'seeds', 'db', 'sqlite3') "
             "if m in sys.modules and m != t.__name__)%s]))")
    tt = subprocess.run([sys.executable, "-B", "-c", probe % ("token_tables", ", all(t.STABLE_CAS[c].get('0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34') == 'USDE' "
                         "for c in ('base', 'arbitrum', 'optimism', 'scroll', 'bsc', 'robinhood')), "
                         "sorted(k for k in ('monad', 'megaeth', 'tron', 'ton', 'sui', 'katana') if k in t.STABLE_CAS), "
                         "t.DS_CHAIN.get('hyperevm'), t.MULTICALL3_BY_CHAIN.get('zksync', '')[:6], t.MULTICALL3[:6], sorted(t.__all__)"),
                         sys.argv[1]], capture_output=True, text=True, timeout=120)
    out["k6_tt"] = json.loads(tt.stdout.strip().splitlines()[-1]) if tt.stdout.strip() else tt.stderr[-400:]
    cc = subprocess.run([sys.executable, "-B", "-c", probe % ("chaincatalog", ", len(t.SWEEP_CHAINS) > 50, sorted(t.NATIVE_MIRROR), sorted(t.ZK_STACK)"),
                         sys.argv[1]], capture_output=True, text=True, timeout=120)
    out["k6_cc"] = json.loads(cc.stdout.strip().splitlines()[-1]) if cc.stdout.strip() else cc.stderr[-400:]
    import token_tables
    free = []
    for mod in (config, chaincatalog, token_tables):
        g9 = vars(mod)
        for v in list(g9.values()):
            if isinstance(v, types.FunctionType) and v.__module__ == mod.__name__:
                for co in codes(v.__code__):
                    free += ["%s.%s:%s" % (mod.__name__, co.co_name, i.argval) for i in dis.get_instructions(co)
                             if i.opname == "LOAD_GLOBAL" and i.argval not in g9 and not hasattr(builtins, i.argval)]
    out["k6_free"] = free
print("JSON " + json.dumps(out, ensure_ascii=False))
'''

if not HAVE:
    GONE = importlib.util.find_spec("common") is None
    T.chk(GONE, "대리 모듈 common 삭제됨(4-6) — 대리 스모크 대상 없음(건너뜀 · 정의 모듈 동작은 모듈별 시험·sqlite_barrier·timeutil_kst 가 봄)",
          SPLIT)
    T.finish()

B1, B2 = os.path.join(T.TMP, "b1"), os.path.join(T.TMP, "b2")
for b in (B1, B2):
    os.makedirs(os.path.join(b, "state", "seed_local"), exist_ok=True)
with open(os.path.join(B1, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": [], "build_proc": "fork"}, f)
with open(os.path.join(B1, "cfg2.json"), "w", encoding="utf-8") as f:
    json.dump({"chains": {}, "wallets": [], "build_proc": "auto"}, f)
with open(os.path.join(B1, ".env"), "w", encoding="utf-8") as f:
    f.write("TJ_BUILD_PROC=off\nTJ_ETHERSCAN_KEY=SYNTHsmokeKEY0000\n")
with open(os.path.join(B1, "state", "chain_activity.json"), "w", encoding="utf-8") as f:
    json.dump({"pairs": {}}, f)
with open(os.path.join(B2, "state", "chain_activity.json"), "w", encoding="utf-8") as f:
    f.write("{손상")
with open(os.path.join(B2, "state", "cursor_evm_ethx.json"), "w", encoding="utf-8") as f:
    json.dump({"0x" + "ab" * 20: 7}, f)
with open(os.path.join(B2, "state", "seed_local", "smoke.json"), "w", encoding="utf-8") as f:
    json.dump({"k": "새 state"}, f)
ENV0 = {k: v for k, v in os.environ.items() if not k.startswith("TJ_") or k.startswith("TJ_TEST_")}
ENV0["TJ_BASE"] = B1
p = subprocess.run([sys.executable, "-c", CHILD, T.SRC, B1, B2, ",".join(SPLIT), ",".join(INTO)], capture_output=True, text=True, timeout=180, env=ENV0)
js = [x for x in p.stdout.splitlines() if x.startswith("JSON ")]
r = json.loads(js[-1][5:]) if js else {}
chk(bool(r), "자식 프로세스 결과(JSON)", (p.returncode, (p.stdout + p.stderr)[-1500:]))
if r:
    S1, S2 = os.path.join(B1, "state"), os.path.join(B2, "state")
    chk(r["paths"] == [S1, os.path.join(B1, ".env"), os.path.join(B1, "config.json"), S1, os.path.join(S1, "ledger.db")],
        "K1 경로 = TJ_BASE 아래(대리 common.X = paths.X)", r["paths"])
    chk(r["cfg"] == [["chains", "wallets"], "fork", []], "K1 load_config = 합성 config.json(paths.CONFIG_PATH 호출 시점)", r["cfg"])
    chk(r["env"] == ["off", "off", ["A", "b"]], "K1 read_env_file · _env_file_value · parse_env_line = 합성 .env 규칙", r["env"])
    chk(r["bpm"] == ["off", ".env"], "K1 runtime.build_proc_mode = .env 가 config 보다 먼저(환경 없음)", r["bpm"])
    chk(r["plan"][1] is True and r["plan"][2] is False and {"on", "core", "cores", "why"} <= set(r["plan"][0]),
        "K1 cpu_plan = 한 번 계산(같은 객체) · off = 빌드 자식 안 씀", r["plan"])
    chk(r["gate0"] == [] and r["es0"] == [True, False], "K1 gate_decisions(빈 게이트) · _es_key_or_collected(.env 키 = 켬 · 키 없고 커서 없음 = 안 켬)",
        [r["gate0"], r["es0"]])
    chk(r["mark0"] == r["upd0"] and r["mark0_at"] is True, "K1 mark_hist_dirty · hist_dirty_update = 첫 state 의 hist_dirty.json",
        [r["mark0"], r["upd0"], r["mark0_at"]])
    chk(r["seed0"] == "없음" and r["day0"] == [86400 * 20000 - 9 * 3600, 86400], "K1 seed_json(없음 = 기본값) · kst_day0 · iso_epoch(시간대 없음 = UTC)",
        [r["seed0"], r["day0"]])
    chk(r["rb_paths"] == [S2, os.path.join(S2, "inbox"), os.path.join(S2, "ledger.db"), os.path.join(S2, "chain_activity.json"),
                          os.path.join(B1, ".env"), os.path.join(B1, "config.json")],
        "K2 rebase_state = 다섯 경로만 새 state(ENV_PATH · CONFIG_PATH 그대로)", r["rb_paths"])
    chk(r["gate1"].startswith("손상:"), "K2 rebase 뒤 gate_decisions = 새 state 의 게이트 파일을 읽음(손상 = fail-closed)", r["gate1"])
    chk(r["es1"] is True and r["mark1_at"] is True and r["upd1"] == "2024-10-05" and r["seed1"] == {"k": "새 state"},
        "K2 rebase 뒤 이더스캔 커서 · 곡선 표식 · seed_local = 새 state", [r["es1"], r["mark1_at"], r["upd1"], r["seed1"]])
    chk(r["in_patch"] == [True, True] and r["after_patch"] == [True, False],
        "K3 mock.patch('common.STATE_DIR') = paths 를 바꾸고, 나온 뒤 paths.STATE_DIR 원래 값 · common dict 에 안 남음", [r["in_patch"], r["after_patch"]])
    chk(r["bpm_noenv"] == ["fork", "config"] and r["bpm_cfg2"] == ["auto", "config"],
        "K3 common.ENV_PATH · common.CONFIG_PATH 대입 = 옮긴 함수(runtime)의 paths.X 조회까지 먹음", [r["bpm_noenv"], r["bpm_cfg2"]])
    chk(r["del"] == [False, False] and r["moved_in_dict"] == [] and r["dir"] is True,
        "K3 del common.X = 정의 모듈에서 지움 · common dict 에 옮긴 이름 0 · dir(common) 엔 보임", [r["del"], r["moved_in_dict"], r["dir"]])
    chk("has no attribute" in r["missing"] and r["owners"] == sorted(SPLIT + INTO) and r["sqlite3"] is False and r["db"] is False,
        "K3 없는 이름 = AttributeError · 넘기는 곳 = split_of 분할 모듈(+ 옮겨 넣은 logs · chaincatalog)만 · import 뒤 sqlite3·db 안 실림",
        [r["missing"], r["owners"], r["sqlite3"], r["db"]])

if r:
    chk(r["own"] == {} and r["into_own"] == [] and r["n_moved"] >= 38,
        "K4 대리 이름 표 = 분할 모듈이 정의한 이름 전부(빠짐·남는 것 0 · %s개) · logs · chaincatalog 로 넘기는 이름은 그 모듈이 정의" % r["n_moved"],
        [r["own"], r["into_own"]])
    chk(r["bare"] == [], "K4 common 에 남은 함수·메서드(안쪽 함수·람다 포함)가 옮긴 이름을 맨 이름으로 읽는 곳 0(바이트코드 LOAD_GLOBAL — 남는 함수 → 정의모듈.X)",
        r["bare"][:20])
    chk(r["split_alone"] == [], "K4 분할 모듈만 import = common 안 실림(분할 모듈 → common 순환 금지)", r["split_alone"])
    chk(r["src_loaded"] == sorted(["chaincatalog", "common", "fsio", "logs"] + SPLIT),
        "K4 common import 폐포의 src 모듈 = fsio · logs · chaincatalog(체인 표 — 4-3) · 분할 모듈만(db 안 실음)",
        r["src_loaded"])

if r and "statefile" in SPLIT:
    chk(r["k5_aw"] == ['{"한":1,"b":[1,2]}', "0o600"], "K5 statefile.atomic_write_json = 압축 구분자 · 한글 그대로 · 0600", r["k5_aw"])
    chk(r["k5_wic"] == [True, False], "K5 write_json_if_changed = 처음 씀 · 같은 내용 다시 = 안 씀", r["k5_wic"])
    chk(r["k5_jl"] == '{"a": 1}\n{"b": 2}\n', "K5 append_durable_jsonl = 부분 줄 닫고 한 줄", r["k5_jl"])
    chk(r["k5_rj"] == "멈춤" and r["k5_rcj"] == ["기본", False, True], "K5 read_json 손상 = 멈춤 · read_control_json 손상 = .bad 로 옮기고 기본값",
        [r["k5_rj"], r["k5_rcj"]])
    chk(r["k5_is"] is True and r["k5_seen"] == ["w2.json", "hist_dirty.json", "sec.json", "via.json"] and r["k5_scrub_n"] >= 1
        and r["k5_restored"] is True,
        "K5 포크 자식 차단 길: common.atomic_write_json 대입 = statefile 을 바꿈 → write_json_if_changed · histmark 표식 · logs.scrub_secret_file · "
        "대리 경유 호출 모두 가짜에 닿음 · 되돌린 뒤 common dict 에 안 남음", [r["k5_is"], r["k5_seen"], r["k5_scrub_n"], r["k5_restored"]])
    chk(r["k5_ua"] == [True, True, ["scan.robx.invalid"], True, "tj"],
        "K5 BROWSER_UA_HOSTS = load_config 가 같은 set 객체를 비우고 채움(common.X is net_http.X · ua_for 가 봄)", r["k5_ua"])
    chk(r["k5_cap"] == "막음" and r["k5_cap2"] == [10, 32 * 1024 * 1024], "K5 common.HTTP_BODY_MAX 대입 = net_http.read_capped 기본 상한(호출 시점) · 되돌림",
        [r["k5_cap"], r["k5_cap2"]])
    chk(r["k5_txt"] == ["see and pump.fun now", 5], "K5 strip_links(URL 지움 · pump.fun 남김) · log_word0(첫 워드만)", r["k5_txt"])
    chk(r["k5_seed"] == {"a": 1, "b": 2}, "K5 seed_json = 공개 seed + seed_local 칸별 합치기", r["k5_seed"])
    chk(r["k5_logs"] == [True, True, True], "K5 logs 로 옮긴 이름: common.SECRET_FIELD_KEYS · setup_logging · scrub_secret_file = logs 의 그 객체", r["k5_logs"])
    chk(r["k5_late"] == ["2024-10-04", 1, "hist_late"], "K5 hist_late_put · hist_late_read(메모리 원장 meta) · HIST_LATE_K", r["k5_late"])
    import ast as _ast
    bt = _ast.parse(open(os.path.join(T.SRC, "buildproc.py"), encoding="utf-8").read())
    hb = [n for n in bt.body if isinstance(n, _ast.FunctionDef) and n.name == "_hist_begin"]
    tg = [_ast.unparse(t) for n in _ast.walk(hb[0]) if isinstance(n, _ast.Assign) for t in n.targets] if hb else []
    chk("statefile.atomic_write_json" in tg and not any(t.startswith("common.") for t in tg),
        "K5 buildproc._hist_begin 이 바꿔 끼우는 표적 = statefile.atomic_write_json(대리 경유 아님 · 옮긴 이름의 주인 모듈)", tg)

if r and "config" in SPLIT:
    chk(r["k6_id"] == [True] * 7, "K6 대리 정체성: common.load_config·_CFG_LOADED·chain_enabled is config.X · 체인 표 4개 is chaincatalog.X", r["k6_id"])
    chk(r["k6_left"] == [False, False, False, False, True],
        "K6 옛 자리에 옮긴 이름 없음(chainsweep.SWEEP_CHAINS · pricing.STABLE_CAS·DS_CHAIN · recon.MULTICALL3 — 대리 없이 일괄 교체) · pricing.DOLLAR_NATIVES 는 남음",
        r["k6_left"])
    chk(r["k6_ns"] == ["MON", "MYARC", "USDT", ["monad"]],
        "K6 load_config 체인 기본값 = EXTRA_CHAINS 네이티브·랩드(랩드 없는 stable 뺌) · DEFAULT_NATIVE_SYMBOL(arc) 보다 명시값 우선", r["k6_ns"])
    chk(r["k6_fake"] == ["가짜", "가짜", True], "K6 common.load_config = 가짜 → config.load_config 도 가짜(대입 전달) · 되돌린 뒤 common dict 에 안 남음", r["k6_fake"])
    chk(r["k6_fill"] == ["Monad", "MON", "내 이름", True, True, True],
        "K6 fill_chain_table = EXTRA_CHAINS(표시명·심볼) 먼저 · 있던 값 우선 · 점검 목록(chaincatalog.SWEEP_CHAINS)은 빠진 키만(표시명·심볼·chainId)", r["k6_fill"])
    chk(r["k6_cat"] == [["MON", "0x3bd359c1119da7da1d913d1c4d2b7c461115433a"], True, "generic", True, [None, "점검 목록에 없는 체인"]],
        "K6 chaincatalog.native_of(EXTRA_CHAINS 우선 · 점검 목록 심볼) · block_for(점검 목록 범용 블록 · 없는 체인)", r["k6_cat"])
    chk(r["k6_cl"] is True, "K6 chainsweep.chain_list = chaincatalog.SWEEP_CHAINS 를 호출 시점에 봄(바꿔 끼우면 따라감)", r["k6_cl"])
    chk(r["k6_tt"] == [[], True, ["katana", "megaeth", "monad", "sui", "ton", "tron"], "hyperevm", "0xf9cd", "0xca11",
                       ["DS_CHAIN", "JPY_STABLE_CAS", "MULTICALL3", "MULTICALL3_BY_CHAIN", "STABLE_CAS", "STABLE_MINTS", "STABLE_SYMS"]],
        "K6 token_tables 만 실은 새 프로세스 = 다른 src 안 실림 · USDe OFT 보강 6체인 · 추가 체인 병합 · DS_CHAIN · Multicall3 완성(보강 루프가 그 안)", r["k6_tt"])
    chk(r["k6_cc"] == [[], True, ["arc", "stable"], ["abstract", "zksync"]],
        "K6 chaincatalog 만 실은 새 프로세스 = 다른 src(common·chainsweep·config·seeds) 안 실림 · SWEEP_CHAINS · NATIVE_MIRROR · ZK_STACK", r["k6_cc"])
    chk(r["k6_free"] == [], "K6 config · chaincatalog · token_tables 함수가 모듈에 없는 전역 이름을 읽는 곳 0(바이트코드 LOAD_GLOBAL — 옮긴 뒤 맨 이름 남김 막기)",
        r["k6_free"][:20])
T.finish()
