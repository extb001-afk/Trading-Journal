#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import ast  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

import cfg_schema as CS  # noqa: E402

chk = T.chk

EXTRA_TOP = {
    "brokers": ("src/other_assets.py", "cfg_fn() 콜백 결과에서 읽음(화면은 getattr(builder, 'cfg'))"),
    "nft": ("src/nft.py", "Tracker.cfg_fn() 콜백 결과에서 읽음"),
    "other_assets": ("src/other_assets.py", "cfg_fn() 콜백 결과에서 읽음"),
    "wow": ("src/http_get.py", "getattr(builder, 'cfg') 에서 읽음"),
}
TOP_VARKEY_OPEN = {
    "bf_engine:_SinceSource._section|varkey|<top>[section]": ("src/bf_engine.py", ("bsc", "sol"), "구간 이름 bsc·sol 만 최상위 블록"),
    "cfg_schema:check|varkey|<top>[k]": ("src/cfg_schema.py", (), "선언표 검사 자체 — 모든 키 이름을 훑음(값 무변 · 읽는 키 아님)"),
}
SUB_VARKEY_OPEN = {
    "sellchart:daily_max|varkey|review['buy_eval_daily_max' if kind == 'buy' else 'sell_eval_daily_]":
        ("src/sellchart.py", ("buy_eval_daily_max", "sell_eval_daily_max")),
}


def _src_has(rel, word):
    m = MODS.get(rel[len("src/"):-len(".py")].replace("/__init__", "").replace("/", ".")) if rel.startswith("src/") else None
    return m is not None and any(isinstance(n, ast.Constant) and n.value == word for n in ast.walk(m.tree))


TOOLS = os.path.join(T.ROOT, "tools", "refactor")
_pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
if not os.path.isfile(os.path.join(TOOLS, "cfg_keys.py")):
    chk(_pub, "[1] 공개판 배치 — 비공개 도구(cfg_keys) 없음 · 정적 대조 건너뜀" if _pub else "[1] 저장소 배치인데 tools/refactor/cfg_keys.py 없음")
