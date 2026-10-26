import json
import os
import time

import _arch as A
import _arch_py_git as G
import _arch_py_ratchet as R
import _arch_split as S


_ACTS = (({"common"}, None, "4막 W2 common 쪼개기(지연 import 3)"),
         ({"xchain_match"}, {"web"}, "4막 W2 xchain_match 디버그 CLI → tools"),
         ({"depaddr", "ex_foreign"}, {"depaddr", "ex_foreign"}, "4막 W2 depaddr↔ex_foreign"),
         ({"review_daily", "sellchart"}, {"review_daily", "sellchart"}, "4막 W4 AI 호출 도우미 분리(review_daily↔sellchart)"),
         ({"pricing", "candles", "hl_spot"}, {"pricing", "candles", "hl_spot"}, "6막 네트워크 한 층(시세↔봉↔HL)"))


def act_of(m, q):
    for src, dst, act in _ACTS:
        if m in src and (dst is None or q in dst):
            return act
    return "4막 W2 순환 끊기(간선별 계획은 그 막 설계 때)"


def _with_acts(lines, old):
    prev = {(ln["k"], ln["m"], ln["q"]): ln.get("a") for ln in old if ln.get("a")}
    for ln in lines:
        a = prev.get((ln["k"], ln["m"], ln["q"]))
        if ln["k"] == "import.cycle_edges":
            ln["a"] = a or act_of(ln["m"], ln["q"])
        elif a:
            ln["a"] = a
    return lines


def _keys_line(group):
    return {"k": R.KEYS_LINE, "m": "*", "q": "*", "v": R.group_keys(group)}


def _current_lines(group, st):
    lines = [_keys_line(group)]
    for k in R.metrics_of(group):
        lines += [R.identity(u) for u in st.metrics.units.get(k, []) if R.violating(k, u["v"], st.rules)]
    if group == "contracts":
        lines.append({"k": "contract.types", "m": "*", "q": "count", "v": st.metrics.floor["contract.types"]})
    return lines


def _tighten(group, st, old):
    by_k, old_keys = {}, None
    for ln in old:
        if ln["k"] == R.KEYS_LINE:
            old_keys = set(ln.get("v") or [])
        else:
            by_k.setdefault(ln["k"], []).append(ln)
    out, refused, changed = [_keys_line(group)], [], []
    if old_keys != set(R.group_keys(group)):
        changed.append("머리 줄 _keys")
    for k in R.metrics_of(group):
        if old_keys is not None and k not in old_keys:
            out += [R.identity(u) for u in st.metrics.units.get(k, []) if R.violating(k, u["v"], st.rules)]
            changed.append("%s 처음 동결" % k)
            continue
        units = S.fold_units(st.split, k, st.metrics.units.get(k, []), by_k.get(k, []))
        vd = R.compare(k, units, by_k.get(k, []), st.rules, st.allow())
        if not vd.ok:
            refused.append("%s(새 %d · 커짐 %d)" % (k, len(vd.new), len(vd.grew)))
            out += by_k.get(k, [])
            continue
        kept = {id(u): b["v"] for u, b, _g in vd.grown}
        heirs = {id(u) for u, _b in vd.succeeded}
        olds = {(b["m"], b["q"]): R.identity(b) for _u, b in vd.succeeded}
        new = [dict(R.identity(u), v=kept.get(id(u), u["v"])) for u in vd.cur_viol
               if id(u) not in heirs and (u["m"], u["q"]) not in olds]
        new += list(olds.values())
        if vd.stale or vd.moved or len(new) != len(by_k.get(k, [])):
            changed.append("%s %d→%d" % (k, len(by_k.get(k, [])), len(new)))
        out += new
    if group == "contracts":
        base = next((b["v"] for b in by_k.get("contract.types", [])), 0)
        cur = st.metrics.floor["contract.types"]
        if cur < base:
            refused.append("contract.types(%d < %d)" % (cur, base))
        elif cur > base:
            changed.append("contract.types %d→%d" % (base, cur))
        out.append({"k": "contract.types", "m": "*", "q": "count", "v": max(cur, base)})
    return _with_acts(out, old), refused, changed


