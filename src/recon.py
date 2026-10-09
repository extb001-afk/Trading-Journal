"""Balance reconciliation against chain and exchange snapshots."""
from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import common

_UA = {"Accept": "application/json", "User-Agent": "tj-bot/0.1 (personal trade journal)"}


GJ_TRIES = 5
GJ_WAIT_MAX = 60.0
BS_PACE = 1.0


def _gj_wait(i: int, e) -> float:
    ra = None
    try:
        ra = float((getattr(e, "headers", None) or {}).get("Retry-After") or "")
    except (TypeError, ValueError):
        ra = None
    base9 = ra if ra is not None and ra >= 0 else 5.0 * (2 ** i)
    return min(GJ_WAIT_MAX, base9) + random.uniform(0, 1.5)


def _gj_retryable(e) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or 500 <= e.code < 600
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout))


def _gj(url: str, timeout: float = 30.0, tries: int = None, sleep=time.sleep):
    req = urllib.request.Request(url, headers=dict(_UA, **{"User-Agent": common.ua_for(url, _UA["User-Agent"])}))
    n9 = GJ_TRIES if tries is None else max(1, int(tries))
    for i in range(n9):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i + 1 >= n9 or not _gj_retryable(e):
                raise
            sleep(_gj_wait(i, e))


def _rpc(url: str, method: str, params, timeout: float = 25.0, gap: bool = True):
    if "_" in str(method):
        import bf_engine as _bfe8
        d = _bfe8.rpc_post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout, ua="tj-bot/0.1")
        if not isinstance(d, dict):
            raise RuntimeError(f"rpc {method}: 응답 형식 오류 ({type(d).__name__})")
        if "error" in d:
            ce9 = _bfe8.classify_rpc_error(d["error"])
            raise _bfe8.NetError(f"rpc {method}: {common.redact_secret_text(str(d['error']))}", ce9.kind, code=ce9.code)
        if d.get("result") is None:
            raise RuntimeError(f"rpc {method}: result 누락")
        return d["result"]
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": common.ua_for(url, "tj-bot/0.1")})
    h9 = (urllib.parse.urlsplit(url).hostname or "").lower()
    if h9 == "helius-rpc.com" or h9.endswith(".helius-rpc.com"):
        import bf_engine
        try:
            bf_engine.helius_configure(common.load_config())
        except (Exception, SystemExit):
            pass
        if not bf_engine.HELIUS.take("tj-core", 10 if method in ("getProgramAccounts", "getAsset") else 1, kind="must"):
            raise RuntimeError(f"rpc {method}: 헬리우스 하루 예산 보류({bf_engine.HELIUS.last_why()}) — 다음 대사 때 다시")
    import bf_engine as _bfe9
    with (_bfe9.sol_open(req, timeout, method, sol=("_" not in str(method))) if gap else urllib.request.urlopen(req, timeout=timeout)) as r:
        d = json.loads(r.read().decode())
    if "error" in d:
        raise RuntimeError(f"rpc {method}: {common.redact_secret_text(str(d['error']))}")
    if not isinstance(d, dict) or d.get("result") is None:
        raise RuntimeError(f"rpc {method}: result 누락")
    return d["result"]


def fetch_evm_balances(base_url: str, wallets: list) -> dict:
    per = {}
    meta = {}
    for w in wallets:
        wb = per.setdefault(w, {})
        d = _gj(f"{base_url}/api/v2/addresses/{w}")
        if not isinstance(d, dict) or d.get("coin_balance") is None:
            raise RuntimeError(f"addresses/{w[:10]} coin_balance 누락")
        wb[("native", None)] = int(d["coin_balance"])
        tb = _gj(f"{base_url}/api/v2/addresses/{w}/token-balances")
        if not isinstance(tb, list):
            raise RuntimeError("token-balances 형식 오류")
        for it in tb:
            tok = (it or {}).get("token") or {}
            if (tok.get("type") or "ERC-20") != "ERC-20":
                continue
            ca = (tok.get("address") or tok.get("address_hash") or "").lower()
            if not ca:
                raise RuntimeError("token-balances CA 누락 — 대사 보류")
            try:
                v = int(it.get("value"))
            except (TypeError, ValueError) as e:
                raise RuntimeError(f"token-balances value 파싱 실패 {ca[:10]}: {it.get('value')!r}") from e
            if v < 0:
                raise RuntimeError(f"token-balances 음수 잔고 {ca[:10]}")
            if v:
                key = ("token", ca)
                wb[key] = wb.get(key, 0) + v
                meta[ca] = (tok.get("symbol"),
                            18 if tok.get("decimals") is None else int(tok.get("decimals")))
        time.sleep(0.2)
    return {"per_wallet": per, "_meta": meta}


