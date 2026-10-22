from __future__ import annotations

import ast
import json
import os

import _arch_py_defs as D
import _arch_py_metrics as M
import _arch_py_ratchet as R
import _arch_scope as _S

SPLIT_KEYS = ("import.cycle_edges", "layer.violations")
PROOF_FILE = "py_split_proof.json"
R.HARD.setdefault("split.proof", ("imports", "분할 승계 표·근거 모양(layers.json split_of 모듈이 있음 · 원래 모듈은 분할 모듈이 아님 · "
                                              "근거 파일 = 원래 모듈마다 항목 · 옮긴 이름이 두 분할 모듈에 겹치지 않음)"))
R.HARD.setdefault("split.internal", ("imports", "분할 계열(원래 모듈 + 분할 모듈) 안 간선 = 허용 표(대리 이름 표 · 치환 근거) 안"))
R.HARD.setdefault("split.cycle", ("imports", "분할 계열 안에서만 닫히는 순환 금지(허용 표와 무관)"))


def _scan(tree, mods):
    _S.annotate(tree)
    uses, scopes, held = {}, {}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in mods and not n.level:
            uses.setdefault(n.module, [set(), False])[0].update(a.name for a in n.names)
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            r = getattr(n.value, "_r", ("unbound",))
            if r[0] == "mod" and r[1] in mods:
                uses.setdefault(r[1], [set(), False])[0].add(n.attr)
                for qq in {n.value._q, "@" + n.value._top}:
                    scopes.setdefault(qq, {"attr": {}, "top": set()})["attr"].setdefault(r[1], set()).add(n.attr)
                held.add(id(n.value))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Name):
            continue
        r = getattr(n, "_r", ("unbound",))
        if r[0] in ("mod", "from") and getattr(n, "_rs", None) == "module":
            for qq in {n._q, "@" + n._top}:
                scopes.setdefault(qq, {"attr": {}, "top": set()})["top"].add(r[1])
        if r[0] == "mod":
            if r[1] in mods and id(n) not in held:
                uses.setdefault(r[1], [set(), False])[1] = True
        elif r[0] == "amb":
            for d in r[1]:
                m = d.split(":")[1] if d.count(":") >= 1 else ""
                if m in mods:
                    uses.setdefault(m, [set(), False])[1] = True
    return uses, scopes


def _in_scope(qq, q):
    return qq == q or qq == "@" + q or (q != D.MODULE_Q and qq.startswith(q + "."))


class _Base(ast.NodeTransformer):

    def __init__(self, sp, ctx):
        self.sp, self.home = sp, sp.family.get(ctx)

    def visit_Attribute(self, node):
        v, sp = node.value, self.sp
        r = getattr(v, "_r", ("unbound",)) if isinstance(v, ast.Name) else ("",)
        if r[0] == "mod" and node.attr in sp.moved.get(r[1], ()):
            o = sp.split_of[r[1]]
            new = ast.Name(id=node.attr, ctx=node.ctx) if self.home == o else \
                ast.Attribute(value=ast.Name(id=o, ctx=ast.Load()), attr=node.attr, ctx=node.ctx)
            return ast.copy_location(new, node)
        return self.generic_visit(node)

    def visit_Import(self, node):
        sp = self.sp
        if self.home is None and node.names and all(a.name in sp.split_of and not a.asname for a in node.names):
            origins = {sp.split_of[a.name] for a in node.names}
            if len(origins) == 1:
                return ast.copy_location(ast.Import(names=[ast.alias(name=origins.pop())]), node)
        return node

    def visit_ImportFrom(self, node):
        sp = self.sp
        if self.home is None and not node.level and node.module in sp.split_of \
                and all(a.name in sp.moved.get(node.module, ()) for a in node.names):
            return ast.copy_location(ast.ImportFrom(module=sp.split_of[node.module], names=node.names, level=0), node)
        return node


