#!/usr/bin/env python3
import argparse
import gzip
import json
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)

import candles  # noqa: E402
import fsio  # noqa: E402
import paths  # noqa: E402

GZ = b"\x1f\x8b"


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def _plain(rec) -> bytes:
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _disk(n: int) -> int:
    return -(-n // 4096) * 4096


def bar_files(cdir: str):
    for sub in sorted(os.listdir(cdir)):
        d = os.path.join(cdir, sub)
        if os.path.islink(d) or not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if fn.endswith(".json") and not os.path.islink(p) and os.path.isfile(p):
                yield p


def convert(raw: bytes, expand: bool):
    gz = raw[:2] == GZ
    if gz != expand:
        return None, "done"
    try:
        rec = candles._bars_unpack(json.loads(gzip.decompress(raw).decode("utf-8"))) if gz else json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, EOFError, TypeError, RecursionError, zlib.error):
        return None, "bad"
    if not isinstance(rec, dict) or not isinstance(rec.get("candles"), list):
        return None, "other"
    new = _plain(rec) if expand else candles.bars_encode(rec, sig=None)
    back = json.loads(new.decode("utf-8")) if expand else candles._bars_unpack(json.loads(gzip.decompress(new).decode("utf-8")))
    if _canon(back) != _canon(rec):
        return None, "diff"
    return new, rec


def run(cdir: str, apply: bool = False, expand: bool = False, log=print, conv=None) -> dict:
    conv = conv or convert
    n = {"files": 0, "conv": 0, "done": 0, "bad": 0, "other": 0, "diff": 0, "changed": 0,
         "bytes0": 0, "bytes1": 0, "disk0": 0, "disk1": 0}
    if not os.path.isdir(cdir):
        log(f"봉 캐시 폴더 없음: {cdir}")
        return n
    for p in bar_files(cdir):
        n["files"] += 1
        try:
            with open(p, "rb") as f:
                st0 = os.fstat(f.fileno())
                raw = f.read()
        except OSError:
            n["bad"] += 1
            continue
        new, rec = conv(raw, expand)
        if new is None:
            n[rec] += 1
            continue
        if apply:
            try:
                st1 = os.stat(p)
            except OSError:
                n["changed"] += 1
                continue
            if (st1.st_ino, st1.st_size, st1.st_mtime_ns) != (st0.st_ino, st0.st_size, st0.st_mtime_ns):
                n["changed"] += 1
                continue
            fsio.atomic_write_bytes(p, new, makedirs=False)
            try:
                os.utime(p, ns=(st0.st_atime_ns, st0.st_mtime_ns))
            except OSError:
                pass
        n["conv"] += 1
        n["bytes0"] += len(raw)
        n["bytes1"] += len(new)
        n["disk0"] += st0.st_blocks * 512 if hasattr(st0, "st_blocks") else _disk(len(raw))
        n["disk1"] += _disk(len(new))
    M = 1024 * 1024
    log(f"{'적용' if apply else '점검(바꾼 것 없음)'} · {'되돌리기(평문)' if expand else '새 형식(gzip · 무손실)'} · 봉 파일 {n['files']}개 중 "
        f"바꿈{'' if apply else '(예정)'} {n['conv']} · 이미 그 형식 {n['done']} · 깨짐(그대로) {n['bad']} · 봉 아님 {n['other']} · "
        f"왕복 다름(그대로) {n['diff']} · 읽은 뒤 바뀜(건너뜀) {n['changed']}")
    log(f"바꾼 파일 크기 {n['bytes0'] / M:.1f}MB → {n['bytes1'] / M:.1f}MB · 디스크(4KB 블록 어림) {n['disk0'] / M:.1f}MB → {n['disk1'] / M:.1f}MB")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="봉 캐시(state/candles) 새 형식 옮기기 — 기본 점검")
    ap.add_argument("--apply", action="store_true", help="실제로 바꿈(없으면 점검만)")
    ap.add_argument("--expand", action="store_true", help="새 형식 → 평문 JSON(옛 코드로 롤백할 때)")
    ap.add_argument("--no-proc-check", action="store_true", help="유닛 정지 확인 생략(정지를 직접 확인했을 때만)")
    a = ap.parse_args(argv)
    if a.apply and not a.no_proc_check:
        why = units_running()
        if why:
            print(why)
            return 2
    r = run(candles.CACHE_DIR, apply=a.apply, expand=a.expand)
    return 1 if r["diff"] else 0


def units_running():
    import ledger_restore as lr
    running = lr.running_units(root=paths.BASE_DIR, scripts=lr.UNIT_SCRIPTS + ("review_daily.py",))
    if running is None:
        return "프로세스 목록(ps)을 못 읽어 유닛 정지를 확인할 수 없어요 — 정지를 직접 확인했다면 --no-proc-check"
    hits = [(pid, nm) for pid, nm in running if nm in lr.FILES_UNITS]
    if hits:
        return "먼저 봉 파일을 쓰는 유닛을 멈추세요: pm2 stop tj-web tj-review\n  떠 있는 것: " + ", ".join(f"{nm}(pid {pid})" for pid, nm in hits)
    return None


if __name__ == "__main__":
    sys.exit(main())