def fetch_sol_balances(rpc_url: str, owners: list) -> dict:
    per = {}
    meta = {}
    for o in owners:
        wb = per.setdefault(o, {})
        lam = _rpc(rpc_url, "getBalance", [o])
        if not isinstance(lam, dict) or lam.get("value") is None:
            raise RuntimeError("getBalance value 누락")
        wb[("native", None)] = int(lam["value"])
        for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                     "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
            res = _rpc(rpc_url, "getTokenAccountsByOwner",
                       [o, {"programId": prog}, {"encoding": "jsonParsed"}])
            if not isinstance(res, dict) or not isinstance(res.get("value"), list):
                raise RuntimeError("getTokenAccountsByOwner value 형식 오류")
            for it in res["value"]:
                info = ((((it or {}).get("account") or {}).get("data") or {})
                        .get("parsed") or {}).get("info") or {}
                mint = info.get("mint")
                ta = info.get("tokenAmount") or {}
                if not mint:
                    raise RuntimeError("token account mint 누락")
                try:
                    v = int(ta.get("amount"))
                except (TypeError, ValueError) as e:
                    raise RuntimeError(f"token account amount 파싱 실패 {mint[:10]}") from e
                if v < 0:
                    raise RuntimeError(f"token account 음수 잔고 {mint[:10]}")
                if v:
                    key = ("token", mint)
                    wb[key] = wb.get(key, 0) + v
                    if ta.get("decimals") is None:
                        raise RuntimeError(f"token account decimals 누락 {mint[:10]}")
                    meta[mint] = (None, int(ta["decimals"]))
            time.sleep(0.12)
    return {"per_wallet": per, "_meta": meta}


def fetch_bsc_balances(rpc_urls: list, wallets: list, token_cas: dict) -> dict:
    url = rpc_urls[0]
    per = {}
    meta = {}
    zero = {}
    for w in wallets:
        wb = per.setdefault(w, {})
        wz = zero.setdefault(w, [])
        wb[("native", None)] = int(_rpc(url, "eth_getBalance", [w, "latest"]), 16)
        for ca in token_cas:
            data = "0x70a08231" + w.lower().replace("0x", "").rjust(64, "0")
            try:
                r = _rpc(url, "eth_call", [{"to": ca, "data": data}, "latest"])
            except RuntimeError as e:
                if "execution reverted" in str(e) or "'code': 3" in str(e):
                    wz.append(ca)
                    continue
                raise
            bal = int(r, 16) if r and r != "0x" else 0
            if bal:
                wb[("token", ca)] = bal
                meta[ca] = token_cas[ca]
            else:
                wz.append(ca)
            time.sleep(0.12)
        time.sleep(0.2)
    return {"per_wallet": per, "_meta": meta, "_zero": zero}


MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
MULTICALL3_BY_CHAIN = {"zksync": "0xf9cda624fbc7e059355ce98a31693d299facd963"}
MC_CHUNK = 150
RPC_BLOCK_LAG = 2
_SEL_AGG3 = "82ad56cb"
_SEL_BAL = "70a08231"
_SEL_DEC = "313ce567"


class RpcExecFail(RuntimeError):
    pass


def _is_exec_err(e) -> bool:
    import bf_engine
    return bf_engine.rpc_fail_class(e) == "exec"


