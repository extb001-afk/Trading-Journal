from __future__ import annotations

import ast
import json
import os

GROUPS_SVC = ("EXF", "PRICING", "RECON")
DICT_METH = ("get", "pop", "setdefault")
PROBES = ("getattr", "hasattr", "setattr", "delattr")
NOT_PASS = PROBES + ("isinstance", "type", "id", "vars", "repr", "str", "super")


def core_files(src_dir):
    return sorted(f for f in os.listdir(src_dir) if f.startswith("core") and f.endswith(".py"))


def _parse(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), path)


def _is_static(fn):
    return any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)


def class_index(src_dir):
    out = {}
    for f in core_files(src_dir):
        for n in _parse(os.path.join(src_dir, f)).body:
            if not isinstance(n, ast.ClassDef):
                continue
            meths, attrs = [], []
            for b in n.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    meths.append(b)
                elif isinstance(b, ast.Assign):
                    attrs += [t.id for t in b.targets if isinstance(t, ast.Name)]
                elif isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                    attrs.append(b.target.id)
            out[n.name] = {"file": f, "bases": [ast.unparse(b) for b in n.bases], "methods": meths, "attrs": attrs, "node": n}
    return out


def mro_names(cls, idx):
    seen, out = set(), []

    def walk(c):
        if c in seen or c not in idx:
            return
        seen.add(c)
        out.append(c)
        for b in idx[c]["bases"]:
            walk(b)
    walk(cls)
    return out


def _receivers(fn):
    if _is_static(fn) or not fn.args.args:
        return None
    return fn.args.args[0].arg


def _const_str(e):
    return e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None


def _via(e, me):
    if isinstance(e, ast.Name) and e.id == me:
        return "self"
    if isinstance(e, ast.Attribute) and e.attr == "core" and isinstance(e.value, ast.Name) and e.value.id == me:
        return "core"
    return None


