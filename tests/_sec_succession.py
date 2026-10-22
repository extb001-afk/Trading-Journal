from __future__ import annotations

import re
from typing import NamedTuple

TJDOM = "tjdom.js"
TJDOM_PATH = "web/v2/tjdom.js"
SINK_METRICS = ("sink_all", "sink_esc_raw", "sink_raw")
ESC_KINDS = ("bidi", "url_scheme")
CANARY_PREFIX = "esc:%s::" % TJDOM
CSP_DROP = ("img-src https:", "style-src 'unsafe-inline'")
CSP_ADD = ("require-trusted-types-for 'script'", "trusted-types tj-html")
CSP_KEEP = ("default-src 'self'", "script-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
            "form-action 'self'") + CSP_ADD
CSP_MODES = {"csp_weak": "exact", "csp_source": "exact", "csp_ro_weak": "exact", "csp_ro_source": "exact"}
_KNOWN_DIRS = ("default-src", "script-src", "style-src", "font-src", "img-src", "connect-src", "object-src", "base-uri", "form-action",
               "frame-ancestors", "require-trusted-types-for", "trusted-types")
_CONNECT_OK = ("'self'", "https://cdn.jsdelivr.net")
_ENT = ("&amp;", "&lt;", "&gt;", "&quot;")


class Verdict(NamedTuple):
    side: dict
    base: dict
    bad: list
    granted: dict
    dec: list


def _norm(d) -> dict:
    return {k: int(v) for k, v in (d or {}).items() if int(v) > 0}


def _file(k: str) -> str:
    return k.split("::", 1)[0]


def _split(side: dict, base: dict, mine) -> tuple:
    return ({k: v for k, v in side.items() if not mine(k)}, {k: v for k, v in base.items() if not mine(k)},
            {k: v for k, v in side.items() if mine(k)}, {k: v for k, v in base.items() if mine(k)})


def _grow(own_side: dict, own_base: dict) -> tuple:
    return ({k: v for k, v in own_side.items() if v > own_base.get(k, 0)}, sorted(k for k, v in own_base.items() if v > own_side.get(k, 0)))


def _verdict(rest_s, rest_b, own_s, own_b, why) -> Verdict:
    new, dec = _grow(own_s, own_b)
    if new and why:
        return Verdict(rest_s, rest_b, [(k, v, own_b.get(k, 0), why) for k, v in sorted(new.items())], {}, dec)
    return Verdict(rest_s, rest_b, [], new, dec)


def _sink_why(metric: str, own_s: dict, rest_s: dict, base: dict, work: dict) -> str | None:
    w_all = _norm(work.get("sink_all"))
    w_out = sum(v for k, v in w_all.items() if _file(k) != TJDOM)
    w_tj = {k: v for k, v in w_all.items() if _file(k) == TJDOM}
    if w_out:
        return "① 작업 트리 web/v2 의 tjdom.js 밖 싱크 %d(0 이어야)" % w_out
    if rest_s:
        return "① 비교하는 쪽의 tjdom.js 밖 싱크 %d(0 이어야 — 기준선을 --update-lower 로 같이 낮추세요)" % sum(rest_s.values())
    if len(w_tj) != 1 or sum(w_tj.values()) != 1:
        return "② 작업 트리 tjdom.js 싱크 = %s(열쇠 하나 · 값 1 이어야)" % w_tj
    if len(own_s) != 1 or sum(own_s.values()) != 1 or set(own_s) - set(w_tj):
        return "② 비교하는 쪽 tjdom.js 싱크 = %s(작업 트리의 그 열쇠 하나 · 값 1 이어야)" % own_s
    if sum(_norm(base.get(metric)).values()) < 1:
        return "③ 기준의 %s 합계 0 — 옮겨 올 싱크가 없음" % metric
    return None


def _sink(metric, side_all, base_all, work_all) -> Verdict:
    side, base = _norm(side_all.get(metric)), _norm(base_all.get(metric))
    rest_s, rest_b, own_s, own_b = _split(side, base, lambda k: _file(k) == TJDOM)
    return _verdict(rest_s, rest_b, own_s, own_b, _sink_why(metric, own_s, rest_s, base_all, work_all))


def _v2_other(d: dict) -> int:
    return sum(v for k, v in d.items() if k.startswith("web/v2/") and k != TJDOM_PATH)


