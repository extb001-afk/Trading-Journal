from __future__ import annotations

import base64
import hashlib
import re

import token_tables

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58_IDX.get(ch)
        if i is None:
            raise ValueError("base58 아닌 문자가 있어요")
        n = n * 58 + i
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


def _dsha(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def b58check_decode(s: str) -> bytes:
    raw = b58decode(s)
    if len(raw) < 5:
        raise ValueError("Base58Check 길이가 너무 짧아요")
    body, ck = raw[:-4], raw[-4:]
    if _dsha(body)[:4] != ck:
        raise ValueError("체크섬이 맞지 않아요 — 한 글자만 틀려도 거부합니다. 복사한 원문을 확인하세요")
    return body


def b58check_encode(body: bytes) -> str:
    return b58encode(body + _dsha(body)[:4])


def tron_key(text: str) -> str:
    a = (text or "").strip()
    if a.lower().startswith("0x"):
        raise ValueError("0x 로 시작하는 건 EVM 주소예요 — 트론 주소는 T 로 시작합니다(같은 키라도 다른 체인 주소로 보지 않아요)")
    if re.fullmatch(r"41[0-9a-fA-F]{40}", a):
        return a.lower()
    if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", a):
        raise ValueError("트론 주소는 T 로 시작하는 34자(Base58) 또는 41 로 시작하는 16진수 42자예요")
    body = b58check_decode(a)
    if len(body) != 21 or body[0] != 0x41:
        raise ValueError("트론 주소 형식이 아니에요(접두 0x41 · 21바이트)")
    return body.hex()


def tron_display(key: str) -> str:
    k = tron_key(key)
    return b58check_encode(bytes.fromhex(k))


_HEX64 = re.compile(r"0x[0-9a-fA-F]{64}")


def sui_key(text: str) -> str:
    a = (text or "").strip()
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", a):
        raise ValueError("0x + 16진수 40자는 EVM 주소예요 — Sui 주소는 0x + 16진수 64자입니다")
    if not _HEX64.fullmatch(a):
        raise ValueError("Sui 주소는 0x + 16진수 64자예요")
    if int(a[2:], 16) == 0:
        raise ValueError("0 주소는 추적할 수 없어요")
    return a.lower()


_MV_ADDR = re.compile(r"0x([0-9a-fA-F]{1,64})(?=::)")
_MV_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def sui_type_canonical(t: str) -> str:
    s = re.sub(r"\s+", "", t or "")
    if not s or len(s) > 2000:
        raise ValueError("Move 타입이 비었거나 너무 길어요")
    pos = _mv_parse(s, 0)
    if pos != len(s):
        raise ValueError("Move 타입 형식이 아니에요")
    return _MV_ADDR.sub(lambda m: "0x" + m.group(1).lower().rjust(64, "0"), s)


def _mv_parse(s: str, i: int) -> int:
    m = re.compile(r"0x[0-9a-fA-F]{1,64}::" + _MV_IDENT + "::" + _MV_IDENT).match(s, i)
    if not m:
        m2 = re.compile(r"(u8|u16|u32|u64|u128|u256|bool|address|signer)\b").match(s, i)
        if m2:
            return m2.end()
        if s.startswith("vector<", i):
            j = _mv_parse(s, i + 7)
            if j >= len(s) or s[j] != ">":
                raise ValueError("Move 타입 형식이 아니에요(vector)")
            return j + 1
        raise ValueError("Move 타입 형식이 아니에요")
    j = m.end()
    if j < len(s) and s[j] == "<":
        j += 1
        while True:
            j = _mv_parse(s, j)
            if j < len(s) and s[j] == ",":
                j += 1
                continue
            if j < len(s) and s[j] == ">":
                return j + 1
            raise ValueError("Move 타입 제네릭 괄호가 맞지 않아요")
    return j


SUI_NATIVE_TYPE = "0x" + "0" * 63 + "2::sui::SUI"


def sui_asset_key(type_text: str) -> str:
    return "mv_" + sui_type_canonical(type_text).encode("utf-8").hex()


def sui_asset_type(key: str) -> str:
    if not isinstance(key, str) or not key.startswith("mv_"):
        raise ValueError("Sui 토큰 키가 아니에요")
    try:
        return sui_type_canonical(bytes.fromhex(key[3:]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("Sui 토큰 키를 되돌릴 수 없어요") from e


def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def ton_parse(text: str, network: str = "mainnet"):
    a = (text or "").strip()
    m = re.fullmatch(r"(-?\d{1,3}):([0-9a-fA-F]{64})", a)
    if m:
        wc = int(m.group(1))
        if wc not in (0, -1):
            raise ValueError("TON 워크체인은 0(basechain) 또는 -1(masterchain)만 받아요")
        return wc, m.group(2).lower()
    m = re.fullmatch(r"(-?\d{1,3})_([0-9a-f]{64})", a)
    if m and int(m.group(1)) in (0, -1):
        return int(m.group(1)), m.group(2)
    if len(a) != 48 or not re.fullmatch(r"[A-Za-z0-9+/_-]{48}", a):
        raise ValueError("TON 주소는 raw(0:…64자) 또는 friendly(48자 EQ…/UQ…)예요")
    try:
        raw = base64.b64decode(a.replace("-", "+").replace("_", "/"), validate=True)
    except (ValueError, TypeError) as e:
        raise ValueError("TON friendly 주소의 base64 가 깨졌어요") from e
    if len(raw) != 36:
        raise ValueError("TON friendly 주소 길이가 맞지 않아요")
    if _crc16_xmodem(raw[:34]) != int.from_bytes(raw[34:], "big"):
        raise ValueError("TON 주소 체크섬(CRC16)이 맞지 않아요 — 복사한 원문을 확인하세요")
    flag = raw[0]
    if flag & 0x80 and network == "mainnet":
        raise ValueError("테스트넷 전용 TON 주소예요 — 메인넷 지갑 주소를 넣으세요")
    if flag & 0x7F not in (0x11, 0x51):
        raise ValueError("TON friendly 주소 플래그가 올바르지 않아요")
    wc = raw[1] - 256 if raw[1] > 127 else raw[1]
    if wc not in (0, -1):
        raise ValueError("TON 워크체인은 0 또는 -1 만 받아요")
    return wc, raw[2:34].hex()


def ton_key(text: str, network: str = "mainnet") -> str:
    wc, h = ton_parse(text, network)
    if int(h, 16) == 0:
        raise ValueError("0 주소는 추적할 수 없어요")
    return f"{wc}_{h}"


def ton_raw(key: str) -> str:
    wc, h = ton_parse(key)
    return f"{wc}:{h}"


def ton_friendly(key: str, bounceable: bool = False, testnet: bool = False, url_safe: bool = True) -> str:
    wc, h = ton_parse(key)
    flag = (0x11 if bounceable else 0x51) | (0x80 if testnet else 0)
    body = bytes([flag, wc & 0xFF]) + bytes.fromhex(h)
    s = base64.b64encode(body + _crc16_xmodem(body).to_bytes(2, "big")).decode()
    return s.replace("+", "-").replace("/", "_") if url_safe else s


_BECH32_CS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST, _BECH32M_CONST = 1, 0x2BC830A3


def _bech32_polymod(values) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_decode(s: str):
    if any(ord(x) < 33 or ord(x) > 126 for x in s):
        raise ValueError("bech32 에 쓸 수 없는 문자가 있어요")
    if s.lower() != s and s.upper() != s:
        raise ValueError("대소문자가 섞인 bech32 주소는 거부해요(BIP173)")
    s = s.lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s) or len(s) > 90:
        raise ValueError("bech32 주소 길이·구분자가 맞지 않아요")
    hrp, data = s[:pos], s[pos + 1:]
    if any(c not in _BECH32_CS for c in data):
        raise ValueError("bech32 에 쓸 수 없는 문자가 있어요")
    d = [_BECH32_CS.find(c) for c in data]
    const = _bech32_polymod(_hrp_expand(hrp) + d)
    if const == _BECH32_CONST:
        enc = "bech32"
    elif const == _BECH32M_CONST:
        enc = "bech32m"
    else:
        raise ValueError("bech32 체크섬이 맞지 않아요 — 복사한 원문을 확인하세요")
    return hrp, d[:-6], enc


def _convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0
    out = []
    maxv = (1 << tobits) - 1
    for v in data:
        if v < 0 or (v >> frombits):
            raise ValueError("비트 변환 실패")
        acc = (acc << frombits) | v
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("bech32 패딩이 올바르지 않아요")
    return out


_BTC_NET = {"mainnet": {"hrp": "bc", "p2pkh": 0x00, "p2sh": 0x05},
            "testnet": {"hrp": "tb", "p2pkh": 0x6F, "p2sh": 0xC4}}


def btc_address(text: str, network: str = "mainnet") -> dict:
    a = (text or "").strip()
    net = _BTC_NET.get(network)
    if net is None:
        raise ValueError("지원하지 않는 비트코인 네트워크예요")
    other = [n for n in _BTC_NET if n != network]
    lo = a.lower()
    if lo.startswith(net["hrp"] + "1") or any(lo.startswith(_BTC_NET[o]["hrp"] + "1") for o in other):
        hrp, data, enc = _bech32_decode(a)
        if hrp != net["hrp"]:
            raise ValueError("다른 네트워크(테스트넷 등)의 비트코인 주소예요")
        if not data:
            raise ValueError("bech32 주소에 데이터가 없어요")
        ver = data[0]
        prog = bytes(_convertbits(data[1:], 5, 8, False))
        if ver > 16 or len(prog) < 2 or len(prog) > 40:
            raise ValueError("세그윗 버전·길이가 올바르지 않아요")
        if ver == 0 and len(prog) not in (20, 32):
            raise ValueError("세그윗 v0 주소 길이가 올바르지 않아요")
        if (ver == 0) != (enc == "bech32"):
            raise ValueError("세그윗 버전과 체크섬 종류(bech32/bech32m)가 맞지 않아요(BIP350)")
        typ = {(0, 20): "p2wpkh", (0, 32): "p2wsh", (1, 32): "p2tr"}.get((ver, len(prog)), f"witness_v{ver}")
        script = bytes([0x50 + ver if ver else 0, len(prog)]) + prog
        return {"address": lo, "type": typ, "script": script.hex()}
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{25,35}", a):
        raise ValueError("비트코인 주소 형식이 아니에요(1…·3…·bc1…)")
    body = b58check_decode(a)
    if len(body) != 21:
        raise ValueError("비트코인 Base58 주소 길이가 맞지 않아요")
    if body[0] == net["p2pkh"]:
        return {"address": a, "type": "p2pkh", "script": "76a914" + body[1:].hex() + "88ac"}
    if body[0] == net["p2sh"]:
        return {"address": a, "type": "p2sh", "script": "a914" + body[1:].hex() + "87"}
    if any(body[0] in (_BTC_NET[o]["p2pkh"], _BTC_NET[o]["p2sh"]) for o in other):
        raise ValueError("다른 네트워크(테스트넷 등)의 비트코인 주소예요")
    raise ValueError("비트코인 주소 버전이 올바르지 않아요")


XPUB_VERSIONS = {"0488b21e": ("xpub", "mainnet", None), "049d7cb2": ("ypub", "mainnet", "sh(wpkh)"),
                 "04b24746": ("zpub", "mainnet", "wpkh"), "043587cf": ("tpub", "testnet", None),
                 "044a5262": ("upub", "testnet", "sh(wpkh)"), "045f1cf6": ("vpub", "testnet", "wpkh")}
XPUB_MULTISIG = {"0295b43f": "Ypub", "02aa7ed3": "Zpub", "024289ef": "Upub", "02575483": "Vpub"}
XPRV_VERSIONS = {"0488ade4": "xprv", "049d7878": "yprv", "04b2430c": "zprv", "04358394": "tprv",
                 "044a4e28": "uprv", "045f18bc": "vprv", "0295b005": "Yprv", "02aa7a99": "Zprv"}
PRIVATE_HINT = "개인 키(확장 개인 키·WIF·시드)처럼 보이는 값이에요 — 저장하지 않았어요. 공개 키(xpub·디스크립터의 공개 부분)만 넣으세요"


def btc_xpub(text: str, network: str = "mainnet") -> dict:
    a = (text or "").strip()
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{100,120}", a):
        raise ValueError("확장 공개 키(xpub/ypub/zpub) 형식이 아니에요")
    body = b58check_decode(a)
    if len(body) != 78:
        raise ValueError("확장 키 길이(78바이트)가 맞지 않아요")
    ver = body[:4].hex()
    if ver in XPRV_VERSIONS:
        raise ValueError(PRIVATE_HINT)
    if ver in XPUB_MULTISIG:
        raise ValueError(f"멀티시그 확장 키({XPUB_MULTISIG[ver]})는 아직 지원하지 않아요 — 단일 서명 지갑만")
    if ver not in XPUB_VERSIONS:
        raise ValueError("알 수 없는 확장 키 버전이에요")
    kind, net, hint = XPUB_VERSIONS[ver]
    if net != network:
        raise ValueError("다른 네트워크(테스트넷 등)의 확장 키예요")
    key = body[45:78]
    if key[0] not in (2, 3):
        raise ValueError("확장 공개 키의 공개 키 부분이 올바르지 않아요")
    return {"xpub": a, "kind": kind, "script_hint": hint, "depth": body[4], "fingerprint": body[5:9].hex(),
            "child": int.from_bytes(body[9:13], "big"), "chaincode": body[13:45].hex(), "pubkey": key.hex()}


def has_private_material(text: str) -> bool:
    s = str(text or "")
    for tok in re.findall(r"[1-9A-HJ-NP-Za-km-z]{50,120}", s):
        try:
            body = b58check_decode(tok)
        except ValueError:
            continue
        if len(body) == 78 and body[:4].hex() in XPRV_VERSIONS:
            return True
        if len(body) in (33, 34) and body[0] in (0x80, 0xEF):
            return True
    return bool(re.search(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])", s)) and not re.search(r"0x[0-9a-fA-F]{64}", s)


_DESC_INPUT = "0123456789()[],'/*abcdefgh@:$%{}IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~ijklmnopqrstuvwxyzABCDEFGH`#\"\\ "
_DESC_GEN = (0xF5DEE51989, 0xA9FDCA3312, 0x1BAB10E32D, 0x3706B1677A, 0x644D626FFD)


def _desc_polymod(symbols) -> int:
    chk = 1
    for value in symbols:
        top = chk >> 35
        chk = ((chk & 0x7FFFFFFFF) << 5) ^ value
        for i in range(5):
            chk ^= _DESC_GEN[i] if ((top >> i) & 1) else 0
    return chk


def _desc_expand(s: str):
    groups, symbols = [], []
    for c in s:
        v = _DESC_INPUT.find(c)
        if v < 0:
            raise ValueError("디스크립터에 쓸 수 없는 문자가 있어요")
        symbols.append(v & 31)
        groups.append(v >> 5)
        if len(groups) == 3:
            symbols.append(groups[0] * 9 + groups[1] * 3 + groups[2])
            groups = []
    if len(groups) == 1:
        symbols.append(groups[0])
    elif len(groups) == 2:
        symbols.append(groups[0] * 3 + groups[1])
    return symbols


def desc_checksum(s: str) -> str:
    c = _desc_polymod(_desc_expand(s) + [0] * 8) ^ 1
    return "".join(_BECH32_CS[(c >> (5 * (7 - i))) & 31] for i in range(8))


_DESC_SHAPES = (("sh(wpkh(", "))", "p2sh-p2wpkh"), ("wpkh(", ")", "p2wpkh"), ("pkh(", ")", "p2pkh"), ("tr(", ")", "p2tr"))
_KEY_EXPR = re.compile(r"(?:\[([0-9a-fA-F]{8})((?:/\d+['hH]?)*)\])?([1-9A-HJ-NP-Za-km-z]{100,120})((?:/(?:\d+|<\d+;\d+>))*)/\*")


def btc_descriptor(text: str, network: str = "mainnet") -> dict:
    s = re.sub(r"\s+", "", text or "")
    if not s:
        raise ValueError("디스크립터가 비었어요")
    if has_private_material(s):
        raise ValueError(PRIVATE_HINT)
    ck = None
    if "#" in s:
        s, ck = s.rsplit("#", 1)
        if len(ck) != 8 or desc_checksum(s) != ck:
            raise ValueError("디스크립터 체크섬(#…)이 맞지 않아요 — 지갑에서 내보낸 원문 그대로 넣으세요")
    for pre, suf, typ in _DESC_SHAPES:
        if s.startswith(pre) and s.endswith(suf):
            inner = s[len(pre):len(s) - len(suf)]
            break
    else:
        raise ValueError("지원하는 디스크립터는 pkh(…) · sh(wpkh(…)) · wpkh(…) · 단일 키 tr(…) 이에요(멀티시그·스크립트는 아직)")
    m = _KEY_EXPR.fullmatch(inner)
    if not m and re.search(r"[1-9A-HJ-NP-Za-km-z]{100,120}(?:/[^/]*)*?/\d+['hH]", inner):
        raise ValueError("공개 확장 키로는 강화(hardened ') 경로를 파생할 수 없어요 — 계정 xpub 뒤엔 일반 경로(/<0;1>/*)만")
    if not m:
        raise ValueError("디스크립터 안의 키는 [지문/경로]xpub…/<0;1>/* 꼴이어야 해요(공개 확장 키 + 끝 '*')")
    xp = btc_xpub(m.group(3), network)
    path = m.group(4) or ""
    multi = re.findall(r"<(\d+);(\d+)>", path)
    if len(multi) > 1:
        raise ValueError("갈래 표기(<a;b>)는 하나만 받아요")
    if multi:
        branches = sorted({int(multi[0][0]), int(multi[0][1])})
    else:
        last = re.findall(r"/(\d+)$", path)
        branches = [int(last[0])] if last else []
    if not branches or any(b not in (0, 1) for b in branches):
        raise ValueError("받는 주소(0)·잔돈 주소(1) 갈래만 받아요 — 끝을 /<0;1>/* 로 넣으세요")
    return {"descriptor": s + "#" + desc_checksum(s), "script_type": typ, "xpub": xp["xpub"], "xpub_kind": xp["kind"],
            "origin": ((m.group(1) or "").lower() + (m.group(2) or "")) or None, "branches": branches,
            "checksum_given": ck is not None}


def btc_wallet_id(source_text: str) -> str:
    return "bw" + hashlib.sha256(("btc|" + (source_text or "")).encode("utf-8")).hexdigest()[:32]


def btc_mask(text: str) -> str:
    s = str(text or "")
    return s if len(s) <= 14 else s[:6] + "…" + s[-4:]


_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
       0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
       0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
       0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]


_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]


