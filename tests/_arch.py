#!/usr/bin/env python3
import os
import sys

_ENV = {k: os.environ.get(k, "") for k in ("TJ_TEST_ARCH_STALE_FAIL", "TJ_TEST_ARCH_BASE_REF", "TJ_TEST_ARCH_CACHE")}
sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import glob  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402

try:
    import fcntl  # noqa: E402
except ImportError:
    fcntl = None

import _arch_py_facts as F  # noqa: E402
import _arch_py_metrics as M  # noqa: E402
import _arch_py_ratchet as R  # noqa: E402
import _arch_split as S  # noqa: E402

USAGE = """python3 <tests>/_arch.py --report          지금 값 · 기준선 · 설계안과 견줄 정의별 값
python3 <tests>/_arch.py --update-lower    줄어든 값만 기준선에 반영(늘어난 지표는 그대로 두고 거부 목록 출력)
python3 <tests>/_arch.py --sync-doc        docs/ARCH.md 의 계층 표(자동 칸)를 layers.json 으로 다시 씀
python3 <tests>/_arch.py --split-report    분할 승계 증명 목록(layers.json split_of · 근거 py_split_proof.json — 승계 단위 · 허용 내부 간선 · 실패)
python3 <tests>/_arch.py --init [--force] [--base <커밋>]   기준선 처음 만들기(이미 있으면 거부)
python3 <tests>/_arch.py --fold-growth     성장 사유 표(py_growth.jsonl)를 현재 상한 표(py_limits_current.json · 단위별 지금 크기)로 접고 비움(멱등)
python3 <tests>/_arch.py --tighten-targets [--write] [--rate 0.05]   축소 목표 표(py_targets.json)와 '쪼개야 할 파일' 안내(실패 아님 ·
      --write = 지금 값의 rate 만큼 줄인 새 목표를 씀 — 분기마다 한 번)
환경(run_all 이 넘기는 TJ_TEST_* 만): TJ_TEST_ARCH_STALE_FAIL=1 낮출 수 있는 기준선도 실패 ·
      TJ_TEST_ARCH_BASE_REF 기준선 무결성 비교 기준(기본 refactor 와의 병합 기준점 · none = 건너뜀) ·
      TJ_TEST_ARCH_CACHE 캐시 폴더(0 = 끔 · 기본 = 임시 폴더 tj_arch_cache_<uid>)"""

HERE, ROOT, SRC = T.HERE, T.ROOT, T.SRC
BASE_DIR = os.path.join(HERE, "arch_baseline")
DOC_ROOT = os.path.realpath(os.path.join(HERE, ".."))
PUBLIC_LAYOUT = DOC_ROOT == os.path.realpath(ROOT)
ARCH_MD = os.path.join(DOC_ROOT, "docs", "ARCH.md")
RULES_PATH = os.path.join(BASE_DIR, "py_rules.json")
LAYERS_PATH = os.path.join(BASE_DIR, "layers.json")
META_PATH = os.path.join(BASE_DIR, "py_meta.json")
SELF_CMD = "python3 " + os.path.relpath(os.path.abspath(__file__), ROOT)
STALE_FAIL = _ENV["TJ_TEST_ARCH_STALE_FAIL"] == "1"
GROWTH_PATH = os.path.join(BASE_DIR, R.GROWTH_FILE)
LIMITS_PATH = os.path.join(BASE_DIR, R.LIMITS_FILE)
TARGETS_PATH = os.path.join(BASE_DIR, R.TARGETS_FILE)
LAYER_BEGIN = "<!-- ARCH:LAYERS:BEGIN — python3 public/tests/_arch.py --sync-doc 가 layers.json 으로 다시 씀(손으로 고치지 말 것) -->"
LAYER_END = "<!-- ARCH:LAYERS:END -->"


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as f:
        return R.loads(f.read())


def discover(src, packages):
    mods, bad = [], []
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if os.path.isdir(path):
            if name == "__pycache__" or name.startswith("."):
                continue
            if name not in packages:
                bad.append("src/%s/ — src 안 새 하위 폴더(배포 도구가 src/ 한 층만 봄)" % name)
                continue
            for sub in sorted(os.listdir(path)):
                sp = os.path.join(path, sub)
                if os.path.isdir(sp) and sub != "__pycache__" and not sub.startswith("."):
                    bad.append("src/%s/%s/ — 패키지 안 하위 폴더" % (name, sub))
                elif sub.endswith(".py"):
                    mods.append((name if sub == "__init__.py" else name + "." + sub[:-3], sp, sub == "__init__.py"))
        elif name.endswith(".py"):
            mods.append((name[:-3], path, False))
    return mods, bad


