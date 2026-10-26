import collections
import json
import os
import re

import _arch as A
import _arch_py_defs as D
import _arch_py_git as G
import _arch_py_ratchet as R

T = A.T
_SKIP_REF = ("none", "skip", "-", "0", "off")


def _skip(what, why):
    T.chk(True, "%s 건너뜀 — %s" % (what, why))


def scope_table(index):
    out = {}
    for mod, fx in index.items():
        scopes = fx.get("scopes", {})
        out[(mod, D.MODULE_Q)] = ("m", "", set(scopes.get(D.MODULE_Q, {}).get("b9", [])))
        for u in fx.get("units", []):
            func = u["t"] == "f"
            q = u["q"] if func else u["q"] + D.BODY_SUFFIX
            out[(mod, q)] = ("f" if func else "b", u.get("h", ""), set(scopes.get(q, {}).get("b9", [])))
    return out


def correspond(cur, base):
    pairs = {k: k for k in cur if k in base}
    gone = sorted(k for k in base if k not in cur)
    fresh = sorted(k for k in cur if k not in base)
    by_fp = collections.defaultdict(list)
    for k in gone:
        if base[k][0] != "m" and base[k][1]:
            by_fp[(base[k][0], base[k][1])].append(k)
    for k in fresh:
        if cur[k][0] != "m" and by_fp.get((cur[k][0], cur[k][1])):
            pairs[k] = by_fp[(cur[k][0], cur[k][1])].pop(0)
    used = set(pairs.values())
    left_b, left_c = collections.defaultdict(list), collections.defaultdict(list)
    for k in gone:
        if k not in used and base[k][0] != "m":
            left_b[(base[k][0], k[1])].append(k)
    for k in fresh:
        if k not in pairs and cur[k][0] != "m":
            left_c[(cur[k][0], k[1])].append(k)
    for key, cs in left_c.items():
        if len(cs) == 1 and len(left_b.get(key, ())) == 1:
            pairs[cs[0]] = left_b[key][0]
    return pairs


def _base_inventory(base, prefix, packages):
    name = "hyg4_%s_%s.json" % (base[:12], A._analyzer_version())
    got = A._cache_load(name)
    if got.get("ok"):
        scopes = {(m, q): (t, h, set(b9)) for m, q, t, h, b9 in got["scopes"]}
        return scopes, set(got["hist"]), set(got["dochist"])
    paths = []
    for p in G.tree_paths(A.ROOT, base, prefix + "src"):
        rel = p[len(prefix):] if prefix and p.startswith(prefix) else p
        parts = rel.split("/")
        if rel.endswith(".py") and (len(parts) == 2 or (len(parts) == 3 and parts[1] in packages)):
            paths.append(p)
    texts = G.cat_files(A.ROOT, base, paths)
    if texts is None:
        return None
    items = []
    for p, text in texts.items():
        rel = (p[len(prefix):] if prefix else p)[4:-3]
        pkg = rel.endswith("/__init__")
        items.append((rel[:-len("/__init__")] if pkg else rel.replace("/", "."), text, pkg))
    index = A.facts_for(items, save=False)
    scopes = scope_table({m: fx for m, fx in index.items() if "error" not in fx})
    hist = {h for fx in index.values() for h in fx.get("hist", [])}
    dochist = {h for fx in index.values() for h in fx.get("dochist", [])}
    A._cache_save(name, {"ok": True, "scopes": [[m, q, t, h, sorted(b9)] for (m, q), (t, h, b9) in sorted(scopes.items())],
                         "hist": sorted(hist), "dochist": sorted(dochist)})
    return scopes, hist, dochist


def _locate(mod, needle, word):
    pkg_init = "." not in mod and os.path.isdir(os.path.join(A.SRC, mod))
    path = os.path.join(A.SRC, mod.replace(".", os.sep) + (os.sep + "__init__.py" if pkg_init else ".py"))
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                hit = re.search(r"(?<![\w])" + re.escape(needle) + r"(?![\w])", line) if word else \
                    (needle in " ".join(line.split()))
                if hit:
                    return "%s:%d" % (os.path.relpath(path, A.ROOT), n)
    except OSError:
        pass
    return os.path.relpath(path, A.ROOT)


