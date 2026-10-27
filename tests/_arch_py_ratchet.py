import json
import os
import re
import tempfile

import _arch_py_defs as D

GROWTH_FILE = "py_growth.jsonl"
LIMITS_FILE = "py_limits_current.json"
TARGETS_FILE = "py_targets.json"
LIMITS_WHY = ("기준선 동결 — 기준선보다 커진 채 허용된 단위(성장 사유 표의 줄)를 접은 달(at)의 지금 크기로 상한 고정: "
              "이보다 커지면 실패 · 줄면 --update-lower 가 내림 · 새로 커질 일은 py_growth.jsonl 에 실제 사유와 함께")
_AT = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")
KEYS_LINE = "_keys"


WHY_MIN = 20
_WHY_FILLER = re.compile(r"허용|성장|allow(?:ed)?|[\W\d_]+", re.I)


def why_ok(why) -> bool:
    return isinstance(why, str) and len(why.strip()) >= WHY_MIN and len(_WHY_FILLER.sub("", why)) >= 4
GROUP_FILE = {"size": "py_size.jsonl", "layers": "py_layers.jsonl", "imports": "py_imports.jsonl",
              "api": "py_api.jsonl", "ledger": "py_ledger.jsonl", "except": "py_except.jsonl",
              "contracts": "py_contracts.jsonl", "compat": "py_compat.jsonl"}
