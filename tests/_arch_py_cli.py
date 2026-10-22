import json
import os

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
        vd = R.compare(k, units, by_k.get(k, []), st.rules, st.growth)
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


def update_lower(st):
    rc = 0
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
    if st.errors and ("--update-lower" in argv or "--init" in argv):
        for e in st.errors:
            print("기준선 갱신 거부 — 소스 분석 실패: " + e)
        print("고칠 것: 위 파일을 고쳐 분석이 되게 한 뒤 다시 실행")
        return 1
    if "--update-lower" in argv:
        return update_lower(st)
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
