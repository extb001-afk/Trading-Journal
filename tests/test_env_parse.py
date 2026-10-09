#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os

import common

with open(common.ENV_PATH, "w", encoding="utf-8") as f:
    f.write("# 합성 값\n"
            "export UPBIT_ACCESS=AAA111\n"
            "UPBIT_SECRET = BBB222\n"
            'TJ_HELIUS_KEY="hk-333"\n'
            "TJ_ETHERSCAN_KEY='es-444'\n"
            "TJ_OKX_KEY=k5\nTJ_OKX_SECRET=s5\nexport TJ_OKX_PASSPHRASE = \"p5\"\n"
            "TJ_ODD=a\"b\n"
            " = 키없음\n"
            "아무말\n")
want = {"UPBIT_ACCESS": "AAA111", "UPBIT_SECRET": "BBB222", "TJ_HELIUS_KEY": "hk-333", "TJ_ETHERSCAN_KEY": "es-444",
        "TJ_OKX_KEY": "k5", "TJ_OKX_SECRET": "s5", "TJ_OKX_PASSPHRASE": "p5", "TJ_ODD": 'a"b'}
got = common.read_env_file()
T.chk(got == want, "공용 규칙: export · '=' 앞뒤 공백 · 같은 따옴표 한 겹 · 키 없는 줄·주석 무시", got)

import settings_store as ss
import alert_bot
import upbit_link
import ex_foreign
import nodekeys

T.chk(ss.read_env() == want, "설정 화면(settings_store.read_env) = 같은 결과", ss.read_env())
T.chk(upbit_link._env() == want, "업비트 수집기 = 같은 결과")
T.chk(ex_foreign._env() == want, "해외 거래소 수집기 = 같은 결과")
T.chk(alert_bot._env() == want, "텔레그램 알림 = 같은 결과")
T.chk(all(nodekeys._env().get(k) == v for k, v in want.items()), "노드 키 = 같은 결과")
T.chk(common._env_file_value("UPBIT_SECRET") == "BBB222" and common._env_file_value("TJ_NONE") is None, "단일 값 읽기")

import web
c9 = web.Spot._okx_creds()
T.chk(c9 == {"key": "k5", "secret": "s5", "passphrase": "p5"}, "웹 OKX 자격(따옴표·export 줄)", c9)

import onboarding
r = T.safe(onboarding._dispatch, "keys/save", {"group": "upbit", "values": {"UPBIT_ACCESS": ["x"], "UPBIT_SECRET": "y"}})
T.chk(isinstance(r, dict) and r.get("ok") is False and "글자" in str(r.get("error")), "키 저장: 배열 값 거부(종전 \"['x']\" 저장)", r)
T.chk(common.read_env_file().get("UPBIT_ACCESS") == "AAA111", "거부 때 .env 그대로")

with open(common.ENV_PATH, "w", encoding="utf-8-sig") as f:
    f.write("UPBIT_ACCESS=BOM111-synthetic-key\nUPBIT_SECRET=BOM222\n")
T.chk(open(common.ENV_PATH, "rb").read(3) == b"\xef\xbb\xbf", "(전제) 합성 .env 가 BOM 으로 시작")
B9 = "BOM111-synthetic-key"
T.chk(common.read_env_file().get("UPBIT_ACCESS") == B9, "W5 BOM .env 첫 키 = 공용 읽기(종전 무시)", common.read_env_file())
T.chk(ss.read_env().get("UPBIT_ACCESS") == B9, "W5 BOM .env 첫 키 = 설정 화면(settings_store.read_env)", ss.read_env())
T.chk(upbit_link._env().get("UPBIT_ACCESS") == B9 and common._env_file_value("UPBIT_ACCESS") == B9, "W5 BOM .env 첫 키 = 수집기·단일 값 읽기")
T.chk(B9 in common._secret_values(), "W5 BOM .env 첫 키 = 로그 비밀값 가림 목록에도(8자 이상 값)")
ss.write_env({"UPBIT_ACCESS": "NEW333"})
raw9 = open(common.ENV_PATH, encoding="utf-8").read()
T.chk(raw9.count("UPBIT_ACCESS=") == 1 and "\ufeff" not in raw9 and common.read_env_file().get("UPBIT_ACCESS") == "NEW333"
      and common.read_env_file().get("UPBIT_SECRET") == "BOM222",
      "W5 BOM .env 에 키 저장 = 첫 줄을 바꿔 씀(종전 = BOM 붙은 옛 줄이 남고 같은 키 줄이 하나 더)", raw9)
T.finish()