else:
    sys.path.insert(0, TOOLS)
    import cfg_keys as CK  # noqa: E402
    MODS = CK.index(T.ROOT)[0]
    snap = CK.snapshot(T.ROOT)
    chk(snap["converged"] is True, "[1] 자료 흐름 지도 고정점 수렴")
    top_reads = set(snap["top"])
    top_open = []
    for site, lits in snap["varkey"].items():
        m = re.match(r"^[^|]+\|varkey\|<top>\[", site)
        if not m:
            continue
        top_reads |= {x for x in lits if x != "?"}
        if "?" in lits:
            top_open.append(site)
    for site in top_open:
        ent = TOP_VARKEY_OPEN.get(site)
        chk(ent is not None, "[1] 최상위 변수 키 '?' 자리 = 닫힌 표에 있음: %s" % site)
        if ent:
            top_reads |= set(ent[1])
            chk(all(_src_has(ent[0], w) for w in ent[1]), "[1] 닫힌 표 글자가 코드에 있음: %s" % site, ent)
    chk(set(TOP_VARKEY_OPEN) <= set(top_open), "[1] 최상위 변수 키 닫힌 표에 낡은 줄 없음", sorted(set(TOP_VARKEY_OPEN) - set(top_open)))
    for k, (rel, why) in sorted(EXTRA_TOP.items()):
        chk(k not in top_reads, "[1] 닫힌 표 EXTRA_TOP '%s' — 지도가 이미 찾음 → 표에서 빼기" % k)
        chk(_src_has(rel, k), "[1] 닫힌 표 EXTRA_TOP '%s' 글자가 %s 에 있음(%s)" % (k, rel, why))
    reads = top_reads | set(EXTRA_TOP)
    decl = CS.declared_top()
    undeclared = sorted(k for k in reads if k not in decl and not CS.is_memo(k))
    chk(not undeclared, "[1] 코드가 읽는 최상위 키 ⊆ 선언 ∪ 메모 꼴 ∪ 실행 주입", undeclared)
    unread = sorted(k for k in decl if k not in reads)
    chk(not unread, "[1] 선언했는데 아무도 안 읽는 최상위 키 0(문서만 남은 키 막기)", unread)
    chk(all(CS.is_memo(k) for k in CS.RUNTIME_KEYS) and set(CS.RUNTIME_KEYS) <= reads, "[1] 실행 주입 키 = 메모 꼴 · 코드가 읽음", CS.RUNTIME_KEYS)
    chk(not (decl & set(CS.RUNTIME_KEYS)), "[1] 실행 주입 키는 선언표에 안 둠(사용자 키 아님)")
    for blk in sorted(CS.BLOCKS):
        subs = CS.declared_sub(blk)
        sub_reads = {s.split(".", 1)[1] for s in snap["sub"] if s.split(".", 1)[0] == blk}
        for site, lits in snap["varkey"].items():
            if re.match(r"^[^|]+\|varkey\|%s\[" % re.escape(blk), site):
                sub_reads |= {x for x in lits if x != "?"}
                if "?" in lits:
                    ent = SUB_VARKEY_OPEN.get(site)
                    chk(ent is not None, "[1] 닫힌 블록 %s 의 변수 키 '?' 자리 = 닫힌 표에 있음: %s" % (blk, site))
                    if ent:
                        sub_reads |= set(ent[1])
                        chk(all(_src_has(ent[0], w) for w in ent[1]), "[1] 닫힌 표 하위 글자가 코드에 있음: %s" % site, ent)
        bad = []
        for u in snap["unresolved"]:
            where, kind, detail = (u.split("|", 2) + ["", ""])[:3]
            if kind == "guard":
                m = (re.search(r"\.get\('%s'\)[^\[]*\[(\w+)\]$" % re.escape(blk), detail)
                     or re.search(r"\['%s'\][^\[]*\[(\w+)\]$" % re.escape(blk), detail))
                if m:
                    sub_reads.add(m.group(1))
            elif kind in ("whole", "passout") and re.match(r"^(?:for in |\*\*|lambda→)?%s(\.|\s|\[|$)" % re.escape(blk), detail):
                bad.append(u)
            elif kind == "conflict" and re.search(r"(?:\{|,)blk:%s(?:,|\})" % re.escape(blk), detail):
                bad.append(u)
        chk(not bad, "[1] 닫힌 블록 %s = 통째 소비·넘김 0(있으면 열린 블록으로)" % blk, bad)
        extra = sorted(x for x in sub_reads if x not in subs and not CS.is_memo(x))
        chk(not extra, "[1] 닫힌 블록 %s 하위 키 읽기 ⊆ 선언" % blk, extra)
        dead = sorted(x for x in subs if x not in sub_reads)
        chk(not dead, "[1] 닫힌 블록 %s 선언 하위 키는 누가 읽음" % blk, dead)
    stale = sorted(s for s in SUB_VARKEY_OPEN if "?" not in snap["varkey"].get(s, ()))
    chk(not stale, "[1] 하위 변수 키 닫힌 표에 낡은 줄 없음", stale)
    chk(all(set(k[1].split("|")) <= set(CS.TYPES) for k in CS.KEYS), "[1] 선언 형 이름 ⊆ TYPES")
    chk([k[0] for k in CS.KEYS] == sorted(k[0] for k in CS.KEYS) and len(CS.KEYS) == len(decl), "[1] 선언표 이름순 · 겹침 0")
    chk(all(isinstance(k[2], str) and k[2] and isinstance(k[3], str) and k[3] for k in CS.KEYS), "[1] 선언마다 설명·문서 기본값 글")
    chk(set(CS.BLOCKS) <= decl and all(CS.TYPES[[k for k in CS.KEYS if k[0] == b][0][1]] == (dict,) for b in CS.BLOCKS),
        "[1] 닫힌 블록 = 선언된 dict 키")

cfg = {"chains": {"eth": {"rpcs": ["https://rpc.invalid"], "zz_sub": 1}}, "wallets": [], "_wallets_note": "메모",
       "zz_unknown": {"a": [1, 2]}, "web": {"port": 8023, "zz_web": True, "_x_note": "메모"}, "backfill_months": "5",
       "bsc": {"zz_open": 1}, "price_overrides_note": "메모", "_disabled_chains": [], "backfill_since": None, "build_proc": True,
       "review": ["틀린 형"], "evm_poll_sec": 45.5}
