#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _sec_lint as L  # noqa: E402
import _harness as T  # noqa: E402

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

t0 = time.time()
IX = L.PyIndex(T.ROOT, ("src", "tools"))
for _m9, _t9 in IX.mods.items():
    L.kw_to_pos(_t9["tree"])
UNIQ = re.compile(r"getpid|secrets\.|token_hex|uuid|mkstemp|NamedTemporaryFile|random|time\.time|monotonic|thread")
TMPNAME = re.compile(r"(?i)tmp|(?<![a-z])temp(?!l)|\.part|\.new\b|_new\b|(?<![a-z])lock")
CLI = re.compile(r"\bsys\.argv\b|^(?:args|a|ns|opts|o)\.\w+")
DIRECT_OK = {
    "src/fsio.py::_create_direct": (1, "create_exclusive 의 폴백 — 하드 링크를 못 거는 파일 시스템에서 '없을 때만 만들기'는 os.replace 로 못 함"
                                       "(덮어씀) · O_EXCL 로 만들고 쓰다 실패하면 만든 파일을 지운다(반쪽 파일이 남지 않음)"),
}
DIRECT_SEEN = {}


def base(s):
    return s.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] if s else ""


def family(mod):
    p = IX.path.get(mod, mod)
    if p.startswith("tools/"):
        return "tool:" + os.path.basename(p)
    m = os.path.basename(p)[:-3]
    for pre, fam in (("core", "core"), ("discopen", "core"), ("evm_", "evm"), ("sol_", "sol"), ("bsc_", "bsc"), ("http_", "web"), ("view_", "web"),
                     ("web", "web"), ("buildproc", "web"), ("onboarding", "web"), ("ex_foreign", "exf"), ("exf_", "exf"), ("depaddr", "exf"),
                     ("liq_watch", "exf"), ("hl_spot", "exf"), ("perp_dex", "exf"), ("upbit_link", "ex"), ("alert_bot", "alert"), ("alert_watch", "alert"),
                     ("review_", "review"), ("tron_watch", "tron"), ("sui_watch", "sui"), ("ton_watch", "ton"), ("btc_watch", "btc"),
                     ("unit_runner", "runner"), ("search_worker", "search")):
        if m == pre or (pre.endswith("_") and m.startswith(pre)) or (pre == "core" and m.startswith("core_")):
            return fam
    return "lib:" + m


def mode_of(call):
    mode = None
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return mode if isinstance(mode, str) else ("r" if len(call.args) < 2 and not call.keywords else None)


def _aliases(mod, fi=None):
    imp = dict(IX.mods[mod]["imp"])
    for n in (fi.nodes if fi is not None else ()):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a9 in n.names:
                imp[a9.asname or a9.name] = (n.module, a9.name)
        elif isinstance(n, ast.Import):
            for a9 in n.names:
                imp[a9.asname or a9.name] = (a9.name, None)
    return imp


def resolve_call(mod, cls, imp, call):
    m = IX.mods[mod]
    f = call.func
    if isinstance(f, ast.Name):
        if f.id in m["func"] or f.id in m["cls"]:
            return (mod, f.id)
        if f.id in imp and imp[f.id][1]:
            return imp[f.id]
    elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        a9 = f.value.id
        if a9 in ("self", "cls") and cls and ("__f__" + f.attr) in m["cls"].get(cls, {}):
            return (mod, cls + "." + f.attr)
        if a9 in imp and imp[a9][1] is None:
            return (imp[a9][0], f.attr)
    return None


def _cls_of(mod, fi):
    c9 = fi.qual.split(".")[0] if "." in fi.qual else None
    return c9 if c9 in IX.mods[mod]["cls"] else None


def exclusive_lock(n):
    if not isinstance(n, ast.Call) or L.call_name(n) not in ("fcntl.flock", "fcntl.lockf"):
        return False
    op = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg in ("operation", "cmd")), None)
    if op is None:
        return False
    names = {x.attr for x in ast.walk(op) if isinstance(x, ast.Attribute)} | {x.id for x in ast.walk(op) if isinstance(x, ast.Name)}
    return "LOCK_EX" in names and "LOCK_UN" not in names