def touches(fn):
    me = _receivers(fn)
    out, passes = [], []
    if me is None:
        return out, passes
    dict_ok = set()
    for x in ast.walk(fn):
        if isinstance(x, ast.Attribute) and _via(x.value, me) and x.attr not in ("__dict__", "__class__") \
                and not (x.attr == "core" and _via(x.value, me) == "self"):
            out.append((x.attr, "store" if isinstance(x.ctx, (ast.Store, ast.Del)) else "attr", _via(x.value, me)))
        elif isinstance(x, ast.Subscript) and isinstance(x.value, ast.Attribute) and x.value.attr == "__dict__" \
                and _via(x.value.value, me) and _const_str(x.slice):
            out.append((x.slice.value, "dictstore" if isinstance(x.ctx, (ast.Store, ast.Del)) else "dict", _via(x.value.value, me)))
            dict_ok.add(id(x.value))
        elif isinstance(x, ast.Compare) and len(x.comparators) == 1 and isinstance(x.ops[0], (ast.In, ast.NotIn)) \
                and isinstance(x.comparators[0], ast.Attribute) and x.comparators[0].attr == "__dict__" \
                and _via(x.comparators[0].value, me) and _const_str(x.left):
            out.append((x.left.value, "dict", _via(x.comparators[0].value, me)))
            dict_ok.add(id(x.comparators[0]))
        elif isinstance(x, ast.Call):
            fu = x.func
            if isinstance(fu, ast.Attribute) and fu.attr in DICT_METH and isinstance(fu.value, ast.Attribute) \
                    and fu.value.attr == "__dict__" and _via(fu.value.value, me) and x.args and _const_str(x.args[0]):
                out.append((x.args[0].value, "dictstore" if fu.attr == "setdefault" else "dict", _via(fu.value.value, me)))
                dict_ok.add(id(fu.value))
            if isinstance(fu, ast.Name) and fu.id in PROBES and len(x.args) >= 2 and _via(x.args[0], me) \
                    and _const_str(x.args[1]):
                out.append((x.args[1].value, "probe:" + fu.id, _via(x.args[0], me)))
            elif isinstance(fu, ast.Name) and fu.id in PROBES and len(x.args) >= 2 and _via(x.args[0], me):
                out.append(("?", "opaque:%s(받는 쪽, 변수)" % fu.id, "self"))
            elif isinstance(fu, ast.Name) and fu.id in ("vars", "type") and len(x.args) == 1 and _via(x.args[0], me):
                out.append(("?", "opaque:%s(받는 쪽)" % fu.id, "self"))
            if (isinstance(fu, ast.Name) and fu.id in NOT_PASS) or ast.unparse(fu) == "object.__new__":
                continue
            for i, a in enumerate(x.args):
                if isinstance(a, ast.Name) and a.id == me:
                    passes.append((x, i))
            for k in x.keywords:
                if isinstance(k.value, ast.Name) and k.value.id == me:
                    passes.append((x, k.arg))
    for x in ast.walk(fn):
        if isinstance(x, ast.Attribute) and _via(x.value, me) and x.attr == "__dict__" and id(x) not in dict_ok:
            out.append(("?", "opaque:__dict__ 통째(글자 열쇠 밖)", "self"))
        elif isinstance(x, ast.Attribute) and _via(x.value, me) and x.attr == "__class__":
            out.append(("?", "opaque:__class__", "self"))
        elif isinstance(x, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and x.value is not None and isinstance(x.value, ast.Name) \
                and x.value.id == me:
            out.append(("?", "opaque:받는 쪽 별칭", "self"))
    return out, passes


def _module_defs(tree):
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    return funcs, classes


def _params(fn):
    a = fn.args
    return [p.arg for p in a.posonlyargs + a.args]


def carrier_flow(tree, entry_kind, entry_name, index):
    funcs, classes = _module_defs(tree)
    names, dkeys, tmod, unres = set(), set(), set(), set()
    work, seen = [], set()

    def push(kind, owner, fname, idx):
        k = (kind, owner, fname, idx)
        if k not in seen:
            seen.add(k)
            work.append(k)

    if entry_kind == "class":
        cn = classes.get(entry_name)
        if cn is None:
            return {"unresolved": ["클래스 없음 " + entry_name]}
        push("meth", entry_name, "__init__", index if isinstance(index, str) else index + 1)
    else:
        push("func", None, entry_name, index)
    attr_carriers = {}
    while work:
        kind, owner, fname, idx = work.pop()
        if kind == "func":
            fn = funcs.get(fname)
        else:
            fn = next((b for b in classes[owner].body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name == fname), None)
        if fn is None:
            unres.add("%s 없음" % fname)
            continue
        ps = _params(fn)
        p = idx if isinstance(idx, str) else (ps[idx] if idx < len(ps) else None)
        if p is None or p not in ps + [k.arg for k in fn.args.kwonlyargs]:
            unres.add("%s 인자 %s" % (fname, idx))
            continue
        _scan_carrier_fn(fn, {p}, owner, attr_carriers, names, dkeys, tmod, unres, push, funcs, classes)
        if kind == "meth" and owner in attr_carriers:
            for b in classes[owner].body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and ("attr", owner, b.name) not in seen:
                    seen.add(("attr", owner, b.name))
                    _scan_carrier_fn(b, set(), owner, attr_carriers, names, dkeys, tmod, unres, push, funcs, classes)
    return {"names": sorted(names), "dict_keys": sorted(dkeys), "type_module": sorted(tmod), "unresolved": sorted(unres)}


def _scan_carrier_fn(fn, local, owner, attr_carriers, names, dkeys, tmod, unres, push, funcs, classes):
    me = _params(fn)[0] if owner and _params(fn) else None
    local = set(local)
    acs = attr_carriers.setdefault(owner, set()) if owner else set()

    def is_c(e):
        if isinstance(e, ast.Name) and e.id in local:
            return True
        return bool(me) and isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == me and e.attr in acs

    changed = True
    while changed:
        changed = False
        for x in ast.walk(fn):
            if isinstance(x, ast.Assign) and is_c(x.value):
                for t in x.targets:
                    if isinstance(t, ast.Name) and t.id not in local:
                        local.add(t.id)
                        changed = True
                    elif me and isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == me and t.attr not in acs:
                        acs.add(t.attr)
                        changed = True
    for x in ast.walk(fn):
        if isinstance(x, ast.Attribute) and is_c(x.value):
            if x.attr == "__class__":
                tmod.add((fn.name, "?"))
            elif x.attr != "__dict__":
                names.add(x.attr)
        elif isinstance(x, ast.Subscript) and isinstance(x.value, ast.Attribute) and x.value.attr == "__dict__" and is_c(x.value.value):
            dkeys.add(_const_str(x.slice) or "?")
        elif isinstance(x, ast.Call):
            fu = x.func
            if isinstance(fu, ast.Attribute) and isinstance(fu.value, ast.Attribute) and fu.value.attr == "__dict__" and is_c(fu.value.value):
                dkeys.add(_const_str(x.args[0]) if x.args and _const_str(x.args[0]) else "?")
            if isinstance(fu, ast.Name) and fu.id in PROBES and len(x.args) >= 2 and is_c(x.args[0]):
                names.add(_const_str(x.args[1]) or "?")
            if isinstance(fu, ast.Name) and fu.id == "type" and len(x.args) == 1 and is_c(x.args[0]):
                tmod.add((fn.name, _tm_attr(fn, x)))
            for i, a in enumerate(list(x.args) + [k.value for k in x.keywords]):
                if not is_c(a):
                    continue
                key = i if i < len(x.args) else x.keywords[i - len(x.args)].arg
                if isinstance(fu, ast.Name) and fu.id in funcs:
                    push("func", None, fu.id, key)
                elif isinstance(fu, ast.Name) and fu.id in classes:
                    push("meth", fu.id, "__init__", key + 1 if isinstance(key, int) else key)
                elif me and isinstance(fu, ast.Attribute) and isinstance(fu.value, ast.Name) and fu.value.id == me and owner:
                    push("meth", owner, fu.attr, key + 1 if isinstance(key, int) else key)
                elif isinstance(fu, ast.Name) and fu.id in PROBES + ("type", "isinstance", "id", "repr", "str"):
                    pass
                else:
                    unres.add("%s → %s" % (fn.name, ast.unparse(fu)[:60]))


def _tm_attr(fn, type_call):
    for x in ast.walk(fn):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "getattr" and len(x.args) >= 2:
            if any(y is type_call for y in ast.walk(x.args[0])):
                return _const_str(x.args[1]) or "?"
    return "?"


def type_module_sites(tree):
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ps = set(_params(n))
            for x in ast.walk(n):
                if isinstance(x, ast.Attribute) and x.attr == "__module__" and isinstance(x.value, ast.Call) \
                        and isinstance(x.value.func, ast.Name) and x.value.func.id == "type" and len(x.value.args) == 1 \
                        and isinstance(x.value.args[0], ast.Name) and x.value.args[0].id in ps:
                    out.append((n.name, _tm_attr(n, x.value)))
    return sorted(set(out))


def module_binds(path, name):
    for n in _parse(path).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return True
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return True
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name:
            return True
        if isinstance(n, (ast.Import, ast.ImportFrom)) and any((a.asname or a.name.split(".")[0]) == name for a in n.names):
            return True
    return False


def _imports(tree):
    out = {}
    for x in ast.walk(tree):
        if isinstance(x, ast.Import):
            for a in x.names:
                out[a.asname or a.name] = a.name
    return out


def facts(src_dir, table, tools_dir=None):
    idx = class_index(src_dir)
    cg = dict(table.get("classes") or {})
    unknown = sorted(c for c in idx if c not in cg)
    svcs = set(table.get("services") or [])
    owner, dups, ports = {}, [], {}

    def defs(c):
        return [n for n in [m.name for m in idx[c]["methods"]] + idx[c]["attrs"] if n not in ("__init__", "__all__")]
    for c in sorted(x for x in idx if x not in svcs):
        for nm in defs(c):
            if nm in owner and owner[nm] != c:
                dups.append([nm, owner[nm], c])
                continue
            owner[nm] = c
    T = {(c, fn.name): touches(fn) for c in idx for fn in idx[c]["methods"]}
    pre_state = {nm for (c, _m), (tl, _p) in T.items() if c not in svcs for nm, how, _v in tl
                 if not how.startswith("opaque:") and nm not in owner}
    for c in sorted(x for x in idx if x in svcs):
        for nm in defs(c):
            if nm in owner and owner[nm] != c and owner[nm] not in svcs or nm in pre_state:
                ports.setdefault(c, []).append(nm)
            elif nm in owner and owner[nm] != c:
                dups.append([nm, owner[nm], c])
            else:
                owner[nm] = c
    g_of = lambda c: cg.get(c, "?")   # noqa: E731
    edges, state, init_touch, other_touch = {}, {}, {}, {}
    bypass, gcore, passes_raw, opaque = [], [], [], []
    written, selfuse = {}, {}
    for c in sorted(idx):
        g = g_of(c)
        for fn in idx[c]["methods"]:
            q = "%s.%s" % (c, fn.name)
            tl, ps = T[(c, fn.name)]
            for nm, how, via in tl:
                if how.startswith("opaque:"):
                    opaque.append((idx[c]["file"], q, how[7:]))
                    continue
                if via == "self":
                    selfuse.setdefault(g, set()).add(nm)
                    if how in ("store", "dictstore", "probe:setattr"):
                        written.setdefault(c, set()).add(nm)
                if nm in owner:
                    h = g_of(owner[nm])
                    if h != g:
                        edges.setdefault("%s>%s" % (g, h), set()).add(nm)
                else:
                    state.setdefault(nm, set()).add(g)
                    if g == "CORE":
                        (init_touch if (c == "Core" and fn.name == "__init__") else other_touch).setdefault(nm, set()).add(q)
                if g in GROUPS_SVC and how in ("dict", "dictstore") and via == "self":
                    bypass.append((idx[c]["file"], q, nm))
                if g in GROUPS_SVC and how in ("probe:getattr", "probe:hasattr") and via == "self":
                    gcore.append((idx[c]["file"], q, how[6:], nm))
            for call, pos in ps:
                passes_raw.append((g, idx[c]["file"], q, call, pos))
    shared = {k: sorted(v) for k, v in state.items() if len(v) > 1}
    core_touch = {k for k, v in state.items() if "CORE" in v}
    port_names = {n for v in ports.values() for n in v}
    grp_of_q = lambda q: g_of(q.split(".")[0])   # noqa: E731
    bypass = sorted({b for b in bypass if b[2] in core_touch or b[2] in port_names
                     or (b[2] in owner and g_of(owner[b[2]]) != grp_of_q(b[1]))})
    gcore = sorted({x for x in gcore if x[3] in core_touch or (x[3] in owner and g_of(owner[x[3]]) == "CORE")})
    init_only = sorted(k for k in shared if k in init_touch and k not in other_touch)
    sp = []
    for g, f, q, call, pos in passes_raw:
        tree = _parse(os.path.join(src_dir, f))
        al = _imports(tree)
        fu = call.func
        rec = {"group": g, "site": "%s:%s" % (f, q), "callee": ast.unparse(fu), "arg": pos}
        if isinstance(fu, ast.Attribute) and isinstance(fu.value, ast.Name) and fu.value.id in al \
                and os.path.isfile(os.path.join(src_dir, al[fu.value.id] + ".py")):
            mt = _parse(os.path.join(src_dir, al[fu.value.id] + ".py"))
            fs, cs = _module_defs(mt)
            kind = "class" if fu.attr in cs else "func"
            fl = carrier_flow(mt, kind, fu.attr, pos)
            rec.update({"module": al[fu.value.id], "names": fl.get("names", []), "dict_keys": fl.get("dict_keys", []),
                        "type_module": [list(t) for t in fl.get("type_module", [])], "unresolved": fl.get("unresolved", [])})
        else:
            rec.update({"module": None, "names": [], "dict_keys": [], "type_module": [], "unresolved": ["받는 쪽 못 풂"]})
        sp.append(rec)
    sp.sort(key=lambda r: (r["site"], r["callee"], str(r["arg"])))
    tm_tools = []
    if tools_dir and os.path.isfile(os.path.join(tools_dir, "rebuild2.py")):
        tm_tools = [["tools/rebuild2.py", f, a] for f, a in type_module_sites(_parse(os.path.join(tools_dir, "rebuild2.py")))]
    return {"classes": {c: {"file": idx[c]["file"], "group": g_of(c), "bases": idx[c]["bases"],
                            "methods": len(idx[c]["methods"]), "attrs": len(idx[c]["attrs"])} for c in sorted(idx)},
            "unknown_classes": unknown, "dups": dups, "owner": owner, "ports": {k: sorted(v) for k, v in sorted(ports.items())},
            "edges": {k: sorted(v) for k, v in sorted(edges.items())}, "state": dict(sorted(shared.items())),
            "state_all": {k: sorted(v) for k, v in sorted(state.items())},
            "core_init_only": init_only, "bypass": [list(b) for b in bypass], "getattr_core": [list(x) for x in gcore],
            "opaque": [list(x) for x in sorted(set(opaque))], "bad_bases": _bad_bases(idx),
            "modfunc": _modfunc(src_dir, owner, g_of),
            "need": {g: sorted(n for n in v if (n in owner and g_of(owner[n]) != g) or (n not in owner and (n in core_touch or len(state.get(n, ())) > 1)))
                     for g, v in sorted(selfuse.items()) if g in GROUPS_SVC},
            "written": {c: sorted(v) for c, v in sorted(written.items())},
            "self_pass": sp, "type_module_tools": tm_tools, "_idx": idx}


def _modfunc(src_dir, owner, g_of):
    out = set()
    for f in core_files(src_dir):
        for n in _parse(os.path.join(src_dir, f)).body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            ps = set(_params(n)) | {a.arg for a in n.args.kwonlyargs}
            for x in ast.walk(n):
                nm = None
                if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id in ps:
                    nm = x.attr
                elif isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in PROBES and len(x.args) >= 2 \
                        and isinstance(x.args[0], ast.Name) and x.args[0].id in ps:
                    nm = _const_str(x.args[1])
                if nm and nm in owner and g_of(owner[nm]) in GROUPS_SVC:
                    out.add((f, n.name, nm))
    return [list(x) for x in sorted(out)]


def _bad_bases(idx):
    import builtins
    return sorted([c, b] for c, v in idx.items() for b in v["bases"] if b not in idx and not isinstance(getattr(builtins, b, None), type))


def table_from(fx, old):
    return {"_doc": old.get("_doc", ""), "classes": old.get("classes", {}), "runtime": old.get("runtime", {}),
            "tm_recv": old.get("tm_recv", {}), "services": old.get("services", []), "ports": fx["ports"],
            "duty": old.get("duty", {}),
            "edges": fx["edges"], "state": fx["state"], "core_init_only": fx["core_init_only"],
            "bypass": fx["bypass"], "getattr_core": fx["getattr_core"], "opaque": fx["opaque"], "modfunc": fx["modfunc"],
            "self_pass": [{k: r[k] for k in ("group", "site", "callee", "arg", "module", "names", "dict_keys", "type_module", "unresolved")}
                          for r in fx["self_pass"]],
            "type_module_tools": fx["type_module_tools"]}


def _sp_key(r):
    return "%s|%s|%s" % (r["site"], r["callee"], r["arg"])


def judge(fx, table, src_dir, have_tools=False):
    bad, lower = [], []
    for c in fx["unknown_classes"]:
        bad.append("묶음 표에 없는 core 클래스 %s(%s) — classes 에 묶음을 적을 것" % (c, fx["classes"][c]["file"]))
    for d in fx["dups"]:
        bad.append("이름 겹침 %s(%s · %s) — 서비스 포트면 표 판을 넓힐 것" % tuple(d))
    tp = table.get("ports", {})
    for c, names in fx["ports"].items():
        bad += ["서비스 %s 의 표에 없는 포트 이름 %s(위임 = 표 ports 에 적을 것)" % (c, n) for n in names if n not in tp.get(c, [])]
    lower += ["포트 이름 줄어듦 %s.%s" % (c, n) for c, names in tp.items() for n in names if n not in fx["ports"].get(c, [])]
    for c in sorted(set(table.get("classes", {})) - set(fx["classes"])):
        lower.append("표 클래스 %s 가 src 에 없음" % c)
    te = table.get("edges", {})
    for k, names in fx["edges"].items():
        for nm in names:
            if nm not in te.get(k, []):
                bad.append("새 경계 이름 %s: %s" % (k, nm))
    for k, names in te.items():
        for nm in names:
            if nm not in fx["edges"].get(k, []):
                lower.append("경계 이름 줄어듦 %s: %s" % (k, nm))
    ts = table.get("state", {})
    for nm, gs in fx["state"].items():
        extra = sorted(set(gs) - set(ts.get(nm, [])))
        if nm not in ts:
            bad.append("새 공유 상태 %s %s" % (nm, gs))
        elif extra:
            bad.append("공유 상태 %s 에 묶음 더해짐 %s" % (nm, extra))
    for nm in ts:
        if sorted(fx["state"].get(nm, [])) != sorted(ts[nm]):
            lower.append("공유 상태 줄어듦 %s" % nm)
    bad += ["바탕 클래스 %s(%s)를 src/core*.py 에서 못 찾음 — 묶음 밖 믹스인" % (b, c) for c, b in fx["bad_bases"]]
    for key, label in (("bypass", "포트 우회"), ("getattr_core", "getattr CORE 글자"), ("opaque", "받는 쪽 분석 밖 꼴"),
                       ("modfunc", "core*.py 모듈 함수의 서비스 이름")):
        cur, base = {tuple(x) for x in fx[key]}, {tuple(x) for x in table.get(key, [])}
        bad += ["새 %s 자리 %s" % (label, list(x)) for x in sorted(cur - base)]
        lower += ["%s 줄어듦 %s" % (label, list(x)) for x in sorted(base - cur)]
    tsp = {_sp_key(r): r for r in table.get("self_pass", [])}
    for r in fx["self_pass"]:
        b = tsp.get(_sp_key(r))
        if b is None:
            bad.append("새 self 넘김 자리 %s → %s" % (r["site"], r["callee"]))
            continue
        for fld in ("names", "dict_keys", "unresolved"):
            new = sorted(set(r[fld]) - set(b.get(fld, [])))
            if new:
                bad.append("self 넘김 %s → %s: 표 밖 %s %s" % (r["site"], r["callee"], fld, new))
        tmn = sorted({tuple(x) for x in r["type_module"]} - {tuple(x) for x in b.get("type_module", [])})
        if tmn:
            bad.append("self 넘김 %s: 표 밖 type(x).__module__ 자리 %s" % (r["site"], tmn))
    for k in sorted(set(tsp) - {_sp_key(r) for r in fx["self_pass"]}):
        lower.append("self 넘김 자리 줄어듦 %s" % k)
    bad += _runtime_checks(fx, table, src_dir)
    if have_tools:
        cur, base = {tuple(x) for x in fx["type_module_tools"]}, {tuple(x) for x in table.get("type_module_tools", [])}
        bad += ["tools 새 type(x).__module__ 자리 %s" % list(x) for x in sorted(cur - base)]
        for f, fn, attr in sorted(cur & base):
            rc = table.get("tm_recv", {}).get("%s:%s" % (f, fn))
            if not rc or rc not in fx["classes"]:
                bad.append("tm_recv 에 %s:%s 의 받는 클래스가 없음" % (f, fn))
            elif not module_binds(os.path.join(src_dir, fx["classes"][rc]["file"]), attr):
                bad.append("%s:%s 가 찾는 %s 가 %s 모듈에 없음(기본값으로 조용히 빠짐)" % (f, fn, attr, fx["classes"][rc]["file"]))
    return bad, lower


def _avail(rc, fx):
    idx = fx["_idx"]
    mro = mro_names(rc, idx)
    defined = {m.name for c in mro for m in idx[c]["methods"]} | {a for c in mro for a in idx[c]["attrs"]}
    wrote = {n for c in mro for n in fx["written"].get(c, [])}
    return mro, defined, wrote


def _runtime_checks(fx, table, src_dir):
    bad, idx = [], fx["_idx"]
    rt = table.get("runtime", {})
    groups = sorted({v["group"] for v in fx["classes"].values() if v["group"] not in ("OTHER", "?")})
    for g in groups:
        rc = rt.get(g)
        if rc not in idx:
            bad.append("runtime 표에 묶음 %s 의 실제 클래스가 없음(%s)" % (g, rc))
            continue
        mro = mro_names(rc, idx)
        miss = sorted(c for c, v in fx["classes"].items() if v["group"] == g and c not in mro)
        if miss:
            bad.append("묶음 %s 클래스 %s 가 실제 클래스 %s 의 바탕에 없음" % (g, miss, rc))

    def look(g, rc, names, what):
        mro, defined, wrote = _avail(rc, fx)
        out = []
        for n in names:
            if n in defined:
                continue
            if n in wrote and "Core" in mro:
                continue
            if n in wrote:
                out.append("%s: %s 가 CORE 공유 상태 %s 를 자기 객체에 씀(Core 와 갈라짐)" % (what, rc, n))
            else:
                out.append("%s: 이름 %s 가 실제 클래스 %s 에 없음(포트 빠짐 — getattr 기본값·AttributeError)" % (what, n, rc))
        return out
    for g, names in fx["need"].items():
        rc = rt.get(g)
        if rc in idx:
            bad += look(g, rc, names, "묶음 %s 몸통" % g)
    core_rc = rt.get("CORE")
    if core_rc in idx:
        _m, cdef, cwrote = _avail(core_rc, fx)
        for c, v in sorted(fx["classes"].items()):
            if v["group"] not in GROUPS_SVC:
                continue
            for fn in idx[c]["methods"]:
                miss = sorted({n for n, how, via in touches(fn)[0] if via == "core" and not how.startswith("opaque:")
                               and n not in cdef and n not in cwrote})
                bad += ["%s.%s: self.core 의 이름 %s 가 실제 CORE 클래스 %s 에 없음(옮겨 간 이름·빠진 초기화를 위임)" % (c, fn.name, n, core_rc)
                        for n in miss]
    for g, names in sorted((table.get("duty") or {}).items()):
        rc = rt.get(g)
        if rc in idx:
            mro, defined, wrote = _avail(rc, fx)
            bad += ["묶음 %s 의무 이름 %s 가 실제 클래스 %s 에서 정의·대입되지 않음(getattr 기본값으로 조용히 빠짐)" % (g, n, rc)
                    for n in names if n not in defined and n not in wrote]
    for f, q, k in fx["bypass"]:
        g = fx["classes"].get(q.split(".")[0], {}).get("group")
        rc = rt.get(g)
        if rc in idx and "Core" not in mro_names(rc, idx):
            bad.append("묶음 %s 가 %s 로 나뉘었는데 포트 우회 %s:%s %s 가 남음(self.__dict__ = 서비스 사전)" % (g, rc, f, q, k))
    for r in fx["self_pass"]:
        rc = rt.get(r["group"])
        if rc not in idx:
            continue
        bad += look(r["group"], rc, r["names"], "self 넘김 %s → %s" % (r["site"], r["callee"]))
        for fn, attr in r["type_module"]:
            if attr == "?" or not module_binds(os.path.join(src_dir, idx[rc]["file"]), attr):
                bad.append("self 넘김 %s: %s 가 찾는 %s 가 %s 모듈(%s)에 없음 — 기본값으로 조용히 기장" % (r["site"], fn, attr, rc, idx[rc]["file"]))
    return bad


def summary(fx):
    rows = []
    for g in GROUPS_SVC:
        outs = sorted({n for k, v in fx["edges"].items() if k.startswith(g + ">") for n in v})
        ins = fx["edges"].get("CORE>" + g, [])
        st = sorted(k for k, v in fx["state"].items() if g in v)
        by = [b for b in fx["bypass"] if fx["classes"].get(b[1].split(".")[0], {}).get("group") == g]
        gc = [b for b in fx["getattr_core"] if fx["classes"].get(b[1].split(".")[0], {}).get("group") == g]
        rows.append({"group": g, "port_calls": outs, "entries": ins, "shared_state": st, "bypass": len(by), "getattr_core": len(gc),
                     "classes": sorted(c for c, v in fx["classes"].items() if v["group"] == g)})
    return rows


def load_table(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump_table(path, tab):
    def one(v):
        return json.dumps(v, ensure_ascii=False, sort_keys=isinstance(v, dict))
    lines, items = ["{"], list(tab.items())
    for i, (k, v) in enumerate(items):
        tail = "," if i < len(items) - 1 else ""
        if isinstance(v, list) and v:
            lines.append(" %s: [" % one(k))
            lines += ["  %s%s" % (one(e), "," if j < len(v) - 1 else "") for j, e in enumerate(v)]
            lines.append(" ]" + tail)
        elif isinstance(v, dict) and v:
            lines.append(" %s: {" % one(k))
            ks = list(v)
            lines += ["  %s: %s%s" % (one(x), one(v[x]), "," if j < len(ks) - 1 else "") for j, x in enumerate(ks)]
            lines.append(" }" + tail)
        else:
            lines.append(" %s: %s%s" % (one(k), one(v), tail))
    lines.append("}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