class Split:

    def __init__(self, split_of, proof, index, rules, layers, read_src):
        self.index, self.read_src = index, read_src
        self.problems, self.notes, self.stale = [], [], []
        self.split_of = {a: o for a, o in split_of.items() if isinstance(a, str) and isinstance(o, str)} \
            if isinstance(split_of, dict) else {}
        if not isinstance(split_of, dict) or len(self.split_of) != len(split_of):
            self.problems.append("layers.json split_of = {분할 모듈: 원래 모듈} 글자 표여야 함")
        self.family = {}
        for a, o in sorted(self.split_of.items()):
            self.family[a] = self.family[o] = o
            if a in self.split_of.values():
                self.problems.append("split_of: %s 가 원래 모듈이면서 분할 모듈(사슬 금지 — 원래 모듈 하나로 적기)" % a)
            if a not in index:
                self.problems.append("split_of: 분할 모듈 src/%s.py 가 없음" % a)
        self._edges(index, rules, layers)
        self.moved, self.ev, self._uses = {}, set(), {}
        self._proof(proof if isinstance(proof, dict) else {})
        self.allow = {(o, a) for a, o in self.split_of.items() if self.moved.get(a)}
        self.allow |= {(m, to) for m, to, why in self.ev if why == "subst" and self.family.get(m) is not None
                       and self.family.get(m) == self.family.get(to) and to in self.split_of}
        self.allow |= {(m, to) for m, to, why in self.ev if why == "back" and m in self.split_of and self.split_of[m] == to}

    def _edges(self, index, rules, layers):
        c = M._Ctx(index, rules, layers)
        self.edges, self.scope_imps = {}, {}
        for mod, fx in index.items():
            for q, sc in fx.get("scopes", {}).items():
                for imp in sc.get("imp", []):
                    tg = c.targets(imp, mod)
                    self.edges.setdefault(mod, set()).update(tg)
                    self.scope_imps.setdefault(mod, {}).setdefault(q, set()).update(tg)
        self.path = c.path

    def _proof(self, proof):
        origins = proof.get("origins") if isinstance(proof.get("origins"), dict) else {}
        owner = {}
        for o in sorted(set(self.split_of.values())):
            ent = origins.get(o)
            if not isinstance(ent, dict):
                self.problems.append("근거 파일 %s 에 원래 모듈 %s 항목 없음(tools/refactor/move_proof.py --emit)" % (PROOF_FILE, o))
                continue
            for a, names in sorted((ent.get("moved") or {}).items()):
                if self.split_of.get(a) != o or not isinstance(names, list):
                    self.problems.append("근거 moved.%s: split_of 에서 %s 를 가리키는 분할 모듈이 아님" % (a, o))
                    continue
                for n in names:
                    if (o, n) in owner and owner[(o, n)] != a:
                        self.problems.append("옮긴 이름 %s.%s 가 %s 와 %s 둘에 겹침" % (o, n, owner[(o, n)], a))
                    owner[(o, n)] = a
                    self.moved.setdefault(a, set()).add(n)
            for e in ent.get("edges") or []:
                self._check_ev(o, e)

    def _check_ev(self, o, e):
        if not isinstance(e, dict) or not all(isinstance(e.get(x), str) for x in ("m", "to", "why", "q")):
            self.problems.append("근거 줄 모양 틀림: %s" % json.dumps(e, ensure_ascii=False)[:120])
            return
        m, to, why, q = e["m"], e["to"], e["why"], e["q"]
        imps = self.scope_imps.get(m, {})
        if self.family.get(m) != o:
            ok = False
        elif why == "import":
            ok = any(to in tg for qq, tg in imps.items() if _in_scope(qq, q))
        elif why == "top":
            ok = to in imps.get(D.MODULE_Q, ()) and any(to in sc["top"] for qq, sc in self.scopes(m).items() if _in_scope(qq, q))
        elif why == "subst":
            ok = to in self.edges.get(m, ()) and any(sc["attr"].get(to, set()) & self.moved.get(to, set())
                                                     for qq, sc in self.scopes(m).items() if _in_scope(qq, q))
        elif why == "back":
            gone = set().union(*[self.moved.get(a, set()) for a, oo in self.split_of.items() if oo == to] or [set()])
            ok = self.split_of.get(m) == to and to in self.edges.get(m, ()) and any(
                sc["attr"].get(to, set()) - gone for qq, sc in self.scopes(m).items() if _in_scope(qq, q))
        else:
            ok = False
        if ok:
            self.ev.add((m, to, why))
        else:
            self.stale.append("%s → %s [%s · %s]" % (m, to, why, q))

    def _scan_of(self, mod):
        if mod not in self._uses:
            try:
                self._uses[mod] = _scan(ast.parse(self.read_src(self.path(mod))), set(self.split_of) | set(self.split_of.values()))
            except (OSError, SyntaxError, UnicodeDecodeError):
                self._uses[mod] = ({}, {})
        return self._uses[mod]

    def uses(self, mod):
        return self._scan_of(mod)[0]

    def scopes(self, mod):
        return self._scan_of(mod)[1]

    def incoming_ok(self, x, a):
        got = self.uses(x).get(a)
        return bool(got and got[0] and not got[1] and got[0] <= self.moved.get(a, set()))

    def outgoing_ok(self, a, y):
        return (a, y, "import") in self.ev or (a, y, "top") in self.ev

    def hard(self):
        out = {"split.proof": list(self.problems)}
        bad = []
        for m in sorted(self.edges):
            for q in sorted(self.edges[m]):
                if self.family.get(m) is not None and self.family.get(m) == self.family.get(q) and (m, q) not in self.allow:
                    bad.append("%s → %s — 분할 계열 안 간선인데 증명 없음(대리 이름 표·치환 근거 밖%s)" % (
                        m, q, " · 분할 모듈이 원래 모듈을 부르는 꼴 = back 근거(원래 모듈의 남은 이름을 읽는 위층 분할 · move_proof ⑦)가 있을 때만" if q == self.family[q] else ""))
        out["split.internal"] = bad
        cyc = []
        for o in sorted(set(self.split_of.values())):
            fam = {x for x, oo in self.family.items() if oo == o}
            sub = {m: self.edges.get(m, set()) & fam for m in fam}
            cyc += ["분할 계열(%s) 안 순환: %s" % (o, " · ".join(c)) for c in M._tarjan(fam, sub)]
        out["split.cycle"] = cyc
        return {k: v for k, v in out.items() if v}

    def normalize_h(self, metrics):
        touched = set(self.family) | {x for x, tg in self.edges.items() if tg & set(self.split_of)}
        hmap = {}
        for mod in sorted(touched & set(self.index)):
            try:
                tree = _Base(self, mod).visit(_S.annotate(ast.parse(self.read_src(self.path(mod)))))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            memo = {}
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    hmap[(mod, n.lineno)] = D.fingerprint(n, memo)
        for units in metrics.units.values():
            for u in units:
                if u.get("h") and u["m"] in touched and ":" in u.get("at", ""):
                    h = hmap.get((u["m"], int(u["at"].rsplit(":", 1)[1])))
                    if h:
                        u["h"] = h


