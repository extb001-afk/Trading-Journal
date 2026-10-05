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
import health
import alert_prefs as AP

log = common.setup_logging("tj-alert")

SOURCES = ("pending_dm.jsonl", "alerts_web.jsonl")
CURSOR_PATH = os.path.join(common.STATE_DIR, "tg_cursor.json")
POLL_SEC = 20
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
        with open(os.path.join(common.BASE_DIR, ".env"), "r", encoding="utf-8") as f:
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


def send_message(token: str, chat: str, text: str, reply_to=None):
    now = time.time()
    if now < _TG_WAIT_UNTIL[0]:
        return False, None, f"텔레그램 속도 제한 대기 {int(_TG_WAIT_UNTIL[0] - now) + 1}초"
    text = common.redact_secret_text(text, generic=False)
    params = {"chat_id": chat, "text": text[:3900]}
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
        cursor[fn] = _tail_end(path) if os.path.exists(path) else 0
        log.info("%s 커서 초기화 — 백로그 %d바이트 건너뜀(파일 끝에서 시작)", fn, cursor[fn])
        changed = True
    return changed


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
        if len(grp) < COALESCE_MIN or k == AP.TEST_KIND:
            msgs.append((i, d.get("text") or f"[{k}] {json.dumps(d, ensure_ascii=False)[:300]}", k, [o]))
            continue
        if k in done_kinds:
            continue
        done_kinds.add(k)
        last3 = [str(x.get("text") or "")[:200] for _o, x in grp[-3:]]
        msgs.append((i, f"[{k}] {len(grp)}건 묶음 — 최근 {len(last3)}건:\n- " + "\n- ".join(last3), k, [o9 for o9, _x in grp]))
    chunk_end = rows[-1][0] if rows else 0
    out = []
    for j, (_i, text, k, cov) in enumerate(msgs):
        nxt = msgs[j + 1][0] if j + 1 < len(msgs) else None
        out.append((rows[nxt - 1][0] if nxt else chunk_end, text, k, cov))
    return out


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
    days = raw.get("days")
    for dk, row in (days.items() if isinstance(days, dict) else ()):
        if not (isinstance(dk, str) and len(dk) == 10 and dk[4] == "-" and dk[7] == "-") or not isinstance(row, dict):
            continue
        r2 = {}
        for cat, c in row.items():
            if cat in AP.CAT and isinstance(c, dict):
                c2 = {f: _cnt(c.get(f)) for f in ("sent", "skip", "held") if _cnt(c.get(f))}
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
    return h


def save_hold(h: dict) -> None:
    try:
        common.atomic_write_json(AP.HOLD_PATH, h)
    except Exception as e:
        log.warning("조용한 시간 보류 저장 실패: %s", e)


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
    h["n"][cat] = _cnt(h["n"].get(cat)) + 1
    h["items"] = (h["items"] + [{"cat": cat, "kind": kind, "text": str(text or "")[:300], "ts": int(now)}])[-AP.HOLD_TEXT_MAX:]
    h.setdefault("since", int(now))
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
    tleft = _test_budget(now)
    for off, d in rows:
        if not isinstance(d, dict):
            out.append((off, d))
            continue
        if held(hold, fn, off):
            out.append((off, None))
            continue
        kind = str(d.get("kind") or "?")
        if kind == AP.TEST_KIND:
            if tleft > 0:
                tleft -= 1
                out.append((off, d))
            else:
                out.append((off, None))
                if off > counted:
                    log.info("테스트 알림 시간당 %d통 넘음 — 버림", TEST_HOURLY)
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
        if how == "send":
            out.append((off, d))
            continue
        if how == "hold" and hold_add(hold, fn, off, cat, kind, d.get("text") or f"[{kind}]", now):
            changed = True
        if off > counted:
            stat_add(st, cat, "held" if how == "hold" else "skip", 1, now)
        out.append((off, None))
    if rows and rows[-1][0] > counted:
        st["counted"][fn] = rows[-1][0]
        st["_dirty"] = True
    return out, changed


def hold_text(hold: dict, doc: dict, early: bool = False) -> str:
    q = doc.get("quiet") or {}
    n = sum(_cnt(v) for v in hold["n"].values())
    lines = [f"🌙 조용한 시간({q.get('from', '?')}~{q.get('to', '?')}) 동안 모인 알림 {n}건" + (" — 너무 많이 쌓여 미리 보내요" if early else "")]
    for c in AP.CATS:
        k = c["key"]
        if hold["n"].get(k):
            lines.append(f"· {c['label']} {hold['n'][k]}건")
    items = hold["items"][-8:]
    if items:
        lines.append("최근:")
        lines += ["- " + str(x.get("text") or "")[:160].replace("\n", " ") for x in items]
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
            else:
                stat_add(st, cat, "skip", 1, now)
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
        conn = conn_factory() if conn_factory else sqlite3.connect(f"file:{common.DB_PATH}?mode=ro", uri=True, timeout=10)
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


