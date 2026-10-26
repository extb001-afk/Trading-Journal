import json
import os

import paths

__all__ = ["SEED_SET_LISTS", "SEED_ID_LISTS", "seed_set_key", "seed_list_kind", "seed_merge", "seed_canon", "seed_json"]


SEED_SET_LISTS = {
    "bridge_contracts.json": ((),),
    "sale_contracts.json": (("cca_factories",), ("chains",)),
    "xchain_bridges.json": (("sol_lp_markers",), ("evm_contracts", "*", "chains")),
    "zero_value_companions.json": (("tokens",),),
}
SEED_ID_LISTS = {"coverage/api_limits.json": (("exchanges",), ("chains",), ("perps",))}


def _seed_path_in(path: tuple, pats) -> bool:
    return any(len(p) == len(path) and all(a == "*" or a == b for a, b in zip(p, path)) for p in pats)


def seed_set_key(v):
    if isinstance(v, str):
        s = v.strip()
        return s.lower() if s[:2].lower() == "0x" else s
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def seed_list_kind(rel, path: tuple) -> str:
    r9 = str(rel or "").replace(os.sep, "/")
    if _seed_path_in(path, SEED_SET_LISTS.get(r9, ())):
        return "set"
    if _seed_path_in(path, SEED_ID_LISTS.get(r9, ())):
        return "id"
    return ""


def seed_merge(base, over, rel=None, _path=()):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = seed_merge(base[k], v, rel, _path + (str(k),)) if k in base else v
        return out
    if rel and isinstance(base, list) and isinstance(over, list):
        kind = seed_list_kind(rel, _path)
        if kind == "set":
            out, seen = [], set()
            for v in list(base) + list(over):
                k9 = seed_set_key(v)
                if k9 in seen:
                    continue
                seen.add(k9)
                out.append(k9 if isinstance(v, str) else v)
            return out
        if kind == "id" and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in list(base) + list(over)):
            ids = {x["id"] for x in over}
            return list(over) + [x for x in base if x["id"] not in ids]
    return over


def seed_canon(o, rel=None, _path=()):
    if isinstance(o, dict):
        return {k: seed_canon(v, rel, _path + (str(k),)) for k, v in o.items()}
    if isinstance(o, list):
        if rel and seed_list_kind(rel, _path) == "set":
            return sorted({seed_set_key(v) for v in o})
        return [seed_canon(v, rel, _path) for v in o]
    return o


def seed_json(rel: str, default=None, base_dir: str = None, strict: bool = False):
    def _one(p, strict9):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return True, json.load(f)
        except FileNotFoundError:
            return False, None
        except (json.JSONDecodeError, OSError, ValueError) as e:
            if strict9:
                raise SystemExit(f"seed 파일 손상: {p}: {e}") from e
            return False, None
    root = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hb, b = _one(os.path.join(root, "seed", rel), strict)
    ho, o = _one(paths.state("seed_local", rel), True)
    if not hb and not ho:
        return default
    if not ho:
        return b
    if not hb:
        return o
    return seed_merge(b, o, rel)
