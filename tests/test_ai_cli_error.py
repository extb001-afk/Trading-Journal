#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T
import _ingest

import review_daily as rd
import sellchart

chk = T.chk
D = "모델 응답을 읽지 못했어요(형식)"
rd._GS.last_err = "Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead, or ask your admin to enable access"
chk("접근이 막혀" in rd.cli_error_text(D), "A1 조직 구독 접근 끔 → 접근이 막혀 있어요")
rd._GS.last_err = "Invalid API key · Please run /login"
chk("로그인이 필요" in rd.cli_error_text(D), "A2 로그인 필요")
rd._GS.last_err = "Claude AI usage limit reached|1791620000"
chk("사용 한도" in rd.cli_error_text(D), "A3 사용 한도")
rd._GS.last_err = "something odd happened"
t4 = rd.cli_error_text(D)
chk(t4.startswith(D) and "something odd" in t4, "A4 모르는 사유 = 기본 문구 + 사유", t4)
rd._GS.last_err = "Error: request rejected; api_key=sk-synthetic-0123456789abcdef0123456789"
t6 = rd.cli_error_text(D)
chk("sk-synthetic-0123456789abcdef0123456789" not in t6 and "0123456789abcdef0123456789" not in t6, "S1 미분류 사유 속 API 키 = 화면 문구에서 가림", t6)
rd._GS.last_err = None
chk(rd.cli_error_text(D) == D, "A5 사유 없음 = 기본 문구")


class _Store:
    kind = "buy"

    def try_lock(self, slots):
        return 1

    def lock_receipt(self, key):
        return 2

    def find(self, *a):
        return None

    def budget_take(self, *a):
        return True

    @staticmethod
    def unlock(fd):
        pass


sellchart.EvalStore.unlock = staticmethod(lambda fd: None)
inp = {"cur": "KRW", "summary": {"score": {"total": 60, "components": {}}}}
cfg = {"review": {"buy_eval_daily_max": 5}}


def _fail_runner(b, p, body):
    rd._GS.last_err = "Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead"
    return None


rec, err = sellchart.run_eval(_Store(), cfg, "2026-07-27", "AAA", "fp1", inp, runner=_fail_runner, binfn=lambda: "/bin/true", model="m")
chk(rec is None and err and "접근이 막혀" in err, "R1 CLI 접근 거부 → 진짜 사유 문구", err)


def _junk_runner(b, p, body):
    rd._GS.last_err = None
    return {"oops": 1}


rec2, err2 = sellchart.run_eval(_Store(), cfg, "2026-07-27", "AAA", "fp2", inp, runner=_junk_runner, binfn=lambda: "/bin/true", model="m")
chk(rec2 is None and err2 == D, "R2 응답은 받았는데 형식 실패 = 형식 문구", err2)
T.finish()
