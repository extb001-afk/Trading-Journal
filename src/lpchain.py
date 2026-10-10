"""On-chain liquidity-position reader."""
import json
import math
import urllib.parse
import urllib.request

import common
import lpdec

SEL = {k: lpdec.selector(k) for k in (
    "getPoolAndPositionInfo(uint256)", "getPositionLiquidity(uint256)", "getSlot0(bytes32)",
    "getFeeGrowthInside(bytes32,int24,int24)", "getPositionInfo(bytes32,address,int24,int24,bytes32)",
    "positions(uint256)", "slot0()", "feeGrowthGlobal0X128()", "feeGrowthGlobal1X128()", "ticks(int24)",
    "getPool(address,address,uint24)", "getPool(address,address,int24)", "symbol()", "decimals()", "ownerOf(uint256)",
    "liquidity()",
    "token0()", "token1()", "getReserves()", "totalSupply()", "stable()", "claimable0(address)", "claimable1(address)",
    "earned(address)", "earned(address,uint256)", "rewardToken()", "pendingCake(uint256)")}
Q96 = 2 ** 96
Q128 = 2 ** 128
M256 = 2 ** 256
ZERO = "0x0000000000000000000000000000000000000000"


def _rpcs(cfg: dict, chain: str) -> list:
    if chain == "bsc":
        return list((cfg.get("bsc") or {}).get("detail_rpcs") or [])
    c = (cfg.get("chains") or {}).get(chain) or {}
    out = list(c.get("rpcs") or [])
    if c.get("rpc") and c["rpc"] not in out:
        out.append(c["rpc"])
    if not out:
        try:
            from evm_watch import RpcSynthMixin
            out = list(RpcSynthMixin.RPC_DEFAULT.get(chain) or [])
        except Exception:
            out = []
    return out


def eth_call(cfg: dict, chain: str, to: str, data: str, timeout: int = 10):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                       "params": [{"to": to, "data": "0x" + data.replace("0x", "")}, "latest"]}).encode()
    import bf_engine as _bfe8
    for rpc in _rpcs(cfg, chain):
        try:
            d = _bfe8.rpc_post(rpc, json.loads(body), timeout=timeout, ua="tj-bot/0.1")
            res = d.get("result") if isinstance(d, dict) else None
            if isinstance(res, str) and res.startswith("0x") and len(res) > 2:
                return res[2:]
        except Exception:
            continue
    return None


def _w(h: str, i: int) -> int:
    return int(h[i * 64:(i + 1) * 64], 16)


def _addr(h: str, i: int) -> str:
    return "0x" + h[i * 64 + 24:(i + 1) * 64]


def _s24(x: int) -> int:
    x &= 0xFFFFFF
    return x - (1 << 24) if x >= (1 << 23) else x


def _enc_int(v: int) -> str:
    return f"{v & (M256 - 1):064x}"


def _enc_addr(a: str) -> str:
    return a.lower().replace("0x", "").rjust(64, "0")


def _str_ret(h) -> str:
    if not h:
        return ""
    try:
        if len(h) == 64:
            b = bytes.fromhex(h).rstrip(b"\x00")
            return b.decode("ascii") if b and all(32 <= c < 127 for c in b) else ""
        off = _w(h, 0) * 2
        if off + 64 > len(h):
            return ""
        ln = int(h[off:off + 64], 16) * 2
        return bytes.fromhex(h[off + 64:off + 64 + ln]).decode(errors="replace")
    except Exception:
        return ""


_TOK_CACHE = {}


def token_meta(cfg: dict, chain: str, addr: str) -> dict:
    key = (chain, addr.lower())
    if key in _TOK_CACHE:
        return _TOK_CACHE[key]
    if addr.lower() == ZERO:
        sym = ((cfg.get("native_symbol") or {}).get(chain)) or ("ETH" if chain != "bsc" else "BNB")
        meta = {"symbol": sym, "decimals": 18, "native": True}
    else:
        dh = eth_call(cfg, chain, addr, SEL["decimals()"])
        if not dh or len(dh) < 64:
            raise ValueError(f"LP token decimals unavailable ({chain} {addr[:10]})")
        dec = _w(dh, 0)
        if dec > 77:
            raise ValueError(f"LP token decimals out of range ({chain} {addr[:10]}: {dec})")
        sym = _str_ret(eth_call(cfg, chain, addr, SEL["symbol()"]))
        meta = {"symbol": sym or addr[:8], "decimals": int(dec), "native": False}
        if not sym:
            return meta
    _TOK_CACHE[key] = meta
    return meta