def docs_text(rules):
    skip = set(rules.get("env_docs_exclude", []))
    paths = [os.path.join(DOC_ROOT, "README.md"), os.path.join(DOC_ROOT, ".env.example")]
    paths += sorted(p for p in glob.glob(os.path.join(DOC_ROOT, "docs", "**", "*.md"), recursive=True)
                    if os.path.basename(p) not in skip)
    out = []
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                out.append(f.read())
    return "\n".join(out)


def _analyzer_version():
    h = hashlib.sha1(("%d.%d" % sys.version_info[:2]).encode())
    for mod in ("_arch_py_defs.py", "_arch_py_facts.py"):
        with open(os.path.join(HERE, mod), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def _cache_dir():
    v = _ENV["TJ_TEST_ARCH_CACHE"]
    if v in ("0", "off", "no"):
        return None
    d = v or os.path.join(tempfile.gettempdir(), "tj_arch_cache_%s" % (os.getuid() if hasattr(os, "getuid") else "u"))
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
    except OSError:
        return None
    mine = not hasattr(os, "getuid") or st.st_uid == os.getuid()
    if not stat.S_ISDIR(st.st_mode) or not mine or st.st_mode & 0o022:
        return None
    return d


def _cache_load(name):
    d = _cache_dir()
    if not d:
        return {}
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_save(name, data):
    d = _cache_dir()
    if not d:
        return
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, os.path.join(d, name))
    except OSError:
        pass


class _CacheLock:

    def __init__(self, name):
        self.f = None
        d = _cache_dir()
        if d and fcntl is not None:
            try:
                self.f = open(os.path.join(d, name), "a")
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX)
            except OSError:
                self.close()

    def close(self):
        if self.f is not None:
            try:
                self.f.close()
            except OSError:
                pass
            self.f = None


def facts_for(items, save=True):
    name = "facts_%s.json" % _analyzer_version()
    lock = _CacheLock(name + ".lock")
    try:
        return _facts_locked(items, save, name)
    finally:
        lock.close()


def _facts_locked(items, save, name):
    cache = _cache_load(name)
    out, fresh = {}, {}
    for mod, text, pkg in items:
        key = hashlib.sha1(("%s\0%d\0" % (mod, pkg)).encode() + text.encode("utf-8")).hexdigest()
        fx = cache.get(key)
        if not isinstance(fx, dict):
            fx = F.facts(text, mod, pkg)
        out[mod], fresh[key] = fx, fx
    if save and set(fresh) != set(cache):
        _cache_save(name, fresh)
    return out


class State:

    def __init__(self):
        self.errors, self.load_error, self.split = [], "", None
        self.limits, limits_bad = [], []
        try:
            self.rules = read_json(RULES_PATH)
            self.layers = read_json(LAYERS_PATH)
            self.meta = read_json(META_PATH, {})
            self.growth = R.load_lines(GROWTH_PATH) or []
        except ValueError as e:
            self.rules = self.layers = None
            self.meta, self.growth, self.load_error = {}, [], "규칙·기준선 파일을 못 읽음: %s" % e
        if os.path.isfile(LIMITS_PATH):
            with open(LIMITS_PATH, encoding="utf-8") as f:
                self.limits, limits_bad = R.parse_limits(f.read())
        if self.rules is None or self.layers is None:
            self.metrics = None
            return
        mods, self.subdirs = discover(SRC, self.rules.get("src_packages", []))
        items, unreadable = [], []
        for mod, path, pkg in mods:
            try:
                with open(path, encoding="utf-8") as f:
                    items.append((mod, f.read(), pkg))
            except (OSError, UnicodeDecodeError) as e:
                unreadable.append("못 읽음 %s: %s" % (os.path.relpath(path, ROOT), e))
        self.index = facts_for(items)
        self.errors = unreadable + [fx["error"] for fx in self.index.values() if "error" in fx]
        good = {m: fx for m, fx in self.index.items() if "error" not in fx}
        self.metrics = M.compute(good, self.rules, self.layers, docs_text(self.rules))
        if self.subdirs:
            self.metrics.hard["src.subdirs"] = list(self.subdirs)
        bad = [json.dumps(g, ensure_ascii=False)[:160] for g in self.growth if not growth_row_ok(g)]
        if bad or limits_bad:
            self.metrics.hard["growth.invalid"] = bad + limits_bad
        if bad:
            self.growth = []
        lim = self.rules.get("limits", {})
        bad = ["limits.%s = %r" % (k, v) for k, v in sorted(lim.items())
               if not isinstance(v, int) or isinstance(v, bool) or v < 0] if isinstance(lim, dict) else ["limits 가 표가 아님"]
        if bad:
            self.metrics.hard["rules.invalid"] = bad
        self.split = S.attach(self, SRC)

    def allow(self):
        return self.growth + R.limit_rows(self.limits)


