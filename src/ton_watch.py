from __future__ import annotations

import base64
import fcntl
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config, logs, net_http, paths, runtime, statefile  # noqa: E402
import address_codec as ac  # noqa: E402
import chain_event  # noqa: E402
import chain_registry as reg  # noqa: E402
import chain_state  # noqa: E402
import chain_watch  # noqa: E402
from chain_watch import Transient  # noqa: E402

CHAIN = "ton"
PROVIDER = "toncenter_v3"
PARSER_VERSION = 1
DEFAULT_BASE = "https://toncenter.com/api/v3"
KEY_ENV = reg.spec(CHAIN).key_env
KEYLESS_RPS = 1.0
KEY_RPS = 10.0
BODY_CAP = 16 * 1024 * 1024
PAGE_DEFAULT = 100
JW_PAGE = 100
JW_MAX_PAGES = 20
EMPTY_TRIES = 3
JW_VERIFY_PER_PASS = 10
ROOTS_KEEP = 20000
SELF_WAIT_TRIES = 3
META_RETRY_SEC = 600
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

OP_JETTON_TRANSFER = 0x0F8A7EA5
OP_INTERNAL_TRANSFER = 0x178D4519
OP_BURN = 0x595F07BC
OP_BURN_NOTIFICATION = 0x7BDD97DE
OP_TRANSFER_NOTIFICATION = 0x7362D09C
OP_EXCESS = 0xD53276DB
OP_TOP_UP = 0xD372158C
OP_BOUNCED = 0xFFFFFFFF
JETTON_OUT_OPS = (OP_JETTON_TRANSFER, OP_BURN)
REFUND_IN_OPS = (OP_EXCESS, OP_TRANSFER_NOTIFICATION)
JETTON_BENIGN_OPS = (None, 0, OP_EXCESS, OP_TOP_UP)


_BOC_MAGIC = bytes.fromhex("b5ee9c72")


def _b64dec(s: str) -> bytes:
    s = str(s or "").strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)


def boc_root_bits(b64: str) -> str:
    raw = _b64dec(b64)
    if raw[:4] != _BOC_MAGIC:
        raise ValueError("BoC 머리(b5ee9c72) 아님")
    if len(raw) < 6:
        raise ValueError("BoC 가 짧음")
    flags = raw[4]
    has_idx, size = flags & 0x80, flags & 0x07
    off = raw[5]
    if not 1 <= size <= 4 or not 1 <= off <= 8:
        raise ValueError("BoC 크기 칸 오류")
    p = 6

    def rd(n):
        nonlocal p
        if p + n > len(raw):
            raise ValueError("BoC 가 잘림")
        v = int.from_bytes(raw[p:p + n], "big")
        p += n
        return v
    cells, roots, _absent, _tot = rd(size), rd(size), rd(size), rd(off)
    if not 1 <= cells <= 4096 or roots < 1:
        raise ValueError("BoC 셀 수 오류")
    root = rd(size)
    for _i in range(roots - 1):
        rd(size)
    if has_idx:
        p += cells * off
    out = []
    for _i in range(cells):
        d1, d2 = rd(1), rd(1)
        if d1 & 16:
            lvl = bin(d1 >> 5).count("1") + 1
            p += lvl * (32 + 2)
        nb = (d2 + 1) // 2
        if p + nb > len(raw):
            raise ValueError("BoC 셀 데이터 잘림")
        bits = "".join(f"{x:08b}" for x in raw[p:p + nb])
        p += nb
        if d2 & 1:
            j = bits.rfind("1")
            if j < 0:
                raise ValueError("BoC 완성 비트 없음")
            bits = bits[:j]
        p += (d1 & 7) * size
        out.append(bits)
    if root >= cells:
        raise ValueError("BoC 뿌리 번호 오류")
    return out[root]