FUNCS = [(mod, fi) for mod, t in IX.mods.items() for fi in L.func_table(t["tree"])]
FLOCK = {(mod, fi.qual) for mod, fi in FUNCS if any(exclusive_lock(n) for n in fi.nodes)}
FLOCK |= {(mod, q.split(".")[0]) for mod, q in list(FLOCK) if "." in q and q.split(".")[0] in IX.mods[mod]["cls"]}
CALLERS = {}
LOCKWITH = {}
HAS_MAIN = {}
for mod, t in IX.mods.items():
    main_ids = set()
    for st9 in t["tree"].body:
        if isinstance(st9, ast.If) and "__main__" in ast.unparse(st9.test):
            HAS_MAIN[mod] = True
            main_ids |= {id(x) for x in ast.walk(st9)}
    imp0 = _aliases(mod)
    for n in L.module_nodes(t["tree"]):
        if isinstance(n, ast.Call):
            t9 = resolve_call(mod, None, imp0, n)
            if t9:
                CALLERS.setdefault(t9, set()).add((mod, "<main>" if id(n) in main_ids else "<mod>"))
for mod, fi in FUNCS:
    cls9, imp9 = _cls_of(mod, fi), _aliases(mod, fi)
    for n in fi.nodes:
        if isinstance(n, ast.Call):
            t9 = resolve_call(mod, cls9, imp9, n)
            if t9:
                CALLERS.setdefault(t9, set()).add((mod, fi.qual))
        elif isinstance(n, (ast.With, ast.AsyncWith)) and any(isinstance(it.context_expr, ast.Call) and resolve_call(mod, cls9, imp9, it.context_expr) in FLOCK
                                                             for it in n.items):
            LOCKWITH.setdefault((mod, fi.qual), set()).update(id(x) for st9 in n.body for x in ast.walk(st9))


def locked(mod, fi, node):
    return (mod, fi.qual) in FLOCK or id(node) in LOCKWITH.get((mod, fi.qual), ())


def fams(mod, q, depth=0, seen=None):
    fam = family(mod)
    if q == "<main>":
        return {"cli:" + os.path.basename(IX.path.get(mod, mod))[:-3]}
    if q == "<mod>" or not fam.startswith("lib:") or "." in q or depth > 4:
        return {fam}
    seen = seen or set()
    out = set()
    for cm, cq in sorted(CALLERS.get((mod, q), ())):
        if (cm, cq) == (mod, q) or (cm, cq) in seen:
            continue
        seen.add((cm, cq))
        nq = cq if cq.startswith("<") else (cq.split(".")[0] if "." in cq and family(cm).startswith("lib:") else cq)
        out |= fams(cm, nq, depth + 1, seen)
    return out or {fam}


M = {k: {} for k in ("direct_write", "fixed_tmp", "helper_copy", "delete_signal", "multi_writer", "ledger_tool")}
S = {k: {} for k in M}


def add(metric, key, sample):
    M[metric][key] = M[metric].get(key, 0) + 1
    S[metric].setdefault(key, []).append(sample)