snap0 = copy.deepcopy(cfg)
ids0 = (id(cfg), id(cfg["chains"]), id(cfg["web"]), list(cfg))
got = CS.check(cfg)
paths_ = [p for p, _r in got]
chk(paths_ == ["zz_unknown", "web.zz_web", "backfill_months", "build_proc", "review"], "[2] 찾은 것 = 모르는 키 · 닫힌 블록 하위 · 형 다름(설정 순서)", got)
chk(cfg == snap0 and (id(cfg), id(cfg["chains"]), id(cfg["web"]), list(cfg)) == ids0, "[2] 값 무변(깊은 같음 · id · 키 순서)")
chk(all("값" not in r and "5" not in r for _p, r in got), "[2] 이유 글에 값 없음", got)
chk(dict(got)["backfill_months"].startswith("형 다름(선언 num · 실제 str)") and dict(got)["build_proc"].startswith("형 다름(선언 str · 실제 bool)"),
    "[2] 형 다름 이유 = 선언·실제 형 이름(bool 은 num 아님)", got)
chk(CS.check({"backfill_months": True}) == [("backfill_months", "형 다름(선언 num · 실제 bool)")], "[2] true 는 숫자 아님")
chk(CS.check({"backfill_months": 3, "evm_poll_sec": 1.5, "backfill_since": 1_700_000_000, "web": None}) == [], "[2] 정수·실수·epoch·null 통과")
for bad_in in (None, [], "x", 3, {1: 2}, {"web": {1: 2}}, {"zz" * 100: 1}, {"z\n\x00": 1}):
    try:
        r = CS.check(bad_in)
        ok = isinstance(r, list)
    except Exception as e:   # noqa: BLE001 [probe]
        ok, r = False, repr(e)
    chk(ok, "[2] 이상한 입력에 예외 0: %r" % (type(bad_in).__name__,), r)
chk(CS.check([]) == [("", "설정이 JSON 객체가 아님")], "[2] 객체 아님 = 한 줄")
long_k = CS.check({"zz" * 100: 1})[0][0]
chk(len(long_k) <= 61 and long_k.endswith("…"), "[2] 긴 이름은 잘라 적음", long_k)
chk(CS.check({"z\n\x00": 1})[0][0] == "z??", "[2] 출력 못 하는 글자는 ? 로", CS.check({"z\n\x00": 1}))
chk(CS.is_memo("_x") and CS.is_memo("brokers_note") and not CS.is_memo("note") and not CS.is_memo(None), "[2] 메모 꼴 = _ 시작 · _note 끝")
chk(CS.declared_sub("bsc") is None and "port" in CS.declared_sub("web"), "[2] 열린 블록 = None · 닫힌 블록 = 집합")