def _rpc_any(urls: list, method: str, params, check=None, tries: int = None, sleep=time.sleep, timeout: float = 25.0):
    if not urls:
        raise RuntimeError(f"rpc {method}: 엔드포인트 없음")
    n9 = GJ_TRIES if tries is None else max(1, int(tries))
    last = None
    for i in range(n9):
        exec_n = 0
        for u in urls:
            try:
                r = _rpc(u, method, params, timeout=timeout)
                return check(r) if check else r
            except Exception as e:
                last = e
                if _is_exec_err(e):
                    exec_n += 1
        if exec_n:
            raise RpcExecFail(f"rpc {method}: 실행 오류 — {common.redact_urls(str(last))[:160]}")
        if i + 1 < n9:
            sleep(_gj_wait(i, last))
    raise RuntimeError(f"rpc {method}: 전 엔드포인트 실패 — {common.redact_urls(str(last))[:160]}")


def _hex_int(x) -> int:
    if not isinstance(x, str) or not x.startswith("0x") or len(x) < 3:
        raise ValueError(f"16진 정수 아님: {str(x)[:40]!r}")
    return int(x, 16)


def _enc_agg3(calls: list) -> str:
    n = len(calls)
    head, body, off = [], [], n * 32
    for tgt, cd in calls:
        b = bytes.fromhex(cd)
        pad = b + b"\0" * ((32 - len(b) % 32) % 32)
        el = (tgt.lower().replace("0x", "").rjust(64, "0") + "1".rjust(64, "0") + "60".rjust(64, "0")
              + format(len(b), "x").rjust(64, "0") + pad.hex())
        head.append(format(off, "x").rjust(64, "0"))
        body.append(el)
        off += len(el) // 2
    return "0x" + _SEL_AGG3 + "20".rjust(64, "0") + format(n, "x").rjust(64, "0") + "".join(head) + "".join(body)


def _dec_agg3(res, n: int) -> list:
    if not isinstance(res, str) or not res.startswith("0x") or (len(res) - 2) % 64:
        raise ValueError("aggregate3 응답 형식 오류")
    raw = bytes.fromhex(res[2:])

    def word(o):
        if o < 0 or o + 32 > len(raw):
            raise ValueError("aggregate3 응답 범위 초과")
        return int.from_bytes(raw[o:o + 32], "big")
    if word(0) != 32:
        raise ValueError("aggregate3 배열 오프셋 비정규")
    if word(32) != n:
        raise ValueError(f"aggregate3 결과 수 {word(32)} ≠ 요청 {n}")
    base9 = 64
    expect = n * 32
    out = []
    for i in range(n):
        rel = word(base9 + 32 * i)
        if rel != expect:
            raise ValueError(f"aggregate3 튜플 오프셋 비정규 #{i}")
        t0 = base9 + rel
        ok = word(t0)
        if ok not in (0, 1):
            raise ValueError("aggregate3 success 값 오류")
        if word(t0 + 32) != 64:
            raise ValueError("aggregate3 bytes 오프셋 비정규")
        ln = word(t0 + 64)
        padded = (ln + 31) // 32 * 32
        end = t0 + 96 + padded
        if end > len(raw):
            raise ValueError("aggregate3 returnData 범위 초과")
        if any(raw[t0 + 96 + ln:end]):
            raise ValueError("aggregate3 패딩 비정규")
        out.append((bool(ok), raw[t0 + 96:t0 + 96 + ln]))
        expect = end - base9
    if base9 + expect != len(raw):
        raise ValueError("aggregate3 응답 끝 불일치")
    return out