def boc_one_cell(bits: str) -> str:
    n = len(bits)
    if n > 1023:
        raise ValueError("셀 비트 1023 초과")
    b = bits
    if n % 8:
        b += "1"
        b += "0" * (-len(b) % 8)
    data = bytes(int(b[i:i + 8], 2) for i in range(0, len(b), 8))
    cell = bytes([0, (n // 8) + ((n + 7) // 8)]) + data
    return base64.b64encode(_BOC_MAGIC + bytes([0x01, 0x01, 1, 1, 0, len(cell), 0]) + cell).decode()


def addr_bits(key: str) -> str:
    wc, h = ac.ton_parse(key)
    return "10" + "0" + format(wc & 0xFF, "08b") + format(int(h, 16), "0256b")


class Bits:

    def __init__(self, s: str):
        self.s, self.i = s, 0

    def u(self, n: int) -> int:
        if n < 0 or self.i + n > len(self.s):
            raise ValueError("본문 비트 모자람")
        v = int(self.s[self.i:self.i + n], 2) if n else 0
        self.i += n
        return v

    def coins(self) -> int:
        return self.u(8 * self.u(4))

    def addr(self):
        tag = self.u(2)
        if tag == 0:
            return None
        if tag != 2 or self.u(1):
            raise ValueError("addr_std 아닌 주소(anycast·extern·var)")
        wc = self.u(8)
        wc = wc - 256 if wc > 127 else wc
        return f"{wc}_{self.u(256):064x}"


def parse_jetton_body(b64: str, expect_op: int) -> dict:
    r = Bits(boc_root_bits(b64))
    op = r.u(32)
    out = {"bounced": False}
    if op == OP_BOUNCED:
        out["bounced"] = True
        op = r.u(32)
    if expect_op is not None and op != expect_op:
        raise ValueError(f"본문 op {op:08x} ≠ {expect_op:08x}")
    out["op"] = op
    out["qid"] = r.u(64)
    out["amount"] = r.coins()
    if out["bounced"]:
        return out
    if op == OP_JETTON_TRANSFER:
        out["dest"] = r.addr()
    elif op == OP_INTERNAL_TRANSFER:
        out["from"] = r.addr()
    return out


def bounced_op(b64) -> int | None:
    try:
        r = Bits(boc_root_bits(b64))
        return r.u(32) if r.u(32) == OP_BOUNCED else None
    except (ValueError, TypeError):
        return None


def hhex(b64) -> str:
    s = str(b64 or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", s):
        return s.lower()
    b = _b64dec(s)
    if len(b) != 32:
        raise ValueError("해시 길이 오류")
    return b.hex()


def hb64(hx: str) -> str:
    return base64.b64encode(bytes.fromhex(hx)).decode()


def akey(raw):
    if raw in (None, ""):
        return None
    return ac.ton_key(str(raw))


def tx_uid(acct: str, lt, hx: str) -> str:
    return f"{acct}.{int(lt)}.{hx}"


def _op(v):
    if v in (None, ""):
        return None
    try:
        return int(str(v), 16) & 0xFFFFFFFF
    except ValueError:
        return None


def _int(v, what, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool):
        raise ValueError(what)
    return int(str(v))


def _xc(*objs) -> bool:
    return any(isinstance(o, dict) and any(str(v) not in ("0", "") for v in o.values()) for o in objs)


def compact(t: dict) -> dict:
    if not isinstance(t, dict):
        raise Transient("tx 형식 오류")
    try:
        desc = t.get("description")
        if not isinstance(desc, dict) or not isinstance(desc.get("aborted"), bool):
            raise ValueError("description.aborted 없음")
        sb, sa = t.get("account_state_before") or {}, t.get("account_state_after") or {}
        if "in_msg" not in t or not isinstance(t.get("out_msgs"), list):
            raise ValueError("in_msg·out_msgs 칸 없음")
        im = t.get("in_msg")
        if im is not None and not isinstance(im, dict):
            raise ValueError("in_msg 형식 오류")
        if im is None and desc.get("type", "ord") == "ord":
            raise ValueError("일반(ord) tx 인데 in_msg 없음")
        ci = None
        xc = _xc(t.get("total_fees_extra_currencies"), sb.get("extra_currencies"), sa.get("extra_currencies"))
        if isinstance(im, dict):
            src = akey(im.get("source"))
            op = _op(im.get("opcode"))
            bounced = im.get("bounced") is True
            body = (im.get("message_content") or {}).get("body")
            if src is not None and im.get("value") is None:
                raise ValueError("내부 메시지 value 없음")
            ci = {"src": src, "val": _int(im.get("value"), "in.value") if src else 0, "op": op, "b": bounced, "h": hhex(im["hash"])}
            if bounced or op in (OP_JETTON_TRANSFER, OP_INTERNAL_TRANSFER, OP_BURN):
                if not isinstance(body, str) or not body:
                    raise ValueError("제톤·되돌아온 메시지 본문 없음")
                ci["body"] = body
            xc = xc or _xc(im.get("value_extra_currencies"))
        outs = []
        for m in t["out_msgs"]:
            if not isinstance(m, dict):
                raise ValueError("out_msgs 형식 오류")
            dst = m.get("destination")
            if dst in (None, ""):
                outs.append({"dst": None, "val": 0, "fwd": _int(m.get("fwd_fee") or 0, "out.fwd"), "op": None, "h": ""})
                continue
            outs.append({"dst": akey(dst), "val": _int(m.get("value"), "out.value"), "fwd": _int(m.get("fwd_fee"), "out.fwd"),
                         "op": _op(m.get("opcode")), "h": hhex(m["hash"])})
            xc = xc or _xc(m.get("value_extra_currencies"))
        pl, ph = _int(t["prev_trans_lt"], "prev_lt"), hhex(t["prev_trans_hash"])
        if pl < 0 or (pl == 0) != (ph == "0" * 64):
            raise ValueError("prev LT·hash 모순(첫 tx 판정 불가)")
        mc = t.get("mc_block_seqno")
        return {"a": akey(t["account"]), "lt": str(_int(t["lt"], "lt")), "h": hhex(t["hash"]), "now": _int(t["now"], "now"),
                "mc": _int(mc, "mc", True), "pl": str(pl), "ph": ph,
                "fin": t.get("finality"), "em": t.get("emulated") is True, "tf": _int(t["total_fees"], "total_fees"),
                "ab": desc["aborted"], "tr": hhex(t["trace_id"]) if t.get("trace_id") else "",
                "bb": _int(sb.get("balance"), "before", True), "ba": _int(sa.get("balance"), "after", True),
                "in": ci, "out": outs, "xc": bool(xc)}
    except (KeyError, TypeError, ValueError) as e:
        raise Transient(f"tx 해석 실패: {str(e)[:80]}") from None


def finalized(ct: dict) -> bool:
    return ct.get("mc") is not None and not ct.get("em") and ct.get("fin") in (None, "finalized")


def wallet_effect(ct: dict, own_jw=frozenset(), roots: dict = None) -> dict:
    im = ct.get("in") or None
    internal = bool(im and im.get("src"))
    inv = int(im.get("val") or 0) if internal else 0
    outs = ct.get("out") or []
    fee_tf = int(ct["tf"]) + sum(int(o["fwd"]) for o in outs)
    flow = inv - sum(int(o["val"]) for o in outs) - fee_tf
    reasons = []
    if ct.get("bb") is not None and ct.get("ba") is not None:
        net = int(ct["ba"]) - int(ct["bb"])
        fee_ok = net == flow
        if not fee_ok:
            reasons.append("fee_unresolved")
    else:
        net, fee_ok = flow, True
        reasons.append("state_balance_missing")
    if ct.get("xc"):
        reasons.append("extra_currency_ignored")
    bounced = internal and im.get("b") is True
    orig = bounced_op(im.get("body")) if bounced else None
    jet_out = sum(int(o["val"]) for o in outs if o.get("op") in JETTON_OUT_OPS and o.get("dst") in own_jw)
    op_in = im.get("op") if internal else None
    ex_ok = op_in == OP_EXCESS and (roots is None or im.get("src") in own_jw or (ct.get("tr") or "") in roots)
    refund = inv if internal and ((not bounced and (ex_ok or (op_in == OP_TRANSFER_NOTIFICATION and im.get("src") in own_jw)))
                                  or (bounced and orig in JETTON_OUT_OPS and im.get("src") in own_jw)) else 0
    fee = (fee_tf + jet_out - refund) if fee_ok else None
    moves = []
    if internal and inv and not refund:
        moves.append((im["src"], ct["a"], inv))
    for o in outs:
        if o.get("dst") and int(o["val"]) > 0 and not (o.get("op") in JETTON_OUT_OPS and o.get("dst") in own_jw):
            moves.append((ct["a"], o["dst"], int(o["val"])))
    ev = "ton:wallet" + (":bounce" if bounced else "") + (":jetton_gas" if jet_out else "") + (":refund" if refund else "")
    return {"net": net, "fee": fee, "failed": (not internal) and bool(ct.get("ab")), "hint": "program_in" if (bounced and not refund) else "transfer",
            "moves": moves, "reasons": reasons, "ev": ev}


def jetton_effect(ct: dict, owner: str, master: str) -> dict:
    im = ct.get("in") or None
    base = {"delta": 0, "cp": None, "hint": "transfer", "reasons": [], "ev": "ton:jetton", "kind": None}
    if not im:
        return base
    op, src = im.get("op"), im.get("src")
    if ct.get("ab"):
        base["ev"] += ":aborted"
        return base
    try:
        if im.get("b"):
            bo = bounced_op(im.get("body"))
            if bo in (OP_INTERNAL_TRANSFER, OP_BURN_NOTIFICATION):
                b = parse_jetton_body(im["body"], bo)
                return dict(base, delta=int(b["amount"]), hint="program_in", ev="ton:jetton:bounce_refund", kind="refund")
            return dict(base, ev="ton:jetton:bounce_other")
        if op == OP_JETTON_TRANSFER:
            if src != owner:
                return dict(base, reasons=["jetton_transfer_not_from_owner"], ev="ton:jetton:foreign_cmd")
            b = parse_jetton_body(im["body"], op)
            return dict(base, delta=-int(b["amount"]), cp=b.get("dest"), ev="ton:jetton:transfer_out", kind="out", qid=b["qid"])
        if op == OP_INTERNAL_TRANSFER:
            b = parse_jetton_body(im["body"], op)
            mint = src == master
            return dict(base, delta=int(b["amount"]), cp=b.get("from") if not mint else master, hint="program_in" if mint else "transfer",
                        ev="ton:jetton:" + ("mint" if mint else "transfer_in"), kind="mint" if mint else "in", qid=b["qid"])
        if op == OP_BURN:
            if src != owner:
                return dict(base, reasons=["jetton_burn_not_from_owner"], ev="ton:jetton:foreign_cmd")
            b = parse_jetton_body(im["body"], op)
            return dict(base, delta=-int(b["amount"]), ev="ton:jetton:burn", kind="burn")
    except (KeyError, ValueError, TypeError) as e:
        raise Transient(f"제톤 본문 해석 실패({ct.get('a', '')[:10]}…): {str(e)[:60]}") from None
    if op not in JETTON_BENIGN_OPS:
        return dict(base, reasons=[f"jetton_op_unrecognized:{op:08x}"], ev="ton:jetton:other")
    return base


_PACE_LOCK = threading.Lock()


def _env_key():
    v = os.environ.get(KEY_ENV) or runtime._env_file_value(KEY_ENV) or ""
    v = str(v).strip()
    return v if KEY_RE.match(v) else None


class TonClient:

    def __init__(self, c9: dict = None, *, base=None, key=None, opener=None, min_interval=None, timeout=None, pace_file=None):
        c9 = c9 if isinstance(c9, dict) else {}
        self.base = str(base or c9.get("base_url") or DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlsplit(self.base)
        if u.scheme != "https" and u.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("toncenter 주소는 https 만(시험 루프백 제외)")
        self.key = _env_key() if key is None else (key or None)
        if min_interval is None:
            quota = 1.0 / (KEY_RPS * 0.8) if self.key else 1.0 / KEYLESS_RPS + 0.1
            mi = c9.get("min_interval_sec")
            min_interval = max(quota, float(mi)) if isinstance(mi, (int, float)) and not isinstance(mi, bool) and mi >= 0 else quota
        self.min_interval = float(min_interval)
        self.timeout = float(timeout or c9.get("timeout_sec") or 20)
        self._open = opener
        self.pace_file = pace_file
        self._next_local = 0.0
        self.calls = 0

    def _pace(self):
        iv = self.min_interval
        if iv <= 0:
            return
        path = self.pace_file or paths.state("ton_pace.lock")
        with _PACE_LOCK:
            now = time.time()
            slot = None
            try:
                fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError:
                fd = None
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    try:
                        nxt = float(os.pread(fd, 40, 0).decode("ascii", "ignore").strip() or 0)
                    except ValueError:
                        nxt = 0.0
                    if nxt > now + 120:
                        nxt = now
                    slot = max(now, nxt)
                    os.pwrite(fd, f"{slot + iv:.3f}".ljust(40).encode(), 0)
                except OSError:
                    slot = None
                finally:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    finally:
                        os.close(fd)
            if slot is None:
                slot = max(now, self._next_local)
            self._next_local = slot + iv
        wait = slot - time.time()
        if wait > 0:
            time.sleep(wait)

    def req(self, method: str, path: str, params=None, body=None) -> dict:
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        headers = {"Accept": "application/json", "User-Agent": "tj-ton/1"}
        if self.key:
            headers["X-API-Key"] = self.key
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        rq = net_http.request(url, data=data, headers=headers, method=method)
        self._pace()
        self.calls += 1
        opener = self._open or (net_http.auth_urlopen if self.key else net_http.urlopen)
        try:
            with opener(rq, timeout=self.timeout) as r:
                raw = net_http.read_capped(r, BODY_CAP)
        except urllib.error.HTTPError as e:
            raise Transient(f"toncenter HTTP {e.code} {path}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            raise Transient(f"toncenter 연결·본문 실패 {path}: {type(e).__name__}") from None
        try:
            d = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise Transient(f"toncenter JSON 깨짐 {path}") from None
        if not isinstance(d, dict) or d.get("error") not in (None, "", False):
            raise Transient(f"toncenter 오류 응답 {path}")
        return d

    def _list(self, d, key, path):
        v = d.get(key)
        if not isinstance(v, list):
            raise Transient(f"toncenter {path}: '{key}' 칸 없음")
        return v

    def transactions(self, raw: str, *, sort: str, limit: int, start_lt=None, end_lt=None) -> list:
        p = {"account": raw, "limit": int(limit), "offset": 0, "sort": sort}
        if start_lt is not None:
            p["start_lt"] = int(start_lt)
        if end_lt is not None:
            p["end_lt"] = int(end_lt)
        rows = self._list(self.req("GET", "/transactions", p), "transactions", "/transactions")
        if len(rows) > int(limit):
            raise Transient("toncenter: 요청보다 많은 행")
        return rows

    def by_message(self, msg_hex: str, direction: str) -> list:
        d = self.req("GET", "/transactionsByMessage", {"msg_hash": hb64(msg_hex), "direction": direction, "limit": 10, "offset": 0})
        return self._list(d, "transactions", "/transactionsByMessage")

    def jetton_wallets(self, *, owner_raw=None, address_raw=None) -> tuple:
        rows, done, off = [], False, 0
        for _pg in range(JW_MAX_PAGES):
            p = {"limit": JW_PAGE, "offset": off, "exclude_zero_balance": "false"}
            if owner_raw:
                p["owner_address"] = owner_raw
            if address_raw:
                p["address"] = address_raw
            part = self._list(self.req("GET", "/jetton/wallets", p), "jetton_wallets", "/jetton/wallets")
            rows += part
            off += len(part)
            if not part or address_raw:
                done = True
                break
        return rows, done

    def jetton_master(self, raw: str) -> tuple:
        d = self.req("GET", "/jetton/masters", {"address": raw, "limit": 1, "offset": 0})
        rows = self._list(d, "jetton_masters", "/jetton/masters")
        md = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
        return (rows[0] if rows else None), md

    def account_states(self, raws: list) -> list:
        d = self.req("GET", "/accountStates", {"address": list(raws), "include_boc": "false"})
        return self._list(d, "accounts", "/accountStates")

    def wallet_address(self, master_raw: str, owner_key: str):
        d = self.req("POST", "/runGetMethod", body={"address": master_raw, "method": "get_wallet_address",
                                                     "stack": [{"type": "slice", "value": boc_one_cell(addr_bits(owner_key))}]})
        ec = d.get("exit_code")
        if isinstance(ec, bool) or not isinstance(ec, (int, str)) or not re.fullmatch(r"-?\d{1,10}", str(ec)):
            raise Transient("get_wallet_address exit_code 없음·형식 오류")
        if int(ec) != 0:
            return None
        st = d.get("stack")
        if not isinstance(st, list) or not st or not isinstance(st[0], dict):
            raise Transient("get_wallet_address 응답 형식 오류")
        try:
            k = Bits(boc_root_bits(st[0].get("value"))).addr()
            return ac.ton_key(k) if k else None
        except (ValueError, TypeError):
            raise Transient("get_wallet_address 주소 해석 실패") from None


def _meta_of(row, md) -> dict:
    jc = (row or {}).get("jetton_content") if isinstance((row or {}).get("jetton_content"), dict) else {}
    ti = None
    for v in (md or {}).values():
        for x in (v or {}).get("token_info") or []:
            if isinstance(x, dict) and x.get("valid") is not False and x.get("type") in (None, "jetton_masters"):
                ti = x
                break
    dec = None
    for cand in (jc.get("decimals"), ((ti or {}).get("extra") or {}).get("decimals") if ti else None):
        try:
            if cand not in (None, ""):
                d = int(str(cand))
                if 0 <= d <= 77:
                    dec = d
                    break
        except ValueError:
            continue
    if dec is None and (ti is not None or (jc and "uri" not in jc)):
        dec = 9
    sym = (ti or {}).get("symbol") or jc.get("symbol") or ""
    sym = re.sub(r"[\x00-\x1f\x7f<>]", "", str(sym)).strip()[:24] or None
    bad = dec is None and ti is None and any(isinstance(x, dict) and x.get("valid") is False and x.get("type") in (None, "jetton_masters")
                                             for v in (md or {}).values() if isinstance(v, dict) for x in (v.get("token_info") or []))
    return {"symbol": sym, "decimals": dec, "scam": bool((ti or {}).get("is_scam")), "invalid": bool(bad)}


def _floor(cfg: dict) -> int:
    if (cfg or {}).get("backfill_full_history"):
        return 0
    try:
        import bf_engine
        t = int(bf_engine.effective_backfill_t0(cfg or {}) or 0)
        s = bf_engine.SINCE.target(CHAIN)
        return int(min(t, s)) if s and t else int(s or t or 0)
    except Exception:   # noqa: BLE001 [fallback]
        return 0


class TonAdapter(reg.ChainAdapter):
    chain = CHAIN

    def __init__(self, cfg: dict, client: TonClient = None, state: chain_state.ChainState = None):
        super().__init__(cfg)
        c9 = ((self.cfg.get(reg.CFG_CHAIN_KEY) or {}) if isinstance(self.cfg.get(reg.CFG_CHAIN_KEY), dict) else {}).get(CHAIN)
        c9 = c9 if isinstance(c9, dict) else {}
        pg = c9.get("page_limit", PAGE_DEFAULT)
        self.page = max(2, min(256, int(pg))) if isinstance(pg, int) and not isinstance(pg, bool) else PAGE_DEFAULT
        self.client = client or TonClient(c9)
        self.st = state
        self._pass = {}
        self._fail = {}
        self._miss = {}
        self._cover = {}

    def bind_state(self, st: chain_state.ChainState) -> None:
        self.st = st

    def _T(self) -> dict:
        if self.st is None:
            raise RuntimeError("TON 어댑터에 수집 상태(ChainState)가 묶이지 않음")
        t = self.st.d.get("ton")
        if not isinstance(t, dict) or t.get("v") != 1:
            t = {"v": 1, "acct": {}, "jw": {}, "meta": {}, "roots": {}}
            self.st.d["ton"] = t
        for k in ("acct", "jw", "meta", "roots", "jw_wait"):
            if not isinstance(t.get(k), dict):
                t[k] = {}
        return t

    def canonical_txid(self, text):
        return str(text)

    def _owners_vh(self, owners) -> str:
        return hashlib.sha256(("|".join(sorted(owners))).encode()).hexdigest()[:16]

    def discovery_query(self, owner, lane):
        key = (lane, owner)
        if lane == "latest" and key in self._pass:
            self._pass[key].discard(owner)
        return {"owner": owner, "lane": lane}, f"{PROVIDER}|p{PARSER_VERSION}|{lane}"

    def _accts(self, owner) -> list:
        A = self._T()["acct"]
        return sorted((k for k, a in A.items() if a.get("owner") == owner), key=lambda k: (A[k].get("kind") != "wallet", k))

    def discover_page(self, owner, query, cursor):
        lane = query.get("lane")
        T = self._T()
        key = (lane, owner)
        if cursor is None or key not in self._pass:
            self._pass[key] = set()
            self._fail[key] = []
            try:
                if lane == "latest":
                    self._fail[key] += self._refresh_accounts(owner)
                else:
                    self._reopen_history(owner)
            except Transient as e:
                self._fail[key].append("계정 목록: " + str(e)[:100])
        done = self._pass[key]
        fails = self._fail.setdefault(key, [])
        for k in self._accts(owner):
            if k in done:
                continue
            a = T["acct"][k]
            try:
                if lane == "latest":
                    items, more = self._scan_forward(k, a)
                else:
                    if a.get("hist") != "run" or not a.get("low"):
                        done.add(k)
                        continue
                    items, more = self._scan_back(k, a)
            except Transient as e:
                done.add(k)
                fails.append(f"{k[:12]}…: " + str(e)[:100])
                continue
            if not more:
                done.add(k)
            self._update_status(owner)
            rest = [x for x in self._accts(owner) if x not in done and (lane == "latest" or T["acct"][x].get("hist") == "run")]
            return items, ("1" if rest or fails else None)
        self._update_status(owner)
        if fails:
            self._pass.pop(key, None)
            self._fail.pop(key, None)
            raise Transient(f"TON 이번 차례 계정 실패 {len(fails)}건: {fails[0]}")
        return [], None

    def _refresh_accounts(self, owner) -> list:
        T = self._T()
        A = T["acct"]
        if owner not in A:
            A[owner] = {"owner": owner, "kind": "wallet", "added": int(time.time())}
        rows, complete = self.client.jetton_wallets(owner_raw=ac.ton_raw(owner))
        W = T["jw_wait"]
        if complete:
            for w9 in [w9 for w9, x in W.items() if not isinstance(x, dict) or x.get("owner") == owner]:
                W.pop(w9, None)
        fails = []
        budget = meta_budget = JW_VERIFY_PER_PASS
        now = int(time.time())
        for r in sorted(rows, key=lambda r9: -int(str(r9.get("last_transaction_lt") or 0)) if str(r9.get("last_transaction_lt") or "0").isdigit() else 0):
            try:
                w, m, o = akey(r.get("address")), akey(r.get("jetton")), akey(r.get("owner"))
            except ValueError:
                continue
            if not w or not m or o != owner:
                continue
            v = T["jw"].get(w)
            if not isinstance(v, dict) or v.get("master") != m or v.get("owner") != owner:
                if budget <= 0:
                    W[w] = {"owner": owner, "master": m, "at": now}
                    continue
                budget -= 1
                try:
                    calc = self.client.wallet_address(ac.ton_raw(m), owner)
                except Transient as e:
                    W[w] = {"owner": owner, "master": m, "at": now}
                    fails.append("제톤 지갑 검증: " + str(e)[:80])
                    continue
                ok = calc == w
                v = {"owner": owner, "master": m, "ok": ok, "at": now, "why": "" if ok else "get_wallet_address 불일치(가짜 제톤 지갑)"}
                T["jw"][w] = v
            W.pop(w, None)
            if not v.get("ok"):
                continue
            mm = T["meta"].get(m)
            if (not isinstance(mm, dict) or mm.get("decimals") is None) and meta_budget > 0 \
                    and (not isinstance(mm, dict) or now - int(mm.get("at") or 0) >= META_RETRY_SEC):
                meta_budget -= 1
                try:
                    row, md = self.client.jetton_master(ac.ton_raw(m))
                    T["meta"][m] = dict(_meta_of(row, md), at=now)
                except Transient as e:
                    fails.append("제톤 메타: " + str(e)[:80])
            a = A.get(w)
            if a is None:
                A[w] = a = {"owner": owner, "kind": "jetton", "master": m, "added": int(time.time())}
            hw = a.get("hw")
            if hw and str(r.get("last_transaction_lt") or "") == str(hw[0]):
                self._pass[("latest", owner)].add(w)
        return fails

    def _reopen_history(self, owner) -> None:
        fl = _floor(self.cfg)
        for k in self._accts(owner):
            a = self._T()["acct"][k]
            low = a.get("low")
            if a.get("hist") == "done" and not a.get("genesis") and low and fl + 86400 < int(a.get("floor") or 0) and int(low[4]) > fl:
                a["hist"] = "run"

    def _note_roots(self, a, rows) -> None:
        if a.get("kind") != "wallet":
            return
        R = self._T()["roots"]
        for r in rows:
            if not (r.get("in") or {}).get("src"):
                R[r["h"]] = int(r["now"])
        if len(R) > ROOTS_KEEP:
            for h in sorted(R, key=lambda x: R[x])[:len(R) - ROOTS_KEEP]:
                R.pop(h, None)

    def _items(self, k, a, rows, floor):
        return [{"stable_id": tx_uid(k, r["lt"], r["h"]), "acct": k, "kind": a.get("kind"), "master": a.get("master"), "tx": r}
                for r in rows if int(r["now"]) >= floor]

    @staticmethod
    def _chain_desc(rows):
        for i in range(len(rows) - 1):
            if rows[i]["pl"] != rows[i + 1]["lt"] or rows[i]["ph"] != rows[i + 1]["h"]:
                raise Transient("TON tx 연속성 끊김(내림차순 · 색인 늦은 삽입?) — 전진 안 함")

    def _scan_forward(self, k, a):
        raw = ac.ton_raw(k)
        floor = _floor(self.cfg)
        if not a.get("hw"):
            rows = [compact(r) for r in self.client.transactions(raw, sort="desc", limit=self.page)]
            for r in rows:
                if r["a"] != k:
                    raise Transient("toncenter: 다른 계정 tx 가 섞임")
            if rows and not all(finalized(r) for r in rows):
                return [], False
            self._chain_desc(rows)
            self._note_roots(a, rows)
            if not rows:
                a.update(hw=[0, "", 0], anchor=[0, ""], low=None, hist="done", genesis=True, floor=floor)
                return [], False
            top, bot = rows[0], rows[-1]
            a.update(hw=[int(top["lt"]), top["h"], int(top["now"])], anchor=[int(top["lt"]), top["h"]],
                     low=[int(bot["lt"]), bot["h"], int(bot["pl"]), bot["ph"], int(bot["now"])], floor=floor, empty=0)
            if int(bot["pl"]) == 0:
                a.update(hist="done", genesis=True)
            elif int(bot["now"]) < floor:
                a["hist"] = "done"
            else:
                a["hist"] = "run"
            return self._items(k, a, rows, floor), False
        hw_lt, hw_h = int(a["hw"][0]), a["hw"][1]
        rows = [compact(r) for r in self.client.transactions(raw, sort="asc", limit=self.page, start_lt=hw_lt + 1)]
        acc = []
        plt, ph = hw_lt, hw_h
        for r in rows:
            if r["a"] != k:
                raise Transient("toncenter: 다른 계정 tx 가 섞임")
            if not finalized(r):
                break
            if int(r["pl"]) != plt or (ph and r["ph"] != ph):
                raise Transient("TON tx 연속성 끊김(오름차순 · 빠진 tx) — 전진 안 함")
            acc.append(r)
            plt, ph = int(r["lt"]), r["h"]
        self._note_roots(a, acc)
        if acc:
            a["hw"] = [int(acc[-1]["lt"]), acc[-1]["h"], int(acc[-1]["now"])]
        more = len(rows) >= self.page and len(acc) == len(rows)
        return [{"stable_id": tx_uid(k, r["lt"], r["h"]), "acct": k, "kind": a.get("kind"), "master": a.get("master"), "tx": r} for r in acc], more

    def _scan_back(self, k, a):
        low = a["low"]
        plt, ph = int(low[2]), low[3]
        floor = _floor(self.cfg)
        if plt == 0:
            a.update(hist="done", genesis=True)
            return [], False
        rows = [compact(r) for r in self.client.transactions(ac.ton_raw(k), sort="desc", limit=self.page, end_lt=plt)]
        if not rows:
            a["empty"] = int(a.get("empty") or 0) + 1
            if a["empty"] >= EMPTY_TRIES:
                a.update(hist="partial", avail=int(low[4]))
                return [], False
            raise Transient("TON 옛 쪽이 비어 있음(첫 tx 전) — 다시 확인")
        for r in rows:
            if r["a"] != k:
                raise Transient("toncenter: 다른 계정 tx 가 섞임")
            if not finalized(r):
                raise Transient("옛 tx 가 확정 전으로 옴 — 다시")
        if rows[0]["lt"] != str(plt) or rows[0]["h"] != ph:
            raise Transient("TON tx 연속성 끊김(과거 쪽 첫 행) — 전진 안 함")
        self._chain_desc(rows)
        self._note_roots(a, rows)
        bot = rows[-1]
        a.update(low=[int(bot["lt"]), bot["h"], int(bot["pl"]), bot["ph"], int(bot["now"])], empty=0,
                 floor=min(int(a.get("floor") or floor), floor) if a.get("floor") else floor)
        if int(bot["pl"]) == 0:
            a.update(hist="done", genesis=True)
        elif int(bot["now"]) < floor:
            a["hist"] = "done"
        return self._items(k, a, rows, floor), a.get("hist") == "run"

    def _update_status(self, owner) -> None:
        T = self._T()
        acs = [T["acct"][k] for k in self._accts(owner)]
        if not acs:
            return
        floor = _floor(self.cfg)
        avail = max([int(a.get("avail") or 0) for a in acs if a.get("hist") == "partial"] + [floor])
        seen = [int((a.get("hw") or [0, "", 0])[2] or 0) for a in acs if a.get("hw")]
        scanned = max(seen) if seen else None
        done = all(a.get("hw") and a.get("hist") in ("done", "partial") for a in acs)
        self.st.set_status(owner, requested_from=floor, available_from=avail, scanned_through=scanned,
                           details_complete_through=(scanned or floor or 1) if done else None)

    def _known_jetton(self, acct_key):
        a = self._T()["acct"].get(acct_key)
        return a if isinstance(a, dict) and a.get("kind") == "jetton" else None

    def _lookup(self, msg_hex, direction):
        if not msg_hex:
            return None
        for t in self.client.by_message(msg_hex, direction):
            ct = compact(t)
            if finalized(ct):
                return ct
        return None

    def fetch_and_normalize(self, ref, owners):
        ct, kind, k = ref.get("tx"), ref.get("kind"), ref.get("acct")
        if not isinstance(ct, dict) or not finalized(ct):
            return None
        owners = set(owners)
        if kind == "wallet":
            return self._norm_wallet(ct, k, owners)
        if kind == "jetton":
            a = self._known_jetton(k) or {"owner": ref.get("owner"), "master": ref.get("master")}
            return self._norm_jetton(ct, k, a.get("owner"), a.get("master"), owners)
        raise Transient("모르는 계정 종류")

    def _self_dests(self, ct, owners):
        return [o for o in ct.get("out") or [] if o.get("dst") in owners and o.get("op") not in JETTON_OUT_OPS]

    def _norm_wallet(self, ct, k, owners):
        im = ct.get("in") or None
        if im and im.get("src") in owners and not im.get("b") and im.get("op") not in (OP_EXCESS, OP_TRANSFER_NOTIFICATION) \
                and im.get("op") not in JETTON_OUT_OPS:
            root = self._lookup(im.get("h"), "out")
            if root is None:
                raise Transient("자기이체 보낸 tx 를 아직 못 찾음(색인 지연)")
            if root["a"] in owners and not (root.get("in") or {}).get("src"):
                parts, missing = self._group_native(root, owners, known={im.get("h"): ct})
                if missing:
                    raise Transient("자기이체 묶음의 받는 tx 가 아직 다 안 보임")
                return self._build(parts, owners)
            return self._build([(ct, "wallet", k, None)], owners)
        if not (im and im.get("src")) and self._self_dests(ct, owners):
            parts, missing = self._group_native(ct, owners)
            uid = tx_uid(k, ct["lt"], ct["h"])
            if missing:
                n = self._miss[uid] = self._miss.get(uid, 0) + 1
                if n < SELF_WAIT_TRIES:
                    return None
                parts = [(ct, "wallet", k, None)]
            self._miss.pop(uid, None)
            return self._build(parts, owners)
        return self._build([(ct, "wallet", k, None)], owners)

    def _group_native(self, root, owners, known=None):
        parts, missing = [(root, "wallet", root["a"], None)], []
        for o in self._self_dests(root, owners):
            r = (known or {}).get(o.get("h")) or self._lookup(o.get("h"), "in")
            if r is None or r["a"] != o["dst"]:
                missing.append(o.get("h"))
                continue
            parts.append((r, "wallet", r["a"], None))
        return parts, missing

    def _norm_jetton(self, ct, k, owner, master, owners):
        if not owner or not master:
            raise Transient("제톤 지갑 주인·master 모름")
        e = jetton_effect(ct, owner, master)
        uid = tx_uid(k, ct["lt"], ct["h"])
        if e["kind"] == "in" and e["cp"] in owners:
            root = self._lookup((ct.get("in") or {}).get("h"), "out")
            if root is None:
                raise Transient("자기 제톤 이동의 보낸 tx 를 아직 못 찾음")
            ra = self._known_jetton(root["a"])
            if ra and ra.get("owner") == e["cp"] and ra.get("master") == master:
                parts, missing = self._group_jetton(root, ra, owners, known={(ct.get("in") or {}).get("h"): ct})
                if missing:
                    raise Transient("자기 제톤 이동 묶음의 받는 tx 가 아직 다 안 보임")
                return self._build(parts, owners)
            return self._build([(ct, "jetton", owner, master)], owners)
        if e["kind"] == "out" and e["cp"] in owners:
            parts, missing = self._group_jetton(ct, {"owner": owner, "master": master}, owners)
            if missing:
                n = self._miss[uid] = self._miss.get(uid, 0) + 1
                if n < SELF_WAIT_TRIES:
                    return None
                parts = [(ct, "jetton", owner, master)]
            self._miss.pop(uid, None)
            return self._build(parts, owners)
        return self._build([(ct, "jetton", owner, master)], owners, effects={0: e})

    def _group_jetton(self, root, ra, owners, known=None):
        parts, missing = [(root, "jetton", ra["owner"], ra["master"])], []
        for o in root.get("out") or []:
            if o.get("op") != OP_INTERNAL_TRANSFER:
                continue
            r = (known or {}).get(o.get("h")) or self._lookup(o.get("h"), "in")
            rb = self._known_jetton(r["a"]) if r else None
            if r is None or rb is None or rb.get("master") != ra["master"] or rb.get("owner") not in owners or r["a"] != o.get("dst"):
                missing.append(o.get("h"))
                continue
            parts.append((r, "jetton", rb["owner"], rb["master"]))
        return parts, missing

    def _rebase(self, parts, effects=None):
        if self.st is None or len(parts) < 2:
            return parts, effects
        em = [i for i in range(1, len(parts)) if self.st.emitted(tx_uid(parts[i][0]["a"], parts[i][0]["lt"], parts[i][0]["h"]))]
        if not em:
            return parts, effects
        rest = [i for i in range(1, len(parts)) if i not in em]
        order = ([0] if self.st.emitted(tx_uid(parts[0][0]["a"], parts[0][0]["lt"], parts[0][0]["h"])) else [em[0], 0]) + rest
        eff = {n: effects[i] for n, i in enumerate(order) if i in effects} if effects else effects
        return [parts[i] for i in order], eff

    def _build(self, parts, owners, effects=None):
        parts, effects = self._rebase(parts, effects)
        root = parts[0][0]
        meta = self._T()["meta"] if self.st is not None else {}
        own_jw = frozenset(w for w, v in (self._T()["jw"] if self.st is not None else {}).items() if isinstance(v, dict) and v.get("ok"))
        net, fee, moves, reasons, evs, hints = {}, {}, [], set(), [], set()
        failed = False
        involved = set()
        wait = self._T()["jw_wait"] if self.st is not None else {}
        for i, (ct, kind, owner, master) in enumerate(parts):
            involved.add(owner)
            if kind == "wallet":
                im9 = ct.get("in") or {}
                if wait and (any(o9.get("op") in JETTON_OUT_OPS and o9.get("dst") in wait for o9 in ct.get("out") or [])
                             or (im9.get("src") in wait and (im9.get("b") or im9.get("op") == OP_TRANSFER_NOTIFICATION))):
                    return None
                e = wallet_effect(ct, own_jw, self._T()["roots"] if self.st is not None else None)
                kk = (owner, "native", None)
                net[kk] = net.get(kk, 0) + int(e["net"])
                if e["fee"]:
                    fee[owner] = fee.get(owner, 0) + int(e["fee"])
                failed = failed or (e["failed"] and len(parts) == 1)
                moves += e["moves"]
            else:
                e = (effects or {}).get(i) or jetton_effect(ct, owner, master)
                if e["delta"]:
                    kk = (owner, "token", master)
                    net[kk] = net.get(kk, 0) + int(e["delta"])
                    if e["delta"] < 0:
                        moves.append((owner, e.get("cp") or "", -int(e["delta"]), master))
                    elif e.get("cp"):
                        moves.append((e["cp"], owner, int(e["delta"]), master))
            reasons.update(e["reasons"])
            evs.append(e["ev"])
            hints.add(e["hint"])
        roots = self._T()["roots"] if self.st is not None else {}
        if len(parts) == 1 and root.get("tr") and root.get("tr") != root["h"] and root["tr"] in roots and "transfer" in hints:
            e0 = evs[0]
            inflow = any(v > 0 for v in net.values()) and not any(v < 0 for (o9, kd9, m9), v in net.items() if kd9 == "token")
            if inflow and ":refund" not in e0:
                hints = {"program_in"}
                evs[0] = e0 + ":trace_mine"
        deltas = []
        for (o, kd, m), v in sorted(net.items(), key=lambda x: (x[0][0], x[0][1], x[0][2] or "")):
            if not v:
                continue
            if kd == "native":
                asset = {"kind": "native"}
            else:
                mm = meta.get(m) or {}
                if mm.get("decimals") is None:
                    if mm.get("invalid"):
                        reasons.add("jetton_meta_invalid_skipped")
                        continue
                    return None
                asset = {"kind": "token", "id": ac.ton_raw(m), "symbol": mm.get("symbol"), "decimals": mm.get("decimals")}
            deltas.append({"owner": o, "asset": asset, "delta_base": str(v)})
        mv = []
        for i, x in enumerate(moves):
            frm, to, amt = x[0], x[1], x[2]
            if not amt or not to and not frm:
                continue
            asset = {"kind": "native"} if len(x) == 3 else {"kind": "token", "id": ac.ton_raw(x[3])}
            mv.append({"id": f"m{i}", "asset": asset, "from": frm or "", "to": to or "", "amount_base": str(int(amt))})
        rec9 = {"v": 1, "kind": chain_event.KIND, "chain": CHAIN, "network": "mainnet",
                "tx_uid": tx_uid(root["a"], root["lt"], root["h"]), "txhash": root["h"], "ts": int(root["now"]),
                "order": {"height": None, "checkpoint": None, "lt": int(root["lt"]), "index": 0},
                "finality": {"state": "finalized", "blockhash": None, "evidence": f"masterchain:{root.get('mc')}"},
                "execution": {"state": "failed" if failed else "success", "trace_complete": True},
                "owners": sorted(involved), "ownership_version": self._owners_vh(owners),
                "deltas": deltas,
                "fees": [{"payer": o, "asset": {"kind": "native"}, "amount_base": str(f), "component": "network_fee", "included_in_deltas": True}
                         for o, f in sorted(fee.items()) if f],
                "movements": mv,
                "classification": {"hint": "program_in" if "program_in" in hints else "transfer", "trusted": False,
                                   "evidence": ";".join(evs)[:200]},
                "completeness": {"history": True, "details": True, "balances": "state_balance_missing" not in reasons,
                                 "reasons": sorted(reasons)},
                "source": {"provider": PROVIDER, "parser_version": PARSER_VERSION, "observed_at": int(time.time()),
                           "payload_digest": chain_event.payload_digest([p[0] for p in parts])}}
        if len(self._cover) > 1000:
            self._cover.clear()
        self._cover[rec9["tx_uid"]] = [tx_uid(p[0]["a"], p[0]["lt"], p[0]["h"]) for p in parts]
        return rec9

    def covered_sids(self, rec) -> list:
        return list(self._cover.pop(str((rec or {}).get("tx_uid")), ()) or ())

    def fetch_balances(self, owners, boundary, tokens=None):
        owners = set(owners)
        sd = statefile.read_json(paths.state(reg.spec(CHAIN).cursor_file), None)
        sd = sd if isinstance(sd, dict) else {}
        T = sd.get("ton") if isinstance(sd.get("ton"), dict) else {}
        A, JW, META = T.get("acct") or {}, T.get("jw") or {}, T.get("meta") or {}
        pend_owners = {(p.get("ref") or {}).get("owner") for p in (sd.get("pending") or {}).values() if isinstance(p, dict)}
        why = []
        per, unobs, metas, lts = {}, {}, {}, {}
        seen_ts = [0]
        states = {akey(s.get("address")): s for s in self.client.account_states([ac.ton_raw(o) for o in sorted(owners)])
                  if isinstance(s, dict) and s.get("address")}
        for o in sorted(owners):
            s = states.get(o)
            hw0 = (A.get(o) or {}).get("hw")
            if s is None:
                if hw0 and int(hw0[0]) == 0:
                    s = {"status": "nonexist", "balance": "0", "last_transaction_lt": "0"}
                else:
                    raise Transient("계정 상태 응답에 내 지갑이 빠짐")
            b9, l9 = s.get("balance"), s.get("last_transaction_lt")
            if b9 is None and l9 in (None, "", "0", 0) and s.get("status") == "nonexist" and hw0 and int(hw0[0]) == 0:
                b9, l9 = "0", "0"
            try:
                bal, lt = _int(b9, "account.balance"), _int(l9, "account.last_transaction_lt")
                if bal < 0 or lt < 0:
                    raise ValueError("계정 잔고·LT 음수")
            except (TypeError, ValueError):
                raise Transient("계정 잔고·last_transaction_lt 칸 없음/깨짐 — 0 으로 안 봄") from None
            wb = {("native", None): bal}
            lts[o] = lt
            hw = (A.get(o) or {}).get("hw")
            if not hw or int(hw[0]) != lt:
                why.append("wallet_lt_ahead")
            else:
                seen_ts.append(int(hw[2] if len(hw) > 2 and hw[2] else 0))
            if o in pend_owners:
                why.append("pending_details")
            rows, full = self.client.jetton_wallets(owner_raw=ac.ton_raw(o))
            if not full:
                why.append("jetton_list_partial")
            seen, seen_w = set(), set()
            for r in rows:
                try:
                    w, m, ow = akey(r.get("address")), akey(r.get("jetton")), akey(r.get("owner"))
                except ValueError:
                    why.append("jetton_row_bad")
                    continue
                if ow != o or not w or not m:
                    continue
                try:
                    jb = _int(r.get("balance"), "jetton.balance")
                    if jb < 0:
                        raise ValueError("제톤 잔고 음수")
                except (TypeError, ValueError):
                    jb = None
                v = JW.get(w)
                if not isinstance(v, dict) or v.get("master") != m:
                    if jb is None or jb > 0:
                        unobs.setdefault(o, []).append(m)
                        why.append("jetton_unverified")
                    continue
                if not v.get("ok"):
                    continue
                seen.add(m)
                seen_w.add(w)
                if jb is None:
                    unobs.setdefault(o, []).append(m)
                    why.append("jetton_balance_missing")
                    continue
                hw = (A.get(w) or {}).get("hw")
                if not hw or str(hw[0]) != str(r.get("last_transaction_lt") or ""):
                    why.append("jetton_lt_ahead")
                else:
                    seen_ts.append(int(hw[2] if len(hw) > 2 and hw[2] else 0))
                mm = META.get(m) or {}
                if mm.get("decimals") is None:
                    if jb > 0:
                        unobs.setdefault(o, []).append(m)
                        if not mm.get("invalid"):
                            why.append("jetton_decimals_unknown")
                    continue
                wb[("token", m)] = wb.get(("token", m), 0) + jb
                metas[m] = (mm.get("symbol"), mm.get("decimals"))
            for tk in (tokens or {}).get(o) or []:
                if tk in seen:
                    continue
                known = [w for w, v in JW.items() if isinstance(v, dict) and v.get("owner") == o and v.get("master") == tk and v.get("ok")]
                if known:
                    unobs.setdefault(o, []).append(tk)
                    why.append("jetton_wallet_missing")
                else:
                    wb[("token", tk)] = 0
            for w, v in JW.items():
                if w not in seen_w and isinstance(v, dict) and v.get("owner") == o and v.get("ok") and v.get("master"):
                    unobs.setdefault(o, []).append(v["master"])
                    why.append("jetton_wallet_missing")
            for m in unobs.get(o) or ():
                wb.pop(("token", m), None)
            per[o] = wb
        return {"per_wallet": per, "_meta": metas,
                "_boundary": {"kind": "account_lt", "value": "lt:" + ",".join(f"{o}={lts[o]}" for o in sorted(lts)), "hash": None,
                              "ts": max(seen_ts)},
                "_complete": not why, "_why": sorted(set(why)), "_unobserved": {o: sorted(set(v)) for o, v in unobs.items()},
                "_source": PROVIDER, "_ownership_version": self._owners_vh(owners), "_jw_fp": jw_fingerprint(owners, T)}


def jw_fingerprint(owners, T=None) -> dict:
    if T is None:
        sd = statefile.read_json(paths.state(reg.spec(CHAIN).cursor_file), None)
        T = sd.get("ton") if isinstance(sd, dict) and isinstance(sd.get("ton"), dict) else {}
    JW = T.get("jw") if isinstance(T.get("jw"), dict) else {}
    out = {}
    for o in sorted(set(owners)):
        s9 = sorted([str(w), str(v["master"])] for w, v in JW.items() if isinstance(v, dict) and v.get("owner") == o and v.get("ok") and v.get("master"))
        out[o] = hashlib.sha256(json.dumps(s9).encode()).hexdigest()[:16]
    return out


def make_adapter(cfg):
    return TonAdapter(cfg)


def main(poll_default: int = 60):
    from inbox import SegmentWriter
    log = logs.setup_logging("tj-" + CHAIN)
    paths.ensure_dirs()
    cfg = config.load_config()
    owners = reg.owners(cfg, CHAIN)
    if not owners:
        raise SystemExit("추적할 TON 지갑이 없음 — config chain_wallets 확인")
    st = chain_state.ChainState(CHAIN)
    st.drop_owner(owners)
    ad = make_adapter(cfg)
    ad.bind_state(st)
    T = ad._T()
    for k in [k for k, a in T["acct"].items() if a.get("owner") not in owners]:
        T["acct"].pop(k, None)
    for k in [k for k, x in T["jw_wait"].items() if not isinstance(x, dict) or x.get("owner") not in owners]:
        T["jw_wait"].pop(k, None)
    st.save()
    col = chain_watch.Collector(ad, SegmentWriter(os.path.join(paths.INBOX_DIR, reg.spec(CHAIN).stream)), st, owners, log=log)
    c9 = ((cfg.get(reg.CFG_CHAIN_KEY) or {}).get(CHAIN) or {}) if isinstance(cfg.get(reg.CFG_CHAIN_KEY), dict) else {}
    poll = int(c9.get("poll_sec", poll_default)) if isinstance(c9, dict) else poll_default
    log.info("가동: TON %d지갑, %d초 주기 · 키 %s", len(owners), poll, "있음" if ad.client.key else "없음(1rps)")
    try:
        while True:
            t0 = time.time()
            try:
                r = col.cycle()
                log.info("[ton] 주기: %s", r)
            except Exception as e:   # noqa: BLE001 [boundary]
                log.warning("[ton] 주기 실패(다음 주기): %s", logs.safe_err(e)[:200])
            time.sleep(max(5.0, poll - (time.time() - t0)))
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
