from __future__ import annotations
import math
import os
import common
import logging
import calcguard

log = logging.getLogger('tj-web')

FS_EX = " · 최초 인식 시가"


FS_PIN_PATH = os.path.join(common.STATE_DIR, "first_seen_px.json")


FS_CAP_X = 10


FS_HOLD_KO = {"wait": " · 최초 인식 시가 시세 대기(받으면 자동 반영)",
              "ret": " · 보냈던 코인이 돌아온 것인지 확인 못 해 최초 인식 시가 보류",
              "unv": " · 정품·유동성 확인이 안 된 토큰이라 최초 인식 시가 보류",
              "cap": f" · 그날 시세가 실제 매도가의 {FS_CAP_X}배를 넘어 최초 인식 시가 보류",
              "none": " · 그날 시세 기록이 없어 최초 인식 시가 못 매김"}


def _fs_pin_load() -> dict:
    if not os.path.exists(FS_PIN_PATH):
        return {}
    try:
        d9 = common.read_json(FS_PIN_PATH, {})
    except (Exception, SystemExit) as _cg9:
        calcguard.swallowed("view_fspin:_fs_pin_load", _cg9)
        d9 = None
    if not isinstance(d9, dict) or d9.get("_v") != 1 or not isinstance(d9.get("p"), dict):
        try:
            os.replace(FS_PIN_PATH, FS_PIN_PATH + ".bad")
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


def _fs_pin_save(new9: dict) -> None:
    if not new9:
        return
    cur9 = _fs_pin_load()
    add9 = {k9: v9 for k9, v9 in new9.items() if k9 not in cur9}
    if not add9:
        return
    cur9.update(add9)
    try:
        common.atomic_write_json(FS_PIN_PATH, {"_v": 1, "p": cur9})
    except OSError as e9:
        log.warning("최초 인식 시가 고정 저장 실패(다음 빌드에 다시): %s", common.safe_err(e9)[:160])