def growth_row_ok(g):
    return isinstance(g, dict) and g.get("k") in R.SPECS and R.SPECS[g["k"]][1] == "num" \
        and all(isinstance(g.get(x), str) and g[x].strip() for x in ("m", "q", "why", "commit")) and R.why_ok(g["why"]) \
        and isinstance(g.get("to"), int) and not isinstance(g.get("to"), bool) and g["to"] >= 0


_STATE = []


def state():
    if not _STATE:
        _STATE.append(State())
    return _STATE[0]


def baseline_path(group):
    return os.path.join(BASE_DIR, R.GROUP_FILE[group])


def _fmt(v):
    return "{" + ", ".join(v) + "}" if isinstance(v, list) else str(v)


def _where(u):
    if u.get("t") in ("e", "x", "n"):
        return ("%s " % u["at"] if u.get("at") else "") + "%s → %s" % (u["m"], u["q"])
    if u.get("at"):
        return "%s %s" % (u["at"], u["q"]) if u["q"] not in ("<file>",) else u["at"]
    return "%s → %s" % (u["m"], u["q"])


def describe(u, b):
    return "%s = %s(%s)" % (_where(u), _fmt(u["v"]), "기준선 %s" % _fmt(b["v"]) if b else "기준선에 없음 — 새 위반")


def emit(vd, n_base):
    k = vd.k
    _g, _kind, _t, title, rule, fix = R.SPECS[k]
    for u, b, g in vd.grown:
        print("허용 %s %s = %s(기준선 %s · 성장 사유 표 상한 %s — %s)" % (k, _where(u), u["v"], b["v"], g["to"], g.get("why", "")),
              flush=True)
    for u, b in vd.succeeded:
        print("승계 %s %s = %s ← 기준선 %s.%s %s(_arch_py_ratchet.SUCCESSION · 옛 단위 예산 안)" % (
            k, _where(u), u["v"], b["m"], b["q"], b["v"]), flush=True)
    if vd.ok:
        T.chk(True, "%s %s — 위반 %d(기준선 %d) · 새 0 · 커짐 0%s" % (
            k, title, len(vd.cur_viol), n_base, " · 옮김 대응 %d" % vd.moved if vd.moved else ""))
    else:
        items = [describe(u, None) for u in vd.new] + [describe(u, b) for u, b in vd.grew]
        T.chk(False, "%s %s — 새 위반 %d · 커짐 %d · 규칙: %s · 고치는 법: %s · 예: %s" % (
            k, title, len(vd.new), len(vd.grew), rule, fix, " | ".join(items[:3])), items[:40])
    stale_note(k, len(vd.stale))


def stale_note(k, n):
    if not n:
        return
    note = "%s 기준선 낮출 수 있음 %d단위(좋아짐·사라짐) — %s --update-lower" % (k, n, SELF_CMD)
    if STALE_FAIL:
        T.chk(False, note + " (TJ_TEST_ARCH_STALE_FAIL=1)")
    else:
        print("안내 " + note, flush=True)


def _hard(group, mx):
    for k, (g, desc) in R.HARD.items():
        if g == group:
            bad = mx.hard.get(k, [])
            T.chk(not bad, "%s %s — 위반 %d" % (k, desc, len(bad)), bad[:40])