WRITES = {}
TEXT = {m: open(os.path.join(T.ROOT, IX.path[m]), encoding="utf-8").read() for m in IX.mods}
if "paths" in IX.mods:
    _pt9 = ast.parse(TEXT["paths"])
    _reg9 = {id(c) for st in _pt9.body if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") in ("REG", "DYN") for c in ast.walk(st.value)}
    TEXT["paths"] = "\n".join(repr(c.value) for c in ast.walk(_pt9) if isinstance(c, ast.Constant) and isinstance(c.value, str) and id(c) not in _reg9)
_KNOWS = {}


def knows(name, mod):
    if name not in _KNOWS:
        pat = re.compile(r"[\"'/]" + re.escape(name) + r"[\"']")
        _KNOWS[name] = {m for m, s9 in TEXT.items() if name in s9 and pat.search(s9)}
    return bool(_KNOWS[name] - {mod})


print("[1~5] 자리 조사(%d 모듈)" % len(IX.mods))
for mod, t in sorted(IX.mods.items()):
    rp = IX.path[mod]
    for fi in L.func_table(t["tree"]) + L.module_fis(t["tree"]):
        f, fn, nodes, la = fi.node, fi.qual, fi.nodes, fi.assigns
        key = "%s::%s" % (rp, fn)
        params = ({a.arg for a in f.args.args + f.args.kwonlyargs} - {"self", "cls"}) if hasattr(f, "args") else set()
        repl = [n for n in nodes if isinstance(n, ast.Call) and L.call_name(n) == "os.replace" and len(n.args) == 2]
        repl_src = {ast.unparse(n.args[0]) for n in repl}
        has_tmp_write = any(isinstance(n, ast.Call) and (L.call_name(n) in ("tempfile.mkstemp", "os.open") or
                                                          (L.call_name(n) == "open" and "w" in (mode_of(n) or ""))) for n in nodes)
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            nm = L.call_name(n)
            if nm == "open" and n.args and (mode_of(n) or "").startswith(("w", "x")) or (nm == "open" and n.args and "w" in (mode_of(n) or "") and "+" in (mode_of(n) or "")):
                a0 = ast.unparse(n.args[0])
                if a0 not in repl_src and not TMPNAME.search(a0) and not a0.startswith(("'/proc", "'/dev", '"/proc', '"/dev')) and not CLI.search(a0):
                    b = base(L.resolve_fi(IX, mod, fi, n.args[0]))
                    add("direct_write", key, "%s:%d open(%s, %r) → %s" % (rp, n.lineno, a0[:40], mode_of(n), b or "?"))
            elif nm == "os.open" and len(n.args) >= 2:
                fl = ast.unparse(n.args[1])
                a0 = ast.unparse(n.args[0])
                if "O_CREAT" in fl and ("O_WRONLY" in fl or "O_TRUNC" in fl) and "O_APPEND" not in fl and "O_RDWR" not in fl \
                        and a0 not in repl_src and not TMPNAME.search(a0) and not CLI.search(a0):
                    if key in DIRECT_OK and "O_EXCL" in fl and "O_TRUNC" not in fl:
                        DIRECT_SEEN[key] = DIRECT_SEEN.get(key, 0) + 1
                    else:
                        b = base(L.resolve_fi(IX, mod, fi, n.args[0]))
                        add("direct_write", key, "%s:%d os.open(%s, %s) → %s" % (rp, n.lineno, a0[:40], fl.replace("os.", "")[:40], b or "?"))
            elif nm in ("os.remove", "os.unlink") and n.args:
                b = base(L.resolve_fi(IX, mod, fi, n.args[0]))
                if b and "*" not in b and not re.search(r"(?i)\.(lock|tmp|part|bak)\b|\.bad|tmp", b) and knows(b, mod):
                    add("delete_signal", key, "%s:%d %s(%s)" % (rp, n.lineno, nm, b))
            tgt = None
            if nm in ("common.atomic_write_json", "atomic_write_json", "common.write_json_if_changed", "write_json_if_changed",
                      "common.append_durable_jsonl", "append_durable_jsonl", "statefile.atomic_write_json", "statefile.write_json_if_changed",
                      "statefile.append_durable_jsonl", "ss._atomic_write_text", "settings_store._atomic_write_text", "fsio.atomic_write_text",
                      "_atomic_write_text", "atomic_write", "_write", "_atomic_write") and n.args:
                tgt = n.args[0]
            elif nm == "os.replace" and len(n.args) == 2:
                tgt = n.args[1]
            elif nm == "open" and n.args and any(c in (mode_of(n) or "") for c in "wax") and ast.unparse(n.args[0]) not in repl_src:
                tgt = n.args[0]
            elif nm == "os.open" and len(n.args) >= 2 and "O_CREAT" in ast.unparse(n.args[1]) and "O_RDWR" not in ast.unparse(n.args[1]):
                tgt = n.args[0]
            if tgt is not None:
                b = base(L.resolve_fi(IX, mod, fi, tgt))
                if b and "*" not in b and not b.startswith(".") and not re.search(r"(?i)\.(tmp|part|lock)\b|tmp|\.bad|\.bak|\.orphan", b):
                    WRITES.setdefault(b, []).append((mod, fn, locked(mod, fi, n), n.lineno))
        for n in repl:
            a0 = n.args[0]
            srcs = la.get(a0.id, []) if isinstance(a0, ast.Name) else [a0]
            for v in srcs:
                txt = ast.unparse(v)
                fixed = (isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add) and isinstance(v.right, ast.Constant)) or \
                        (isinstance(v, ast.JoinedStr) and isinstance(v.values[-1], ast.Constant)) or \
                        (isinstance(v, ast.Call) and L.call_name(v) in ("os.path.join", "paths.state") and v.args and
                         ((isinstance(v.args[-1], ast.BinOp) and isinstance(v.args[-1].right, ast.Constant)) or isinstance(v.args[-1], ast.Constant)))
                if fixed and not UNIQ.search(txt) and TMPNAME.search(txt):
                    add("fixed_tmp", key, "%s:%d os.replace(%s ← %s, …)" % (rp, n.lineno, ast.unparse(a0)[:20], txt[:50]))
                    break
        for n in repl:
            d0 = n.args[1]
            roots = {x.id for x in ast.walk(d0) if isinstance(x, ast.Name)}
            if roots & params and has_tmp_write and fn.rsplit(".", 1)[-1] not in ("swap_in", "apply", "files_apply", "new_ledger", "read_control_json"):
                add("helper_copy", key, "%s:%d os.replace(…, %s) — 목적지가 인자" % (rp, n.lineno, ast.unparse(d0)[:30]))
                break

