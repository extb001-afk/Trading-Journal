#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import _arch_codemap as C  # noqa: E402
import _arch_ratchet as R  # noqa: E402

chk = T.chk
t0 = time.time()

cases = {
    "원가 엔진 결과 장부(리팩터 P3 S2) — 결과 컨테이너를 한 객체로.\n둘째 줄": "원가 엔진 결과 장부 — 결과 컨테이너를 한 객체로",
    "확인 필요 주소 AI 의견 (aiaddr 10-06 오너: \"기억이 잘 안 나는": "확인 필요 주소 AI 의견",
    "장기 총자산 곡선 — 오너 10-03 \"3개월도 보여주자\".": "장기 총자산 곡선",
    "토큰 세일 원가 연결 — 1차 대상 CCA. 2026-09-26 오너 지시": "토큰 세일 원가 연결 — 1차 대상 CCA",
    "a | b 나눔": "a \\| b 나눔",
    "": "—",
}
got4 = {k: C.responsibility(k) for k in cases}
chk(got4 == cases, "[4] 책임 칸 = 독스트링 첫 줄에서 괄호 속·오너/날짜 꼬리 지움 · '|' 이스케이프 · 없으면 —", got4)
chk(C.responsibility("가" * 200).endswith("…") and len(C.responsibility("가" * 200)) == 141, "[4] 책임 칸 140자 상한(넘으면 …)")

shapes = {
    "modules": {"modules": {"common": "기반", "brokers.kis": "수집기"}},
    "flat": {"common": "기반", "src/brokers/kis.py": "수집기"},
    "layer→list": {"layers": {"기반": ["common"], "수집기": ["brokers/*"]}},
    "list of dict": {"layers": [{"name": "기반", "modules": ["common.py"]}, {"layer": "수집기", "patterns": ["brokers.*"]}]},
    "layer→list(맨 위)": {"기반": ["common"], "수집기": ["brokers.k*"]},
}
got5 = {}
for label, data in shapes.items():
    lp = os.path.join(T.TMP, "layers_%d.json" % len(got5))
    with open(lp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    lay, state = C.load_layers(lp)
    got5[label] = (lay("common"), lay("brokers.kis"), lay("web"), "?" in state)
chk(all(v == ("기반", "수집기", "—", False) for v in got5.values()), "[5] layers.json 다섯 꼴 모두 읽힘(정확한 이름·무늬 · 표에 없는 모듈 = —)", got5)
with open(os.path.join(T.TMP, "layers_bad.json"), "w", encoding="utf-8") as f:
    f.write('{"x": 1}')
chk(C.load_layers(os.path.join(T.TMP, "layers_bad.json"))[0]("common") == "?" and C.load_layers(None)[0]("common") == "—",
    "[5] 모르는 꼴 = '?'(시험 [3] 이 실패로 알림) · 파일 없음 = '—'")

if not R.repo_layout():
    print("(공개판 배치 — 독스트링·주석이 지워져 CODEMAP 재생성 비교를 건너뜀)")
else:
    mods = C.modules(T.ROOT)
    layers = C.load_layers(C.LAYERS)
    text1 = C.render_text(mods, layers)
    srt = all(m["api"] == sorted(m["api"]) and m["deps"] == sorted(m["deps"]) and m["lazy"] == sorted(m["lazy"]) for m in mods)
    chk([m["name"] for m in mods] == sorted(m["name"] for m in mods) and srt,
        "[1] 결정적 — 모듈·공개 API·의존 목록이 모두 이름순(파일 목록·집합 순서에 안 기댐)")
    path = os.path.join(T.ROOT, C.OUT)
    have = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
    first = None
    if have is not None and have != text1:
        a, b = have.split("\n"), text1.split("\n")
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        first = {"줄": i + 1, "커밋본": a[i][:160] if i < len(a) else "(끝)", "다시 만든 글": b[i][:160] if i < len(b) else "(끝)"}
    chk(have == text1, f"[2] {C.OUT} = 지금 src 로 다시 만든 글 — 다르면 `python3 public/tests/_arch_codemap.py --write` 하고 커밋",
        "파일 없음" if have is None else first)
    rows = [ln for ln in text1.split("\n") if ln.startswith("| `")]
    chk(len(rows) == len(mods) == len({m["name"] for m in mods}) and all(f"| `{m['name']}` |" in text1 for m in mods),
        f"[3] 모듈 {len(mods)}개 = 표 줄 {len(rows)}개(빠짐·겹침 없음)")
    hits = C.OWNER_INFO.findall(text1)
    chk(not hits, "[3] CODEMAP 에 오너 정보 꼴 없음(오너 낱말·0x 주소·9자리 넘는 숫자·메일)", hits[:10])
    state = layers[1]
    chk("?" not in state, f"[3] 계층 표 상태: {state}", state)
    print(f"모듈 {len(mods)}개 · 줄 {sum(m['lines'] for m in mods):,} · CODEMAP {len(text1.encode('utf-8')):,}바이트 · {time.time() - t0:.1f}초")
T.finish()