def amounts_from_liquidity(liq: int, sqrt_price_x96: int, tick_lower: int, tick_upper: int):
    sa = math.sqrt(1.0001 ** tick_lower)
    sb = math.sqrt(1.0001 ** tick_upper)
    sp = sqrt_price_x96 / Q96
    if sp <= sa:
        return liq * (1 / sa - 1 / sb), 0.0
    if sp >= sb:
        return 0.0, liq * (sb - sa)
    return liq * (1 / sp - 1 / sb), liq * (sp - sa)


def _price_from_sqrt(sqrt_price_x96: int, dec0: int, dec1: int) -> float:
    p = (sqrt_price_x96 / Q96) ** 2
    return p * (10 ** dec0) / (10 ** dec1)


def read_v4(cfg: dict, chain: str, mgr: str, meta: dict, token_id: int) -> dict:
    sv = meta.get("stateview")
    if not sv:
        return {}
    h = eth_call(cfg, chain, mgr, SEL["getPoolAndPositionInfo(uint256)"] + _enc_int(token_id))
    if not h or len(h) < 6 * 64:
        return {}
    c0, c1, fee, tsp, hooks, info = _addr(h, 0), _addr(h, 1), _w(h, 2), _s24(_w(h, 3)), _addr(h, 4), _w(h, 5)
    tl, tu = _s24(info >> 8), _s24(info >> 32)
    pool_id = lpdec.keccak256(bytes.fromhex(h[:5 * 64]))
    lh = eth_call(cfg, chain, mgr, SEL["getPositionLiquidity(uint256)"] + _enc_int(token_id))
    if not lh or len(lh) < 64:
        return {}
    liq = _w(lh, 0)
    sh = eth_call(cfg, chain, sv, SEL["getSlot0(bytes32)"] + pool_id.hex())
    if not sh or len(sh) < 2 * 64:
        return {}
    sqrt_p, tick = _w(sh, 0), _s24(_w(sh, 1))
    fees0 = fees1 = 0
    fees_ok = True
    if liq > 0:
        fg = eth_call(cfg, chain, sv, SEL["getFeeGrowthInside(bytes32,int24,int24)"] + pool_id.hex() + _enc_int(tl) + _enc_int(tu))
        pi = eth_call(cfg, chain, sv, SEL["getPositionInfo(bytes32,address,int24,int24,bytes32)"]
                      + pool_id.hex() + _enc_addr(mgr) + _enc_int(tl) + _enc_int(tu) + _enc_int(token_id))
        if fg and pi and len(fg) >= 2 * 64 and len(pi) >= 3 * 64:
            fees0 = ((_w(fg, 0) - _w(pi, 1)) % M256) * _w(pi, 0) // Q128
            fees1 = ((_w(fg, 1) - _w(pi, 2)) % M256) * _w(pi, 0) // Q128
        else:
            fees_ok = False
    m0, m1 = token_meta(cfg, chain, c0), token_meta(cfg, chain, c1)
    a0, a1 = amounts_from_liquidity(liq, sqrt_p, tl, tu)
    return {"proto": "uni_v4", "token0": c0, "token1": c1, "sym0": m0["symbol"], "sym1": m1["symbol"],
            "dec0": m0["decimals"], "dec1": m1["decimals"], "fee": fee, "tickSpacing": tsp, "hooks": hooks,
            "tickLower": tl, "tickUpper": tu, "tick": tick, "liquidity": str(liq),
            "amount0": a0 / 10 ** m0["decimals"], "amount1": a1 / 10 ** m1["decimals"],
            "fees0": fees0 / 10 ** m0["decimals"], "fees1": fees1 / 10 ** m1["decimals"],
            "price": _price_from_sqrt(sqrt_p, m0["decimals"], m1["decimals"]),
            "priceLower": (1.0001 ** tl) * 10 ** m0["decimals"] / 10 ** m1["decimals"],
            "priceUpper": (1.0001 ** tu) * 10 ** m0["decimals"] / 10 ** m1["decimals"],
            "inRange": tl <= tick < tu, "poolId": "0x" + pool_id.hex(), "feesOk": fees_ok}


