#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

USAGE_HEAD = "upbit_trades_fill — 업비트 옛 주문(체결 목록 없는 원본)의 실제 체결 시각 채우기 · 1회 도구 (외부 검토 L13③ · fxcollect1009)."

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
PUBLISHED_RPS = {"order": 8, "default": 30}
LIMIT_SHARE = 0.8
RPS_CAP = 6.0
RPS_DEFAULT = 1.0
SEC_LOW = 5
NOTFOUND_GIVEUP = 3
NET_STREAK_STOP = 5
SAVE_EVERY = 10
CHUNK = 50
PROGRESS = "upbit_trades_fill.json"
KEEP_RESP = ("uuid", "market", "side", "state", "ord_type", "executed_volume", "paid_fee", "executed_funds", "trades_count", "trades")


def _kst(ts):
    return datetime.fromtimestamp(int(ts), KST)


def targets(conn) -> dict:
    import acct_norm
    out = {}
    for u, pl in conn.execute("SELECT uuid, payload FROM raw_ex WHERE exchange='upbit' AND kind='order'"
                              " GROUP BY uuid HAVING revision = MAX(revision)"):
        try:
            o = json.loads(pl)
        except (TypeError, ValueError):
            continue
        if not isinstance(o, dict) or acct_norm.fill_ts(o) is not None:
            continue
        try:
            if float(o.get("executed_volume") or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        out[str(u)] = o
    return out


def load_progress(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    except (OSError, ValueError) as e:
        raise SystemExit(f"진행 파일 읽기 실패({path}): {e} — 손으로 확인(지우면 처음부터 다시 받음)")
    if not isinstance(st, dict):
        st = {}
    for k in ("got", "bad", "nf", "err"):
        if not isinstance(st.get(k), dict):
            st[k] = {}
    st.setdefault("v", 1)
    return st


def save_progress(path: str, st: dict) -> None:
    st["saved_at"] = int(time.time())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class UpbitClient:

    API = "https://api.upbit.com"

    def __init__(self, access: str, secret: str):
        self.access, self.secret = access, secret

    def get_order(self, uuid: str):
        import urllib.error
        import urllib.parse
        import urllib.request
        import upbit_link
        q = {"uuid": uuid}
        req = urllib.request.Request(self.API + "/v1/order?" + urllib.parse.urlencode(q), headers={
            "Authorization": f"Bearer {upbit_link._jwt(self.access, self.secret, q)}",
            "Accept": "application/json", "User-Agent": "tj-bot/0.1 (trades fill)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode()), _sec_left(r.headers.get("Remaining-Req"))
        except urllib.error.HTTPError as e:
            return e.code, None, _sec_left(e.headers.get("Remaining-Req") if e.headers else None)


def _sec_left(h):
    for part in str(h or "").split(";"):
        part = part.strip()
        if part.startswith("sec="):
            try:
                return int(part[4:])
            except ValueError:
                return None
    return None


def fetch(stored: dict, st: dict, client, rps: float, limit: int = 0, save=None, clock=time.monotonic, sleep=time.sleep,
          stop_flag=None, log=print) -> dict:
    import acct_norm
    rps = max(0.05, min(float(rps), RPS_CAP))
    gap = 1.0 / rps
    todo = [u for u in sorted(stored, key=lambda k: (str(stored[k].get("created_at") or ""), k))
            if u not in st["got"] and u not in st["bad"] and int((st["nf"].get(u) or 0)) < NOTFOUND_GIVEUP]
    if limit:
        todo = todo[:limit]
    res = {"calls": 0, "got": 0, "bad": 0, "nf": 0, "err": 0, "stopped": None, "todo": len(todo)}
    last = None
    streak = 0
    for i, u in enumerate(todo):
        if stop_flag is not None and stop_flag.get("stop"):
            res["stopped"] = "중단 신호"
            break
        if last is not None:
            wait = gap - (clock() - last)
            if wait > 0:
                sleep(wait)
        last = clock()
        res["calls"] += 1
        try:
            code, body, sec = client.get_order(u)
        except Exception as e:
            code, body, sec = None, None, None
            st["err"][u] = {"n": int((st["err"].get(u) or {}).get("n", 0)) + 1, "e": str(e)[:120]}
        if code == 200 and isinstance(body, dict):
            streak = 0
            st["err"].pop(u, None)
            st["nf"].pop(u, None)
            resp = {k: body.get(k) for k in KEEP_RESP if k in body}
            merged, why = acct_norm.trades_fill_merge(stored[u], resp)
            if merged is None:
                st["bad"][u] = {"why": why, "resp": resp}
                res["bad"] += 1
            else:
                st["got"][u] = resp
                res["got"] += 1
        elif code == 404:
            streak = 0
            st["nf"][u] = int(st["nf"].get(u) or 0) + 1
            res["nf"] += 1
        elif code in (401, 403):
            res["stopped"] = f"HTTP {code} — 키 거부(조회 권한·IP 허용 확인)"
            break
        elif code == 429:
            res["stopped"] = "HTTP 429 — 업비트 한도: 저장하고 멈춤(잠시 뒤 같은 명령으로 이어하기)"
            break
        else:
            streak += 1
            res["err"] += 1
            if code is not None:
                st["err"][u] = {"n": int((st["err"].get(u) or {}).get("n", 0)) + 1, "e": f"HTTP {code}"}
            if streak >= NET_STREAK_STOP:
                res["stopped"] = f"연속 실패 {streak}회 — 저장하고 멈춤(나중에 이어하기)"
                break
        if sec is not None and sec <= SEC_LOW:
            sleep(1.0)
        if save is not None and (i + 1) % SAVE_EVERY == 0:
            save()
        if (i + 1) % 50 == 0:
            log(f"  … {i + 1}/{len(todo)} (받음 {res['got']} · 검사 실패 {res['bad']} · 404 {res['nf']} · 실패 {res['err']})")
    if save is not None:
        save()
    return res


def impact(stored: dict, st: dict) -> dict:
    import acct_norm
    rep = {"ready": 0, "same_day": 0, "day_moved": 0, "month_moved": 0, "multi_day": 0, "max_shift_h": 0.0, "shift_h_sum": 0.0, "top": []}
    for u, resp in st["got"].items():
        o = stored.get(u)
        if not o:
            continue
        merged, why = acct_norm.trades_fill_merge(o, resp)
        if merged is None:
            continue
        rep["ready"] += 1
        import common
        c9 = common.iso_epoch(o.get("created_at"))
        f9 = acct_norm.fill_ts(merged)
        if c9 is None or f9 is None:
            continue
        first9 = min(acct_norm.fill_ts({"trades": [t]}) for t in merged["trades"])
        d0, d1 = _kst(c9), _kst(f9)
        h = (f9 - c9) / 3600.0
        rep["shift_h_sum"] += h
        rep["max_shift_h"] = max(rep["max_shift_h"], h)
        if d0.date() == d1.date():
            rep["same_day"] += 1
        else:
            rep["day_moved"] += 1
            if (d0.year, d0.month) != (d1.year, d1.month):
                rep["month_moved"] += 1
            rep["top"].append((h, u, o.get("market"), o.get("side"), d0.strftime("%Y-%m-%d %H:%M"), d1.strftime("%Y-%m-%d %H:%M")))
        if _kst(first9).date() != d1.date():
            rep["multi_day"] += 1
    rep["top"] = sorted(rep["top"], reverse=True)[:15]
    return rep


def build_records(stored: dict, st: dict, now: int = None) -> list:
    import acct_norm
    items = []
    for u in sorted(st["got"]):
        if u in stored and acct_norm.trades_fill_merge(stored[u], st["got"][u])[0] is not None:
            items.append(dict(st["got"][u], uuid=u))
    now = int(now or time.time())
    return [{"v": 1, "kind": "ex_order_trades", "exchange": "upbit", "ts": now, "src": "tools/upbit_trades_fill",
             "orders": items[i:i + CHUNK]} for i in range(0, len(items), CHUNK)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=USAGE_HEAD)
    ap.add_argument("--base", required=True, help="TJ 루트(config.json·state/ 가 있는 곳) — 기본값 없음")
    ap.add_argument("--fetch", action="store_true", help="업비트 단건 조회로 체결 목록 받기(원장 무접촉 · 진행 파일)")
    ap.add_argument("--apply", action="store_true", help="받은 것을 inbox(ex) 로 — tj-core 가 원본 개정·재기장")
    ap.add_argument("--yes", action="store_true", help="--fetch·--apply 실제 실행 확인(없으면 할 일만 보여 줌)")
    ap.add_argument("--rps", type=float, default=RPS_DEFAULT, help=f"초당 조회 수(기본 {RPS_DEFAULT} · 상한 {RPS_CAP})")
    ap.add_argument("--limit", type=int, default=0, help="이번 받기 최대 건수(시험 삼아 몇 건만)")
    ap.add_argument("--show", type=int, default=15, help="미리보기에 날짜가 바뀌는 주문을 몇 줄 보여 줄지(0 = 안 보임)")
    a = ap.parse_args(argv)
    base = os.path.realpath(os.path.expanduser(a.base))
    if not os.path.isfile(os.path.join(base, "config.json")) or not os.path.isdir(os.path.join(base, "state")):
        print(f"--base 가 TJ 루트가 아님: {base}", file=sys.stderr)
        return 2
    if a.fetch and a.apply:
        print("--fetch 와 --apply 는 따로(받기 → 미리보기로 확인 → 적용)", file=sys.stderr)
        return 2
    os.environ["TJ_BASE"] = base
    os.environ.pop("TJ_CONFIG", None)
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    import common
    db = os.path.join(base, "state", "ledger.db")
    if not os.path.exists(db):
        print(f"원장 없음: {db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        stored = targets(conn)
    finally:
        conn.close()
    path = os.path.join(base, "state", PROGRESS)
    lock = open(path + ".lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("다른 upbit_trades_fill 가 실행 중 — 끝난 뒤 다시", file=sys.stderr)
        return 3
    st = load_progress(path)
    left = [u for u in stored if u not in st["got"] and u not in st["bad"] and int(st["nf"].get(u) or 0) < NOTFOUND_GIVEUP]
    rps = max(0.05, min(a.rps, RPS_CAP))
    n_nonkrw = sum(1 for o in stored.values() if not str(o.get("market") or "").startswith("KRW-"))
    n_cancel = sum(1 for o in stored.values() if str(o.get("state") or "") == "cancel")
    print(f"대상(체결 목록 없는 업비트 주문) {len(stored)}건 (비KRW {n_nonkrw} · 부분 체결 후 취소 {n_cancel}) · 받음 {len(st['got'])} · "
          f"검사 실패 {len(st['bad'])} · 404 포기 {sum(1 for v in st['nf'].values() if int(v) >= NOTFOUND_GIVEUP)} · "
          f"남은 조회 {len(left)}회 ≈ {len(left) / rps / 60:.1f}분(초당 {rps:g}회)")
    if not a.fetch and not a.apply:
        if st["got"]:
            rep = impact(stored, st)
            avg = rep["shift_h_sum"] / rep["ready"] if rep["ready"] else 0
            print(f"영향(받은 {rep['ready']}건): 같은 날 {rep['same_day']} · 날짜 바뀜 {rep['day_moved']} (달 바뀜 {rep['month_moved']}) · "
                  f"여러 날에 걸친 체결 {rep['multi_day']} · 평균 이동 {avg:.1f}시간 · 최대 {rep['max_shift_h']:.1f}시간")
            for h, u, mk, sd, d0, d1 in rep["top"][:max(0, a.show)]:
                print(f"  {u[:8]}… {mk} {sd} 생성 {d0} → 마지막 체결 {d1} (+{h:.1f}h)")
            for u, b in list(st["bad"].items())[:10]:
                print(f"  [검사 실패] {u[:8]}… {b.get('why')}")
        print("다음: --fetch --yes(받기) · --apply --yes(적용 — tj-core 소비 뒤 반영)")
        return 0
    if a.fetch:
        if not left:
            print("받을 것 없음")
            return 0
        if not a.yes:
            print(f"--fetch: 업비트 단건 조회 {len(left) if not a.limit else min(a.limit, len(left))}회 예정 — 실제로 하려면 --yes")
            return 0
        import upbit_link
        env = upbit_link._env()
        acc, sec = env.get("UPBIT_ACCESS"), env.get("UPBIT_SECRET")
        if not acc or not sec:
            print(f"키 없음: {common.ENV_PATH} 의 UPBIT_ACCESS·UPBIT_SECRET", file=sys.stderr)
            return 2
        flag = {"stop": False}

        def _sig(*_a):
            flag["stop"] = True
            print("\n중단 신호 — 지금 것까지 저장하고 끝냄(다시 실행하면 이어서)")
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
        t0 = time.time()
        res = fetch(stored, st, UpbitClient(acc, sec), rps, a.limit, save=lambda: save_progress(path, st), stop_flag=flag)
        print(f"받기 끝: 조회 {res['calls']}회 · 받음 {res['got']} · 검사 실패 {res['bad']} · 404 {res['nf']} · 실패 {res['err']} · "
              f"{time.time() - t0:.0f}초" + (f" · 멈춤: {res['stopped']}" if res["stopped"] else ""))
        print("다음: 미리보기(인자 없이)로 영향 확인 → --apply --yes")
        return 0 if not res["stopped"] or res["stopped"] == "중단 신호" else 1
    recs = build_records(stored, st)
    n = sum(len(r["orders"]) for r in recs)
    if not recs:
        print("적용할 것 없음(받은 것이 없거나 이미 반영됨)")
        return 0
    if not a.yes:
        print(f"--apply: inbox(ex) 레코드 {len(recs)}개(주문 {n}건) 예정 — 실제로 하려면 --yes")
        return 0
    import inbox
    w = inbox.SegmentWriter(os.path.join(common.INBOX_DIR, "ex"))
    for r in recs:
        w.append(r)
    w.close()
    print(f"inbox/ex 'ex_order_trades' {len(recs)}개(주문 {n}건) — tj-core 가 소비하며 원본 개정·시각 재기장"
          " (로그: '업비트 옛 주문 체결 목록 채우기' · 끝나면 미리보기의 대상이 줄어든다)")
    print("  · 새 시각의 환율·쿼트 시세를 그 자리에서 못 받은 주문(조회 실패 — 한 번 실패하면 60초 쉬어 같은 적용의 뒤 주문들도)은 tj-core 가 되돌려 둔다"
          "(로그 '체결 시각 재기장 되돌림') — 몇 분 뒤 미리보기로 남은 대상을 보고 --apply --yes 를 다시")
    return 0


if __name__ == "__main__":
    sys.exit(main())