def owner(key, table):
    mod, q = key
    own = q[:-len(D.BODY_SUFFIX)] if q.endswith(D.BODY_SUFFIX) else q
    parent = own.rpartition(".")[0]
    if not parent:
        return (mod, D.MODULE_Q)
    return (mod, parent) if (mod, parent) in table else (mod, parent + D.BODY_SUFFIX)


def _moved_names(pairs, cur, base):
    out = collections.defaultdict(set)
    for key, prev in pairs.items():
        if key == prev or cur[key][0] == "m":
            continue
        name = key[1][:-len(D.BODY_SUFFIX)] if key[1].endswith(D.BODY_SUFFIX) else key[1]
        old = prev[1][:-len(D.BODY_SUFFIX)] if prev[1].endswith(D.BODY_SUFFIX) else prev[1]
        name, old = name.rsplit(".", 1)[-1], old.rsplit(".", 1)[-1]
        if name == old and name in base.get(owner(prev, base), ("", "", set()))[2]:
            out[owner(key, cur)].add(name)
    return out


def new_bindings(cur, base):
    pairs, out = correspond(cur, base), []
    moved = _moved_names(pairs, cur, base)
    for key in sorted(cur):
        names = cur[key][2]
        if not names:
            continue
        old = base[pairs[key]][2] if key in pairs else set()
        for name in sorted(names - old - moved.get(key, set())):
            out.append("%s %s 안 %s" % (_locate(key[0], name, True), key[1], name))
    return out


def run_hygiene():
    st = A.state()
    if A.PUBLIC_LAYOUT:
        return _skip("hygiene", "공개판 배치(이름·주석 위생은 저장소에서만 · 공개 사본은 주석을 지움)")
    if st.metrics is None:
        return T.chk(False, "hygiene: 규칙 파일 없음")
    base = (st.meta or {}).get("hygiene_base", "")
    top = G.toplevel(A.ROOT)
    if not top:
        return _skip("hygiene", "git 작업 트리가 아님")
    if not G.commit_of(A.ROOT, base):
        return _skip("hygiene", "기준 커밋 %s 없음(얕은 복제·다른 저장소)" % (base[:12] or "-"))
    rel = os.path.relpath(os.path.realpath(A.ROOT), top)
    prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
    inv = _base_inventory(base, prefix, st.rules.get("src_packages", []))
    if inv is None:
        return _skip("hygiene", "기준 트리를 읽지 못함(git cat-file)")
    base_scopes, hist, dochist = inv
    good = {m: fx for m, fx in st.index.items() if "error" not in fx}
    new_ids = new_bindings(scope_table(good), base_scopes)
    new_hist = []
    for mod, fx in sorted(good.items()):
        for key, kind in (("hist", "주석"), ("dochist", "독스트링")):
            for text in fx.get(key, []):
                if text not in hist and text not in dochist:
                    new_hist.append("%s [%s] %s" % (_locate(mod, text[:40], False), kind, text[:120]))
    T.chk(not new_ids, "hygiene.name9 새 '9로 끝나는 이름' 바인딩 %d개(기준 트리 %s 의 짝 범위에 없던 것 — 범위 짝 = 같은 (모듈, 이름) · "
          "옮긴 범위는 지문 1:1·이름 경로) · 규칙: 새 코드에 이름9 금지 · 고치는 법: 뜻이 드러나는 이름으로" % (len(new_ids), base[:8]),
          new_ids[:40])
    T.chk(not new_hist, "hygiene.history 새 이력 주석·독스트링(검수 표지·핫픽스·리팩터 단계·날짜·회차·오너 번호) %d줄 — 기준 트리 어디에도"
          " 없던 글 · 규칙: 이력은 CHANGELOG·git 으로 · 고치는 법: 주석엔 '왜·불변식'만 남겨라" % len(new_hist), new_hist[:40])
    ex = st.metrics.extra
    print("참고 이름9: 선언 %d · 참조 %d · 고유 %d · 이력 주석 %d/%d줄 · 이력 독스트링 %d/%d줄" % (
        ex["name9"]["decl"], ex["name9"]["ref"], ex["name9"]["unique"], ex["comments"]["history"],
        ex["comments"]["counted"], ex["doclines"]["history"], ex["doclines"]["lines"]), flush=True)


def _typed(k, lines):
    return [dict(ln, t=R.unit_type(k, ln["q"]), at="") for ln in lines]


