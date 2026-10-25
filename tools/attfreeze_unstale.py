#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)

import attfreeze  # noqa: E402
import fsio  # noqa: E402
import paths  # noqa: E402
import statefile  # noqa: E402

KEYS = ("st", "st0", "sx", "sxt")
OTHER_S = attfreeze.MARK_SLACK_S + attfreeze.BUILD_SLACK_S
WEB_UNITS = ("web.py", "unit_runner.py web")


def _sig(p):
    st = os.stat(p)
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _load(p):
    cur = statefile.read_json(p, None)
    if not (isinstance(cur, dict) and isinstance(cur.get("d"), dict)):
        raise SystemExit("att_frozen.json 없음·손상 — 아무것도 안 바꿈")
    return cur


def targets(store: dict, at: int) -> list:
    return sorted(d for d, r in store["d"].items()
                  if isinstance(r, dict) and r.get("st") == "s" and r.get("st0") == "b" and "sxt" not in r
                  and attfreeze._at_s(r.get("at")) == int(at))


def targets_sxt(store: dict, sxt: int, at: int) -> list:
    return sorted(d for d, r in store["d"].items()
                  if isinstance(r, dict) and r.get("st") == "s" and r.get("st0") == "b" and "sxt" in r
                  and attfreeze._at_s(r.get("sxt")) == int(sxt) and attfreeze._at_s(r.get("at")) == int(at) > int(sxt))


def others_sxt(store: dict, sxt: int, at: int, days: list) -> int:
    if not days:
        return 0
    return sum(1 for m in store.get("dm") or [] if isinstance(m, list) and len(m) >= 3 and str(m[1]) <= max(days)
               and attfreeze._at_s(m[2]) != int(sxt) and int(sxt) - OTHER_S <= attfreeze._at_s(m[2]) <= int(at))


def plan_apply(store: dict, at, now: int, sxt=None):
    new = json.loads(json.dumps(store, ensure_ascii=False))
    days = targets(new, at) if sxt is None else targets_sxt(new, sxt, at)
    undo = {"tool": "attfreeze_unstale", "v": 1, "at": None if at is None else int(at), "applied": now, "days": {}}
    if sxt is not None:
        undo["sxt"] = int(sxt)
    for d in days:
        r = new["d"][d]
        undo["days"][d] = {"before": {k: r[k] for k in KEYS if k in r}, "h": r.get("h"), "rat": r.get("at")}
        r["st"] = "b"
        for k in KEYS[1:]:
            r.pop(k, None)
    if days:
        bf = new.get("bf") if isinstance(new.get("bf"), dict) else {}
        bf2 = {k: v for k, v in bf.items() if k not in ("tries", "err")}
        bf2.update(v=1, unstale=now)
        undo["bf_before"], undo["bf_after"] = new.get("bf"), bf2
        new["bf"] = bf2
    return new, undo, len(days)


def plan_undo(store: dict, undo: dict):
    new = json.loads(json.dumps(store, ensure_ascii=False))
    n = skip = 0
    for d, u in (undo.get("days") or {}).items():
        r = new["d"].get(d)
        if not (isinstance(r, dict) and r.get("st") == "b" and not any(k in r for k in KEYS[1:]) and r.get("h") == u.get("h") and r.get("at") == u.get("rat")):
            skip += 1
            continue
        for k in KEYS:
            r.pop(k, None)
        before = u.get("before") if isinstance(u.get("before"), dict) else {}
        r.update({k: v for k, v in before.items() if k in KEYS})
        n += 1
    bf_ok = "bf_after" in undo and new.get("bf") == undo["bf_after"]
    if bf_ok:
        if undo.get("bf_before") is None:
            new.pop("bf", None)
        else:
            new["bf"] = undo["bf_before"]
    return new, n, skip, bf_ok


def web_running():
    import ledger_restore as lr
    running = lr.running_units(root=paths.BASE_DIR, scripts=lr.UNIT_SCRIPTS)
    if running is None:
        return "프로세스 목록(ps)을 못 읽어 tj-web 정지를 확인할 수 없어요 — 정지를 직접 확인했다면 --no-proc-check"
    hits = [(pid, nm) for pid, nm in running if nm in WEB_UNITS]
    if hits:
        return "먼저 tj-web 을 멈추세요: pm2 stop tj-web\n  떠 있는 것: " + ", ".join(f"{nm}(pid {pid})" for pid, nm in hits)
    return None