_FIX_SPLIT = "책임별로 작은 모듈로 나눠라(src 한 층 · 새 모듈은 layers.json 에 한 줄 등록)"
SPECS = {
    "file.lines": ("size", "num", "m", "파일 줄 수", "파일 ≤ 600줄(하드 800)", _FIX_SPLIT),
    "file.bytes": ("size", "num", "m", "파일 바이트", "파일 ≤ 48KB(하드 64KiB)", _FIX_SPLIT),
    "func.lines": ("size", "num", "f", "함수 줄 수(def 줄~끝 · 안쪽 def 포함)", "함수 ≤ 60줄(하드 80)",
                   "작은 도우미 함수로 나눠라(안쪽 def 로 쪼개도 바깥 함수 줄 수는 그대로 셈)"),
    "func.args": ("size", "num", "f", "인자 수(self·cls 빼고 · *args·**kw 각 1)", "인자 ≤ 7",
                  "관련 인자를 dataclass 로 묶거나 호출 쪽 묶음 객체를 넘겨라"),
    "func.depth": ("size", "num", "f", "제어 중첩 깊이(if·for·while·try·with)", "중첩 ≤ 4",
                   "일찍 돌려주기(guard clause)·도우미 함수로 펴라"),
    "stage.reload": ("size", "num", "f", "빌드 단계 이름표 조건부 재적재 `if \"x\" in _bs9: x = _bs9[\"x\"]` 수(함수 자기 범위)",
                     "늘리지 말 것(5막 S1 — 단계 입력은 머리 풀기 · 증명된 것만 남김)",
                     "늘 묶이는 입력은 머리 풀기로 · 죽은 쌍은 지워라(단계 재적재 정리 도구 bs9_reload --report·--apply)"),
    "class.lines": ("size", "num", "c", "클래스 줄 수", "클래스 ≤ 400줄", "역할별 클래스로 나눠라(새 믹스인 금지)"),
    "class.methods": ("size", "num", "c", "클래스 메서드 수", "메서드 ≤ 25", "역할별 클래스로 나눠라(새 믹스인 금지)"),
    "class.mixin_bases": ("size", "num", "c", "…Mixin 부모 수", "믹스인 상속 늘리지 말 것", "합성(역할 객체를 속성으로)으로"),
    "mixin.defs": ("size", "num", "c", "…Mixin 클래스 정의", "새 믹스인 금지", "역할 객체(보통 클래스)로 나눠라"),
    "module.reexport_only": ("size", "num", "m", "재수출 전용 모듈(import·별칭만)", "새로 만들지 말 것",
                             "쓰는 쪽 import 를 정의 모듈로 바꾸고 껍데기 모듈을 지워라"),
    "layer.violations": ("layers", "num", "e", "계층 위반 간선(모듈 → 더 위 계층 모듈 import)",
                         "아래 계층만 import(같은 계층 가능 · 표 = layers.json · 설명 = docs/ARCH.md)",
                         "의존 방향을 뒤집거나(인자·콜백으로 받기) 기능을 맞는 계층 모듈로 옮겨라"),
    "import.cycle_edges": ("imports", "num", "x", "순환 간선(같은 순환 묶음 안의 import 간선 · 함수 안 import 포함)",
                           "새 간선 금지(허용 = 기준선 간선 목록 · 'a' = 끊을 담당 막)",
                           "새 import 를 빼거나 의존 방향을 뒤집어라(함수 안 import 로 숨겨도 순환으로 셈)"),
    "import.lazy": ("imports", "num", "s", "함수 안 import(src 모듈)", "늘리지 말 것(순환 회피용 0 · 나머지는 이유)",
                    "모듈 맨 위 import 로(순환이면 순환부터 끊어라)"),
    "import.star": ("imports", "num", "s", "import *", "금지", "쓰는 이름을 적어 import"),
    "import.private": ("imports", "num", "n", "남의 _이름 import·접근((정의 모듈, 이름)별 자리 수)", "늘리지 말 것",
                       "정의 모듈에서 공개 이름(밑줄 없음)으로 내보내라"),
    "import.reexport": ("imports", "num", "n", "호환 재수출(모듈 수준 from import 인데 그 모듈에서 안 씀)",
                        "새로 만들지 말 것", "쓰는 쪽이 정의 모듈에서 바로 import(안 쓰는 import 는 지움)"),
    "api.urlopen": ("api", "num", "s", "직접 HTTP(urlopen·build_opener·Request)", "net_* 모듈에서만",
                    "공용 HTTP 도우미를 불러라(6막 뒤 net_*)"),
    "api.hmac": ("api", "num", "s", "HMAC 서명(hmac.new·digest·HMAC)", "ex_sign*·login_auth 에서만", "서명 도우미를 불러라"),
    "api.sqlite": ("api", "num", "s", "sqlite3.connect", "db·db_* 에서만", "db 의 연결 도우미를 불러라"),
    "api.replace": ("api", "num", "s", "os.replace·os.rename", "fsio·fsio_* 에서만(이유 있는 허용 = py_rules.json allow_units)",
                    "fsio 원자 쓰기 도우미를 불러라(옆으로 치우기·원장 교체는 allow_units 에 이유와 함께)"),
    "api.kst": ("api", "num", "s", "KST 직접 정의(timedelta(hours=9)·ZoneInfo('Asia/Seoul')·32400·9*3600)",
                "timeutil·timeutil_* 에서만", "이미 있는 KST 상수·도우미를 import(4막 뒤 timeutil)"),
    "api.statepath": ("api", "num", "s", "state 경로 직접 조립(os.path.join(STATE_DIR, …)·STATE_DIR + …·f'{STATE_DIR}')",
                      "paths·paths_* 에서만", "이미 있는 경로 상수·도우미를 불러라(4막 뒤 paths 등록부)"),
    "copy.num": ("api", "num", "s", "숫자 파서 사본(작은 float·int·Decimal 변환 함수)", "num·num_* 하나만", "있는 파서를 import"),
    "copy.atomic": ("api", "num", "s", "원자 쓰기 사본(쓰기 열기 + os.replace 하는 함수)", "fsio·fsio_* 하나만",
                    "fsio 도우미를 불러라"),
    "copy.statepath": ("api", "num", "s", "state 경로 도우미 사본(state 경로를 돌려주는 함수)", "paths·paths_* 하나만",
                       "있는 경로 도우미를 불러라"),
    "const.1384": ("api", "num", "s", "고정 환율 1384 리터럴", "상수 하나(서버 → 화면)", "acct_norm.DEFAULT_KRW_USD 를 써라"),
    "ledger.write": ("ledger", "set", "s", "원장 표 쓰기 SQL('표:동작' 집합)", "지금 쓰는 곳 밖에 새로 금지",
                     "원장 계층 함수(core_post 등)를 불러라 — 새 원장 쓰기 자리는 총괄 검토 뒤 기준선에"),
    "except.broad": ("except", "num", "s", "넓은 except(Exception·BaseException·맨 except — 다시 던짐·이유 코드 빼고)",
                     "늘리지 말 것", "잡을 예외를 좁혀라 — 꼭 넓게면 `# noqa: BLE001 [이유코드] 설명`(닫힌 목록 = docs/ARCH.md)"),
    "except.money_nocg": ("except", "num", "s", "돈 경로 모듈의 삼키는 넓은 except 인데 calcguard 기록 없음", "0 목표 · 늘리지 말 것",
                          "처리기에 calcguard.swallowed('자리 이름', e) 를 넣어라(이유 코드로는 안 빠짐)"),
    "except.swallow_pass": ("except", "num", "x", "calcguard.swallowed(…) 다음이 pass 뿐인 처리기(저장소 전체 합 · 세션31 요청서 #2-3)",
                            "늘리지 말 것", "삼킨 뒤 할 일을 적어라 — 계산 경로면 calcguard.row_err 로 행 표식 · 데이터 이상을 일부러 넘기면 "
                            "swallowed(…, expected=True) 와 처리(대체값·건너뜀 기록)를 같이"),
    "doc.missing": ("contracts", "num", "f", "공개 함수 독스트링 없음", "공개 함수 = 한 줄 계약",
                    "무엇을 받아 무엇을 돌려주나 한 줄 독스트링"),
    "hint.untyped": ("contracts", "num", "f", "공개 함수 인자 타입 힌트 없음(self·cls·*args·**kw 빼고)", "새 공개 함수는 전부",
                     "인자에 타입 힌트(from __future__ import annotations 로 3.9 안전)"),
    "cfg.literal": ("contracts", "num", "s", "cfg 리터럴 접근(cfg.get('키')·cfg['키'] — 받는 식에 cfg)", "늘리지 말 것(10막 설정 스키마)",
                    "이미 읽은 값을 인자로 넘기거나 있는 접근자를 불러라"),
    "env.undocumented": ("contracts", "num", "x", "문서 없는 TJ_* 이름", "README·.env.example·docs 에 적을 것",
                         "README 환경 변수 표 또는 .env.example 에 한 줄"),
    "compat.py310": ("compat", "num", "s", "파이썬 3.10+ 문법·API(3.9 하한)", "README·CI 하한 = 3.9",
                     "3.9 에서 도는 꼴로(Optional[X]·from __future__ import annotations·zip 길이 확인 등)"),
}
SPECIAL = {"contract.types": "contracts"}
HARD = {
    "src.subdirs": ("size", "src 안 새 하위 폴더 금지(배포 도구가 src/ 한 층만 봄 · 이미 있는 brokers 만 예외)"),
    "layer.unassigned": ("layers", "모든 src 모듈은 계층 표에 등록"),
    "ref.modset": ("api", "buildproc MODSET/MODDICT 의 (모듈, 이름)이 그 모듈에 정의돼 있어야 함"),
    "ledger.tables": ("ledger", "db 스키마의 표는 전부 원장 표 목록에"),
    "except.badcode": ("except", "이유 코드는 닫힌 목록(py_rules.json except_reasons · docs/ARCH.md)에서만"),
    "growth.invalid": ("size", "성장 사유 표(py_growth.jsonl) 줄 = 아는 지표 k · 모듈 m · 이름 q · 허용 상한 to(0 이상 정수) · 사유 why(20자 이상 · "
                               "'허용'·'성장' 같은 빈말만이면 거부) · 커밋 commit(글자) — 틀린 줄이 하나라도 있으면 표 전체를 안 씀"),
    "rules.invalid": ("size", "규칙 파일 한도(limits) = 0 이상 정수(NaN·글자 금지)"),
    "doc.misplaced": ("contracts", "문자열 단독 문장은 독스트링 자리(모듈·클래스·함수 몸통 첫 문장)에만 — 그 밖 자리는 공개 빌드(주석·독스트링 제거)가 "
                                   "지워 비공개·공개 몸통 지문이 달라짐 · 고치는 법: 함수 맨 앞 독스트링으로 옮기거나 # 주석으로"),
}
_ORDER = ("k", "m", "q", "f", "h", "v", "a")
_LEVELS = {"f": ("mq", "h", "q", "f", "b"), "c": ("mq", "h", "q", "b"), "b": ("mq", "q"), "m": ("mq",),
           "n": ("mq", "q"), "e": ("mq", "f"), "x": ("mq",)}


