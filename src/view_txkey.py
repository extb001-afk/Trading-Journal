from __future__ import annotations
import re
import common
import outflow_match
import logging
import calcguard

log = logging.getLogger('tj-web')

_HEX64_TX = re.compile(r"[0-9a-fA-F]{64}")


def _txk(t) -> str:
    t = str(t or "")
    return t.lower() if (t.startswith("0x") or _HEX64_TX.fullmatch(t)) else t

_B64URL_32_TX = re.compile(r"[A-Za-z0-9_-]{43}")


def _ton_hash_uids(conn) -> dict:
    out, dup = {}, set()
    try:
        for u9, h9 in conn.execute("SELECT txhash, json_extract(snapshot, '$.txhash') FROM raw_txs"
                                   " WHERE chain = 'ton' AND json_valid(snapshot)").fetchall():
            h9 = str(h9 or "").lower()
            if not _HEX64_TX.fullmatch(h9):
                continue
            if h9 in out and out[h9] != u9:
                dup.add(h9)
            out[h9] = u9
    except Exception as e9:
        calcguard.swallowed("view_txkey:_ton_hash_uids", e9)
        log.warning("TON 출금 도착 색인 실패(이번 빌드 종전 비교키): %s", common.safe_err(e9)[:160])
        return {}
    for h9 in dup:
        out.pop(h9, None)
    return out


def _wd_txk(t, net=None, ton=None) -> str:
    k = _txk(t)
    if not ton or not k:
        return k
    n = str(net or "").strip().upper()
    if n and n.split("-")[-1] not in ("TON", "TONCOIN"):
        return k
    s = str(t).strip()
    h = outflow_match.norm_txid(s + "=" if _B64URL_32_TX.fullmatch(s) else s)
    return ton.get(h[2:], k) if (h.startswith("0x") and len(h) == 66) else k
