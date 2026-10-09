from __future__ import annotations

import calendar
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
import zlib
from datetime import datetime, timedelta, timezone

import common

log = logging.getLogger("tj-web")

KST = timezone(timedelta(hours=9))
DB_NAME = "search.db"
SCHEMA = 2
ROWV = 3
TX_AGG_V = 4
KINDS = ("coin", "event", "tx", "outflow", "memo", "review", "wallet", "deposit", "nft", "other")
Q_MAX = 200
LIMIT_DEF, LIMIT_MAX = 20, 50
QUERY_BUDGET_S = 2.0
ITEM_GRACE_S = 1.0
PROGRESS_N = 50000
FTS_DRIVE_MAX = 3000
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

KO_SHORT = {"비트": "BTC", "이더": "ETH", "솔": "SOL", "리플": "XRP", "도지": "DOGE", "트럼프": "TRUMP", "시바": "SHIB", "아비": "ARB",
            "폴카": "DOT", "링크": "LINK", "월코": "WLD", "하이퍼": "HYPE", "온도": "ONDO", "에테나": "ENA", "주피터": "JUP", "펭구": "PENGU",
            "비캐": "BCH", "이클": "ETC", "스텔라": "XLM", "알고랜드": "ALGO", "샌드박스": "SAND", "엑시": "AXS", "셀레스티아": "TIA"}
KO_ALL = dict(KO_SHORT, **KO_ALIAS)
_CHO_SET = set(_CHO)

CHAIN_NAME_FALLBACK = {"eth": "Ethereum", "base": "Base", "arbitrum": "Arbitrum", "optimism": "Optimism", "polygon": "Polygon",
                       "bsc": "BSC", "sol": "Solana", "scroll": "Scroll", "zksync": "zkSync", "gnosis": "Gnosis"}
CHAIN_ALIAS = {"ethereum": "eth", "mainnet": "eth", "이더리움": "eth", "베이스": "base", "arb": "arbitrum", "arbitrum one": "arbitrum",
               "아비트럼": "arbitrum", "op": "optimism", "op mainnet": "optimism", "옵티미즘": "optimism", "matic": "polygon", "pol": "polygon",
               "폴리곤": "polygon", "bnb": "bsc", "bnb chain": "bsc", "bnb smart chain": "bsc", "bep20": "bsc", "바이낸스 체인": "bsc",
               "solana": "sol", "솔라나": "sol", "zksync era": "zksync", "xdai": "gnosis", "avax": "avalanche", "avalanche c-chain": "avalanche",
               "아발란체": "avalanche", "erc20": "eth", "trc20": "tron", "trx": "tron", "트론": "tron", "bera": "berachain"}
EX_ALIAS = {"upbit": "upbit", "업비트": "upbit", "bithumb": "bithumb", "빗썸": "bithumb", "binance": "binance", "바이낸스": "binance",
            "bybit": "bybit", "바이빗": "bybit", "okx": "okx", "오케이엑스": "okx", "kucoin": "kucoin", "쿠코인": "kucoin", "gate": "gate",
            "gateio": "gate", "gate.io": "gate", "게이트": "gate", "게이트아이오": "gate", "hyperliquid": "hyperliquid", "하이퍼리퀴드": "hyperliquid",
            "bitget": "bitget", "비트겟": "bitget", "coinone": "coinone", "코인원": "coinone", "korbit": "korbit", "코빗": "korbit", "mexc": "mexc",
            "htx": "htx", "huobi": "htx", "후오비": "htx"}
_EX_NAMES = sorted(EX_ALIAS, key=len, reverse=True)
TYPE_ALIAS = {"매도": "sell", "매수": "buy", "스왑": "swap", "입금": "deposit", "받음": "deposit", "출금": "withdraw", "보냄": "withdraw", "가스": "gas",
              "수수료": "gas", "fee": "gas", "전송": "transfer", "이동": "transfer", "send": "transfer", "유동성": "lp"}
DATE_MIN_Y, DATE_MAX_Y = 1970, 2100


_JAMO_BACK = {chr(0x1100 + i): _CHO[i] for i in range(19)}


def nfkc(s):
    if s is None:
        return None
    s = str(s)
    if s.isascii():
        return s
    r = "…".join(unicodedata.normalize("NFKC", x) for x in s.split("…")) if "…" in s else unicodedata.normalize("NFKC", s)
    if any("ᄀ" <= ch <= "ᄒ" for ch in r):
        r = "".join(_JAMO_BACK.get(ch, ch) for ch in r)
    return r


def ex_key(s):
    t = (nfkc(s) or "").strip().lower()
    if not t:
        return None
    if t in EX_ALIAS:
        return EX_ALIAS[t]
    for n in _EX_NAMES:
        if t.startswith(n) and (len(t) == len(n) or not t[len(n)].isalnum()):
            return EX_ALIAS[n]
    return None


_SEP_RE = re.compile(r"\s*(?:·|/|,|→|->|\(|\))\s*")
_TAIL_RE = re.compile(r"\s+(외\s*\d+.*|입금.*|출금.*|체인|네트워크|network)$", re.I)


class Names:

    def __init__(self, chain_names=None):
        cn = dict(CHAIN_NAME_FALLBACK)
        cn.update(chain_names or {})
        self.keys = {str(k).lower() for k in cn}
        self.rev = {}
        for k, v in cn.items():
            self.rev[(nfkc(v) or "").strip().lower()] = str(k).lower()
        for a, k in CHAIN_ALIAS.items():
            self.rev.setdefault(a, k)
        self.disp = {str(k).lower(): str(v) for k, v in cn.items()}

    def chain(self, s):
        t = (nfkc(s) or "").strip().lower()
        if not t:
            return None
        if t in self.keys:
            return t
        r = self.rev.get(t)
        if r:
            return r
        t2 = _TAIL_RE.sub("", t).strip()
        if t2 and t2 != t:
            return t2 if t2 in self.keys else self.rev.get(t2)
        return None

    def chains_in(self, text) -> list:
        out = []
        for piece in _SEP_RE.split(nfkc(text) or ""):
            k = self.chain(piece)
            if k and k not in out:
                out.append(k)
        return out

    def exs_in(self, text) -> list:
        out = []
        for piece in _SEP_RE.split(nfkc(text) or ""):
            k = ex_key(piece)
            if k and k not in out:
                out.append(k)
        return out


