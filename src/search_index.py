from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone

import common

log = logging.getLogger("tj-web")

KST = timezone(timedelta(hours=9))
DB_NAME = "search.db"
SCHEMA = 2
TX_AGG_V = 2
KINDS = ("coin", "event", "tx", "outflow", "memo", "review", "wallet", "deposit", "nft", "other")
Q_MAX = 200
LIMIT_DEF, LIMIT_MAX = 20, 50
QUERY_BUDGET_S = 0.8
TICK_S = 20.0
FULL_EVERY_S = 6 * 3600
BATCH = 800
BATCH_SLEEP = 0.03
NFT_EVERY_S = 600
TX_RESCAN_S = 300
IA_SAVE_S = 300
TYPES = ("swap", "buy", "sell", "deposit", "withdraw", "lp", "gas", "transfer")

KO_ALIAS = {
    "비트코인": "BTC", "이더리움": "ETH", "솔라나": "SOL", "리플": "XRP", "테더": "USDT", "유에스디코인": "USDC", "바이낸스코인": "BNB",
    "도지코인": "DOGE", "도지": "DOGE", "에이다": "ADA", "카르다노": "ADA", "트론": "TRX", "아발란체": "AVAX", "체인링크": "LINK", "폴카닷": "DOT",
    "폴리곤": "POL", "라이트코인": "LTC", "비트코인캐시": "BCH", "시바이누": "SHIB", "유니스왑": "UNI", "니어": "NEAR", "앱토스": "APT",
    "수이": "SUI", "아비트럼": "ARB", "옵티미즘": "OP", "스텔라루멘": "XLM", "이더리움클래식": "ETC", "코스모스": "ATOM", "페페": "PEPE",
    "톤코인": "TON", "헤데라": "HBAR", "하이퍼리퀴드": "HYPE", "월드코인": "WLD", "세이": "SEI", "봉크": "BONK",
}
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def choseong(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            out.append(_CHO[(o - 0xAC00) // 588])
        else:
            out.append(ch)
    return "".join(out)


_CHO_ALIAS = {}
for _k, _v in KO_ALIAS.items():
    _CHO_ALIAS.setdefault(choseong(_k), _v)

CHAIN_NAME_FALLBACK = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism", "polygon": "Polygon",
                       "bsc": "BSC", "sol": "Solana", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis"}

_TX_TYPE = {"SWAP": "swap", "CONVERT": "swap", "EX_BUY": "buy", "EXF_BUY": "buy", "EX_SELL": "sell", "EXF_SELL": "sell",
            "TRANSFER_IN": "deposit", "PROGRAM_IN": "deposit", "STAKE_REWARD": "deposit", "EX_DEPOSIT": "deposit", "EXF_DEPOSIT": "deposit",
            "TRANSFER_OUT": "withdraw", "TRANSFER_OUT_EX": "withdraw", "EX_WITHDRAW": "withdraw", "EXF_WITHDRAW": "withdraw",
            "LP_ADD": "lp", "LP_REMOVE": "lp", "LP_ADJUST": "lp", "FAILED": "gas", "NOOP": "gas",
            "TRANSFER_SELF": "transfer", "BRIDGE": "transfer"}
_TX_KO = {"swap": "스왑", "buy": "매수", "sell": "매도", "deposit": "받음", "withdraw": "보냄", "lp": "LP", "gas": "가스·실패", "transfer": "내 지갑 이동"}
_TX_PRIO = ("SWAP", "CONVERT", "LP_ADD", "LP_REMOVE", "LP_ADJUST", "BRIDGE", "TRANSFER_OUT_EX", "TRANSFER_OUT", "TRANSFER_SELF",
            "TRANSFER_IN", "PROGRAM_IN", "STAKE_REWARD", "FAILED", "NOOP")


def db_path() -> str:
    return os.path.join(common.STATE_DIR, DB_NAME)


def _demo() -> bool:
    return os.environ.get("TJ_DEMO") == "1"


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _hm(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), KST).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _short(s: str) -> str:
    s = str(s or "")
    return s if len(s) <= 14 else s[:6] + "…" + s[-4:]


def _num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


_USD_RE = re.compile(r"[-−]?\$\s?([\d,]+(?:\.\d+)?)")


def _usd_of(a) -> float | None:
    m = _USD_RE.search(str(a or ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return -v if str(a).lstrip().startswith(("-", "−")) else v


def _addr_norm(a: str) -> str:
    a = str(a or "").strip()
    return a.lower() if a.lower().startswith("0x") else a


def _sig(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _ev_type(k: str, d: str) -> str:
    k, d = str(k or ""), str(d or "")
    if "LP" in k or "유동성" in k:
        return "lp"
    if "매수" in k:
        return "swap" if "스왑" in d else "buy"
    if "매도" in k:
        return "swap" if "스왑" in d else "sell"
    if "입금" in k:
        return "deposit"
    if "외부 전송" in k:
        return "withdraw"
    if "전송" in k:
        if "→ 외부" in d or "보낸 내역" in d:
            return "withdraw"
        return "transfer"
    if "가스" in k or "가스" in d[:12]:
        return "gas"
    return "transfer"


_DDL = [
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
    """CREATE TABLE IF NOT EXISTS docs (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE, grp TEXT NOT NULL,
        title TEXT NOT NULL, sub TEXT, body TEXT, date TEXT, ts INTEGER, usd REAL, pnl REAL,
        sym TEXT, sym_u TEXT, chain TEXT, chain_l TEXT, etype TEXT, addr TEXT, addr_l TEXT, tx TEXT, tx_l TEXT,
        anc TEXT, spam INTEGER NOT NULL DEFAULT 0, syms TEXT, chains TEXT)""",
    "CREATE INDEX IF NOT EXISTS docs_grp ON docs(grp)",
    "CREATE INDEX IF NOT EXISTS docs_kind_ts ON docs(kind, ts)",
    "CREATE INDEX IF NOT EXISTS docs_addr ON docs(addr_l)",
    "CREATE INDEX IF NOT EXISTS docs_tx ON docs(tx_l)",
    "CREATE INDEX IF NOT EXISTS docs_sym ON docs(sym_u)",
    "CREATE INDEX IF NOT EXISTS docs_date ON docs(date)",
]
_COLS = ("kind", "key", "grp", "title", "sub", "body", "date", "ts", "usd", "pnl", "sym", "sym_u", "chain", "chain_l", "etype",
         "addr", "addr_l", "tx", "tx_l", "anc", "spam", "syms", "chains")


def _row(d) -> dict:
    d = dict(d)
    sy = [str(x).strip() for x in (d.get("syms") or ([d["sym"]] if d.get("sym") else [])) if x and str(x).strip()]
    chs = [str(x).strip() for x in (d.get("chains") or ([d["chain"]] if d.get("chain") else [])) if x and str(x).strip()]
    d["sym_u"] = str(d.get("sym") or "").upper() or None
    d["chain_l"] = str(d.get("chain") or "").lower() or None
    d["addr_l"] = _addr_norm(d.get("addr")) or None
    d["tx_l"] = _addr_norm(d.get("tx")) or None
    d["spam"] = 1 if d.get("spam") else 0
    d["syms"] = (" " + " ".join(dict.fromkeys(x.upper() for x in sy)) + " ") if sy else None
    d["chains"] = (" " + " ".join(dict.fromkeys(x.lower() for x in chs)) + " ") if chs else None
    return d


def fts_supported() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        try:
            c.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
            return True
        finally:
            c.close()
    except sqlite3.Error:
        return False


class Index:

    def __init__(self, path=None, sleep=time.sleep):
        self.path = path or db_path()
        self.sleep = sleep
        self.conn = None
        self.fts = False
        self.writes = 0

    def _precreate(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def open(self):
        if self.conn is not None:
            return self.conn
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._precreate()
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        v = None
        try:
            r = c.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
            v = r[0] if r else None
        except sqlite3.Error:
            v = None
        if v is not None and str(v) != str(SCHEMA):
            c.close()
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.remove(self.path + sfx)
                except OSError:
                    pass
            self._precreate()
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL")
        for d in _DDL:
            c.execute(d)
        self.fts = fts_supported()
        if self.fts:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(title, sub, body, tokenize='trigram')")
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('schema', ?)", (str(SCHEMA),))
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('fts', ?)", ("1" if self.fts else "0",))
        c.commit()
        for p9 in (self.path, self.path + "-wal", self.path + "-shm"):
            try:
                os.chmod(p9, 0o600)
            except OSError:
                pass
        self.conn = c
        return c

    def meta_get(self, k, dflt=None):
        r = self.open().execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else dflt

    def meta_set(self, k, v):
        self.writes += 1
        c = self.open()
        c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, None if v is None else str(v)))
        c.commit()

    def meta_del_prefix(self, p):
        c = self.open()
        c.execute("DELETE FROM meta WHERE k >= ? AND k < ?", (p, p + "￿"))
        c.commit()

    def _del_where(self, where, args):
        self.writes += 1
        c = self.open()
        if self.fts:
            c.execute(f"DELETE FROM fts WHERE rowid IN (SELECT id FROM docs WHERE {where})", args)
        c.execute(f"DELETE FROM docs WHERE {where}", args)

    def replace_groups(self, grps, docs):
        c = self.open()
        grps = list(grps)
        for i in range(0, len(grps), 400):
            part = grps[i:i + 400]
            self._del_where("grp IN (%s)" % ",".join("?" * len(part)), part)
        c.commit()
        self._insert(docs)

    def replace_keys(self, keys, docs):
        c = self.open()
        keys = list(keys)
        for i in range(0, len(keys), 400):
            part = keys[i:i + 400]
            self._del_where("key IN (%s)" % ",".join("?" * len(part)), part)
        c.commit()
        self._insert(docs)

    def clear_kind(self, kind):
        self._del_where("kind = ?", (kind,))
        self.open().commit()

    def _insert(self, docs):
        self.writes += 1
        c = self.open()
        rows = []
        uniq = {}
        for d in docs:
            uniq[d["key"]] = d
        for d in uniq.values():
            d = _row(d)
            rows.append(tuple(d.get(k) for k in _COLS))
        for i in range(0, len(rows), BATCH):
            part = rows[i:i + BATCH]
            for r in part:
                cur = c.execute("INSERT OR REPLACE INTO docs (%s) VALUES (%s)" % (",".join(_COLS), ",".join("?" * len(_COLS))), r)
                if self.fts:
                    c.execute("INSERT INTO fts (rowid, title, sub, body) VALUES (?, ?, ?, ?)", (cur.lastrowid, r[3] or "", r[4] or "", r[5] or ""))
            c.commit()
            if len(rows) > BATCH:
                self.sleep(BATCH_SLEEP)

    def count(self):
        return self.open().execute("SELECT count(*) FROM docs").fetchone()[0]


def docs_events(day_ix: dict, pos_pnl: dict, chain_names: dict, iso: str):
    out = []
    seen = {}
    for ts, kind, e, meta in day_ix.get(iso) or ():
        if not isinstance(e, dict):
            continue
        sym = str((meta[1] if meta else None) or e.get("sym") or "")
        k = str(e.get("k") or "")
        d = str(e.get("d") or "")
        a = e.get("a")
        src = str(e.get("src") or "")
        chain = str((meta[2] if meta else None) or (d.split(" · ", 1)[0] if " · " in d else "") or "")
        txs = str(e.get("tx") or "")
        txs = "" if txs in ("—", "-") else txs
        h = hashlib.sha1("|".join((k, d, str(e.get("q")), str(a), txs, src, sym)).encode()).hexdigest()[:10]
        base = f"ev:{iso}:{int(ts)}:{h}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        key = base if not n else f"{base}:{n}"
        pnl = None
        if meta and "매도" in k:
            rbd = pos_pnl.get(meta[0]) or {}
            pnl = _num(rbd.get(iso))
        addr = src[2:] if src.startswith("w:") else ""
        exl = src[3:] if src.startswith("ex:") else ""
        sub = " · ".join(x for x in (_hm(ts), d, (str(e.get("q")) + " " + sym) if e.get("q") else "", _short(addr) if addr else exl) if x)
        out.append({"kind": "event", "key": key, "grp": "ev:" + iso, "title": (sym + " " + k).strip(), "sub": sub,
                    "body": " ".join(x for x in (txs, str(e.get("symRaw") or ""), str(e.get("hide") or "")) if x),
                    "date": iso, "ts": int(ts), "usd": _usd_of(a), "pnl": pnl, "sym": sym or None, "chain": chain or None,
                    "etype": _ev_type(k, d), "addr": addr or None, "tx": txs or None, "anc": "evday:" + iso,
                    "spam": kind == "hidden"})
    return out


_EV_SIG_KEYS = ("k", "d", "a", "q", "tx", "src", "sym", "symRaw", "hide", "hideKind")


def _day_sig(rows, pos_pnl=None, iso="") -> str:
    parts = []
    for ts, kind, e, meta in rows or ():
        e = e if isinstance(e, dict) else {}
        pnl = ""
        if meta and "매도" in str(e.get("k") or "") and pos_pnl is not None:
            pnl = str((pos_pnl.get(meta[0]) or {}).get(iso))
        parts.append("\x1e".join([str(ts), str(kind)] + [str(e.get(k9)) for k9 in _EV_SIG_KEYS] + [str(meta), pnl]))
    raw = "\x1f".join(parts).encode("utf-8", "replace")
    return f"{len(parts)}:{zlib.crc32(raw):08x}:{len(raw)}"


def docs_state(fields: dict, chain_names: dict):
    out = {"coin": [], "outflow": [], "wallet": [], "deposit": []}
    by = {}
    for c in fields.get("coins") or ():
        if not isinstance(c, dict):
            continue
        sym = str(c.get("sym") or "").strip()
        if not sym:
            continue
        g = by.setdefault(sym.upper(), {"sym": sym, "names": [], "chains": set(), "qty": 0.0, "val": 0.0, "guard": 0})
        nm = str(c.get("name") or "")
        if nm and nm not in g["names"] and len(g["names"]) < 6:
            g["names"].append(nm)
        if " · " in nm:
            g["chains"].add(nm.split(" · ", 1)[1])
        g["qty"] += _num(c.get("qty")) or 0
        g["val"] += (_num(c.get("qty")) or 0) * (_num(c.get("price")) or 0)
        g["guard"] |= 1 if c.get("guard") else 0
    try:
        import spamguard as _sg
    except Exception:
        _sg = None
    for su, g in by.items():
        try:
            sp = bool(_sg and (_sg.odd_symbol(g["sym"]) or _sg.impostor_of(g["sym"])))
        except Exception:
            sp = False
        ch = sorted(g["chains"])
        out["coin"].append({"kind": "coin", "key": "coin:" + su, "grp": "st:coin", "title": g["sym"],
                            "sub": " · ".join(x for x in (" · ".join(ch[:3]) + (f" 외 {len(ch) - 3}곳" if len(ch) > 3 else ""),
                                                          "보유" if g["val"] >= 1 else ("보유 0 · 기록만" if g["qty"] <= 0 else "소액·시세 없음")) if x),
                            "body": " ".join(g["names"]), "sym": g["sym"], "chain": ch[0] if len(ch) == 1 else None,
                            "anc": "coin:" + su, "spam": sp, "usd": None, "chains": ch})
    for r in fields.get("outflows") or ():
        if not isinstance(r, dict) or not r.get("address"):
            continue
        a = str(r["address"])
        toks = [str(t.get("sym") or "") for t in (r.get("tokens") or ()) if isinstance(t, dict)]
        chs = [str(x) for x in (r.get("chainNames") or ())]
        nm = str(r.get("alias") or "")
        title = (nm + " " if nm else "") + (_short(a) if not a.startswith("wd:") else "주소 미상 출금")
        out["outflow"].append({"kind": "outflow", "key": "of:" + a, "grp": "st:outflow", "title": title.strip(),
                               "sub": " · ".join(x for x in (" · ".join(chs[:3]), " ".join(toks[:4]), f"{int(r.get('count') or 0)}건",
                                                             str(r.get("last") or "")) if x),
                               "body": " ".join(x for x in (str(r.get("memo") or ""), str(r.get("exchange") or ""), " ".join(toks)) if x),
                               "date": str(r.get("last") or "")[:10] or None, "ts": int(r.get("lastTs") or 0) or None,
                               "usd": _num(r.get("usdAtSend")), "sym": toks[0] if len(toks) == 1 else None,
                               "chain": chs[0] if len(chs) == 1 else None, "etype": "withdraw",
                               "addr": None if a.startswith("wd:") else a, "anc": "outflow:" + a,
                               "spam": bool(r.get("dust")) or str(r.get("status") or "") == "spam",
                               "syms": toks, "chains": chs + [str(x) for x in (r.get("chains") or ())]})
    for w in fields.get("walletRows") or ():
        if not isinstance(w, dict) or not w.get("addr"):
            continue
        a = str(w["addr"])
        out["wallet"].append({"kind": "wallet", "key": "w:" + _addr_norm(a), "grp": "st:wallet",
                              "title": (str(w.get("alias") or "") + " " + _short(a)).strip(), "sub": str(w.get("chains") or ""),
                              "body": "지갑 " + str(w.get("alias") or ""), "addr": a, "anc": None})
    for d in fields.get("depositRows") or ():
        if not isinstance(d, dict) or not d.get("addr"):
            continue
        a = str(d["addr"])
        memo = str(d.get("memo") or "")
        out["deposit"].append({"kind": "deposit", "key": "dep:" + str(d.get("ex")) + ":" + _addr_norm(a) + ":" + memo, "grp": "st:deposit",
                               "title": f"{d.get('ex') or ''} 입금 주소 {_short(a)}".strip(),
                               "sub": " · ".join(x for x in (str(d.get("net") or ""), ("메모 " + memo) if memo and memo != "—" else "") if x),
                               "body": "입금 주소 " + str(d.get("ex") or ""), "addr": a, "anc": None})
    return out


def docs_memos(state_dir: str, today_iso: str):
    out = []
    try:
        with open(os.path.join(state_dir, "day_memos.json"), encoding="utf-8") as f:
            dm = (json.load(f) or {}).get("memos") or {}
    except (OSError, ValueError, AttributeError):
        dm = {}
    lo = _iso_shift(today_iso, -364)
    for k, v in dm.items() if isinstance(dm, dict) else ():
        if not isinstance(v, dict) or "|" not in str(k):
            continue
        iso, sym = str(k).split("|", 1)
        memo = str(v.get("memo") or "")
        if not memo:
            continue
        out.append({"kind": "memo", "key": "dm:" + str(k), "grp": "f:memo", "title": f"{sym} 매매 근거 · {iso[5:].replace('-', '/')}",
                    "sub": memo[:120], "body": memo, "date": iso, "ts": int(v.get("at") or 0) or None, "sym": sym,
                    "anc": ("day:" + iso[5:]) if iso >= lo else ("evday:" + iso)})
    try:
        with open(os.path.join(state_dir, "ui_prefs.json"), encoding="utf-8") as f:
            plans = (json.load(f) or {}).get("plans") or {}
    except (OSError, ValueError, AttributeError):
        plans = {}
    for k, v in plans.items() if isinstance(plans, dict) else ():
        memo = str((v or {}).get("memo") or "") if isinstance(v, dict) else ""
        if not memo:
            continue
        sym = str(k).split(":", 1)[-1] if ":" in str(k) else str(k)
        out.append({"kind": "memo", "key": "pm:" + str(k), "grp": "f:memo", "title": f"{sym} 계획 메모", "sub": memo[:120], "body": memo,
                    "sym": sym, "anc": "coin:" + sym.upper()})
    return out


def _iso_shift(iso: str, days: int) -> str:
    try:
        return (datetime.strptime(iso, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "0000-00-00"


def docs_reviews(state_dir: str, today_iso: str, rbd: dict):
    out = []
    lo = _iso_shift(today_iso, -364)

    def rd(name):
        try:
            with open(os.path.join(state_dir, name), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
    for k, v in rd("reviews_llm.json").items():
        if not isinstance(v, dict):
            continue
        iso = str(v.get("iso") or k)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
            continue
        txt = [str(v.get("sum") or ""), str(v.get("note") or "")] + [str(x) for x in (v.get("obs") or []) if x] + [str(v.get("next") or "")]
        body = " ".join(t for t in txt if t)
        if not body.strip():
            continue
        out.append({"kind": "review", "key": "rv:" + iso, "grp": "f:review", "title": f"{int(iso[5:7])}월 {int(iso[8:10])}일 일간 리뷰" + (f" · {v.get('s')}" if v.get("s") else ""),
                    "sub": str(v.get("note") or v.get("sum") or "")[:140], "body": body, "date": iso, "ts": int(v.get("at") or 0) or None,
                    "pnl": _num((rbd or {}).get(iso)), "anc": ("day:" + iso[5:]) if iso >= lo else None})
    for k, v in rd("reviews_llm_weekly.json").items():
        if not isinstance(v, dict):
            continue
        fr, to = str(v.get("from") or ""), str(v.get("to") or "")
        txt = [str(v.get("sum") or ""), str(v.get("note") or ""), str(v.get("rule") or ""), str(v.get("next") or "")] + \
              [str((p or {}).get("text") if isinstance(p, dict) else p) for p in (v.get("patterns") or [])]
        body = " ".join(t for t in txt if t and t != "None")
        if not body.strip():
            continue
        iso = to if re.fullmatch(r"\d{4}-\d{2}-\d{2}", to) else None
        out.append({"kind": "review", "key": "rw:" + str(k), "grp": "f:review",
                    "title": f"주간 리뷰 {fr[5:].replace('-', '/')}–{to[5:].replace('-', '/')}" + (f" · {v.get('s')}" if v.get("s") else ""),
                    "sub": str(v.get("note") or v.get("sum") or "")[:140], "body": body, "date": iso, "ts": int(v.get("at") or 0) or None,
                    "anc": ("day:" + iso[5:]) if iso and iso >= lo else None})
    return out


def docs_other(state_dir: str):
    out = []
    try:
        with open(os.path.join(state_dir, "other_assets.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return out
    for it in (d or {}).get("items") or () if isinstance(d, dict) else ():
        if not isinstance(it, dict) or not it.get("id"):
            continue
        name = str(it.get("name") or "")
        cat = str(it.get("cat") or it.get("kind") or "")
        out.append({"kind": "other", "key": "oa:" + str(it["id"]), "grp": "f:other", "title": name or "(이름 없음)",
                    "sub": " · ".join(x for x in (cat, str(it.get("ticker") or it.get("code") or "")) if x),
                    "body": " ".join(x for x in (name, cat, str(it.get("ticker") or it.get("code") or ""), "부채" if it.get("liab") else "") if x),
                    "anc": "other:" + str(it["id"])})
    return out


def docs_nft(view: dict):
    out = []
    if not isinstance(view, dict):
        return out

    def add(r, grp_label, spam=False):
        if not isinstance(r, dict) or not r.get("key"):
            return
        nm = str(r.get("name") or r.get("sym") or r.get("key"))
        out.append({"kind": "nft", "key": "nft:" + str(r["key"]), "grp": "nft", "title": nm,
                    "sub": " · ".join(x for x in (str(r.get("chain") or ""), grp_label, (f"{r.get('count')}개" if r.get("count") else "")) if x),
                    "body": " ".join(x for x in (nm, str(r.get("sym") or ""), str(r.get("chain") or "")) if x),
                    "sym": r.get("sym"), "chain": r.get("chain"), "anc": "nft:" + str(r["key"]), "spam": spam})
    for r in view.get("tracked") or ():
        add(r, "추적 중")
    for r in view.get("candidates") or ():
        add(r, "후보")
    for r in view.get("watch") or ():
        add(r, "관심")
    for r in ((view.get("spam") or {}).get("items") or ()) if isinstance(view.get("spam"), dict) else ():
        add(r, "스팸", True)
    for r in view.get("hidden") or ():
        add(r, "숨김", True)
    return out


def ledger_tx_docs(conn, chain_names: dict, only=None):
    cn = chain_names or CHAIN_NAME_FALLBACK
    q = ("SELECT p.source_ns, p.source_id, MIN(p.event_ts), group_concat(DISTINCT a.symbol), group_concat(DISTINCT p.event), "
         "group_concat(DISTINCT p.location), SUM(CASE WHEN p.leg_kind='acq' THEN CAST(p.cost_usd AS REAL) END), "
         "SUM(CASE WHEN p.leg_kind='disp' THEN CAST(p.cost_usd AS REAL) END), SUM(CASE WHEN p.cost_usd IS NULL THEN 0 ELSE 1 END), "
         "SUM(CASE WHEN p.leg_kind='move_in' AND p.location LIKE 'out:%' THEN CAST(p.cost_usd AS REAL) END), "
         "SUM(CASE WHEN p.leg_kind='gas' THEN CAST(p.cost_usd AS REAL) END) "
         "FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.source_kind = 'chain_tx'")
    args = []
    if only is not None:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _sq (ns TEXT, id TEXT)")
        conn.execute("DELETE FROM _sq")
        conn.executemany("INSERT INTO _sq VALUES (?, ?)", list(only))
        q += " AND (p.source_ns, p.source_id) IN (SELECT ns, id FROM _sq)"
    q += " GROUP BY p.source_ns, p.source_id"
    out = []
    for ns, sid, ts, syms, evs, locs, acq, disp, ncost, mvout, gas in conn.execute(q, args):
        sid = str(sid or "")
        if not sid:
            continue
        ev_l = [x for x in str(evs or "").split(",") if x]
        main = next((x for x in _TX_PRIO if x in ev_l), ev_l[0] if ev_l else "")
        et = _TX_TYPE.get(main, "transfer")
        sy = [x for x in str(syms or "").split(",") if x][:12]
        wal = ""
        for loc in str(locs or "").split(","):
            p9 = loc.split(":")
            if len(p9) >= 3 and p9[0] == "wallet":
                wal = p9[2]
                break
        usd = max(abs(acq or 0), abs(disp or 0), abs(mvout or 0)) or (abs(gas) if gas else None)
        spam = bool(set(ev_l) <= {"PROGRAM_IN", "TRANSFER_IN"} and not ncost)
        chn = cn.get(ns, ns)
        hsh = sid.split(":", 1)[0] if ":" in sid and not sid.startswith("0x") else sid
        iso = _iso(ts)
        out.append({"kind": "tx", "key": f"tx:{ns}:{sid}", "grp": "tx:" + str(ns), "title": "tx " + _short(hsh),
                    "sub": " · ".join(x for x in (_hm(ts), _TX_KO.get(et, et), " ".join(sy[:3]), chn) if x),
                    "body": " ".join(x for x in (" ".join(sy), " ".join(ev_l), chn) if x),
                    "date": iso, "ts": int(ts or 0) or None, "usd": usd, "sym": sy[0] if len(sy) == 1 else None, "chain": ns, "etype": et,
                    "addr": wal or None, "tx": hsh, "anc": ("evday:" + iso) if iso else None, "spam": spam,
                    "syms": sy, "chains": [ns, chn]})
    return out


def _realized_total(fields) -> dict:
    out = {}
    if not isinstance(fields, dict):
        return out
    fut = (fields.get("futures") or {}).get("realizedByDate") if isinstance(fields.get("futures"), dict) else None
    for src in (fields.get("realizedByDate") or {}, fut or {}):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            x = _num(v)
            if x is not None and len(str(k)) == 10:
                out[str(k)] = round(out.get(str(k), 0.0) + x, 2)
    return out


class Indexer:
    def __init__(self, state_fn=None, nft_fn=None, chain_names=None, path=None, ledger_path=None, sleep=time.sleep, clock=time.time):
        self.state_fn, self.nft_fn = state_fn, nft_fn
        self.cn = chain_names or CHAIN_NAME_FALLBACK
        self.ix = Index(path, sleep=sleep)
        self.ledger_path = ledger_path or common.DB_PATH
        self.sleep, self.clock = sleep, clock
        self.mu = threading.Lock()
        self.done_first = False
        self.last_full = 0.0
        self.last_nft = 0.0
        self.indexed_at = 0
        self._last_out = None
        self._last_dix = None
        self._tx_fsig = None
        self._tx_pending = False
        self._tx_rescan_at = 0.0
        self._ia_saved = 0.0

    def feed_state(self, out, dix):
        if isinstance(out, dict) and out is not self._last_out:
            f = out.get("fields") or {}
            ds = docs_state(f, self.cn)
            for kind, docs in ds.items():
                s = _sig([(d["key"], d.get("title"), d.get("sub"), d.get("body"), d.get("usd"), d.get("spam")) for d in docs])
                if self.ix.meta_get("sig:st:" + kind) != s:
                    self.ix.replace_groups(["st:" + kind], docs)
                    self.ix.meta_set("sig:st:" + kind, s)
            self._last_out = out
        if isinstance(dix, dict) and dix is not self._last_dix and isinstance(dix.get("ix"), dict):
            ix = dix["ix"]
            pos_pnl = {}
            for p in dix.get("pos") or ():
                if isinstance(p, dict) and p.get("key"):
                    pos_pnl[str(p["key"])] = p.get("realizedByDay") or {}
            have = {k[len("sig:ev:"):]: v for k, v in self.ix.open().execute("SELECT k, v FROM meta WHERE k >= 'sig:ev:' AND k < 'sig:ev:￿'")}
            days = sorted(ix.keys(), reverse=True)
            for iso in days:
                s = _day_sig(ix.get(iso), pos_pnl, iso)
                if have.get(iso) == s:
                    continue
                self.ix.replace_groups(["ev:" + iso], docs_events(ix, pos_pnl, self.cn, iso))
                self.ix.meta_set("sig:ev:" + iso, s)
            gone = [d for d in have if d not in ix]
            if gone:
                self.ix.replace_groups(["ev:" + d for d in gone], [])
                for d in gone:
                    self.ix.meta_set("sig:ev:" + d, None)
                self.ix.open().execute("DELETE FROM meta WHERE k IN (%s)" % ",".join("?" * len(gone)), ["sig:ev:" + d for d in gone])
                self.ix.open().commit()
            self._last_dix = dix

    def feed_files(self, today_iso, rbd):
        sd = os.path.dirname(self.ix.path)
        for kind, names, fn in (("memo", ("day_memos.json", "ui_prefs.json"), lambda: docs_memos(sd, today_iso)),
                                ("review", ("reviews_llm.json", "reviews_llm_weekly.json"), lambda: docs_reviews(sd, today_iso, rbd)),
                                ("other", ("other_assets.json",), lambda: docs_other(sd))):
            st = []
            for n in names:
                try:
                    s9 = os.stat(os.path.join(sd, n))
                    st.append([n, int(s9.st_mtime_ns), s9.st_size])
                except OSError:
                    st.append([n, 0, 0])
            s = _sig([st, today_iso[:7], sorted((rbd or {}).items()) if kind == "review" else None])
            if self.ix.meta_get("sig:f:" + kind) != s:
                self.ix.replace_groups(["f:" + kind], fn())
                self.ix.meta_set("sig:f:" + kind, s)

    def feed_nft(self):
        if not self.nft_fn or self.clock() - self.last_nft < NFT_EVERY_S:
            return
        self.last_nft = self.clock()
        try:
            v = self.nft_fn()
        except Exception as e:
            log.warning("검색 색인: NFT 보기 실패(무시): %s", type(e).__name__)
            return
        docs = docs_nft(v)
        s = _sig([(d["key"], d["title"], d["sub"], d["spam"]) for d in docs])
        if self.ix.meta_get("sig:nft") != s:
            self.ix.replace_groups(["nft"], docs)
            self.ix.meta_set("sig:nft", s)

    _TX_DOC_COLS = ("title", "sub", "body", "date", "ts", "usd", "sym", "chain", "etype", "addr", "tx", "anc", "spam", "syms", "chains")

    @staticmethod
    def _ltot(lc, where="", args=()):
        r = lc.execute("SELECT count(*), total(CAST(cost_usd AS REAL)), total(cost_usd IS NULL) FROM postings "
                       "WHERE source_kind = 'chain_tx' " + where, args).fetchone()
        return [int(r[0] or 0), round(float(r[1] or 0), 6), int(r[2] or 0)]

    @staticmethod
    def _atot(lc):
        r = lc.execute("SELECT count(*), total(length(symbol)), total(symbol IS NULL) FROM assets").fetchone()
        return [int(r[0] or 0), int(r[1] or 0), int(r[2] or 0)]

    def _tx_rescan(self, lc):
        docs = {d["key"]: d for d in ledger_tx_docs(lc, self.cn)}
        cur = {}
        for row in self.ix.open().execute("SELECT key, %s FROM docs WHERE kind = 'tx'" % ", ".join(self._TX_DOC_COLS)):
            cur[row[0]] = row[1:]
        chg = []
        for k, d in docs.items():
            r9 = _row(d)
            v = tuple(r9.get(c9) for c9 in self._TX_DOC_COLS)
            if cur.get(k) != v:
                chg.append(d)
        gone = [k for k in cur if k not in docs]
        if chg or gone:
            self.ix.replace_keys([d["key"] for d in chg] + gone, chg)
        return len(chg), len(gone)

    def feed_ledger(self):
        lp = self.ledger_path
        if not os.path.exists(lp):
            return
        try:
            st0 = os.stat(lp)
            ino = str(st0.st_ino)
            try:
                stw = os.stat(lp + "-wal")
                wsig = (stw.st_mtime_ns, stw.st_size)
            except OSError:
                wsig = (0, 0)
            fsig = (ino, st0.st_mtime_ns, st0.st_size) + wsig
        except OSError:
            return
        now = self.clock()
        if fsig == self._tx_fsig and not (self._tx_pending and now - self._tx_rescan_at >= TX_RESCAN_S):
            return
        lc = sqlite3.connect(f"file:{lp}?mode=ro", uri=True, timeout=10)
        try:
            lc.execute("BEGIN")
            try:
                last = json.loads(self.ix.meta_get("tx:agg") or "null")
            except ValueError:
                last = None
            mx = int(lc.execute("SELECT max(posting_id) FROM postings WHERE source_kind = 'chain_tx'").fetchone()[0] or 0)
            atot = self._atot(lc)
            full = (not isinstance(last, dict) or last.get("ino") != ino or mx < int(last.get("mx") or 0)
                    or last.get("v") != TX_AGG_V)
            if not full:
                l_mx = int(last.get("mx") or 0)
                old = self._ltot(lc, "AND posting_id <= ?", (l_mx,))
                if old[0] < int((last.get("tot") or [0])[0]):
                    full = True
            if full:
                docs = ledger_tx_docs(lc, self.cn)
                self.ix.clear_kind("tx")
                self.ix._insert(docs)
                self._tx_pending, self._tx_rescan_at = False, now
            else:
                same_old = old == list(last.get("tot") or []) and atot == list(last.get("atot") or [])
                if mx > l_mx:
                    srcs = [tuple(r) for r in lc.execute("SELECT DISTINCT source_ns, source_id FROM postings WHERE source_kind = 'chain_tx' AND posting_id > ?", (l_mx,))]
                    docs = ledger_tx_docs(lc, self.cn, only=srcs)
                    self.ix.replace_keys([f"tx:{ns}:{sid}" for ns, sid in srcs], docs)
                if not same_old:
                    self._tx_pending = True
                if self._tx_pending and now - self._tx_rescan_at >= TX_RESCAN_S:
                    self._tx_rescan(lc)
                    self._tx_pending, self._tx_rescan_at = False, now
                elif self._tx_pending:
                    self.ix.meta_set("tx:agg", json.dumps(dict(last, mx=mx, v=TX_AGG_V)))
                    self._tx_fsig = fsig
                    return
            self.ix.meta_set("tx:agg", json.dumps({"ino": ino, "mx": mx, "tot": self._ltot(lc, "AND posting_id <= ?", (mx,)), "atot": atot, "v": TX_AGG_V}))
            self._tx_fsig = fsig
        finally:
            lc.close()

    def tick(self):
        with self.mu:
            now = self.clock()
            if now - self.last_full >= FULL_EVERY_S:
                if self.last_full:
                    self.ix.open().execute("DELETE FROM meta WHERE k LIKE 'sig:%' OR k IN ('tx:last', 'tx:agg')")
                    self.ix.open().commit()
                    self._last_out = self._last_dix = None
                    self._tx_fsig = None
                self.last_full = now
            out = dix = None
            if self.state_fn:
                try:
                    out, dix = self.state_fn()
                except Exception as e:
                    log.warning("검색 색인: 상태 읽기 실패(무시): %s", type(e).__name__)
            w0 = self.ix.writes
            today = (out or {}).get("todayIso") if isinstance(out, dict) else None
            today = today or datetime.now(KST).strftime("%Y-%m-%d")
            rbd = _realized_total((out or {}).get("fields") if isinstance(out, dict) else None)
            self.feed_files(today, rbd)
            self.feed_nft()
            if isinstance(out, dict):
                self.feed_state(out, None)
            if isinstance(dix, dict):
                self.feed_state(None, dix)
            self.feed_ledger()
            self.indexed_at = int(self.clock())
            if self.ix.writes != w0 or self.clock() - self._ia_saved >= IA_SAVE_S:
                self.ix.meta_set("indexedAt", self.indexed_at)
                self._ia_saved = self.clock()
            if isinstance(dix, dict) and isinstance(out, dict):
                if not self.done_first and self.ix.meta_get("built") != "1":
                    self.ix.meta_set("built", 1)
                self.done_first = True

    def loop(self):
        if _demo():
            return
        try:
            d0 = float(os.environ.get("TJ_SEARCH_IDX_DELAY") or 15)
            tk = max(1.0, float(os.environ.get("TJ_SEARCH_TICK") or TICK_S))
        except ValueError:
            d0, tk = 15.0, TICK_S
        self.sleep(d0)
        while True:
            t0 = self.clock()
            try:
                self.tick()
            except Exception as e:
                log.warning("검색 색인 갱신 실패(다음 회차): %s", common.safe_err(e)[:160])
            self.sleep(max(min(2.0, tk), tk - (self.clock() - t0)))


INDEXER = None


def start(state_fn, nft_fn=None, chain_names=None):
    global INDEXER
    if INDEXER is not None or _demo():
        return INDEXER
    INDEXER = Indexer(state_fn, nft_fn, chain_names)
    threading.Thread(target=INDEXER.loop, daemon=True, name="search-index").start()
    return INDEXER


_FILTER_RE = re.compile(r"(?<!\S)(coin|chain|type|after|before|pnl|amt|addr|tx):(\S+)", re.I)
_EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_EVM_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,90}$")
_HEXP = re.compile(r"^(0x[0-9a-fA-F]{2,63}|[0-9a-fA-F]{6,63})$")
_TICK = re.compile(r"^\$?[A-Z][A-Z0-9]{1,9}$|^[0-9][A-Z][A-Z0-9]{0,8}$")
_NUM = re.compile(r"^[$]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^[$]?\d{4,}(?:\.\d+)?$")
_CMP = re.compile(r"^(<=|>=|<|>|=|~)?(-?\d+(?:\.\d+)?)$")


def _month_end(y, m):
    return (datetime(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).strftime("%Y-%m-%d")


def _date_range(tok: str, today: datetime):
    t = tok.strip()
    d0 = today.date()
    if t in ("오늘", "today"):
        s = d0.isoformat()
        return s, s
    if t in ("어제", "yesterday"):
        s = (d0 - timedelta(days=1)).isoformat()
        return s, s
    if t in ("그제", "그저께"):
        s = (d0 - timedelta(days=2)).isoformat()
        return s, s
    if t in ("이번주", "이번 주"):
        a = d0 - timedelta(days=d0.weekday())
        return a.isoformat(), d0.isoformat()
    if t in ("지난주", "지난 주"):
        a = d0 - timedelta(days=d0.weekday() + 7)
        return a.isoformat(), (a + timedelta(days=6)).isoformat()
    if t in ("이번달", "이번 달"):
        return d0.replace(day=1).isoformat(), d0.isoformat()
    if t in ("지난달", "지난 달"):
        e = d0.replace(day=1) - timedelta(days=1)
        return e.replace(day=1).isoformat(), e.isoformat()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            s = datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%Y-%m-%d")
            return s, s
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m and 1 <= int(m[2]) <= 12:
        y, mo = int(m[1]), int(m[2])
        return f"{y}-{mo:02d}-01", _month_end(y, mo)
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", t) or re.fullmatch(r"(\d{1,2})월\s?(\d{1,2})일?", t)
    if m:
        mo, da = int(m[1]), int(m[2])
        for y in (d0.year, d0.year - 1):
            try:
                c = datetime(y, mo, da).date()
            except ValueError:
                return None
            if c <= d0:
                return c.isoformat(), c.isoformat()
        return None
    return None


def parse_query(q: str, today: datetime = None):
    today = today or datetime.now(KST)
    q = re.sub(r"[\x00-\x1f\x7f]", " ", str(q or ""))[:Q_MAX]
    filters = {}
    for m in _FILTER_RE.finditer(q):
        filters[m.group(1).lower()] = m.group(2)
    text = _FILTER_RE.sub(" ", q)
    text = re.sub(r"(\d{1,2})월\s+(\d{1,2})일", r"\1월\2일", text)
    text = re.sub(r"(이번|지난)\s+(주|달)", r"\1\2", text)
    toks = [t for t in text.split() if t]
    out = {"text": " ".join(toks), "filters": {}, "detect": "text", "tokens": [], "ticker": None, "hexp": [], "exact": [],
           "date": None, "amt_near": None}
    f = out["filters"]
    for k in ("coin", "chain", "type", "addr", "tx"):
        if filters.get(k):
            f[k] = filters[k][:90]
    if f.get("type") and f["type"].lower() not in TYPES:
        f.pop("type")
    for k in ("after", "before"):
        v = filters.get(k)
        if v:
            r = _date_range(v, today)
            if r:
                f[k] = r[0] if k == "after" else r[1]
    for k in ("pnl", "amt"):
        v = filters.get(k)
        if v:
            m = _CMP.fullmatch(v.replace(",", "").replace("$", ""))
            if m:
                f[k] = (m.group(1) or "=") + m.group(2)
    rest = []
    for t in toks:
        tl = t.strip()
        if _EVM_ADDR.fullmatch(tl):
            out["exact"].append(("addr", tl.lower()))
            out["detect"] = "addr"
            continue
        if _EVM_TX.fullmatch(tl):
            out["exact"].append(("tx", tl.lower()))
            out["detect"] = "tx"
            continue
        if _B58.fullmatch(tl) and len(tl) >= 32 and not tl.isdigit():
            out["exact"].append(("tx" if len(tl) >= 80 else "addr_or_tx", tl))
            out["detect"] = "tx" if len(tl) >= 80 else "addr"
            continue
        if _HEXP.fullmatch(tl) and not tl.isdigit() and (tl.lower().startswith("0x") or any(ch.isdigit() for ch in tl)):
            out["hexp"].append(tl.lower())
            out["detect"] = "hexprefix"
            continue
        dr = _date_range(tl, today)
        if dr:
            out["date"] = dr
            out["detect"] = "date"
            continue
        if re.fullmatch(r"(19|20)\d\d", tl):
            out["date"] = (tl + "-01-01", tl + "-12-31")
            out["detect"] = "date"
            continue
        if _NUM.fullmatch(tl):
            try:
                v = float(tl.replace("$", "").replace(",", ""))
            except ValueError:
                v = None
            if v is not None and v >= 1000:
                out["amt_near"] = v
                out["detect"] = "amount"
                continue
        if _TICK.fullmatch(tl) and not out["ticker"]:
            out["ticker"] = tl.upper()
            out["detect"] = "ticker"
        al = KO_ALIAS.get(tl) or _CHO_ALIAS.get(tl)
        if al and not out["ticker"]:
            out["ticker"] = al
            out["detect"] = "ticker"
            if tl in _CHO_ALIAS and tl not in KO_ALIAS:
                continue
        rest.append(tl[:60])
    out["tokens"] = rest[:8]
    if out["date"]:
        f.setdefault("after", out["date"][0])
        f.setdefault("before", out["date"][1])
    if out["amt_near"] is not None and "amt" not in f:
        f["amt"] = "~" + (str(int(out["amt_near"])) if out["amt_near"] == int(out["amt_near"]) else str(out["amt_near"]))
    return out


def _fts_phrase(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


def _lesc(tok: str) -> str:
    return str(tok).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(tok: str) -> str:
    return "%" + _lesc(tok) + "%"


def _word(tok: str) -> str:
    return "% " + _lesc(tok) + " %"


def _build_where(p, kinds, fts_on):
    where, args = [], []
    f = p["filters"]
    where.append("d.kind IN (%s)" % ",".join("?" * len(kinds)))
    args += list(kinds)
    if f.get("coin"):
        cu = f["coin"].upper()
        where.append("(d.sym_u = ? OR d.syms LIKE ? ESCAPE '\\')")
        args += [cu, _word(cu)]
    if f.get("chain"):
        c = f["chain"].lower()
        where.append("(d.chain_l = ? OR d.chain_l LIKE ? ESCAPE '\\' OR d.chains LIKE ? ESCAPE '\\' OR d.sub LIKE ? ESCAPE '\\')")
        args += [c, _like(c), _like(c), _like(f["chain"])]
    if f.get("type"):
        t9 = f["type"].lower()
        if t9 in ("sell", "buy"):
            where.append("(d.etype = ? OR (d.etype = 'swap' AND d.title LIKE ?))")
            args += [t9, "%" + ("매도" if t9 == "sell" else "매수") + "%"]
        else:
            where.append("d.etype = ?")
            args.append(t9)
    if f.get("after"):
        where.append("d.date >= ?")
        args.append(f["after"])
    if f.get("before"):
        where.append("d.date <= ?")
        args.append(f["before"])
    for col, k in (("pnl", "pnl"), ("usd", "amt")):
        v = f.get(k)
        if v:
            if v.startswith("~"):
                x = float(v[1:])
                where.append(f"d.{col} IS NOT NULL AND abs(d.{col}) BETWEEN ? AND ?")
                args += [x * 0.99, x * 1.01]
            else:
                m = _CMP.fullmatch(v)
                op, x = m.group(1) or "=", float(m.group(2))
                if k == "amt":
                    where.append(f"d.{col} IS NOT NULL AND abs(d.{col}) {op} ?")
                else:
                    where.append(f"d.{col} IS NOT NULL AND d.{col} {op} ?")
                args.append(x)
    for k, col in (("addr", "addr_l"), ("tx", "tx_l")):
        v = f.get(k)
        if v:
            vv = _addr_norm(v)
            where.append(f"d.{col} >= ? AND d.{col} < ?")
            args += [vv, vv + "￿"]
    for kind, v in p["exact"]:
        if kind == "addr":
            where.append("(d.addr_l = ? OR d.tx_l = ?)")
            args += [v, v]
        elif kind == "tx":
            where.append("(d.tx_l = ? OR d.addr_l = ?)")
            args += [v, v]
        else:
            where.append("(d.addr_l = ? OR d.tx_l = ?)")
            args += [v, v]
    for h in p["hexp"]:
        hh = h if h.startswith("0x") else h
        cond = ["(d.addr_l >= ? AND d.addr_l < ?)", "(d.tx_l >= ? AND d.tx_l < ?)"]
        a9 = [hh, hh + "￿", hh, hh + "￿"]
        if not h.startswith("0x"):
            cond += ["(d.addr_l >= ? AND d.addr_l < ?)", "(d.tx_l >= ? AND d.tx_l < ?)"]
            a9 += ["0x" + hh, "0x" + hh + "￿", "0x" + hh, "0x" + hh + "￿"]
        where.append("(" + " OR ".join(cond) + ")")
        args += a9
    fts_terms = []
    tick = p.get("ticker")
    for t in p["tokens"]:
        is_tick = bool(tick) and (t.upper() == tick or KO_ALIAS.get(t) == tick)
        if fts_on and len(t) >= 3 and not is_tick:
            fts_terms.append(_fts_phrase(t))
        elif is_tick:
            tsy = _word(tick)
            if fts_on and len(t) >= 3 and t.upper() == tick:
                where.append("(d.sym_u = ? OR d.syms LIKE ? ESCAPE '\\' OR d.id IN (SELECT rowid FROM fts WHERE fts MATCH ?))")
                args += [tick, tsy, _fts_phrase(t)]
            else:
                where.append("(d.sym_u = ? OR d.syms LIKE ? ESCAPE '\\' OR d.title LIKE ? ESCAPE '\\' OR d.sub LIKE ? ESCAPE '\\' OR d.body LIKE ? ESCAPE '\\')")
                args += [tick, tsy, _like(t), _like(t), _like(t)]
        else:
            where.append("(d.title LIKE ? ESCAPE '\\' OR d.sub LIKE ? ESCAPE '\\' OR d.body LIKE ? ESCAPE '\\')")
            args += [_like(t), _like(t), _like(t)]
    if tick and not any((t.upper() == tick or KO_ALIAS.get(t) == tick) for t in p["tokens"]):
        where.append("(d.sym_u = ? OR d.syms LIKE ? ESCAPE '\\')")
        args += [tick, _word(tick)]
    if fts_terms:
        where.append("d.id IN (SELECT rowid FROM fts WHERE fts MATCH ?)")
        args.append(" AND ".join(fts_terms))
    return where, args


SNIP_W = 76


def _needles(p) -> list:
    return [x for x in ([*p["tokens"], *p["hexp"]] + ([p["ticker"]] if p.get("ticker") else [])) if x]


def _hl(title: str, sub: str, body: str, p):
    ns = _needles(p)
    if not ns:
        return None
    rx = re.compile("|".join(re.escape(n) for n in sorted(set(ns), key=len, reverse=True)), re.I)
    for txt in (sub or "", body or ""):
        t = re.sub(r"</?mark>", "", str(txt), flags=re.I)
        m = rx.search(t)
        if not m:
            continue
        a = max(0, m.start() - SNIP_W // 3)
        b = min(len(t), a + SNIP_W)
        a = max(0, b - SNIP_W) if b - a < SNIP_W else a
        seg = t[a:b]
        out = rx.sub(lambda mm: "<mark>" + mm.group(0) + "</mark>", seg)
        return ("…" if a > 0 else "") + out + ("…" if b < len(t) else "")
    return None


def search(q: str, kinds=None, limit=None, after=None, before=None, path=None, today: datetime = None, budget_s: float = QUERY_BUDGET_S,
           clock=time.monotonic) -> dict:
    t0 = clock()
    q = str(q or "")[:Q_MAX]
    p = parse_query(q, today)
    if after and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(after)):
        p["filters"]["after"] = str(after) if len(str(after)) == 10 else str(after) + "-01"
    if before and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(before)):
        b = str(before)
        p["filters"]["before"] = b if len(b) == 10 else _month_end(int(b[:4]), int(b[5:7]))
    ks = [k for k in (kinds or KINDS) if k in KINDS] or list(KINDS)
    try:
        lim = max(1, min(LIMIT_MAX, int(limit))) if limit not in (None, "") else LIMIT_DEF
    except (TypeError, ValueError):
        lim = LIMIT_DEF
    parsed = {"text": p["text"], "filters": dict(p["filters"]), "detect": p["detect"]}
    base = {"ok": True, "q": q, "parsed": parsed, "tookMs": 0, "building": False, "indexedAt": None, "groups": []}
    if _demo():
        return base
    path = path or db_path()
    if not os.path.exists(path):
        base["building"] = True
        return base
    has_query = bool(p["tokens"] or p["exact"] or p["hexp"] or p.get("ticker") or any(p["filters"].values()))
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        base["building"] = True
        return base
    partial = False
    try:
        c.execute("PRAGMA query_only=1")
        meta = dict(c.execute("SELECT k, v FROM meta WHERE k IN ('fts', 'indexedAt', 'built')").fetchall())
        fts_on = meta.get("fts") == "1"
        base["indexedAt"] = int(meta["indexedAt"]) if meta.get("indexedAt") else None
        if INDEXER is not None and INDEXER.indexed_at and os.path.abspath(INDEXER.ix.path) == os.path.abspath(path):
            base["indexedAt"] = INDEXER.indexed_at
        base["building"] = not meta.get("built")
        if not has_query:
            base["tookMs"] = int((clock() - t0) * 1000)
            return base
        deadline = t0 + max(0.05, budget_s)
        c.set_progress_handler(lambda: 1 if clock() > deadline else 0, 2000)
        where, args = _build_where(p, ks, fts_on)
        wsql = " AND ".join(where)
        tick = p.get("ticker") or (p["tokens"][0].upper() if len(p["tokens"]) == 1 else "")
        first = p["tokens"][0] if p["tokens"] else ""
        order = ("d.spam ASC, (CASE WHEN d.sym_u = ? THEN 0 WHEN d.title LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END) ASC, "
                 "COALESCE(d.ts, 0) DESC, d.id DESC")
        oargs = [tick, (first.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%") if first else "￿"]
        counts = {}
        try:
            for k, n in c.execute(f"SELECT d.kind, count(*) FROM docs d WHERE {wsql} GROUP BY d.kind", args):
                counts[k] = n
        except sqlite3.OperationalError as e:
            if "interrupt" not in str(e).lower():
                raise
            partial = True
        groups = []
        order_k = [k for k in KINDS if k in ks]
        if p["detect"] in ("addr", "tx", "hexprefix"):
            order_k.sort(key=lambda k: {"outflow": 0, "tx": 1, "wallet": 2, "deposit": 3, "event": 4}.get(k, 5))
        for k in order_k:
            if counts and not counts.get(k):
                continue
            if not counts and partial:
                break
            if clock() > deadline:
                partial = True
                break
            try:
                rows = c.execute(f"SELECT d.kind, d.key, d.title, d.sub, d.date, d.ts, d.usd, d.sym, d.chain, d.addr, d.tx, d.anc, d.spam, d.body "
                                 f"FROM docs d WHERE {wsql} AND d.kind = ? ORDER BY {order} LIMIT ?", args + [k] + oargs + [lim]).fetchall()
            except sqlite3.OperationalError as e:
                if "interrupt" not in str(e).lower():
                    raise
                partial = True
                break
            items = []
            for kind, key, title, sub, date, ts, usd, sym, chain, addr, tx, anc, spam, body in rows:
                it = {"kind": kind, "id": key, "title": title, "sub": sub or "", "date": date, "ts": ts, "usd": usd, "sym": sym,
                      "chain": chain, "addr": addr, "tx": tx, "anc": anc}
                h9 = _hl(title or "", sub or "", body or "", p)
                if h9:
                    it["hl"] = h9
                if spam:
                    it["spam"] = True
                items.append(it)
            if items:
                groups.append({"kind": k, "n": counts.get(k, len(items)), "items": items})
        base["groups"] = groups
    except sqlite3.Error as e:
        log.warning("검색 실패: %s", common.safe_err(e)[:160])
        base["ok"] = False
        base["error"] = "검색 색인을 읽지 못했어요 — 잠시 뒤 다시"
    finally:
        c.close()
    if partial:
        base["partial"] = True
    base["tookMs"] = int((clock() - t0) * 1000)
    return base
