from __future__ import annotations

import logging
from typing import NamedTuple

import calcguard

__all__ = ["Migration", "REGISTRY", "STARTUP", "startup"]

log = logging.getLogger("tj-core")


class Migration(NamedTuple):
    n: int
    name: str
    kind: str
    stamp: str
    where: str
    callers: tuple
    again: str
    data_rev: int
    rebuild: str
    guard: str = ""
    fail_log: str = ""


_CARRY = "도장 이월 — rebuild2 가 라이브 meta 를 가져가 shadow 에서 다시 안 돎(원장 재생이 이 변환을 증명하지 않음)"

REGISTRY = (
    Migration(0, "기준 스키마", "스키마 확장", "schema_version", "db.DDL", ("db.open_db",),
              "없음(CREATE … IF NOT EXISTS 멱등 · 정본 = db.DDL · db.SCHEMA_VERSION · db.DATA_REV)", 0,
              "새 원장 = 같은 DDL(open_db) · 지문 = test_ledger_schema"),
    Migration(1, "_reclass_plain_xfer_once", "데이터 1회", "reclass_q_plainxfer", "core_classify.ClassifyMixin._reclass_plain_xfer_once",
              ("migrate.startup",), "없음", 0, _CARRY,
              "core:Core.run[_reclass_plain_xfer_once]", "평범한 전송 재분류 실패(원장 무변, 다음 기동 재시도): %s"),
    Migration(2, "_reclass_added_lp_mgrs_once", "시드 1회", "reclass_lp_mgr:<체인>:<관리자>",
              "core_classify.ClassifyMixin._reclass_added_lp_mgrs_once", ("migrate.startup",), "시드에 관리자 추가(added 날짜)", 0, _CARRY,
              "core:Core.run[_reclass_added_lp_mgrs_once]", "새 LP 관리자 재분류 실패(원장 무변, 다음 기동 재시도): %s"),
    Migration(3, "_out_px_band_fix_once", "데이터 1회", "px_out_band_r", "core_pricing.PricingMixin._out_px_band_fix_once",
              ("migrate.startup",), "없음", 0, _CARRY,
              "core:Core.run[_out_px_band_fix_once]", "보낸 내역 시가 되돌림 실패(원장 무변, 다음 기동 재시도): %s"),
    Migration(4, "_exf_redate_once", "데이터 1회", "exf_redate_m", "core_exf_late.ExfLateMixin._exf_redate_once",
              ("core_exf.ExfMixin.exf_recon_pass",), "없음", 0, _CARRY),
    Migration(5, "_exf_debt_redate_once", "데이터 1회", "exf_debt_redate_t", "core_exf_late.ExfLateMixin._exf_debt_redate_once",
              ("core_exf.ExfMixin.exf_recon_pass",), "없음", 0, _CARRY),
    Migration(6, "_exf_fix_place_once", "세대 1회", "exf_fix_place_v", "core_exf.ExfMixin._exf_fix_place_once",
              ("core_exf.ExfMixin.exf_recon_pass", "tools/exf_fix_place._apply"), "세대 번호 ExfMixin.EXF_FIX_V", 0, _CARRY),
    Migration(7, "_rpc_recon_reset", "데이터 1회", "recon_reset_rpc_<체인>", "core_recon.ReconMixin._rpc_recon_reset",
              ("core_recon.ReconMixin.recon_pass",), "체인별(설정 chains 의 RPC 조회 체인 · 백필 끝 · 대사 도장 있음)", 0, _CARRY),
    Migration(8, "_exf_fut_place_once", "세대 1회", "exf_fut_place_v", "core_exf_fut.ExfFutMixin._exf_fut_place_once",
              ("core_exf.ExfMixin.exf_recon_pass", "tools/exf_fut_place._apply"), "세대 번호 ExfFutMixin.EXF_FUT_V · 도구 redo", 1, _CARRY),
    Migration(9, "apply_cell", "데이터 1회", "autofix:<ex>:<SYM>", "autofix_apply.apply_cell",
              ("tools/ledger_rowfix._run_autofix",), "칸마다(영수증·끄기 표식 없을 때 · core 경로 = autofix.enabled 만 — autofix_apply.core_pass)", 2,
              "자동 행·영수증 이월 — rebuild2 가 opening 행을 그대로 다시 넣고(시각 모름 = 역산 안 함) meta 영수증·묘비·재파생 막음 표식을 가져감"),
    Migration(10, "_split_rev_mark", "데이터 1회", "upbit_split_v", "core_fills.FillsMixin._split_rev_mark",
              ("core_fills.FillsMixin._consume_fills",), "분할 레그를 넣을 때마다(도장 있으면 data_rev 만 멱등 · 옛 합산 주문 바꾸기 = tools/ledger_rowfix --kind upbit_split --apply)", 3,
              "재구축 = 최신 raw_ex 를 _consume_fills 가 다시 기장 → 같은 분할 레그·도장·data_rev 3(분할 주문이 있을 때)"),
)

STARTUP = tuple(m.n for m in REGISTRY if "migrate.startup" in m.callers)


def startup(core: "core.Core") -> None:  # noqa: F821
    for n, call in ((1, lambda: core._reclass_plain_xfer_once()),
                    (2, lambda: core._reclass_added_lp_mgrs_once()),
                    (3, lambda: core.svc_price._out_px_band_fix_once())):
        m = REGISTRY[n]
        try:
            call()
        except Exception as e:  # noqa: BLE001 [isolate]
            calcguard.swallowed(m.guard, e, expected=calcguard.db_env(e))
            core.conn.rollback()
            log.error(m.fail_log, e)