def _grown(st):
    out, failing = {}, []
    for group in R.GROUP_FILE:
        by_k = {}
        for ln in R.load_lines(A.baseline_path(group)) or []:
            if ln["k"] != R.KEYS_LINE and R.valid_value(ln["k"], ln.get("v")):
                by_k.setdefault(ln["k"], []).append(ln)
        for k in R.metrics_of(group):
            if R.SPECS[k][1] != "num" or (k == "doc.missing" and A.PUBLIC_LAYOUT):
                continue
            units = S.fold_units(st.split, k, st.metrics.units.get(k, []), by_k.get(k, []))
            vd = R.compare(k, units, by_k.get(k, []), st.rules, st.allow())
            if not vd.ok:
                failing.append((k, "%s(새 %d · 커짐 %d)" % (k, len(vd.new), len(vd.grew))))
            for u, _b, _g in vd.grown:
                key = (k, u["m"], u["q"])
                out[key] = max(out.get(key, 0), u["v"])
    return out, failing


LIMITS_DOC = ("현재 상한 표 — 기준선(py_*.jsonl)보다 커진 채 허용된 단위의 상한(to = 접을 때 지금 크기 · at = 접은 달). "
              "쓰는 법: python3 tests/_arch.py --fold-growth(성장 사유 표를 접고 비움 · 멱등) · 줄어든 값은 --update-lower 가 내림")


def fold_growth(st, at=None):
    if not st.allow() and not os.path.isfile(A.LIMITS_PATH):
        print("접을 줄 없음(성장 사유 표·현재 상한 표 둘 다 비어 있음)")
        return 0
    grown, failing = _grown(st)
    if failing:
        print("접기 거부 — 래칫 실패 중: %s(코드를 고치거나 성장 사유 줄을 먼저)" % ", ".join(x for _k, x in failing))
        return 1
    rows = R.fold_limits(grown, st.limits, at or time.strftime("%Y-%m"))
    R.dump_limits(A.LIMITS_PATH, rows, LIMITS_DOC)
    R.dump_lines(A.GROWTH_PATH, [])
    print("접음: 성장 사유 줄 %d + 옛 상한 표 줄 %d → 현재 상한 표 %d줄(%s) · 성장 사유 표 비움" % (
        len(st.growth), len(st.limits), len(rows), R.LIMITS_FILE))
    return 0


TARGET_KEYS = ("file.lines", "file.bytes", "func.lines", "class.lines")
TARGETS_DOC = ("축소 목표 표(안내만 · 시험 실패 아님) — 분기마다 --tighten-targets --write 로 지금 크기에서 rate 만큼 줄인 목표를 쓰고, "
               "--tighten-targets 가 목표를 넘는 단위('쪼개야 할 파일')를 출력")


def _target_units(st):
    out = []
    for k in TARGET_KEYS:
        for u in st.metrics.units.get(k, []):
            if R.violating(k, u["v"], st.rules):
                out.append((k, u["m"], u["q"], u["v"], u.get("at") or u["m"]))
    return out