def group_of(k):
    return SPECS[k][0] if k in SPECS else SPECIAL.get(k) or HARD[k][0]


def metrics_of(group):
    return [k for k, s in SPECS.items() if s[0] == group]


def unit_type(k, q):
    t = SPECS[k][2]
    if t != "s":
        return t
    return "m" if q == D.MODULE_Q else ("b" if q.endswith(D.BODY_SUFFIX) else "f")


def limit_of(k, rules):
    return rules.get("limits", {}).get(k, 0)


def violating(k, v, rules):
    return bool(v) if SPECS[k][1] == "set" else v > limit_of(k, rules)


def _rank(v):
    return len(v) if isinstance(v, list) else v


def worse(k, cur, base):
    if SPECS[k][1] == "set":
        return not set(cur) <= set(base)
    return cur > base


def better(k, cur, base):
    if SPECS[k][1] == "set":
        return set(cur) < set(base)
    return cur < base


def no_nan(name):
    raise ValueError("NaN·Infinity 금지(%s)" % name)


def loads(text):
    return json.loads(text, parse_constant=no_nan)


def load_lines(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return parse_lines(f.read(), path)


def parse_lines(text, where):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line:
            try:
                d = loads(line)
            except ValueError as e:
                raise ValueError("%s:%d JSON 이 아님(%s)" % (where, n, e)) from e
            if not isinstance(d, dict) or not isinstance(d.get("k"), str):
                raise ValueError("%s:%d 줄 모양이 아님(k 없음)" % (where, n))
            out.append(d)
    return out


def valid_value(k, v):
    if k in SPECS and SPECS[k][1] == "set":
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def group_keys(group):
    return sorted([k for k, sp in SPECS.items() if sp[0] == group] + [k for k, g in SPECIAL.items() if g == group])


def header_problems(group, lines):
    heads = [ln for ln in lines if ln.get("k") == KEYS_LINE]
    if len(heads) != 1 or not lines or lines[0] is not heads[0]:
        return ["_keys 머리 줄은 첫 줄 하나여야 함(%d개)" % len(heads)]
    if heads[0].get("v") != group_keys(group):
        return ["_keys 머리 줄 = %s 이어야 함(지금 %s) — %s 지표가 바뀌었으면 --update-lower" % (
            group_keys(group), heads[0].get("v"), group)]
    return []


def bad_lines(lines):
    out = []
    for ln in lines:
        k = ln.get("k")
        if k == KEYS_LINE:
            if not isinstance(ln.get("v"), list) or not all(isinstance(x, str) for x in ln["v"]):
                out.append("_keys 머리 줄 v 가 글자 목록이 아님")
        elif not isinstance(ln.get("m"), str) or not isinstance(ln.get("q"), str) or not valid_value(k, ln.get("v")):
            out.append("%s 줄 모양 틀림 %s" % (k, json.dumps(ln, ensure_ascii=False)[:120]))
    return out


def _sort_key(d):
    return tuple(json.dumps(d.get(x), ensure_ascii=False, sort_keys=True) for x in _ORDER)


def dump_lines(path, lines):
    rows = []
    for d in sorted(lines, key=_sort_key):
        rows.append(json.dumps({x: d[x] for x in _ORDER if x in d and d[x] not in (None, "")},
                               ensure_ascii=False, separators=(",", ":")))
    write_text(path, "\n".join(rows) + ("\n" if rows else ""))


def identity(u):
    return {x: u[x] for x in _ORDER if x in u and u[x] not in (None, "")}


def _key(u, level):
    if level == "mq":
        return (u["m"], u["q"])
    if level == "h":
        return u.get("h")
    if level == "q":
        return u["q"]
    path = u.get("f") or u["q"]
    return path if level == "f" else path.rsplit(".", 1)[-1]


def match(base, cur):
    pairs, taken = {}, set()
    for level in ("mq", "h", "q", "f", "b"):
        groups = {}
        for i, u in enumerate(base):
            if i not in pairs and level in _LEVELS[u["t"]]:
                k = _key(u, level)
                if k is not None:
                    groups.setdefault((u["t"], k), ([], []))[0].append(i)
        if not groups:
            continue
        for j, u in enumerate(cur):
            if j not in taken and level in _LEVELS[u["t"]]:
                k = _key(u, level)
                g = groups.get((u["t"], k)) if k is not None else None
                if g is not None:
                    g[1].append(j)
        for bi, cj in groups.values():
            for i, j in _pair_group(base, cur, bi, cj):
                pairs[i] = j
                taken.add(j)
    return pairs


def _bare(u):
    return (u.get("f") or u["q"]).rsplit(".", 1)[-1]


def _pair_group(base, cur, bi, cj):
    out, free_c = [], list(cj)
    for same_name in (True, False):
        for i in sorted(bi, key=lambda x: _rank(base[x]["v"]), reverse=True):
            h = base[i].get("h")
            same = [x for x in free_c if h and cur[x].get("h") == h and (not same_name or _bare(cur[x]) == _bare(base[i]))]
            if same:
                j = max(same, key=lambda x: _rank(cur[x]["v"]))
                out.append((i, j))
                free_c.remove(j)
                bi = [x for x in bi if x != i]
    bi = sorted(bi, key=lambda i: _rank(base[i]["v"]), reverse=True)
    free_c.sort(key=lambda j: _rank(cur[j]["v"]), reverse=True)
    return out + list(zip(bi, free_c))


class Verdict:

    def __init__(self, k):
        self.k, self.new, self.grew, self.grown, self.stale, self.cur_viol, self.moved = k, [], [], [], [], [], 0
        self.succeeded = []

    @property
    def ok(self):
        return not self.new and not self.grew


def growth_allows(growth, k, u):
    for g in growth:
        if g.get("k") == k and g.get("m") == u["m"] and g.get("q") == u["q"] and isinstance(g.get("to"), int) \
                and not isinstance(u["v"], list) and u["v"] <= g["to"]:
            return g
    return None


def parse_limits(text):
    try:
        doc = loads(text)
    except ValueError as e:
        return [], ["%s JSON 이 아님(%s)" % (LIMITS_FILE, e)]
    rows = doc.get("limits") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return [], ["%s 의 limits 가 목록이 아님" % LIMITS_FILE]
    bad, seen = [], set()
    for e in rows:
        ok = isinstance(e, dict) and e.get("k") in SPECS and SPECS[e["k"]][1] == "num" \
            and all(isinstance(e.get(x), str) and e[x].strip() for x in ("m", "q")) \
            and isinstance(e.get("to"), int) and not isinstance(e.get("to"), bool) and e["to"] >= 0 \
            and isinstance(e.get("at"), str) and bool(_AT.match(e["at"])) and set(e) <= {"k", "m", "q", "to", "at"}
        key = (e.get("k"), e.get("m"), e.get("q")) if isinstance(e, dict) else None
        if not ok or key in seen:
            bad.append("%s 줄 %s %s" % (LIMITS_FILE, "겹침" if ok else "모양 틀림", json.dumps(e, ensure_ascii=False)[:140]))
        seen.add(key)
    return (rows if not bad else []), bad


def limit_rows(rows):
    return [{"k": e["k"], "m": e["m"], "q": e["q"], "to": e["to"], "why": "%s 기준선 동결(%s)" % (e["at"], LIMITS_FILE),
             "commit": LIMITS_FILE} for e in rows]


def fold_limits(grown, old, at):
    prev = {(e["k"], e["m"], e["q"]): e for e in old}
    out = []
    for key in sorted(grown):
        p = prev.get(key)
        out.append({"k": key[0], "m": key[1], "q": key[2], "to": grown[key],
                    "at": p["at"] if p is not None and grown[key] <= p["to"] else at})
    return out


def lower_limits(grown, old, keep_k=()):
    out = []
    for e in old:
        key = (e["k"], e["m"], e["q"])
        if e["k"] in keep_k:
            out.append(e)
        elif key in grown:
            out.append(dict(e, to=min(e["to"], grown[key])))
    return out


def dump_limits(path, rows, doc):
    lines = ["  " + json.dumps({x: e[x] for x in ("k", "m", "q", "to", "at")}, ensure_ascii=False, separators=(",", ":"))
             for e in sorted(rows, key=lambda e: (e["k"], e["m"], e["q"]))]
    write_text(path, '{"_doc": %s,\n "why": %s,\n "limits": [%s]}\n' % (
        json.dumps(doc, ensure_ascii=False), json.dumps(LIMITS_WHY, ensure_ascii=False),
        ("\n" + ",\n".join(lines) + "\n ") if lines else ""))


def write_text(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_arch_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


_WHY_CARDS = ("거대 함수 단계 추출(요청서 #9) — _build_cards 몸통을 같은 파일 안 단계 메서드 _cards_* 7개로 그대로 옮김(공유 지역 = cst) · "
              "줄 수 = 옛 함수 예산 안(합) · 중첩 깊이 = 옛 함수 값 이하(최대) · cfg 리터럴·함수 안 import 는 자리만 옮김(합 무변)")
_WHY_DAILY = ("거대 함수 단계 추출(요청서 #9) — _daily_series 몸통을 같은 파일 안 단계 메서드 _ds_* 5개로 그대로 옮김(공유 지역 = dct) · "
              "줄 수 = 옛 함수 예산 안(합) · 중첩 깊이 = 옛 함수 값 이하(최대)")
_WHY_REPLAY = ("거대 함수 단계 추출(지시서 #3 · 세션31) — _replay_main 본 루프 뒤 후처리 몸통을 같은 파일 안 모듈 함수 _pos_* 7개로, 본 루프 행 프롤로그를"
               " _row_prologue 로 글자 그대로 옮김(구간마다 입력 = 묶기 전에 읽는 앞 이름 · 출력 = 뒤 구간·결과가 읽는 이름) · 줄 수 = 옛 함수 예산 안(합) · "
               "중첩 깊이 = 옛 함수 값 이하(최대) · cfg 리터럴은 자리만 옮김(합 무변)")
_WHY_REPLAY_RUN = ("거대 함수 단계 추출(지시서 #3 · 세션31 단계 4) — _replay_main 안 중첩 분기 함수를 ReplayRun 메서드로 몸통 그대로 옮김(nonlocal 줄만 지움 · "
                   "행을 넘어 사는 상태 없음 확인) — 줄 수·깊이는 옛 중첩 함수 단위와 이름 짝(맨 끝 이름) · 이 줄 = 옛 함수의 9-이름 승계(이름 위생)")
SUCCESSION = (
    ("class.mixin_bases", ("core", "Core"), ("core_svc", "ExfService"),
     "9-1 ExfService 합성(9막 설계 문서 '래칫 영향 예측' class.mixin_bases 줄 = 9막 승계 표) — Core 바탕에서 뺀 EXF 믹스인 4개가 "
     "ExfService 바탕으로 옮김(Core 16 → 12 · 합 16 무변)"),
    ("cfg.literal", ("core_exf", "ExfMixin.settle_planner"), ("core_svc", "exf_settle_planner"),
     "9-1 정착 계획기 ExfMixin.settle_planner → core_svc.exf_settle_planner(읽기 전용 계획기 · 같은 cfg 리터럴 2 · 옛 메서드는 지움)"),
    ("class.mixin_bases", ("core", "Core"), ("core_svc", "ReconService"),
     "9-2 ReconService 합성(9막 설계 문서 '래칫 영향 예측' class.mixin_bases 줄 = 9막 승계 표) — Core 바탕에서 뺀 RECON 믹스인 2개"
     "(ReconMixin·ProvMixin)가 ReconService 바탕으로 옮김(Core 12 → 10 · Core 10 + ExfService 4 + ReconService 2 = 16 무변)"),
    ("class.mixin_bases", ("core", "Core"), ("core_svc", "PriceService"),
     "9-3 PriceService 합성(9막 설계 문서 '래칫 영향 예측' class.mixin_bases 줄 = 9막 승계 표) — Core 바탕에서 뺀 PRICING 믹스인 1개"
     "(PricingMixin)가 PriceService 바탕으로 옮김(Core 10 → 9 · Core 9 + ExfService 4 + ReconService 2 + PriceService 1 = 16 무변)"),
    ("except.broad", ("core", "Core.run"), ("migrate", "startup"),
     "9-6 시작 1회 변환 3 자리(Core.run 의 try·calcguard·rollback·로그 세 벌) → migrate.startup 의 등록부 차례 한 벌(Core.run 23 → 20 · "
     "startup 1 · 합 21 ≤ 23 · 위치 글·로그 글은 등록부 칸 그대로)"),
    ("import.lazy", ("http_route", "RouteMixin.do_POST"), ("http_post_prefs", "post_wallet_alias"),
     "10-3 do_POST 사슬 몸통 → http_post_prefs 최상위 함수(10막 설계 문서 6장 · '래칫 영향 예측' import.lazy 줄 = 단위 이동 승계) — "
     "지갑 별명 몸통의 함수 안 import chain_registry 한 자리가 몸통과 같이 옮김(do_POST 1 → 0 · post_wallet_alias 1 · 합 1 무변)"),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_risk"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_hold_prep"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_holdings"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_extra"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_prov_events"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_positions"), _WHY_CARDS),
    ("func.lines", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_daily_gates"), _WHY_CARDS),
    ("func.lines", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_prep"), _WHY_DAILY),
    ("func.lines", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_rewind"), _WHY_DAILY),
    ("func.lines", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_fixups"), _WHY_DAILY),
    ("func.lines", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_days"), _WHY_DAILY),
    ("func.lines", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_save"), _WHY_DAILY),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_risk"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_hold_prep"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_holdings"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_extra"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_prov_events"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_positions"), _WHY_CARDS),
    ("func.depth", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_daily_gates"), _WHY_CARDS),
    ("func.depth", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_prep"), _WHY_DAILY),
    ("func.depth", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_rewind"), _WHY_DAILY),
    ("func.depth", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_fixups"), _WHY_DAILY),
    ("func.depth", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_days"), _WHY_DAILY),
    ("func.depth", ("view_daily", "DailyMixin._daily_series"), ("view_daily", "DailyMixin._ds_save"), _WHY_DAILY),
    ("cfg.literal", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_risk"), _WHY_CARDS),
    ("cfg.literal", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_extra"), _WHY_CARDS),
    ("import.lazy", ("view_b_cards", "CardsMixin._build_cards"), ("view_b_cards", "CardsMixin._cards_extra"), _WHY_CARDS),
    ("func.depth", ("view_b_replay", "ReplayMixin._replay_main"), ("view_b_replay", "_pos_ex_pending"), _WHY_REPLAY),
    ("cfg.literal", ("view_b_replay", "ReplayMixin._replay_main"), ("view_b_replay", "_pos_prov"), _WHY_REPLAY),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main"), ("view_b_replay", "_row_prologue"), _WHY_REPLAY),
    ("func.depth", ("view_b_replay", "ReplayMixin._replay_main"), ("view_b_replay", "ReplayRun._after_exf_fee"), _WHY_REPLAY_RUN),
    ("class.lines", ("view_b_replay", "ReplayMixin"), ("view_b_replay", "ReplayRun"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_stake_reward"), ("view_b_replay", "ReplayRun._h_stake_reward"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_gas_exf_wd_fee"), ("view_b_replay", "ReplayRun._h_gas_exf_wd_fee"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_gas"), ("view_b_replay", "ReplayRun._h_gas"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_opening"), ("view_b_replay", "ReplayRun._h_opening"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_ex_deposit"), ("view_b_replay", "ReplayRun._h_ex_deposit"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_exf_deposit"), ("view_b_replay", "ReplayRun._h_exf_deposit"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_exf_fee"), ("view_b_replay", "ReplayRun._h_exf_fee"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_move"), ("view_b_replay", "ReplayRun._h_move"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_acq"), ("view_b_replay", "ReplayRun._h_acq"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._stable_bridge_in"), ("view_b_replay", "ReplayRun._stable_bridge_in"), _WHY_REPLAY_RUN),
    ("func.lines", ("view_b_replay", "ReplayMixin._replay_main._h_disp"), ("view_b_replay", "ReplayRun._h_disp"), _WHY_REPLAY_RUN),
)


SUCCESSION_MAX = frozenset({"func.depth"})


def succession_rows(k, table=None):
    if k not in SPECS or SPECS[k][1] != "num":
        return []
    return [(o, n, why) for kk, o, n, why in (SUCCESSION if table is None else table) if kk == k]


def _succeed(k, base, cur_units, pairs, back, rules, table=None):
    rows = succession_rows(k, table)
    if not rows:
        return {}
    at_base = {(b["m"], b["q"]): i for i, b in enumerate(base)}
    at_cur = {}
    for j, u in enumerate(cur_units):
        if j not in back and violating(k, u["v"], rules):
            at_cur.setdefault((u["m"], u["q"]), []).append(j)
    heirs = {}
    for old, new, _why in rows:
        i = at_base.get(old)
        if i is not None:
            heirs.setdefault(i, []).extend(at_cur.get(new, []))
    claims = {}
    for i, js in heirs.items():
        for j in set(js):
            claims[j] = claims.get(j, 0) + 1
    out = {}
    for i, js in heirs.items():
        js = sorted(set(js))
        if not js or any(claims[j] > 1 for j in js):
            continue
        own = pairs.get(i)
        vals = ([cur_units[own]["v"]] if own is not None else []) + [cur_units[j]["v"] for j in js]
        total = max(vals) if k in SUCCESSION_MAX else sum(vals)
        if total <= base[i]["v"]:
            for j in js:
                out[j] = i
    return out


def compare(k, cur_units, base_lines, rules, growth=(), succession=None):
    base = [dict(b, t=unit_type(k, b["q"])) for b in base_lines]
    pairs = match(base, cur_units)
    back = {j: i for i, j in pairs.items()}
    heir = _succeed(k, base, cur_units, pairs, back, rules, succession)
    vd = Verdict(k)
    for j, u in enumerate(cur_units):
        if not violating(k, u["v"], rules):
            continue
        vd.cur_viol.append(u)
        i = back.get(j)
        if i is None and j in heir:
            vd.succeeded.append((u, base[heir[j]]))
            continue
        if i is None:
            vd.new.append(u)
            continue
        b = base[i]
        if (b["m"], b["q"]) != (u["m"], u["q"]):
            vd.moved += 1
        if worse(k, u["v"], b["v"]):
            g = growth_allows(growth, k, u)
            if g is None:
                vd.grew.append((u, b))
            else:
                vd.grown.append((u, b, g))
    for i, b in enumerate(base):
        j = pairs.get(i)
        u = cur_units[j] if j is not None else None
        if u is None or not violating(k, u["v"], rules) or better(k, u["v"], b["v"]):
            vd.stale.append((u, b))
    return vd