def fold_units(sp, k, units, base_lines):
    if sp is None or k not in SPLIT_KEYS:
        return units
    base = {(b["m"], b["q"]) for b in base_lines}
    out, seen = [], set()

    def put(u):
        if (u["m"], u["q"]) not in seen:
            seen.add((u["m"], u["q"]))
            out.append(u)
    for u in units:
        m, q = u["m"], u["q"]
        fm, fq = sp.family.get(m), sp.family.get(q)
        if (m, q) in base or (fm is None and fq is None):
            put(u)
            continue
        if fm is not None and fm == fq:
            if (m, q) in sp.allow:
                sp.notes.append("%s %s → %s = 분할 계열 안 허용 간선(비교 밖 · split.internal 이 검사)" % (k, m, q))
                continue
            put(u)
            continue
        nm, nq = m, q
        if fq is not None and q != fq and sp.incoming_ok(m, q):
            nq = fq
        if fm is not None and m != fm and sp.outgoing_ok(m, q):
            nm = fm
        if (nm, nq) != (m, q) and (nm, nq) in base:
            sp.notes.append("%s %s → %s = 기준선 %s → %s 승계(%s)" % (
                k, m, q, nm, nq, "치환 꼴 사용" if nq != q else "옮긴 import 근거"))
            put(dict(u, m=nm, q=nq))
        else:
            put(dict(u, t="x") if fm is not None and m != fm else u)
    return out


def fold_count(nodes, split_of):
    so = split_of if isinstance(split_of, dict) else {}
    return len({so.get(n, n) for n in nodes})


def attach(st, src_dir):
    so = (st.layers or {}).get("split_of") or {}
    if not so or st.metrics is None:
        return None
    proof, path = {}, os.path.join(os.path.dirname(os.path.abspath(__file__)), "arch_baseline", PROOF_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            proof = R.loads(f.read())
    except (OSError, ValueError):
        proof = {}
    root = os.path.dirname(os.path.abspath(src_dir))

    def read_src(rel):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read()
    good = {m: fx for m, fx in st.index.items() if "error" not in fx}
    sp = Split(so, proof, good, st.rules, st.layers, read_src)
    sp.normalize_h(st.metrics)
    for k, bad in sp.hard().items():
        st.metrics.hard.setdefault(k, []).extend(bad)
    return sp


def report(sp):
    if sp is None:
        return ["분할 승계 꺼짐(layers.json split_of 비어 있음)"]
    out = ["분할 표 %d · 허용 표 %d · 검증된 근거 %d · 낡은 근거 %d" % (len(sp.split_of), len(sp.allow), len(sp.ev), len(sp.stale))]
    out += ["허용 %s → %s" % x for x in sorted(sp.allow)]
    out += ["메모 " + x for x in sp.notes]
    out += ["낡은 근거(승계 안 씀) " + x for x in sp.stale]
    return out
