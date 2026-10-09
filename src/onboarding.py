"""Setup wizard API (wallets, keys, Telegram) for the local web UI."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import cgplan
import common
import demo_data
import settings_store as ss

log = common.setup_logging("tj-web")
DEMO = os.environ.get("TJ_DEMO") == "1"
SETUP_JS = os.path.join(common.BASE_DIR, "web", "v2", "setup.js")
UA = "tj-bot/1.0 (self-hosted trade journal)"
MAX_BODY = 64 * 1024


def _hostname(host_header: str) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def host_allowed(host_header: str) -> bool:
    h = _hostname(host_header)
    if not h:
        return False
    if _is_ip(h) or h == "localhost" or h.endswith(".ts.net"):
        return True
    try:
        extra = (ss.read_config_raw().get("web") or {}).get("allowed_hosts") or []
    except Exception:
        extra = []
    return h in {str(x).lower() for x in extra}


_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _setup_allow_lan() -> bool:
    try:
        return (ss.read_config_raw().get("web") or {}).get("setup_allow_lan") is True
    except Exception:
        return False


def client_allowed(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    if a.is_loopback:
        return True
    if (a.version == 4 and a in _TAILNET_V4) or (a.version == 6 and a in _TAILNET_V6):
        return True
    return bool(a.is_private) and _setup_allow_lan()


def origin_ok(h, required: bool) -> bool:
    sfs = (h.headers.get("Sec-Fetch-Site") or "").lower()
    if sfs in ("cross-site", "same-site"):
        return False
    origin = h.headers.get("Origin")
    if not origin:
        return not required
    try:
        u = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.netloc:
        return False
    host = (h.headers.get("Host") or "").strip().lower()
    return u.netloc.lower() == host


def guard(h, method: str) -> bool:
    if not host_allowed(h.headers.get("Host") or ""):
        h._send(421, {"ok": False, "error": "허용되지 않은 Host — IP 주소·localhost·테일넷 이름으로 접속하세요"})
        return False
    if method == "POST" and not origin_ok(h, required=False):
        h._send(403, {"ok": False, "error": "다른 출처(사이트)에서 온 요청은 거부합니다"})
        return False
    return True


class RateLimit:
    def __init__(self):
        self.ev = {}
        self.lock = threading.Lock()

    def hit(self, key: str, n: int, per: float) -> bool:
        now = time.time()
        with self.lock:
            q = [t for t in self.ev.get(key, []) if now - t < per]
            if len(q) >= n:
                self.ev[key] = q
                return False
            q.append(now)
            self.ev[key] = q
            return True


RL = RateLimit()


def scrub(msg, extra=()) -> str:
    s = str(msg)
    vals = [v for v in list(ss.read_env().values()) + list(extra) if v and len(v) >= 4]
    for v in sorted(vals, key=len, reverse=True):
        s = s.replace(v, "••••")
    s = re.sub(r"bot\d+:[A-Za-z0-9_-]{10,}", "bot••••", s)
    s = re.sub(r"(api[-_]?key=)[^&\s\"']+", r"\1••••", s, flags=re.I)
    return s[:300]


def demo_synth() -> bool:
    return DEMO and not os.path.exists(common.CONFIG_PATH)


def why_text(e, what: str) -> str:
    log.warning("%s 읽기 실패: %s", what, scrub(type(e).__name__))
    if isinstance(e, FileNotFoundError):
        return ("필요한 파일이 아직 없어요 — config.json 이 없거나 수집기가 아직 한 번도 돌지 않았어요. "
                "설정 마법사에서 지갑을 넣고 수집기(pm2 start ecosystem.config.js)를 켠 뒤 몇 분 뒤에 다시 보세요")
    if isinstance(e, PermissionError):
        return "파일을 읽을 권한이 없어요 — tj-bot 폴더와 state/ 의 소유자가 화면(tj-web)을 띄운 사용자와 같은지 확인하세요"
    if isinstance(e, sqlite3.Error):
        return "원장(state/ledger.db)을 읽지 못했어요 — 아직 만들어지기 전이거나 잠겨 있어요. 잠시 뒤 다시 시도하세요"
    if isinstance(e, (ValueError, SystemExit)):
        return "설정·상태 파일 형식이 깨졌을 수 있어요 — config.json 을 확인하고, 계속되면 tj-web 로그(pm2 logs tj-web)를 보세요"
    if isinstance(e, OSError):
        return "파일을 읽지 못했어요(디스크·파일 문제) — tj-web 로그(pm2 logs tj-web)를 확인하세요"
    return "예상하지 못한 오류가 났어요 — tj-web 로그(pm2 logs tj-web)에서 자세한 내용을 확인하세요"


def net_why(e) -> str:
    import socket
    import ssl
    log.warning("외부 연결 실패: %s", scrub(type(e).__name__))
    r = getattr(e, "reason", None)
    if isinstance(e, urllib.error.HTTPError):
        return f"서버가 거절했어요(HTTP {e.code}) — 잠시 뒤 다시 시도하세요"
    if isinstance(e, (socket.timeout, TimeoutError)) or isinstance(r, (socket.timeout, TimeoutError)):
        return "응답이 너무 늦어요 — 잠시 뒤 다시 시도하세요"
    if isinstance(e, ssl.SSLError) or isinstance(r, ssl.SSLError):
        return "보안 연결(SSL)을 맺지 못했어요 — 서버 시계와 인증서 설정을 확인하세요"
    if isinstance(r, socket.gaierror) or isinstance(e, socket.gaierror):
        return "주소를 찾지 못했어요 — 이 서버의 인터넷(DNS) 연결을 확인하세요"
    if isinstance(e, ConnectionError) or isinstance(r, (ConnectionError, OSError)) or isinstance(e, urllib.error.URLError):
        return "서버에 닿지 못했어요 — 이 서버의 인터넷 연결·방화벽을 확인하고 잠시 뒤 다시 시도하세요"
    return "예상하지 못한 오류가 났어요 — 잠시 뒤 다시 시도하고, 계속되면 tj-web 로그(pm2 logs tj-web)를 보세요"


def _base(name: str, default: str) -> str:
    v = os.environ.get("TJ_TEST_BASE_" + name.upper(), "")
    return v.rstrip("/") if v.startswith("http://127.0.0.1:") else default


def _cg_base(plan: str) -> str:
    real = cgplan.ROOT["pro" if plan == "pro" else "demo"]
    if plan == "pro":
        v = os.environ.get("TJ_TEST_BASE_COINGECKO_PRO", "")
        if not v.startswith("http://127.0.0.1:"):
            v = os.environ.get("TJ_TEST_BASE_COINGECKO", "")
        return (v.rstrip("/") + "/api/v3") if v.startswith("http://127.0.0.1:") else real
    v = _base("coingecko", "")
    return (v + "/api/v3") if v else real


_CG_BUDGET_MSG = {
    "minute": "코인게코 호출 몫(공표 한도의 80%)이 지금 꽉 찼어요(시세·NFT 조회 중) — 잠시 뒤(1분쯤) 다시 시험하세요",
    "day": "오늘(이번 달) 쓸 수 있는 코인게코 호출 몫(공표 한도의 80%)을 다 써서 확인하지 않았어요 — 몫이 생기면(하루 뒤·다음 달) 다시 시험하세요",
    "store": "호출 예산 기록을 확인하지 못해 코인게코를 부르지 않았어요 — 잠시 뒤 다시 시험하세요",
}
_CG_PROBE = {}
_CG_PROBE_TTL = 600


def _cg_probe(key: str, cached: bool = False) -> dict:
    fp = cgplan.kfp(key)
    now = time.time()
    c = _CG_PROBE.get(fp)
    if cached and c and now - c[0] < _CG_PROBE_TTL:
        return c[1]
    try:
        prefer = (cgplan.Store().load(key) or {}).get("plan")
    except Exception:
        prefer = None

    def reserve():
        try:
            import nft
            return nft.cg_reserve(key)
        except Exception as e:
            log.warning("코인게코 확인 예산 확인 실패: %s", type(e).__name__)
            return "store"
    r = cgplan.probe(key, lambda u, h: _http(u, h), base=_cg_base, prefer=prefer, reserve=reserve)
    if r.get("ok"):
        if len(_CG_PROBE) > 8:
            _CG_PROBE.clear()
        _CG_PROBE[fp] = (now, r)
    return r


def _cg_ours() -> int:
    try:
        import nft
        return nft.shared_budget().month_count("coingecko_key")
    except Exception:
        return 0


def _cg_status(key: str) -> dict:
    st = cgplan.Store()
    try:
        rec = st.load(key) if key else None
    except Exception:
        rec = None
    return cgplan.status(rec, None, st.share(), _cg_ours())


def _cg_record(key: str, r: dict, how: str) -> None:
    if not r.get("ok"):
        return
    now = int(time.time())
    f = {"plan": r["plan"], "at": now, "how": how}
    if r["plan"] == "pro" and "info" in r:
        f["info_try_at"] = now
        if r.get("info"):
            f.update(info=r["info"], info_at=now)
        else:
            f.update(info=None, info_at=None)
    try:
        cgplan.Store().save(key, **f)
    except Exception as e:
        log.warning("코인게코 키 등급 기록 실패: %s", type(e).__name__)


def _http(url: str, headers=None, data=None, method=None, timeout=12, sol=False):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    try:
        import bf_engine as _bfe9
        with _bfe9.sol_open(req, timeout, sol=sol) as r:
            raw = r.read(1 << 20)
            code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read(1 << 16) if e.fp else b""
        code = e.code
    try:
        return code, json.loads(raw.decode("utf-8") or "null")
    except ValueError:
        return code, raw.decode("utf-8", "replace")[:300]


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt_hs256(payload: dict, secret: str) -> str:
    h = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    p = _b64u(json.dumps(payload).encode())
    s = _b64u(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"


def _err_text(code, d) -> str:
    if isinstance(d, dict):
        e = d.get("error")
        if isinstance(e, dict):
            return f"{e.get('name') or ''} {e.get('message') or ''}".strip()
        for k in ("msg", "retMsg", "message", "description", "label"):
            if d.get(k):
                return str(d.get(k))
    return f"HTTP {code}"


def _ip_hint(text: str) -> str:
    t = text.lower()
    if "ip" in t and any(w in t for w in ("whitelist", "authorization_ip", "not allowed", "restrict", "허용", "등록")):
        return " — 키의 IP 화이트리스트에 이 서버 공인 IP 를 등록하세요"
    if any(w in t for w in ("invalid", "signature", "api-key", "apikey", "jwt", "unauthorized", "401")):
        return " — 키·시크릿 복사가 정확한지 확인하세요"
    return ""


PERM_VERIFIABLE = ("binance", "bybit", "okx")
PERM_WHY = ("이 봇은 잔고·내역 조회만 합니다 — 거래·출금·이체 권한은 전혀 쓰지 않습니다. 그런데 키는 이 서버 .env 에 저장되므로, "
            "서버·백업·화면 공유 중 어디서든 키가 새면 거래 권한으로는 남이 내 계정에서 사고팔아 자산을 빼돌릴 수 있고"
            "(유동성 없는 코인을 비싸게 사게 만드는 식), 출금 권한으로는 바로 외부 주소로 보낼 수 있으며, 이체 권한으로는 계정 사이로 자산을 옮길 수 있습니다. "
            "조회 전용 키는 새더라도 볼 수만 있습니다.")
PERM_FIX = {
    "binance": ["바이낸스 → Account → API Management 에서 이 키를 삭제(Delete)하세요",
                "Create API → System generated 로 새 키를 만드세요",
                "Edit restrictions 에서 Enable Reading 만 남기고 Spot & Margin Trading · Margin Loan · Futures · European Options · "
                "Withdrawals · Universal Transfer · Internal Transfer 를 모두 끄세요",
                "IP access restrictions → Restrict access to trusted IPs only → 이 서버 공인 IP",
                "새 API Key·Secret Key 를 여기에 다시 넣으세요"],
    "bybit": ["바이비트 → Account & Security → API 에서 이 키를 삭제하세요",
              "Create New Key → System-generated API Keys",
              "API Key Permissions 를 Read-Only 로 고르세요 (Read-Write 금지, Wallet 의 Withdraw·Transfer 체크 금지)",
              "IP 제한: Only IPs with permissions granted → 이 서버 공인 IP",
              "새 API Key·Secret 을 여기에 다시 넣으세요"],
    "okx": ["OKX → 프로필 → API 에서 이 키를 삭제하세요",
            "Create API key 에서 권한은 Read 만 체크하세요 (Trade·Withdraw 체크 금지)",
            "IP 허용 목록에 이 서버 공인 IP 를 넣으세요",
            "새 API Key·Secret·Passphrase 를 여기에 다시 넣으세요"],
}
PERM_NOT_CHECKABLE = ("이 거래소(업비트·빗썸·쿠코인·게이트)는 API 로 키 권한을 확인할 수 없습니다 — 자동 확인은 바이낸스·바이비트·OKX 만 됩니다. "
                      "발급 화면에서 '조회' 권한만 켰는지 직접 확인하세요")
PERM_RETRY = "키 권한을 자동으로 확인하지 못해 저장하지 않았습니다 — 잠시 뒤 다시 저장하세요(이 거래소는 '조회 권한만 켰음' 체크로 대신할 수 없습니다)"

_BN_ALLOW_TRUE = frozenset(("enableReading", "ipRestrict", "enableFixReadOnly"))
_BN_LABELS = (
    ("enableWithdrawals", "withdraw", "출금 (Enable Withdrawals)"),
    ("enableSpotAndMarginTrading", "trade", "현물·마진 거래 (Enable Spot & Margin Trading)"),
    ("enableMargin", "trade", "마진 대출·상환·이체 (Enable Margin Loan, Repay & Transfer)"),
    ("enableFutures", "trade", "선물 거래 (Enable Futures)"),
    ("enableVanillaOptions", "trade", "옵션 거래 (Enable European Options)"),
    ("enablePortfolioMarginTrading", "trade", "포트폴리오 마진 거래 (Enable Portfolio Margin Trading)"),
    ("enableFixApiTrade", "trade", "FIX API 거래 (Enable FIX API Trade)"),
    ("permitsUniversalTransfer", "transfer", "유니버설 이체 (Permits Universal Transfer)"),
    ("enableInternalTransfer", "transfer", "내부 이체 (Enable Internal Transfer)"),
)


def _perm_binance(r: dict):
    if not isinstance(r, dict):
        return None
    d = []
    known = set()
    for k, kind, lab in _BN_LABELS:
        known.add(k)
        if r.get(k):
            d.append((kind, lab))
    for k in sorted(str(x) for x in r):
        if k in known or k in _BN_ALLOW_TRUE:
            continue
        v = r.get(k)
        if v is True or (k.lower().startswith(("enable", "permit")) and not isinstance(v, bool) and v not in (None, 0, "", "false")):
            d.append(("other", f"알 수 없는 권한 ({k[:60]}) — 조회 전용 키에는 Enable Reading 만 켜져 있어야 합니다"))
    if not d and (any(k not in r for k in _BN_CORE) or any(k in r and not isinstance(r[k], bool) for k in _BN_KEYS)):
        return None
    return d


_BN_KEYS = ("enableReading", "enableWithdrawals", "enableSpotAndMarginTrading", "enableMargin", "enableFutures",
            "enableVanillaOptions", "enablePortfolioMarginTrading", "enableFixApiTrade",
            "permitsUniversalTransfer", "enableInternalTransfer")
_BN_CORE = ("enableReading", "enableWithdrawals", "enableSpotAndMarginTrading", "enableFutures",
            "permitsUniversalTransfer", "enableInternalTransfer")


def _perm_bybit(res: dict):
    if not isinstance(res, dict):
        return None
    raw_ro = res.get("readOnly")
    ro = int(raw_ro) if type(raw_ro) in (int, str) and str(raw_ro) in ("0", "1") else None
    perms = res.get("permissions") if isinstance(res.get("permissions"), dict) else None
    flat = set()
    odd = perms is None or ro is None
    for v in (perms or {}).values():
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",")]
        elif not isinstance(v, list):
            odd = True
            continue
        if any(not isinstance(x, str) for x in v):
            odd = True
        flat |= {x.strip() for x in v if isinstance(x, str)}
    d = []
    if "Withdraw" in flat:
        d.append(("withdraw", "출금 (Wallet › Withdraw)"))
    if ro == 0:
        d.append(("trade", "읽기/쓰기 키 (Read-Write) — 주문·포지션 변경 가능"))
        tr = sorted(flat & {"AccountTransfer", "SubMemberTransfer", "SubMemberTransferList"})
        if tr:
            d.append(("transfer", "이체 (Wallet › " + ", ".join(tr) + ")"))
    if not d and odd:
        return None
    return d


def _perm_okx(perm):
    if isinstance(perm, (list, tuple)):
        perm = ",".join(str(x) for x in perm)
    if not isinstance(perm, str):
        return None
    toks = {t.strip().lower() for t in perm.split(",") if t.strip()}
    if not toks:
        return None
    d = []
    if "withdraw" in toks:
        d.append(("withdraw", "출금 (Withdraw)"))
    if "trade" in toks:
        d.append(("trade", "거래 (Trade — 주문·계정 간 이체 포함)"))
    if not d and toks - {"read_only"}:
        return None
    return d


def _perm_result(danger, note=""):
    if danger is None:
        return {"checked": False, "danger": [], "note": note or "키 권한 응답을 해석하지 못했습니다"}
    return {"checked": True, "danger": [{"kind": k, "label": lab} for k, lab in danger], "note": note}


def perm_block_info(group: str, danger: list) -> dict:
    kinds = [x["kind"] for x in danger]
    what = "·".join(n for k, n in (("trade", "거래"), ("withdraw", "출금"), ("transfer", "이체"), ("other", "기타")) if k in kinds)
    return {"group": group, "name": ss.EXCHANGES[group]["name"], "danger": danger, "kinds": sorted(set(kinds)),
            "title": f"{ss.EXCHANGES[group]['name']} 키에 {what} 권한이 켜져 있습니다", "why": PERM_WHY,
            "fix": PERM_FIX.get(group, [])}


def perm_gate(group: str, vals: dict, ack: bool):
    if group in PERM_VERIFIABLE:
        r = test_group(group, vals)
        p = r.get("perm") or {}
        if p.get("checked") and p.get("danger"):
            info = perm_block_info(group, p["danger"])
            return {"ok": False, "permBlock": info,
                    "error": info["title"] + " — 저장하지 않았습니다. 조회 전용 키로 다시 만들어 넣어 주세요"}, None
        if p.get("checked"):
            return None, {"how": "api", "at": int(time.time())}
        if not r.get("ok") and r.get("detail"):
            why = scrub(r.get("detail"), vals.values())
            return {"ok": False, "permRetry": True, "reason": why,
                    "error": "연결 테스트 실패 — " + why + " · 키 권한을 확인할 수 없어 저장하지 않았습니다(원인을 고친 뒤 다시 저장하세요)"}, None
        why = scrub(p.get("note") or r.get("detail") or "권한 확인 실패", vals.values())
        return {"ok": False, "permRetry": True, "reason": why, "error": PERM_RETRY + " (" + why + ")"}, None
    if not ack:
        return {"ok": False, "needAck": True, "reason": PERM_NOT_CHECKABLE,
                "error": "'조회 권한만 켰음'을 확인해야 저장할 수 있습니다 — " + PERM_NOT_CHECKABLE}, None
    return None, {"how": "ack", "at": int(time.time())}


def test_group(group: str, vals: dict) -> dict:
    g = ss.GROUPS[group]
    fk = [k for k, _ in g["fields"]]
    v = [vals.get(k, "") for k in fk]
    if not all(v):
        return {"ok": False, "detail": "모든 칸을 채워야 테스트할 수 있습니다"}
    r = _test_group(group, v)
    if group in ss.EXCHANGES and "perm" not in r:
        r["perm"] = {"checked": False, "danger": [], "unsupported": group not in PERM_VERIFIABLE,
                     "note": PERM_NOT_CHECKABLE if group not in PERM_VERIFIABLE else "연결 테스트가 실패해 키 권한을 확인하지 못했습니다"}
    return r


def _test_group(group: str, v: list) -> dict:
    warn = []
    try:
        if group == "helius":
            import bf_engine as _bfe9
            try:
                _bfe9.helius_configure(common.load_config())
            except (Exception, SystemExit):
                pass
            if not _bfe9.HELIUS.take("web", 1, kind="must"):
                return {"ok": False, "detail": "Helius 오늘 호출 예산을 다 써서 지금은 확인을 미뤄요(" + str(_bfe9.HELIUS.last_why()) + ") — UTC 0시(한국 오전 9시) 뒤 다시"}
            code, d = _http(_base("helius", "https://mainnet.helius-rpc.com") + "/?api-key=" + urllib.parse.quote(v[0]),
                            {"Content-Type": "application/json"},
                            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}).encode(), "POST", sol=True)
            ok = code == 200 and isinstance(d, dict) and d.get("result") == "ok"
            return {"ok": ok, "detail": "Helius 응답 정상 (getHealth)" if ok else _err_text(code, d)}
        if group == "etherscan":
            q = urllib.parse.urlencode({"chainid": 1, "module": "stats", "action": "ethprice", "apikey": v[0]})
            import bf_engine
            u9 = _base("etherscan", "https://api.etherscan.io") + "/v2/api?" + q
            if (urllib.parse.urlsplit(u9).hostname or "").lower() == "api.etherscan.io":
                if not bf_engine.es_budget_take("web"):
                    if bf_engine.es_budget_why() == "pace":
                        return {"ok": False, "detail": "이더스캔 실시간 확인 몫을 하루에 나눠 쓰느라 잠시 대기 중(옛 기록을 먼저 채우는 중) — 잠시 뒤 다시 확인"}
                    return {"ok": False, "detail": "이더스캔 하루 예산(공표 한도 80% · 수집기와 합산) 소진 — UTC 자정 뒤 다시 확인"}
                bf_engine.es_dispatch_wait(time.time() + 15)
            code, d = _http(u9)
            ok = isinstance(d, dict) and str(d.get("status")) == "1"
            return {"ok": ok, "detail": "Etherscan 키 정상" if ok else str((d or {}).get("result") or _err_text(code, d))
                    if isinstance(d, dict) else _err_text(code, d)}
        if group == "opensea":
            code, d = _http(_base("opensea", "https://api.opensea.io") + "/api/v2/collections/pudgypenguins/stats", {"x-api-key": v[0]})
            ok = code == 200 and isinstance(d, dict) and isinstance(d.get("total"), dict)
            return {"ok": ok, "detail": "OpenSea 키 정상 (컬렉션 통계)" if ok else _err_text(code, d)}
        if group == "coingecko":
            r = _cg_probe(v[0])
            if r.get("ok"):
                t9 = time.time()
                rec = {"plan": r["plan"], "info": r.get("info"), "info_at": t9 if r.get("info") else None, "info_try_at": t9 if "info" in r else None}
                tx9 = cgplan.plan_text(rec, t9, cgplan.Store().share(), _cg_ours())
                det = f"CoinGecko {cgplan.PLAN_KO[r['plan']]} 키 정상 — {tx9}"
                if r["plan"] == "pro" and not r.get("info_ok"):
                    det += " (사용량 /key 를 못 읽었어요 — 확인될 때까지 데모 수준으로만 써요)"
                return {"ok": True, "detail": det, "cg": {"plan": r["plan"], "text": tx9}, "_cg": r}
            if r.get("budget"):
                return {"ok": False, "detail": _CG_BUDGET_MSG.get(r["budget"], _CG_BUDGET_MSG["store"])}
            if r.get("rejected"):
                return {"ok": False, "detail": r.get("detail") or "CoinGecko 가 키를 거부했습니다"}
            return {"ok": False, "detail": "CoinGecko 연결 실패 — " + str(r.get("detail") or "응답 없음") + " · 잠시 뒤 다시 시험하세요"}
        if group in ("upbit", "bithumb"):
            base = _base(group, "https://api.upbit.com" if group == "upbit" else "https://api.bithumb.com")
            pl = {"access_key": v[0], "nonce": str(uuid.uuid4())}
            if group == "bithumb":
                pl["timestamp"] = int(time.time() * 1000)
            code, d = _http(base + "/v1/accounts", {"Authorization": "Bearer " + _jwt_hs256(pl, v[1])})
            if code == 200 and isinstance(d, list):
                return {"ok": True, "detail": f"잔고 조회 성공 · 자산 {len(d)}종"}
            t = _err_text(code, d)
            return {"ok": False, "detail": t + _ip_hint(t)}
        if group == "binance":
            base = _base("binance", "https://api.binance.com")

            def call(path):
                qs = urllib.parse.urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 10000})
                sig = hmac.new(v[1].encode(), qs.encode(), hashlib.sha256).hexdigest()
                return _http(f"{base}{path}?{qs}&signature={sig}", {"X-MBX-APIKEY": v[0]})
            code, d = call("/api/v3/account")
            if not (code == 200 and isinstance(d, dict) and "balances" in d):
                t = _err_text(code, d)
                return {"ok": False, "detail": t + _ip_hint(t)}
            n = sum(1 for b in d.get("balances") or [] if float(b.get("free") or 0) + float(b.get("locked") or 0) > 0)
            c2, r = call("/sapi/v1/account/apiRestrictions")
            perm = _perm_result(None, f"권한 조회 실패({_err_text(c2, r)})")
            if c2 == 200 and isinstance(r, dict):
                perm = _perm_result(_perm_binance(r))
                ks = {x["kind"] for x in perm["danger"]}
                if "withdraw" in ks:
                    warn.append("출금 권한이 켜져 있습니다 — 조회 전용 키로 다시 만드세요")
                if "trade" in ks:
                    warn.append("거래 권한이 켜져 있습니다 — 이 봇은 조회만 합니다(Enable Reading 만 필요)")
                if "transfer" in ks:
                    warn.append("이체 권한이 켜져 있습니다 — 조회 전용 키로 다시 만드세요")
                if not r.get("ipRestrict"):
                    warn.append("IP 제한이 꺼져 있습니다 — 이 서버 IP 로 제한하길 권장")
            return {"ok": True, "detail": f"잔고 조회 성공 · 보유 자산 {n}종", "warn": warn, "perm": perm}
        if group == "bybit":
            base = _base("bybit", "https://api.bybit.com")

            def call(path, params):
                qs = urllib.parse.urlencode(params)
                ts, recv = str(int(time.time() * 1000)), "10000"
                sig = hmac.new(v[1].encode(), (ts + v[0] + recv + qs).encode(), hashlib.sha256).hexdigest()
                return _http(f"{base}{path}" + (f"?{qs}" if qs else ""),
                             {"X-BAPI-API-KEY": v[0], "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sig})
            code, d = call("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
            if not (isinstance(d, dict) and d.get("retCode") == 0):
                t = _err_text(code, d)
                return {"ok": False, "detail": t + _ip_hint(t)}
            c2, r = call("/v5/user/query-api", {})
            perm = _perm_result(None, f"권한 조회 실패({_err_text(c2, r)})")
            if isinstance(r, dict) and r.get("retCode") == 0:
                res = r.get("result") or {}
                perm = _perm_result(_perm_bybit(res))
                ks = {x["kind"] for x in perm["danger"]}
                if "trade" in ks:
                    warn.append("읽기/쓰기 키입니다 — Read-Only 키로 다시 만드세요")
                if "withdraw" in ks:
                    warn.append("출금 권한이 켜져 있습니다 — 조회 전용 키로 다시 만드세요")
                if not res.get("ips") or res.get("ips") == ["*"]:
                    warn.append("IP 제한이 없습니다 — 이 서버 IP 로 제한하길 권장")
            return {"ok": True, "detail": "잔고 조회 성공 (Unified 계정)", "warn": warn, "perm": perm}
        if group == "okx":
            base = _base("okx", "https://www.okx.com")

            def call(path):
                ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"
                sig = base64.b64encode(hmac.new(v[1].encode(), (ts + "GET" + path).encode(), hashlib.sha256).digest()).decode()
                return _http(base + path, {"OK-ACCESS-KEY": v[0], "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": ts,
                                           "OK-ACCESS-PASSPHRASE": v[2]})
            code, d = call("/api/v5/account/balance")
            if not (isinstance(d, dict) and str(d.get("code")) == "0"):
                t = _err_text(code, d)
                return {"ok": False, "detail": t + _ip_hint(t)}
            c2, r = call("/api/v5/account/config")
            perm = _perm_result(None, f"권한 조회 실패({_err_text(c2, r)})")
            if isinstance(r, dict) and str(r.get("code")) == "0" and r.get("data") and isinstance(r["data"], list):
                p9 = (r["data"][0].get("perm") if isinstance(r["data"][0], dict) else None)
                perm = _perm_result(_perm_okx(p9))
                p9 = str(p9 or "")
                if perm["danger"]:
                    warn.append(f"키 권한이 '{p9[:60]}' 입니다 — Read 만 켠 키로 다시 만드세요")
            return {"ok": True, "detail": "잔고 조회 성공", "warn": warn, "perm": perm}
        if group == "kucoin":
            base = _base("kucoin", "https://api.kucoin.com")
            path = "/api/v1/accounts"
            ts = str(int(time.time() * 1000))
            sig = base64.b64encode(hmac.new(v[1].encode(), (ts + "GET" + path).encode(), hashlib.sha256).digest()).decode()
            pph = base64.b64encode(hmac.new(v[1].encode(), v[2].encode(), hashlib.sha256).digest()).decode()
            code, d = _http(base + path, {"KC-API-KEY": v[0], "KC-API-SIGN": sig, "KC-API-TIMESTAMP": ts,
                                          "KC-API-PASSPHRASE": pph, "KC-API-KEY-VERSION": "2"})
            if isinstance(d, dict) and str(d.get("code")) == "200000":
                return {"ok": True, "detail": f"잔고 조회 성공 · 계정 {len(d.get('data') or [])}개"}
            t = _err_text(code, d)
            return {"ok": False, "detail": t + _ip_hint(t)}
        if group == "gate":
            base = _base("gate", "https://api.gateio.ws")
            path = "/api/v4/spot/accounts"
            ts = str(int(time.time()))
            payload = f"GET\n{path}\n\n{hashlib.sha512(b'').hexdigest()}\n{ts}"
            sig = hmac.new(v[1].encode(), payload.encode(), hashlib.sha512).hexdigest()
            code, d = _http(base + path, {"KEY": v[0], "Timestamp": ts, "SIGN": sig})
            if code == 200 and isinstance(d, list):
                return {"ok": True, "detail": f"잔고 조회 성공 · 자산 {len(d)}종"}
            t = _err_text(code, d)
            return {"ok": False, "detail": t + _ip_hint(t)}
    except Exception as e:
        log.warning("키 시험 연결 실패(%s): %s", group, scrub(e, v)[:200])
        return {"ok": False, "detail": "연결 실패 — " + net_why(e)}
    return {"ok": False, "detail": "알 수 없는 대상"}


TG_TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,64}$")
TG = {"lock": threading.Lock(), "p": None}


def _tg(token: str, method: str, params: dict | None = None, timeout: int = 12):
    base = _base("telegram", "https://api.telegram.org")
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                   for k, v in (params or {}).items()}).encode()
    try:
        code, d = _http(f"{base}/bot{token}/{method}", {"Content-Type": "application/x-www-form-urlencoded"}, data, "POST",
                        timeout=timeout)
    except Exception as e:
        log.warning("텔레그램 연결 실패: %s", scrub(e, [token])[:200])
        raise RuntimeError("텔레그램 연결 실패 — " + net_why(e))
    if not isinstance(d, dict):
        raise RuntimeError(f"텔레그램 응답 오류 (HTTP {code})")
    return d


def _pending():
    p = TG["p"]
    if p and time.time() - p["started"] > 600:
        TG["p"] = None
        return None
    return p


def _tg_send(token, chat, text):
    d = _tg(token, "sendMessage", {"chat_id": chat, "text": text})
    if not d.get("ok"):
        raise RuntimeError("테스트 메시지 발송 실패: " + scrub(d.get("description") or "", [token]))


def _tg_save(token, chat, bot, chat_info):
    ss.write_env({ss.TG_TOKEN: token, ss.TG_CHAT: str(chat)})
    ss.update_settings(telegram={"bot": bot.get("username"), "bot_name": bot.get("first_name"),
                                 "chat_type": chat_info.get("type"), "chat_name": chat_info.get("name"),
                                 "connected_at": int(time.time())})


def tg_validate(token: str) -> dict:
    token = (token or "").strip()
    if not TG_TOKEN_RE.match(token):
        return {"ok": False, "error": "토큰 형식이 아닙니다 — @BotFather 가 준 '숫자:영문' 전체를 붙여넣으세요"}
    d = _tg(token, "getMe")
    if not d.get("ok"):
        return {"ok": False, "error": "토큰이 거부됐습니다 (" + scrub(d.get("description") or "", [token]) + ")"}
    bot = d.get("result") or {}
    if not bot.get("username"):
        return {"ok": False, "error": "봇 정보를 읽지 못했습니다"}
    offset = 0
    u = _tg(token, "getUpdates", {"offset": -1, "timeout": 0, "allowed_updates": ["message"]})
    if not u.get("ok"):
        desc = scrub(u.get("description") or "", [token])
        if "webhook" in desc.lower():
            return {"ok": False, "error": "이 봇에 웹훅이 설정돼 있습니다 — 알림 전용 새 봇을 만들어 쓰세요"}
        return {"ok": False, "error": "업데이트 조회 실패 (" + desc + ") — 다른 프로그램이 같은 봇을 쓰고 있으면 새 봇을 만드세요"}
    for x in u.get("result") or []:
        offset = max(offset, int(x.get("update_id") or 0) + 1)
    nonce = secrets.token_hex(6)
    with TG["lock"]:
        TG["p"] = {"token": token, "bot": {"username": bot["username"], "first_name": bot.get("first_name") or ""},
                   "nonce": nonce, "offset": offset, "started": time.time()}
    return {"ok": True, "bot": {"username": bot["username"], "name": bot.get("first_name") or ""},
            "link": f"https://t.me/{bot['username']}?start={nonce}", "start": f"/start {nonce}"}


def tg_poll() -> dict:
    with TG["lock"]:
        p = _pending()
        if not p:
            return {"ok": False, "error": "연결 대기가 만료됐습니다 — 토큰 확인부터 다시 하세요", "expired": True}
        token = p["token"]
        u = _tg(token, "getUpdates", {"offset": p["offset"], "timeout": 1, "allowed_updates": ["message"]}, timeout=8)
        if not u.get("ok"):
            return {"ok": False, "error": "업데이트 조회 실패: " + scrub(u.get("description") or "", [token])}
        found = None
        for x in u.get("result") or []:
            p["offset"] = max(p["offset"], int(x.get("update_id") or 0) + 1)
            msg = x.get("message") or {}
            chat = msg.get("chat") or {}
            text = str(msg.get("text") or "").strip()
            parts = text.split()
            if not parts or not parts[0].split("@")[0] == "/start" or "id" not in chat:
                continue
            if len(parts) > 1 and parts[1] == p["nonce"]:
                found = chat
            elif len(parts) == 1:
                p["bare"] = True
        if not found:
            out = {"ok": True, "waiting": True, "left": int(600 - (time.time() - p["started"]))}
            if p.get("bare"):
                out["hint"] = "코드 없이 보낸 /start 는 연결하지 않습니다 — 화면의 링크(또는 '/start <코드>' 복사)로 보내세요"
            return out
        name = found.get("title") or " ".join(x for x in (found.get("first_name"), found.get("last_name")) if x) \
            or found.get("username") or ""
        info = {"type": found.get("type"), "name": name}
        try:
            _tg_send(token, found["id"], "[tj-bot] 알림 연결 완료 — 이 채팅으로 목표가·손절·분류 알림이 옵니다.")
        except RuntimeError as e:
            return {"ok": False, "error": common.safe_err(e)}
        _tg(token, "getUpdates", {"offset": p["offset"], "timeout": 0})
        _tg_save(token, found["id"], p["bot"], info)
        TG["p"] = None
        return {"ok": True, "connected": True, "chat": info}


def tg_manual(chat_id: str, token: str = "") -> dict:
    chat_id = str(chat_id or "").strip()
    if not re.fullmatch(r"-?\d{3,20}|@[A-Za-z][A-Za-z0-9_]{4,31}", chat_id):
        return {"ok": False, "error": "chat_id 는 숫자(그룹은 -100…) 또는 @채널이름 입니다"}
    tok = str(token or "").strip()
    if not tok:
        return {"ok": False, "needToken": True, "error": "chat_id 를 바꾸려면 봇 토큰을 같이 입력하세요"}
    with TG["lock"]:
        p = _pending()
        if p and hmac.compare_digest(tok.encode(), p["token"].encode()):
            bot = p["bot"]
        else:
            if not TG_TOKEN_RE.match(tok):
                return {"ok": False, "error": "토큰 형식이 아닙니다"}
            d = _tg(tok, "getMe")
            if not d.get("ok"):
                return {"ok": False, "error": "토큰이 거부됐습니다"}
            bot = {"username": (d.get("result") or {}).get("username"), "first_name": (d.get("result") or {}).get("first_name")}
        try:
            _tg_send(tok, chat_id, "[tj-bot] 알림 연결 완료 (chat_id 직접 입력).")
        except RuntimeError as e:
            return {"ok": False, "error": common.safe_err(e) + " — 봇에게 먼저 /start 를 보냈는지, 그룹이면 봇을 초대했는지 확인하세요"}
        _tg_save(tok, chat_id, bot, {"type": "manual", "name": ""})
        TG["p"] = None
    return {"ok": True, "connected": True}


def tg_test() -> dict:
    tok, chat = ss.env_value(ss.TG_TOKEN), ss.env_value(ss.TG_CHAT)
    if not tok or not chat:
        return {"ok": False, "error": "연결된 텔레그램이 없습니다"}
    try:
        _tg_send(tok, chat, "[tj-bot] 테스트 알림입니다.")
    except RuntimeError as e:
        return {"ok": False, "error": common.safe_err(e)}
    return {"ok": True}


def tg_disconnect() -> dict:
    ss.write_env({ss.TG_TOKEN: None, ss.TG_CHAT: None})
    ss.update_settings(telegram=None)
    with TG["lock"]:
        TG["p"] = None
    return {"ok": True}


def _recon_done() -> list:
    if not os.path.exists(common.DB_PATH):
        return []
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=3)
        try:
            return [r[0][len("recon_done_"):] for r in c.execute("SELECT k FROM meta WHERE k LIKE 'recon_done_%'")]
        finally:
            c.close()
    except sqlite3.Error:
        return []


NODE_UNITS = ["tj-bsc", "tj-evm", "tj-core", "tj-web"]


def _node_apply(group: str) -> dict:
    try:
        import wallet_register as wr
        wr._record_reload({"ts": int(time.time()), "chains": ["bsc", "base"], "source": "nodekeys:" + str(group)[:20], "units": list(NODE_UNITS)})
    except Exception:
        pass
    try:
        import chainoff
        return chainoff.apply_info()
    except Exception:
        return {"mode": "", "manual": "pm2 restart " + " ".join(NODE_UNITS)}


def _node_bad(group: str, got: dict) -> str:
    import nodekeys
    for k, v in got.items():
        if k in (nodekeys.ENV_QN_BSC, nodekeys.ENV_QN_BASE):
            if not nodekeys._qn_url(v, "bsc" if k == nodekeys.ENV_QN_BSC else "base"):
                return ("BSC" if k == nodekeys.ENV_QN_BSC else "Base") + " 엔드포인트는 https://…quiknode.pro/… 주소(그 체인용)를 그대로 붙여 넣으세요"
        elif not nodekeys.KEY_RE.match(v):
            return "키 형식이 아니에요(영문·숫자·-·_ 8~128자)"
    return ""


def _node_rpc(url: str, method: str, params: list, timeout: float = 15.0):
    import bf_engine
    d = bf_engine.http_json(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                            timeout=timeout, retries=1)
    if not isinstance(d, dict) or "result" not in d:
        code9 = ((d or {}).get("error") or {}).get("code") if isinstance(d, dict) and isinstance(d.get("error"), dict) else None
        raise RuntimeError("노드가 거절" + (f"(코드 {int(code9)})" if isinstance(code9, int) else ""))
    return d["result"]


def _node_test(group: str, got: dict) -> dict:
    import nodekeys
    bad = _node_bad(group, got)
    if bad:
        return {"ok": False, "error": bad}
    env9 = dict(nodekeys._env())
    env9.update(got)
    keys9 = [v for v in got.values() if v] + [env9.get(k, "") for k, _ in ss.GROUPS[group]["fields"]]
    us = nodekeys.urls(env9)
    out = []
    back = {"bsc": 180 * 192_000, "base": 180 * 43_200}
    probe = {"bsc": "0x0000000000000000000000000000000000001000", "base": "0x4200000000000000000000000000000000000006"}
    cid_want = {"bsc": 56, "base": 8453}
    for c in ("bsc", "base"):
        for p9, u in us[c]:
            if p9 != group:
                continue
            r = {"chain": c, "ok": False}
            try:
                try:
                    cid9 = int(str(_node_rpc(u, "eth_chainId", [])), 16)
                except (TypeError, ValueError):
                    cid9 = None
                if cid9 != cid_want[c]:
                    r["err"] = f"다른 체인 주소(체인 번호 {cid9 if cid9 is not None else '모름'} — {c.upper()} 는 {cid_want[c]})"
                    out.append(r)
                    continue
                head = int(_node_rpc(u, "eth_blockNumber", []), 16)
                r["head"] = head
                bal = _node_rpc(u, "eth_getBalance", [probe[c], hex(max(1, head - back[c]))])
                r["archive"] = isinstance(bal, str) and bal.startswith("0x")
                r["ok"] = True
            except Exception as e:
                nm9 = type(e).__name__
                kind9 = getattr(e, "kind", "") or ""
                r["err"] = (str(e) if isinstance(e, RuntimeError) and str(e).startswith("노드가 거절") else
                            "한도·속도 제한" if kind9 in ("http429", "quota", "budget") else
                            "인증 실패(키·주소 확인)" if kind9 in ("http4xx",) else
                            "연결 실패" if kind9 in ("timeout", "conn", "dns", "http5xx", "circuit") or nm9 in ("URLError", "TimeoutError") else
                            "응답 오류")
            out.append(r)
    if not out:
        return {"ok": False, "error": "시험할 값이 없어요 — 키(또는 엔드포인트)를 넣고 시험하세요"}
    det = " · ".join(f"{r['chain'].upper()} " + (("최신 블록 OK · 옛 블록(약 180일 전) " + ("됨" if r.get("archive") else "안 됨")) if r["ok"] else ("실패 — " + r.get("err", "")))
                     for r in out)
    return {"ok": True, "test": {"ok": all(r["ok"] for r in out), "detail": det, "results": out}}


def _recon_late() -> set:
    if not os.path.exists(common.DB_PATH):
        return set()
    try:
        c = sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=3)
        try:
            rd = {}
            for k, v in c.execute("SELECT k, v FROM meta WHERE k LIKE 'recon_done_%'"):
                try:
                    rd[k[len("recon_done_"):]] = float(v)
                except (TypeError, ValueError):
                    continue
            r9 = c.execute("SELECT v FROM meta WHERE k='ext_rebuilt_at'").fetchone()
            try:
                er = float(r9[0]) if r9 else 0.0
            except (TypeError, ValueError):
                er = 0.0
            out = set()
            for ch, a, t in c.execute("SELECT chain, address, added_at FROM wallets"):
                try:
                    t9 = float(t or 0)
                except (TypeError, ValueError):
                    continue
                if ch in rd and t9 > rd[ch] and t9 > er:
                    a9 = str(a or "")
                    out.add((ch, a9.lower() if a9.startswith("0x") else a9))
            return out
        finally:
            c.close()
    except sqlite3.Error:
        return set()


def status() -> dict:
    env = ss.read_env()
    try:
        raw = ss.read_config_raw()
    except (OSError, ValueError) as e:
        if not DEMO:
            if isinstance(e, FileNotFoundError):
                return {"ok": False, "error": "config.json 이 없어요 — 저장소 폴더에서 bash tools/setup.sh 로 만들고(config.example.json 복사) 화면을 새로 고치세요"}
            return {"ok": False, "error": "config.json 을 읽지 못했어요 — " + (why_text(e, "config.json") if isinstance(e, OSError) else scrub(e))}
        raw = demo_data.demo_config()
    try:
        cfg = ss.load_config_quiet()
    except Exception:
        cfg = raw
    st = ss.read_settings()
    wl = ss.wallet_list(raw)
    late9 = _recon_late()
    try:
        import wallet_register as _wr
        wait9 = _wr.pending_addrs() if _wr.auto_reload_alive() else set()
    except Exception:
        wait9 = set()
    for w in wl:
        a9 = str(w.get("address") or "")
        k9 = a9.lower() if a9.startswith("0x") else a9
        w["reconDone"] = sorted(c for c in w["chains"] if (c, k9) in late9)
        if (a9.lower() if a9.startswith("0x") else a9) in wait9:
            w["applyWait"] = True

    def grp(g):
        fields = [{"key": k, "label": lab, "masked": ss.mask(env.get(k, ""), public=k in ss.PUBLIC_KEY_FIELDS), "set": bool(env.get(k))}
                  for k, lab in g["fields"]]
        return {"name": g["name"], "set": all(x["set"] for x in fields), "partial": any(x["set"] for x in fields),
                "fields": fields}
    runners = ss.runner_status()
    units = {}
    if runners:
        for u in ss.RUNNER_UNITS:
            hb = runners.get(u)
            try:
                ready, why, fp = ss.unit_inputs(u, cfg, env)
            except BaseException:
                ready, why, fp = False, "설정 읽기 실패", ""
            if not hb:
                units[u] = {"state": "unknown"}
            elif not ready:
                units[u] = {"state": "waiting", "why": why}
            elif hb.get("by") == "reload" and hb.get("state") == "pending":
                units[u] = {"state": "pending", "why": ""}
            elif hb.get("by") == "reload" and hb.get("fp") != fp:
                units[u] = {"state": "manual", "why": ""}
            else:
                units[u] = {"state": "applied" if hb.get("fp") == fp else "pending", "why": hb.get("why") or ""}
    exs = {k: grp(g) for k, g in ss.EXCHANGES.items()}
    kp = st.get("key_perm") if isinstance(st.get("key_perm"), dict) else {}
    for k in exs:
        exs[k]["permCheck"] = k in PERM_VERIFIABLE
        rec = kp.get(k)
        exs[k]["perm"] = {"how": rec.get("how"), "at": rec.get("at")} if isinstance(rec, dict) and exs[k]["set"] else None
    dep = demo_data.depaddr_status() if DEMO else _depaddr_status(env)
    if DEMO:
        for k in dep:
            if k in exs:
                exs[k]["set"] = True
    tg_set = bool(env.get(ss.TG_TOKEN) and env.get(ss.TG_CHAT))
    tgs = st.get("telegram") or {}
    p = _pending()
    return {
        "ok": True, "demo": DEMO, "csrf": ss.csrf_token(),
        "needsSetup": not DEMO and not wl and not st.get("onboarded"), "onboarded": bool(st.get("onboarded")),
        "wallets": wl, "chains": [{"key": k, "name": n} for k, n in ss.evm_chains(raw)],
        "solNeedsHelius": (raw.get("sol") or {}).get("rpc") == "helius",
        "evmNeedsKeys": _evm_needs_keys(raw),
        "explorers": _explorers_status(grp),
        "nodes": _nodes_status(),
        "exchanges": exs,
        "telegram": {"connected": tg_set, "bot": tgs.get("bot") if tg_set else None,
                     "chatName": tgs.get("chat_name") if tg_set else None,
                     "chatMasked": ss.mask(env.get(ss.TG_CHAT, ""), public=True) if tg_set else "",
                     "pending": ({"bot": p["bot"]["username"], "link": f"https://t.me/{p['bot']['username']}?start={p['nonce']}",
                                  "start": f"/start {p['nonce']}"} if p else None)},
        "prefs": {"currency": st.get("currency") or "KRW"},
        "apply": {"runner": bool(runners), "units": units,
                  "mode": ("reload" if runners and all(h9.get("by") == "reload" for h9 in runners.values()) else ("runner" if runners else "")),
                  "manual": "pm2 restart tj-evm tj-sol tj-bsc tj-core tj-web"},
        "backfillMonths": raw.get("backfill_months", 5),
        "walletCap": {"max": ss.MAX_ADDRESSES, "batch": ss.MAX_BATCH},
        "depaddr": dep,
        "perp": _perp_status(raw),
    }


def _evm_needs_keys(raw) -> bool:
    try:
        return ss.needs_etherscan(raw)
    except Exception:
        return False


def _tier_view(raw_path: str) -> dict:
    import urllib.parse as _up
    try:
        import addr_tier
        q = _up.parse_qs(raw_path.partition("?")[2])
        try:
            add_n = max(0, min(ss.MAX_ADDRESSES, int((q.get("add") or ["0"])[0])))
        except ValueError:
            add_n = 0
        chains = [c for c in ((q.get("chains") or [""])[0]).split(",") if re.fullmatch(r"[a-z0-9_]{1,24}", c or "")][:40]
        try:
            cfg = ss.load_config_quiet()
        except Exception:
            cfg = {}
        out = addr_tier.web_view(cfg, add_n=add_n, add_chains=chains)
        raw = ss.read_config_raw()
        out["cap"] = {"max": ss.MAX_ADDRESSES, "batch": ss.MAX_BATCH, "n": len({ss._addr_key(w) for w in raw.get("wallets") or []})}
        return out
    except Exception as e:
        return {"ok": False, "error": why_text(e, "확인 주기 정보")}


def _explorers_status(grp) -> dict:
    out = {k: grp(g) for k, g in ss.EXPLORERS.items()}
    for k in ss.NODE_GROUPS:
        if out.get(k) is not None:
            out[k]["set"] = bool(out[k].get("partial"))
    cg = out.get("coingecko")
    if cg is not None:
        cg["plan"] = None
        if cg.get("set"):
            try:
                cg["plan"] = _cg_status(ss.env_value(cgplan.ENV_KEY))
            except Exception:
                cg["plan"] = cgplan.status(None)
    return out


def _nodes_status() -> dict:
    try:
        import nodekeys
        return nodekeys.status()
    except Exception:
        return {}


def _perp_status(raw) -> dict:
    try:
        import perp_dex
        return {"dexes": [{"key": k, "name": v["name"], "kind": v["kind"]} for k, v in perp_dex.DEXES.items()],
                "wallets": ss.perp_list(raw), "state": perp_dex.status(raw), "max": ss.MAX_PERP}
    except Exception as e:
        return {"error": why_text(e, "퍼프 덱스 상태"), "dexes": [], "wallets": []}


def _depaddr_status(env) -> dict:
    try:
        import depaddr
        return depaddr.summary(env)
    except Exception as e:
        return {"error": why_text(e, "입금주소 수집 현황")}


def handle_get(h, path: str) -> bool:
    if not guard(h, "GET"):
        return True
    if path == "/v2/setup.js":
        sa9 = getattr(h, "_send_asset", None)
        if callable(sa9):
            sa9(SETUP_JS, "application/javascript; charset=utf-8", str(getattr(h, "path", "") or "").partition("?")[2])
            return True
        with open(SETUP_JS, "rb") as f:
            h._send(200, f.read(), "application/javascript; charset=utf-8")
        return True
    if path == "/api/setup/status":
        if not client_allowed(h.client_address[0]):
            h._send(403, {"ok": False, "error": "로컬·테일넷에서만 설정할 수 있습니다"})
            return True
        h._send(200, status())
        return True
    if demo_synth() and path in ("/api/setup/tier", "/api/setup/chains"):
        try:
            h._send(200, demo_data.tier_view(getattr(h, "path", "") or "") if path == "/api/setup/tier" else demo_data.chains_view())
        except Exception as e:
            h._send(200, {"ok": False, "error": why_text(e, "확인 주기 정보" if path == "/api/setup/tier" else "체인 목록")})
        return True
    if path == "/api/setup/tier":
        if not client_allowed(h.client_address[0]):
            h._send(403, {"ok": False, "error": "로컬·테일넷에서만 설정할 수 있습니다"})
            return True
        h._send(200, _tier_view(getattr(h, "path", "") or ""))
        return True
    if path == "/api/setup/chains":
        if not client_allowed(h.client_address[0]):
            h._send(403, {"ok": False, "error": "로컬·테일넷에서만 설정할 수 있습니다"})
            return True
        try:
            import chainoff
            h._send(200, chainoff.summary())
        except Exception as e:
            h._send(200, {"ok": False, "error": why_text(e, "체인 목록")})
        return True
    if DEMO and path in ("/api/state", "/api/v2/state"):
        h._send(200, demo_data.build())
        return True
    if DEMO and path == "/api/futures":
        h._send(200, demo_data.fut_raw())
        return True
    if demo_synth() and path == "/api/coverage_limits":
        try:
            h._send(200, {"ok": True, "data": demo_data.coverage()})
        except Exception as e:
            h._send(200, {"ok": False, "error": why_text(e, "수집 한계")})
        return True
    if path == "/api/day_events" and (DEMO or not os.path.exists(common.DB_PATH)):
        h._send(200, {"ok": True, "n": 0, "counts": {}, "days": {}, "events": [], "hidden": []})
        return True
    if path == "/api/tax_rows" and (DEMO or not os.path.exists(common.DB_PATH)):
        h._send(200, {"ok": True, "total": 0, "rows": []})
        return True
    if path == "/api/curve_hist" and (DEMO or not os.path.exists(common.DB_PATH)):
        h._send(200, {"ok": True, "days": [], "building": False, "progress": {}})
        return True
    if path == "/api/receipt" and (DEMO or not os.path.exists(common.DB_PATH)):
        h._send(200, {"ok": True, "empty": True})
        return True
    if not DEMO and not os.path.exists(common.DB_PATH) and path in ("/api/fut_receipt", "/api/receipt_list", "/api/outflow_candidates"):
        h._send(200, {"ok": True, "empty": True, "n": 0, "items": []} if path != "/api/outflow_candidates" else
                {"ok": True, "empty": True, "total": 0, "totalTok": 0, "totalStable": 0, "shown": 0, "quarN": 0, "cands": []})
        return True
    if path in ("/api/state", "/api/v2/state") and not os.path.exists(common.DB_PATH):
        try:
            cfg = ss.load_config_quiet()
        except Exception:
            cfg = {}
        h._send(200, demo_data.empty(cfg))
        return True
    return False


def _read_body(h):
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        return None
    if n < 0 or n > MAX_BODY:
        return None
    h.connection.settimeout(10)
    try:
        body = json.loads(h.rfile.read(n).decode() or "{}") if n else {}
    except (ValueError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def handle_post(h, path: str) -> bool:
    if not guard(h, "POST"):
        return True
    if DEMO:
        h._send(403, {"ok": False, "error": "데모 모드 — 저장하지 않습니다 (실사용은 TJ_DEMO 없이 실행)"})
        return True
    if not origin_ok(h, required=True):
        h._send(403, {"ok": False, "error": "출처(Origin) 확인 실패 — 같은 화면에서만 요청할 수 있습니다"})
        return True
    tok0 = h.headers.get("X-TJ-CSRF") or ""
    if not tok0 or not hmac.compare_digest(tok0, ss.csrf_token()):
        h._send(403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
        return True
    if not path.startswith("/api/setup/"):
        return False
    if not client_allowed(h.client_address[0]):
        h._send(403, {"ok": False, "error": "로컬·테일넷에서만 설정할 수 있습니다"})
        return True
    if not origin_ok(h, required=True):
        h._send(403, {"ok": False, "error": "출처(Origin) 확인 실패"})
        return True
    tok = h.headers.get("X-TJ-CSRF") or ""
    if not tok or not hmac.compare_digest(tok, ss.csrf_token()):
        h._send(403, {"ok": False, "error": "CSRF 토큰 불일치 — 페이지를 새로고침하세요"})
        return True
    if "application/json" not in (h.headers.get("Content-Type") or ""):
        h._send(415, {"ok": False, "error": "JSON 요청만 받습니다"})
        return True
    body = _read_body(h)
    if body is None:
        h._send(400, {"ok": False, "error": "본문 형식 오류(JSON 객체, 64KB 이하)"})
        return True
    act = path[len("/api/setup/"):]
    if not RL.hit("all", 120, 60):
        h._send(429, {"ok": False, "error": "요청이 너무 많습니다 — 잠시 후 다시"})
        return True
    try:
        res = _dispatch(act, body)
    except ValueError as e:
        res = {"ok": False, "error": common.safe_err(e)}
    except RuntimeError as e:
        res = {"ok": False, "error": scrub(e)}
    except Exception as e:
        log.warning("setup %s 실패: %s", act, scrub(type(e).__name__))
        res = {"ok": False, "error": "저장하다 예상하지 못한 오류가 났어요 — 바뀐 것이 있는지 화면을 새로 고쳐 확인하고, 계속되면 tj-web 로그(pm2 logs tj-web)를 보세요"}
    code = 200 if res.get("ok") else (429 if res.get("rate") else 400)
    h._send(code, res)
    return True


def _perm_record(group: str, rec):
    with ss.LOCK:
        cur = ss.read_settings().get("key_perm")
        kp = dict(cur) if isinstance(cur, dict) else {}
        if rec is None:
            kp.pop(group, None)
        else:
            kp[group] = rec
        ss.update_settings(key_perm=kp or None)


def _limited(key, n, per):
    if not RL.hit(key, n, per):
        return {"ok": False, "rate": True, "error": "테스트를 너무 자주 눌렀습니다 — 1분 뒤 다시"}
    return None


def _dispatch(act: str, b: dict) -> dict:
    if act == "wallets/add":
        import wallet_register
        r = wallet_register.register_wallet(b.get("address"), b.get("chains") or [], b.get("label"), source="setup")
        done = set(_recon_done())
        late = [c for c in r["chains"] if c in done]
        return {"ok": True, "added": r, "reconDone": late}
    if act == "wallets/add_many":
        import wallet_register
        addrs, chains = b.get("addresses"), b.get("chains") or []
        if not (isinstance(addrs, list) and all(isinstance(x, str) for x in addrs)) and not isinstance(addrs, str):
            return {"ok": False, "error": "addresses 는 주소 문자열 배열입니다"}
        if not isinstance(chains, list):
            return {"ok": False, "error": "chains 는 체인 이름 배열입니다"}
        r = wallet_register.register_wallets(addrs, chains, source="setup")
        done = set(_recon_done())
        late = sorted({c for x in r["results"] if x.get("status") == "added" for c in x.get("chains") or [] if c in done})
        return {"ok": True, "results": r["results"], "added": r["added"], "apply": r["apply"], "reconDone": late,
                "max": ss.MAX_BATCH}
    if act == "wallets/check_now":
        import addr_tier
        a = b.get("address")
        if a is not None:
            if not isinstance(a, str) or not a.strip():
                return {"ok": False, "error": "주소 형식이 아닙니다"}
            _k, a, _n = ss.validate_address(a)
        if not RL.hit("check_now", 30, 60):
            return {"ok": False, "rate": True, "error": "너무 자주 눌렀어요 — 1분 뒤 다시"}
        return addr_tier.request_check(a)
    if act == "chains/set":
        import chainoff
        if not RL.hit("chains_set", 20, 60):
            return {"ok": False, "rate": True, "error": "너무 자주 눌렀어요 — 1분 뒤 다시"}
        return chainoff.set_enabled(b.get("chain"), b.get("on"))
    if act == "wallets/remove":
        n = ss.remove_wallet(b.get("address"))
        return {"ok": bool(n), "removed": n, **({} if n else {"error": "없는 주소입니다"})}
    if act == "perp/add":
        r = ss.add_perp(str(b.get("dex") or ""), b.get("address"), b.get("label"))
        return {"ok": True, "added": r}
    if act == "perp/remove":
        n = ss.remove_perp(str(b.get("dex") or ""), b.get("address"))
        return {"ok": bool(n), "removed": n, **({} if n else {"error": "없는 주소입니다"})}
    if act == "wallets/label":
        n = ss.rename_wallet(b.get("address"), b.get("label"))
        return {"ok": bool(n), **({} if n else {"error": "없는 주소입니다"})}
    if act == "keys/nodeplan":
        import nodekeys
        p9 = str(b.get("provider") or "")
        if p9 not in nodekeys.PROVIDERS:
            return {"ok": False, "error": "알 수 없는 서비스"}
        plan9, share9, month9 = b.get("plan"), b.get("share"), b.get("month")
        if plan9 not in ("free", "paid") or (nodekeys.PROVIDERS[p9]["paid_only"] and plan9 != "paid"):
            return {"ok": False, "error": "요금제는 무료·유료 중 하나(QuickNode 는 유료만)"}
        if isinstance(share9, bool) or share9 not in nodekeys.SHARES:
            return {"ok": False, "error": "사용 비율은 10·25·50·80(%) 중 하나만 됩니다"}
        if month9 is not None and (isinstance(month9, bool) or not isinstance(month9, int) or not 0 < month9 <= 10 ** 12):
            return {"ok": False, "error": "월 한도는 1 이상 정수(비우면 무료 한도 기준)"}
        with ss.LOCK:
            cur9 = ss.read_settings()
            np9 = dict(cur9.get(nodekeys.PLANS_KEY) or {}) if isinstance(cur9.get(nodekeys.PLANS_KEY), dict) else {}
            np9[p9] = {"plan": plan9, "share": share9, "month": month9}
            ss.update_settings(**{nodekeys.PLANS_KEY: np9})
        return {"ok": True, "nodes": nodekeys.status(), "apply": _node_apply(p9)}
    if act == "keys/cgshare":
        v = b.get("share")
        if not cgplan.valid_share(v):
            return {"ok": False, "error": "사용 비율은 10·25·50·80(%) 중 하나만 됩니다"}
        cgplan.Store().set_share(v)
        return {"ok": True, "share": v, "cg": _cg_status(ss.env_value(cgplan.ENV_KEY))}
    if act in ("keys/save", "keys/test", "keys/delete"):
        g = str(b.get("group") or "")
        if g not in ss.GROUPS:
            return {"ok": False, "error": "알 수 없는 대상"}
        fields = [k for k, _ in ss.GROUPS[g]["fields"]]
        if act == "keys/delete":
            ss.write_env({k: None for k in fields})
            if g in ss.NODE_GROUPS:
                return {"ok": True, "apply": _node_apply(g)}
            if g in ss.EXCHANGES:
                _perm_record(g, None)
            if g == "coingecko":
                _CG_PROBE.clear()
                try:
                    cgplan.Store().clear()
                except Exception:
                    pass
            return {"ok": True}
        vals_in = b.get("values") if isinstance(b.get("values"), dict) else {}
        bad9 = [k for k in fields if vals_in.get(k) is not None and not isinstance(vals_in.get(k), str)]
        if bad9:
            return {"ok": False, "error": "키 값은 글자로만 넣을 수 있어요"}
        vals = {}
        for k in fields:
            v = str(vals_in.get(k) or "").strip()
            vals[k] = ss.validate_env_value(k, v) if v else ""
        if act == "keys/save" and g in ss.NODE_GROUPS:
            got = {k: v for k, v in vals.items() if v}
            if not got:
                return {"ok": False, "error": "값을 넣으세요"}
            bad = _node_bad(g, got)
            if bad:
                return {"ok": False, "error": bad}
            ss.write_env(got)
            return {"ok": True, "apply": _node_apply(g)}
        if act == "keys/save":
            if not all(vals.values()):
                return {"ok": False, "error": "모든 칸을 채우세요"}
            rec = None
            if g == "coingecko":
                lim = _limited("save:" + g, 8, 60)
                if lim:
                    lim["error"] = "저장을 너무 자주 눌렀습니다 — 1분 뒤 다시"
                    return lim
                key9 = vals[fields[0]]
                r9 = _cg_probe(key9, cached=True)
                if not r9.get("ok") and r9.get("rejected"):
                    return {"ok": False, "error": "CoinGecko 가 이 키를 받지 않았어요 — 저장하지 않았습니다 (" + scrub(r9.get("detail") or "거부", [key9]) + ")"}
                ss.write_env(vals)
                if r9.get("ok"):
                    _cg_record(key9, r9, "save")
                else:
                    try:
                        if cgplan.Store().load(key9) is None:
                            cgplan.Store().clear()
                    except Exception:
                        pass
                try:
                    st9 = _cg_status(key9)
                except Exception:
                    st9 = cgplan.status(None)
                if r9.get("ok"):
                    note9 = {}
                elif r9.get("budget"):
                    note9 = {"note": "지금은 코인게코 호출 몫(공표 한도의 80%)이 없어 확인을 미뤘어요 — 등급(데모·프로)은 몫이 생기면 자동으로 판별해요"}
                else:
                    note9 = {"note": "코인게코 연결을 확인하지 못해 등급(데모·프로)은 첫 조회 때 자동으로 판별해요 — " + scrub(r9.get("detail") or "", [key9])}
                return {"ok": True, "cg": st9, **note9}
            if g in ss.EXCHANGES:
                lim = _limited("save:" + g, 8, 60) if g in PERM_VERIFIABLE else None
                if lim:
                    lim["error"] = "저장을 너무 자주 눌렀습니다 — 1분 뒤 다시"
                    return lim
                blk, rec = perm_gate(g, vals, b.get("readOnlyAck") is True)
                if blk:
                    return blk
            ss.write_env(vals)
            if rec:
                _perm_record(g, rec)
            if g in ss.EXCHANGES:
                try:
                    import depaddr
                    depaddr.request_refresh(g)
                except Exception:
                    pass
            return {"ok": True}
        if g in ss.NODE_GROUPS:
            lim = _limited("test:" + g, 5, 60) or _limited("test:any", 20, 600)
            if lim:
                return lim
            return _node_test(g, {k: v for k, v in vals.items() if v})
        lim = _limited("test:" + g, 5, 60) or _limited("test:any", 20, 600)
        if lim:
            return lim
        stored = ss.read_env()
        vals = {k: (vals[k] or stored.get(k, "")) for k in fields}
        r = test_group(g, vals)
        cg9 = r.pop("_cg", None)
        if g == "coingecko" and cg9 and cg9.get("ok") and vals.get(fields[0]) and vals[fields[0]] == ss.env_value(fields[0]):
            _cg_record(vals[fields[0]], cg9, "test")
        r["detail"] = scrub(r.get("detail") or "", vals.values())
        r["warn"] = [scrub(w, vals.values()) for w in r.get("warn") or []]
        p9 = r.get("perm")
        if isinstance(p9, dict):
            p9["note"] = scrub(p9.get("note") or "", vals.values())
            if p9.get("checked") and p9.get("danger"):
                r["permBlock"] = perm_block_info(g, p9["danger"])
        return {"ok": True, "test": r}
    if act == "depaddr/refresh":
        import depaddr
        ex = str(b.get("exchange") or "")
        env = ss.read_env()
        if ex != "all" and ex not in ss.EXCHANGES:
            return {"ok": False, "error": "알 수 없는 거래소"}
        targets = [e for e in (ss.EXCHANGES if ex == "all" else [ex])
                   if all(env.get(k) for k, _ in ss.EXCHANGES[e]["fields"])]
        if not targets:
            return {"ok": False, "error": "조회 키가 저장된 거래소가 없습니다"}
        lim = _limited("depaddr:" + ex, 4, 60)
        if lim:
            lim["error"] = "새로고침을 너무 자주 눌렀습니다 — 1분 뒤 다시"
            return lim
        for e in targets:
            depaddr.request_refresh(e)
        return {"ok": True, "requested": targets}
    if act == "telegram/validate":
        return _limited("tg", 20, 60) or tg_validate(b.get("token"))
    if act == "telegram/poll":
        return _limited("tgpoll", 90, 60) or tg_poll()
    if act == "telegram/manual":
        return _limited("tg", 20, 60) or tg_manual(b.get("chat_id"), b.get("token") or "")
    if act == "telegram/test":
        return _limited("tg", 20, 60) or tg_test()
    if act == "telegram/disconnect":
        return tg_disconnect()
    if act == "prefs":
        cur = b.get("currency")
        if cur not in ("KRW", "USD"):
            return {"ok": False, "error": "KRW 또는 USD"}
        ss.update_settings(currency=cur)
        return {"ok": True}
    if act == "finish":
        ss.update_settings(onboarded=True)
        return {"ok": True}
    if act == "public_ip":
        lim = _limited("ip", 6, 60)
        if lim:
            return lim
        try:
            code, d = _http(_base("ipify", "https://api.ipify.org") + "/?format=json", timeout=8)
            ip = str((d or {}).get("ip") or "") if isinstance(d, dict) else ""
        except Exception:
            ip = ""
        return {"ok": bool(ip), "ip": ip, **({} if ip else {"error": "공인 IP 조회 실패"})}
    return {"ok": False, "error": "알 수 없는 요청"}


class _DemoSpot:
    updated = 0


class DemoBuilder:
    spot = _DemoSpot()
    daily_px = None

    def __init__(self, webmod=None):
        self.web = webmod

    def build(self):
        return demo_data.build()

    def snapshot(self):
        return None

    def kick_refresh(self):
        return None

    def fut_receipt(self, iso):
        import fut_rcpt
        ev, px = demo_data.fut_fixture()
        names = dict(demo_data.FUT_EXN, **(getattr(self.web, "PERP_NAMES", None) or {}))
        byex = getattr(self.web, "_fut_by_date_ex", None) or demo_data.fut_by_date_ex
        body = fut_rcpt.assemble(iso, demo_data.fut_fev(ev), px, names, byex, int(time.time() * 1000), stale=(), accts={})
        body["builtAt"] = demo_data._day_built()
        return body

    def _fut_view(self):
        v = self.__dict__.get("_fv")
        sb = getattr(self.web, "StateBuilder", None)
        if v is None and sb is not None:
            v = sb.__new__(sb)
            v.fut_receipt = self.fut_receipt
            self._fv = v
        return v

    def fut_chart(self, iso, sym, iv="5m", venue=None, fetch=True, cache_only=False):
        v = self._fut_view()
        if v is None:
            return {"ok": True, "empty": True, "side": "fut", "date": iso, "sym": sym}
        out = v.fut_chart(iso, sym, iv, venue, fetch=False)
        if isinstance(out, dict) and out.get("ok") and not out.get("empty") and out.get("chart") is None and out.get("window"):
            demo_data.fut_candles(out)
        return out

    def chart_request(self, iso, sym, iv="5m", after="1h", venue=None, wait=None, side="sell", bvenue=None):
        if side == "fut":
            return self.fut_chart(iso, sym, iv, venue), "ok"
        return {"ok": False, "error": "데모에는 이 차트가 없어요(합성 데이터)"}, "ok"

    @property
    def _day_idx(self):
        return demo_data.day_idx()

    @property
    def daily(self):
        return demo_data.daily_freeze()

    def prefs(self):
        return {}

    def _last_scan_str(self):
        return "5초 전 스캔"


def demo_main(webmod) -> bool:
    if not DEMO:
        return False
    common.ensure_dirs()
    try:
        cport = (ss.read_config_raw().get("web") or {}).get("port")
    except (OSError, ValueError):
        cport = None
    port = int(os.environ.get("TJ_PORT") or cport or 8023)
    webmod.BUILDER = DemoBuilder(webmod)
    try:
        srv = webmod.QuietHTTPServer(("127.0.0.1", port), webmod.Handler)
    except OSError as e:
        webmod.port_busy_exit(port, e, demo=True)
    log.info("★데모 모드★ http://127.0.0.1:%d/v2/ — 합성 데이터(실지갑 아님), 저장 POST 거부", port)
    def _term9(*_a):
        raise SystemExit(0)
    try:
        import signal as _sig9
        _sig9.signal(_sig9.SIGTERM, _term9)
    except (ValueError, OSError):
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return True