ex = json.load(open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8"))
chk(CS.check(ex) == [], "[3] config.example.json 경고 0", CS.check(ex))
chk(all(k in CS.declared_top() or CS.is_memo(k) for k in ex), "[3] 예시 최상위 키 = 선언 또는 메모")

CANARY = "canary-SECRET-%d" % os.getpid()


class Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.levels = []

    def emit(self, rec):
        self.lines.append(rec.getMessage())
        self.levels.append(rec.levelno)


cap = Cap()
lg = logging.Logger("tj.test_cfg_schema")
lg.addHandler(cap)
CS._WARNED[0] = False
n1 = CS.warn_once({"chains": {}, "wallets": [], "zz_secret_holder": CANARY, "web": {"zz": CANARY, CANARY + "k": 1}, "backfill_months": CANARY,
                   CANARY + "-as-key": None}, lg)
n2 = CS.warn_once({"zz_again": 1}, lg)
chk(n1 == 5 and n2 == 0 and len(cap.lines) == 1 and cap.levels == [logging.INFO], "[4] 프로세스당 한 번(두 번째 = 0 · INFO 1줄)", (n1, n2, cap.lines))
chk(CANARY not in cap.lines[0] and "zz_secret_holder" not in cap.lines[0] and "web.zz" not in cap.lines[0], "[4] 값·선언 밖 이름(키 자리 카나리아) 안 찍힘", cap.lines)
chk("<선언 밖 #1>(모르는 키" in cap.lines[0] and "web.<선언 밖 #2>(모르는 하위 키" in cap.lines[0]
    and "backfill_months(형 다름(선언 num · 실제 str))" in cap.lines[0] and "<선언 밖 #5>" in cap.lines[0], "[4] 선언된 이름·이유·순번만", cap.lines)
cap.lines.clear()
CS._WARNED[0] = False
many = {"zz%02d" % i: i for i in range(25)}
chk(CS.warn_once(many, lg) == 25 and " 외 5개" in cap.lines[0] and "zz20" not in cap.lines[0], "[4] 20개까지만 적고 '외 N개'", cap.lines)
CS._WARNED[0] = False


class BadLog:
    def info(self, *a, **k):
        raise OSError("로그 못 씀")


try:
    r4 = CS.warn_once({"zz": 1}, BadLog())
    ok4 = r4 == 0
except Exception:   # noqa: BLE001 [probe]
    ok4 = False
chk(ok4, "[4] 경고를 못 남겨도 warn_once 는 예외 0 · 0 돌려줌")
CS._WARNED[0] = False

cp = os.path.join(T.TMP, "cfg_schema_conf.json")
body = {"chains": {"eth": {"rpcs": ["https://rpc.invalid"]}}, "wallets": [], "zz_new_key": {"token": CANARY}, "web": {"zz_web": CANARY},
        "review": {"coach_role": CANARY}}
with open(cp, "w", encoding="utf-8") as f:
    json.dump(body, f)
prog = (
    "import sys, json, logging\nsys.path.insert(0, sys.argv[1])\n"
    "logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout)\n"
    "import config\n"
    "if sys.argv[2] == 'boom':\n    import cfg_schema\n    cfg_schema.check = lambda c: 1 / 0\n"
    "a = config.load_config()\nb = config.load_config()\n"
    "print('RESULT', json.dumps({'zz': a.get('zz_new_key'), 'web': a.get('web'), 'rev': a.get('review'), 'same': a.get('zz_new_key') == b.get('zz_new_key')}))\n")
env = dict(os.environ, TJ_CONFIG=cp, TJ_BASE=T.TMP)
env.pop("pm_id", None)
for mode in ("normal", "boom"):
    p = subprocess.run([sys.executable, "-I", "-B", "-c", prog, T.SRC, mode], env=env, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    res = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
    val = json.loads(res[0][7:]) if res else {}
    warn = [ln for ln in p.stdout.splitlines() if "설정 확인:" in ln]
    chk(p.returncode == 0 and val.get("zz") == {"token": CANARY} and val.get("web") == {"zz_web": CANARY} and val.get("same") is True,
        "[5] %s: load_config 정상 · 모르는 키 값 그대로 돌려줌" % mode, out[-600:])
    if mode == "normal":
        chk(len(warn) == 1 and "zz_new_key" not in warn[0] and "web.<선언 밖 #2>" in warn[0] and warn[0].startswith("INFO "),
            "[5] 설정 확인 줄 = 한 번(두 번 읽어도) · INFO · 선언 밖 이름 가림", warn)
    else:
        chk(not warn, "[5] 검사가 던지면 경고 없이 정상 기동", warn)
    chk(CANARY not in out.replace(json.dumps(val, ensure_ascii=False), ""), "[5] %s: 카나리아 값이 로그에 없음" % mode)
chk(json.load(open(cp, encoding="utf-8")) == body, "[5] 설정 파일 무변")

src_cfg = open(os.path.join(T.SRC, "config.py"), encoding="utf-8").read()
fn = [n for n in ast.parse(src_cfg).body if isinstance(n, ast.FunctionDef) and n.name == "load_config"][0]
order = []
for st in fn.body:
    for n in ast.walk(st):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in ("warn_once", "apply_activity_gate", "_drop_disabled_chains", "_config_fail"):
                order.append((st.lineno, name))
seq = [nm for _l, nm in sorted(order)]
chk(seq.count("warn_once") == 1 and seq.index("warn_once") > max(i for i, x in enumerate(seq) if x == "_config_fail")
    and seq.index("warn_once") < seq.index("apply_activity_gate") < seq.index("_drop_disabled_chains"),
    "[5] 연결 자리 = 필수 키 검사 뒤 · 활동 게이트·끈 체인 빼기 앞", seq)
users = []
for f in sorted(os.listdir(T.SRC)):
    if f.endswith(".py") and f != "cfg_schema.py":
        with open(os.path.join(T.SRC, f), encoding="utf-8") as fh:
            tr = ast.parse(fh.read())
        if any((isinstance(n, ast.Import) and any(a.name == "cfg_schema" for a in n.names))
               or (isinstance(n, ast.ImportFrom) and n.module == "cfg_schema") for n in ast.walk(tr)):
            users.append(f)
chk(users == ["config.py"], "[5] cfg_schema 를 부르는 src = config 하나(다른 읽기 길 경고 없음)", users)
T.finish()