def _mc_call(urls: list, blk: str, items: list, mc, sleep=time.sleep) -> dict:
    out = {}

    def run(chunk):
        try:
            res = _rpc_any(urls, "eth_call", [{"to": mc, "data": _enc_agg3([(t, cd) for _k, t, cd in chunk])}, blk],
                           check=lambda r: _dec_agg3(r, len(chunk)), sleep=sleep)
        except RpcExecFail:
            if len(chunk) == 1:
                out[chunk[0][0]] = None
                return
            h = len(chunk) // 2
            run(chunk[:h])
            run(chunk[h:])
            return
        for (k, _t, _cd), (ok, rd) in zip(chunk, res):
            out[k] = rd if ok else None
    if mc:
        for i in range(0, len(items), MC_CHUNK):
            run(items[i:i + MC_CHUNK])
        return out
    for k, tgt, cd in items:
        try:
            rd = _rpc_any(urls, "eth_call", [{"to": tgt, "data": "0x" + cd}, blk], sleep=sleep)
        except RpcExecFail:
            out[k] = None
            continue
        if not isinstance(rd, str) or not rd.startswith("0x") or (len(rd) - 2) % 2:
            raise RuntimeError(f"eth_call 응답 형식 오류 {tgt[:10]}")
        out[k] = bytes.fromhex(rd[2:])
        time.sleep(0.05)
    return out


def _mc_balances(urls: list, blk: str, pairs: list, mc, sleep=time.sleep) -> dict:
    got = _mc_call(urls, blk, [((w, ca), ca, _SEL_BAL + str(w).lower().replace("0x", "").rjust(64, "0")) for w, ca in pairs],
                   mc, sleep=sleep)
    return {k: (int.from_bytes(v, "big") if v is not None and len(v) == 32 else None) for k, v in got.items()}


def _bs_token_list(base_url: str, w: str) -> dict:
    tb = _gj(f"{base_url}/api/v2/addresses/{w}/token-balances")
    if not isinstance(tb, list):
        raise RuntimeError("token-balances 형식 오류")
    out = {}
    for it in tb:
        if isinstance(it, dict) and "token" in it and it["token"] is None:
            continue
        tok = (it or {}).get("token") or {}
        if (tok.get("type") or "ERC-20") != "ERC-20":
            continue
        ca = (tok.get("address") or tok.get("address_hash") or "").lower()
        if not ca:
            raise RuntimeError("token-balances CA 누락 — 발견 불완전, 대사 보류")
        try:
            v = int(it.get("value"))
        except (TypeError, ValueError):
            v = None
        out[ca] = (tok.get("symbol"), v)
    return out


