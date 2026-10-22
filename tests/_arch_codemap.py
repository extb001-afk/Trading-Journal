#!/usr/bin/env python3
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
LAYERS = os.path.join(HERE, "arch_baseline", "layers.json")
OUT = os.path.join("public", "docs", "CODEMAP.md")
_RESP_MAX = 140


def _modname(rel: str) -> str:
    parts = rel[len("src/"):-len(".py")].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def module_files(root: str) -> list[str]:
    out = []
    for dp, dn, fns in os.walk(os.path.join(root, "src")):
        dn[:] = sorted(d for d in dn if d != "__pycache__" and not d.startswith("."))
        rel = os.path.relpath(dp, root).replace(os.sep, "/")
        out += [rel + "/" + f for f in fns if f.endswith(".py")]
    return sorted(out, key=_modname)


def _resolve(pkg: str, node: ast.ImportFrom, names: set[str]) -> set[str]:
    if node.level:
        parts = pkg.split(".") if pkg else []
        parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
        base = ".".join(parts + ([node.module] if node.module else []))
    else:
        base = node.module or ""
    out = {base + "." + a.name for a in node.names if base and base + "." + a.name in names}
    return out or ({base} if base in names else set())


def _imports(mod: str, pkg: str, tree: ast.Module, names: set[str]) -> tuple[set[str], set[str]]:
    top, lazy = set(), set()
    stack = [(st, False) for st in tree.body]
    while stack:
        st, in_fn = stack.pop()
        if isinstance(st, ast.Import):
            (lazy if in_fn else top).update({a.name for a in st.names if a.name in names} - {mod})
        elif isinstance(st, ast.ImportFrom):
            (lazy if in_fn else top).update(_resolve(pkg, st, names) - {mod})
        else:
            fn = in_fn or isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))
            for block in ("body", "orelse", "finalbody"):
                stack += [(x, fn) for x in getattr(st, block, None) or [] if isinstance(x, ast.stmt)]
            stack += [(x, fn) for h in getattr(st, "handlers", None) or [] for x in h.body]
            stack += [(x, fn) for c in getattr(st, "cases", None) or [] for x in c.body]
    return top, lazy - top


