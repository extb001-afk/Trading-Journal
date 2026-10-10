#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import signal
import sqlite3
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

USAGE_HEAD = "bithumb_filltime_1010 — 빗썸 지난 체결의 시각을 '주문 생성 시각' → '마지막 체결 시각'으로 바로잡는 1회 도구 (13차 bthfill)."

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
EX = "bithumb"
PROGRESS = "bithumb_filltime_1010.json"
RECORD_KIND = "exf_fill_retime"
MARK = "_tj_retime"
RPS_DEFAULT = 4.0
RPS_CAP = 5.0
DAILY_MAX_DEFAULT = 15000
NOTFOUND_GIVEUP = 3
NET_STREAK_STOP = 5
SAVE_EVERY = 20
CHUNK = 50
TERMINAL = ("done", "cancel")


def _kst(ts):
    return datetime.fromtimestamp(int(ts), KST)


def _dec(v):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def _has_tz(s) -> bool:
    t = str(s or "").strip()
    if len(t) < 19:
        return False
    tail = t[19:]
    return tail.endswith(("Z", "z")) or "+" in tail or "-" in tail


def _row_ts(s):
    try:
        return int(datetime.fromisoformat(str(s or "")).timestamp())
    except (ValueError, TypeError):
        return None


def targets(conn):
    out, n_done = {}, 0
    for fid, rev, pl, obs in conn.execute("SELECT uuid, revision, payload, observed_at FROM raw_ex WHERE exchange=? AND kind='trade'"
                                          " GROUP BY uuid HAVING revision = MAX(revision)", (EX,)):
        try:
            p = json.loads(pl)
        except (TypeError, ValueError):
            continue
        if not isinstance(p, dict) or not str(fid).startswith(EX + ":"):
            continue
        if isinstance(p.get(MARK), dict):
            n_done += 1
            continue
        try:
            ts = int(p.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0 or p.get("late") or p.get("src"):
            continue
        out[str(fid).split(":", 1)[1]] = {"id": str(fid), "ts": ts, "base": str(p.get("base") or "").upper(),
                                          "quote": str(p.get("quote") or "").upper(), "side": str(p.get("side") or ""),
                                          "qty": str(p.get("qty") or ""), "funds": str(p.get("funds") or ""), "rev": int(rev), "obs": int(obs)}
    return out, n_done


def recon_times(conn) -> list:
    out = set()
    for (sid,) in conn.execute("SELECT DISTINCT source_id FROM postings WHERE source_kind='exchange' AND source_ns=?", (EX + ":recon",)):
        t = str(sid).rsplit(":", 1)[-1]
        if t.isdigit():
            out.add(int(t))
    return sorted(out)


def between_sells(conn, stored: dict, st: dict) -> int:
    aids, n = {}, 0
    for u, g in st["got"].items():
        s = stored.get(u)
        if not s or s.get("side") != "buy":
            continue
        o9, n9 = int(s["ts"]) // 1000, int(g["ts"]) // 1000
        if n9 <= o9:
            continue
        b = s.get("base")
        if b not in aids:
            r = conn.execute("SELECT asset_id FROM assets WHERE kind='exchange_currency' AND chain IS NULL AND address=?",
                             (f"{EX}:{b}".lower(),)).fetchone()
            aids[b] = r[0] if r else None
        if aids[b] is not None and conn.execute(
                "SELECT 1 FROM postings WHERE location=? AND event_ts>=? AND event_ts<? AND asset_id=? AND event='EXF_SELL' AND leg_seq=0 LIMIT 1",
                (f"exchange:{EX}", o9, n9, aids[b])).fetchone():
            n += 1
    return n


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
    for k in ("got", "keep", "bad", "nf", "err"):
        if not isinstance(st.get(k), dict):
            st[k] = {}
    if not isinstance(st.get("day"), dict):
        st["day"] = {}
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


def judge(s: dict, o, now: int = None):
    now = int(now or time.time())
    if not isinstance(o, dict):
        return "bad", "응답 모양 다름"
    if str(o.get("state") or "") not in TERMINAL:
        return "bad", f"종결 아님({str(o.get('state') or '')[:12]})"
    ca = o.get("created_at")
    if not _has_tz(ca):
        return "bad", "생성 시각에 시간대 없음(해석 불가 — 손으로 확인)"
    c9 = _row_ts(ca)
    if c9 is None:
        return "bad", "생성 시각 읽기 실패"
    if c9 != int(s["ts"]) // 1000:
        return "keep", "fill"
    if str(o.get("ord_type") or "") != "limit":
        return "keep", "market"
    tr = o.get("trades")
    if not isinstance(tr, list) or not tr or not all(isinstance(t, dict) for t in tr):
        return "keep", "notrades"
    import acct_norm
    sv, ts_list = Decimal(0), []
    for t in tr:
        v9 = _dec(t.get("volume"))
        if v9 is None or v9 < 0 or not _has_tz(t.get("created_at")):
            return "bad", "체결 행 읽기 실패(수량·시간대)"
        t9 = acct_norm.fill_ts({"trades": [t]})
        if t9 is None:
            return "bad", "체결 행 시각 읽기 실패"
        sv += v9
        ts_list.append(int(t9))
    ev = _dec(o.get("executed_volume"))
    if ev is None or ev <= 0 or sv != ev:
        return "bad", "체결 목록 수량 합 다름"
    q9 = _dec(s.get("qty"))
    if q9 is None or q9 != ev:
        return "bad", "체결 수량이 원장과 다름"
    if s.get("funds") not in (None, "") and o.get("executed_funds") not in (None, ""):
        if _dec(s["funds"]) != _dec(o.get("executed_funds")):
            return "bad", "체결 금액이 원장과 다름"
    q, _, b = str(o.get("market") or "").upper().partition("-")
    side = "buy" if str(o.get("side")) == "bid" else ("sell" if str(o.get("side")) == "ask" else "")
    if (b, q, side) != (s.get("base"), s.get("quote"), s.get("side")):
        return "bad", "종목·방향이 원장과 다름"
    last, first = max(ts_list), min(ts_list)
    if first < c9 - 1:
        return "bad", "체결이 생성보다 이름"
    if last > now + 300:
        return "bad", "체결 시각이 미래"
    return "got", {"ts": last * 1000, "first": first * 1000, "ntr": len(tr), "c": c9}


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def fetch(stored: dict, st: dict, call, rps: float, limit: int = 0, daily_max: int = DAILY_MAX_DEFAULT, save=None, clock=time.monotonic,
          sleep=time.sleep, stop_flag=None, log=print, today=_today) -> dict:
    rps = max(0.05, min(float(rps), RPS_CAP))
    gap = 1.0 / rps
    todo = [u for u in sorted(stored, key=lambda k: (int(stored[k]["ts"]), k))
            if u not in st["got"] and u not in st["keep"] and u not in st["bad"] and int(st["nf"].get(u) or 0) < NOTFOUND_GIVEUP]
    if limit:
        todo = todo[:limit]
    res = {"calls": 0, "got": 0, "keep": 0, "bad": 0, "nf": 0, "err": 0, "stopped": None, "todo": len(todo)}
    last, streak = None, 0
    for i, u in enumerate(todo):
        if stop_flag is not None and stop_flag.get("stop"):
            res["stopped"] = "중단 신호"
            break
        d9 = today()
        if st["day"].get("d") != d9:
            st["day"] = {"d": d9, "n": 0}
        if int(st["day"].get("n") or 0) >= int(daily_max):
            res["stopped"] = f"하루 한도 {int(daily_max)}회(한국 날짜 {d9}) — 내일 같은 명령으로 이어하기"
            break
        if last is not None:
            wait = gap - (clock() - last)
            if wait > 0:
                sleep(wait)
        last = clock()
        res["calls"] += 1
        st["day"]["n"] = int(st["day"].get("n") or 0) + 1
        code, body = 200, None
        try:
            body = call("/v1/order", {"uuid": u})
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            c9 = getattr(e, "code", None)
            if c9 in (429, 418):
                res["stopped"] = f"HTTP {c9} — 빗썸 한도: 저장하고 멈춤(잠시 뒤 같은 명령으로 이어하기)"
                break
            code = None
            st["err"][u] = {"n": int((st["err"].get(u) or {}).get("n", 0)) + 1, "e": type(e).__name__}
        if code == 200 and isinstance(body, dict) and str(body.get("uuid") or "") == u:
            streak = 0
            st["err"].pop(u, None)
            st["nf"].pop(u, None)
            kind, val = judge(stored[u], body)
            if kind == "got":
                st["got"][u] = val
                res["got"] += 1
            elif kind == "keep":
                st["keep"][u] = val
                res["keep"] += 1
            else:
                st["bad"][u] = {"why": val}
                res["bad"] += 1
        elif code == 404:
            streak = 0
            st["nf"][u] = int(st["nf"].get(u) or 0) + 1
            res["nf"] += 1
        elif code in (401, 403):
            res["stopped"] = f"HTTP {code} — 키 거부(조회 권한·IP 허용 확인)"
            break
        elif code in (429, 418):
            res["stopped"] = f"HTTP {code} — 빗썸 한도: 저장하고 멈춤(잠시 뒤 같은 명령으로 이어하기)"
            break
        else:
            streak += 1
            res["err"] += 1
            if code is not None:
                st["err"][u] = {"n": int((st["err"].get(u) or {}).get("n", 0)) + 1, "e": "응답 모양 다름" if code == 200 else f"HTTP {code}"}
            if streak >= NET_STREAK_STOP:
                res["stopped"] = f"연속 실패 {streak}회 — 저장하고 멈춤(나중에 이어하기)"
                break
        if save is not None and (i + 1) % SAVE_EVERY == 0:
            save()
        if (i + 1) % 500 == 0:
            log(f"  … {i + 1}/{len(todo)} (바뀜 후보 {res['got']} · 그대로 {res['keep']} · 검사 실패 {res['bad']} · 404 {res['nf']} · 실패 {res['err']})")
    if save is not None:
        save()
    return res


def impact(stored: dict, st: dict, recon=()) -> dict:
    rep = {"targets": len(stored), "judged": 0, "changed": 0, "same": 0, "day": 0, "month": 0, "multi_day": 0, "cross_recon": 0,
           "krw_changed": Decimal(0), "krw_day": Decimal(0), "shift_h_sum": 0.0, "max_shift_h": 0.0, "keep": {}, "bad": len(st["bad"]),
           "nf_giveup": 0, "months": {}, "top": []}
    for u, s in stored.items():
        m9 = _kst(int(s["ts"]) // 1000).strftime("%Y-%m")
        mm = rep["months"].setdefault(m9, {"n": 0, "judged": 0, "chg": 0, "day": 0, "krw_day": Decimal(0)})
        mm["n"] += 1
        if u in st["got"] or u in st["keep"] or u in st["bad"] or int(st["nf"].get(u) or 0) >= NOTFOUND_GIVEUP:
            rep["judged"] += 1
            mm["judged"] += 1
        if int(st["nf"].get(u) or 0) >= NOTFOUND_GIVEUP:
            rep["nf_giveup"] += 1
        if u in st["keep"]:
            rep["keep"][st["keep"][u]] = rep["keep"].get(st["keep"][u], 0) + 1
        g = st["got"].get(u)
        if not g:
            continue
        o9, n9 = int(s["ts"]) // 1000, int(g["ts"]) // 1000
        if n9 == o9:
            rep["same"] += 1
            continue
        krw = _dec(s.get("funds")) or Decimal(0)
        rep["changed"] += 1
        mm["chg"] += 1
        rep["krw_changed"] += krw
        h = (n9 - o9) / 3600.0
        rep["shift_h_sum"] += h
        rep["max_shift_h"] = max(rep["max_shift_h"], h)
        d0, d1 = _kst(o9), _kst(n9)
        if d0.date() != d1.date():
            rep["day"] += 1
            mm["day"] += 1
            mm["krw_day"] += krw
            rep["krw_day"] += krw
            if (d0.year, d0.month) != (d1.year, d1.month):
                rep["month"] += 1
            rep["top"].append((h, u, s.get("base"), s.get("side"), d0.strftime("%Y-%m-%d %H:%M"), d1.strftime("%Y-%m-%d %H:%M")))
        if _kst(int(g.get("first") or g["ts"]) // 1000).date() != d1.date():
            rep["multi_day"] += 1
        if any(o9 < b9 <= n9 for b9 in recon):
            rep["cross_recon"] += 1
    rep["top"] = sorted(rep["top"], reverse=True)[:15]
    return rep


def build_records(stored: dict, st: dict, now: int = None) -> list:
    items = []
    for u, g in st["got"].items():
        s = stored.get(u)
        if s is None or int(g["ts"]) // 1000 == int(s["ts"]) // 1000:
            continue
        items.append({"id": s["id"], "ts_old": int(s["ts"]), "ts": int(g["ts"])})
    items.sort(key=lambda x: (x["ts"], x["id"]))
    now = int(now or time.time())
    return [{"v": 1, "kind": RECORD_KIND, "exchange": EX, "ts": now, "src": "tools/bithumb_filltime_1010", "fills": items[i:i + CHUNK]}
            for i in range(0, len(items), CHUNK)]


def _code_ready(root: str):
    try:
        core_src = open(os.path.join(root, "src", "core.py"), encoding="utf-8").read()
        rb_src = open(os.path.join(root, "tools", "rebuild2.py"), encoding="utf-8").read()
    except OSError as e:
        return f"코드 읽기 실패: {e}"
    if f'"{RECORD_KIND}"' not in core_src or "_consume_exf_retime" not in core_src:
        return "src/core.py 에 'exf_fill_retime' 처리기가 없음 — 이 도구와 같은 판을 배포하고 tj-core 를 다시 띄운 뒤 적용"
    if "def exf_trade_rows" not in rb_src:
        return "tools/rebuild2.py 가 옛 판(체결 원본 최신 revision 아님 — 재구축이 옛 시각으로 되돌림) — 같은 판을 배포한 뒤 적용"
    return None


def _print_preview(stored, st, n_done, recon, rps, show, out=print, n_between=None):
    left = [u for u in stored if u not in st["got"] and u not in st["keep"] and u not in st["bad"]
            and int(st["nf"].get(u) or 0) < NOTFOUND_GIVEUP]
    rep = impact(stored, st, recon)
    out(f"빗썸 체결(원장) — 바로잡을 대상 {len(stored)}건 · 이미 바로잡음 {n_done}건 · 판정함 {rep['judged']}건 · "
        f"남은 조회 {len(left)}회 ≈ {len(left) / rps / 60:.1f}분(초당 {rps:g}회 · 하루 상한 {st['day'].get('n', 0)}/{DAILY_MAX_DEFAULT} 오늘 사용)")
    if rep["judged"]:
        ch = rep["changed"]
        avg = rep["shift_h_sum"] / ch if ch else 0.0
        out(f"비교: 시각 바뀜 {ch}건 · 한국 날짜 바뀜 {rep['day']}건({(rep['day'] / rep['judged'] * 100):.1f}% · 판정한 것 기준) · 달 바뀜 {rep['month']}건 · "
            f"같은 시각 {rep['same']}건 · 그대로 {sum(rep['keep'].values())}건 {json.dumps(rep['keep'], ensure_ascii=False)} · "
            f"검사 실패 {rep['bad']}건 · 404 포기 {rep['nf_giveup']}건")
        out(f"      영향 금액(원화 체결 금액 합): 시각 바뀜 {rep['krw_changed']:,.0f}원 · 날짜 바뀜 {rep['krw_day']:,.0f}원 · "
            f"여러 날에 걸친 체결 {rep['multi_day']}건 · 대사 시점을 넘는 건 {rep['cross_recon']}건(대사 {len(recon)}회) · "
            f"평균 이동 {avg:.1f}시간 · 최대 {rep['max_shift_h']:.1f}시간")
        if n_between is not None:
            out(f"      늦춰지는 매수 중 그 사이 같은 코인 매도가 낀 건 {n_between}건(그 매도의 원가·실현손익이 바뀔 수 있음 — 실제 체결 순서대로가 맞는 방향)")
        if rep["judged"] < len(stored) and rep["judged"]:
            r9 = rep["day"] / rep["judged"]
            out(f"      (아직 다 받지 않음 — 지금 비율이면 날짜 바뀜 ≈ {r9 * len(stored):.0f}건 예상)")
        out("월별(옛 시각 기준 · 한국 달): 달 | 대상 | 판정 | 시각 바뀜 | 날짜 바뀜 | 날짜 바뀜 금액(원)")
        for m9 in sorted(rep["months"]):
            v = rep["months"][m9]
            out(f"  {m9} | {v['n']} | {v['judged']} | {v['chg']} | {v['day']} | {v['krw_day']:,.0f}")
        for h, u, b, sd, d0, d1 in rep["top"][:max(0, show)]:
            out(f"  {u[:8]}… {b} {sd} 생성 {d0} → 마지막 체결 {d1} (+{h:.1f}h)")
        for u, b in list(st["bad"].items())[:10]:
            out(f"  [검사 실패] {u[:8]}… {b.get('why')}")
    recs = build_records(stored, st)
    out(f"적용하면: 'exf_fill_retime' 레코드 {len(recs)}개(체결 {sum(len(r['fills']) for r in recs)}건)")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=USAGE_HEAD)
    ap.add_argument("--base", required=True, help="TJ 루트(config.json·state/ 가 있는 곳) — 기본값 없음")
    ap.add_argument("--fetch", action="store_true", help="빗썸 단건 조회로 체결 시각 받기(원장 무접촉 · 진행 파일)")
    ap.add_argument("--apply", action="store_true", help="받은 것 중 시각이 바뀌는 것을 inbox(ex) 로 — tj-core 가 원본 개정·재기장")
    ap.add_argument("--rps", type=float, default=RPS_DEFAULT, help=f"초당 조회 수(기본 {RPS_DEFAULT:g} · 상한 {RPS_CAP:g})")
    ap.add_argument("--limit", type=int, default=0, help="이번 받기 최대 건수(시험 삼아 몇 건만)")
    ap.add_argument("--daily-max", type=int, default=DAILY_MAX_DEFAULT, help=f"한국 날짜 하루 조회 상한(기본 {DAILY_MAX_DEFAULT})")
    ap.add_argument("--show", type=int, default=15, help="미리보기에 날짜가 바뀌는 체결을 몇 줄 보여 줄지(0 = 안 보임)")
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
    path = os.path.join(base, "state", PROGRESS)
    lock = open(path + ".lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("다른 bithumb_filltime_1010 가 실행 중 — 끝난 뒤 다시", file=sys.stderr)
        return 3
    st = load_progress(path)
    preview = not a.fetch and not a.apply
    conn = sqlite3.connect(common.sqlite_ro_uri(db), uri=True, timeout=30)
    try:
        stored, n_done = targets(conn)
        recon = recon_times(conn)
        n_between = between_sells(conn, stored, st) if preview and st["got"] else None
    finally:
        conn.close()
    rps = max(0.05, min(a.rps, RPS_CAP))
    if preview:
        _print_preview(stored, st, n_done, recon, rps, a.show, n_between=n_between)
        print("다음: --fetch(받기 · 빗썸 조회) → 미리보기 → --apply(적용 — tj-core 소비 뒤 반영)")
        return 0
    if a.fetch:
        left = [u for u in stored if u not in st["got"] and u not in st["keep"] and u not in st["bad"]
                and int(st["nf"].get(u) or 0) < NOTFOUND_GIVEUP]
        if not left:
            print("받을 것 없음")
            return 0
        env = common.read_env_file()
        if not env.get("TJ_BITHUMB_KEY") or not env.get("TJ_BITHUMB_SECRET"):
            print(f"키 없음: {common.ENV_PATH} 의 TJ_BITHUMB_KEY·TJ_BITHUMB_SECRET", file=sys.stderr)
            return 2
        import ex_foreign as XF
        try:
            XF._clock_restore()
        except Exception:
            pass
        call = XF._bithumb_caller(env)
        flag = {"stop": False}

        def _sig(*_a):
            flag["stop"] = True
            print("\n중단 신호 — 지금 것까지 저장하고 끝냄(다시 실행하면 이어서)")
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
        n9 = min(a.limit, len(left)) if a.limit else len(left)
        print(f"받기 시작: 단건 조회 최대 {n9}회 · 초당 {rps:g}회 ≈ {n9 / rps / 60:.1f}분 · 하루 상한 {a.daily_max}")
        t0 = time.time()
        res = fetch(stored, st, call, rps, a.limit, a.daily_max, save=lambda: save_progress(path, st), stop_flag=flag)
        print(f"받기 끝: 조회 {res['calls']}회 · 바뀜 후보 {res['got']} · 그대로 {res['keep']} · 검사 실패 {res['bad']} · 404 {res['nf']} · "
              f"실패 {res['err']} · {time.time() - t0:.0f}초" + (f" · 멈춤: {res['stopped']}" if res["stopped"] else ""))
        print("다음: 미리보기(인자 없이)로 비교 표 확인 → --apply")
        return 0 if not res["stopped"] or res["stopped"] == "중단 신호" else 1
    why = _code_ready(os.path.join(HERE, ".."))
    if why:
        print(f"적용 안 함: {why}", file=sys.stderr)
        return 2
    recs = build_records(stored, st)
    n = sum(len(r["fills"]) for r in recs)
    if not recs:
        print("적용할 것 없음(받은 것이 없거나 이미 반영됨)")
        return 0
    import inbox
    w = inbox.SegmentWriter(os.path.join(common.INBOX_DIR, "ex"))
    for r in recs:
        w.append(r)
    w.close()
    print(f"inbox/ex '{RECORD_KIND}' {len(recs)}개(체결 {n}건) — tj-core 가 소비하며 원본 개정·시각 재기장"
          " (로그 '빗썸 지난 체결 시각 바로잡기' · 끝나면 미리보기의 '이미 바로잡음'이 는다)")
    print("  · 새 시각 환율을 그 자리에서 못 받은 체결은 tj-core 가 되돌려 둔다(로그 '시각 바로잡기 되돌림') — 몇 분 뒤 미리보기로 남은 것을 보고 --apply 다시")
    return 0


if __name__ == "__main__":
    sys.exit(main())
