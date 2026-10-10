"""Solana liquidity-position reader."""
import base64
import hashlib
import json
import struct
import urllib.request

DLMM_PROG = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
MGR = "dlmm"
NAME = "Meteora DLMM"
WSOL = "So11111111111111111111111111111111111111112"

IX = {
    "b59d59438fb63448": ("add_liquidity", "add", 0, 1, 11),
    "e4a24e1c46db7473": ("add_liquidity2", "add", 0, 1, 9),
    "0703967f94283dc8": ("add_liquidity_by_strategy", "add", 0, 1, 11),
    "03dd95da6f8d76d5": ("add_liquidity_by_strategy2", "add", 0, 1, 9),
    "2905eeaf64e106cd": ("add_liquidity_by_strategy_one_side", "add", 0, 1, 8),
    "1c8cee63e7a21595": ("add_liquidity_by_weight", "add", 0, 1, 11),
    "d13b3f5b6fc899e4": ("add_liquidity_by_weight2", "add", 0, 1, 9),
    "5e9b6797465fdca5": ("add_liquidity_one_side", "add", 0, 1, 8),
    "a1c26754ab47fa9a": ("add_liquidity_one_side_precise", "add", 0, 1, 8),
    "2133a3c975627de7": ("add_liquidity_one_side_precise2", "add", 0, 1, 6),
    "849c841f4328e861": ("cancel_limit_order", "lo_cancel", 6, 0, 9),
    "a9204f8988e84689": ("claim_fee", "claim", 1, 0, 4),
    "70bf65ab1c907fbb": ("claim_fee2", "claim", 1, 0, 2),
    "955fb5f25e5a9ea2": ("claim_reward", "claim", 1, 0, 4),
    "be037f77b2579db7": ("claim_reward2", "claim", 1, 0, 2),
    "397c249b7ef95dab": ("close_limit_order_if_empty", "lo_close", 0, -1, 1),
    "7b86510031446262": ("close_position", "close", 0, 1, 4),
    "ae5a2373ba2893e2": ("close_position2", "close", 0, -1, 1),
    "3b7cd4765b986e9d": ("close_position_if_empty", "close", 0, -1, 1),
    "dbc0ea47bebf6650": ("initialize_position", "open", 1, 2, 3),
    "8f13f291d50f6873": ("initialize_position2", "open", 1, 2, 3),
    "fbbdbef475fe2394": ("initialize_position_by_operator", "open", 2, 3, 4),
    "2e527d92558de499": ("initialize_position_pda", "open", 2, 3, 4),
    "6cb021ba92e501c5": ("place_limit_order", "lo_place", 4, 0, 6),
    "5c04b0c177b95309": ("rebalance_liquidity", "rebalance", 0, 1, 9),
    "0a333d2370691855": ("remove_all_liquidity", "remove", 0, 1, 11),
    "5055d14818ceb16c": ("remove_liquidity", "remove", 0, 1, 11),
    "e6d7527ff165e392": ("remove_liquidity2", "remove", 0, 1, 9),
    "1a526698f04a691a": ("remove_liquidity_by_range", "remove", 0, 1, 11),
    "cc02c391359191cd": ("remove_liquidity_by_range2", "remove", 0, 1, 9),
}
MINT_IDX = {"cancel_limit_order": (4, 5), "claim_fee2": (7, 8), "claim_fee": (9, 10)}
for _n in ("add_liquidity", "add_liquidity2", "add_liquidity_by_strategy", "add_liquidity_by_strategy2", "add_liquidity_by_weight",
           "add_liquidity_by_weight2", "rebalance_liquidity", "remove_all_liquidity", "remove_liquidity", "remove_liquidity2",
           "remove_liquidity_by_range", "remove_liquidity_by_range2"):
    MINT_IDX[_n] = (7, 8)