def _by_metric(lines):
    out = {}
    for ln in lines:
        if ln["k"] != R.KEYS_LINE:
            out.setdefault(ln["k"], []).append(ln)
    return out


def _known_keys(name, old):
    keys = next((ln["v"] for ln in old if ln["k"] == R.KEYS_LINE and isinstance(ln.get("v"), list)), None)
    if keys is not None:
        return set(keys)
    group = next((g for g, fn in R.GROUP_FILE.items() if fn == name), None)
    return set(R.metrics_of(group)) | {k for k, g in R.SPECIAL.items() if g == group} if group else set()


def _loosened_metric(k, lines, prev, live):
    if k in R.SPECIAL:
        cur_floor = lines[0]["v"] if lines else 0
        old_floor = prev[0]["v"] if prev else 0
        return ["%s 바닥 %s → %s" % (k, old_floor, cur_floor)] if cur_floor < old_floor else []
    if k not in R.SPECS:
        return ["알 수 없는 지표 %s" % k]
    b = _typed(k, prev)
    exact = collections.defaultdict(list)
    for i, ln in enumerate(b):
        exact[_ident(ln)].append(i)
    moved = {}
    for i, pos in R.match(b, live).items():
        moved.setdefault(_ident(live[pos]), []).append(i)
    used, out = set(), []
    for u in lines:
        key = _ident(u)
        i = next((x for x in exact.get(key, []) if x not in used), None)
        if i is None:
            i = next((x for x in moved.get(key, []) if x not in used), None)
        if i is None:
            out.append("%s 새 줄(기준점 줄과도, 지금 소스의 옮김 대응과도 안 맞음) %s %s = %s" % (k, u["m"], u["q"], u["v"]))
            continue
        used.add(i)
        if R.worse(k, u["v"], b[i]["v"]):
            out.append("%s 커짐 %s %s %s → %s" % (k, u["m"], u["q"], b[i]["v"], u["v"]))
    return out


def _ident(u):
    return (u["m"], u["q"], u.get("f") or u["q"], u.get("h") or "")


def _loosened_lines(name, new, old, units):
    by_new, by_old, known = _by_metric(new), _by_metric(old), _known_keys(name, old)
    out = R.bad_lines(new) + _header_problems(new, known)
    for k in sorted(set(by_new) | set(by_old) | known):
        if k not in known and k not in by_old:
            if k not in R.SPECS and k not in R.SPECIAL:
                out.append("알 수 없는 지표 %s" % k)
            continue
        out += _loosened_metric(k, by_new.get(k, []), by_old.get(k, []), units.get(k, []))
    return out


def _header_problems(new, known):
    heads = [ln for ln in new if ln.get("k") == R.KEYS_LINE]
    if not heads:
        return ["_keys 머리 줄 없음(기준점 동결 지표 %s)" % sorted(known)] if known else []
    keys = heads[0].get("v")
    if len(heads) != 1 or new[0] is not heads[0] or not isinstance(keys, list):
        return ["_keys 머리 줄은 첫 줄 하나여야 함"]
    out = []
    if sorted(known - set(keys)):
        out.append("_keys 동결 지표 빠짐 %s" % sorted(known - set(keys)))
    unknown = sorted(k for k in keys if k not in R.SPECS and k not in R.SPECIAL)
    if unknown:
        out.append("_keys 모르는 지표 %s" % unknown)
    return out


def _loosened_rules(new, old):
    out = []
    for k, v in sorted(new.get("limits", {}).items()):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            out.append("limits.%s = %r — 0 이상 정수만" % (k, v))
        elif v > R.limit_of(k, old):
            out.append("limits.%s %s → %s" % (k, R.limit_of(k, old), v))
    if new.get("ledger_schema_module") != old.get("ledger_schema_module"):
        out.append("ledger_schema_module %s → %s" % (old.get("ledger_schema_module"), new.get("ledger_schema_module")))
    for table in ("api_allow", "copy_home"):
        for kind, pats in sorted(new.get(table, {}).items()):
            extra = sorted(set(pats) - set(old.get(table, {}).get(kind, [])))
            if extra:
                out.append("%s.%s 허용 추가 %s" % (table, kind, extra))
    left = collections.Counter((u["k"], u["q"]) for u in old.get("allow_units", []))
    for u in new.get("allow_units", []):
        if left[(u["k"], u["q"])]:
            left[(u["k"], u["q"])] -= 1
        else:
            out.append("allow_units 추가 %s %s %s" % (u["k"], u["m"], u["q"]))
    for key, grow_is_loose in (("except_reasons", True), ("src_packages", True), ("env_docs_exclude", False),
                               ("ledger_tables", False), ("money_modules", False)):
        a, b = set(new.get(key, [])), set(old.get(key, []))
        diff = sorted(a - b) if grow_is_loose else sorted(b - a)
        if diff:
            out.append("%s %s %s" % (key, "추가" if grow_is_loose else "빠짐", diff))
    return out