def _public_api(tree: ast.Module) -> list[str]:
    for st in tree.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in st.targets) \
                and isinstance(st.value, (ast.List, ast.Tuple)):
            return sorted(e.value for e in st.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return sorted(st.name for st in tree.body
                  if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not st.name.startswith("_"))


_HISTORY = re.compile(r"오너|\d{4}-\d{2}-\d{2}")


def responsibility(doc: str) -> str:
    line = next((ln.strip() for ln in (doc or "").splitlines() if ln.strip()), "")
    prev = None
    while prev != line:
        prev, line = line, re.sub(r"\([^()]*\)", "", line)
    line = re.sub(r"\([^()]*$", "", line)
    parts = re.split(r"( — |\. )", line)
    keep = []
    for i in range(0, len(parts), 2):
        if _HISTORY.search(parts[i]):
            break
        keep += parts[max(i - 1, 0):i + 1] if i else [parts[0]]
    line = re.sub(r"\s+", " ", "".join(keep)).strip(" ·—:-,.").replace("|", "\\|")
    return (line[:_RESP_MAX] + "…") if len(line) > _RESP_MAX else (line or "—")


OWNER_INFO = re.compile(r"오너|0x[0-9a-fA-F]{40}|(?<!\d)\d{9,}(?!\d)|[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")


def modules(root: str) -> list[dict]:
    files = module_files(root)
    names = {_modname(f) for f in files}
    out = []
    for rel in files:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = f.read()
        tree = ast.parse(text, rel)
        mod = _modname(rel)
        pkg = mod if rel.endswith("/__init__.py") else mod.rpartition(".")[0]
        top, lazy = _imports(mod, pkg, tree, names)
        out.append({"name": mod, "path": rel, "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                    "resp": responsibility(ast.get_docstring(tree) or ""), "api": _public_api(tree), "deps": sorted(top),
                    "lazy": sorted(lazy)})
    return out


def load_layers(path: str | None):
    if not path or not os.path.isfile(path):
        return (lambda m: "—"), "계층 표 없음(layers.json — G0a) → 모두 —"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return (lambda m: "?"), f"layers.json 을 못 읽음({type(e).__name__}) → 모두 ?"
    pairs = _layer_pairs(data)
    if not pairs:
        return (lambda m: "?"), "layers.json 꼴을 모름 → 모두 ?"
    exact = {_norm(p): lay for p, lay in pairs if not any(c in p for c in "*?[")}
    pats = sorted(((_norm(p), lay) for p, lay in pairs if any(c in p for c in "*?[")), key=lambda t: (-len(t[0].replace("*", "")), t[0]))

    def layer_of(m: str) -> str:
        return exact.get(m) or next((lay for p, lay in pats if fnmatch.fnmatchcase(m, p)), "—")
    return layer_of, "계층 표 = public/tests/arch_baseline/layers.json"


def _norm(p: str) -> str:
    p = p[4:] if p.startswith("src/") else p
    p = p[:-3] if p.endswith(".py") else p
    return p.replace("/", ".")


def _layer_pairs(data) -> list[tuple[str, str]]:
    if isinstance(data, dict) and isinstance(data.get("modules"), dict):
        return [(m, str(v)) for m, v in data["modules"].items()]
    lay = data.get("layers") if isinstance(data, dict) else None
    if isinstance(lay, dict):
        return [(m, k) for k, v in lay.items() for m in (v.get("modules", []) if isinstance(v, dict) else v or [])]
    if isinstance(lay, list):
        out = []
        for e in lay:
            if isinstance(e, dict):
                name = e.get("name") or e.get("layer") or e.get("id")
                out += [(m, str(name)) for m in (e.get("modules") or e.get("members") or e.get("patterns") or [])]
        return out
    if isinstance(data, dict) and data and all(isinstance(v, str) for v in data.values()):
        return list(data.items())
    if isinstance(data, dict) and data and all(isinstance(v, list) for v in data.values()):
        return [(m, k) for k, v in data.items() for m in v if isinstance(m, str)]
    return []


def render(root: str, layers_path: str | None = LAYERS) -> str:
    return render_text(modules(root), load_layers(layers_path))


def render_text(mods: list[dict], layers: tuple) -> str:
    layer_of, layer_state = layers
    out = ["# CODEMAP — src 모듈 지도", "",
           "자동 생성 — 손으로 고치지 말 것. 다시 만들기: `python3 public/tests/_arch_codemap.py --write` · "
           "같은지 검사: `python3 public/tests/test_arch_codemap.py`", "",
           "열: 줄 수 · 계층(public/tests/arch_baseline/layers.json · 없으면 —) · 책임(모듈 독스트링 첫 줄) · "
           "공개 API(`__all__` 또는 최상위 공개 def/class) · 의존(내부 모듈 · 최상위 import / 함수 안 지연 import)", "",
           f"모듈 {len(mods)}개 · 줄 {sum(m['lines'] for m in mods):,} · {layer_state}", "",
           "| 모듈 | 줄 | 계층 | 책임 |", "|---|---:|---|---|"]
    out += [f"| `{m['name']}` | {m['lines']} | {layer_of(m['name'])} | {m['resp']} |" for m in mods]
    out += ["", "## 모듈별 공개 API · 의존", ""]
    for m in mods:
        out.append(f"### `{m['name']}` — {m['path']}")
        out.append(f"- 공개 API({len(m['api'])}): " + (" · ".join(f"`{a}`" for a in m["api"]) or "—"))
        out.append("- 의존: " + (" · ".join(f"`{d}`" for d in m["deps"]) or "—"))
        if m["lazy"]:
            out.append("- 지연 import: " + " · ".join(f"`{d}`" for d in m["lazy"]))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    root = os.path.abspath(os.path.join(HERE, "..", ".."))
    if not os.path.isfile(os.path.join(root, "src", "version.py")) or os.path.basename(os.path.dirname(HERE)) != "public":
        print("저장소 배치(…/public/tests)에서만 — 공개판 배치는 독스트링이 지워져 CODEMAP 을 만들지 않음")
        return 1
    text = render(root)
    state = load_layers(LAYERS)[1]
    if "?" in state:
        print(f"경고: {state} — _arch_codemap.load_layers 를 layers.json 꼴에 맞춰 고쳐라", file=sys.stderr)
    if "--write" in argv:
        with open(os.path.join(root, OUT), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{OUT} 씀 — {text.count(chr(10))}줄 · {len(text.encode('utf-8')):,}바이트 · {state}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