DEP_KINDS = ("open", "add", "lo_place", "rebalance")
WD_KINDS = ("remove", "claim", "close", "lo_cancel", "lo_close", "rebalance")

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58I = {c: i for i, c in enumerate(_B58)}


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58I[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def is_pubkey(s) -> bool:
    if not isinstance(s, str) or not (32 <= len(s) <= 44) or any(c not in _B58I for c in s):
        return False
    try:
        return len(b58decode(s)) == 32
    except (KeyError, ValueError):
        return False


def short(pk: str) -> str:
    return (pk[:4] + "…" + pk[-4:]) if isinstance(pk, str) and len(pk) > 10 else str(pk)


def _ix_iter(tx: dict):
    msg = (tx.get("transaction") or {}).get("message") or {}
    for ins in msg.get("instructions") or []:
        yield ins
    for grp in ((tx.get("meta") or {}).get("innerInstructions") or []):
        for ins in grp.get("instructions") or []:
            yield ins


def extract(tx: dict, mine) -> dict:
    try:
        mine = set(mine or ())
        out = []
        for ins in _ix_iter(tx):
            if ins.get("programId") != DLMM_PROG or not isinstance(ins.get("data"), str):
                continue
            accs = [a.get("pubkey") if isinstance(a, dict) else a for a in (ins.get("accounts") or [])]
            try:
                data = b58decode(ins["data"])
            except (KeyError, ValueError):
                continue
            ent = IX.get(data[:8].hex())
            if not ent:
                continue
            name, kind, pi, qi, wi = ent
            if pi >= len(accs):
                continue
            who = accs[wi] if 0 <= wi < len(accs) else None
            if who not in mine and not (set(accs) & mine):
                continue
            bps = None
            if name.startswith("remove_liquidity_by_range") and len(data) >= 18:
                bps = struct.unpack_from("<H", data, 16)[0]
            elif name == "remove_all_liquidity":
                bps = 10000
            mi = MINT_IDX.get(name)
            mints = [accs[mi[0]], accs[mi[1]]] if mi and mi[1] < len(accs) else None
            out.append([kind, name, accs[pi], accs[qi] if 0 <= qi < len(accs) else None, bps, mints])
        return {"prog": MGR, "ixs": out} if out else None
    except Exception:
        return None


def lp_detect(rec: dict, mine) -> dict:
    lp = (rec or {}).get("lp") or {}
    if lp.get("prog") != MGR or not lp.get("ixs"):
        return None
    who = ""
    for d in rec.get("deltas") or []:
        if d.get("owner") in mine:
            who = d["owner"]
            break
    if not who:
        who = rec.get("fee_payer") if rec.get("fee_payer") in mine else ""
    ixs = [x for x in lp["ixs"] if isinstance(x, (list, tuple)) and len(x) >= 3 and is_pubkey(x[2])]
    if not ixs:
        return None
    ids = sorted({x[2] for x in ixs})
    mint = sorted({x[2] for x in ixs if x[0] in ("open", "lo_place")})
    burn = sorted({x[2] for x in ixs if x[0] in ("close", "lo_close")})
    dep_ids = sorted({x[2] for x in ixs if x[0] in DEP_KINDS})
    wd_ids = sorted({x[2] for x in ixs if x[0] in WD_KINDS})
    frac = {}
    for x in ixs:
        if x[0] == "remove" and x[1] == "remove_all_liquidity":
            frac[x[2]] = [1, 1]
        elif x[0] == "remove":
            if frac.get(x[2]) != [1, 1]:
                frac[x[2]] = None
        elif x[0] == "rebalance":
            frac[x[2]] = None
    for i in wd_ids:
        if i not in frac and any(x[0] == "claim" and x[2] == i for x in ixs):
            frac[i] = [0, 1]
    frac = {k: v for k, v in frac.items() if v is not None}
    pairs = sorted({x[3] for x in ixs if len(x) > 3 and x[3]})
    mints = {}
    for x in ixs:
        if len(x) > 5 and isinstance(x[5], (list, tuple)) and len(x[5]) == 2 and all(is_pubkey(m) for m in x[5]):
            mints.setdefault(x[2], list(x[5]))
    unk_loc = f"lp:sol:{MGR}:?{who}"
    if len(dep_ids) == 1:
        dep_loc = f"lp:sol:{MGR}:{dep_ids[0]}"
    elif not dep_ids and len(wd_ids) == 1:
        dep_loc = f"lp:sol:{MGR}:{wd_ids[0]}"
    elif not dep_ids:
        dep_loc = unk_loc
    else:
        dep_loc = f"lp:sol:{MGR}:multi"
    kinds = {x[0] for x in ixs}
    return {"mgr": MGR, "proto": "meteora_dlmm", "name": NAME, "ids": ids, "mint": mint, "burn": burn, "gone": [],
            "dep_ids": dep_ids, "wd_ids": wd_ids,
            "actions": sorted({"MINT" if k in ("open", "lo_place") else "INCREASE" if k == "add" else
                               "DECREASE" if k in ("remove", "lo_cancel", "rebalance") else
                               "COLLECT" if k == "claim" else "BURN" for k in kinds}),
            "liq": [], "frac": frac, "who": who, "pairs": pairs, "mints": mints,
            "limit": bool(kinds & {"lo_place", "lo_cancel", "lo_close"}),
            "loc": (f"lp:sol:{MGR}:{ids[0]}" if len(ids) == 1 else f"lp:sol:{MGR}:multi"),
            "dep_loc": dep_loc, "unk_loc": unk_loc}


_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def _on_curve(b: bytes) -> bool:
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return True
    return pow(x2, (_P - 1) // 2, _P) == 1


def find_pda(seeds, program: str):
    prog = b58decode(program)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + prog + b"ProgramDerivedAddress").digest()
        if not _on_curve(h):
            return b58encode(h), bump
    return None, None


def bin_array_pda(lb_pair: str, index: int) -> str:
    return find_pda([b"bin_array", b58decode(lb_pair), struct.pack("<q", index)], DLMM_PROG)[0]


def bin_array_index(bin_id: int) -> int:
    return bin_id // 70


def _rpc(urls, method, params, timeout=20):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for u in urls or []:
        try:
            req = urllib.request.Request(u, data=body, headers={"Content-Type": "application/json", "User-Agent": "tj-bot/0.1"})
            import bf_engine as _bfe9
            with _bfe9.sol_open(req, timeout, method, sol=True) as r:
                d = json.loads(_bfe9.common.read_capped(r).decode())
            if "result" in d:
                return d["result"]
        except Exception:
            continue
    return None


def _accounts(urls, keys):
    res = _rpc(urls, "getMultipleAccounts", [keys, {"encoding": "base64"}])
    vals = (res or {}).get("value") if isinstance(res, dict) else None
    if not isinstance(vals, list) or len(vals) != len(keys):
        return None
    out = []
    for v in vals:
        if not v:
            out.append(None)
            continue
        try:
            out.append((v.get("owner"), base64.b64decode(v["data"][0])))
        except Exception:
            out.append(None)
    return out


DISC_POSITION_V2 = bytes([117, 176, 212, 199, 245, 180, 133, 182])
DISC_LBPAIR = bytes([33, 11, 49, 98, 181, 101, 177, 13])
DISC_BINARRAY = bytes([92, 142, 92, 220, 5, 148, 70, 181])
DISC_LIMIT_ORDER = bytes([137, 183, 212, 91, 115, 29, 141, 227])


def parse_position(b: bytes) -> dict:
    if len(b) < 7920 or b[:8] != DISC_POSITION_V2:
        return {}
    shares = [int.from_bytes(b[72 + 16 * i:88 + 16 * i], "little") for i in range(70)]
    fees = []
    for i in range(70):
        o = 4552 + 48 * i
        fees.append((int.from_bytes(b[o:o + 16], "little"), int.from_bytes(b[o + 16:o + 32], "little"),
                     struct.unpack_from("<Q", b, o + 32)[0], struct.unpack_from("<Q", b, o + 40)[0]))
    lo, hi = struct.unpack_from("<ii", b, 7912)
    return {"lb_pair": b58encode(b[8:40]), "owner": b58encode(b[40:72]), "shares": shares, "fees": fees,
            "lower": lo, "upper": hi}


def parse_lbpair(b: bytes) -> dict:
    if len(b) < 216 or b[:8] != DISC_LBPAIR:
        return {}
    active, step = struct.unpack_from("<iH", b, 76)
    return {"active_id": active, "bin_step": step, "mint_x": b58encode(b[88:120]), "mint_y": b58encode(b[120:152])}


def parse_bin_array(b: bytes) -> dict:
    if len(b) < 56 + 144 * 70 or b[:8] != DISC_BINARRAY:
        return {}
    idx = struct.unpack_from("<q", b, 8)[0]
    out = {}
    for i in range(70):
        o = 56 + 144 * i
        ax, ay = struct.unpack_from("<QQ", b, o)
        sup = int.from_bytes(b[o + 32:o + 48], "little")
        fx = int.from_bytes(b[o + 80:o + 96], "little")
        fy = int.from_bytes(b[o + 96:o + 112], "little")
        out[idx * 70 + i] = (ax, ay, sup, fx, fy)
    return {"index": idx, "lb_pair": b58encode(b[24:56]), "bins": out}


def position_amounts(pos: dict, bins: dict):
    ax = ay = fx = fy = 0
    ok = pos["upper"] - pos["lower"] < 70
    for i in range(70):
        bid = pos["lower"] + i
        if bid > pos["upper"]:
            break
        sh = pos["shares"][i]
        fxc, fyc, fxp, fyp = pos["fees"][i]
        fx += fxp
        fy += fyp
        if not sh:
            continue
        bn = bins.get(bid)
        if bn is None:
            ok = False
            continue
        bx, by, sup, fxs, fys = bn
        if sup:
            ax += bx * sh // sup
            ay += by * sh // sup
        fx += ((sh >> 64) * ((fxs - fxc) % (1 << 128))) >> 64
        fy += ((sh >> 64) * ((fys - fyc) % (1 << 128))) >> 64
    return ax, ay, fx, fy, ok


def read_dlmm_position(urls, pos_key: str, meta_of=None) -> dict:
    try:
        acc = _accounts(urls, [pos_key])
        if acc is None:
            return {}
        if acc[0] is None:
            return {"proto": "meteora_dlmm", "liquidity": "0", "closedOnchain": True}
        owner_prog, raw = acc[0]
        if owner_prog != DLMM_PROG:
            return {}
        if raw[:8] == DISC_LIMIT_ORDER:
            return {"proto": "meteora_dlmm", "limitOrder": True, "liquidity": "1"}
        pos = parse_position(raw)
        if not pos:
            return {}
        idxs = sorted({bin_array_index(pos["lower"]), bin_array_index(pos["upper"])})
        keys = [pos["lb_pair"]] + [bin_array_pda(pos["lb_pair"], i) for i in idxs]
        accs = _accounts(urls, keys)
        if not accs or not accs[0]:
            return {}
        pair = parse_lbpair(accs[0][1])
        if not pair:
            return {}
        bins = {}
        for a in accs[1:]:
            if a:
                ba = parse_bin_array(a[1])
                if ba and ba["lb_pair"] == pos["lb_pair"]:
                    bins.update(ba["bins"])
        ax, ay, fx, fy, ok = position_amounts(pos, bins)
        if not ok:
            return {}
        liq = sum(pos["shares"])
        mx = (meta_of or (lambda m: {}))(pair["mint_x"]) or {}
        my = (meta_of or (lambda m: {}))(pair["mint_y"]) or {}
        if mx.get("decimals") is None or my.get("decimals") is None:
            return {}
        d0, d1 = int(mx["decimals"]), int(my["decimals"])
        step = pair["bin_step"]

        def px(bid):
            return (1 + step / 10000) ** bid * 10 ** d0 / 10 ** d1
        return {"proto": "meteora_dlmm", "token0": pair["mint_x"], "token1": pair["mint_y"],
                "sym0": mx.get("symbol") or pair["mint_x"][:6], "sym1": my.get("symbol") or pair["mint_y"][:6],
                "dec0": d0, "dec1": d1, "binStep": step, "lbPair": pos["lb_pair"], "owner": pos["owner"],
                "tickLower": pos["lower"], "tickUpper": pos["upper"], "tick": pair["active_id"],
                "liquidity": str(liq), "amount0": ax / 10 ** d0, "amount1": ay / 10 ** d1,
                "fees0": fx / 10 ** d0, "fees1": fy / 10 ** d1, "price": px(pair["active_id"]),
                "priceLower": px(pos["lower"]), "priceUpper": px(pos["upper"] + 1),
                "inRange": pos["lower"] <= pair["active_id"] <= pos["upper"], "feesOk": ok, "amountsOk": ok}
    except Exception:
        return {}