def _loosened_layers(new, old):
    out = []
    if new.get("layers") != old.get("layers"):
        out.append("계층 목록·순서 바꿈 %s → %s" % (old.get("layers"), new.get("layers")))
    prev = dict(old.get("planned", {}), **old.get("modules", {}))
    cur = dict(new.get("planned", {}), **new.get("modules", {}))
    for mod, lay in sorted(cur.items()):
        if mod in prev and prev[mod] != lay:
            out.append("계층 바꿈 %s: %s → %s" % (mod, prev[mod], lay))
    for mod in sorted(set(old.get("planned", {})) - set(cur)):
        out.append("계획 모듈 지움 %s(%s)" % (mod, old["planned"][mod]))
    so_new, so_old = new.get("split_of") or {}, old.get("split_of") or {}
    for mod, orig in sorted(so_new.items()) if isinstance(so_new, dict) else [("split_of", repr(so_new))]:
        if not isinstance(so_old, dict) or so_old.get(mod) != orig:
            out.append("분할 승계 표 split_of 늘림 %s → %s" % (mod, orig))
    return out


def _loosened_split_proof(new, old):
    def items(doc):
        out = set()
        origins = doc.get("origins") if isinstance(doc, dict) else None
        for o, ent in sorted((origins or {}).items()) if isinstance(origins, dict) else []:
            ent = ent if isinstance(ent, dict) else {}
            moved = ent.get("moved") if isinstance(ent.get("moved"), dict) else {}
            out |= {"옮긴 이름 %s→%s.%s" % (o, a, n) for a, ns in moved.items() for n in (ns if isinstance(ns, list) else [ns])}
            out |= {"근거 %s %s" % (o, json.dumps(e, ensure_ascii=False, sort_keys=True)) for e in ent.get("edges") or []}
        return out
    return sorted(items(new) - items(old))


def _growth_new(cur, old):
    left = collections.Counter(json.dumps(ln, ensure_ascii=False, sort_keys=True) for ln in R.parse_lines(old or "", "old"))
    out = []
    for ln in R.parse_lines(cur, R.GROWTH_FILE):
        key = json.dumps(ln, ensure_ascii=False, sort_keys=True)
        if left[key]:
            left[key] -= 1
        else:
            out.append(key)
    return out


def _check_file(name, cur, old, mb, ref, units):
    try:
        _check_file_parsed(name, cur, old, mb, ref, units)
    except ValueError as e:
        T.chk(False, "integrity %s — 읽을 수 없음(%s)" % (name, e))


def _check_file_parsed(name, cur, old, mb, ref, units):
    if name == R.GROWTH_FILE:
        added = _growth_new(cur, old)
        for a in added:
            print("검수 성장 사유 표 새 줄(병합 기준점 %s 뒤): %s" % (mb[:8], a), flush=True)
        T.chk(True, "integrity %s — 병합 기준점 %s 뒤 새 줄 %d(위 '검수' 줄 — 기준선 숫자는 안 올림)" % (name, mb[:8], len(added)))
        return
    if old is None:
        return
    if name in CLS_FILES:
        bad = loosened_cls(name, cur, old)
    elif name.endswith(".jsonl"):
        bad = _loosened_lines(name, R.parse_lines(cur, name), R.parse_lines(old, name + "@" + mb[:8]), units)
    elif name == "py_rules.json":
        bad = _loosened_rules(R.loads(cur), R.loads(old))
    elif name == "layers.json":
        bad = _loosened_layers(R.loads(cur), R.loads(old))
    elif name == "py_split_proof.json":
        bad = _loosened_split_proof(R.loads(cur), R.loads(old))
    else:
        a, b = R.loads(cur).get("hygiene_base"), R.loads(old).get("hygiene_base")
        bad = ["hygiene_base %s → %s" % (b, a)] if b and a != b else []
    T.chk(not bad, "integrity %s — 병합 기준점 %s(%s) 대비 느슨해진 곳 %d · 규칙: 기준선·규칙을 느슨하게 바꾸는 것은 기준 브랜치에서만"
          "(총괄 검토) · 고치는 법: 코드를 고쳐 기준선 안으로 · 줄인 값 반영은 --update-lower · 불가피한 성장은 py_growth.jsonl" % (
              name, mb[:8], ref, len(bad)), bad[:40])


