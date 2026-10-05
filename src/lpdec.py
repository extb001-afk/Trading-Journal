"""Liquidity-position decoding helpers."""
import json
import os

_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _keccak_f(st):
    for rnd in range(24):
        c = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        st = [[st[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(st[x][y], _ROT[x][y])
        st = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        st[0][0] ^= _RC[rnd]
    return st


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    st = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        st = _keccak_f(st)
    return b"".join(st[i % 5][i // 5].to_bytes(8, "little") for i in range(17))[:32]


def selector(sig: str) -> str:
    return keccak256(sig.encode()).hex()[:8]


_MGR_CACHE = None


NFT_PROTOS = ("uni_v4", "uni_v3", "slipstream")


def lp_managers(base_dir=None) -> dict:
    global _MGR_CACHE
    if _MGR_CACHE is not None:
        return _MGR_CACHE
    base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "seed", "lp_managers.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = {}
    out = {}
    for chain, m in raw.items():
        if chain.startswith("_") or not isinstance(m, dict):
            continue
        out[chain] = {str(a).lower(): v for a, v in m.items() if isinstance(v, dict) and v.get("proto")}
    _MGR_CACHE = out
    return out


def _u(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 32], "big")


def _dyn_bytes(b: bytes, off: int) -> bytes:
    if off < 0 or off + 32 > len(b):
        return b""
    ln = _u(b, off)
    return b[off + 32:off + 32 + ln]


def _dyn_array_of_bytes(b: bytes, off: int) -> list:
    if off < 0 or off + 32 > len(b):
        return []
    n = _u(b, off)
    if n > 512:
        return []
    out = []
    for i in range(n):
        p = _u(b, off + 32 + 32 * i)
        out.append(_dyn_bytes(b, off + 32 + p))
    return out


SEL_MULTICALL = selector("multicall(bytes[])")
SEL_V4_MODIFY = selector("modifyLiquidities(bytes,uint256)")
SEL_V3 = {
    selector("increaseLiquidity((uint256,uint256,uint256,uint256,uint256,uint256))"): "INCREASE",
    selector("decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))"): "DECREASE",
    selector("collect((uint256,address,uint128,uint128))"): "COLLECT",
    selector("burn(uint256)"): "BURN",
    selector("mint((address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,address,uint256))"): "MINT",
    selector("mint((address,address,int24,int24,int24,uint256,uint256,uint256,uint256,address,uint256,uint160))"): "MINT",
    selector("harvest(uint256,address)"): "COLLECT",
    selector("withdraw(uint256,address)"): "COLLECT",
    selector("collectTo((uint256,address,uint128,uint128),address)"): "COLLECT",
    selector("getReward(uint256)"): "COLLECT",
    selector("withdraw(uint256)"): "COLLECT",
}
SEL_DEPOSIT_U256 = selector("deposit(uint256)")
V4_ACTIONS = {0: "INCREASE", 1: "DECREASE", 2: "MINT", 3: "BURN", 4: "INCREASE"}


def decode_lp_calls(raw_input) -> list:
    try:
        if not raw_input or not isinstance(raw_input, str) or not raw_input.startswith("0x") or len(raw_input) < 10:
            return []
        b = bytes.fromhex(raw_input[2:])
    except ValueError:
        return []
    return _decode_calls(b, depth=0)


def _decode_calls(b: bytes, depth: int) -> list:
    out = []
    try:
        sel = b[:4].hex()
        data = b[4:]
        if sel == SEL_MULTICALL and depth < 2:
            for c in _dyn_array_of_bytes(data, _u(data, 0)):
                out.extend(_decode_calls(c, depth + 1))
        elif sel == SEL_V4_MODIFY:
            unlock = _dyn_bytes(data, _u(data, 0))
            actions = _dyn_bytes(unlock, _u(unlock, 0))
            params = _dyn_array_of_bytes(unlock, _u(unlock, 32))
            for a, p in zip(actions, params):
                name = V4_ACTIONS.get(a)
                if name is None:
                    continue
                tid = _u(p, 0) if (name != "MINT" and len(p) >= 32) else None
                if name == "MINT":
                    liq = _u(p, 7 * 32) if len(p) >= 8 * 32 else None
                elif a == 4:
                    liq = None
                elif name in ("INCREASE", "DECREASE"):
                    liq = _u(p, 32) if len(p) >= 64 else None
                else:
                    liq = None
                out.append((name, tid, liq))
        elif sel in SEL_V3:
            name = SEL_V3[sel]
            tid = _u(data, 0) if (name != "MINT" and len(data) >= 32) else None
            liq = _u(data, 32) if (name == "DECREASE" and len(data) >= 64) else None
            out.append((name, tid, liq))
    except Exception:
        return out
    return out


def nft_moves(snap: dict, managers: dict) -> list:
    tx = snap.get("tx") or {}
    tts = (tx.get("token_transfers") or []) + (snap.get("token_transfers") or [])
    out = []
    for t in tts:
        tok = t.get("token") or {}
        if (tok.get("type") or "ERC-20") != "ERC-721":
            continue
        addr = str(tok.get("address") or tok.get("address_hash") or t.get("contractAddress") or "").lower()
        if addr not in managers:
            continue
        tot = t.get("total") or {}
        tid = tot.get("token_id") or t.get("tokenID") or t.get("token_id")
        try:
            tid = int(str(tid))
        except (TypeError, ValueError):
            continue
        f = t.get("from"); to = t.get("to")
        f = (f.get("hash") if isinstance(f, dict) else f) or ""
        to = (to.get("hash") if isinstance(to, dict) else to) or ""
        out.append((addr, tid, str(f).lower(), str(to).lower()))
    return out


def lp_tid(x):
    if x is None or isinstance(x, bool):
        return None
    s9 = str(x)
    if s9.isdigit():
        return int(s9)
    if len(s9) == 42 and s9.startswith("0x"):
        try:
            int(s9[2:], 16)
            return s9.lower()
        except ValueError:
            return None
    import lpsol
    return s9 if lpsol.is_pubkey(s9) else None


def lp_location(chain: str, mgr: str, ids) -> str:
    ids = sorted({t for t in (lp_tid(i) for i in ids) if t is not None}, key=lambda t: (isinstance(t, str), str(t).zfill(80)))
    tail = str(ids[0]) if len(ids) == 1 else ("multi" if ids else "?")
    return f"lp:{chain}:{mgr}:{tail}"


if __name__ == "__main__":
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert selector("transfer(address,uint256)") == "a9059cbb"
    assert selector("balanceOf(address)") == "70a08231"
    assert SEL_V4_MODIFY == "dd46508f" and SEL_MULTICALL == "ac9650d8"
    assert selector("decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))") == "0c49ccbe"
    assert selector("increaseLiquidity((uint256,uint256,uint256,uint256,uint256,uint256))") == "219f5d17"
    print("lpdec self-test OK; managers:", {c: len(m) for c, m in lp_managers().items()})
