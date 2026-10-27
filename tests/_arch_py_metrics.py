import _arch_py_defs as D

def matches(mod, patterns):
    for p in patterns:
        if (p.endswith("*") and mod.startswith(p[:-1])) or mod == p:
            return True
    return False


def scope_type(q):
    if q == D.MODULE_Q:
        return "m"
    return "b" if q.endswith(D.BODY_SUFFIX) else "f"


class Metrics:

    def __init__(self):
        self.units = {}
        self.cycles = []
        self.floor = {}
        self.hard = {}
        self.extra = {}

    def add(self, k, m, q, v, t, at="", f=None, h=None):
        u = {"k": k, "m": m, "q": q, "v": v, "t": t, "at": at}
        if f and f != q:
            u["f"] = f
        if h:
            u["h"] = h
        self.units.setdefault(k, []).append(u)


class _Ctx:

    def __init__(self, index, rules, layers):
        self.index, self.rules = index, rules
        self.mods = set(index)
        names = layers.get("layers", [])
        self.layer_names = names
        self.layer_of = {}
        for table in (layers.get("planned", {}), layers.get("modules", {})):
            for mod, lay in table.items():
                if lay in names:
                    self.layer_of[mod] = names.index(lay)

    def targets(self, imp, me):
        _ln, _lazy, kind, mod, names = imp
        out = set()
        if mod in self.mods:
            out.add(mod)
        elif kind == "import" and mod.split(".")[0] in self.mods:
            out.add(mod.split(".")[0])
        if kind == "from":
            out.update(mod + "." + n for n in names if mod + "." + n in self.mods)
        out.discard(me)
        return out

    def path(self, mod):
        return "src/" + mod.replace(".", "/") + (".py" if mod != "brokers" else "/__init__.py")


def _size(mx, c, mod, fx):
    p = c.path(mod)
    mx.add("file.lines", mod, "<file>", fx["lines"], "m", p)
    mx.add("file.bytes", mod, "<file>", fx["bytes"], "m", p)
    mx.add("module.reexport_only", mod, "<file>", int(bool(fx.get("reexport_only"))), "m", p)
    for u in fx["units"]:
        at = "%s:%d" % (p, u["l0"])
        if u["t"] == "f":
            for k, v in (("func.lines", u["len"]), ("func.args", u["args"]), ("func.depth", u["depth"]),
                         ("stage.reload", u.get("reload", 0))):
                mx.add(k, mod, u["q"], v, "f", at, u["f"], u["h"])
            mx.add("doc.missing", mod, u["q"], int(u["pub"] and not u["doc"]), "f", at, u["f"], u["h"])
            mx.add("hint.untyped", mod, u["q"], u["unt"] if u["pub"] else 0, "f", at, u["f"], u["h"])
        else:
            for k, v in (("class.lines", u["len"]), ("class.methods", u["meth"]), ("class.mixin_bases", u["mixb"]),
                         ("mixin.defs", int(u["mixin"]))):
                mx.add(k, mod, u["q"], v, "c", at, None, u["h"])


