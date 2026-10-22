#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402

import envfile, paths  # noqa: E402
import settings_store as ss  # noqa: E402
import depaddr  # noqa: E402
import liq_watch  # noqa: E402
import ex_foreign  # noqa: E402

EX7 = ["upbit", "bithumb", "binance", "bybit", "okx", "kucoin", "gate"]
EX8 = EX7 + ["coinbase"]
T.chk(list(envfile.EX_KEYS) == EX8 and list(ss.EXCHANGES) == EX8, "[1] 거래소 차례 = 표 · 설정 화면 같음",
      (list(envfile.EX_KEYS), list(ss.EXCHANGES)))
scr = {ex: tuple(k for k, _lab in g["fields"]) for ex, g in ss.EXCHANGES.items()}
T.chk(scr == dict(envfile.EX_KEYS), "[1] 키 이름·차례 = 설정 화면 fields", (scr, envfile.EX_KEYS))
T.chk(all(isinstance(v, tuple) and v and all(isinstance(k, str) and k for k in v) for v in envfile.EX_KEYS.values()),
      "[1] 표 값 = 비지 않은 문자열 튜플")
T.chk("EX_KEYS" in envfile.__all__, "[1] 공개 이름(__all__)")

E = envfile.EX_KEYS
T.chk(list(depaddr.NEED) == EX7 and all(depaddr.NEED[ex] is E[ex] for ex in EX7), "[2] depaddr.NEED = 표(같은 객체 · 차례)", depaddr.NEED)
T.chk(list(liq_watch.NEED_KEYS) == ["binance", "bybit", "okx"] and all(v is E[ex] for ex, v in liq_watch.NEED_KEYS.items()),
      "[2] liq_watch.NEED_KEYS = 표(같은 객체 · 차례)", liq_watch.NEED_KEYS)
T.chk(list(liq_watch.LEV_KEYS) == ["binance", "bybit", "okx", "kucoin", "gate"]
      and all(v is E[ex] for ex, v in liq_watch.LEV_KEYS.items()), "[2] liq_watch.LEV_KEYS = 표(같은 객체 · 차례)", liq_watch.LEV_KEYS)
T.chk(list(ex_foreign.FETCHERS) == ["binance", "bybit", "okx", "kucoin", "gate", "bithumb", "coinbase"]
      and all(need is E[ex] and callable(fn) for ex, (fn, need) in ex_foreign.FETCHERS.items()),
      "[2] ex_foreign.FETCHERS 둘째 칸 = 표(같은 객체 · 차례)", {ex: v[1] for ex, v in ex_foreign.FETCHERS.items()})
T.chk(ex_foreign.FETCHERS["binance"][0] is ex_foreign.fetch_binance and ex_foreign.FETCHERS["bithumb"][0] is ex_foreign.fetch_bithumb,
      "[2] FETCHERS 첫 칸(수집 함수) 그대로")
OLD = {"upbit": ("UPBIT_ACCESS", "UPBIT_SECRET"), "bithumb": ("TJ_BITHUMB_KEY", "TJ_BITHUMB_SECRET"),
       "binance": ("TJ_BINANCE_KEY", "TJ_BINANCE_SECRET"), "bybit": ("TJ_BYBIT_KEY", "TJ_BYBIT_SECRET"),
       "okx": ("TJ_OKX_KEY", "TJ_OKX_SECRET", "TJ_OKX_PASSPHRASE"), "kucoin": ("TJ_KUCOIN_KEY", "TJ_KUCOIN_SECRET", "TJ_KUCOIN_PASSPHRASE"),
       "gate": ("TJ_GATE_KEY", "TJ_GATE_SECRET"), "coinbase": ("TJ_COINBASE_KEY_NAME", "TJ_COINBASE_SECRET")}
T.chk(dict(E) == OLD and list(E) == list(OLD), "[2] 표 값 = 6-4 전 사본 값 + 코인베이스(CDP 키 이름 · EC 비밀키 본문)", E)


def _old_read_env() -> dict:
    out = {}
    try:
        with open(paths.ENV_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
                kv = envfile.parse_env_line(line)
                if kv and kv[0]:
                    out[kv[0]] = kv[1]
    except OSError:
        pass
    return out


def _run(fn):
    try:
        return ("ok", fn())
    except Exception as e:
        return ("exc", type(e).__name__)


CASES = [
    ("빈 파일", b""),
    ("빈 줄·공백 줄만", b"\n\n   \n\t\n"),
    ("주석", b"# A=1\n  # B=2\n#C\nD=4\n"),
    ("값 안 #", b"A=x#y\nB = # z\n"),
    ("따옴표 한 겹", b"A=\"v1\"\nB='v2'\nC=\"\"\nD=''\n"),
    ("따옴표 짝 안 맞음·한 글자", b"A=\"v1'\nB=\"\nC='\nD=\"a\nE=a\"\n"),
    ("따옴표 두 겹·안쪽 공백", b"A=\"'v'\"\nB=\" v \"\nC='\"x\"'\n"),
    ("'=' 여러 개", b"A=b=c\nB==x\nC=\"=\"=\n"),
    ("'=' 앞뒤 공백·탭", b"A = 1\nB\t=\t2\n  C=3  \n"),
    ("export 접두", b"export A=1\nexport  B = 2\nexport=3\nexportC=4\nexport\tD=5\nEXPORT E=6\n"),
    ("export 만·키 없음", b"export =1\n = 2\n=\n=x\nexport \nexport\n"),
    ("'=' 없는 줄", "그냥말\nA\nB=1\n".encode("utf-8")),
    ("빈 값", b"A=\nB=  \n"),
    ("같은 키 = 뒤 줄이 덮음", b"A=1\nA=2\nexport A=3\n"),
    ("BOM", b"\xef\xbb\xbfA=1\nB=2\n"),
    ("CRLF", b"A=1\r\nB='2'\r\n# c\r\n"),
    ("CR 만", b"A=1\rB=2\r"),
    ("끝 줄바꿈 없음", b"A=1\nB=2"),
    ("한글·유니코드", "A=값\n키=v\nB= x \n".encode("utf-8")),
    ("공백 든 키", b"A B=1\n export C=2\n"),
    ("잘못된 UTF-8", b"A=1\nB=\xff\xfe\n"),
]
E9 = paths.ENV_PATH
if not os.path.realpath(E9).startswith(os.path.realpath(T.TMP) + os.sep):
    raise SystemExit(f"시험 .env 가 임시 폴더 밖: {E9}")
diff = []
for name, raw in CASES:
    with open(E9, "wb") as f:
        f.write(raw)
    a, b, c = _run(_old_read_env), _run(ss.read_env), _run(envfile.read_env_file)
    if not (a == b == c):
        diff.append((name, a, b, c))
os.remove(E9)
miss = (_run(_old_read_env), _run(ss.read_env), _run(envfile.read_env_file))
os.mkdir(E9)
dir9 = (_run(_old_read_env), _run(ss.read_env), _run(envfile.read_env_file))
os.rmdir(E9)
for name, r9 in (("없는 파일", miss), ("폴더", dir9)):
    if not (r9[0] == r9[1] == r9[2] == ("ok", {})):
        diff.append((name,) + r9)
T.chk(not diff, f"[3] read_env 경계 입력 {len(CASES) + 2}가지 = 옛 몸체 · 위임 · envfile 셋 다 같음(값·예외 종류)", diff)
T.chk(sum(1 for _n, raw in CASES if b"=" in raw) >= 18, "(전제) 경계 표가 비지 않음")
T.finish()
