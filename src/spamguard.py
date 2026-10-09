"""Spam and fake-token filtering."""
import json
import os
import re
import threading
import time
import unicodedata

MAJORS = {"USDT", "USDC", "USDG", "DAI", "BUSD", "FDUSD", "PYUSD", "USD1", "USDE", "USDS", "TUSD", "USDP",
          "USDT0", "ETH", "WETH", "BTC", "WBTC", "SOL", "WSOL", "BNB", "WBNB", "POL", "MATIC", "ARB", "OP", "AVAX", "TRX", "XRP"}

_CONF = {}
for _src, _dst in (
        ("АаВвСсЕеНнКкМмОоРрТтХхУуЅѕІіЈјԀԁҮүЁёЌќЍѝԌԍӀ", "AABBCCEEHHKKMMOOPPTTXXYYSSIIJJDDYYEEKKNNGGI"),
        ("ΑαΒβΕεΖζΗηΙιΚκΜμΝνΟοΡρΤτΥυΧχ", "AABBEEZZHHIIKKMMNNOOPPTTYYXX"),
        ("ꓮꓐꓚꓓꓰꓝꓖꓧꓲꓙꓗꓡꓟꓠꓳꓑꓣꓢꓔꓴꓦꓪꓫꓬꓜ", "ABCDEFGHIJKLMNOPRSTUVWXYZ"),
        ("ՍսՏѕՕօԼᏚᎢᎪᎬᎻᏀᏴᏙᎠ", "UUSSOOLSTAEHGBVD"),
        ("∪⊤ƧƊ", "UTSD"),
        ("₮", "T"),
):
    if len(_src) != len(_dst):
        _dst = _dst.ljust(len(_src), "?")
    for _a, _b in zip(_src, _dst):
        if _b != "?":
            _CONF[_a] = _b
_DIGIT = {"5": "S", "0": "O", "1": "I", "3": "E", "8": "B"}
_INVIS = re.compile("[​-‏‪-‮⁠-⁯﻿­͏ᅟᅠ឴឵᠋-᠎ㅤﾠ￰-￸\ufe00-\ufe0f\U000e0000-\U000e01ef]")