def read_v3(cfg: dict, chain: str, mgr: str, meta: dict, token_id: int) -> dict:
    h = eth_call(cfg, chain, mgr, SEL["positions(uint256)"] + _enc_int(token_id))
    if not h or len(h) < 12 * 64:
        return {}
    slip = meta.get("proto") == "slipstream"
    t0, t1 = _addr(h, 2), _addr(h, 3)
    fee_or_tsp = _s24(_w(h, 4)) if slip else _w(h, 4)
    tl, tu, liq = _s24(_w(h, 5)), _s24(_w(h, 6)), _w(h, 7)
    fg0_last, fg1_last, owed0, owed1 = _w(h, 8), _w(h, 9), _w(h, 10), _w(h, 11)
    fac = meta.get("factory")
    if not fac:
        return {}
    sel_pool = SEL["getPool(address,address,int24)"] if slip else SEL["getPool(address,address,uint24)"]
    ph = eth_call(cfg, chain, fac, sel_pool + _enc_addr(t0) + _enc_addr(t1) + _enc_int(fee_or_tsp))
    if not ph or len(ph) < 64:
        return {}
    pool = _addr(ph, 0)
    if pool == ZERO:
        return {}
    sh = eth_call(cfg, chain, pool, SEL["slot0()"])
    if not sh or len(sh) < 2 * 64:
        return {}
    sqrt_p, tick = _w(sh, 0), _s24(_w(sh, 1))
    fees0, fees1 = owed0, owed1
    fees_ok = True
    if liq > 0:
        try:
            g0 = _w(eth_call(cfg, chain, pool, SEL["feeGrowthGlobal0X128()"]), 0)
            g1 = _w(eth_call(cfg, chain, pool, SEL["feeGrowthGlobal1X128()"]), 0)
            lo = eth_call(cfg, chain, pool, SEL["ticks(int24)"] + _enc_int(tl))
            up = eth_call(cfg, chain, pool, SEL["ticks(int24)"] + _enc_int(tu))
            k9 = 3 if slip else 2
            lo0, lo1, up0, up1 = _w(lo, k9), _w(lo, k9 + 1), _w(up, k9), _w(up, k9 + 1)
            below0 = lo0 if tick >= tl else (g0 - lo0) % M256
            below1 = lo1 if tick >= tl else (g1 - lo1) % M256
            above0 = up0 if tick < tu else (g0 - up0) % M256
            above1 = up1 if tick < tu else (g1 - up1) % M256
            in0 = (g0 - below0 - above0) % M256
            in1 = (g1 - below1 - above1) % M256
            fees0 += ((in0 - fg0_last) % M256) * liq // Q128
            fees1 += ((in1 - fg1_last) % M256) * liq // Q128
        except Exception:
            fees_ok = False
    m0, m1 = token_meta(cfg, chain, t0), token_meta(cfg, chain, t1)
    a0, a1 = amounts_from_liquidity(liq, sqrt_p, tl, tu)
    return {"proto": meta.get("proto"), "token0": t0, "token1": t1, "sym0": m0["symbol"], "sym1": m1["symbol"],
            "dec0": m0["decimals"], "dec1": m1["decimals"], "fee": (None if slip else fee_or_tsp),
            "tickSpacing": (fee_or_tsp if slip else None), "pool": pool,
            "tickLower": tl, "tickUpper": tu, "tick": tick, "liquidity": str(liq),
            "amount0": a0 / 10 ** m0["decimals"], "amount1": a1 / 10 ** m1["decimals"],
            "fees0": fees0 / 10 ** m0["decimals"], "fees1": fees1 / 10 ** m1["decimals"],
            "price": _price_from_sqrt(sqrt_p, m0["decimals"], m1["decimals"]),
            "priceLower": (1.0001 ** tl) * 10 ** m0["decimals"] / 10 ** m1["decimals"],
            "priceUpper": (1.0001 ** tu) * 10 ** m0["decimals"] / 10 ** m1["decimals"],
            "inRange": tl <= tick < tu, "feesOk": fees_ok}


def read_v2(cfg: dict, chain: str, pair: str, units: int, wallet=None, gauge=None) -> dict:
    try:
        if units <= 0:
            return {"proto": "v2", "liquidity": "0"}
        h0 = eth_call(cfg, chain, pair, SEL["token0()"])
        h1 = eth_call(cfg, chain, pair, SEL["token1()"])
        hr = eth_call(cfg, chain, pair, SEL["getReserves()"])
        hs = eth_call(cfg, chain, pair, SEL["totalSupply()"])
        if not (h0 and h1 and hr and hs) or len(hr) < 128:
            return {}
        t0, t1 = _addr(h0, 0), _addr(h1, 0)
        r0, r1, ts = _w(hr, 0), _w(hr, 1), _w(hs, 0)
        if ts <= 0:
            return {}
        m0, m1 = token_meta(cfg, chain, t0), token_meta(cfg, chain, t1)
        hst = eth_call(cfg, chain, pair, SEL["stable()"])
        stable = (bool(_w(hst, 0)) if hst and len(hst) >= 64 else None)
        f0 = f1 = 0
        if stable is not None and wallet:
            c0 = eth_call(cfg, chain, pair, SEL["claimable0(address)"] + _enc_addr(wallet))
            c1 = eth_call(cfg, chain, pair, SEL["claimable1(address)"] + _enc_addr(wallet))
            f0 = _w(c0, 0) if c0 and len(c0) >= 64 else 0
            f1 = _w(c1, 0) if c1 and len(c1) >= 64 else 0
        a0, a1 = r0 * units / ts, r1 * units / ts
        px = (r1 / 10 ** m1["decimals"]) / (r0 / 10 ** m0["decimals"]) if r0 else 0.0
        out = {"proto": "v2", "pool": pair, "token0": t0, "token1": t1, "sym0": m0["symbol"], "sym1": m1["symbol"],
               "dec0": m0["decimals"], "dec1": m1["decimals"], "stable": stable, "liquidity": str(units),
               "share": units / ts, "amount0": a0 / 10 ** m0["decimals"], "amount1": a1 / 10 ** m1["decimals"],
               "fees0": f0 / 10 ** m0["decimals"], "fees1": f1 / 10 ** m1["decimals"], "price": px,
               "priceLower": 0, "priceUpper": 0, "inRange": True, "feesOk": True}
        if gauge and wallet:
            out.update(read_stake_reward(cfg, chain, gauge, None, wallet))
        return out
    except Exception:
        return {}


