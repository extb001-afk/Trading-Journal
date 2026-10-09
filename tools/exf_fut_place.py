#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import common
import core
from exf_fix_place import _core_stopped, _planner, _ro

KST = timezone(timedelta(hours=9))


def _t(ts):
    return datetime.fromtimestamp(int(ts), KST).strftime("%Y-%m-%d %H:%M:%S")


def _q(qb, dec):
    return int(qb) / 10 ** int(dec)


def _print(plan, curs):
    for m in plan:
        if m.get("err"):
            print(f"{m['ex']:8s} {m['sym']:6s} ★계획 못 세움 — {m['err']}★")
        if m.get("hold"):
            print(f"{m['ex']:8s} {m['sym']:6s} 보류(옛 배치 유지 — 근거 부족): {m['hold']}")
        if not m.get("cands"):
            for b9, why9 in m.get("skip") or ():
                print(f"{m['ex']:8s} {m['sym']:6s} 대사 {_t(b9)} 건너뜀 — {why9}")
            continue
        dec = m["dec"]
        print(f"{m['ex']:8s} {m['sym']:6s} 대사 {len(m['cands'])}건({', '.join(_t(b) for b in m['cands'])}) · 선물 정산 {m['f_sum']}")
        for o in m["del"]:
            print(f"    지움  {_t(o['ts'])} {o['sid']} L{o['leg']} {_q(o['qb'], dec):+,.8f}")
        for o in m["upd"]:
            print(f"    바꿈  {_t(o['ts'])} → {_t(o['ts_new'])} {o['sid']} L{o['leg']} {_q(o['qb'], dec):+,.8f} → {_q(o['qb_new'], dec):+,.8f}")
        for o in m["ins"]:
            print(f"    넣음  {_t(o['ts'])} {o['sid']} L{o['leg']} {_q(o['qb'], dec):+,.8f}")
        for o in m["fut"]:
            print(f"    선물  {_t(o['ts'])} {o['sid']} L{o['leg']} {_q(o['qb'], dec):+,.8f}")
        for b9, why9 in m.get("skip") or ():
            print(f"    건너뜀 대사 {_t(b9)} — {why9}")
    nd = sum(len(m.get("cands") or ()) for m in plan)
    ns = sum(len(m.get("skip") or ()) for m in plan)
    ne = sum(1 for m in plan if m.get("err"))
    nh = sum(1 for m in plan if m.get("hold"))
    print(f"바뀌는 통화 {sum(1 for m in plan if m.get('cands'))} · 다시 놓는 대사 {nd} · 건너뛴 대사 {ns} · 계획 못 세운 통화 {ne}"
          f" · 보류 통화 {nh} · 커서 {json.dumps(curs, ensure_ascii=False)}")