def scan_crit(path: str, fn: str, start: int, hold: dict, limit: int = CRIT_SCAN_BYTES) -> list:
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
                if not any(('"' + k + '"').encode() in line for k in _CRIT_KINDS):
                    continue
                try:
                    d = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(d, dict) and AP.cat_of(d.get("kind"), d.get("cat")) in AP.CRIT and not held(hold, fn, pos):
                    out.append((pos, d))
    except OSError:
        return []
    return out


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
    if off >= size:
        return
    rows, chunk_end = read_chunk(path, off)
    if not rows:
        return
    if fn == "pending_dm.jsonl":
        rows = drop_scam(rows)
    try:
        rows, hch = filter_rows(rows, fn, doc, conn, time.time(), st, hold, hst)
        if hch:
            save_hold(hold)
    except Exception as e:
        log.warning("알림 설정 필터 실패(이번 청크는 전부 발송): %s", e)
    bal_keys = {o: d.get("keys") for o, d in rows if isinstance(d, dict) and d.get("kind") == BAL_KIND and d.get("keys")}
    msgs = coalesce_k(rows)
    if not msgs:
        off = chunk_end
    sent_n = 0
    if chunk_end < size:
        try:
            for _e, text, kind, cov in coalesce_k(scan_crit(path, fn, chunk_end, hold)):
                if sent_n >= MAX_PER_CYCLE or not send(token, chat, text):
                    break
                sent_n += 1
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
        free = is_test or AP.cat_of(kind) in AP.CRIT
        _SENT_TIMES[:] = [t for t in _SENT_TIMES if now - t < 3600]
        if sent_n >= MAX_PER_CYCLE:
            break
        if not free and (blocked or len(_SENT_TIMES) >= HOURLY_CAP):
            if not blocked and now - cap_state.get("warned", 0) > 600:
                cap_state["warned"] = now
                log.warning("시간당 발송 상한 %d 도달 — 남은 알림은 다음 사이클에 묶어서 발송(봇 이상 경보는 그대로 보냄)", HOURLY_CAP)
            blocked = True
            continue
        if not send(token, chat, text):
            break
        sent_n += 1
        if kind == BAL_KIND and hst is not None and bal_keys:
            try:
                health.note_bal_dm(hst, [k for o in cov for k in (bal_keys.get(o) or ())], time.time())
            except Exception as e:
                log.warning("잔고 불일치 발송 키 기록 실패(무시): %s", e)
        if mark_done(hold, fn, cov if blocked else [o for o in cov if o > end_off], off if blocked else end_off):
            save_hold(hold)
        if not blocked:
            off = end_off
            _save_cursor(cursor, fn, off)
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
            time.sleep(60)
            continue
        warned = False
        now0 = time.time()
        if not st.get("first_seen"):
            st["first_seen"] = int(now0)
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
        try:
            big = any(len(v) > HOLD_IDS_WARN for v in hold["ids"].values())
            if big:
                log.warning("조용한 시간 보류가 너무 큼(소스별 ID > %d) — 묶음을 미리 보냄(ID 는 커서가 지날 때까지 유지)", HOLD_IDS_WARN)
            if flush_hold(token, chat, doc, conn, now0, st, hold, force=big):
                save_stats(st, now0)
        except Exception as e:
            log.warning("조용한 시간 묶음 발송 실패(다음 사이클): %s", e)
        for fn in SOURCES:
            try:
                run_source(fn, token, chat, cursor, doc, conn, st, hold, cap_state, mon.st)
            except Exception as e:
                log.warning("%s 처리 실패(다음 사이클): %s", fn, e)
        if st.get("_dirty"):
            save_stats(st)
        time.sleep(POLL_SEC)


def cli_test() -> int:
    token, chat = _tg_creds()
    if not token:
        print("텔레그램 미연결 — .env 에 TJ_TG_TOKEN / TJ_TG_CHAT 을 넣은 뒤 다시 실행하세요")
        return 2
    ok, mid, err = send_message(token, chat, f"✅ tj-bot 알림 테스트 — 이 메시지가 보이면 연결 정상 "
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