def site_fams(m, fn):
    fs = fams(m, fn)
    own = "lib:" + os.path.basename(IX.path.get(m, m))[:-3]
    return (fs - {own}) if len(fs) > 1 else fs


for b, sites in sorted(WRITES.items()):
    allf = set()
    for m, fn, _lk, _ln in sites:
        allf |= site_fams(m, fn)
    if len(allf) < 2:
        continue
    for m, fn, lk, ln in sites:
        if not lk:
            add("multi_writer", b, "%s::%s:%d(%s)" % (IX.path[m], fn, ln, "·".join(sorted(site_fams(m, fn)))))

WRITER_LOCK_MODS = {m for m, t9 in IX.mods.items() if any("core_writer.lock" in s for s in L.str_consts(t9["tree"]))}
WRITER_LOCK_CALLS = {(m, q) for m, q in FLOCK if m in WRITER_LOCK_MODS}
WRITER_LOCK_CTX = set()


def _local_calls(fi, names):
    return [c for c in fi.nodes if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in names]


def _returned_calls(fi):
    out = []
    for n in fi.nodes:
        if isinstance(n, ast.Return) and n.value is not None:
            for v in ((n.value.body, n.value.orelse) if isinstance(n.value, ast.IfExp) else (n.value,)):
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name):
                    out.append(v.func.id)
    return out


_grew = True
while _grew:
    _grew = False
    for _m9, _fi9 in FUNCS:
        key9 = (_m9, _fi9.qual)
        if _m9 not in WRITER_LOCK_MODS or "." in _fi9.qual or key9 in WRITER_LOCK_CALLS or key9 in WRITER_LOCK_CTX:
            continue
        calls9 = {q for m, q in WRITER_LOCK_CALLS if m == _m9}
        ctx9 = {q for m, q in WRITER_LOCK_CTX if m == _m9}
        gen9 = any(isinstance(x, (ast.Yield, ast.YieldFrom)) for x in _fi9.nodes)
        with9 = {id(it.context_expr) for x in _fi9.nodes if isinstance(x, (ast.With, ast.AsyncWith)) for it in x.items}
        takes9 = bool(_local_calls(_fi9, calls9)) or any(id(c) in with9 for c in _local_calls(_fi9, ctx9))
        if takes9 and not gen9:
            WRITER_LOCK_CALLS.add(key9)
            _grew = True
        elif takes9 or any(q in ctx9 for q in _returned_calls(_fi9)):
            WRITER_LOCK_CTX.add(key9)
            _grew = True
WRITER_LOCK_FUNCS = WRITER_LOCK_CALLS | WRITER_LOCK_CTX
SQLW = re.compile(r"(?is)^\s*(?:insert|update|delete|replace\s+into|create\s+(?:table|index|trigger|view)|drop\s|alter\s)")
for mod, t in sorted(IX.mods.items()):
    rp = IX.path[mod]
    if not rp.startswith("tools/"):
        continue
    tree = t["tree"]
    lits = L.str_consts(tree)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    writes = any(L.call_name(c).endswith((".execute", ".executemany", ".executescript")) and c.args and isinstance(c.args[0], ast.Constant)
                 and isinstance(c.args[0].value, str) and SQLW.search(c.args[0].value) for c in calls) \
        or any(L.call_name(c).endswith(".commit") for c in calls)
    ledger = any("ledger.db" in s for s in lits) or "DB_PATH" in ast.dump(tree) or any(L.call_name(c) in ("db.connect", "dbm.connect", "db.open_rw") for c in calls)
    mt = IX.mods[mod]
    res = set()
    entered = set()
    with_ids = {id(it.context_expr) for n in ast.walk(tree) if isinstance(n, (ast.With, ast.AsyncWith)) for it in n.items}
    for c in calls:
        fn9 = c.func
        tgt9 = None
        if isinstance(fn9, ast.Attribute) and isinstance(fn9.value, ast.Name) and fn9.value.id in mt["imp"] and mt["imp"][fn9.value.id][1] is None:
            tgt9 = (mt["imp"][fn9.value.id][0], fn9.attr)
        elif isinstance(fn9, ast.Name) and fn9.id in mt["imp"] and mt["imp"][fn9.id][1]:
            tgt9 = mt["imp"][fn9.id]
        if tgt9 is not None:
            res.add(tgt9)
            if id(c) in with_ids:
                entered.add(tgt9)
    lock = any("core_writer.lock" in s for s in lits) or any(L.call_name(c).rsplit(".", 1)[-1] == "writer_lock" for c in calls) \
        or any(("writer" in t9[1] or "ledger" in t9[1]) and t9 in FLOCK for t9 in res) or bool(res & WRITER_LOCK_CALLS) or bool(entered & WRITER_LOCK_CTX)
    if writes and ledger and not lock:
        add("ledger_tool", rp, "%s — SQL 쓰기·원장 경로 있음 · core.writer_lock 없음" % rp)

