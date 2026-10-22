#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402

ENV_SHORT = "q7Zx"
ENV_MID = "Wd3kP9a"
ENV_LONG = "SYNTHenvLongVal8823"
ENV_SECRET = "SYNTHsecQwErTy5512"
with open(os.path.join(T.TMP, ".env"), "w", encoding="utf-8") as f:
    f.write("TJ_PIN_HINT=%s\nTJ_MODE_X=%s\nTJ_NOTE_X=%s\nTJ_X_SECRET=%s\nTJ_TG_CHAT=123456789\n" % (ENV_SHORT, ENV_MID, ENV_LONG, ENV_SECRET))
with open(os.path.join(T.ROOT, "config.example.json"), encoding="utf-8") as f:
    CFG = json.load(f)
CFG["wallets"], CFG["exchange_addresses"] = [], []
with open(os.path.join(T.TMP, "config.json"), "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)

import brokers.base as BB  # noqa: E402
import calcguard as CG  # noqa: E402
import onboarding  # noqa: E402


def OLD_BROKER(text, cfg):
    t = str(text or "")
    vals = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str) and len(o) >= 4:
            vals.append(o)
    walk(cfg or {})
    for v in sorted(set(vals), key=len, reverse=True):
        t = t.replace(v, "***")
        if "-" in v:
            t = t.replace(v.replace("-", ""), "***")
    return t[:300]


def OLD_SCRUB(msg, env, extra=()):
    s = str(msg)
    vals = [v for v in list(env.values()) + list(extra) if v and len(v) >= 4]
    for v in sorted(vals, key=len, reverse=True):
        s = s.replace(v, "••••")
    s = re.sub(r"bot\d+:[A-Za-z0-9_-]{10,}", "bot••••", s)
    s = re.sub(r"(api[-_]?key=)[^&\s\"']+", r"\1••••", s, flags=re.I)
    return s[:300]


def hidden_by_old(old_out, vals):
    return [v for v in vals if v not in old_out]


def partial_leak(old_out, new_out, vals):
    bad = []
    for v in hidden_by_old(old_out, vals):
        for g in {v[i:i + 5] for i in range(max(1, len(v) - 4))}:
            if g in new_out and g not in old_out:
                bad.append((v, g))
    return bad


print("[1] brokers.base.redact ⊇ 옛 함수")
ACCT = "12345678-01"
BCFG = {"cfg": {"enabled": True, "app_key": "PSsynthAppKey77", "app_secret": "Zx9Lm2Qw7Er4Ty6Ui1Op3As5",
                "account": ACCT, "nested": {"pin": "7731", "list": ["abcd", {"deep": "Hq2-W8"}]}, "paper": False},
        "tok": {"access": "tokSYNTHaccessToken99887766"}}
BVALS = ["PSsynthAppKey77", "Zx9Lm2Qw7Er4Ty6Ui1Op3As5", ACCT, "1234567801", "7731", "abcd", "Hq2-W8", "Hq2W8", "tokSYNTHaccessToken99887766"]
msg1 = "오류 key=PSsynthAppKey77 sec Zx9Lm2Qw7Er4Ty6Ui1Op3As5 계좌 %s / 1234567801 pin 7731 abcd Hq2-W8 Hq2W8 tok tokSYNTHaccessToken99887766" % ACCT
old1, new1 = OLD_BROKER(msg1, BCFG), BB.redact(msg1, BCFG)
T.chk(set(hidden_by_old(old1, BVALS)) == set(BVALS), "(시험 뜻) 옛 함수는 값 전부 가림", old1)
T.chk(not [v for v in BVALS if v in new1] and "••••" not in new1 and "***" in new1, "새 경로도 값 전부 가림(중첩 cfg · 4자 · 대시 뺀 꼴 · 8자↑ · 토큰)", new1)
CV = "aB7!q,Z9x8Y7"
T.chk(BB.redact("password=" + CV, {"password": CV}) == "password=***" and onboarding.scrub("password=" + CV, [CV]) == "password=***",
      "쉼표 든 값 + key=값 꼴: 값 전체 가림(규칙이 원문에서 자리만 표시 — 앞 치환이 값을 쪼개지 않음)",
      (BB.redact("password=" + CV, {"password": CV}), onboarding.scrub("password=" + CV, [CV])))
IN1 = "aB7!q,api_key=inner&Z9x8Y7"
IN2 = "bot5512345678:AAQwErTyUiOp,Z9x8Y7"
T.chk(onboarding.scrub("실패 " + IN1, [IN1]) == "실패 ***" and onboarding.scrub(IN2, [IN2]) == "***"
      and onboarding.scrub("x api_key=aB7!q&Z9x8Y7", ["api_key=aB7!q&Z9x8Y7"]) == "x ***",
      "설정 화면: 값 안의 api_key=·bot 토큰 꼴도 값 전체 가림(래퍼 정규식도 엔진이 원문에서 함께)",
      (onboarding.scrub("실패 " + IN1, [IN1]), onboarding.scrub(IN2, [IN2])))
T.chk(BB.redact("123", {"account": "1-23"}) == "***" and BB.redact("code abc", {"app_secret": "a-b-c"}) == "code ***",
      "대시 뺀 꼴은 길이 무관(원래 값이 4자↑면 — 옛 증권사 가림과 같음)", (BB.redact("123", {"account": "1-23"}), BB.redact("code abc", {"app_secret": "a-b-c"})))
