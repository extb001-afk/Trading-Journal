#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402
import _ingest  # noqa: E402,F401

import ai_cli  # noqa: E402
import review_daily as rd  # noqa: E402
import sellchart  # noqa: E402

chk = T.chk
D = "모델 응답을 읽지 못했어요(형식)"
rd._GS.last_err = "Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead, or ask your admin to enable access"
chk("접근이 막혀" in ai_cli.cli_error_text(D), "A1 조직 구독 접근 끔 → 접근이 막혀 있어요")
rd._GS.last_err = "Invalid API key · Please run /login"
chk("로그인이 필요" in ai_cli.cli_error_text(D), "A2 로그인 필요")
rd._GS.last_err = "Claude AI usage limit reached|1791620000"
chk("사용 한도" in ai_cli.cli_error_text(D), "A3 사용 한도")
rd._GS.last_err = "something odd happened"
t4 = ai_cli.cli_error_text(D)
chk(t4.startswith(D) and "something odd" in t4, "A4 모르는 사유 = 기본 문구 + 사유", t4)
rd._GS.last_err = "Error: request rejected; api_key=sk-synthetic-0123456789abcdef0123456789"
t6 = ai_cli.cli_error_text(D)
chk("sk-synthetic-0123456789abcdef0123456789" not in t6 and "0123456789abcdef0123456789" not in t6, "S1 미분류 사유 속 API 키 = 화면 문구에서 가림", t6)
rd._GS.last_err = None
chk(ai_cli.cli_error_text(D) == D, "A5 사유 없음 = 기본 문구")


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


def _fail_runner(b, p, body, msg="Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead"):
    rd._GS.last_err = msg
    return None


rec, err = sellchart.run_eval(_Store(), cfg, "2026-07-27", "AAA", "fp1", inp, runner=_fail_runner, binfn=lambda: "/bin/true", model="m")
chk(rec is None and err and "접근이 막혀" in err, "R1 CLI 접근 거부 → 진짜 사유 문구", err)


def _junk_runner(b, p, body):
    rd._GS.last_err = None
    return {"oops": 1}


rec2, err2 = sellchart.run_eval(_Store(), cfg, "2026-07-27", "AAA", "fp2", inp, runner=_junk_runner, binfn=lambda: "/bin/true", model="m")
chk(rec2 is None and err2 == D, "R2 응답은 받았는데 형식 실패 = 형식 문구", err2)
import logging  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402

FAKE = os.path.join(T.TMP, "fake_claude_err.py")
SEEN = os.path.join(T.TMP, "fake_claude_err_in.txt")
with open(FAKE, "w", encoding="utf-8") as f:
    f.write("#!%s\nimport sys\nopen(%r, 'a', encoding='utf-8').write(sys.stdin.read() + '\\n#####\\n')\n"
            "print('Claude AI usage limit reached|1791620000')\nsys.exit(1)\n" % (sys.executable, SEEN))
os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IXUSR)