def tighten_targets(st, write=False, rate=0.05, label=None):
    cur = _target_units(st)
    if write:
        rows = [{"k": k, "m": m, "q": q, "from": v, "to": max(R.limit_of(k, st.rules), int(v * (1 - rate)))}
                for k, m, q, v, _at in cur]
        doc = {"_doc": TARGETS_DOC, "label": label or _quarter(), "rate": rate}
        lines = ["  " + json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in sorted(rows, key=lambda r: (r["k"], r["m"], r["q"]))]
        R.write_text(A.TARGETS_PATH, '{"_doc": %s,\n "label": %s,\n "rate": %s,\n "targets": [%s]}\n' % (
            json.dumps(doc["_doc"], ensure_ascii=False), json.dumps(doc["label"]), json.dumps(rate),
            ("\n" + ",\n".join(lines) + "\n ") if lines else ""))
        print("목표 표 씀: %s %d단위(%s · 줄임 %g)" % (R.TARGETS_FILE, len(rows), doc["label"], rate))
    try:
        with open(A.TARGETS_PATH, encoding="utf-8") as f:
            tdoc = R.loads(f.read())
        targets = {(t["k"], t["m"], t["q"]): t["to"] for t in tdoc["targets"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        print("안내 목표 표 없음·못 읽음(%s) — --tighten-targets --write 로 만든다" % e.__class__.__name__)
        return 0
    over = sorted(((v - targets[(k, m, q)], k, m, q, v, targets[(k, m, q)], at) for k, m, q, v, at in cur
                   if (k, m, q) in targets and v > targets[(k, m, q)]), reverse=True)
    files = {}
    for _d, k, m, q, v, t, at in over:
        if k in ("file.lines", "file.bytes"):
            files.setdefault(at, []).append("%s %d → %d" % ("줄" if k == "file.lines" else "바이트", v, t))
    print("쪼개야 할 파일(목표 %s · 파일 %d · 함수·클래스 %d) — 안내만(실패 아님)" % (
        tdoc.get("label", "?"), len(files), sum(1 for x in over if x[1] not in ("file.lines", "file.bytes"))))
    for at, parts in files.items():
        print("- %s %s" % (at, " · ".join(sorted(parts))))
    for _d, k, m, q, v, t, at in [x for x in over if x[1] not in ("file.lines", "file.bytes")][:20]:
        print("  · %s %s %s %d → 목표 %d" % (at, q, k, v, t))
    return 0


def _quarter():
    y, mo = time.localtime()[:2]
    return "%d-Q%d" % (y, (mo - 1) // 3 + 1)


def update_lower(st):
    rc = 0
    grown, failing = _grown(st)
    for group in R.GROUP_FILE:
        path = A.baseline_path(group)
        old = R.load_lines(path)
        if old is None:
            print("%s: 기준선 없음 — --init 먼저" % group)
            rc = 1
            continue
        new, refused, changed = _tighten(group, st, old)
        if refused:
            rc = 1
            print("%s: 거부(늘어남 — 코드를 고치거나 기준 브랜치에서 총괄이) %s" % (group, ", ".join(refused)))
        if changed:
            R.dump_lines(path, new)
            print("%s: 조임 %s" % (group, ", ".join(changed)))
    if st.limits:
        low = R.lower_limits(grown, st.limits, {k for k, _x in failing})
        if low != st.limits:
            R.dump_limits(A.LIMITS_PATH, low, LIMITS_DOC)
            print("%s: 내림 %d줄 → %d줄(줄어든 값만)" % (R.LIMITS_FILE, len(st.limits), len(low)))
    return rc


def init(st, force, base):
    exists = [g for g in R.GROUP_FILE if os.path.exists(A.baseline_path(g))]
    if exists and not force:
        print("기준선이 이미 있음(%s) — 처음 만들기만 하는 명령(--force 는 총괄만 · 늘어난 값까지 받아들임)" % ", ".join(exists))
        return 1
    for group in R.GROUP_FILE:
        old = R.load_lines(A.baseline_path(group)) or []
        R.dump_lines(A.baseline_path(group), _with_acts(_current_lines(group, st), old))
    R.dump_lines(A.GROWTH_PATH, [])
    if os.path.isfile(A.LIMITS_PATH):
        R.dump_limits(A.LIMITS_PATH, [], LIMITS_DOC)
    commit = G.commit_of(A.ROOT, base or "HEAD") or ""
    meta = {"hygiene_base": commit, "_설명": "hygiene_base = 이름·주석 위생의 기준 트리 커밋(이 커밋 src 에 없던 새 9-이름·이력 주석만 실패)"}
    with open(A.META_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    print("기준선 만듦: %s · hygiene_base %s" % (", ".join(R.GROUP_FILE.values()), commit[:12]))
    return 0


def sync_doc(st):
    if not os.path.isfile(A.ARCH_MD):
        print("ARCH.md 없음: " + A.ARCH_MD)
        return 1
    with open(A.ARCH_MD, encoding="utf-8") as f:
        text = f.read()
    if A.arch_md_block(text) is None:
        print("ARCH.md 에 자동 칸 표식이 없음")
        return 1
    head, rest = text.split(A.LAYER_BEGIN, 1)
    tail = rest.split(A.LAYER_END, 1)[1]
    new = head + A.LAYER_BEGIN + "\n" + A.layer_table_md(st.layers) + "\n" + A.LAYER_END + tail
    if new != text:
        with open(A.ARCH_MD, "w", encoding="utf-8") as f:
            f.write(new)
        print("ARCH.md 계층 표 다시 씀")
    else:
        print("ARCH.md 계층 표 = layers.json 그대로")
    return 0


def report(st):
    mx, rules = st.metrics, st.rules
    print("지표(위반 단위 수 · 값 합 · 기준선 줄 수) — 정의 = docs/ARCH.md")
    for group in R.GROUP_FILE:
        base = R.load_lines(A.baseline_path(group)) or []
        for k in R.metrics_of(group):
            viol = [u for u in mx.units.get(k, []) if R.violating(k, u["v"], rules)]
            total = sum(len(u["v"]) if isinstance(u["v"], list) else u["v"] for u in viol)
            print("  %-22s %6d  합 %8d  기준선 %6d   %s" % (k, len(viol), total, sum(1 for b in base if b["k"] == k),
                                                       R.SPECS[k][3]))
    print("  %-22s %6d  (%s)" % ("순환 묶음(참고)", len(mx.cycles), "·".join(str(len(c)) for c in mx.cycles)))
    print("  %-22s %6d" % ("contract.types", mx.floor["contract.types"]))
    for k, bad in sorted(mx.hard.items()):
        print("  굳은 검사 %s 실패 %d" % (k, len(bad)))
    print("참고: " + json.dumps(_reference(st), ensure_ascii=False, indent=1))
    return 0


def split_report(st):
    for group in R.GROUP_FILE:
        by_k = {}
        for ln in R.load_lines(A.baseline_path(group)) or []:
            by_k.setdefault(ln["k"], []).append(ln)
        for k in R.metrics_of(group):
            if k in S.SPLIT_KEYS:
                S.fold_units(st.split, k, st.metrics.units.get(k, []), by_k.get(k, []))
    for line in S.report(st.split):
        print(line)
    bad = {k: v for k, v in st.metrics.hard.items() if k.startswith("split.")}
    for k, v in sorted(bad.items()):
        for x in v:
            print("실패 %s %s" % (k, x))
    print("결과: 분할 굳은 검사 실패 %d" % sum(len(v) for v in bad.values()))
    return 1 if bad else 0


def _reference(st):
    mx, idx = st.metrics, st.index
    funcs = [u for fx in idx.values() if "units" in fx for u in fx["units"] if u["t"] == "f"]
    pub = [u for u in funcs if u["pub"]]
    named = sum(u["na"] for u in pub)
    typed = named - sum(u["unt"] for u in pub)
    ex = dict(mx.extra)
    ex.pop("py310_labels", None)
    return dict(ex, functions=len(funcs), func_over80=sum(1 for u in funcs if u["len"] > 80),
                func_ge80=sum(1 for u in funcs if u["len"] >= 80), public=len(pub),
                public_doc_pct=round(100.0 * sum(1 for u in pub if u["doc"]) / max(1, len(pub)), 1),
                public_arg_hint_pct=round(100.0 * typed / max(1, named), 1), cycles=[len(c) for c in mx.cycles])


def main(argv):
    st = A.state()
    if st.metrics is None:
        print("규칙 파일(py_rules.json·layers.json)이 없음 — 저장소 배치에서 쓰는 명령")
        return 1
    if st.errors and ("--update-lower" in argv or "--init" in argv or "--fold-growth" in argv):
        for e in st.errors:
            print("기준선 갱신 거부 — 소스 분석 실패: " + e)
        print("고칠 것: 위 파일을 고쳐 분석이 되게 한 뒤 다시 실행")
        return 1
    if "--update-lower" in argv:
        return update_lower(st)
    if "--fold-growth" in argv:
        return fold_growth(st)
    if "--tighten-targets" in argv:
        rate = 0.05
        try:
            if "--rate" in argv and argv.index("--rate") + 1 < len(argv):
                rate = float(argv[argv.index("--rate") + 1])
        except ValueError:
            rate = -1.0
        if not 0 < rate < 1:
            print("--rate 는 0 과 1 사이")
            return 2
        return tighten_targets(st, "--write" in argv, rate)
    if "--init" in argv:
        base = argv[argv.index("--base") + 1] if "--base" in argv and argv.index("--base") + 1 < len(argv) else None
        return init(st, "--force" in argv, base)
    if "--sync-doc" in argv:
        return sync_doc(st)
    if "--report" in argv:
        return report(st)
    if "--split-report" in argv:
        return split_report(st)
    print(A.USAGE)
    return 0