NAMES = Names()

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
        anc TEXT, spam INTEGER NOT NULL DEFAULT 0, syms TEXT, chains TEXT, h TEXT)""",
    "CREATE INDEX IF NOT EXISTS docs_grp ON docs(grp)",
    "CREATE INDEX IF NOT EXISTS docs_kind_ts ON docs(kind, ts)",
    "CREATE INDEX IF NOT EXISTS docs_addr ON docs(addr_l)",
    "CREATE INDEX IF NOT EXISTS docs_tx ON docs(tx_l)",
    "CREATE INDEX IF NOT EXISTS docs_sym ON docs(sym_u)",
    "CREATE INDEX IF NOT EXISTS docs_date ON docs(date)",
    "CREATE INDEX IF NOT EXISTS docs_kind_date ON docs(kind, date, ts)",
    "CREATE INDEX IF NOT EXISTS docs_kind_pnl ON docs(kind, pnl) WHERE pnl IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS docs_old ON docs(kind) WHERE h IS NULL",
    """CREATE TABLE IF NOT EXISTS tg (t TEXT NOT NULL, kind TEXT NOT NULL, ns INTEGER NOT NULL, ts INTEGER NOT NULL, id INTEGER NOT NULL,
        PRIMARY KEY (t, kind, ns, ts, id)) WITHOUT ROWID""",
    "CREATE INDEX IF NOT EXISTS tg_id ON tg(id)",
]
_COLS = ("kind", "key", "grp", "title", "sub", "body", "date", "ts", "usd", "pnl", "sym", "sym_u", "chain", "chain_l", "etype",
         "addr", "addr_l", "tx", "tx_l", "anc", "spam", "syms", "chains", "h")
_ADD_COLS = (("h", "TEXT"),)


def _tags_of(d) -> list:
    out = []
    for x in d.get("tys") or ([d["etype"]] if d.get("etype") else []):
        if x:
            out.append("ty:" + str(x))
    for x in d.get("cks") or ():
        if x:
            out.append("c:" + str(x).lower())
    sy = d.get("syms") or ([d["sym"]] if d.get("sym") else [])
    for x in sy:
        x9 = (nfkc(x) or "").strip().upper()
        if x9:
            out.append("s:" + x9)
    for x in d.get("xks") or ():
        if x:
            out.append("x:" + str(x))
    for x in d.get("wals") or ():
        if x:
            out.append("w:" + _addr_norm(x))
    for x in d.get("hs") or ():
        out.append("h:" + str(x))
    pn = _num(d.get("pnl"))
    if pn is not None and pn != 0:
        out.append("p:-" if pn < 0 else "p:+")
    return list(dict.fromkeys(out))


def _row(d) -> dict:
    d = dict(d)
    for k9 in ("title", "sub", "body", "sym", "chain"):
        if d.get(k9) is not None:
            d[k9] = nfkc(d[k9])
    d["title"] = d.get("title") or ""
    sy = [str(nfkc(x)).strip() for x in (d.get("syms") or ([d["sym"]] if d.get("sym") else [])) if x and str(x).strip()]
    chs = [str(nfkc(x)).strip() for x in (d.get("chains") or ([d["chain"]] if d.get("chain") else [])) if x and str(x).strip()]
    tags = _tags_of(dict(d, syms=sy))
    d["sym_u"] = str(d.get("sym") or "").upper() or None
    d["chain_l"] = str(d.get("chain") or "").lower() or None
    d["addr_l"] = _addr_norm(d.get("addr")) or None
    d["tx_l"] = _addr_norm(d.get("tx")) or None
    d["spam"] = 1 if d.get("spam") else 0
    d["syms"] = (" " + " ".join(dict.fromkeys(x.upper() for x in sy)) + " ") if sy else None
    d["chains"] = (" " + " ".join(dict.fromkeys(x.lower() for x in chs)) + " ") if chs else None
    try:
        d["ts"] = int(d["ts"]) if d.get("ts") is not None else None
    except (TypeError, ValueError):
        d["ts"] = None
    for k9 in ("usd", "pnl"):
        d[k9] = _num(d.get(k9))
    vals = [d.get(k9) for k9 in _COLS[:-1]]
    d["h"] = hashlib.sha1(json.dumps([vals, tags], ensure_ascii=False, default=str).encode()).hexdigest()[:20]
    d["_tags"] = tags
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


def _chunks(seq, n=400):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Index:

    def __init__(self, path=None, sleep=time.sleep):
        self.path = path or db_path()
        self.sleep = sleep
        self.conn = None
        self.fts = False
        self.writes = 0
        self.changed = 0
        self.rowv = None
        self._in_tx = False

    def _precreate(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA journal_size_limit=33554432")
        return c

    def open(self):
        if self.conn is not None:
            return self.conn
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._precreate()
        c = self._connect()
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
            c = self._connect()
        c.execute("BEGIN IMMEDIATE")
        try:
            for d in _DDL[:2]:
                c.execute(d)
            have = {r[1] for r in c.execute("PRAGMA table_info(docs)")}
            for col, typ in _ADD_COLS:
                if col not in have:
                    c.execute(f"ALTER TABLE docs ADD COLUMN {col} {typ}")
            for d in _DDL[2:]:
                c.execute(d)
            self.fts = fts_supported()
            if self.fts:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(title, sub, body, tokenize='trigram')")
            c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('schema', ?)", (str(SCHEMA),))
            c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('fts', ?)", ("1" if self.fts else "0",))
            r = c.execute("SELECT v FROM meta WHERE k='rowv'").fetchone()
            n0 = c.execute("SELECT count(*) FROM docs").fetchone()[0]
            if r is None and not n0:
                c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(ROWV),))
                r = (str(ROWV),)
            self.rowv = r[0] if r else None
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        for p9 in (self.path, self.path + "-wal", self.path + "-shm"):
            try:
                os.chmod(p9, 0o600)
            except OSError:
                pass
        self.conn = c
        return c

    class _Tx:
        def __init__(self, ix):
            self.ix = ix

        def __enter__(self):
            c = self.ix.open()
            if self.ix._in_tx:
                self.nested = True
                return c
            self.nested = False
            c.execute("BEGIN")
            self.ix._in_tx = True
            return c

        def __exit__(self, et, ev, tb):
            if self.nested:
                return False
            c = self.ix.conn
            self.ix._in_tx = False
            c.execute("ROLLBACK" if et else "COMMIT")
            return False

    def tx(self):
        return Index._Tx(self)

    def meta_get(self, k, dflt=None):
        r = self.open().execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else dflt

    def meta_set(self, k, v):
        self.writes += 1
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (k, None if v is None else str(v)))

    def meta_del_prefix(self, p):
        with self.tx() as c:
            c.execute("DELETE FROM meta WHERE k >= ? AND k < ?", (p, p + "￿"))

    def _del_ids(self, c, ids):
        for part in _chunks(ids):
            q9 = ",".join("?" * len(part))
            if self.fts:
                c.execute(f"DELETE FROM fts WHERE rowid IN ({q9})", part)
            c.execute(f"DELETE FROM tg WHERE id IN ({q9})", part)
            c.execute(f"DELETE FROM docs WHERE id IN ({q9})", part)

    def _ins_rows(self, c, rows):
        ins = "INSERT INTO docs (%s) VALUES (%s)" % (",".join(_COLS), ",".join("?" * len(_COLS)))
        for i in range(0, len(rows), BATCH):
            for r in rows[i:i + BATCH]:
                cur = c.execute(ins, tuple(r.get(k) for k in _COLS))
                rid = cur.lastrowid
                if self.fts:
                    c.execute("INSERT INTO fts (rowid, title, sub, body) VALUES (?, ?, ?, ?)", (rid, r["title"] or "", r.get("sub") or "", r.get("body") or ""))
                if r["_tags"]:
                    ns9, ts9 = 0 if r["spam"] else 1, int(r.get("ts") or 0)
                    c.executemany("INSERT OR IGNORE INTO tg (t, kind, ns, ts, id) VALUES (?, ?, ?, ?, ?)",
                                  [(t9, r["kind"], ns9, ts9, rid) for t9 in r["_tags"]])
            if len(rows) > BATCH and i + BATCH < len(rows):
                self.sleep(BATCH_SLEEP)

    def _apply(self, c, rows, cur):
        if not rows:
            return
        ids = [cur[r["key"]][0] for r in rows if r["key"] in cur]
        other = [r["key"] for r in rows if r["key"] not in cur]
        for part in _chunks(other):
            ids += [r9[0] for r9 in c.execute("SELECT id FROM docs WHERE key IN (%s)" % ",".join("?" * len(part)), part)]
        self._del_ids(c, ids)
        self._ins_rows(c, rows)

    def replace(self, where, args, docs):
        if isinstance(docs, (list, tuple)):
            uq = {}
            for d in docs:
                uq[d["key"]] = d
            docs = list(uq.values())
        n_chg = 0
        with self.tx() as c:
            cur = {}
            for key9, id9, h9 in c.execute(f"SELECT key, id, h FROM docs WHERE {where}", tuple(args)):
                cur[key9] = (id9, h9)
            seen, pend = set(), []
            for d in docs:
                r = _row(d)
                k9 = r["key"]
                seen.add(k9)
                o9 = cur.get(k9)
                if o9 is not None and o9[1] == r["h"]:
                    continue
                pend.append(r)
                if len(pend) >= BATCH:
                    self._apply(c, pend, cur)
                    n_chg += len(pend)
                    pend = []
                    self.sleep(BATCH_SLEEP)
            self._apply(c, pend, cur)
            n_chg += len(pend)
            gone = [cur[k9][0] for k9 in cur if k9 not in seen]
            self._del_ids(c, gone)
        if n_chg or gone:
            self.writes += 1
            self.changed += n_chg + len(gone)
        return n_chg, len(gone)

    def replace_groups(self, grps, docs):
        grps = list(grps)
        if not grps:
            return 0, 0
        if len(grps) == 1:
            return self.replace("grp = ?", (grps[0],), docs)
        with self.tx():
            tot = [0, 0]
            docs = list(docs)
            for part in _chunks(grps):
                pk = set(part)
                a9, b9 = self.replace("grp IN (%s)" % ",".join("?" * len(part)), part, [d for d in docs if d.get("grp") in pk])
                tot[0] += a9
                tot[1] += b9
            return tuple(tot)

    def replace_keys(self, keys, docs):
        keys = list(keys)
        docs = list(docs)
        with self.tx():
            tot = [0, 0]
            for part in _chunks(keys):
                pk = set(part)
                a9, b9 = self.replace("key IN (%s)" % ",".join("?" * len(part)), part, [d for d in docs if d.get("key") in pk])
                tot[0] += a9
                tot[1] += b9
            rest = [d for d in docs if d.get("key") not in set(keys)]
            if rest:
                a9, _b = self.replace("0", (), rest)
                tot[0] += a9
            return tuple(tot)

    def clear_kind(self, kind):
        return self.replace("kind = ?", (kind,), [])

    def _insert(self, docs):
        docs = list(docs)
        return self.replace_keys([d["key"] for d in docs], docs)

    def count(self):
        return self.open().execute("SELECT count(*) FROM docs").fetchone()[0]

    def maintain(self, full=False):
        c = self.open()
        if self.fts:
            with self.tx() as c9:
                if full:
                    c9.execute("INSERT INTO fts(fts) VALUES('optimize')")
                else:
                    c9.execute("INSERT INTO fts(fts, rank) VALUES('merge', 300)")
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

    def vacuum_if_bloated(self, min_free_mb=32, frac=0.4):
        c = self.open()
        pc = c.execute("PRAGMA page_count").fetchone()[0]
        fl = c.execute("PRAGMA freelist_count").fetchone()[0]
        ps = c.execute("PRAGMA page_size").fetchone()[0]
        if fl * ps < min_free_mb * 1e6 or fl < pc * frac:
            return None
        before = pc * ps / 1e6
        c.execute("VACUUM")
        try:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        after = c.execute("PRAGMA page_count").fetchone()[0] * ps / 1e6
        return round(before, 1), round(after, 1)


def _tax_pnl(e):
    t = e.get("_tax")
    if not isinstance(t, dict):
        return None
    try:
        v = float(t.get("_disp", t.get("disp") or 0)) - float(t.get("_acq", t.get("acq") or 0)) - float(t.get("_fee", t.get("fee") or 0))
    except (TypeError, ValueError):
        return None
    return round(v, 2)


def docs_events(day_ix: dict, pos_pnl: dict, chain_names, iso: str):
    nm = chain_names if isinstance(chain_names, Names) else Names(chain_names)
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
        seg = d.split(" · ", 1)[0] if d else ""
        cks = nm.chains_in(seg)
        if not cks and meta and meta[2] and not src.startswith("ex:"):
            mk = nm.chains_in(str(meta[2]))
            cks = mk if len(mk) == 1 else []
        xks = []
        if src.startswith("ex:"):
            xk = ex_key(src[3:]) or src[3:].lower()
            xks.append(xk)
        for x9 in nm.exs_in(seg):
            if x9 not in xks:
                xks.append(x9)
        chain_disp = str((meta[2] if meta else None) or (d.split(" · ", 1)[0] if " · " in d else "") or "")
        txs = str(e.get("tx") or "")
        txs = "" if txs in ("—", "-") else txs
        h = hashlib.sha1("|".join((k, d, str(e.get("q")), str(a), txs, src, sym)).encode()).hexdigest()[:10]
        base = f"ev:{iso}:{int(ts)}:{h}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        key = base if not n else f"{base}:{n}"
        pnl = None
        if kind == "hidden":
            pass
        elif "_tax" in e and "매도" in k:
            pnl = _tax_pnl(e)
        elif meta and "매도" in k:
            rbd = pos_pnl.get(meta[0]) or {}
            pnl = _num(rbd.get(iso))
        addr = src[2:] if src.startswith("w:") else ""
        exl = src[3:] if src.startswith("ex:") else ""
        sub = " · ".join(x for x in (_hm(ts), d, (str(e.get("q")) + " " + sym) if e.get("q") else "", _short(addr) if addr else exl) if x)
        et = _ev_type(k, d)
        tys = [et]
        if et == "swap" and "매도" in k:
            tys.append("sell")
        elif et == "swap" and "매수" in k:
            tys.append("buy")
        out.append({"kind": "event", "key": key, "grp": "ev:" + iso, "title": (sym + " " + k).strip(), "sub": sub,
                    "body": " ".join(x for x in (txs, str(e.get("symRaw") or ""), str(e.get("hide") or "")) if x),
                    "date": iso, "ts": int(ts), "usd": _usd_of(a), "pnl": pnl, "sym": sym or None,
                    "chain": cks[0] if len(cks) == 1 else (chain_disp or None),
                    "etype": et, "addr": addr or None, "tx": txs or None, "anc": "evday:" + iso,
                    "spam": kind == "hidden", "cks": cks, "xks": xks, "tys": tys})
    return out


_EV_SIG_KEYS = ("k", "d", "a", "q", "tx", "src", "sym", "symRaw", "hide", "hideKind")


def _day_sig(rows, pos_pnl=None, iso="") -> str:
    parts = []
    for ts, kind, e, meta in rows or ():
        e = e if isinstance(e, dict) else {}
        pnl = ""
        if kind == "hidden":
            pass
        elif "_tax" in e and "매도" in str(e.get("k") or ""):
            pnl = "t" + str(_tax_pnl(e))
        elif meta and "매도" in str(e.get("k") or "") and pos_pnl is not None:
            pnl = str((pos_pnl.get(meta[0]) or {}).get(iso))
        parts.append("\x1e".join([str(ts), str(kind)] + [str(e.get(k9)) for k9 in _EV_SIG_KEYS] + [str(meta), pnl]))
    raw = "\x1f".join(parts).encode("utf-8", "replace")
    return f"{len(parts)}:{zlib.crc32(raw):08x}:{len(raw)}"


def docs_state(fields: dict, chain_names):
    nm9 = chain_names if isinstance(chain_names, Names) else Names(chain_names)
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
        cks9, xks9 = [], []
        for c9 in ch:
            for k9 in nm9.chains_in(c9):
                if k9 not in cks9:
                    cks9.append(k9)
            for k9 in nm9.exs_in(c9):
                if k9 not in xks9:
                    xks9.append(k9)
        out["coin"].append({"kind": "coin", "key": "coin:" + su, "grp": "st:coin", "title": g["sym"],
                            "sub": " · ".join(x for x in (" · ".join(ch[:3]) + (f" 외 {len(ch) - 3}곳" if len(ch) > 3 else ""),
                                                          "보유" if g["val"] >= 1 else ("보유 0 · 기록만" if g["qty"] <= 0 else "소액·시세 없음")) if x),
                            "body": " ".join(g["names"]), "sym": g["sym"], "chain": ch[0] if len(ch) == 1 else None,
                            "anc": "coin:" + su, "spam": sp, "usd": None, "chains": ch, "cks": cks9, "xks": xks9})
    for r in fields.get("outflows") or ():
        if not isinstance(r, dict) or not r.get("address"):
            continue
        a = str(r["address"])
        tk_all = [t for t in (r.get("tokens") or ()) if isinstance(t, dict)]
        tk_real = [t for t in tk_all if not t.get("phantom")]
        toks = [str(t.get("sym") or "") for t in (tk_real or tk_all)]
        ph_all = bool(tk_all) and not tk_real
        chs = [str(x) for x in (r.get("chainNames") or ())]
        nm = str(r.get("alias") or "").strip() or str(r.get("memo") or "").strip()[:40]
        sa9 = _short(a) if not a.startswith("wd:") else "주소 미상 출금"
        title = nm or sa9
        cat9 = str(r.get("category") or "")
        cks9 = []
        for c9 in [str(x) for x in (r.get("chains") or ())] + chs:
            k9 = nm9.chain(c9)
            if k9 and k9 not in cks9:
                cks9.append(k9)
        xk9 = ex_key(r.get("exchange")) if r.get("exchange") else None
        out["outflow"].append({"kind": "outflow", "key": "of:" + a, "grp": "st:outflow", "title": title.strip(),
                               "sub": " · ".join(x for x in ((sa9 if nm else ""), " · ".join(chs[:3]), " ".join(toks[:4]), f"{int(r.get('count') or 0)}건",
                                                             str(r.get("last") or ""), cat9) if x),
                               "body": " ".join(x for x in (str(r.get("memo") or ""), str(r.get("exchange") or ""), " ".join(toks), cat9,
                                                            "세일 참가 참가금" if cat9 == "세일 참가금" else "") if x),
                               "date": str(r.get("last") or "")[:10] or None, "ts": int(r.get("lastTs") or 0) or None,
                               "usd": _num(r.get("usdAtSend")), "sym": toks[0] if len(toks) == 1 else None,
                               "chain": chs[0] if len(chs) == 1 else None, "etype": "withdraw",
                               "addr": None if a.startswith("wd:") else a, "anc": "outflow:" + a,
                               "spam": bool(r.get("dust")) or str(r.get("status") or "") == "spam" or ph_all,
                               "syms": toks, "chains": chs + [str(x) for x in (r.get("chains") or ())],
                               "cks": cks9, "xks": [xk9] if xk9 else [], "hs": ["memo"] if str(r.get("memo") or "").strip() else []})
    for w in fields.get("walletRows") or ():
        if not isinstance(w, dict) or not w.get("addr"):
            continue
        a = str(w["addr"])
        out["wallet"].append({"kind": "wallet", "key": "w:" + _addr_norm(a), "grp": "st:wallet",
                              "title": (str(w.get("alias") or "") + " " + _short(a)).strip(), "sub": str(w.get("chains") or ""),
                              "body": "지갑 " + str(w.get("alias") or ""), "addr": a, "anc": None,
                              "cks": nm9.chains_in(str(w.get("chains") or "")) or (["sol"] if not a.lower().startswith("0x") else [])})
    for d in fields.get("depositRows") or ():
        if not isinstance(d, dict) or not d.get("addr"):
            continue
        a = str(d["addr"])
        memo = str(d.get("memo") or "")
        out["deposit"].append({"kind": "deposit", "key": "dep:" + str(d.get("ex")) + ":" + _addr_norm(a) + ":" + memo, "grp": "st:deposit",
                               "title": f"{d.get('ex') or ''} 입금 주소 {_short(a)}".strip(),
                               "sub": " · ".join(x for x in (str(d.get("net") or ""), ("메모 " + memo) if memo and memo != "—" else "") if x),
                               "body": "입금 주소 " + str(d.get("ex") or ""), "addr": a, "anc": None,
                               "cks": nm9.chains_in(str(d.get("net") or "")), "xks": [x9 for x9 in [ex_key(d.get("ex"))] if x9]})
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


def docs_nft(view: dict, names=None):
    out = []
    if not isinstance(view, dict):
        return out
    nm9 = names if isinstance(names, Names) else NAMES

    def add(r, grp_label, spam=False):
        if not isinstance(r, dict) or not r.get("key"):
            return
        nm = str(r.get("name") or r.get("sym") or r.get("key"))
        out.append({"kind": "nft", "key": "nft:" + str(r["key"]), "grp": "nft", "title": nm,
                    "sub": " · ".join(x for x in (str(r.get("chain") or ""), grp_label, (f"{r.get('count')}개" if r.get("count") else "")) if x),
                    "body": " ".join(x for x in (nm, str(r.get("sym") or ""), str(r.get("chain") or "")) if x),
                    "sym": r.get("sym"), "chain": r.get("chain"), "anc": "nft:" + str(r["key"]), "spam": spam,
                    "cks": nm9.chains_in(str(r.get("chain") or ""))})
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


def _lure_assets(conn) -> set:
    try:
        import spamguard as _sg
        return {int(r[0]) for r in conn.execute("SELECT asset_id, chain, address, symbol FROM assets WHERE kind = 'token' AND address IS NOT NULL")
                if r[3] and not _sg.is_genuine(r[1], r[2]) and (_sg.impostor_of(r[3]) or _sg.odd_symbol(r[3]))}
    except Exception:
        return set()


def ledger_tx_docs(conn, chain_names, only=None):
    nm9 = chain_names if isinstance(chain_names, Names) else Names(chain_names)
    cn = nm9.disp
    q = ("SELECT p.source_ns, p.source_id, MIN(p.event_ts), group_concat(DISTINCT a.symbol), group_concat(DISTINCT p.event), "
         "group_concat(DISTINCT p.location), SUM(CASE WHEN p.leg_kind='acq' THEN CAST(p.cost_usd AS REAL) END), "
         "SUM(CASE WHEN p.leg_kind='disp' THEN CAST(p.cost_usd AS REAL) END), SUM(CASE WHEN p.cost_usd IS NULL THEN 0 ELSE 1 END), "
         "SUM(CASE WHEN p.leg_kind='move_in' AND p.location LIKE 'out:%' THEN CAST(p.cost_usd AS REAL) END), "
         "SUM(CASE WHEN p.leg_kind='gas' THEN CAST(p.cost_usd AS REAL) END), "
         "group_concat(DISTINCT p.asset_id) "
         "FROM postings p JOIN assets a ON a.asset_id = p.asset_id WHERE p.source_kind = 'chain_tx'")
    args = []
    if only is not None:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _sq (ns TEXT, id TEXT)")
        conn.execute("DELETE FROM _sq")
        conn.executemany("INSERT INTO _sq VALUES (?, ?)", list(only))
        q += " AND (p.source_ns, p.source_id) IN (SELECT ns, id FROM _sq)"
    q += " GROUP BY p.source_ns, p.source_id"
    lure = _lure_assets(conn)
    for ns, sid, ts, syms, evs, locs, acq, disp, ncost, mvout, gas, aids in conn.execute(q, args):
        sid = str(sid or "")
        if not sid:
            continue
        ev_l = [x for x in str(evs or "").split(",") if x]
        main = next((x for x in _TX_PRIO if x in ev_l), ev_l[0] if ev_l else "")
        et = _TX_TYPE.get(main, "transfer")
        sy = [x for x in str(syms or "").split(",") if x][:12]
        wals = []
        for loc in str(locs or "").split(","):
            p9 = loc.split(":")
            if len(p9) >= 3 and p9[0] == "wallet" and p9[2] and p9[2] not in wals:
                wals.append(p9[2])
        wal = wals[0] if wals else ""
        usd = max(abs(acq or 0), abs(disp or 0), abs(mvout or 0)) or (abs(gas) if gas else None)
        spam = bool(set(ev_l) <= {"PROGRAM_IN", "TRANSFER_IN"} and not ncost)
        if not spam and not ncost and aids:
            ids9 = [x for x in str(aids).split(",") if x]
            spam = bool(ids9) and all(int(x) in lure for x in ids9 if x.isdigit())
        chn = cn.get(ns, ns)
        hsh = sid.split(":", 1)[0] if ":" in sid and not sid.startswith("0x") else sid
        iso = _iso(ts)
        ck9 = nm9.chain(ns) or str(ns or "").lower()
        yield ({"kind": "tx", "key": f"tx:{ns}:{sid}", "grp": "tx:" + str(ns), "title": "tx " + _short(hsh),
                    "sub": " · ".join(x for x in (_hm(ts), _TX_KO.get(et, et), " ".join(sy[:3]), chn) if x),
                    "body": " ".join(x for x in (" ".join(sy), " ".join(ev_l), chn) if x),
                    "date": iso, "ts": int(ts or 0) or None, "usd": usd, "sym": sy[0] if len(sy) == 1 else None, "chain": ns, "etype": et,
                    "addr": wal or None, "tx": hsh, "anc": ("evday:" + iso) if iso else None, "spam": spam,
                    "syms": sy, "chains": [ns, chn], "cks": [ck9] if ck9 else [], "wals": wals})


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
        self.names = Names(chain_names)
        self.cn = self.names.disp
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
        self._mig = None
        self._chg_full = 0

    def _names_meta(self):
        v = json.dumps(self.names.disp, ensure_ascii=False, sort_keys=True)
        if self.ix.meta_get("chainmap") != v:
            self.ix.meta_set("chainmap", v)

    def feed_state(self, out, dix):
        if isinstance(out, dict) and out is not self._last_out:
            f = out.get("fields") or {}
            ds = docs_state(f, self.names)
            for kind, docs in ds.items():
                s = _sig([(d["key"], d.get("title"), d.get("sub"), d.get("body"), d.get("usd"), d.get("spam"), d.get("cks"), d.get("xks"), d.get("hs"))
                          for d in docs])
                if self.ix.meta_get("sig:st:" + kind) != s:
                    with self.ix.tx():
                        self.ix.replace_groups(["st:" + kind], docs)
                        self.ix.meta_set("sig:st:" + kind, s)
            self._last_out = out
            if isinstance(self._mig, dict):
                self._mig["state"] = True
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
                with self.ix.tx():
                    self.ix.replace_groups(["ev:" + iso], docs_events(ix, pos_pnl, self.names, iso))
                    self.ix.meta_set("sig:ev:" + iso, s)
            gone = [d for d in have if d not in ix]
            if gone:
                with self.ix.tx() as c9:
                    self.ix.replace_groups(["ev:" + d for d in gone], [])
                    for part in _chunks(["sig:ev:" + d for d in gone]):
                        c9.execute("DELETE FROM meta WHERE k IN (%s)" % ",".join("?" * len(part)), part)
            self._last_dix = dix
            if isinstance(self._mig, dict):
                self._mig["events"] = True

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
                with self.ix.tx():
                    self.ix.replace_groups(["f:" + kind], fn())
                    self.ix.meta_set("sig:f:" + kind, s)
        if isinstance(self._mig, dict):
            self._mig["files"] = True

    def feed_nft(self):
        if not self.nft_fn:
            if isinstance(self._mig, dict):
                self._mig["nft"] = "skip"
            return
        if self.clock() - self.last_nft < NFT_EVERY_S and not (isinstance(self._mig, dict) and not self._mig.get("nft")):
            return
        self.last_nft = self.clock()
        try:
            v = self.nft_fn()
        except Exception as e:
            log.warning("검색 색인: NFT 보기 실패(무시): %s", type(e).__name__)
            return
        docs = docs_nft(v, self.names)
        s = _sig([(d["key"], d["title"], d["sub"], d["spam"], d.get("cks")) for d in docs])
        if self.ix.meta_get("sig:nft") != s:
            with self.ix.tx():
                self.ix.replace_groups(["nft"], docs)
                self.ix.meta_set("sig:nft", s)
        if isinstance(self._mig, dict):
            self._mig["nft"] = True

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
        return self.ix.replace("kind = 'tx'", (), ledger_tx_docs(lc, self.names))

    def feed_ledger(self):
        lp = self.ledger_path
        if not os.path.exists(lp):
            if isinstance(self._mig, dict):
                self._mig["ledger"] = "skip"
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
        lc = sqlite3.connect(common.sqlite_ro_uri(lp), uri=True, timeout=10)
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
                agg9 = {"ino": ino, "mx": mx, "tot": self._ltot(lc, "AND posting_id <= ?", (mx,)), "atot": atot, "v": TX_AGG_V}
                with self.ix.tx():
                    self._tx_rescan(lc)
                    self.ix.meta_set("tx:agg", json.dumps(agg9))
                self._tx_pending, self._tx_rescan_at = False, now
                self._tx_fsig = fsig
                if isinstance(self._mig, dict):
                    self._mig["ledger"] = True
                return
            same_old = old == list(last.get("tot") or []) and atot == list(last.get("atot") or [])
            if mx > l_mx:
                srcs = [tuple(r) for r in lc.execute("SELECT DISTINCT source_ns, source_id FROM postings WHERE source_kind = 'chain_tx' AND posting_id > ?", (l_mx,))]
                docs = list(ledger_tx_docs(lc, self.names, only=srcs))
                self.ix.replace_keys([f"tx:{ns}:{sid}" for ns, sid in srcs], docs)
            if not same_old:
                self._tx_pending = True
            if self._tx_pending and now - self._tx_rescan_at >= TX_RESCAN_S:
                with self.ix.tx():
                    self._tx_rescan(lc)
                    self.ix.meta_set("tx:agg", json.dumps({"ino": ino, "mx": mx, "tot": self._ltot(lc, "AND posting_id <= ?", (mx,)), "atot": atot, "v": TX_AGG_V}))
                self._tx_pending, self._tx_rescan_at = False, now
                self._tx_fsig = fsig
                return
            elif self._tx_pending:
                self.ix.meta_set("tx:agg", json.dumps(dict(last, mx=mx, v=TX_AGG_V)))
                self._tx_fsig = fsig
                return
            self.ix.meta_set("tx:agg", json.dumps({"ino": ino, "mx": mx, "tot": self._ltot(lc, "AND posting_id <= ?", (mx,)), "atot": atot, "v": TX_AGG_V}))
            self._tx_fsig = fsig
        finally:
            lc.close()

    def _mig_start(self):
        if self._mig is not None:
            return
        self.ix.open()
        if str(self.ix.rowv) == str(ROWV):
            self._mig = False
            return
        self._mig = {"state": "skip" if not self.state_fn else False, "events": "skip" if not self.state_fn else False, "files": False,
                     "nft": "skip" if not self.nft_fn else False, "ledger": False, "t0": self.clock()}
        with self.ix.tx() as c9:
            c9.execute("DELETE FROM meta WHERE k LIKE 'sig:%' OR k IN ('tx:last', 'tx:agg')")
        self._last_out = self._last_dix = None
        self._tx_fsig = None
        log.info("검색 색인: 행 형식 %s → %s 바꾸는 중(그룹마다 한 트랜잭션 · 검색은 계속)", self.ix.rowv, ROWV)

    def _mig_finish(self):
        m = self._mig
        if not isinstance(m, dict) or not all(m.get(k) for k in ("state", "events", "files", "nft", "ledger")):
            return
        src_kinds = {"state": ("coin", "outflow", "wallet", "deposit"), "events": ("event",), "files": ("memo", "review", "other"), "nft": ("nft",), "ledger": ("tx",)}
        purge = [k9 for s9, ks9 in src_kinds.items() if m.get(s9) is True for k9 in ks9]
        with self.ix.tx() as c9:
            ids = [r[0] for r in c9.execute("SELECT id FROM docs WHERE h IS NULL AND kind IN (%s)" % ",".join("?" * len(purge)), purge)] if purge else []
            self.ix._del_ids(c9, ids)
            left = c9.execute("SELECT count(*) FROM docs WHERE h IS NULL").fetchone()[0]
            if not left:
                c9.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('rowv', ?)", (str(ROWV),))
        self._mig = False
        if left:
            log.warning("검색 색인: 원천을 못 읽은 옛 행 %d 개가 남아 형식 완료를 미룸(다음 기동 때 다시)", left)
            return
        self.ix.rowv = str(ROWV)
        try:
            self.ix.maintain(full=True)
            vac = self.ix.vacuum_if_bloated()
        except sqlite3.Error as e:
            vac = None
            log.warning("검색 색인: 정리 실패(다음 6시간에 다시): %s", common.safe_err(e)[:120])
        self._chg_full = 0
        log.info("검색 색인: 행 형식 %s 완료(%.0f초 · 옛 행 %d 정리 · 크기 %s)", ROWV, self.clock() - m["t0"], len(ids), vac)

    def tick(self):
        with self.mu:
            now = self.clock()
            self._mig_start()
            full9 = False
            if now - self.last_full >= FULL_EVERY_S:
                if self.last_full:
                    with self.ix.tx() as c9:
                        c9.execute("DELETE FROM meta WHERE k LIKE 'sig:%' OR k IN ('tx:last', 'tx:agg')")
                    self._last_out = self._last_dix = None
                    self._tx_fsig = None
                    full9 = True
                self.last_full = now
            self._names_meta()
            out = dix = None
            if self.state_fn:
                try:
                    out, dix = self.state_fn()
                except Exception as e:
                    log.warning("검색 색인: 상태 읽기 실패(무시): %s", type(e).__name__)
            w0 = self.ix.writes
            c0 = self.ix.changed
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
            self._mig_finish()
            dc = self.ix.changed - c0
            self._chg_full += dc
            try:
                if full9 and self._chg_full >= 2000:
                    self.ix.maintain(full=True)
                    self._chg_full = 0
                elif dc >= 200:
                    self.ix.maintain(full=False)
            except sqlite3.Error as e:
                log.warning("검색 색인: 병합 실패(다음 회차): %s", common.safe_err(e)[:120])
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
    try:
        INDEXER.ix.open()
    except Exception as e:
        log.warning("검색 색인 열기 실패(첫 회차에 다시): %s", common.safe_err(e)[:160])
    threading.Thread(target=INDEXER.loop, daemon=True, name="search-index").start()
    return INDEXER


_FILTER_RE = re.compile(r"(?<!\S)(coin|chain|type|after|before|pnl|amt|addr|tx):(\S+)", re.I)
_FILT2_RE = re.compile(r"^(-?)([A-Za-z_]{2,12}):(.+)$")
_KNOWN_F = {"coin", "sym", "chain", "type", "kind", "after", "before", "on", "pnl", "amt", "addr", "tx", "wallet", "ex", "has"}
_NEG_OK = {"coin", "sym", "chain", "type", "kind", "ex", "has", "wallet"}
_EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_EVM_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_SHORT_HEX = re.compile(r"^(0x)?([0-9a-fA-F]{2,62})(?:\.{2,3}|…)([0-9a-fA-F]{2,62})$")
_SHORT_B58 = re.compile(r"^([1-9A-HJ-NP-Za-km-z]{3,60})(?:\.{2,3}|…)([1-9A-HJ-NP-Za-km-z]{3,60})$")
_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,90}$")
_B58P = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{4,31}$")
_HEXP = re.compile(r"^(0x[0-9a-fA-F]{2,63}|[0-9a-fA-F]{6,63})$")
_TICK = re.compile(r"^\$?[A-Z][A-Z0-9]{1,9}$|^[0-9][A-Z][A-Z0-9]{0,8}$")
_NUM = re.compile(r"^[$]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^[$]?\d{4,}(?:\.\d+)?$")
_DIGITS = re.compile(r"^\d{4,15}$")
_CMP = re.compile(r"^(<=|>=|<|>|=|~)?(-?\d+(?:\.\d+)?)$")
_DATEISH = re.compile(r"^\d{1,6}-\d{1,2}(?:-\d{1,2})?$")
_HANGUL = re.compile(r"^[가-힣ㄱ-ㅎ]+$")
SYM_KINDS = ("coin", "event", "tx", "outflow", "memo", "nft")
OFFSET_MAX = (1 << 63) - 1
WALLET_IN_MAX = 400


def _b58p_ok(tl: str) -> bool:
    if not _B58P.fullmatch(tl) or tl.isdigit():
        return False
    mixed = bool(re.search(r"[a-z]", tl) and re.search(r"[A-Z]", tl))
    return (mixed and not re.fullmatch(r"[A-Z][a-z]+", tl)) or (any(ch.isdigit() for ch in tl) and len(tl) >= 8)


def _yr_ok(y) -> bool:
    return DATE_MIN_Y <= int(y) <= DATE_MAX_Y


def _month_end(y, m):
    return f"{int(y):04d}-{int(m):02d}-{calendar.monthrange(int(y), int(m))[1]:02d}"


def _date_why(tok: str):
    t = str(tok or "").strip()
    m = re.fullmatch(r"(\d{1,6})-(\d{1,2})(?:-(\d{1,2}))?", t)
    if not m:
        return None
    try:
        if not _yr_ok(m[1]):
            return f"날짜 범위({DATE_MIN_Y}~{DATE_MAX_Y}) 밖"
    except ValueError:
        return "날짜를 알아듣지 못했어요"
    return "없는 날짜"


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
        if not _yr_ok(m[1]):
            return None
        try:
            s = datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%Y-%m-%d")
            return s, s
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m and 1 <= int(m[2]) <= 12 and _yr_ok(m[1]):
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


def alias_syms(tok: str, held=None):
    t = nfkc(tok or "").strip()
    if not t:
        return [], None
    if t in KO_ALL:
        return [KO_ALL[t]], "exact"
    if len(t) < 2 or not _HANGUL.fullmatch(t):
        return [], None
    cho_only = all(ch in _CHO_SET for ch in t)
    if not cho_only and any(ch in _CHO_SET for ch in t):
        return [], None
    cands = []
    for name, sym in KO_ALL.items():
        if cho_only:
            cn = choseong(name)
            if cn == t:
                cands.append((0, len(name), sym))
            elif cn.startswith(t):
                cands.append((1, len(name), sym))
        elif name.startswith(t):
            cands.append((1, len(name), sym))
    if held is not None:
        cands = [c for c in cands if c[0] == 0 or c[2] in held]
    cands.sort()
    out = []
    for _r, _n, sym in cands:
        if sym not in out:
            out.append(sym)
    return out[:4], ("cho" if cho_only else "prefix") if out else None


def krw_rate(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 100 <= x <= 10000 else None


def parse_query(q: str, today: datetime = None, held=None, names=None):
    today = today or datetime.now(KST)
    nm = names if isinstance(names, Names) else NAMES
    q = nfkc(re.sub(r"[\x00-\x1f\x7f]", " ", str(q or "")))[:Q_MAX]
    text = re.sub(r"(\d{1,2})월\s+(\d{1,2})일", r"\1월\2일", q)
    text = re.sub(r"(이번|지난)\s+(주|달)", r"\1\2", text)
    out = {"text": "", "filters": {}, "neg": {}, "ignored": [], "detect": "text", "tokens": [], "ticker": None, "tickers": [], "alias": [],
           "hexp": [], "exact": [], "short": [], "b58p": [], "numtext": [], "date": None, "amt_near": None}
    f, neg, ign = out["filters"], out["neg"], out["ignored"]
    rest = []
    for t in text.split():
        m = _FILT2_RE.match(t)
        if not m or m.group(2).lower() in ("http", "https", "ftp", "mailto") or m.group(3).startswith("//"):
            rest.append(t)
            continue
        is_neg, key, val = m.group(1) == "-", m.group(2).lower(), m.group(3)
        key = {"sym": "coin", "kind": "type"}.get(key, key)
        if key not in _KNOWN_F:
            ign.append({"t": t[:60], "why": "모르는 조건"})
            continue
        if is_neg and key not in _NEG_OK:
            ign.append({"t": t[:60], "why": "빼기(-)를 쓸 수 없는 조건"})
            continue
        v = None
        if key == "coin":
            v = (nfkc(val) or "").strip().upper()[:30] or None
        elif key == "chain":
            v = nm.chain(val) or (val.lower() if re.fullmatch(r"[a-z0-9_.-]{2,24}", val.lower()) else None)
            if v is None:
                ign.append({"t": t[:60], "why": "모르는 체인"})
                continue
        elif key == "type":
            v = TYPE_ALIAS.get(val.lower(), TYPE_ALIAS.get(val, val.lower()))
            if v not in TYPES:
                ign.append({"t": t[:60], "why": "모르는 종류(swap·buy·sell·deposit·withdraw·lp·gas·transfer)"})
                continue
        elif key == "ex":
            v = ex_key(val) or (val.lower() if re.fullmatch(r"[a-z0-9_.-]{2,24}", val.lower()) else None)
            if v is None:
                ign.append({"t": t[:60], "why": "모르는 거래소"})
                continue
        elif key == "has":
            v = "memo" if val.lower() in ("memo", "memos", "메모", "근거") else None
            if v is None:
                ign.append({"t": t[:60], "why": "has: 는 memo 만 알아요"})
                continue
        elif key == "wallet":
            v = (nfkc(val) or "").strip()[:60] or None
        elif key in ("after", "before", "on"):
            r = _date_range(val, today)
            if not r:
                ign.append({"t": t[:60], "why": _date_why(val) or "날짜를 알아듣지 못했어요"})
                continue
            if key in ("after", "on"):
                f["after"] = r[0]
            if key in ("before", "on"):
                f["before"] = r[1]
            continue
        elif key in ("pnl", "amt"):
            m2 = _CMP.fullmatch(val.replace(",", "").replace("$", ""))
            if not m2:
                ign.append({"t": t[:60], "why": "숫자 조건을 알아듣지 못했어요"})
                continue
            v = (m2.group(1) or "=") + m2.group(2)
        elif key in ("addr", "tx"):
            v = val[:90]
        if v is None:
            ign.append({"t": t[:60], "why": "값이 비었어요"})
            continue
        if is_neg:
            neg.setdefault(key, [])
            if v not in neg[key]:
                neg[key].append(v)
        else:
            f[key] = v
    toks = []
    for t in rest:
        tl = t.strip()
        if not tl:
            continue
        if _EVM_ADDR.fullmatch(tl):
            out["exact"].append(("addr", tl.lower()))
            out["detect"] = "addr"
            continue
        if _EVM_TX.fullmatch(tl):
            out["exact"].append(("tx", tl.lower()))
            out["detect"] = "tx"
            continue
        if _HEX64.fullmatch(tl):
            out["exact"].append(("tx", "0x" + tl.lower()))
            out["detect"] = "tx"
            continue
        m = _SHORT_HEX.fullmatch(tl)
        if m and (m.group(1) or len(m.group(2)) + len(m.group(3)) >= 8) and not (m.group(2) + m.group(3)).isalpha():
            pre = ("0x" if m.group(1) else "") + m.group(2).lower()
            out["short"].append((pre, m.group(3).lower(), True))
            out["detect"] = "short"
            continue
        m = _SHORT_B58.fullmatch(tl)
        if m and (any(ch.isdigit() for ch in m.group(1) + m.group(2)) or (re.search(r"[a-z]", tl) and re.search(r"[A-Z]", tl))):
            out["short"].append((m.group(1), m.group(2), False))
            out["detect"] = "short"
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
        if _DATEISH.fullmatch(tl) and _date_why(tl):
            ign.append({"t": tl[:60], "why": _date_why(tl)})
            continue
        if _DIGITS.fullmatch(tl) and int(tl) >= 1000:
            out["amt_near"] = float(int(tl))
            out["numtext"].append(tl)
            out["detect"] = "amount"
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
        if _TICK.fullmatch(tl):
            tk = tl.lstrip("$").upper()
            if tk not in out["tickers"]:
                out["tickers"].append(tk)
            out["ticker"] = out["ticker"] or tk
            out["detect"] = "ticker"
            continue
        if _b58p_ok(tl):
            out["b58p"].append(tl)
            out["detect"] = "b58prefix"
            continue
        if _HANGUL.fullmatch(tl):
            syms, mode = alias_syms(tl, held)
            if syms:
                out["alias"].append((tl, syms, mode))
                out["ticker"] = out["ticker"] or syms[0]
                out["detect"] = "ticker"
                if mode == "cho":
                    continue
        toks.append(tl[:60])
    out["tokens"] = toks[:8]
    out["text"] = " ".join(rest)
    if out["date"]:
        f.setdefault("after", out["date"][0])
        f.setdefault("before", out["date"][1])
    if out["amt_near"] is not None and "amt" not in f and not out["numtext"]:
        f["amt"] = "~" + (str(int(out["amt_near"])) if out["amt_near"] == int(out["amt_near"]) else str(out["amt_near"]))
    if out["numtext"] and "amt" not in f:
        f["amt"] = "~" + str(int(out["amt_near"]))
        out["amt_or_text"] = True
    return out


def _fts_phrase(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


def _lesc(tok: str) -> str:
    return str(tok).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(tok: str) -> str:
    return "%" + _lesc(tok) + "%"


def _word(tok: str) -> str:
    return "% " + _lesc(tok) + " %"


_WORD_RX = {}


def _wordhit(text, w):
    if not text or not w:
        return 0
    rx = _WORD_RX.get(w)
    if rx is None:
        if len(_WORD_RX) > 200:
            _WORD_RX.clear()
        rx = _WORD_RX[w] = re.compile(r"(?<![0-9A-Za-z])" + re.escape(w) + r"(?![0-9A-Za-z])", re.I)
    return 1 if rx.search(text) else 0


def _text_cond(tok, fts_on):
    if fts_on and len(tok) >= 3:
        return "d.id IN (SELECT rowid FROM fts WHERE fts MATCH ?)", [_fts_phrase(tok)]
    return "(d.title LIKE ? ESCAPE '\\' OR d.sub LIKE ? ESCAPE '\\' OR d.body LIKE ? ESCAPE '\\')", [_like(tok)] * 3


def _pref_cond(col, v):
    return f"(d.{col} >= ? AND d.{col} < ?)", [v, v + "￿"]


def _idq(parts, wparts=()):
    sq = [f"SELECT id FROM docs WHERE {c9}" for c9, _a in parts] + [f"SELECT id FROM tg WHERE kind = 'tx' AND {c9}" for c9, _a in wparts]
    return "d.id IN (" + " UNION ALL ".join(sq) + ")", [x for _c, a in parts for x in a] + [x for _c, a in wparts for x in a]


def _wal_cond(vals, kind, ctx):
    c9, a9 = _in_list(vals)
    if kind == "tx" and ctx.get("has_tg", True):
        c10, a10 = _in_list(["w:" + v for v in vals])
        pos = f"d.id IN (SELECT id FROM docs WHERE addr_l IN {c9} UNION SELECT id FROM tg WHERE t IN {c10} AND kind = 'tx')"
        return pos, "NOT " + pos, a9 + a10
    return "d.addr_l IN " + c9, "(d.addr_l IS NULL OR d.addr_l NOT IN " + c9 + ")", a9


def _legacy_tag_cond(t9, a="d"):
    k, _, v = t9.partition(":")
    if k == "s":
        return f"({a}.sym_u = ? OR {a}.syms LIKE ? ESCAPE '\\')", [v, _word(v)]
    if k == "c":
        return f"({a}.chain_l = ? OR {a}.chains LIKE ? ESCAPE '\\')", [v, _word(v)]
    if k == "ty":
        if v in ("sell", "buy"):
            return f"({a}.etype = ? OR ({a}.etype = 'swap' AND {a}.title LIKE ?))", [v, "%" + ("매도" if v == "sell" else "매수") + "%"]
        return f"{a}.etype = ?", [v]
    if k == "x":
        return f"({a}.sub LIKE ? ESCAPE '\\')", ["%" + _lesc(v) + "%"]
    return "0", []


def _mixed_tag_cond(t9, kind):
    lc9, la9 = _legacy_tag_cond(t9, "o")
    return (f"d.id IN (SELECT id FROM tg WHERE t = ? AND kind = ? UNION ALL SELECT o.id FROM docs o WHERE o.kind = ? AND o.h IS NULL AND {lc9})",
            [t9, kind, kind] + la9)


def _memo_cond(kind, has_tg=True):
    dm = "m.kind = 'memo' AND m.key >= 'dm:' AND m.key < 'dm;'"
    if kind == "memo":
        return "1", []
    if kind == "event":
        return (f"(d.date IN (SELECT m.date FROM docs m WHERE {dm}) AND EXISTS (SELECT 1 FROM docs m WHERE {dm} AND m.date = d.date AND m.sym_u = d.sym_u))", [])
    if kind == "tx" and not has_tg:
        return (f"(d.date IN (SELECT m.date FROM docs m WHERE {dm}) AND EXISTS (SELECT 1 FROM docs m WHERE {dm} AND m.date = d.date "
                "AND d.syms LIKE '% ' || m.sym_u || ' %'))", [])
    if kind == "outflow" and not has_tg:
        return "0", []
    if kind == "tx":
        return (f"(d.date IN (SELECT m.date FROM docs m WHERE {dm}) AND EXISTS (SELECT 1 FROM docs m JOIN tg x ON x.id = d.id AND x.t = 's:' || m.sym_u "
                f"WHERE {dm} AND m.date = d.date))", [])
    if kind == "coin":
        return "EXISTS (SELECT 1 FROM docs m WHERE m.kind = 'memo' AND m.sym_u = d.sym_u)", []
    if kind == "outflow":
        return "EXISTS (SELECT 1 FROM tg x WHERE x.id = d.id AND x.t = 'h:memo')", []
    return "0", []


def _kind_query(p, kind, fts_on, ctx):
    f, neg = p["filters"], p.get("neg") or {}
    where, args, tags = [], [], []
    symk = kind in SYM_KINDS
    if f.get("coin"):
        tags.append("s:" + f["coin"])
    if f.get("chain"):
        tags.append("c:" + f["chain"])
    if f.get("type"):
        tags.append("ty:" + f["type"])
    if f.get("ex"):
        tags.append("x:" + f["ex"])
    for tk in p.get("tickers") or ():
        if symk:
            tags.append("s:" + tk)
        else:
            c9, a9 = _text_cond(tk, fts_on)
            where.append(f"({c9} AND tjw(d.title || ' ' || COALESCE(d.sub, '') || ' ' || COALESCE(d.body, ''), ?))")
            args += a9 + [tk]
    ntags = []
    for k9, pre in (("coin", "s:"), ("chain", "c:"), ("type", "ty:"), ("ex", "x:")):
        for v9 in neg.get(k9) or ():
            ntags.append(pre + v9)
    if f.get("has") == "memo":
        c9, a9 = _memo_cond(kind, ctx.get("has_tg", True))
        if c9 == "0":
            return {"skip": True}
        if c9 != "1":
            where.append(c9)
            args += a9
    if "memo" in (neg.get("has") or ()):
        c9, a9 = _memo_cond(kind, ctx.get("has_tg", True))
        if c9 == "1":
            return {"skip": True}
        if c9 != "0":
            where.append("NOT " + c9)
            args += a9
    if ctx.get("wallet") is not None:
        wl = ctx["wallet"]
        if not wl:
            return {"skip": True}
        c9, _n9, a9 = _wal_cond(wl, kind, ctx)
        where.append(c9)
        args += a9
    wn = list(dict.fromkeys(a for wl in ctx.get("wallet_neg") or () for a in wl))
    if wn:
        _p9, c9, a9 = _wal_cond(wn, kind, ctx)
        where.append(c9)
        args += a9
    wtg = kind == "tx" and ctx.get("has_tg", True)
    wrng = lambda v9: [("t >= ? AND t < ?", ["w:" + v9, "w:" + v9 + "\uffff"])] if wtg else []
    if f.get("after"):
        where.append("d.date >= ?")
        args.append(f["after"])
    if f.get("before"):
        where.append("d.date <= ?")
        args.append(f["before"])
    for col, k in (("pnl", "pnl"), ("usd", "amt")):
        v = f.get(k)
        if not v or (k == "amt" and p.get("amt_or_text")):
            continue
        if k == "pnl" and v in ("<0", ">0") and ctx.get("has_tg", True) and not ctx.get("mixed"):
            tags.append("p:-" if v == "<0" else "p:+")
            continue
        if v.startswith("~"):
            x = float(v[1:])
            kr9 = p.get("krw_rate") if k == "amt" else None
            if kr9:
                where.append(f"d.{col} IS NOT NULL AND (abs(d.{col}) BETWEEN ? AND ? OR abs(d.{col}) BETWEEN ? AND ?)")
                args += [x * 0.99, x * 1.01, x / kr9 * 0.95, x / kr9 * 1.05]
            else:
                where.append(f"d.{col} IS NOT NULL AND abs(d.{col}) BETWEEN ? AND ?")
                args += [x * 0.99, x * 1.01]
        else:
            m = _CMP.fullmatch(v)
            op, x = m.group(1) or "=", float(m.group(2))
            where.append(f"d.{col} IS NOT NULL AND {'abs(d.' + col + ')' if k == 'amt' else 'd.' + col} {op} ?")
            args.append(x)
    rng = lambda col, v9: (f"{col} >= ? AND {col} < ?", [v9, v9 + "￿"])
    for k, col in (("addr", "addr_l"), ("tx", "tx_l")):
        v = f.get(k)
        if v:
            c9, a9 = _idq([rng(col, _addr_norm(v))], wrng(_addr_norm(v)) if k == "addr" else ())
            where.append(c9)
            args += a9
    for kd, v in p["exact"]:
        c9, a9 = _idq([("addr_l = ?", [v]), ("tx_l = ?", [v])], [("t = ?", ["w:" + v])] if wtg else ())
        where.append(c9)
        args += a9
    for h in p["hexp"]:
        hv = [h] if h.startswith("0x") else [h, "0x" + h]
        c9, a9 = _idq([rng(col, v9) for v9 in hv for col in ("addr_l", "tx_l")], [x for v9 in hv for x in wrng(v9)])
        where.append(c9)
        args += a9
    for pre, suf, is_hex in p.get("short") or ():
        parts, wp = [], []
        for v9 in ([pre] if (not is_hex or pre.startswith("0x")) else [pre, "0x" + pre]):
            for col in ("addr_l", "tx_l"):
                parts.append((f"{col} >= ? AND {col} < ? AND substr({col}, -?) = ?", [v9, v9 + "￿", len(suf), suf]))
                if len(v9) >= 6 and len(suf) >= 4:
                    parts.append((f"{col} = ?", [v9[:6] + "…" + suf[-4:]]))
            if wtg:
                wp.append(("t >= ? AND t < ? AND substr(t, -?) = ?", ["w:" + v9, "w:" + v9 + "￿", len(suf), suf]))
        c9, a9 = _idq(parts, wp)
        where.append(c9)
        args += a9
    for b in p.get("b58p") or ():
        c1, a1 = _idq([rng("addr_l", b), rng("tx_l", b)], wrng(b))
        c3, a3 = _text_cond(b, fts_on)
        where.append(f"({c1} OR ({c3} AND instr(d.title || ' ' || COALESCE(d.sub, '') || ' ' || COALESCE(d.body, ''), ?) > 0))")
        args += a1 + a3 + [b]
    for tok in p.get("numtext") or ():
        x = float(int(tok))
        c3, a3 = _text_cond(tok, fts_on)
        kr9 = p.get("krw_rate")
        if kr9:
            where.append(f"((d.usd IS NOT NULL AND (abs(d.usd) BETWEEN ? AND ? OR abs(d.usd) BETWEEN ? AND ?)) OR {c3})")
            args += [x * 0.99, x * 1.01, x / kr9 * 0.95, x / kr9 * 1.05] + a3
        else:
            where.append(f"((d.usd IS NOT NULL AND abs(d.usd) BETWEEN ? AND ?) OR {c3})")
            args += [x * 0.99, x * 1.01] + a3
    for tl, syms, mode in p.get("alias") or ():
        if ctx.get("has_tg", True):
            sq = "(d.id IN (SELECT x.id FROM tg x WHERE x.kind = ? AND x.t IN (%s))" % ",".join("?" * len(syms)) + (" OR d.sym_u IN (%s))" % ",".join("?" * len(syms)) if ctx.get("mixed") else ")")
            sa = [kind] + ["s:" + s9 for s9 in syms] + (list(syms) if ctx.get("mixed") else [])
        else:
            sq = "d.sym_u IN (%s)" % ",".join("?" * len(syms))
            sa = list(syms)
        if mode == "cho":
            if not symk:
                return {"skip": True}
            where.append(sq)
            args += sa
        else:
            c3, a3 = _text_cond(tl, fts_on)
            where.append(f"({sq} OR {c3})" if symk else c3)
            args += (sa + a3) if symk else a3
    fts_terms = []
    alias_toks = {a[0] for a in p.get("alias") or ()}
    for t in p["tokens"]:
        if t in alias_toks:
            continue
        if fts_on and len(t) >= 3:
            fts_terms.append(_fts_phrase(t))
        else:
            c9, a9 = _text_cond(t, False)
            where.append(c9)
            args += a9
    fts_q = " AND ".join(fts_terms) if fts_terms else None
    tier = None
    t_syms = list(p.get("tickers") or []) + [a[1][0] for a in (p.get("alias") or ()) if a[1]]
    t_alt = [s9 for a in (p.get("alias") or ()) for s9 in a[1][1:]] or [""]
    first = p["tokens"][0] if p["tokens"] else ""
    if first and not t_syms:
        t_syms = [first.upper()]
    if t_syms or first:
        pre9 = (t_syms[0] if t_syms else first.upper())
        tier = ("(CASE WHEN d.sym_u IN (%s) THEN 0 WHEN (d.sym_u IN (%s) OR d.sym_u LIKE ? ESCAPE '\\' OR d.title LIKE ? ESCAPE '\\') THEN 1 ELSE 2 END)"
                % (",".join("?" * len(t_syms or [""])), ",".join("?" * len(t_alt))),
                list(t_syms or [""]) + t_alt + [_lesc(pre9) + "%", _lesc(first or pre9) + "%"])
    return {"skip": False, "tags": list(dict.fromkeys(tags)), "ntags": ntags, "where": where, "args": args, "tier": tier, "fts": fts_q}


SNIP_W = 76


def _needles(p) -> list:
    return [x for x in ([*p["tokens"], *p["hexp"], *(p.get("tickers") or []), *(p.get("b58p") or []), *(p.get("numtext") or [])]
                        + [a[0] for a in p.get("alias") or () if a[2] != "cho"]
                        + [x9[0] for x9 in p.get("short") or ()] + ([p["ticker"]] if p.get("ticker") else [])) if x]


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


def _held_syms(c):
    return {r[0][2:] for r in c.execute("SELECT t FROM tg WHERE kind = 'coin' AND t >= 's:' AND t < 's;'")}


def _in_list(vals):
    vals = list(vals)
    if len(vals) <= WALLET_IN_MAX:
        return "(%s)" % ",".join("?" * len(vals)), vals
    return "(SELECT value FROM json_each(?))", [json.dumps(vals, ensure_ascii=False)]


def _wallet_addrs(c, val):
    v = (nfkc(val) or "").strip()
    vl = v.casefold()
    rows = []
    for addr, body in c.execute("SELECT addr, body FROM docs WHERE kind = 'wallet'"):
        al = str(body or "")
        al = al[3:] if al.startswith("지갑 ") else al
        rows.append((_addr_norm(addr), al.strip().casefold()))
    for test in (lambda a, al: al == vl, lambda a, al: al.startswith(vl), lambda a, al: vl in al,
                 lambda a, al: len(v) >= 4 and (a.startswith(v.lower()) if v.lower().startswith("0x") else a.startswith(v))):
        hit = list(dict.fromkeys(a for a, al in rows if a and al is not None and test(a, al)))
        if hit:
            return hit
    return []


def search(q: str, kinds=None, limit=None, after=None, before=None, path=None, today: datetime = None, budget_s: float = QUERY_BUDGET_S,
           clock=time.monotonic, offset=None, krw=None) -> dict:
    t0 = clock()
    q = str(q or "")[:Q_MAX]
    path = path or db_path()
    c = None
    held = None
    names = NAMES
    base = {"ok": True, "q": q, "parsed": {}, "tookMs": 0, "building": False, "indexedAt": None, "groups": [], "total": 0, "ignored": []}
    if not _demo() and os.path.exists(path):
        try:
            c = sqlite3.connect(common.sqlite_ro_uri(path), uri=True, timeout=2)
            c.execute("PRAGMA query_only=1")
            c.execute("BEGIN")
        except sqlite3.Error:
            c = None
    try:
        if c is not None and re.search(r"[가-힣ㄱ-ㅎ]", nfkc(q) or ""):
            try:
                held = _held_syms(c)
            except sqlite3.Error:
                held = None
        if c is not None:
            try:
                cm = (c.execute("SELECT v FROM meta WHERE k='chainmap'").fetchone() or [None])[0]
                if cm:
                    names = Names(json.loads(cm))
            except (sqlite3.Error, ValueError, TypeError):
                pass
        p = parse_query(q, today, held=held, names=names)
        p["krw_rate"] = krw_rate(krw)
        ign = p["ignored"]
        for k9, v9 in (("after", after), ("before", before)):
            if not v9:
                continue
            v9 = str(v9)
            m9 = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", v9)
            r9 = None
            if m9 and _yr_ok(m9[1]) and 1 <= int(m9[2]) <= 12:
                try:
                    r9 = (datetime.strptime(v9, "%Y-%m-%d").strftime("%Y-%m-%d") if m9[3] else
                          (f"{m9[1]}-{m9[2]}-01" if k9 == "after" else _month_end(int(m9[1]), int(m9[2]))))
                except ValueError:
                    r9 = None
            if r9:
                p["filters"][k9] = r9
            else:
                ign.append({"t": f"{k9}={v9[:20]}", "why": _date_why(v9) or "날짜를 알아듣지 못했어요"})
        ks = [k for k in (kinds or KINDS) if k in KINDS] or list(KINDS)
        try:
            lim = max(1, min(LIMIT_MAX, int(limit))) if limit not in (None, "") else LIMIT_DEF
        except (TypeError, ValueError):
            lim = LIMIT_DEF
        try:
            off = max(0, min(OFFSET_MAX, int(offset))) if offset not in (None, "") else 0
        except (TypeError, ValueError):
            off = 0
        base["parsed"] = {"text": p["text"], "filters": dict(p["filters"]), "neg": dict(p["neg"]), "detect": p["detect"]}
        base["ignored"] = ign
        if _demo():
            base["demo"] = True
            return base
        if c is None:
            base["building"] = True
            return base
        partial = False
        try:
            meta = dict(c.execute("SELECT k, v FROM meta WHERE k IN ('fts', 'indexedAt', 'built', 'rowv')").fetchall())
            fts_on = meta.get("fts") == "1"
            base["indexedAt"] = int(meta["indexedAt"]) if meta.get("indexedAt") else None
            if INDEXER is not None and INDEXER.indexed_at and os.path.abspath(INDEXER.ix.path) == os.path.abspath(path):
                base["indexedAt"] = INDEXER.indexed_at
            base["building"] = not meta.get("built")
            has_tg = bool(c.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tg'").fetchone())
            mixed = False
            if str(meta.get("rowv")) != str(ROWV):
                base["upgrading"] = True
                mixed = has_tg and bool(c.execute("SELECT 1 FROM docs WHERE h IS NULL LIMIT 1").fetchone()) if has_tg else False
            f = p["filters"]
            for k9, pre in (("chain", "c:"), ("ex", "x:")):
                vals = ([f[k9]] if f.get(k9) else []) + list(p["neg"].get(k9) or [])
                for v9 in vals:
                    known = (k9 == "chain" and (v9 in names.keys)) or (k9 == "ex" and v9 in set(EX_ALIAS.values()))
                    if not known and has_tg and not c.execute("SELECT 1 FROM tg WHERE t = ? LIMIT 1", (pre + v9,)).fetchone():
                        ign.append({"t": f"{k9}:{v9}", "why": "모르는 " + ("체인" if k9 == "chain" else "거래소")})
                        if f.get(k9) == v9:
                            f.pop(k9)
                        else:
                            p["neg"][k9] = [x for x in p["neg"][k9] if x != v9]
            ctx = {"has_tg": has_tg, "mixed": mixed}
            if f.get("wallet"):
                ctx["wallet"] = _wallet_addrs(c, f["wallet"])
                if not ctx["wallet"]:
                    ign.append({"t": "wallet:" + f["wallet"], "why": "그런 지갑 별명이 없어요"})
                    ctx.pop("wallet")
                    f.pop("wallet")
            for v9 in p["neg"].get("wallet") or ():
                a9 = _wallet_addrs(c, v9)
                if a9:
                    ctx.setdefault("wallet_neg", []).append(a9)
                else:
                    ign.append({"t": "-wallet:" + v9, "why": "그런 지갑 별명이 없어요"})
            base["parsed"] = {"text": p["text"], "filters": dict(f), "neg": {k: list(v) for k, v in p["neg"].items() if v}, "detect": p["detect"]}
            has_query = bool(p["tokens"] or p["exact"] or p["hexp"] or p.get("tickers") or p.get("alias") or p.get("short") or p.get("b58p")
                             or p.get("numtext") or any(v for k, v in f.items()) or any(p["neg"].values()))
            if not has_query:
                base["tookMs"] = int((clock() - t0) * 1000)
                return base
            deadline = t0 + max(0.05, budget_s)
            c.set_progress_handler(lambda: 1 if clock() > deadline else 0, PROGRESS_N)
            try:
                c.create_function("tjw", 2, _wordhit, deterministic=True)
            except (TypeError, sqlite3.NotSupportedError):
                c.create_function("tjw", 2, _wordhit)
            order_k = [k for k in KINDS if k in ks]
            if p["detect"] in ("addr", "tx", "hexprefix", "short", "b58prefix"):
                order_k.sort(key=lambda k: {"outflow": 0, "tx": 1, "wallet": 2, "deposit": 3, "event": 4}.get(k, 5))
            groups, total = [], 0
            cols = "d.kind, d.key, d.title, d.sub, d.date, d.ts, d.usd, d.sym, d.chain, d.addr, d.tx, d.anc, d.spam, d.body"
            plans = []
            fts_n = {}

            def _frm(pl, kinds9):
                kw = ("d.kind = ?", [kinds9]) if isinstance(kinds9, str) else ("d.kind IN (%s)" % ",".join("?" * len(kinds9)), list(kinds9))
                if pl["drive"] == "@fts":
                    return "fts CROSS JOIN docs d ON d.id = fts.rowid", ["fts MATCH ?", kw[0]], [pl["kq"]["fts"]] + kw[1]
                if pl["drive"] is not None:
                    return "tg g CROSS JOIN docs d ON d.id = g.id", ["g.t = ?", "g.kind = ?"], [pl["drive"], kinds9]
                return "docs d", [kw[0]], kw[1]
            try:
                for k in order_k:
                    kq = _kind_query(p, k, fts_on, ctx)
                    if kq.get("skip"):
                        continue
                    where, args = list(kq["where"]), list(kq["args"])
                    for t9 in kq["ntags"]:
                        lc9, la9 = _legacy_tag_cond(t9)
                        if not has_tg:
                            where.append(f"NOT {lc9}")
                            args += la9
                        elif mixed:
                            mc9, ma9 = _mixed_tag_cond(t9, k)
                            where.append("NOT " + mc9)
                            args += ma9
                        else:
                            where.append("NOT EXISTS (SELECT 1 FROM tg x WHERE x.id = d.id AND x.t = ?)")
                            args.append(t9)
                    drive, dn = None, None
                    fq9 = kq.get("fts")
                    if fq9 and fq9 not in fts_n:
                        fts_n[fq9] = c.execute("SELECT count(*) FROM fts WHERE fts MATCH ?", (fq9,)).fetchone()[0]
                    if fq9 and fts_n[fq9] == 0:
                        continue
                    if not has_tg or mixed:
                        for t9 in kq["tags"]:
                            lc9, la9 = _legacy_tag_cond(t9)
                            if has_tg:
                                mc9, ma9 = _mixed_tag_cond(t9, k)
                                where.append(mc9)
                                args += ma9
                            else:
                                where.append(lc9)
                                args += la9
                    elif kq["tags"]:
                        for t9 in kq["tags"]:
                            n9 = c.execute("SELECT count(*) FROM tg WHERE t = ? AND kind = ?", (t9, k)).fetchone()[0]
                            if dn is None or n9 < dn:
                                drive, dn = t9, n9
                        if dn == 0:
                            continue
                        if f.get("after") or f.get("before"):
                            nd9 = c.execute("SELECT count(*) FROM docs WHERE kind = ? AND date >= ? AND date <= ?",
                                            (k, f.get("after") or "0000", f.get("before") or "9999")).fetchone()[0]
                            if nd9 == 0:
                                continue
                            if nd9 < dn:
                                drive, dn = None, nd9
                        if f.get("pnl"):
                            np9 = c.execute("SELECT count(*) FROM docs WHERE kind = ? AND pnl IS NOT NULL", (k,)).fetchone()[0]
                            if np9 == 0:
                                continue
                            if np9 < dn:
                                drive, dn = None, np9
                        for t9 in kq["tags"]:
                            if t9 != drive:
                                where.append("EXISTS (SELECT 1 FROM tg x WHERE x.id = d.id AND x.t = ?)")
                                args.append(t9)
                    if fq9:
                        if fts_n[fq9] <= FTS_DRIVE_MAX and (drive is None or fts_n[fq9] < (dn or 0)):
                            if drive is not None:
                                where.append("EXISTS (SELECT 1 FROM tg x WHERE x.id = d.id AND x.t = ?)")
                                args.append(drive)
                            drive, dn = "@fts", fts_n[fq9]
                        else:
                            where.append("d.id IN (SELECT rowid FROM fts WHERE fts MATCH ?)")
                            args.append(fq9)
                    pure9 = has_tg and not mixed and not kq["where"] and not (fq9 and drive != "@fts")
                    plans.append({"k": k, "kq": kq, "where": where, "args": args, "drive": drive, "dn": dn, "n": None, "pure": pure9})
            except sqlite3.OperationalError as e:
                if "interrupt" not in str(e).lower():
                    raise
                partial = True
            try:
                byw = {}
                for pl in plans:
                    if pl["drive"] not in (None, "@fts"):
                        if not pl["where"]:
                            pl["n"] = pl["dn"]
                        elif pl["pure"]:
                            q9 = "SELECT id FROM tg WHERE t = ? AND kind = ?"
                            a9 = [pl["drive"], pl["k"]]
                            for t9 in pl["kq"]["tags"]:
                                if t9 != pl["drive"]:
                                    q9 += " INTERSECT SELECT id FROM tg WHERE t = ? AND kind = ?"
                                    a9 += [t9, pl["k"]]
                            for t9 in pl["kq"]["ntags"]:
                                q9 += " EXCEPT SELECT id FROM tg WHERE t = ? AND kind = ?"
                                a9 += [t9, pl["k"]]
                            pl["n"] = c.execute(f"SELECT count(*) FROM ({q9})", a9).fetchone()[0]
                        else:
                            frm9, w09, a09 = _frm(pl, pl["k"])
                            pl["n"] = c.execute(f"SELECT count(*) FROM {frm9} WHERE " + " AND ".join(w09 + pl["where"]), a09 + pl["args"]).fetchone()[0]
                    else:
                        byw.setdefault((pl["drive"], tuple(pl["where"]), tuple(map(str, pl["args"]))), []).append(pl)
                for _sig9, pls in byw.items():
                    ks9 = [pl["k"] for pl in pls]
                    frm9, w09, a09 = _frm(pls[0], ks9)
                    cnt = dict(c.execute(f"SELECT d.kind, count(*) FROM {frm9} WHERE " + " AND ".join(w09 + pls[0]["where"]) + " GROUP BY d.kind",
                                         a09 + pls[0]["args"]).fetchall())
                    for pl in pls:
                        pl["n"] = cnt.get(pl["k"], 0)
            except sqlite3.OperationalError as e:
                if "interrupt" not in str(e).lower():
                    raise
                partial = True
            deadline = max(deadline, clock() + ITEM_GRACE_S)
            for pl in plans:
                k, kq, drive, n = pl["k"], pl["kq"], pl["drive"], pl["n"]
                if n == 0:
                    continue
                if clock() > deadline:
                    partial = True
                    break
                frm, w0, a0 = _frm(pl, k)
                wsql = " AND ".join(w0 + pl["where"])
                wargs = a0 + pl["args"]
                if kq["tier"] is not None:
                    order = f"d.spam ASC, {kq['tier'][0]} ASC, COALESCE(d.ts, 0) DESC, d.id DESC"
                    oargs = kq["tier"][1]
                elif drive not in (None, "@fts"):
                    order, oargs = "g.ns DESC, g.ts DESC, g.id DESC", []
                else:
                    order, oargs = "d.spam ASC, COALESCE(d.ts, 0) DESC, d.id DESC", []
                try:
                    rows = c.execute(f"SELECT {cols} FROM {frm} WHERE {wsql} ORDER BY {order} LIMIT ? OFFSET ?", wargs + oargs + [lim, off]).fetchall()
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
                if items or n:
                    g = {"kind": k, "n": n, "items": items, "offset": off, "more": (n is None and len(items) >= lim) or (n is not None and off + len(items) < n)}
                    if n is None:
                        g["partial"] = True
                    groups.append(g)
                    total = None if (total is None or n is None) else total + n
            base["groups"] = [g for g in groups if g["items"] or off]
            base["total"] = total
        except sqlite3.Error as e:
            log.warning("검색 실패: %s", common.safe_err(e)[:160])
            base["ok"] = False
            base["error"] = "검색 색인을 읽지 못했어요 — 잠시 뒤 다시"
        if partial:
            base["partial"] = True
        base["tookMs"] = int((clock() - t0) * 1000)
        return base
    finally:
        if c is not None:
            c.close()