def _scopes(mx, c, mod, fx, valid_codes, edges, pairs, private):
    rules, p = c.rules, c.path(mod)
    money = mod in set(rules.get("money_modules", []))
    allow, home = rules.get("api_allow", {}), rules.get("copy_home", {})
    reasons = {(r["k"], r["m"], r["q"]) for r in rules.get("allow_units", [])}
    ledger = set(rules.get("ledger_tables", []))
    lines = {u["q"]: (u["l0"], u.get("f"), u.get("h")) for u in fx["units"]}
    scopes = {D.MODULE_Q: {}}
    for u in fx["units"]:
        scopes[u["q"] if u["t"] == "f" else u["q"] + D.BODY_SUFFIX] = {}
    scopes.update(fx["scopes"])
    for q, sc in scopes.items():
        t = scope_type(q)
        l0, fp, h = lines.get(q, (0, None, None)) if t == "f" else (0, None, None)
        at = "%s:%d" % (p, l0) if l0 else p

        def add(k, v, q=q, t=t, at=at, fp=fp, h=h):
            mx.add(k, mod, q, v, t, at, fp, h)
        lazy = 0
        for imp in sc.get("imp", []):
            tg = c.targets(imp, mod)
            edges.setdefault(mod, set()).update(tg)
            lazy += bool(imp[1] and tg)
            for t2 in tg:
                if mod in c.layer_of and t2 in c.layer_of and c.layer_of[t2] > c.layer_of[mod]:
                    pairs.setdefault((mod, t2), at)
        add("import.lazy", lazy)
        add("import.star", sc.get("star", 0))
        for kind, key in (("urlopen", "api.urlopen"), ("hmac", "api.hmac"), ("sqlite", "api.sqlite"),
                          ("replace", "api.replace"), ("kst", "kst"), ("statepath", "sp")):
            n = sc.get(key, 0)
            if matches(mod, allow.get(kind, [])) or ("api." + kind, mod, q) in reasons:
                n = 0
            add("api." + kind, n)
        if t == "f":
            add("copy.num", 0 if matches(mod, home.get("num", [])) else sc.get("num", 0))
            add("copy.atomic", 0 if matches(mod, home.get("atomic", [])) else sc.get("atomic", 0))
            add("copy.statepath", 0 if matches(mod, home.get("statepath", [])) else int(bool(sc.get("spret"))))
        led = sorted(x for x in sc.get("led", []) if x.split(":")[0] in ledger or x.startswith("{dyn}"))
        add("ledger.write", led)
        broad = nocg = 0
        for kind, last_raise, cg, code, _noqa in sc.get("exc", []):
            if code and code not in valid_codes:
                mx.hard.setdefault("except.badcode", []).append("%s %s [%s]" % (at, q, code))
            if kind not in ("broad", "bare") or last_raise:
                continue
            broad += code not in valid_codes
            nocg += money and not cg
        add("except.broad", broad)
        add("except.money_nocg", nocg)
        add("cfg.literal", sc.get("cfg", 0))
        add("const.1384", sc.get("c1384", 0))
        py = sc.get("py310", [])
        add("compat.py310", len(py))
        if py:
            mx.extra.setdefault("py310_labels", []).append("%s %s: %s" % (at, q, ", ".join(sorted(set(py)))))
        for target, name in sc.get("priv", []):
            if target in c.mods and target != mod:
                private[(target, name)] = private.get((target, name), 0) + 1


def _tarjan(nodes, edges):
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(edges.get(root, ()))))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges.get(w, ())))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    x = stack.pop()
                    on.discard(x)
                    comp.append(x)
                    if x == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return sorted(out, key=lambda cmp: (-len(cmp), cmp))