def fetch_evm_rpc_balances(rpc_urls: list, wallets: list, token_cas: dict, *, discover_url: str = None,
                           must: dict = None, exclude=(), want_native: bool = True, want_tokens: bool = True,
                           multicall: str = MULTICALL3, wallet_cas: dict = None, block: int = None, strict=None,
                           sweep: dict = None, sleep=time.sleep) -> dict:
    urls = [u for u in (rpc_urls or []) if u]
    if not urls:
        raise RuntimeError("RPC 엔드포인트 없음 — 대사 보류")
    wallets = list(wallets)
    excl = {str(x).lower() for x in exclude or ()}
    must = {str(w).lower(): {str(c).lower() for c in (s or ())} for w, s in (must or {}).items()}
    cas = {str(ca).lower(): m for ca, m in (token_cas or {}).items() if str(ca).lower() not in excl}
    sw = {str(ca).lower(): s for ca, s in (sweep or {}).items() if str(ca).lower() not in excl}
    spec = {}

    def is_strict(w, ca):
        if ca in must.get(str(w).lower(), ()):
            return True
        try:
            return bool(strict(ca)) if strict else False
        except Exception:
            return True
    bs, dfail = {}, {}
    if want_tokens and discover_url:
        for i, w in enumerate(wallets):
            if i:
                sleep(BS_PACE)
            try:
                bs[w] = _bs_token_list(discover_url, w)
            except Exception as e:
                dfail[w] = e
        if dfail and len(dfail) == len(wallets):
            raise next(iter(dfail.values()))
    head = _rpc_any(urls, "eth_blockNumber", [], check=_hex_int, sleep=sleep)
    if block is None:
        bn = max(0, head - RPC_BLOCK_LAG)
    else:
        bn = int(block)
        if bn <= 0 or bn > head:
            raise RuntimeError(f"조회 블록 {bn} 이 헤드 {head} 밖 — 대사 보류")
    blk = hex(bn)

    def _blk_check(r):
        if not isinstance(r, dict) or _hex_int(r.get("number")) != bn:
            raise ValueError("eth_getBlockByNumber 응답 블록 불일치")
        return _hex_int(r.get("timestamp"))
    bts = _rpc_any(urls, "eth_getBlockByNumber", [blk, False], check=_blk_check, sleep=sleep)
    if want_tokens and multicall:
        code = _rpc_any(urls, "eth_getCode", [multicall, blk], sleep=sleep)
        if not isinstance(code, str) or not code.startswith("0x"):
            raise RuntimeError("eth_getCode 응답 형식 오류")
        if len(code) <= 2:
            multicall = None
    per = {w: {} for w in wallets}
    meta = {}
    if want_native:
        for w in wallets:
            if w in dfail:
                continue
            per[w][("native", None)] = _rpc_any(urls, "eth_getBalance", [str(w).lower(), blk], check=_hex_int, sleep=sleep)
    diff, unobs, hold = [], {}, {}
    for w, e in dfail.items():
        hold[w] = ["발견실패:" + type(e).__name__]
    queried = None
    if want_tokens:
        queried = {}
        pairs = []
        for w in wallets:
            if w in dfail:
                continue
            base_w = cas if wallet_cas is None else {str(x).lower() for x in (wallet_cas.get(str(w).lower()) or ())}
            cw = {ca for ca in base_w if ca not in excl} | {ca for ca in (bs.get(w) or {}) if ca not in excl}
            spec[w] = set(sw) - cw - must.get(str(w).lower(), set())
            cw |= set(sw)
            pairs += [(w, ca) for ca in sorted(cw)]
            queried[w] = sorted(cw)
        items = [(("bal", w, ca), ca, _SEL_BAL + str(w).lower().replace("0x", "").rjust(64, "0")) for w, ca in pairs]
        items += [(("dec", ca), ca, _SEL_DEC) for ca in sorted({ca for _w, ca in pairs if ca not in cas or cas[ca][1] is None})]
        items.sort(key=lambda it: 0 if (it[0][0] == "bal" and is_strict(it[0][1], it[0][2])) else 1)
        got = _mc_call(urls, blk, items, multicall, sleep=sleep)
        for (w, ca) in pairs:
            rd = got.get(("bal", w, ca))
            v = int.from_bytes(rd, "big") if rd is not None and len(rd) == 32 else None
            b9 = (bs.get(w) or {}).get(ca)
            dec = None
            if v and ca not in cas:
                dd = got.get(("dec", ca))
                d9 = int.from_bytes(dd, "big") if dd is not None and len(dd) == 32 else None
                if d9 is None or d9 > 255:
                    v = None
                else:
                    dec = d9
            elif v and cas[ca][1] is None:
                dd = got.get(("dec", ca))
                d9 = int.from_bytes(dd, "big") if dd is not None and len(dd) == 32 else None
                dec = d9 if d9 is not None and d9 <= 77 else None
            if v is None:
                if is_strict(w, ca) and ca not in spec.get(w, ()):
                    hold.setdefault(w, []).append(ca)
                else:
                    unobs.setdefault(w, []).append(ca)
                continue
            if w in bs and (b9[1] if b9 else 0) != v:
                diff.append((w, ca, None if not b9 else b9[1], v))
            if v:
                per[w][("token", ca)] = v
                meta[ca] = (tuple(cas[ca]) if cas[ca][1] is not None else (cas[ca][0], dec)) if ca in cas else ((b9[0] if b9 else sw.get(ca)), dec)
    for w in hold:
        per.pop(w, None)
    return {"per_wallet": per, "_meta": meta, "_source": "rpc", "_block": bn, "_block_ts": bts, "_bs_diff": diff, "_unobs": unobs,
            "_hold": hold, "_queried": queried, "_multicall": bool(multicall)}