class _Rec(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


rec_h = _Rec()
logging.getLogger("tj-review").addHandler(rec_h)
try:
    rec3, err3 = sellchart.run_eval(_Store(), cfg, "2026-07-27", "AAA", "fp3", inp, binfn=lambda: FAKE, model="m")
    seen3 = [x for x in open(SEEN, encoding="utf-8").read().split("\n#####\n") if x]
    chk(rec3 is None and err3 and "사용 한도" in err3 and len(seen3) == 2 and all("<<<DATA " in x and x.index("<<<DATA ") > 0 for x in seen3)
        and sum("(매수평가 2026-07-27|AAA, rc=1)" in m for m in rec_h.msgs) == 2,
        "R3 run_eval 기본 runner = ai_cli.invoke(프롬프트 + 울타리 데이터 · 꼬리표 '매수평가 날짜|심볼' · 재요청 1번 = 2회) · rc 1 사유 → 화면 문구",
        (err3, len(seen3), rec_h.msgs))
    os.remove(SEEN)
    rv4 = rd._run_cli(FAKE, "규칙\n", None, "주소 의견", body="<<<DATA n>>>\n{}\n<<<END n>>>")
    seen4 = [x for x in open(SEEN, encoding="utf-8").read().split("\n#####\n") if x]
    chk(rv4 is None and seen4 == ["규칙\n<<<DATA n>>>\n{}\n<<<END n>>>"] and any("(주소 의견, rc=1)" in m for m in rec_h.msgs),
        "R4 review_daily._run_cli(body 있음) = 조립 없이 stdin = prompt + body 한 번(ai_cli.invoke)", (seen4, rec_h.msgs[-1:]))
finally:
    logging.getLogger("tj-review").removeHandler(rec_h)

_E_INP = {"cur": "KRW", "summary": {"score": {"total": 60, "components": {}}}}


def _e_get(p9):
    return {"ok": True, "side": "buy", "sym": "AAA", "evalFp": "fpE", "evalInput": dict(_E_INP)}


class _EStore(_Store):
    def __init__(self, take=True):
        self.take = take

    def budget_take(self, *a):
        return self.take


def _e_runner(msg):
    return lambda b, p, body: _fail_runner(b, p, body, msg)


_E_ACC = "Your organization has disabled Claude subscription access for Claude Code · Use an Anthropic API key instead, or ask your admin to enable access"
_E_LIM = "Claude AI usage limit reached|1791620000"
_E_LOG = "Invalid API key · Please run /login"
_E_CFG = {"review": {"buy_eval_daily_max": 5, "sell_eval_daily_max": 0}}


def _e_one(runner, take=True, cfg=None):
    return rd.eval_one(cfg or _E_CFG, "2026-07-27", "AAA", "buy", get=_e_get, sleep=lambda s: None, runner=runner,
                       binfn=lambda: "/bin/true", stores={"buy": _EStore(take)})


chk(_e_one(_e_runner(_E_ACC)) == "blocked", "E1 조직 접근 거부(실측 CLI 문구) → 'blocked'(하루 상한 budget 아님)", _e_one(_e_runner(_E_ACC)))
chk(_e_one(_e_runner(_E_LIM)) == "blocked", "E2 Claude 사용 한도(실측 CLI 문구) → 'blocked'(하루 상한 budget 아님)", _e_one(_e_runner(_E_LIM)))
chk(_e_one(_e_runner(_E_LOG)) == "fail", "E3 로그인 필요 → 'fail'(종전 그대로)", _e_one(_e_runner(_E_LOG)))
chk(_e_one(_e_runner(_E_ACC), take=False) == "budget", "E4 하루 상한 소진(budget_msg '한도(N회)를 다 썼어요') → 'budget'")
chk(_e_one(_e_runner(_E_ACC), cfg={"review": {"buy_eval_daily_max": 0}}) == "budget", "E5 상한 0(budget_msg '꺼져 있어요') → 'budget'")
rd_rec = _Rec()
rd.log.addHandler(rd_rec)
try:
    c6 = rd.receipt_evals(_E_CFG, [("2026-07-27", "AAA"), ("2026-07-28", "AAA")], get=_e_get, sleep=lambda s: None,
                          runner=_e_runner(_E_ACC), binfn=lambda: "/bin/true", stores={"buy": _EStore()})
finally:
    rd.log.removeHandler(rd_rec)
sum6 = [m for m in rd_rec.msgs if m.startswith("AI 매도·매수 평가:")]
chk(c6.get("budget") == 0 and c6.get("blocked") == 1 and c6.get("skip") == 1 and "하루 상한" not in str(c6.get("stopped"))
    and "Claude CLI 막힘" in str(c6.get("stopped")) and sum6 and "하루 상한" not in sum6[-1] and "Claude CLI 막힘" in sum6[-1]
    and any("평가 실패" in m and "접근이 막혀" in m for m in rd_rec.msgs),
    "E6 receipt_evals: 접근 거부 = 그 쪽 멈춤(다음 건 안 부름 · 종전 동작) · 사유 'Claude CLI 막힘'(하루 상한 아님) · 경고에 진짜 사유", (c6, sum6))
T.finish()