RATCHET_OWNED = frozenset({"py_unit_closure.jsonl"})


CLS_FILES = frozenset({"hyg_srctext.jsonl", "hyg_untested.jsonl"})


def loosened_cls(name, cur, old):
    import _arch_ratchet as HR
    spec = HR.SPECS[name[:-len(".jsonl")]]
    return HR.increases(spec, HR.parse(spec, cur), HR.parse(spec, old))


def _ours(name):
    return (name.startswith("py_") and name not in RATCHET_OWNED) or name == "layers.json" or name in CLS_FILES


def _public_base(root, top):
    tag = G.last_tag(root)
    sha = G.commit_of(root, tag) if tag else None
    if sha:
        return sha, "마지막 태그 %s" % tag
    if G.is_shallow(root):
        return None, "태그 없는 얕은 복제(VERSION 마지막 커밋 = 얕은 경계라 비교 못 함 — git fetch --unshallow --tags 또는 CI fetch-depth: 0)"
    rel = os.path.relpath(os.path.join(os.path.realpath(root), "VERSION"), top).replace(os.sep, "/")
    sha = G.last_commit_of(top, rel)
    return (sha, "VERSION 마지막 커밋") if sha else (None, "태그도 VERSION 커밋도 없음")


def base_commit(root, public, want=""):
    ref = want or ("공개판 기준" if public else "refactor")
    if ref.lower() in _SKIP_REF:
        return None, ref, "TJ_TEST_ARCH_BASE_REF=%s" % ref
    top = G.toplevel(root)
    head = G.commit_of(root, "HEAD")
    if public and not want:
        if not top or not head:
            return None, ref, "공개판 배치 · git 작업 트리·HEAD 없음(깃 없는 사본 — 비교할 이전 판이 없음)"
        sha, name = _public_base(root, top)
        return (sha, name, None) if sha else (None, ref, "공개판 배치 · " + name)
    rc = G.commit_of(root, ref)
    if not top or not head or not rc:
        return None, ref, "git 작업 트리·HEAD·기준 브랜치 '%s' 중 없는 것이 있음" % ref
    mb = G.merge_base(root, head, rc)
    return (mb, ref, None) if mb else (None, ref, "병합 기준점 없음(%s)" % ref)


def run_integrity():
    mb, ref, why = base_commit(A.ROOT, A.PUBLIC_LAYOUT, A._ENV["TJ_TEST_ARCH_BASE_REF"])
    if why:
        return _skip("integrity", why)
    top = G.toplevel(A.ROOT)
    st = A.state()
    units = st.metrics.units if st.metrics is not None else {}
    rel_dir = os.path.relpath(A.BASE_DIR, top).replace(os.sep, "/")
    names = {f for f in os.listdir(A.BASE_DIR) if _ours(f)}
    names |= {p.rsplit("/", 1)[-1] for p in G.tree_paths(A.ROOT, mb, rel_dir) if _ours(p.rsplit("/", 1)[-1])}
    seen = 0
    for name in sorted(names):
        path = os.path.join(A.BASE_DIR, name)
        old = G.show(A.ROOT, mb, rel_dir + "/" + name)
        if not os.path.isfile(path):
            if old is not None:
                seen += 1
                T.chk(False, "integrity %s — 병합 기준점 %s 에 있던 기준선·규칙 파일을 지움(느슨해짐)" % (name, mb[:8]))
            continue
        with open(path, encoding="utf-8") as f:
            cur = f.read()
        seen += old is not None
        _check_file(name, cur, old, mb, ref, units)
    if not seen:
        T.chk(True, "integrity — 병합 기준점 %s 에 기준선 파일이 없음(처음 생기는 커밋) · 비교 없음" % mb[:8])