T.chk(len(BB.redact("x" * 500, BCFG)) == 300 and BB.redact(None, BCFG) == "" and BB.redact("오류 없음", {}) == "오류 없음", "300자 자르기 · None = 빈 글 · 값 없음 = 그대로")
rnd = random.Random(7)
ALNUM = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789,;!"
bad1 = []
for i in range(200):
    vals = ["".join(rnd.choice(ALNUM) for _ in range(rnd.randint(4, 20))) for _ in range(rnd.randint(1, 4))]
    vals = [v[:3] + "-" + v[3:] if rnd.random() < 0.3 and len(v) >= 6 else v for v in vals]
    cfg = {"a": vals[0], "b": {"c": vals[1:], "d": [{"e": "zz"}]}}
    want = vals + [v.replace("-", "") for v in vals if "-" in v]
    text = " · ".join(rnd.choice(["", "password=", "secret: ", "token="]) + rnd.choice(want) + rnd.choice(["", " 오류", "/", "="])
                      for _ in range(6))[:280]
    old, new = OLD_BROKER(text, cfg), BB.redact(text, cfg)
    miss = partial_leak(old, new, [v for v in want if v in text])
    if miss:
        bad1.append((text, new, miss))
T.chk(not bad1, "의사 난수 200건: 옛 함수가 가린 값은 새 경로에서도 가림(5자 조각 부분 누출 0)", bad1[:2])

print("[2] onboarding.scrub ⊇ 옛 함수")
ENV = {"TJ_PIN_HINT": ENV_SHORT, "TJ_MODE_X": ENV_MID, "TJ_NOTE_X": ENV_LONG, "TJ_X_SECRET": ENV_SECRET, "TJ_TG_CHAT": "123456789"}
T.chk(onboarding.ss.read_env() == ENV, "(전제) 설정 화면이 읽는 .env = 시험 .env", onboarding.ss.read_env())
XKEY = "CGsynthKey4471"
msg2 = ("실패 %s %s %s %s chat 123456789 키 %s https://api.telegram.org/bot5512345678:AAQwErTyUiOp/getMe api_key=ab,cd&x=1 "
        "API-KEY=zz9yy8xx7" % (ENV_SHORT, ENV_MID, ENV_LONG, ENV_SECRET, XKEY))
old2, new2 = OLD_SCRUB(msg2, ENV, [XKEY]), onboarding.scrub(msg2, [XKEY])
SVALS = [ENV_SHORT, ENV_MID, ENV_LONG, ENV_SECRET, "123456789", XKEY, "AAQwErTyUiOp", "ab,cd", "zz9yy8xx7"]
T.chk(set(hidden_by_old(old2, SVALS)) == set(SVALS), "(시험 뜻) 옛 함수는 값 전부 가림", old2)
T.chk(not [v for v in SVALS if v in new2] and "bot***" in new2 and "api_key=***" in new2 and "••••" not in new2,
      "새 경로도 전부 가림(.env 에만 있는 4·7자 값 · extra · bot 토큰 · api_key=값 · 표식 ***)", new2)
bad2 = []
for i in range(200):
    ex = ["".join(rnd.choice(ALNUM) for _ in range(rnd.randint(4, 16))) for _ in range(rnd.randint(0, 2))]
    ex = [rnd.choice(["", "api_key=", "bot12345:"]).join([e[:3], e[3:]]) if rnd.random() < 0.3 else e for e in ex]
    pool = list(ENV.values()) + ex
    text = " ".join(rnd.choice(["", "password=", "api_key="]) + rnd.choice(pool) + rnd.choice(["", ":", "/", " 실패"]) for _ in range(5))[:280]
    old, new = OLD_SCRUB(text, ENV, ex), onboarding.scrub(text, ex)
    miss = partial_leak(old, new, [v for v in pool if v in text])
    if miss:
        bad2.append((text, new, miss))
T.chk(not bad2, "의사 난수 200건: 옛 함수가 가린 값은 새 경로에서도 가림(5자 조각 부분 누출 0)", bad2[:2])
T.chk(onboarding.scrub(ValueError("x")) == "x" and len(onboarding.scrub("y" * 900)) == 300, "예외 객체 · 300자 자르기(종전)")

print("[3] 대조군 무변")
CTL = ["주소 0x%s 잔고 0" % ("1f" * 20), "tx 0x%s 확인" % ("ab12cd34" * 8), "체인 목록을 읽지 못했어요 — 다시 시도하세요", "ConnectionRefusedError"]
T.chk([BB.redact(c, BCFG) for c in CTL] == CTL and [onboarding.scrub(c) for c in CTL] == CTL, "주소·tx 해시·보통 문장·예외 이름은 그대로",
      ([BB.redact(c, BCFG) for c in CTL], [onboarding.scrub(c) for c in CTL]))

print("[4] calcguard 사유 저장 = logs.safe_err")
BEARER = "tYp8Ws2Df4Gh6Jk8Lz0Xc2Vb4Nm6Qw"
try:
    raise RuntimeError("노드 실패 https://x.example.invalid/v2/Kd3Fh5Jl7Zn9Xb1Cv3Mq5 %s Bearer %s" % (ENV_SECRET, BEARER))
except RuntimeError as e:
    CG.swallowed("t:wrappers", e)
CG.flush(now=CG.time.time() + 10 ** 6)
with open(CG.path_of(), encoding="utf-8") as f:
    why = ((json.load(f).get("sites") or {}).get("t:wrappers") or {}).get("why") or ""
T.chk(why.startswith("RuntimeError") and BEARER not in why and "Kd3Fh5Jl" not in why and ENV_SECRET[:8] not in why,
      "사유에 Bearer·경로형 키·설정 비밀값 없음", why)

T.finish()