def main(argv=None, running=None) -> int:
    ap = argparse.ArgumentParser(description="att_frozen.json '정정 전 값' 오판 1회 되돌림")
    ap.add_argument("--at", type=int, help="그 빌드 시각(epoch 초) — 대상 기록의 at")
    ap.add_argument("--sxt", type=int, help="두 번째 꼴: 그 표식 시각(epoch 초 · 원장 정정 아닌 표식만) — 대상 기록의 sxt(--at 필수)")
    ap.add_argument("--apply", action="store_true", help="실제로 씀(기본 = 점검)")
    ap.add_argument("--undo-out", help="적용 때 되돌리기 파일(없는 새 경로)")
    ap.add_argument("--undo", help="되돌리기 파일로 되돌림")
    ap.add_argument("--no-proc-check", action="store_true", help="tj-web 정지를 직접 확인했을 때만")
    a = ap.parse_args(argv)
    if bool(a.undo) == (a.at is not None or a.sxt is not None):
        ap.error("--at·--sxt(되돌림) 또는 --undo(되돌리기) 하나만")
    if a.sxt is not None and a.at is None:
        ap.error("--sxt 는 --at <그 빌드 복원 시각> 과 같이(한 표식 × 한 빌드만)")
    if a.apply and not a.undo and not a.undo_out:
        ap.error("--apply 는 --undo-out <되돌리기 파일> 필요")
    if a.undo_out and os.path.lexists(a.undo_out):
        ap.error("--undo-out 파일이 이미 있음 — 새 경로로")
    p = paths.state(attfreeze.FILE)
    if not os.path.exists(p):
        print("att_frozen.json 없음 — 0건")
        return 0
    if a.apply and not a.no_proc_check:
        why = (running or web_running)()
        if why:
            print(why)
            return 2
    with fsio.locked(p):
        sig = _sig(p)
        store = _load(p)
        if a.undo:
            undo = json.load(open(a.undo, encoding="utf-8"))
            if undo.get("tool") != "attfreeze_unstale":
                raise SystemExit("되돌리기 파일이 아님 — 아무것도 안 바꿈")
            new, n, skip, bf_ok = plan_undo(store, undo)
            print(f"되돌림 {n}일 · 건너뜀 {skip}일(그 뒤 바뀜) · 복원 세대 표식 {'되돌림' if bf_ok else '그대로(그 뒤 바뀜)'}" + ("" if a.apply else " (점검 — 안 바꿈)"))
            changed = n or bf_ok
        else:
            new, undo, n = plan_apply(store, a.at, int(time.time()), a.sxt)
            what = (f"sxt 없음 · at = {a.at}" if a.sxt is None else f"sxt = {a.sxt} · at = {a.at} > sxt")
            print(f"대상 {n}일(st 's' · st0 'b' · {what}) → 'b' · 복원 세대 표식 {'v 1(다음 빌드가 다시 계산)' if n else '그대로'}"
                  + ("" if a.apply else " (점검 — 안 바꿈)"))
            changed = bool(n)
            if a.sxt is not None and others_sxt(store, a.sxt, a.at, sorted(undo["days"])):
                print(f"거부: 그 빌드에 같이 걸렸을 수 있는 다른 처리 표식 {others_sxt(store, a.sxt, a.at, sorted(undo['days']))}건(dm) — 원장 정정 표식이 섞였을 수 있어 안 바꿈")
                return 2
            if a.apply and n and not fsio.create_exclusive(a.undo_out, json.dumps(undo, ensure_ascii=False).encode("utf-8")):
                raise SystemExit("되돌리기 파일을 못 만듦 — 아무것도 안 바꿈")
        if not (a.apply and changed):
            return 0
        if _sig(p) != sig:
            raise SystemExit("읽은 뒤 att_frozen.json 이 바뀜(tj-web 이 쓰는 중?) — 아무것도 안 바꿈 · tj-web 정지 확인 후 다시")
        statefile.atomic_write_json(p, new)
        print("저장: att_frozen.json" + (f" · 되돌리기 파일: {a.undo_out}" if a.undo_out and not a.undo else ""))
        return 0


if __name__ == "__main__":
    sys.exit(main())