def _drop(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat in ("Cf", "Cn", "Co", "Cs") or bool(_INVIS.match(ch))


def clean(sym) -> str:
    s = str(sym or "")
    if s.isascii():
        return s
    return "".join(ch for ch in s if not _drop(ch))


_PRE_NFKC = str.maketrans({"Ϲ": "C", "ϲ": "c"})


def fold(sym) -> str:
    s = unicodedata.normalize("NFKC", clean(sym).translate(_PRE_NFKC))
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    out = []
    for ch in s:
        ch = _CONF.get(ch, ch)
        out.append(ch.upper() if ch.isascii() else ch)
    return "".join(out)


def _head(s: str) -> str:
    return re.split(r"[\s|/:,(]+", s.strip(), maxsplit=1)[0] if s.strip() else ""


LURE_TLD = ("com|io|org|net|xyz|top|mom|site|app|live|pro|claim|gift|click|vip|cc|co|me|us|info|biz|link|lol|fun|run|to|gg|ai|so|"
            "world|global|online|tech|store|shop|space|website|cash|money|exchange|finance|fi|bond|today|club|ltd|icu|cfd|sbs|buzz|win|"
            "bet|games|network|events|ink|tv|in|cn|ru|tk|ml|ga|gq|cf|ws|su|vc|sh|ly|im|eu|asia|zone|email|agency|market|digital|"
            "cloud|host|page|dev|rewards|claims|airdrop|events|homes|lat|quest|foundation|services|financial|limited|group")
_TAIL_LURE = re.compile(r"(https?:|www\.|t\.me|\.(com|io|org|net|xyz|top|mom|site|app|live|pro|claim|gift|click|vip)\b|"
                        r"(?<![\w.])[a-z0-9][a-z0-9-]{1,62}\.(?:" + LURE_TLD + r")(?![\w-])|"
                        r"visit|claim|reward|airdrop|voucher|bonus|zero[\s_-]?fees?|返佣|空投|免费|✅|🎁|\$\s?\d|"
                        r"@\w{3,}bot\b|telegram)", re.I)


_CJK_NAMES = ("CJK", "HANGUL", "HIRAGANA", "KATAKANA", "YI ", "BOPOMOFO")


def _one_off(head_raw: str):
    if not head_raw or head_raw.isascii():
        return None
    na = [ch for ch in head_raw if not ch.isascii()]
    if len(na) < 2:
        return None
    per = []
    for ch in head_raw:
        fc = fold(ch)
        if len(fc) != 1:
            return None
        per.append(_DIGIT.get(fc, fc))
    hits = []
    for m in sorted(MAJORS):
        if len(m) != len(per):
            continue
        diff = [i for i, (a, b) in enumerate(zip(per, m)) if a != b]
        if len(diff) != 1:
            continue
        ch = head_raw[diff[0]]
        if ch.isascii() or not ch.isalpha():
            continue
        try:
            nm = unicodedata.name(ch)
        except ValueError:
            continue
        if nm.startswith(_CJK_NAMES):
            continue
        hits.append(m)
    return hits[0] if len(hits) == 1 else None


_IMP_MEMO = {}
_IMP_MEMO_MAX = 100000


def impostor_of(sym):
    raw = str(sym or "")
    r = _IMP_MEMO.get(raw, _IMP_MEMO)
    if r is _IMP_MEMO:
        r = _impostor_calc(raw)
        if len(_IMP_MEMO) < _IMP_MEMO_MAX:
            _IMP_MEMO[raw] = r
    return r


def _impostor_calc(sym):
    raw = str(sym or "")
    if not raw:
        return None
    head_raw = _head(clean(raw))
    hidden = clean(raw) != raw
    if not hidden and head_raw.isascii() and head_raw.upper() in MAJORS and head_raw == raw.strip():
        return None
    if not hidden and head_raw == raw.strip() and head_raw.replace("₮", "T").upper() in MAJORS and head_raw.replace("₮", "T").isascii():
        return None
    tail = clean(raw).strip()[len(head_raw):]
    if not hidden and head_raw.isascii() and tail.strip() and not _TAIL_LURE.search(tail):
        return None
    f = _head(fold(raw))
    cands = {f, "".join(_DIGIT.get(c, c) for c in f)}
    for c in cands:
        if c in MAJORS and (hidden or c != head_raw or not head_raw.isascii() or raw != head_raw):
            return c
    if "Υ" in head_raw or "υ" in head_raw:
        fu = _head(fold(raw.replace("Υ", "U").replace("υ", "u")))
        for c in (fu, "".join(_DIGIT.get(x, x) for x in fu)):
            if c in MAJORS:
                return c
    one = _one_off(head_raw)
    if one:
        return one
    f2 = "".join(_DIGIT.get(c, c) for c in f)
    if not f2.isascii():
        hits = []
        for m in sorted(MAJORS):
            if len(m) == len(f2):
                diff = [(a, b) for a, b in zip(f2, m) if a != b]
                if len(diff) == 1 and not diff[0][0].isascii():
                    hits.append(m)
        if len(hits) == 1:
            return hits[0]
    return None


GENUINE_CAS = {
    "eth": {
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
        "0x6c3ea9036406852006290770bedfcaba0e23a0e8": "PYUSD",
        "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409": "FDUSD",
        "0x0000000000085d4780b73119b644ae5ecd22b376": "TUSD",
        "0x8e870d67f660d95d5be530380d0ec0bd388289e1": "USDP",
        "0x4fabb145d64652a948d72533023f6e7a623c7c53": "BUSD",
        "0xdc035d45d973e3ec169d2276ddab16f1e407384f": "USDS",
        "0xe343167631d89b6ffc58b88d6b7fb0228795491d": "USDG",
        "0xb50721bcf8d664c30412cfbc6cf7a15145234ad1": "ARB",
        "0x455e53cbb86018ac2b8092fdcd39d8444affc3f6": "POL",
        "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0": "MATIC",
        "0xb8c77482e45f1f44de1745f52c74426c631bdd52": "BNB",
    },
    "base": {"0x4200000000000000000000000000000000000006": "WETH",
             "0x0555e30da8f98308edb960aa94c0db47230d2b9c": "WBTC",
             "0x820c137fa70c8691f0e44dc420a5e53c168921dc": "USDS"},
    "arbitrum": {
        "0x82af49447d8a07e3bd95bd0d56f35241523fbab1": "WETH",
        "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f": "WBTC",
        "0x912ce59144191c1204e64559fe8253a0e49e6548": "ARB",
    },
    "optimism": {
        "0x4200000000000000000000000000000000000006": "WETH",
        "0x4200000000000000000000000000000000000042": "OP",
        "0x68f180fcce6836688e9084f035309e29bf0a2095": "WBTC",
        "0x01bff41798a0bcf287b996046ca68b395dbc1071": "USDT0",
    },
    "polygon": {
        "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619": "WETH",
        "0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6": "WBTC",
        "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270": "WPOL",
        "0x0000000000000000000000000000000000001010": "POL",
    },
    "bsc": {
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": "WBNB",
        "0x2170ed0880ac9a755fd29b2688956bd959f933f8": "ETH",
        "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": "BTCB",
        "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
        "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409": "FDUSD",
        "0x40af3827f39d0eacbf4a168f8d4ee67c121d11c9": "TUSD",
        "0x1d2f0da169ceb9fc7b3144628db156f3f6c60dbe": "XRP",
        "0x570a5d26f7765ecb712c0924e4de545b89fd43df": "SOL",
        "0x1ce0c2827e2ef14d5c4f29a091d735a204794041": "AVAX",
        "0xce7de646e7208a4ef112cb6ed5038fa6cc6b12e3": "TRX",
        "0xcc42724c6683b7e57334c4e856f4c9965ed682bd": "MATIC",
    },
    "zksync": {
        "0x000000000000000000000000000000000000800a": "ETH",
        "0x5aea5775959fbc2557cc8789bc1bf90a239d9a91": "WETH",
        "0x4b9eb6c0b6ea15176bbf62841c6b2a8a398cb656": "DAI",
    },
    "scroll": {"0x5300000000000000000000000000000000000004": "WETH"},
    "gnosis": {"0x6a023ccd1ff6f2045c3309768ead9e68f978f6e1": "WETH"},
    "arc": {
        "0x3600000000000000000000000000000000000000": "USDC",
        "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1": "EURC",
        "0x171a4217b86a807a64eb94757db6849fb4bdbaa0": "cirBTC",
        "0x128cc466b61f542da60c70e3aa11c10e19b84edb": "WETH",
    },
    "sol": {
        "So11111111111111111111111111111111111111112": "WSOL",
        "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": "PYUSD",
        "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB": "USD1",
        "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": "WETH",
        "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT": "USDE",
    },
}
try:
    import common as _common
    for _ch9, _m9 in _common.EXTRA_CHAINS.items():
        if _m9[3]:
            GENUINE_CAS.setdefault(_ch9, {}).setdefault(_m9[3].lower(), "W" + _m9[1])
except ImportError:
    pass
_ALIAS = {"TETHER": "USDT", "TETHERUSD": "USDT", "BSCUSD": "USDT", "USDCOIN": "USDC", "ETHER": "ETH", "ETHEREUM": "ETH",
          "WRAPPEDETHER": "WETH", "BITCOIN": "BTC", "WRAPPEDBTC": "WBTC", "WRAPPEDBITCOIN": "WBTC", "SOLANA": "SOL",
          "WRAPPEDSOL": "WSOL", "BINANCECOIN": "BNB"}
_GEN = None


USER_FILE = "genuine_tokens.json"
USER_EVERY = 5.0
USER_MAX = 2000
_USER = {"sig": None, "at": None, "set": frozenset(), "map": {}}
_USER_LOCK = threading.Lock()


def user_path():
    try:
        import common
        return os.path.join(common.STATE_DIR, USER_FILE)
    except Exception:
        return None


def _norm_ca(chain, ca):
    ch = str(chain or "").strip().lower()
    a = str(ca or "").strip()
    return ch, (a if ch == "sol" else a.lower())


def _user_read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return frozenset(), {}
    except (OSError, ValueError):
        return frozenset(), {}
    s, out = set(), {}
    if not isinstance(d, dict):
        return frozenset(), {}
    for ch, m in d.items():
        if not isinstance(ch, str) or ch.startswith("_") or not isinstance(m, dict):
            continue
        for a, sym in m.items():
            if not isinstance(a, str) or a.startswith("_") or len(s) >= USER_MAX:
                continue
            k = _norm_ca(ch, a)
            if not k[0] or not k[1]:
                continue
            s.add(k)
            out.setdefault(k[0], {})[k[1]] = str(sym)[:24] if isinstance(sym, str) else ""
    return frozenset(s), out


def _user_refresh(force=False):
    now = time.monotonic()
    u = _USER
    if not force and u["at"] is not None and now - u["at"] < USER_EVERY:
        return u
    with _USER_LOCK:
        p = user_path()
        try:
            st = os.stat(p) if p else None
            sig = (p, st.st_mtime_ns, st.st_size) if st else (p, None, None)
        except OSError:
            sig = (p, None, None)
        if force or sig != u["sig"]:
            s, m = _user_read(p) if p and sig[1] is not None else (frozenset(), {})
            u.update(sig=sig, set=s, map=m)
        u["at"] = now
    return u


def user_sig():
    return _user_refresh()["sig"]


def user_tokens() -> dict:
    return {ch: dict(m) for ch, m in _user_refresh()["map"].items()}


def is_user_genuine(chain, ca) -> bool:
    return _norm_ca(chain, ca) in _user_refresh()["set"]


def set_user_genuine(chain, ca, sym, on: bool) -> bool:
    import common
    p = user_path()
    ch, a = _norm_ca(chain, ca)
    with _USER_LOCK:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                d = {}
        except FileNotFoundError:
            d = {}
        except (OSError, ValueError):
            raise ValueError("정품 목록 파일이 깨져 있어요 — state/" + USER_FILE + " 를 고치거나 지운 뒤 다시")
        m = d.get(ch) if isinstance(d.get(ch), dict) else {}
        hit = next((k for k in m if isinstance(k, str) and _norm_ca(ch, k)[1] == a), None)
        if on:
            if hit is not None:
                return False
            if sum(len(v) for k, v in d.items() if isinstance(v, dict) and not str(k).startswith("_")) >= USER_MAX:
                raise ValueError(f"정품 목록이 가득 찼어요({USER_MAX}개)")
            m[a] = str(sym or "")[:24]
        else:
            if hit is None:
                return False
            m.pop(hit, None)
        if m:
            d[ch] = m
        else:
            d.pop(ch, None)
        common.atomic_write_json(p, d)
    _user_refresh(force=True)
    return True


def plain_symbol(sym) -> bool:
    s = str(sym or "")
    return bool(s.strip()) and clean(s) == s and s.replace("₮", "T").isascii()


def _genuine():
    global _GEN
    if _GEN is None:
        s = set()
        for ch, m in GENUINE_CAS.items():
            s |= {(ch, a if ch == "sol" else a.lower()) for a in m}
        try:
            import pricing
            for tab in (pricing.STABLE_CAS, pricing.JPY_STABLE_CAS):
                for ch, m in tab.items():
                    s |= {(ch, a.lower()) for a in m}
            s |= {("sol", a) for a in pricing.STABLE_MINTS}
        except Exception:
            pass
        _GEN = s
    return _GEN


def is_genuine(chain, ca) -> bool:
    ch = str(chain or "")
    a = str(ca or "")
    k = (ch, a if ch == "sol" else a.lower())
    return k in _genuine() or k in _user_refresh()["set"]


def major_of(sym):
    f = fold(sym)
    if not f.strip():
        return None
    for c0 in (_head(f), re.sub(r"[^A-Z0-9]", "", f)):
        for c in (c0, "".join(_DIGIT.get(x, x) for x in c0)):
            if c in MAJORS:
                return c
            if c in _ALIAS:
                return _ALIAS[c]
    return None


def fake_major(sym, pairs):
    pairs = [p for p in (pairs or []) if p and p[1]]
    if not pairs:
        return None
    m = major_of(sym)
    if not m:
        return None
    return None if any(is_genuine(ch, ca) for ch, ca in pairs) else m


_ODD_SPACE = re.compile("[ -   　 ᠎]")


def odd_symbol(sym):
    s = clean(sym)
    if not s:
        return None
    if _ODD_SPACE.search(s):
        return "보이지 않는 공백 섞임"
    letters = [ch for ch in s if ch.isalpha()]
    if any(ch.isascii() for ch in letters) and any(ch in _CONF for ch in letters):
        return "라틴·키릴·그리스 등 혼용 문자"
    for ch in s:
        o = ord(ch)
        if 0x1D400 <= o <= 0x1D7FF:
            return "수학 글꼴 문자"
        if 0x0250 <= o <= 0x02AF or 0x1D00 <= o <= 0x1DBF or 0xA720 <= o <= 0xA7FF or 0x2C60 <= o <= 0x2C7F:
            return "유사 라틴 문자(IPA·소형 대문자)"
    nfd = unicodedata.normalize("NFD", s)
    for i, ch in enumerate(nfd):
        if unicodedata.combining(ch) and i and nfd[i - 1].isascii() and nfd[i - 1].isalpha():
            return "결합 부호 붙은 라틴 글자"
    return None


def snapshot_synth(fee_value, raw_input) -> bool:
    return str(raw_input) == "0x01" or str(fee_value) == "0"


def signer_known_other(tx_from, fee_value, raw_input, my) -> bool:
    if snapshot_synth(fee_value, raw_input) or not tx_from:
        return False
    f = str(tx_from)
    return not (f in my or f.lower() in my)


def signer_mine(tx_from, fee_value, raw_input, my) -> bool:
    if snapshot_synth(fee_value, raw_input):
        return False
    f = str(tx_from or "")
    return f in my or f.lower() in my


STABLE_MAJ = {"USDT", "USDC", "USDG", "DAI", "BUSD", "FDUSD", "PYUSD", "USD1", "USDE", "USDS", "TUSD", "USDP", "USDT0"}
POISON_STABLE_QTY = 0.001


def tx_scam_reason(conn, chain, txh, my, price_guard=None):
    ch = str(chain or "")
    t = str(txh or "")
    t = t.lower() if t.startswith("0x") else t
    try:
        legs = conn.execute(
            "SELECT p.leg_kind, p.event, p.qty_base, a.asset_id, a.kind, a.address, a.symbol, a.decimals, g.name"
            " FROM postings p JOIN assets a ON a.asset_id = p.asset_id LEFT JOIN asset_groups g ON g.group_id = a.group_id"
            " WHERE p.source_ns=? AND p.source_id=? AND p.location LIKE 'wallet:%'"
            " AND p.leg_kind IN ('acq', 'disp', 'move_in', 'move_out')", (ch, t)).fetchall()
        if not legs:
            return None
        if ch == "sol":
            sg = conn.execute("SELECT json_extract(snapshot, '$.fee_payer'), NULL, NULL FROM raw_txs WHERE chain=? AND txhash=?"
                              " AND json_valid(snapshot)", (ch, t)).fetchone()
        else:
            sg = conn.execute("SELECT COALESCE(json_extract(snapshot, '$.tx.from.hash'), json_extract(snapshot, '$.tx.from')),"
                              " json_extract(snapshot, '$.tx.fee.value'), json_extract(snapshot, '$.tx.raw_input')"
                              " FROM raw_txs WHERE chain=? AND txhash=? AND json_valid(snapshot)", (ch, t)).fetchone()
    except Exception:
        return None
    mine = bool(sg) and signer_mine(sg[0], sg[1], sg[2], my)
    why = None
    for lk, ev, qb, aid, kind, ca, sym, dec, gname in legs:
        s = sym or re.sub(r"#\d+$", "", gname or "")
        try:
            q = abs(int(qb)) / (10 ** int(dec if dec is not None else 18))
        except (TypeError, ValueError):
            return None
        r = None
        if q == 0:
            r = "수량 0 전송(주소 오염)"
        elif mine and lk in ("move_out", "disp"):
            return None
        elif kind == "token":
            priced = None

            def _priced():
                return conn.execute("SELECT 1 FROM postings WHERE asset_id=? AND leg_kind IN ('acq', 'disp') AND cost_usd IS NOT NULL LIMIT 1",
                                    (aid,)).fetchone() is not None
            if impostor_of(s) or odd_symbol(s):
                priced = _priced()
                r = None if priced or is_genuine(ch, ca) else "사칭 심볼 토큰"
            elif fake_major(s, [(ch, ca)]):
                priced = _priced()
                liq = False
                if not priced and plain_symbol(s):
                    liq = spot_liquid(ch, ca, price_guard)
                    if liq is None:
                        return None
                r = None if priced or liq else f"가짜 {major_of(s)}(정품 컨트랙트 아님)"
            if r is None and lk == "move_out" and ch != "sol" and sg and signer_known_other(sg[0], sg[1], sg[2], my) \
                    and not is_genuine(ch, ca):
                has_inflow = conn.execute(
                    "SELECT 1 FROM postings WHERE asset_id=? AND location LIKE 'wallet:%'"
                    " AND leg_kind IN ('opening', 'acq', 'move_in') AND CAST(qty_base AS REAL)>0 LIMIT 1",
                    (aid,)).fetchone() is not None
                r = None if has_inflow or (priced if priced is not None else _priced()) else "가짜 전송(내가 서명하지 않음)"
            if r is None and lk == "acq" and not mine and sg and is_genuine(ch, ca) and major_of(s) in STABLE_MAJ \
                    and q <= POISON_STABLE_QTY:
                r = "주소 오염 초소액 수령"
        if r is None:
            return None
        why = why or r
    return why


SPOT_FILE = "spot.json"
RESERVE_STALE_SEC = 6 * 3600
_SPOT = {"sig": None, "d": None}


def spot_liquid(chain, ca, price_guard=None):
    try:
        import common
        p = os.path.join(common.STATE_DIR, SPOT_FILE)
        st = os.stat(p)
    except FileNotFoundError:
        return False
    except Exception:
        return None
    sig = (p, st.st_mtime_ns, st.st_size)
    if _SPOT["sig"] != sig:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                return None
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            return None
        _SPOT.update(sig=sig, d=d)
    d = _SPOT["d"]
    g = price_guard if isinstance(price_guard, dict) else {}
    try:
        mn = float(g.get("min_reserve_usd", 10000.0))
    except (TypeError, ValueError):
        mn = 10000.0
    try:
        mx = max(1800.0, float(g.get("dex_max_age_sec", 6 * 3600)))
    except (TypeError, ValueError):
        mx = 6 * 3600.0
    ch, a = _norm_ca(chain, ca)
    k = f"{ch}:{a}"
    try:
        now = time.time()
        px = float((d.get("dex_usd") or {}).get(k) or 0)
        rv = (d.get("dex_res") or {}).get(k)
        if rv is None or now - float((d.get("dex_res_ts") or {}).get(k) or 0) > RESERVE_STALE_SEC:
            return False
        if now - float((d.get("dex_ts") or {}).get(k) or 0) > mx:
            return False
        return 0 < px < float("inf") and mn <= float(rv) < float("inf")
    except (TypeError, ValueError, AttributeError):
        return None


_CS_MEMO = {}
_CS_MEMO_MAX = 200000


def _clean_str(v: str) -> str:
    if v.isascii():
        return v
    r = _CS_MEMO.get(v, _CS_MEMO)
    if r is _CS_MEMO:
        r = clean(v) if any(_drop(ch) for ch in v) else None
        if len(_CS_MEMO) < _CS_MEMO_MAX:
            _CS_MEMO[v] = r
    return v if r is None else r


def annotate(obj, _depth: int = 0):
    n = 0
    if _depth > 8:
        return 0
    if isinstance(obj, dict):
        s = obj.get("sym")
        if isinstance(s, str) and s:
            c = clean(s)
            imp = impostor_of(s)
            if c != s:
                obj["symRaw"] = s
                obj["sym"] = c
                n += 1
            if imp:
                obj["imp"] = imp
                n += 1
        for k, v in list(obj.items()):
            if isinstance(v, (dict, list)):
                n += annotate(v, _depth + 1)
            elif isinstance(v, str) and k not in ("symRaw",):
                c = _clean_str(v)
                if c is not v:
                    obj[k] = c
                    n += 1
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                n += annotate(v, _depth + 1)
            elif isinstance(v, str):
                c = _clean_str(v)
                if c is not v:
                    obj[i] = c
                    n += 1
    return n
