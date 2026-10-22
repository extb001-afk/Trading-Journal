from __future__ import annotations

import re
import time

import bf_engine
import logs

SRC = "alchemy_transfers"
METHOD = "alchemy_getAssetTransfers"
NETS = {"base": "base-mainnet"}
PAGE_MAX = 1000
MAX_PAGES = 30
OFF_SEC = 3600
_HASH_RE = re.compile(r"^0x[0-9a-f]{64}$")
_ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]{1,64}$")
_OFF = {"until": 0.0, "why": ""}


class AlchSkip(Exception):
    pass


class AlchFail(RuntimeError):

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"alchemy_transfers 보완 실패(일시 · {kind})")
        self.kind = kind
        self.detail = detail


def off_now() -> bool:
    return time.time() < float(_OFF["until"] or 0)


def _set_off(why: str) -> None:
    _OFF["until"] = time.time() + OFF_SEC
    _OFF["why"] = why


def url_for(chain: str, env: dict = None):
    net = NETS.get(chain)
    if not net or off_now():
        return None
    try:
        import nodekeys
        u = nodekeys.alchemy_url(net, env)
    except Exception:   # noqa: BLE001 [fallback]
        return None
    if not u:
        return None
    try:
        bf_engine._rpc_cfg_ensure()
        if not bf_engine._rpc_day_of(f"{net}.g.alchemy.com"):
            return None
    except Exception:   # noqa: BLE001 [fallback]
        return None
    return u


def _local(e) -> bool:
    return isinstance(e, bf_engine.NetError) and (getattr(e, "kind", None) in ("budget", "circuit") or bool(getattr(e, "local", False)))


def _cap_off(e) -> bool:
    code = getattr(e, "code", None)
    if code in (401, 403):
        return True
    m = str(e).lower()
    return "-32601" in m or "method not found" in m or "not enabled" in m or "unsupported network" in m or "is not supported" in m


def norm(t) -> dict:
    if not isinstance(t, dict):
        raise AlchFail("payload", "항목이 객체가 아님")
    uid = t.get("uniqueId")
    h = str(t.get("hash") or "").lower()
    if not isinstance(uid, str) or not uid or not _HASH_RE.match(h):
        raise AlchFail("payload", "uniqueId·hash 없음")
    if t.get("category") not in (None, "internal"):
        raise AlchFail("payload", f"분류 {t.get('category')!r}")
    try:
        blk = int(str(t.get("blockNum")), 16)
    except (TypeError, ValueError):
        raise AlchFail("payload", "blockNum 형식")
    f9 = str(t.get("from") or "").lower()
    t9 = str(t.get("to") or "").lower()
    if not _ADDR_RE.match(f9) or (t9 and not _ADDR_RE.match(t9)):
        raise AlchFail("payload", "주소 형식")
    rc = t.get("rawContract") if isinstance(t.get("rawContract"), dict) else {}
    if rc.get("address") not in (None, ""):
        raise AlchFail("payload", "네이티브 아님(rawContract.address)")
    v = None
    rv, dec = rc.get("value"), rc.get("decimal")
    try:
        if isinstance(rv, str) and _HEX_RE.match(rv) and isinstance(dec, str) and _HEX_RE.match(dec) and int(dec, 16) == 18:
            v = int(rv, 16)
    except ValueError:
        v = None
    parts = uid.split(":")
    path = None
    if len(parts) >= 3 and parts[0].lower() == h and parts[1] == "internal":
        path = ":".join(parts[2:])
    return {"uid": uid, "hash": h, "blk": blk, "from": f9, "to": t9, "value": v, "root": path == "", "path": path}


def _path_key(p) -> tuple:
    if not p:
        return (1,)
    try:
        return (0,) + tuple(int(x) for x in str(p).split("_"))
    except ValueError:
        return (1,)


def fetch_range(url: str, b0: int, b1: int, kw: dict = None, max_pages: int = MAX_PAGES) -> tuple:
    if not url or int(b0) < 0 or int(b1) < int(b0):
        raise AlchSkip("범위·주소 없음")
    kw = dict(kw or {"timeout": 20.0, "retries": 1})
    seen, order = {}, []
    pk, pages, restarts = None, 0, 0
    while True:
        if pages >= int(max_pages):
            raise AlchFail("partial", f"쪽 상한 {max_pages} — 미완료")
        prm = {"fromBlock": hex(int(b0)), "toBlock": hex(int(b1)), "category": ["internal"], "excludeZeroValue": True,
               "withMetadata": False, "maxCount": hex(PAGE_MAX), "order": "asc"}
        if pk:
            prm["pageKey"] = pk
        try:
            res = bf_engine.rpc_call(url, METHOD, [prm], **kw)
        except AlchFail:
            raise
        except Exception as e:  # noqa: BLE001
            if _local(e):
                raise AlchFail("budget", f"0콜 거절({getattr(e, 'kind', '?')})")
            if _cap_off(e):
                _set_off(f"키 거부·미지원({getattr(e, 'code', None) or getattr(e, 'kind', '?')})")
                raise AlchSkip("키 거부·미지원 — 1시간 쉼")
            raise AlchFail(str(getattr(e, "kind", None) or type(e).__name__), logs.safe_err(e)[:120])
        pages += 1
        if not isinstance(res, dict) or not isinstance(res.get("transfers"), list):
            raise AlchFail("payload", "transfers 없음")
        new9 = 0
        for t in res["transfers"]:
            n9 = norm(t)
            if not (int(b0) <= n9["blk"] <= int(b1)):
                raise AlchFail("payload", "범위 밖 블록")
            if n9["uid"] in seen:
                continue
            seen[n9["uid"]] = n9
            order.append(n9["uid"])
            new9 += 1
        nk = res.get("pageKey")
        if nk in (None, ""):
            break
        if not isinstance(nk, str) or len(nk) > 512:
            raise AlchFail("payload", "pageKey 형식")
        if pk is not None and not new9 and res["transfers"]:
            restarts += 1
        pk = nk
    return [seen[u] for u in order], {"pages": pages, "restarts": restarts, "calls": pages}


def rows_for(transfers: list, myset) -> dict:
    my = {str(a).lower() for a in myset or ()}
    per = {}
    for t in transfers or ():
        if t.get("root"):
            continue
        if t.get("from") not in my and t.get("to") not in my:
            continue
        if t.get("value") is None:
            raise AlchFail("precision", "내 지갑 행 원시값(rawContract.value·decimal 18) 없음 — 정밀도 미확인")
        if int(t["value"]) <= 0:
            continue
        per.setdefault(t["hash"], []).append(t)
    out = {}
    for h, lst in per.items():
        lst = sorted(lst, key=lambda x: _path_key(x.get("path")))
        out[h] = [{"from": x["from"], "to": x["to"], "value": str(int(x["value"])), "success": True} for x in lst]
    return out