def read_stake_reward(cfg: dict, chain: str, staker: str, token_id=None, wallet=None) -> dict:
    try:
        st = str(staker or "").lower()
        meta = (lpdec.lp_managers(common.BASE_DIR).get(chain) or {}).get(st) or {}
        if meta.get("proto") == "stake":
            if token_id is None:
                return {}
            h = eth_call(cfg, chain, st, SEL["pendingCake(uint256)"] + _enc_int(int(token_id)))
            rt = meta.get("reward")
        else:
            rh = eth_call(cfg, chain, st, SEL["rewardToken()"])
            rt = _addr(rh, 0) if rh and len(rh) >= 64 else None
            if not wallet:
                return {}
            if token_id is not None:
                h = eth_call(cfg, chain, st, SEL["earned(address,uint256)"] + _enc_addr(wallet) + _enc_int(int(token_id)))
            else:
                h = eth_call(cfg, chain, st, SEL["earned(address)"] + _enc_addr(wallet))
        if not rt or not h or len(h) < 64:
            return {}
        m = token_meta(cfg, chain, rt)
        return {"rewardAmount": _w(h, 0) / 10 ** m["decimals"], "rewardToken": rt, "rewardSym": m["symbol"]}
    except Exception:
        return {}


def read_position(cfg: dict, chain: str, mgr: str, token_id: int) -> dict:
    meta = (lpdec.lp_managers(common.BASE_DIR).get(chain) or {}).get(mgr.lower()) or {}
    try:
        if meta.get("proto") == "uni_v4":
            return read_v4(cfg, chain, mgr, meta, token_id)
        if meta.get("proto") in ("uni_v3", "slipstream"):
            return read_v3(cfg, chain, mgr, meta, token_id)
    except Exception:
        return {}
    return {}


def owner_of(cfg: dict, chain: str, mgr: str, token_id: int):
    h = eth_call(cfg, chain, mgr, SEL["ownerOf(uint256)"] + _enc_int(token_id))
    return _addr(h, 0) if h and len(h) >= 64 else None


NFT_PAGES_MAX = 200


def list_wallet_positions(cfg: dict, chain: str, wallet: str, timeout: int = 20) -> list:
    base = ((cfg.get("chains") or {}).get(chain) or {}).get("blockscout")
    mgrs = lpdec.lp_managers(common.BASE_DIR).get(chain) or {}
    if not base or not mgrs:
        return []
    url0 = f"{str(base).rstrip('/')}/api/v2/addresses/{wallet}/nft?type=ERC-721"
    url, out, seen = url0, [], set()
    for _page in range(NFT_PAGES_MAX):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": common.ua_for(url, "tj-bot/0.1"), "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(common.read_capped(r).decode())
        except Exception:
            return None
        if not isinstance(d, dict) or not isinstance(d.get("items"), list):
            return None
        for it in d["items"]:
            tok = it.get("token") or {}
            addr = str(tok.get("address") or tok.get("address_hash") or "").lower()
            if addr in mgrs:
                try:
                    out.append((addr, int(str(it.get("id")))))
                except (TypeError, ValueError):
                    continue
        npp = d.get("next_page_params")
        if not npp:
            return out
        if not isinstance(npp, dict):
            return None
        mk = json.dumps(npp, sort_keys=True)
        if mk in seen:
            return None
        seen.add(mk)
        url = url0 + "&" + urllib.parse.urlencode(npp)
    return None