_M64 = (1 << 64) - 1


def _keccak_f(s):
    for rc in _RC:
        c = [s[x][0] ^ s[x][1] ^ s[x][2] ^ s[x][3] ^ s[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ (((c[(x + 1) % 5] << 1) | (c[(x + 1) % 5] >> 63)) & _M64) for x in range(5)]
        s = [[s[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = _ROT[x][y]
                v = s[x][y]
                b[y][(2 * x + 3 * y) % 5] = ((v << r) | (v >> (64 - r))) & _M64 if r else v
        s = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        s[0][0] ^= rc
    return s


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    while len(msg) % rate:
        msg.append(0)
    msg[-1] |= 0x80
    s = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            s[x][y] ^= int.from_bytes(blk[i * 8:i * 8 + 8], "little")
        s = _keccak_f(s)
    out = b""
    for i in range(4):
        out += s[i % 5][i // 5].to_bytes(8, "little")
    return out


def to_checksum(addr: str) -> str:
    a = addr.lower().replace("0x", "")
    h = keccak256(a.encode()).hex()
    return "0x" + "".join(ch.upper() if ch.isalpha() and int(h[i], 16) >= 8 else ch for i, ch in enumerate(a))


SOL_NOT_WALLET = {
    "11111111111111111111111111111111": "시스템 프로그램",
    "So11111111111111111111111111111111111111112": "wSOL 민트",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "토큰 프로그램",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "토큰-2022 프로그램",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "연결 토큰 계정 프로그램",
    "Stake11111111111111111111111111111111111111": "스테이크 프로그램",
    "Vote111111111111111111111111111111111111111": "투표 프로그램",
    "ComputeBudget111111111111111111111111111111": "컴퓨트 예산 프로그램",
    **{m: f"{sym} 민트" for m, sym in token_tables.STABLE_MINTS.items()},
}


def validate_address(addr: str):
    a = (addr or "").strip()
    sec9 = secret_like([a]) or ("개인 키(Solana 비밀 키)처럼 보이는 값이에요 — 지우고 주소만 넣으세요. 개인 키는 절대 입력하지 마세요"
                                if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", a) else "") \
        or ("개인 키(비트코인 WIF·확장 개인 키)처럼 보이는 값이에요 — 지우고 주소만 넣으세요. 개인 키는 절대 입력하지 마세요" if has_private_material(a) else "")
    if sec9:
        raise ValueError(sec9.replace("아무것도 저장하지 않았습니다", "저장하지 않았습니다"))
    if a in SOL_NOT_WALLET:
        raise ValueError(f"지갑 주소가 아니에요({SOL_NOT_WALLET[a]}) — 내 지갑 주소를 넣으세요")
    if a.lower().startswith("0x"):
        body = a[2:]
        if len(body) != 40 or not re.fullmatch(r"[0-9a-fA-F]{40}", body):
            raise ValueError("EVM 주소는 0x + 16진수 40자입니다")
        if int(body, 16) == 0:
            raise ValueError("0 주소는 추적할 수 없습니다")
        note = ""
        if body != body.lower() and body != body.upper():
            if to_checksum(a) != "0x" + body:
                raise ValueError("체크섬이 맞지 않습니다 — 대소문자가 섞인 주소는 한 글자만 틀려도 거부합니다. 복사한 원문을 확인하세요")
            note = "체크섬 확인됨"
        else:
            note = "체크섬 없는 주소(전부 소문자/대문자) — 오타 여부를 한 번 더 확인하세요"
        return "evm", "0x" + body.lower(), note
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", a):
        raise ValueError("0x… EVM 주소 또는 Solana(base58) 주소가 아닙니다 — 비트코인·트론·코스모스 등은 지원하지 않아요")
    if len(b58decode(a)) != 32:
        raise ValueError("Solana 주소는 base58 로 32바이트여야 합니다(트론 T… 주소 등은 지원하지 않아요)")
    return "sol", a, "Solana 주소 형식 확인됨"


ADDR_SPLIT = re.compile(r"[\s,;，；、]+")


def split_addresses(text) -> list:
    return [t for t in ADDR_SPLIT.split(str(text or "")) if t]


_SECRET_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_WORD = re.compile(r"[A-Za-z]{3,8}")


def secret_like(tokens) -> str:
    toks = [t for t in tokens if isinstance(t, str)]
    if _SECRET_HEX64.search(ADDR_SPLIT.sub("", "".join(toks))):
        return "개인 키(16진수 64자)처럼 보이는 값이 있어 아무것도 저장하지 않았습니다 — 지우고 주소만 넣으세요. 개인 키는 절대 입력하지 마세요"
    if sum(1 for t in toks for w in ADDR_SPLIT.split(t) if _WORD.fullmatch(w)) >= 12:
        return "시드 문구(단어 12·24개)처럼 보이는 값이 있어 아무것도 저장하지 않았습니다 — 지우고 주소만 넣으세요. 시드는 절대 입력하지 마세요"
    return ""
