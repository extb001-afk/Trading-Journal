from __future__ import annotations
import math
import os
from datetime import datetime
import logs, paths, statefile
import logging
import calcguard  # noqa: E402
from timeutil import KST

log = logging.getLogger('tj-web')

FS_EX = " · 최초 인식 시가"


FS_CAP_X = 10


FS_HOLD_KO = {"wait": " · 최초 인식 시가 시세 대기(받으면 자동 반영)",
              "ret": " · 보냈던 코인이 돌아온 것인지 확인 못 해 최초 인식 시가 보류",
              "unv": " · 정품·유동성 확인이 안 된 토큰이라 최초 인식 시가 보류",
              "cap": f" · 그날 시세가 실제 매도가의 {FS_CAP_X}배를 넘어 최초 인식 시가 보류",
              "none": " · 그날 시세 기록이 없어 최초 인식 시가 못 매김"}


def _fs_pin_load() -> dict:
    if not os.path.exists(paths.state("first_seen_px.json")):
        return {}
    try:
        d9 = statefile.read_json(paths.state("first_seen_px.json"), {})
    except (Exception, SystemExit) as _cg9:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_fspin:_fs_pin_load", _cg9)
        d9 = None
    if not isinstance(d9, dict) or d9.get("_v") != 1 or not isinstance(d9.get("p"), dict):
        try:
            os.replace(paths.state("first_seen_px.json"), paths.state("first_seen_px.json") + ".bad")
        except OSError:
            pass
        log.warning("최초 인식 시가 고정 저장소 손상 — .bad 로 옮기고 새로 시작")
        return {}
    out, bad9 = {}, 0
    for k9, v9 in d9["p"].items():
        try:
            if not isinstance(k9, str) or not isinstance(v9, (list, tuple)) or not v9 or isinstance(v9[0], (str, bool)):
                raise ValueError("형식")
            u9 = float(v9[0])
            if not (math.isfinite(u9) and u9 > 0):
                raise ValueError("단가")
            t9 = v9[3] if len(v9) > 3 else 0
            t9 = int(t9) if isinstance(t9, (int, float)) and not isinstance(t9, bool) and math.isfinite(t9) else 0
            out[k9] = [u9, str(v9[1]) if len(v9) > 1 else "", str(v9[2]) if len(v9) > 2 else "", t9]
        except (TypeError, ValueError, OverflowError, KeyError, IndexError):
            bad9 += 1
    if bad9:
        log.warning("최초 인식 시가 고정 저장소: 손상 항목 %d개 무시(다음 빌드가 다시 매김)", bad9)
    return out


KD_AT0 = "2028-12-31"
KD_AT_LO, KD_AT_HI = "2026-01-01", "2099-12-31"
KD_PIN = "kr_deemed_px.json"


def kd_at_ok(at: object) -> bool:
    if not isinstance(at, str) or len(at) != 10 or not (KD_AT_LO <= at <= KD_AT_HI):
        return False
    try:
        datetime.strptime(at, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def kd_conf(prefs: object) -> str | None:
    kdp = prefs.get("kr_deemed") if isinstance(prefs, dict) else None
    if not isinstance(kdp, dict) or kdp.get("on") is not True:
        return None
    return kdp["at"] if kd_at_ok(kdp.get("at")) else KD_AT0


def kd_field(prefs: dict, summ: dict | None) -> dict:
    kdp = prefs.get("kr_deemed") if isinstance(prefs.get("kr_deemed"), dict) else {}
    at = kd_conf(prefs) or (kdp.get("at") if kd_at_ok(kdp.get("at")) else KD_AT0)
    out = {"on": kd_conf(prefs) is not None, "at": at}
    if out["on"] and isinstance(summ, dict):
        out.update({k: summ.get(k) for k in ("state", "rows", "add", "wait", "none", "skip", "unk", "n", "up", "lost", "miss", "lostBy")})
    return out


def kd_ts(at: str) -> int:
    return int(datetime.strptime(at, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KST).timestamp())


def kd_pin_load(at: str) -> dict:
    try:
        doc = statefile.read_json(paths.state(KD_PIN), {}) if os.path.exists(paths.state(KD_PIN)) else {}
    except (Exception, SystemExit) as exc:   # noqa: BLE001 [fallback]
        calcguard.swallowed("view_fspin:kd_pin_load", exc)
        return {}
    if not isinstance(doc, dict) or doc.get("_v") != 1 or doc.get("at") != at or not isinstance(doc.get("p"), dict):
        return {}
    out = {}
    for key, val in doc["p"].items():
        try:
            if not isinstance(val, (list, tuple)) or not val or isinstance(val[0], (str, bool)):
                continue
            unit = float(val[0])
            if isinstance(key, str) and math.isfinite(unit) and unit > 0:
                out[key] = [unit, str(val[1]) if len(val) > 1 else "", int(val[2]) if len(val) > 2 and isinstance(val[2], int) else 0]
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            continue
    return out


def kd_pin_save(at: str, new: dict) -> None:
    if not new:
        return
    cur = kd_pin_load(at)
    add = {key: val for key, val in new.items() if key not in cur}
    if not add:
        return
    cur.update(add)
    try:
        statefile.atomic_write_json(paths.state(KD_PIN), {"_v": 1, "at": at, "p": cur})
    except OSError as exc:
        log.warning("의제취득가액 시가 고정 저장 실패(다음 빌드에 다시): %s", logs.safe_err(exc)[:160])


def _fs_pin_save(new9: dict) -> None:
    if not new9:
        return
    cur9 = _fs_pin_load()
    add9 = {k9: v9 for k9, v9 in new9.items() if k9 not in cur9}
    if not add9:
        return
    cur9.update(add9)
    try:
        statefile.atomic_write_json(paths.state("first_seen_px.json"), {"_v": 1, "p": cur9})
    except OSError as e9:
        log.warning("최초 인식 시가 고정 저장 실패(다음 빌드에 다시): %s", logs.safe_err(e9)[:160])