def _undo_load(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if not isinstance(d, dict) or d.get("v") != core.Core.EXF_FUT_V or not isinstance(d.get("plan"), list):
        raise ValueError(f"이 세대(v{core.Core.EXF_FUT_V})의 되돌리기 자료가 아님")
    plan = [m for m in d["plan"] if isinstance(m, dict) and m.get("cands")]
    if not plan:
        raise ValueError("되돌릴 통화가 없는 자료")
    for m in plan:
        ex = m.get("ex")
        if ex not in core.Core.EXF_FUT_EX or m.get("loc") != f"exchange:{ex}" or not isinstance(m.get("aid"), int):
            raise ValueError(f"자료의 거래소·위치·자산이 잘못됨: {ex} {m.get('loc')}")
        for k in ("del", "upd", "ins", "fut"):
            if not isinstance(m.get(k), list) or not all(isinstance(o, dict) for o in m[k]):
                raise ValueError(f"자료 형식 오류: {ex} {m.get('sym')} {k}")
        tot = (-sum(int(o["qb"]) for o in m["del"]) + sum(int(o["qb_new"]) - int(o["qb"]) for o in m["upd"])
               + sum(int(o["qb"]) for o in m["ins"]) + sum(int(o["qb"]) for o in m["fut"]))
        if tot != 0:
            raise ValueError(f"자료의 재배치 합이 0 이 아님({ex} {m.get('sym')} {tot}) — 항목이 빠졌거나 바뀐 자료")
    return d, plan


def _undo(path):
    try:
        d, plan = _undo_load(path)
    except (OSError, TypeError, ValueError, KeyError) as e:
        print(f"거부: 되돌리기 자료 오류 — {e}")
        return 1
    conn = sqlite3.connect(common.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    c = _planner(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        mark9 = str(c._meta_get("exf_fut_place_v") or "").split(":")
        if len(mark9) >= 2 and mark9[1] == "undone":
            raise ValueError("이미 되돌린 원장(표식 %s) — 다시 하려면 --apply" % ":".join(mark9))
        if len(mark9) != 3 or mark9[0] != str(d["v"]):
            raise ValueError("원장의 이관 세대 표식이 자료와 다름(이미 되돌렸거나 다른 원장)")
        if int(mark9[2]) != len(plan) or len({(m["ex"], m["sym"]) for m in plan}) != len(plan):
            raise ValueError(f"자료의 통화 수({len(plan)})가 원장 표식의 적용 통화 수({mark9[2]})와 다름 — 불완전 자료")
        with open(os.path.join(common.STATE_DIR, f"exf_fut_place_v{d['v']}.json"), encoding="utf-8") as fh:
            if json.load(fh) != d:
                raise ValueError("이 원장의 정본 되돌리기 자료(state/exf_fut_place_v%s.json)와 내용이 다름" % d["v"])
        locs = sorted({m["loc"] for m in plan})
        led0, pos0 = _snap(conn, locs)
        for m in plan:
            ex, loc = m["ex"], m["loc"]
            for ns9, lst9 in ((f"{ex}:recon", m["ins"]), (f"{ex}:{common.EXF_FUT_NS}", m["fut"])):
                for o in lst9:
                    r9 = conn.execute("SELECT posting_id, event_ts, qty_base, asset_id, location, event FROM postings WHERE source_kind='exchange'"
                                      " AND source_ns=? AND source_id=? AND leg_seq=?", (ns9, o["sid"], int(o["leg"]))).fetchone()
                    if (r9 is None or int(r9["event_ts"]) != int(o["ts"]) or str(r9["qty_base"]) != str(o["qb"]) or r9["location"] != loc
                            or r9["event"] != "EXF_ADJUST" or int(r9["asset_id"]) != int(o.get("aid") or m["aid"])):
                        raise ValueError(f"지금 원장이 재배치 뒤 모양과 다름: {ns9} {o['sid']} L{o['leg']}")
                    conn.execute("DELETE FROM postings WHERE posting_id=?", (int(r9["posting_id"]),))
                    c._bump_position(int(r9["asset_id"]), -int(o["qb"]), loc)
            for o in m["upd"]:
                r9 = conn.execute("SELECT posting_id, event_ts, qty_base, source_ns, source_id, leg_seq, location, asset_id FROM postings"
                                  " WHERE posting_id=?", (int(o["pid"]),)).fetchone()
                if (r9 is None or int(r9["event_ts"]) != int(o["ts_new"]) or str(r9["qty_base"]) != str(o["qb_new"]) or r9["location"] != loc
                        or r9["source_ns"] != f"{ex}:recon" or r9["source_id"] != o["sid"] or int(r9["leg_seq"]) != int(o["leg"])
                        or int(r9["asset_id"]) != int(m["aid"])):
                    raise ValueError(f"지금 원장이 재배치 뒤 모양과 다름: {o['sid']} L{o['leg']}")
                conn.execute("UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?", (int(o["ts"]), str(o["qb"]), int(o["pid"])))
                c._bump_position(int(m["aid"]), int(o["qb"]) - int(o["qb_new"]), loc)
            for o in m["del"]:
                conn.execute(
                    "INSERT INTO postings (posting_id, source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
                    " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES (?, 'exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'opening',"
                    " 'EXF_ADJUST', ?)", (int(o["pid"]), f"{ex}:recon", o["sid"], int(o["leg"]), int(o["ts"]), int(o["aid"]), loc, str(o["qb"]),
                                          int(o.get("cv") or core.CLASSIFIER_VER)))
                c._bump_position(int(o["aid"]), int(o["qb"]), loc)
        led1, pos1 = _snap(conn, locs)
        bad_l = sorted(k for k in set(led0) | set(led1) if led0.get(k, 0) != led1.get(k, 0))
        bad_p = sorted(k for k in set(pos0) | set(pos1) if Decimal(str(pos0.get(k) or 0)) != Decimal(str(pos1.get(k) or 0)))
        if bad_l or bad_p:
            raise ValueError(f"되돌린 뒤 원장 합·positions 가 달라짐 {bad_l[:5]} {bad_p[:5]}")
        nt9 = 0
        for m in plan:
            ex, sym = m["ex"], m["sym"]
            for b9 in (m["tomb_new"] if isinstance(m.get("tomb_new"), list) else m["cands"]):
                if not isinstance(m.get("tomb_new"), list):
                    has9 = any(not common.exf_is_debt_int("EXF_ADJUST", int(r9[0]), f"{ex}:recon", f"exfrecon:{sym}:{int(b9)}") for r9 in conn.execute(
                        "SELECT leg_seq FROM postings WHERE source_kind='exchange' AND source_ns=? AND source_id=? AND location=? AND event='EXF_ADJUST'",
                        (f"{ex}:recon", f"exfrecon:{sym}:{int(b9)}", m["loc"])))
                    if not has9:
                        continue
                nt9 += conn.execute("DELETE FROM exf_adj_tomb WHERE ex=? AND sym=? AND bts=?", (ex, sym, int(b9))).rowcount
        conn.execute("DELETE FROM meta WHERE k LIKE 'exf\\_fut\\_cur\\_%' ESCAPE '\\' OR k=?", (core.Core.EXF_FUT_WAIT_META,))
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('exf_fut_place_v', ?)", (f"{d['v']}:undone:{int(time.time())}",))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"거부: 되돌림 전체 취소(원장·표식 무변) — {e} · 정본 롤백 = 원장 백업 복원")
        return 1
    try:
        os.remove(os.path.join(common.STATE_DIR, "daily_cache.json"))
    except FileNotFoundError:
        pass
    ts9 = [m["t_from"] for m in plan if m.get("t_from") is not None]
    hd = common.mark_hist_dirty(min(ts9)) if ts9 else None
    print(f"되돌림 {len(plan)} 통화 · 지운 대사 경계 {nt9}줄 삭제 · meta exf_fut_place_v = '{d['v']}:undone:…'(자동 적용 금지 — 다시 하려면 --apply)"
          f" · exf_fut_cur_* 삭제 · daily_cache 무효화 · 장기 곡선 표식 {hd}")
    return 0


def _out_ok(out):
    dst = os.path.abspath(out)
    real = os.path.realpath(dst)
    st = os.path.realpath(common.STATE_DIR)
    if os.path.commonpath([real, st]) == st or real in {os.path.realpath(common.CONFIG_PATH), os.path.realpath(common.ENV_PATH)}:
        raise ValueError(f"state·설정 경로는 출력으로 못 씀({real})")
    if os.path.lexists(dst):
        try:
            with open(dst, encoding="utf-8") as fh:
                prev = json.load(fh)
        except (OSError, ValueError) as e:
            raise ValueError(f"미리보기 계획이 아닌 기존 파일({e.__class__.__name__})") from e
        if not isinstance(prev, dict) or set(prev) != {"plan", "curs"}:
            raise ValueError("미리보기 계획이 아닌 기존 파일은 덮어쓰지 않음")


def _snap(conn, locs):
    if not locs:
        return {}, {}
    q = ",".join("?" * len(locs))
    led = {}
    for a, l, v in conn.execute(f"SELECT asset_id, location, qty_base FROM postings WHERE location IN ({q})", list(locs)):
        k = (int(a), str(l))
        led[k] = led.get(k, 0) + int(v)
    pos = {(int(g), str(l)): str(v) for g, l, v in conn.execute(f"SELECT group_id, location, qty_norm FROM positions WHERE location IN ({q})", list(locs))}
    return led, pos


def _backup(conn):
    bd = os.path.join(common.STATE_DIR, "backups")
    os.makedirs(bd, exist_ok=True)
    size = os.path.getsize(common.DB_PATH) + (os.path.getsize(common.DB_PATH + "-wal") if os.path.exists(common.DB_PATH + "-wal") else 0)
    free = shutil.disk_usage(bd).free
    if free < size * 1.2:
        raise ValueError(f"디스크 여유 {free / 1024 ** 3:.1f}GB < 원장×1.2 {size * 1.2 / 1024 ** 3:.1f}GB — 공간을 비우거나, 따로 백업을 떴으면 --no-backup")
    dst = os.path.join(bd, f"ledger_pre_futplace_v{core.Core.EXF_FUT_V}_{time.strftime('%Y%m%d_%H%M%S')}.db")
    tmp = dst + ".tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        b9 = sqlite3.connect(tmp)
        try:
            conn.backup(b9)
            b9.execute("PRAGMA journal_mode=DELETE")
            if not b9.execute("SELECT count(*) FROM meta").fetchone()[0]:
                raise ValueError("백업본 meta 비어 있음")
        finally:
            b9.close()
        os.replace(tmp, dst)
    except BaseException:
        for sfx in ("", "-wal", "-shm", "-journal"):
            if os.path.exists(tmp + sfx):
                os.remove(tmp + sfx)
        raise
    return dst


def _args(argv):
    ap = argparse.ArgumentParser(prog="exf_fut_place.py", description="선물 정산 재배치(1회 이관) — 미리보기(기본·읽기 전용) · 적용(--apply) · 되돌리기(--undo). "
                                 "적용·되돌리기는 tj-core 정지 중에만.")
    ap.add_argument("--json", metavar="OUT", help="미리보기 계획을 이 파일로(state·설정·.env 안 거부)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="적용(적용할 것이 있으면 먼저 원장 백업 1부) — 되돌린 원장도 다시")
    g.add_argument("--undo", metavar="UNDO_JSON", help="되돌리기(state/exf_fut_place_v<N>.json) — 표식 '세대:undone:시각'(자동 적용 금지)")
    ap.add_argument("--expect", metavar="PLAN_JSON", help="--apply: 검토한 미리보기 계획(--json 출력)과 잠금 안 계획이 같을 때만")
    ap.add_argument("--no-backup", action="store_true", help="--apply: 적용 전 원장 백업 생략(배포 도구처럼 따로 백업을 뜬 경우만)")
    a = ap.parse_args(argv)
    if (a.expect or a.no_backup) and not a.apply:
        ap.error("--expect·--no-backup 은 --apply 와 같이")
    return a


def main(argv=None):
    a = _args(sys.argv[1:] if argv is None else argv)
    out = a.json
    if not os.path.isfile(common.DB_PATH):
        print(f"거부: 원장 없음({common.DB_PATH}) — TJ_BASE 확인(빈 원장을 만들지 않음)")
        return 1
    if a.undo:
        if not _core_stopped():
            print("거부: pm2 에 떠 있는 tj-core(src/core.py)가 있거나 확인하지 못함(우회 옵션 없음)")
            return 1
        return _undo(a.undo)
    if a.apply:
        if not _core_stopped():
            print("거부: pm2 에 떠 있는 tj-core(src/core.py)가 있거나 확인하지 못함(우회 옵션 없음)")
            return 1
        expect = None
        if a.expect:
            try:
                with open(a.expect, encoding="utf-8") as fh:
                    expect = (json.load(fh) or {}).get("plan")
            except (OSError, ValueError) as e:
                print(f"거부: --expect 파일 읽기 실패 — {e}")
                return 1
            if not isinstance(expect, list):
                print("거부: --expect 파일에 plan 없음")
                return 1
        if expect is not None and any(m.get("err") for m in expect):
            print("거부: 검토한 계획에 계획 못 세운 통화가 있음(미리보기 종료 코드 1) — 원장 무변")
            return 1
        conn = sqlite3.connect(common.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        c = _planner(conn)
        before = c._meta_get("exf_fut_place_v")
        sc, pend = c._exf_fut_place_scope()
        locs = sorted({f"exchange:{ex}" for ex in core.Core.EXF_FUT_EX})
        if sc != "done":
            pl0, _cu = c._exf_fut_place_plan(only=pend)
            if any(m.get("cands") for m in pl0) and not a.no_backup:
                try:
                    bk = _backup(conn)
                except (OSError, ValueError, sqlite3.Error) as e:
                    print(f"거부: 적용 전 원장 백업 실패 — {e} · 원장 무변")
                    return 1
                print(f"적용 전 원장 백업: {bk}")
        led0, pos0 = _snap(conn, locs)
        res = c._exf_fut_place_once(expect=expect, redo=True)
        after = c._meta_get("exf_fut_place_v")
        if res is False:
            print("거부: 잠금 안에서 다시 세운 계획이 --expect 와 다름(원장이 그 사이 바뀜) — 원장 무변")
            return 1
        sc1, pend1 = c._exf_fut_place_scope()
        if res is None and sc1 not in ("done", "partial"):
            print("실패: 적용 안 됨(로그 참고) — 원장 무변")
            return 1
        led1, pos1 = _snap(conn, locs)
        bad_l = sorted(k for k in set(led0) | set(led1) if led0.get(k, 0) != led1.get(k, 0))
        bad_p = sorted(k for k in set(pos0) | set(pos1) if pos0.get(k) != pos1.get(k)
                       and not (Decimal(str(pos0.get(k) or 0)) == Decimal(str(pos1.get(k) or 0))))
        if bad_l or bad_p:
            print(f"★일치 검사 실패 — 원장 합 다름 {bad_l[:10]} · positions 다름 {bad_p[:10]} (적용은 끝남 — 배포 도구는 중단·원장까지 롤백)★")
            return 1
        print(f"적용: meta exf_fut_place_v {before} → {after} · 일치 검사 통과(거래소 위치 {len(locs)}곳 · 원장 합 {len(led1)}칸 · positions {len(pos1)}칸 무변)"
              + (f" · ★대기 거래소 {','.join(sorted(pend1))}(다음 대사에 core 가 그 거래소만 다시)★" if sc1 == "partial" else ""))
        return 0
    if out:
        try:
            _out_ok(out)
        except (OSError, ValueError) as e:
            print(f"거부: --json 출력 경로 — {e}")
            return 1
    conn = _ro()
    pc = _planner(conn)
    sc, pend = pc._exf_fut_place_scope()
    if sc == "done":
        print(f"이미 적용(meta exf_fut_place_v={pc._meta_get('exf_fut_place_v')}) — core·--apply 는 다시 하지 않음(아래 계획은 점검용)")
    elif sc == "undone":
        print(f"되돌린 원장(meta exf_fut_place_v={pc._meta_get('exf_fut_place_v')} — 자동 적용 금지) · 아래는 --apply 로 다시 할 때의 계획")
    elif sc == "partial":
        print(f"일부 거래소만 옮긴 원장 — 남은 거래소 {','.join(sorted(pend))} 만")
    plan, curs = pc._exf_fut_place_plan(only=pend)
    _print(plan, curs)
    if out:
        try:
            _out_ok(out)
            common.atomic_write_json(os.path.abspath(out), {"plan": plan, "curs": curs})
        except (OSError, ValueError) as e:
            print(f"거부: --json 출력 경로 — {e}")
            return 1
    if any(m.get("err") for m in plan):
        print("★계획 못 세운 통화가 있음 — 적용하지 말 것(배포 도구 = 중단)★")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
