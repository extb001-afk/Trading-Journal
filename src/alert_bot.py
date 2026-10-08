"""Telegram alert sender (price targets, health, daily summaries)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
if __name__ == "__main__":
    common.cpu_reserve_apply()
import health
import alert_prefs as AP

log = common.setup_logging("tj-alert")

SOURCES = ("pending_dm.jsonl", "alerts_web.jsonl", AP.FAST_QUEUE)
FROM_START = frozenset({AP.FAST_QUEUE})
CURSOR_PATH = os.path.join(common.STATE_DIR, "tg_cursor.json")
POLL_SEC = 20
URGENT_TICK = 0.5
URGENT_MAX_PASS = 10
URGENT_LATE = 120
URGENT_REPLAY = 3600
MAX_PER_CYCLE = 15
READ_LINES_MAX = 500
COALESCE_MIN = 4
HOURLY_CAP = 30
_SENT_TIMES = []
TEST_HOURLY = 6
_TEST_TIMES = []
CRIT_SCAN_BYTES = 2 * 1024 * 1024
HOLD_IDS_WARN = 4 * READ_LINES_MAX


def _env():
    out = {}
    try:
        with open(common.ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    out[k] = v
    except OSError:
        pass
    return out


def _tg_creds():
    try:
        import settings_store
        tok = settings_store.env_value(settings_store.TG_TOKEN)
        chat = settings_store.env_value(settings_store.TG_CHAT)
        if tok and chat:
            return tok, chat
    except Exception:
        pass
    env = _env()
    token, chat = env.get("TJ_TG_TOKEN") or None, env.get("TJ_TG_CHAT") or None
    return (token, chat) if token and chat else (None, None)


_tg_credentials = _tg_creds

TG_API_DEFAULT = "https://api.telegram.org"
_TG_API_LOOP = re.compile(r"http://127\.0\.0\.1:\d{1,5}(/[A-Za-z0-9._~/-]*)?")


def _tg_api_base(v=None) -> str:
    v = os.environ.get("TJ_TG_API") if v is None else v
    if not v:
        return TG_API_DEFAULT
    v = str(v).strip().rstrip("/")
    if v == TG_API_DEFAULT or _TG_API_LOOP.fullmatch(v):
        return v
    log.warning("TJ_TG_API 무시 — 공식 주소(%s)나 http://127.0.0.1:<포트> 만 허용(값은 로그에 남기지 않음)", TG_API_DEFAULT)
    return TG_API_DEFAULT


TG_API = _tg_api_base()


_TG_WAIT_UNTIL = [0.0]
TG_RETRY_MAX = 3600


def _retry_after(body) -> float:
    try:
        d = body if isinstance(body, dict) else json.loads(body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body))
        v = float(((d or {}).get("parameters") or {}).get("retry_after") or 0)
        return v if v == v and v > 0 else 0.0
    except Exception:
        return 0.0


def _silent_text(text: str) -> bool:
    return str(text or "").lstrip().startswith(("📋", "✅", "🌙"))


def send_message(token: str, chat: str, text: str, reply_to=None, silent=None):
    now = time.time()
    if now < _TG_WAIT_UNTIL[0]:
        return False, None, f"텔레그램 속도 제한 대기 {int(_TG_WAIT_UNTIL[0] - now) + 1}초"
    text = common.redact_secret_text(text, generic=False)
    params = {"chat_id": chat, "text": text[:3900]}
    if silent or (silent is None and _silent_text(text)):
        params["disable_notification"] = "true"
    if reply_to:
        params["reply_to_message_id"] = str(reply_to)
        params["allow_sending_without_reply"] = "true"
    req = urllib.request.Request(f"{TG_API}/bot{token}/sendMessage", data=urllib.parse.urlencode(params).encode())
    ra = 0.0
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        ok = d.get("ok") is True
        err = None if ok else str(d.get("description") or "ok=false")[:160]
        mid = ((d.get("result") or {}).get("message_id")) if ok else None
        if not ok and int(d.get("error_code") or 0) == 429:
            ra = _retry_after(d) or 30.0
    except urllib.error.HTTPError as e:
        ok, mid, err = False, None, common.redact_secret_text(str(e))[:160]
        if e.code == 429:
            try:
                ra = _retry_after(e.read()) or 30.0
            except Exception:
                ra = 30.0
        log.warning("발송 실패: %s", err)
    except Exception as e:
        ok, mid, err = False, None, common.redact_secret_text(str(e))[:160]
        log.warning("발송 실패: %s", err)
    if ra > 0:
        _TG_WAIT_UNTIL[0] = time.time() + min(ra, TG_RETRY_MAX)
        log.warning("텔레그램 속도 제한(429) — %d초 쉬고 이어서 보냄", int(min(ra, TG_RETRY_MAX)))
        return False, None, f"텔레그램 속도 제한(429) — {int(min(ra, TG_RETRY_MAX))}초 대기"
    health.note_send(ok, err)
    return ok, mid, err


def send(token: str, chat: str, text: str) -> bool:
    return send_message(token, chat, text)[0]


def send_photo(token: str, chat: str, png: bytes, caption: str = "", silent: bool = True):
    now = time.time()
    if now < _TG_WAIT_UNTIL[0]:
        return False, None, f"텔레그램 속도 제한 대기 {int(_TG_WAIT_UNTIL[0] - now) + 1}초"
    caption = common.redact_secret_text(caption or "", generic=False)[:1024]
    bnd = "tjb" + os.urandom(12).hex()
    parts = []
    fields = {"chat_id": str(chat), "caption": caption}
    if silent:
        fields["disable_notification"] = "true"
    for k, v in fields.items():
        parts.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    parts.append(f"--{bnd}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"summary.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
    body = b"".join(parts) + png + f"\r\n--{bnd}--\r\n".encode()
    req = urllib.request.Request(f"{TG_API}/bot{token}/sendPhoto", data=body, headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    ra = 0.0
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        ok = d.get("ok") is True
        err = None if ok else str(d.get("description") or "ok=false")[:160]
        mid = ((d.get("result") or {}).get("message_id")) if ok else None
        if not ok and int(d.get("error_code") or 0) == 429:
            ra = _retry_after(d) or 30.0
    except urllib.error.HTTPError as e:
        ok, mid, err = False, None, common.redact_secret_text(str(e))[:160]
        if e.code == 429:
            try:
                ra = _retry_after(e.read()) or 30.0
            except Exception:
                ra = 30.0
        log.warning("그림 발송 실패: %s", err)
    except Exception as e:
        ok, mid, err = False, None, common.redact_secret_text(str(e))[:160]
        log.warning("그림 발송 실패: %s", err)
    if ra > 0:
        _TG_WAIT_UNTIL[0] = time.time() + min(ra, TG_RETRY_MAX)
        return False, None, f"텔레그램 속도 제한(429) — {int(min(ra, TG_RETRY_MAX))}초 대기"
    health.note_send(ok, err)
    return ok, mid, err


def _tail_end(path: str) -> int:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0
            back = min(size, 65536)
            f.seek(size - back)
            chunk = f.read(back)
    except OSError:
        return 0
    i = chunk.rfind(b"\n")
    return (size - back + i + 1) if i >= 0 else 0


def init_cursor(cursor: dict) -> bool:
    changed = False
    for fn in SOURCES:
        if fn in cursor:
            continue
        path = os.path.join(common.STATE_DIR, fn)
        cursor[fn] = _fast_start(path) if fn in FROM_START else (_tail_end(path) if os.path.exists(path) else 0)
        log.info("%s 커서 초기화 — 백로그 %d바이트 건너뜀(파일 끝에서 시작)", fn, cursor[fn])
        changed = True
    return changed


def _fast_start(path: str, now: float = None) -> int:
    if not os.path.exists(path):
        return 0
    lo = (time.time() if now is None else now) - URGENT_REPLAY
    pos = 0
    try:
        with open(path, "rb") as f:
            for line in f:
                if not line.endswith(b"\n"):
                    break
                try:
                    ts = float((json.loads(line.decode("utf-8", "replace")) or {}).get("ts") or 0)
                except (ValueError, TypeError, AttributeError):
                    ts = 0.0
                if not (1e9 < ts < 1e11) or ts >= lo:
                    return pos
                pos += len(line)
    except OSError:
        return 0
    return pos


def _fast_send_ok(kind, conn=None) -> bool:
    try:
        t9, c9 = _tg_creds()
        if not (t9 and c9):
            return False
        return AP.decide(AP.load(), AP.cat_of(kind), time.time(), conn, kind) == "send"
    except Exception:
        return True


def _fast_to(kind, token, chat):
    if kind in AP.FAST_KINDS:
        t9, c9 = _tg_creds()
        return (t9, c9) if (t9 and c9) else (None, None)
    return token, chat


def read_chunk(path: str, off: int, max_lines: int = READ_LINES_MAX):
    rows = []
    with open(path, "rb") as f:
        f.seek(off)
        pos = off
        while len(rows) < max_lines:
            line = f.readline()
            if not line or not line.endswith(b"\n"):
                break
            pos += len(line)
            try:
                d = json.loads(line.decode("utf-8"))
            except UnicodeDecodeError:
                try:
                    d = json.loads(line.decode("utf-8", "replace"))
                    log.warning("%s 줄(끝 %d바이트)에 UTF-8 아닌 바이트 — 대체 문자로 읽음", os.path.basename(path), pos)
                except ValueError:
                    d = None
                    log.warning("%s 손상 줄(끝 %d바이트, UTF-8 아님) 건너뜀", os.path.basename(path), pos)
            except ValueError:
                d = None
            if d is not None and not isinstance(d, dict):
                d = None
            rows.append((pos, d))
    return rows, (rows[-1][0] if rows else off)


def coalesce_k(rows) -> list:
    by_kind = {}
    first = []
    for i, (o, d) in enumerate(rows):
        if not isinstance(d, dict):
            continue
        k = str(d.get("kind") or "?")
        by_kind.setdefault(k, []).append((o, d))
        first.append((i, k, d, o))
    msgs = []
    done_kinds = set()
    for i, k, d, o in first:
        grp = by_kind[k]
        if len(grp) < COALESCE_MIN or k == AP.TEST_KIND or k in AP.FAST_KINDS:
            msgs.append((i, (_late_note(d) if k in AP.FAST_KINDS else (d.get("text") or f"[{k}] {json.dumps(d, ensure_ascii=False)[:300]}")), k, [o]))
            continue
        if k in done_kinds:
            continue
        done_kinds.add(k)
        last3 = [str(x.get("text") or "").split("\n", 1)[0][:160] for _o, x in grp[-3:]]
        c9 = AP.CAT.get(AP.cat_of(k, d.get("cat"))) or {}
        heads = {str(x.get("text") or "").lstrip()[:1] for _o, x in grp}
        head = "✅" if heads == {"✅"} else "🔴" if AP.tier(c9.get("key")) == "now" else "📋"
        act = {"🔴": "앱에서 하나씩 확인하세요", "✅": "할 일은 없어요"}.get(head, "급한 건 아니에요")
        if AP.tier(c9.get("key")) == "now":
            items = []
            for _o, x in grp:
                ls = [s9.strip() for s9 in str(x.get("text") or "").split("\n") if s9.strip() and not s9.strip().startswith("[보기]")]
                items.append((_o, ls))
            acts = {ls[1] for _o, ls in items if len(ls) > 1}
            common_act = next(iter(acts)) if len(acts) == 1 and all(len(ls) > 1 for _o, ls in items) else None
            if common_act:
                act = common_act.rstrip(".")
            elif acts:
                act = "건마다 할 일을 적었어요" if head != "🔴" else "건마다 할 일을 적었어요 — 하나씩 확인하세요"
            parts, body, cov9 = [], [], []
            for _o, ls in items:
                det = ls[2:] if common_act else ls[1:]
                it = (ls[0].lstrip("🔴📋✅ ") + ("" if not det else " · " + " · ".join(det))) if ls else str(grp[0][1].get("kind") or "")
                if len(it) > 3300:
                    it = it[:3300] + " …(잘림 — 앱에서 확인)"
                if body and sum(len(b9) + 3 for b9 in body) + len(it) > 3400:
                    parts.append((body, cov9))
                    body, cov9 = [], []
                body.append(it)
                cov9.append(_o)
            parts.append((body, cov9))
            for pi, (body, cov9) in enumerate(parts):
                tag = "" if len(parts) == 1 else f" ({pi + 1}/{len(parts)})"
                msgs.append((i, f"{head} {c9.get('label') or '알림'} {len(grp)}건이 한꺼번에 왔어요{tag}\n" + act
                             + (" — 전부:" if len(parts) == 1 else " — 이어서:" if pi else " — 다음 통에 이어서:") + "\n- " + "\n- ".join(body),
                             k, cov9 if pi < len(parts) - 1 else [o9 for o9, _x in grp], pi < len(parts) - 1))
            continue
        msgs.append((i, f"{head} {c9.get('label') or '알림'} {len(grp)}건이 한꺼번에 왔어요\n"
                     + act + f" — 최근 {len(last3)}건:\n- " + "\n- ".join(x.lstrip('🔴📋✅ ') for x in last3), k,
                     [o9 for o9, _x in grp]))
    chunk_end = rows[-1][0] if rows else 0
    out = []
    for j, mj in enumerate(msgs):
        _i, text, k, cov = mj[:4]
        if len(mj) > 4 and mj[4]:
            out.append((None, text, k, cov))
            continue
        nxt = next((m9[0] for m9 in msgs[j + 1:]), None)
        out.append((rows[nxt - 1][0] if nxt else chunk_end, text, k, cov))
    return out


def _late_note(d, now=None) -> str:
    text = str(d.get("text") or f"[{d.get('kind')}]")
    ts9 = _num_ts(d.get("ts"))
    lag = ((time.time() if now is None else now) - ts9) if ts9 else 0
    if lag > URGENT_LATE:
        text += f"\n(감지 {int(lag // 60)}분 전 알림이 늦게 나가요 — 지금 상태는 앱에서 확인하세요)"
    return text


def coalesce(rows) -> list:
    return [(o, t) for o, t, _k, _c in coalesce_k(rows)]


def _cnt(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10 ** 12 else 0


def load_stats() -> dict:
    try:
        raw = common.read_json(AP.STATS_PATH, {}) or {}
    except (Exception, SystemExit):
        raw = {}
    st = {"v": 1, "days": {}, "counted": {}}
    if not isinstance(raw, dict):
        return st
    fs = raw.get("first_seen")
    if AP._num_ok(fs) and 0 < fs < AP.TS_MAX:
        st["first_seen"] = int(fs)
    bf = raw.get("bf_first")
    if AP._num_ok(bf) and 0 < bf < AP.TS_MAX:
        st["bf_first"] = int(bf)
    days = raw.get("days")
    for dk, row in (days.items() if isinstance(days, dict) else ()):
        if not (isinstance(dk, str) and len(dk) == 10 and dk[4] == "-" and dk[7] == "-") or not isinstance(row, dict):
            continue
        r2 = {}
        for cat, c in row.items():
            if cat in AP.CAT and isinstance(c, dict):
                c2 = {f: _cnt(c.get(f)) for f in ("sent", "skip", "held", "daily", "web") if _cnt(c.get(f))}
                if c2:
                    r2[cat] = c2
        if r2:
            st["days"][dk] = r2
    cnt = raw.get("counted")
    for fn in SOURCES:
        v = cnt.get(fn) if isinstance(cnt, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10 ** 15:
            st["counted"][fn] = v
    return st


def save_stats(st: dict, now: float = None) -> None:
    try:
        keep = {AP.day_key((now or time.time()) - i * 86400) for i in range(AP.STATS_KEEP_DAYS)}
        st["days"] = {k: v for k, v in (st.get("days") if isinstance(st.get("days"), dict) else {}).items() if k in keep}
        st.pop("_dirty", None)
        common.atomic_write_json(AP.STATS_PATH, st)
    except Exception as e:
        log.warning("알림 발송 기록 저장 실패: %s", e)


def stat_add(st: dict, cat: str, field: str, n: int = 1, now: float = None) -> None:
    if n <= 0:
        return
    days = st.get("days")
    if not isinstance(days, dict):
        days = st["days"] = {}
    dk = AP.day_key(now)
    day = days.get(dk)
    if not isinstance(day, dict):
        day = days[dk] = {}
    row = day.get(cat)
    if not isinstance(row, dict):
        row = day[cat] = {}
    row[field] = _cnt(row.get(field)) + int(n)
    st["_dirty"] = True


def load_hold() -> dict:
    try:
        raw = common.read_json(AP.HOLD_PATH, {}) or {}
    except (Exception, SystemExit):
        raw = {}
    h = {"n": {}, "items": [], "ids": {fn: [] for fn in SOURCES}}
    if not isinstance(raw, dict):
        return h
    n = raw.get("n")
    for k, v in (n.items() if isinstance(n, dict) else ()):
        if k in AP.CAT and _cnt(v):
            h["n"][k] = _cnt(v)
    for x in (raw.get("items") if isinstance(raw.get("items"), list) else [])[-AP.HOLD_TEXT_MAX:]:
        if isinstance(x, dict) and x.get("cat") in AP.CAT:
            h["items"].append({"cat": x["cat"], "kind": str(x.get("kind") or "")[:40], "text": str(x.get("text") or "")[:300],
                               "ts": _cnt(x.get("ts"))})
    ids = raw.get("ids")
    if isinstance(ids, dict):
        for fn in SOURCES:
            lst = ids.get(fn)
            h["ids"][fn] = sorted({v for v in (lst if isinstance(lst, list) else []) if isinstance(v, int) and not isinstance(v, bool) and v > 0})
    elif isinstance(ids, list):
        for x in ids:
            fn9, _, o9 = str(x).rpartition(":")
            if fn9 in SOURCES and o9.isdigit():
                h["ids"][fn9].append(int(o9))
        for fn in SOURCES:
            h["ids"][fn] = sorted(set(h["ids"][fn]))
    if _cnt(raw.get("since")) and h["n"]:
        h["since"] = _cnt(raw["since"])
    dg = raw.get("dg") if isinstance(raw.get("dg"), dict) else {}
    h["dg"] = {"items": [], "n": {}}
    for k, v in ((dg.get("n") or {}).items() if isinstance(dg.get("n"), dict) else ()):
        if k in AP.CAT and _cnt(v):
            h["dg"]["n"][k] = _cnt(v)
    for k, v in list((dg.get("k") or {}).items() if isinstance(dg.get("k"), dict) else ())[:200]:
        if isinstance(k, str) and 0 < len(k) <= 48 and _cnt(v):
            h["dg"].setdefault("k", {})[k] = _cnt(v)
    if _cnt(dg.get("fix")):
        h["dg"]["fix"] = _cnt(dg["fix"])
    for x in (dg.get("items") if isinstance(dg.get("items"), list) else [])[-DG_ITEMS_MAX:]:
        if isinstance(x, dict) and x.get("cat") in AP.CAT:
            h["dg"]["items"].append({"cat": x["cat"], "kind": str(x.get("kind") or "")[:40], "text": str(x.get("text") or "")[:300],
                                     "ts": _cnt(x.get("ts")), "d": x.get("d") if isinstance(x.get("d"), dict) else None})
    if isinstance(raw.get("dg_day"), str) and len(raw["dg_day"]) == 10:
        h["dg_day"] = raw["dg_day"]
    return h


def save_hold(h: dict) -> bool:
    pend = h.pop("_pend", None)
    try:
        common.atomic_write_json(AP.HOLD_PATH, h)
        return True
    except Exception as e:
        if pend:
            h["_pend"] = pend
        log.warning("보류·하루 요약 재료 저장 실패(커서는 그 줄 앞에 둠): %s", e)
        return False


def _pend_add(h: dict, src, off) -> None:
    if src is not None and off is not None:
        h.setdefault("_pend", {}).setdefault(src, []).append(off)


def held(h: dict, src: str, off: int) -> bool:
    return off in h["ids"].get(src, ())


def mark_done(h: dict, src: str, offs, cursor_off: int) -> bool:
    lst = h["ids"].setdefault(src, [])
    add = [o for o in offs if o > cursor_off and o not in lst]
    lst.extend(add)
    return bool(add)


def hold_add(h: dict, src, off, cat: str, kind: str, text: str, now: float) -> bool:
    if src is not None:
        lst = h["ids"].setdefault(src, [])
        if off in lst:
            return False
        lst.append(off)
        _pend_add(h, src, off)
    h["n"][cat] = _cnt(h["n"].get(cat)) + 1
    h["items"] = (h["items"] + [{"cat": cat, "kind": kind, "text": str(text or "")[:300], "ts": int(now)}])[-AP.HOLD_TEXT_MAX:]
    h.setdefault("since", int(now))
    return True


DG_ITEMS_MAX = 120


RECON_KINDS = ("EXF_RECON", "RECON", "EX_RECON")
_FIX_RE = re.compile(r"(\d[\d,]*)\s*개\s*(?:통화|자산)\s*보정")


def recon_fixed(text, d=None) -> int:
    if isinstance(d, dict) and _cnt(d.get("fixed")):
        return _cnt(d["fixed"])
    m = _FIX_RE.search(str(text or ""))
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return 1
    return 1


def _dg_key(kind, d=None) -> str:
    k = str(kind or "?")[:40]
    if k == "LP_RANGE" and isinstance(d, dict) and isinstance(d.get("out"), bool):
        k += ":out" if d["out"] else ":in"
    return k


def dg_add(h: dict, src, off, cat: str, kind: str, text: str, now: float, d=None) -> bool:
    if src is not None:
        lst = h["ids"].setdefault(src, [])
        if off in lst:
            return False
        lst.append(off)
        _pend_add(h, src, off)
    g = h.setdefault("dg", {"items": [], "n": {}})
    g["n"][cat] = _cnt(g["n"].get(cat)) + 1
    kk = _dg_key(kind, d)
    gk = g.setdefault("k", {})
    if kk in gk or len(gk) < 200:
        gk[kk] = _cnt(gk.get(kk)) + 1
    if kind in RECON_KINDS:
        g["fix"] = _cnt(g.get("fix")) + recon_fixed(text, d)
    it = {"cat": cat, "kind": kind, "text": str(text or "")[:300], "ts": int(now), "d": d if isinstance(d, dict) else None}
    items = g["items"] + [it]
    if len(items) > DG_ITEMS_MAX:
        keep_pnl = [x for x in items if x.get("kind") == "PNL_DAILY"][-1:]
        rest = [x for x in items if x.get("kind") != "PNL_DAILY"][-(DG_ITEMS_MAX - len(keep_pnl)):]
        items = keep_pnl + rest
    g["items"] = items
    return True


def retire_held(h: dict, src: str, cursor_off: int) -> bool:
    lst = h["ids"].get(src) or []
    keep = [o for o in lst if o > cursor_off]
    if len(keep) != len(lst):
        h["ids"][src] = keep
        return True
    return False


def _test_budget(now: float) -> int:
    _TEST_TIMES[:] = [t for t in _TEST_TIMES if now - t < 3600]
    return max(0, TEST_HOURLY - len(_TEST_TIMES))


BAL_KIND = "BALANCE_MISMATCH"


def filter_rows(rows, fn: str, doc: dict, conn, now: float, st: dict, hold: dict, hst: dict = None):
    counted = int(st["counted"].get(fn) or 0)
    out, changed = [], False
    bf_once = False
    tleft = _test_budget(now)
    for off, d in rows:
        if not isinstance(d, dict):
            out.append((off, d))
            continue
        if held(hold, fn, off):
            out.append((off, None))
            continue
        kind = str(d.get("kind") or "?")
        if kind in AP.FAST_KINDS:
            out.append((off, d))
            continue
        if kind == AP.TEST_KIND:
            if tleft > 0:
                tleft -= 1
                out.append((off, d))
            else:
                out.append((off, None))
                if off > counted:
                    log.info("테스트 알림 시간당 %d통 넘음 — 버림", TEST_HOURLY)
            continue
        if kind == BAL_KIND and isinstance(hst, dict) and hst.get("last_eval"):
            if off > counted:
                stat_add(st, AP.cat_of(kind, d.get("cat")), "skip", 1, now)
            out.append((off, None))
            continue
        if kind == BAL_KIND and hst is not None:
            try:
                cov9 = health.bal_covered(hst, d.get("keys"))
            except Exception:
                cov9 = False
            if cov9:
                if off > counted:
                    log.info("잔고 불일치 알림 거름 — 같은 키를 헬스 '잔고 불일치' 경보가 이미 알림(%d건)", len(d.get("keys") or ()))
                out.append((off, None))
                continue
        cat = AP.cat_of(kind, d.get("cat"))
        how = AP.decide(doc, cat, now, conn, kind)
        if how == "web" and kind == AP.FIRST_BACKFILL_KIND and not st.get("bf_first") and not bf_once:
            bf_once = True
            out.append((off, dict(d, text="📋 과거 기록을 다 가져왔어요\n할 일은 없어요 — 이제 손익·보유가 전체 기간 기준이에요.")))
            continue
        if how == "send":
            out.append((off, d))
            continue
        if how == "hold" and hold_add(hold, fn, off, cat, kind, d.get("text") or f"[{kind}]", now):
            changed = True
        if how == "daily" and dg_add(hold, fn, off, cat, kind, d.get("text") or f"[{kind}]", now, d.get("d")):
            changed = True
        if off > counted:
            stat_add(st, cat, {"hold": "held", "daily": "daily", "web": "web"}.get(how, "skip"), 1, now)
        out.append((off, None))
    if rows and rows[-1][0] > counted:
        st["counted"][fn] = rows[-1][0]
        st["_dirty"] = True
    return out, changed


def hold_text(hold: dict, doc: dict, early: bool = False) -> str:
    q = doc.get("quiet") or {}
    n = sum(_cnt(v) for v in hold["n"].values())
    lines = [f"📋 밤({q.get('from', '?')}~{q.get('to', '?')}) 동안 모인 알림 {n}건" + (" — 너무 많이 쌓여 미리 보내요" if early else ""),
             "급한 건 아니에요 — 훑어보고 필요하면 앱에서 확인하세요."]
    for c in AP.CATS:
        k = c["key"]
        if hold["n"].get(k):
            lines.append(f"· {c['label']} {hold['n'][k]}건")
    items = hold["items"][-8:]
    if items:
        lines.append("최근:")
        lines += ["- " + str(x.get("text") or "").split("\n", 1)[0].lstrip("🔴📋✅ ")[:160] for x in items]
    if n > len(items):
        lines.append(f"… 외 {n - len(items)}건(원문 생략 — 위 카테고리별 수에 포함)")
    return "\n".join(lines)


def flush_hold(token, chat, doc: dict, conn, now: float, st: dict, hold: dict, force: bool = False) -> bool:
    if not hold["n"] or (AP.in_quiet(doc, now) and not force):
        return False
    live = {k for k in hold["n"] if AP.effective(doc, k, now, conn)}
    if not live:
        hold.update(items=[], n={})
        hold.pop("since", None)
        save_hold(hold)
        return True
    hold["n"] = {k: v for k, v in hold["n"].items() if k in live}
    hold["items"] = [x for x in hold["items"] if x.get("cat") in live]
    if not send(token, chat, hold_text(hold, doc, early=force)):
        return False
    _SENT_TIMES.append(time.time())
    for k in hold["n"]:
        try:
            stat_add(st, k, "sent", 1, now)
        except Exception as e:
            log.warning("발송 기록 실패(무시): %s", e)
    hold.update(items=[], n={})
    hold.pop("since", None)
    save_hold(hold)
    return True


_DOW = "월화수목금토일"


def _kday(now):
    from datetime import datetime as _dt
    return _dt.fromtimestamp(now, AP.KST)


def _md_ko(iso: str) -> str:
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(iso, "%Y-%m-%d")
        return f"{d.month}월 {d.day}일({_DOW[d.weekday()]})"
    except (TypeError, ValueError):
        return str(iso)


def _open_problems(hst, stall_on=False) -> list:
    out = []
    try:
        for i in ((hst or {}).get("incidents") or {}).values():
            if not isinstance(i, dict) or i.get("resolved") or str(i.get("id") or "").startswith(("quota:", "bfstall:", "gaps:", "key:")):
                continue
            if not stall_on and health.alert_cat(i) == "stall":
                continue
            if health.alert_cat(i) == "bal":
                continue
            out.append((0 if i.get("level") == "crit" else 1, str(i.get("title") or "")[:40]))
    except Exception:
        return []
    return [t for _l, t in sorted(out)]


def _open_bal_keys(hst) -> int:
    try:
        n = 0
        for i in ((hst or {}).get("incidents") or {}).values():
            if not (isinstance(i, dict) and i.get("check") == "balcheck:mismatch" and not i.get("resolved")):
                continue
            if not i.get("announced") or i.get("muted"):
                continue
            if not i.get("bal_v"):
                n += (len(i.get("keys") or ()) or 1) if i.get("level") == "crit" else 0
                continue
            if i.get("level") != "crit" or not i.get("notify"):
                continue
            pend9 = set()
            for o in (hst or {}).get("outbox") or ():
                if isinstance(o, dict) and o.get("kind") in ("open", "group", "remind") and i.get("id") in (o.get("incs") or ()):
                    pend9.update(o.get("keys") or ())
            n += len((set(i.get("keys_told") or ()) & set(i.get("keys") or ())) - pend9)
        return n
    except Exception:
        return 0


def _open_bal_any(hst) -> bool:
    try:
        return any(isinstance(i, dict) and i.get("check") == "balcheck:mismatch" and not i.get("resolved") and i.get("level") in ("warn", "crit")
                   for i in ((hst or {}).get("incidents") or {}).values())
    except Exception:
        return False


def compose_digest(dg: dict, doc: dict, now: float, hst=None, cfg=None):
    if not AP.digest_on(doc, now):
        return None, None, "KRW"
    hbal9 = isinstance(hst, dict) and bool(hst.get("last_eval"))

    def live(kind):
        k9 = str(kind or "").split(":", 1)[0]
        return not (hbal9 and k9 == BAL_KIND) and AP.effective(doc, AP.cat_of(k9), now)
    items = [x for x in list((dg or {}).get("items") or []) if isinstance(x, dict) and live(x.get("kind"))]
    kc = (dg or {}).get("k")
    if not isinstance(kc, dict):
        kc = {}
        for x in items:
            kk = _dg_key(x.get("kind"), x.get("d"))
            kc[kk] = kc.get(kk, 0) + 1
    kc = {k: _cnt(v) for k, v in kc.items() if _cnt(v) and live(k)}
    today = _kday(now).strftime("%Y-%m-%d")
    by = {}
    for x in items:
        by.setdefault(x.get("kind"), []).append(x)
    lines = [f"📋 하루 요약 · {_md_ko(today)}"]
    curve, cur = None, "KRW"
    pnl = [x for x in by.get("PNL_DAILY", []) if isinstance(x.get("d"), dict)]
    if pnl:
        d = pnl[-1]["d"]
        cur = d.get("cur") or "KRW"
        import alert_watch as _aw
        m = (lambda v: _aw.money(v, "KRW", 1.0, True)) if cur == "KRW" else (lambda v: _aw.money(v, "USD", None, True))
        when = "오늘" if d.get("iso") == today else ("어제" if d.get("iso") and d["iso"] < today else str(d.get("iso")))
        bits = [f"{when} 실현 {m(d.get('realized') or 0)}"]
        if int(d.get("sells") or 0):
            bits.append(f"매도 {int(d['sells'])}건")
        if d.get("delta") is not None:
            bits.append(f"총자산 {m(d['delta'])}")
        lines.append(" · ".join(bits))
        top = [t for t in (d.get("top") or []) if isinstance(t, list) and len(t) >= 2]
        if top:
            lines.append("많이 움직인 코인 " + " · ".join(f"{t[0]} {'+' if float(t[1]) >= 0 else '−'}{abs(float(t[1])):.0f}%" for t in top[:3]))
        cv = [c for c in (d.get("curve") or []) if isinstance(c, list) and len(c) >= 2]
        if len(cv) >= 2:
            curve = [[float(c[1]), c[2]] for c in cv] if any(len(c) > 2 for c in cv) else [float(c[1]) for c in cv]
    elif by.get("PNL_DAILY"):
        t9 = by["PNL_DAILY"][-1]["text"]
        lines.append(t9.split("\n", 2)[1] if "\n" in t9 else "손익 요약 도착")
    good, check = [], []
    rec_n = sum(kc.get(k, 0) for k in RECON_KINDS)
    fix_n = _cnt((dg or {}).get("fix")) if "fix" in (dg or {}) else sum(recon_fixed(x.get("text"), x.get("d")) for x in items if x.get("kind") in RECON_KINDS)
    if not live("EXF_RECON"):
        fix_n = 0
    mism = kc.get("BALANCE_MISMATCH", 0)
    told = _open_bal_keys(hst) if AP.effective(doc, "balmis", now) else 0
    if mism or told:
        check.append(f"잔고가 기록과 다른 곳 {max(mism, told)}" + ("(이미 알림)" if told and not mism else ""))
    if rec_n and fix_n:
        good.append(f"잔고 맞춤: {fix_n}개 고침")
    elif rec_n and not (mism or told or _open_bal_any(hst)):
        good.append("잔고는 모두 맞아요")
    rv = by.get("REVIEW_DAILY", []) + by.get("REVIEW_WEEKLY", [])
    if rv or kc.get("REVIEW_DAILY") or kc.get("REVIEW_WEEKLY"):
        g = (((rv[-1].get("d") or {}).get("grade") if rv else "") or "").strip()
        good.append("AI 복기가 도착했어요" + (f"({g})" if g and g != "—" else ""))
    inflow = by.get("BIG_INFLOW", [])
    for x in inflow[-2:]:
        good.append(f"큰 입금 {(x.get('d') or {}).get('amt') or ''}".strip())
    if kc.get("BIG_INFLOW") and not inflow:
        good.append(f"큰 입금 {kc['BIG_INFLOW']}건")
    lp_out, lp_in = kc.get("LP_RANGE:out", 0), kc.get("LP_RANGE:in", 0)
    if lp_out:
        check.append(f"LP 범위 벗어남 {lp_out}")
    if lp_in and not lp_out:
        good.append(f"LP 범위로 돌아옴 {lp_in}")
    unk = kc.get("UNKNOWN", 0)
    if unk:
        check.append(f"처음 보는 토큰 {unk}")
    oa_items = by.get("OA_ALERT", []) + by.get("NFT_CG_SLOW", [])
    for x in oa_items[-2:]:
        msg = (x.get("d") or {}).get("msg") or x.get("text", "").split("\n", 1)[0].lstrip("📋⏳🏦✅ ")[:40]
        (good if "다시 연결" in msg else check).append(msg)
    oa_n = kc.get("OA_ALERT", 0) + kc.get("NFT_CG_SLOW", 0)
    if oa_n and not oa_items:
        check.append(f"기타 자산 소식 {oa_n}")
    probs = _open_problems(hst, AP.effective(doc, "stall", now))
    if probs and AP.effective(doc, "digest", now):
        check.append(f"안 풀린 봇 문제 {len(probs)}(" + ", ".join(probs[:2]) + ")")
    known = {"PNL_DAILY", "EXF_RECON", "RECON", "EX_RECON", "BALANCE_MISMATCH", "REVIEW_DAILY", "REVIEW_WEEKLY", "BIG_INFLOW", "LP_RANGE", "UNKNOWN",
             "OA_ALERT", "NFT_CG_SLOW", "digest"}
    etc = sum(v for k, v in kc.items() if k.split(":", 1)[0] not in known)
    if etc:
        check.append(f"그 밖의 소식 {etc}")
    if not pnl and not by.get("PNL_DAILY") and not good and not check:
        return None, None, cur
    if good:
        lines.append(" · ".join(good[:4]))
    lines.append(f"살펴볼 것 {len(check)}가지 — " + " · ".join(check[:5]) if check else "살펴볼 것은 없어요")
    link = AP.public_link("daily", cfg)
    if link:
        lines.append(f"[오늘 카드 열기] {link}")
    return "\n".join(lines), curve, cur


def flush_digest(token, chat, doc: dict, now: float, st: dict, hold: dict, hst=None, cfg=None) -> bool:
    day = AP.digest_due(doc, hold.get("dg_day"), now)
    if not day:
        return False
    dg = hold.get("dg") or {"items": [], "n": {}}
    text, curve, cur = compose_digest(dg, doc, now, hst, cfg)
    if text:
        th = doc.get("th") or {}
        png = None
        if curve and th.get("digest_chart", True):
            try:
                import tinychart
                png = tinychart.render(curve, axis=bool(th.get("digest_axis", True)), cur=cur)
            except Exception as e:
                log.warning("하루 요약 그림 실패(글자만 보냄): %s", e)
        ok = bool(png) and len(text) <= 1024 and send_photo(token, chat, png, text, silent=True)[0]
        if not ok:
            ok = send(token, chat, text)
            if ok and png and len(text) > 1024:
                send_photo(token, chat, png, "", silent=True)
        if not ok:
            return False
        _SENT_TIMES.append(time.time())
        try:
            stat_add(st, "digest", "sent", 1, now)
        except Exception as e:
            log.warning("발송 기록 실패(무시): %s", e)
    hold["dg"] = {"items": [], "n": {}}
    hold["dg_day"] = day
    save_hold(hold)
    return True


def health_gate(st: dict, hold: dict, now_fn=time.time):
    def gate(kind, text):
        now = now_fn()
        cat = AP.cat_of(kind)
        if cat in AP.CRIT:
            return True
        try:
            doc = AP.load()
            conn = AP.connect_ts(st)
            how = AP.decide(doc, cat, now, conn)
        except Exception as e:
            log.warning("헬스 알림 설정 판정 실패(보냄): %s", e)
            return True
        if how == "send":
            return True
        try:
            if how == "hold":
                if hold_add(hold, None, None, cat, kind, text, now):
                    save_hold(hold)
                stat_add(st, cat, "held", 1, now)
            elif how == "daily":
                if dg_add(hold, None, None, cat, kind, text, now):
                    save_hold(hold)
                stat_add(st, cat, "daily", 1, now)
            else:
                stat_add(st, cat, "web" if how == "web" else "skip", 1, now)
            save_stats(st, now)
        except Exception as e:
            log.warning("헬스 알림 보류·기록 실패(무시): %s", e)
        return False
    return gate


SCAM_KINDS = ("TRANSFER_OUT", "PROGRAM_IN", "UNKNOWN", "NEW_ASSET", "TRANSFER_OUT_EX")


def drop_scam(rows, conn_factory=None):
    want = [i for i, (_o, d) in enumerate(rows) if isinstance(d, dict) and d.get("kind") in SCAM_KINDS
            and isinstance(d.get("payload"), dict) and d["payload"].get("chain") and d["payload"].get("txhash")]
    if not want:
        return rows
    try:
        import sqlite3
        import spamguard
        conn = conn_factory() if conn_factory else sqlite3.connect(common.sqlite_ro_uri(common.DB_PATH), uri=True, timeout=10)
    except Exception as e:
        log.warning("스캠 알림 거르기 생략(원장 열기 실패): %s", e)
        return rows
    try:
        cfg = common.read_json(common.CONFIG_PATH, {}) or {}
        my = {(w.get("address") or "") if w.get("type") == "sol" else (w.get("address") or "").lower() for w in cfg.get("wallets") or []}
        out = list(rows)
        n = 0
        for i in want:
            pl = rows[i][1]["payload"]
            if spamguard.tx_scam_reason(conn, pl["chain"], pl["txhash"], my):
                out[i] = (rows[i][0], None)
                n += 1
        if n:
            log.info("스캠 tx 알림 %d건 거름(가짜 전송·사칭·주소 오염)", n)
        return out
    except Exception as e:
        log.warning("스캠 알림 거르기 실패(원래대로 발송): %s", e)
        return rows
    finally:
        try:
            conn.close()
        except Exception:
            pass


def health_tick(mon, token, chat, gate=None):
    try:
        if mon.due():
            send_fn = (lambda text, reply_to=None: send_message(token, chat, text, reply_to)) if token else None
            mon.tick(send_fn, tg_configured=bool(token), gate=gate)
    except Exception as e:
        log.warning("헬스 판정 실패(다음 주기): %s", e)


_CRIT_KINDS = tuple(k for k, c in AP.KIND_CAT.items() if c in AP.CRIT)


def scan_crit(path: str, fn: str, start: int, hold: dict, limit: int = CRIT_SCAN_BYTES, doc: dict = None, conn=None, now=None) -> list:
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(start)
            pos = start
            while pos - start < limit:
                line = f.readline()
                if not line or not line.endswith(b"\n"):
                    break
                pos += len(line)
                if doc is None and not any(('"' + k + '"').encode() in line for k in _CRIT_KINDS):
                    continue
                try:
                    d = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(d, dict) or held(hold, fn, pos):
                    continue
                cat = AP.cat_of(d.get("kind"), d.get("cat"))
                if cat in AP.CRIT or (doc is not None and str(d.get("kind")) != AP.TEST_KIND
                                      and AP.decide(doc, cat, now, conn, d.get("kind")) == "send"):
                    out.append((pos, d))
    except OSError:
        return []
    return out


_URG = {"pos": {}}


def urgent_pass(now=None) -> int:
    c = _URG
    token, chat, cursor, hold = c.get("token"), c.get("chat"), c.get("cursor"), c.get("hold")
    if not token or not chat or cursor is None or hold is None:
        return 0
    conn, st = c.get("conn"), c.get("st") or {"days": {}, "counted": {}}
    sent = 0
    for fn in SOURCES:
        path = os.path.join(common.STATE_DIR, fn)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        cur = int(cursor.get(fn, 0) or 0)
        if cur > size:
            continue
        pos = max(cur, int(c["pos"].get(fn, cur) or cur))
        if pos >= size:
            continue
        rows, _end = read_chunk(path, pos)
        for off, d in rows:
            kind = str(d.get("kind") or "") if isinstance(d, dict) else ""
            if kind not in AP.FAST_KINDS or held(hold, fn, off):
                c["pos"][fn] = off
                continue
            cat = AP.cat_of(kind, d.get("cat"))
            if sent:
                time.sleep(0.3)
            if not _fast_send_ok(kind, conn):
                if mark_done(hold, fn, [off], cur):
                    save_hold(hold)
                c["pos"][fn] = off
                try:
                    stat_add(st, cat, "skip", 1, now)
                except Exception as e:
                    log.warning("발송 기록 실패(무시): %s", e)
                continue
            token, chat = _tg_creds()
            if not token or not chat:
                return sent
            if sent >= URGENT_MAX_PASS or not send(token, chat, _late_note(d)):
                return sent
            sent += 1
            if mark_done(hold, fn, [off], cur):
                save_hold(hold)
            c["pos"][fn] = off
            try:
                stat_add(st, cat, "sent", 1, now)
            except Exception as e:
                log.warning("발송 기록 실패(무시): %s", e)
            ts9 = _num_ts(d.get("ts"))
            log.info("긴급 알림 즉시 발송(%s%s)", kind, f" · 줄 시각 뒤 {time.time() - ts9:.1f}초" if ts9 else "")
    return sent


def _num_ts(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if 1e9 < x < 1e11 else 0.0


def _urgent_hook():
    try:
        urgent_pass()
    except Exception as e:
        log.warning("긴급 즉시 경로 실패(다음 틱): %s", e)


_REAL_SLEEP = time.sleep


def _wait_urgent(sec: float) -> None:
    if time.sleep is not _REAL_SLEEP:
        _urgent_hook()
        time.sleep(sec)
        return
    end = time.time() + sec
    while True:
        _urgent_hook()
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(URGENT_TICK, left))


def _wait_creds(sec: float) -> None:
    if time.sleep is not _REAL_SLEEP:
        time.sleep(sec)
        return
    end = time.time() + sec
    while time.time() < end:
        tok9, chat9 = _tg_creds()
        if tok9 and chat9:
            return
        time.sleep(min(URGENT_TICK, max(0.0, end - time.time())))


def _save_cursor(cursor: dict, fn: str, off: int) -> bool:
    cursor[fn] = off
    try:
        common.atomic_write_json(CURSOR_PATH, cursor)
        return True
    except OSError as e:
        log.warning("커서 저장 실패: %s", e)
        return False


def run_source(fn: str, token, chat, cursor: dict, doc: dict, conn, st: dict, hold: dict, cap_state: dict, hst: dict = None) -> None:
    path = os.path.join(common.STATE_DIR, fn)
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    off = int(cursor.get(fn, 0))
    if off > size:
        off = 0
        st["counted"][fn] = 0
        hold["ids"][fn] = []
        _URG["pos"].pop(fn, None)
    if off >= size:
        return
    rows, chunk_end = read_chunk(path, off)
    if not rows:
        return
    if fn == "pending_dm.jsonl":
        rows = drop_scam(rows)
    try:
        rows, hch = filter_rows(rows, fn, doc, conn, time.time(), st, hold, hst)
    except Exception as e:
        log.warning("알림 설정 필터 실패(이번 청크는 전부 발송): %s", e)
    ceil9 = None
    if hold.get("_pend") and not save_hold(hold):
        p9 = [o for o in (hold.get("_pend") or {}).get(fn) or () if o > off]
        if p9:
            lim9 = min(p9)
            ceil9 = max([o for o, _d in rows if o < lim9] or [off])
    bal_keys = {o: d.get("keys") for o, d in rows if isinstance(d, dict) and d.get("kind") == BAL_KIND and d.get("keys")}
    msgs = coalesce_k(rows)
    if not msgs:
        off = chunk_end if ceil9 is None else max(off, min(chunk_end, ceil9))
    sent_n = 0
    if chunk_end < size:
        try:
            far = scan_crit(path, fn, chunk_end, hold) if ceil9 is None else \
                scan_crit(path, fn, chunk_end, hold, doc=doc, conn=conn, now=time.time())
            if ceil9 is not None and fn == "pending_dm.jsonl":
                far = [r for r in drop_scam(far) if isinstance(r[1], dict)]
            for _e, text, kind, cov in coalesce_k(far):
                crit9 = AP.cat_of(kind) in AP.CRIT
                if kind in AP.FAST_KINDS and not _fast_send_ok(kind, conn):
                    if mark_done(hold, fn, cov, off):
                        save_hold(hold)
                    try:
                        stat_add(st, AP.cat_of(kind), "skip", len(cov), time.time())
                    except Exception as e:
                        log.warning("발송 기록 실패(무시): %s", e)
                    continue
                _SENT_TIMES[:] = [t for t in _SENT_TIMES if time.time() - t < 3600]
                if not crit9 and len(_SENT_TIMES) >= HOURLY_CAP:
                    continue
                tk9, ch9 = _fast_to(kind, token, chat)
                if sent_n >= MAX_PER_CYCLE or (kind in AP.FAST_KINDS and not tk9) or not send(tk9, ch9, text):
                    break
                sent_n += 1
                if not crit9:
                    _SENT_TIMES.append(time.time())
                if mark_done(hold, fn, cov, off):
                    save_hold(hold)
                try:
                    stat_add(st, AP.cat_of(kind), "sent", 1, time.time())
                except Exception as e:
                    log.warning("발송 기록 실패(무시): %s", e)
                time.sleep(0.5)
        except Exception as e:
            log.warning("%s 봇 이상 경보 앞 훑기 실패(다음 사이클): %s", fn, e)
    blocked = False
    for end_off, text, kind, cov in msgs:
        now = time.time()
        is_test = kind == AP.TEST_KIND
        free = is_test or AP.cat_of(kind) in AP.CRIT or kind in AP.FAST_KINDS
        _SENT_TIMES[:] = [t for t in _SENT_TIMES if now - t < 3600]
        if sent_n >= MAX_PER_CYCLE:
            break
        if not free and (blocked or len(_SENT_TIMES) >= HOURLY_CAP):
            if not blocked and now - cap_state.get("warned", 0) > 600:
                cap_state["warned"] = now
                log.warning("시간당 발송 상한 %d 도달 — 남은 알림은 다음 사이클에 묶어서 발송(봇 이상 경보는 그대로 보냄)", HOURLY_CAP)
            blocked = True
            continue
        _urgent_hook()
        if kind in AP.FAST_KINDS and not _fast_send_ok(kind, conn) and not (cov and all(held(hold, fn, o) for o in cov)):
            try:
                stat_add(st, AP.cat_of(kind), "skip", len(cov), time.time())
            except Exception as e:
                log.warning("발송 기록 실패(무시): %s", e)
            if blocked or (ceil9 is not None and end_off > ceil9):
                if mark_done(hold, fn, cov, off):
                    save_hold(hold)
            else:
                off = end_off
                _save_cursor(cursor, fn, off)
            continue
        if cov and all(held(hold, fn, o) for o in cov):
            if not (blocked or (ceil9 is not None and end_off > ceil9)):
                off = end_off
                _save_cursor(cursor, fn, off)
            continue
        tk9, ch9 = _fast_to(kind, token, chat)
        if (kind in AP.FAST_KINDS and not tk9) or not send(tk9, ch9, text):
            break
        sent_n += 1
        if kind == BAL_KIND and hst is not None and bal_keys:
            try:
                health.note_bal_dm(hst, [k for o in cov for k in (bal_keys.get(o) or ())], time.time())
            except Exception as e:
                log.warning("잔고 불일치 발송 키 기록 실패(무시): %s", e)
        hc9 = blocked or end_off is None or (ceil9 is not None and end_off > ceil9)
        if mark_done(hold, fn, cov if hc9 else [o for o in cov if o > end_off], off if hc9 else end_off):
            save_hold(hold)
        if not hc9:
            off = end_off
            _save_cursor(cursor, fn, off)
        if kind == AP.FIRST_BACKFILL_KIND and not st.get("bf_first"):
            st["bf_first"] = int(now)
            st["_dirty"] = True
        if is_test:
            _TEST_TIMES.append(time.time())
        elif not free:
            _SENT_TIMES.append(time.time())
        if not is_test:
            try:
                stat_add(st, AP.cat_of(kind), "sent", 1, now)
            except Exception as e:
                log.warning("발송 기록 실패(무시): %s", e)
        time.sleep(0.5)
    if _save_cursor(cursor, fn, off) and retire_held(hold, fn, off):
        save_hold(hold)


def main():
    common.ensure_dirs()
    cursor = common.read_json(CURSOR_PATH, {})
    warned = False
    cap_state = {}
    mon = health.Monitor()
    st = load_stats()
    hold = load_hold()
    gate = health_gate(st, hold)
    while True:
        token, chat = _tg_creds()
        health_tick(mon, token, chat, gate)
        if not token or not chat:
            if not warned:
                log.info("TJ_TG_TOKEN/TJ_TG_CHAT 대기 중 — .env 에 넣으면 즉시 발송 시작")
                warned = True
            _URG.update(token=None, chat=None)
            _wait_creds(60)
            continue
        warned = False
        now0 = time.time()
        if not st.get("first_seen"):
            st["first_seen"] = int(now0)
            save_stats(st, now0)
        if not st.get("bf_first"):
            c9 = AP.connect_ts(st)
            if c9 and now0 - c9 > AP.FIRST_DAYS * 86400:
                st["bf_first"] = int(now0)
                save_stats(st, now0)
        try:
            doc = AP.load()
        except Exception as e:
            log.warning("알림 설정 읽기 실패(추천값으로): %s", e)
            doc = AP.default_doc()
        try:
            conn = AP.connect_ts(st)
        except Exception as e:
            log.warning("텔레그램 연결 시각 읽기 실패: %s", e)
            conn = None
        if init_cursor(cursor):
            common.atomic_write_json(CURSOR_PATH, cursor)
        _URG.update(token=token, chat=chat, cursor=cursor, doc=doc, conn=conn, st=st, hold=hold)
        _urgent_hook()
        try:
            big = any(len(v) > HOLD_IDS_WARN for v in hold["ids"].values())
            if big:
                log.warning("조용한 시간 보류가 너무 큼(소스별 ID > %d) — 묶음을 미리 보냄(ID 는 커서가 지날 때까지 유지)", HOLD_IDS_WARN)
            if flush_hold(token, chat, doc, conn, now0, st, hold, force=big):
                save_stats(st, now0)
        except Exception as e:
            log.warning("조용한 시간 묶음 발송 실패(다음 사이클): %s", e)
        for fn in SOURCES:
            _urgent_hook()
            try:
                run_source(fn, token, chat, cursor, doc, conn, st, hold, cap_state, mon.st)
            except Exception as e:
                log.warning("%s 처리 실패(다음 사이클): %s", fn, e)
        try:
            if flush_digest(token, chat, doc, time.time(), st, hold, mon.st):
                save_stats(st)
        except Exception as e:
            log.warning("하루 요약 발송 실패(다음 사이클): %s", e)
        if st.get("_dirty"):
            save_stats(st)
        _wait_urgent(POLL_SEC)


def cli_test() -> int:
    token, chat = _tg_creds()
    if not token:
        print("텔레그램 미연결 — .env 에 TJ_TG_TOKEN / TJ_TG_CHAT 을 넣은 뒤 다시 실행하세요")
        return 2
    ok, mid, err = send_message(token, chat, f"🔔 tj-bot 알림 테스트 — 이 메시지가 보이면 연결 정상 "
                                             f"({time.strftime('%m-%d %H:%M')})")
    print("발송 성공 (message_id=%s)" % mid if ok else f"발송 실패: {err}")
    return 0 if ok else 1


def cli_health_once() -> int:
    st = health.Monitor().tick(None, tg_configured=bool(_tg_creds()[0]))
    print(json.dumps({"overall": st.get("overall"), "open": [(x["level"], x["unit"], x["title"], x["detail"])
                                                            for x in st.get("open", [])],
                      "watching": [(x["level"], x["unit"], x["title"]) for x in st.get("watching", [])]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv[1:]:
        sys.exit(cli_test())
    if "--health-once" in sys.argv[1:]:
        sys.exit(cli_health_once())
    try:
        main()
    except KeyboardInterrupt:
        log.info("정지 신호(SIGINT) — 종료")