for k in M:
    print("  %-14s %3d 자리 · 합 %d" % (k, len(M[k]), sum(M[k].values())))
T.chk(len(IX.mods) >= 100 and len(WRITES) >= 20 and sum(M["helper_copy"].values()) >= 1,
      "조사기 동작(모듈 100+ · 쓰기 대상 파일 20+ · 공용 원자 헬퍼 1+ — 고쳐서 0 이 될 지표에는 하한을 두지 않음)",
      {"모듈": len(IX.mods), "쓰기 파일": len(WRITES), "헬퍼": sum(M["helper_copy"].values())})

hints = {
    "direct_write": "최종 경로에 바로 씀(쓰다 죽으면 반쪽 파일) — statefile.atomic_write_json 처럼 같은 폴더 임시 파일 → fsync → os.replace",
    "fixed_tmp": "임시 파일 이름이 고정(+'.tmp') — 두 쓰기가 같은 임시 파일을 밟음 · tempfile.mkstemp(dir=같은 폴더) 를 쓰세요",
    "helper_copy": "원자 쓰기 헬퍼 사본이 늘었음 — 새로 만들지 말고 statefile.atomic_write_json(또는 R2 의 공용 헬퍼)을 부르세요",
    "delete_signal": "다른 모듈이 아는 파일을 지워 신호로 씀(지우기·다시 만들기 경합) — 원장 meta 의 seq·버전 칸으로(R1 daily_inval_seq)",
    "multi_writer": "여러 유닛이 쓰는 파일에 잠금 없는 쓰기 — fcntl.flock 으로 읽기-수정-쓰기를 감싸세요(R3)",
    "ledger_tool": "원장을 쓰는 도구에 원장 작성자 잠금이 없음 — with ledger_lock.hold(paths.DB_PATH, who=…) 로 쓰기 전체를 감싸세요(R3)",
}
doc = ("G1 test_stab_lint 기준선 — 원자 쓰기·경합 6종 자리(파일::함수 → 수 · multi_writer 는 파일 이름 → 잠금 없는 쓰기 자리 수 · "
       "helper_copy 는 합계만). 늘면 FAIL · 줄면 `--update-lower`")
T.chk(DIRECT_SEEN == {k: v[0] for k, v in DIRECT_OK.items()},
      "[stab] direct_write 이유 있는 허용(DIRECT_OK) = 지금 소스의 O_EXCL 자리 수와 같음(늘면·사라지면 허용 표를 고쳐라)",
      {"허용": {k: v[0] for k, v in DIRECT_OK.items()}, "지금": DIRECT_SEEN})
T.chk("ledger_lock" not in IX.mods or ({("ledger_lock", "acquire")} <= WRITER_LOCK_CALLS
                                        and {("ledger_lock", "hold"), ("ledger_lock", "hold_if")} <= WRITER_LOCK_CTX),
      "[stab] 원장 잠금 도우미 인식(ledger_lock — 부르면 잡음 acquire · with 로 들어가야 잡음 hold·hold_if)",
      {"call": sorted(WRITER_LOCK_CALLS), "with": sorted(WRITER_LOCK_CTX)})
L.ratchet(T, "stab", M, doc, hints=hints, samples=S, modes={"helper_copy": "total"},
          exists=lambda f: (os.path.exists(os.path.join(T.ROOT, f)) if "/" in f else True))
print("(시간 %.1f초)" % (time.time() - t0))
T.finish()
