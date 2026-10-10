#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os

chk = T.chk
OLD = ("옛 기록부터 채워서", "평소보다 늦을 수 있어요(첫날", "첫날은 새 거래 확인이 평소보다 늦을", "첫날 새 거래 확인이 평소보다 늦을", "이보다 늦을 수 있어요")
files = {"setup.js": os.path.join(T.ROOT, "web", "v2", "setup.js"), "health.py": os.path.join(T.SRC, "health.py")}
txt = {k: open(p, encoding="utf-8").read() if os.path.exists(p) else "" for k, p in files.items()}
hits = {k: [o for o in OLD if o in v] for k, v in txt.items()}
chk(all(txt.values()) and not any(hits.values()), "W1 옛 문구 계열 0(설정 화면·헬스)", hits)
import health
chk("옛 기록은" in health.PACE_NOTE_FILL and "뒤에서" in health.PACE_NOTE_FILL and "새 거래 확인" in health.PACE_NOTE_FILL,
    "W2a 헬스 '천천히 확인 중' 안내 = 새 거래 확인 몫 먼저 · 옛 기록은 뒤에서", health.PACE_NOTE_FILL)
chk(txt["setup.js"].count("옛 기록은 뒤에서") >= 3 and "새 거래는 지금 주기대로" in txt["setup.js"],
    "W2b 설정 화면 = '옛 기록은 뒤에서 채우는 중 — 새 거래는 지금 주기대로'", txt["setup.js"].count("옛 기록은 뒤에서"))
chk(txt["health.py"].count("새 거래 확인은 먼저 떼어 둔 몫으로") >= 1, "W2c 헬스 과거 데이터 가져오기 줄 = 새 거래 확인은 먼저 떼어 둔 몫으로", None)
T.finish()