def _esc_why(side: dict, base: dict, work: dict) -> str | None:
    for nm, d in (("비교하는 쪽", side), ("작업 트리", work)):
        if d.get(TJDOM_PATH, 0) != 1:
            return "%s tjdom.js esc 사본 %d(1 이어야)" % (nm, d.get(TJDOM_PATH, 0))
        if _v2_other(d) >= _v2_other(base):
            return "%s web/v2 의 다른 esc 사본 %d — 기준 %d 보다 줄지 않음(옮김이 아니라 새 사본)" % (nm, _v2_other(d), _v2_other(base))
    if sum(side.values()) > sum(base.values()):
        return "esc 사본 합계 %d → %d 늘어남" % (sum(base.values()), sum(side.values()))
    return None


def _esc(metric, side_all, base_all, work_all) -> Verdict:
    side, base, work = _norm(side_all.get(metric)), _norm(base_all.get(metric)), _norm(work_all.get(metric))
    rest_s, rest_b, own_s, own_b = _split(side, base, lambda k: k == TJDOM_PATH)
    return _verdict(rest_s, rest_b, own_s, own_b, _esc_why(side, base, work))


_TJ_ESC = re.compile(r"esc:%s::esc:([a-z_]+)" % re.escape(TJDOM))
_ESC_KEY = re.compile(r"esc:(.+?)::([^:]+):([a-z_]+)")


def _kinds(d: dict) -> set:
    return {m.group(3) for m in (_ESC_KEY.fullmatch(k) for k in d) if m}


def _canary_why(k: str, side: dict, base: dict, work: dict) -> str | None:
    m = _TJ_ESC.fullmatch(k)
    if not m:
        return "tjdom.js 이스케이프 정의는 esc 하나만(열쇠 꼴 esc:tjdom.js::esc:<종류> · #2·다른 이름 = 표 밖)"
    kind = m.group(1)
    if kind not in ESC_KINDS:
        return "종류 %s 는 승계 대응 표(%s) 밖" % (kind, "·".join(ESC_KINDS))
    gone = [b for b in base if b.startswith("esc:") and not b.startswith(CANARY_PREFIX) and b.endswith(":" + kind)
            and b not in side and b not in work]
    if not gone:
        return "기준의 지운 사본(비교하는 쪽·작업 트리 모두 없음) 중 종류 %s 가 하나도 없음" % kind
    if sum(side.values()) > sum(base.values()):
        return "알려진 구멍 합계 %d → %d 늘어남" % (sum(base.values()), sum(side.values()))
    if len(_kinds(side)) > len(_kinds(base)):
        return "esc 종류 수 %d → %d 늘어남" % (len(_kinds(base)), len(_kinds(side)))
    return None


def _canary(metric, side_all, base_all, work_all) -> Verdict:
    side, base, work = _norm(side_all.get(metric)), _norm(base_all.get(metric)), _norm(work_all.get(metric))
    rest_s, rest_b, own_s, own_b = _split(side, base, lambda k: k.startswith(CANARY_PREFIX))
    new, dec = _grow(own_s, own_b)
    bad, granted = [], {}
    for k, v in sorted(new.items()):
        why = _canary_why(k, side, base, work)
        if why:
            bad.append((k, v, own_b.get(k, 0), why))
        else:
            granted[k] = v
    return Verdict(rest_s, rest_b, bad, granted, dec)


def strict_sources(enforce_sources) -> set:
    return (set(enforce_sources) - set(CSP_DROP)) | set(CSP_ADD)


WHOLE = "(정책 전체)"


def _whole(v: Verdict, why: str | None, side: dict, base: dict) -> Verdict:
    if why and not v.bad:
        return v._replace(bad=[(WHOLE, sum(side.values()), sum(base.values()), why)], granted={})
    return v