def compute(index, rules, layers, docs_text):
    c, mx = _Ctx(index, rules, layers), Metrics()
    valid_codes = set(rules.get("except_reasons", {}))
    edges, pairs, private, env = {}, {}, {}, set()
    for mod in sorted(index):
        fx = index[mod]
        _size(mx, c, mod, fx)
        _scopes(mx, c, mod, fx, valid_codes, edges, pairs, private)
        env.update(fx.get("env", []))
        for src_mod, name, bound in fx.get("unused_from", []):
            if src_mod in c.mods or (src_mod + "." + name) in c.mods:
                mx.add("import.reexport", mod, bound, 1, "n", c.path(mod))
        for line in fx.get("bare_str", []):
            mx.hard.setdefault("doc.misplaced", []).append("%s:%d" % (c.path(mod), line))
        for tm, name in fx.get("modset", []):
            if tm not in c.mods or name not in index[tm].get("defs", []):
                mx.hard.setdefault("ref.modset", []).append("%s: (%s, %s) — %s 에 그 이름이 없음" % (c.path(mod), tm, name, tm))
    for (src_mod, target), at in sorted(pairs.items()):
        lay = c.layer_names[c.layer_of[src_mod]]
        mx.add("layer.violations", src_mod, target, 1, "e", at, "%s→%s" % (lay, target))
    for (target, name), n in sorted(private.items()):
        mx.add("import.private", target, name, n, "n")
    for name in sorted(env):
        documented = name in docs_text and _word_in(name, docs_text)
        mx.add("env.undocumented", "*", name, 0 if documented else 1, "x")
    mx.add("except.swallow_pass", "*", "*", sum(sc.get("swp", 0) for fx in index.values() for sc in fx["scopes"].values()), "x")
    for mod in sorted(c.mods - set(c.layer_of)):
        mx.hard.setdefault("layer.unassigned", []).append(
            "%s — 계층 표(arch_baseline/layers.json 'modules')에 없음: 책임에 맞는 계층으로 한 줄 등록하라" % c.path(mod))
    for table in ("modules", "planned"):
        for mod, lay in sorted(layers.get(table, {}).items()):
            if lay not in c.layer_names:
                mx.hard.setdefault("layer.unassigned", []).append("layers.json %s.%s = '%s' — 없는 계층 이름" % (table, mod, lay))
    mx.cycles = _tarjan(c.mods, edges)
    comp_of = {m: i for i, comp in enumerate(mx.cycles) for m in comp}
    for a in sorted(edges):
        for b in sorted(edges[a]):
            if a in comp_of and comp_of.get(b) == comp_of[a]:
                mx.add("import.cycle_edges", a, b, 1, "x", c.path(a))
    mx.floor["contract.types"] = sum(1 for fx in index.values() for u in fx["units"] if u.get("contract"))
    ddl = {t for fx in index.values() for t in fx.get("ddl", [])}
    db_ddl = set(index.get(rules.get("ledger_schema_module", "db"), {}).get("ddl", []))
    missing = sorted(db_ddl - set(rules.get("ledger_tables", [])))
    if missing:
        mx.hard["ledger.tables"] = ["db 스키마 표인데 원장 표 목록(py_rules.json ledger_tables)에 없음: " + ", ".join(missing)]
    mx.extra.update(_extras(index, c, edges, mx, ddl))
    return mx


def _word_in(name, text):
    i = text.find(name)
    while i >= 0:
        before = text[i - 1] if i else " "
        after = text[i + len(name)] if i + len(name) < len(text) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return True
        i = text.find(name, i + 1)
    return False


def _extras(index, c, edges, mx, ddl):
    n9d = sum(fx["n9"][0] for fx in index.values())
    n9r = sum(fx["n9"][1] for fx in index.values())
    ids9 = set(i for fx in index.values() for i in fx.get("ids9", []))
    com = [sum(fx["comments"][i] for fx in index.values()) for i in (0, 1)]
    doc = [sum(fx["doclines"][i] for fx in index.values()) for i in (0, 1)]
    cyc_of = {m: i for i, comp in enumerate(mx.cycles) for m in comp}
    lazy_cyc = lazy_all = 0
    for mod, fx in index.items():
        for sc in fx["scopes"].values():
            for imp in sc.get("imp", []):
                tg = c.targets(imp, mod)
                if imp[1] and tg:
                    lazy_all += 1
                    lazy_cyc += any(mod in cyc_of and cyc_of.get(t) == cyc_of[mod] for t in tg)
    exc = [e for fx in index.values() for sc in fx["scopes"].values() for e in sc.get("exc", [])]
    broad = [e for e in exc if e[0] in ("broad", "bare")]
    layer_sum = {}
    for u in mx.units.get("layer.violations", []):
        a, b = c.layer_names[c.layer_of[u["m"]]], c.layer_names[c.layer_of[u["q"]]]
        layer_sum["%s→%s" % (a, b)] = layer_sum.get("%s→%s" % (a, b), 0) + 1
    return {
        "name9": {"decl": n9d, "ref": n9r, "total": n9d + n9r, "unique": len(ids9)},
        "comments": {"counted": com[0], "history": com[1]}, "doclines": {"lines": doc[0], "history": doc[1]},
        "lazy": {"all": lazy_all, "cycle": lazy_cyc, "other": lazy_all - lazy_cyc},
        "except": {"handlers": len(exc), "broad_all": len(broad), "broad_last_raise": sum(1 for e in broad if e[1]),
                   "noqa_ble001": sum(1 for e in broad if e[4]), "with_reason_code": sum(1 for e in broad if e[3])},
        "layer_edges_by_layer": layer_sum,
        "ddl_tables": sorted(ddl),
    }