def _special(group, mx, by_k):
    if group == "imports":
        print("참고 순환 묶음 %d개(%s) · 지연 import %d(순환 관련 %d · 그 밖 %d)" % (
            len(mx.cycles), "·".join(str(len(c)) for c in mx.cycles) or "0", mx.extra["lazy"]["all"],
            mx.extra["lazy"]["cycle"], mx.extra["lazy"]["other"]), flush=True)
    if group == "contracts":
        base = next((b["v"] for b in by_k.get("contract.types", [])), 0)
        cur = mx.floor["contract.types"]
        T.chk(cur >= base, "contract.types 경계 계약 타입(dataclass·TypedDict·NamedTuple) 수 %d(기준선 %d) — 줄면 실패" % (cur, base))
        stale_note("contract.types", int(cur > base))


def run_group(group, finish=True):
    st = state()
    if st.load_error:
        T.chk(False, "%s: %s" % (group, st.load_error))
        return T.finish() if finish else None
    if st.metrics is None:
        if PUBLIC_LAYOUT:
            T.chk(True, "%s: 공개판 배치 — 규칙·기준선 파일 없음(공개 빌드는 tests/*.py 만 복사) · 건너뜀" % group)
            return T.finish() if finish else None
        T.chk(False, "%s: 규칙 파일 없음 %s · %s" % (group, RULES_PATH, LAYERS_PATH))
        return T.finish() if finish else None
    for e in st.errors:
        T.chk(False, "사실 뽑기 실패 — " + e)
    path = baseline_path(group)
    try:
        lines = R.load_lines(path)
    except ValueError as e:
        T.chk(False, "%s: 기준선을 못 읽음 — %s" % (group, e))
        return T.finish() if finish else None
    if lines is None:
        T.chk(PUBLIC_LAYOUT, "%s: 기준선 없음 %s — 처음 만들기 = %s --init" % (group, os.path.relpath(path, ROOT), SELF_CMD))
        return T.finish() if finish else None
    bad = R.bad_lines(lines) + R.header_problems(group, lines)
    T.chk(not bad, "%s 기준선 줄 모양(머리 줄 _keys = 첫 줄 하나 · 이 묶음 지표 전부 · 개수·크기 v = 0 이상 정수 · 집합 v = 글자 목록 · "
          "NaN 금지) — 틀린 곳 %d" % (R.GROUP_FILE[group], len(bad)), bad[:20])
    by_k = {}
    for ln in lines:
        if ln["k"] != R.KEYS_LINE and R.valid_value(ln["k"], ln.get("v")):
            by_k.setdefault(ln["k"], []).append(ln)
    mx = st.metrics
    for k in R.metrics_of(group):
        if k == "doc.missing" and PUBLIC_LAYOUT:
            T.chk(True, "doc.missing — 공개판 배치는 독스트링을 지워 건너뜀")
            continue
        units = S.fold_units(st.split, k, mx.units.get(k, []), by_k.get(k, []))
        emit(R.compare(k, units, by_k.get(k, []), st.rules, st.allow()), len(by_k.get(k, [])))
    _special(group, mx, by_k)
    _hard(group, mx)
    return T.finish() if finish else None


def layer_table_md(layers):
    tmp = set(layers.get("provisional", []))
    rows = ["| 계층 | 모듈(* = 임시 분류 · 정본 = arch_baseline/layers.json) |", "|---|---|"]
    for i, lay in enumerate(layers["layers"]):
        mods = sorted(m for m, v in layers["modules"].items() if v == lay)
        plan = sorted(m for m, v in layers.get("planned", {}).items() if v == lay)
        cell = " · ".join(m + ("*" if m in tmp else "") for m in mods)
        if plan:
            cell += " · 계획(아직 없음): " + " · ".join(plan)
        rows.append("| %d %s | %s |" % (i, lay, cell))
    return "\n".join(rows)


def arch_md_block(text):
    if LAYER_BEGIN not in text or LAYER_END not in text:
        return None
    return text.split(LAYER_BEGIN, 1)[1].split(LAYER_END, 1)[0].strip("\n")


if __name__ == "__main__":
    sys.modules.setdefault("_arch", sys.modules[__name__])
    import _arch_py_cli
    sys.exit(_arch_py_cli.main(sys.argv[1:]))