def _csp_src(metric, side_all, base_all, work_all) -> Verdict:
    side, base, work = _norm(side_all.get(metric)), _norm(base_all.get(metric)), _norm(work_all.get(metric))
    rest_s, rest_b, own_s, own_b = _split(side, base, lambda k: k in CSP_ADD)
    half = [nm for nm, d in (("비교하는 쪽", side), ("작업 트리", work)) if 0 < sum(x in d for x in CSP_ADD) < len(CSP_ADD)]
    lack = [nm for nm, d in (("비교하는 쪽", side), ("작업 트리", work)) if not all(x in d for x in CSP_ADD)]
    pair = "Trusted Types 두 줄(%s)은 함께" % " · ".join(CSP_ADD)
    v = _verdict(rest_s, rest_b, own_s, own_b, ("%s — %s 에 다 있지 않음" % (pair, "·".join(lack))) if lack else None)
    return _whole(v, ("%s — %s 에 한 줄만" % (pair, "·".join(half))) if half else None, own_s, own_b)


def _ro_why(rs: dict, strict: set) -> str | None:
    out = sorted(set(rs) - strict)
    if out:
        return "엄격안 밖 출처 %s(표 밖·약화)" % out
    lack = [x for x in CSP_KEEP if x not in rs]
    if lack:
        return "엄격안 필수 줄 빠짐 %s" % lack
    return None


def _csp_ro(metric, side_all, base_all, work_all) -> Verdict:
    side, base, work = _norm(side_all.get(metric)), _norm(base_all.get(metric)), _norm(work_all.get(metric))
    strict = strict_sources(_norm(base_all.get("csp_source")))
    why = None
    for nm, d in (("비교하는 쪽", side), ("작업 트리", work)):
        w = _ro_why(d, strict) if d else None
        if w:
            why = "Report-Only %s — %s" % (nm, w)
            break
    return _whole(_verdict({}, {}, side, base, why), why, side, base)


_RULES = {("xss", m): _sink for m in SINK_METRICS}
_RULES.update({("xss_canary", "known_hole"): _canary, ("xss_csp", "csp_source"): _csp_src, ("xss_csp", "csp_ro_source"): _csp_ro,
               ("js_esc", "n"): _esc})


def judge(name: str, metric: str, side: dict, base: dict, work: dict) -> Verdict:
    rule = _RULES.get((name, metric))
    if rule is None:
        return Verdict(_norm(side.get(metric)), _norm(base.get(metric)), [], {}, [])
    return rule(metric, side, base, work)


def csp_dirs(policy: str) -> tuple[dict, set]:
    out, dup = {}, set()
    for part in policy.split(";"):
        w = part.split()
        if w:
            nm = w[0].lower()
            if nm in out:
                dup.add(nm)
            else:
                out[nm] = w[1:]
    return out, dup


def _policy_metrics(policy: str) -> tuple[dict, dict]:
    dirs, _dup = csp_dirs(policy)
    weak = set()
    if "'unsafe-inline'" in dirs.get("style-src", []):
        weak.add("style-src 'unsafe-inline'")
    if "https:" in dirs.get("img-src", []):
        weak.add("img-src https:(모든 https 이미지)")
    if "require-trusted-types-for" not in dirs:
        weak.add("Trusted Types 없음(require-trusted-types-for)")
    for d in dirs:
        if d not in _KNOWN_DIRS:
            weak.add("모르는 지시어 %s" % d)
    for x in dirs.get("connect-src", []):
        if x not in _CONNECT_OK:
            weak.add("connect-src %s" % x)
    srcs = {"%s %s" % (d, x): 1 for d, v in dirs.items() for x in v if not (d == "script-src" and x.startswith("'sha256-"))}
    return {k: 1 for k in weak}, srcs


def csp_metrics(enforce: str, report_only: str | None = None) -> dict:
    weak, srcs = _policy_metrics(enforce)
    out = {"csp_weak": weak, "csp_source": srcs}
    if report_only is not None:
        out["csp_ro_weak"], out["csp_ro_source"] = _policy_metrics(report_only)
    return out


def tjdom_esc_problems(defs: list, n_amp: int) -> list:
    out = []
    if len(defs) != 1:
        out.append("tjdom.js esc 정의 %d개(하나여야 — const/let/var/function esc 꼴)" % len(defs))
    for d in defs:
        lack = [e for e in _ENT if e not in d]
        if lack:
            out.append("tjdom.js esc 정의에 엔티티 글자 %s 없음(표기를 바꿔 셈을 피하는 꼴 금지): %s" % (lack, d[:100]))
    if n_amp != 1:
        out.append("js_esc web/v2/tjdom.js = %d(1 이어야 — '&amp;' 리터럴 하나)" % n_amp)
    return out
