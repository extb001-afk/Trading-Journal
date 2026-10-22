#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "post_lift.py")):
    chk(True, "공개판 배치 — 비공개 도구(tools/refactor/post_lift.py) 없음 · 건너뜀")
    T.finish()
sys.path.insert(0, TOOLS)
import post_lift as L  # noqa: E402

BASE = '''"""합성 라우팅."""
import json
import paths
import statefile
import web_ctx


class RouteMixin:
    def do_POST(self):
        path = self.path
        locked = False
        try:
            n = 1
            body = json.loads("{}")
            if path == "/api/flow_register":
                return self._flow_register(body)
            web_ctx.prefs_lock().acquire()
            locked = True
            prefs = web_ctx.builder().prefs()
            if path == "/api/outflow_resolve":
                return self._outflow_resolve(body)
            if path == "/api/sale_link":
                # 세일 연결 끊기
                lot9 = str(body.get("lot") or "")
                if not lot9 or len(lot9) > 160:
                    return self._send(400, {"error": f"{lot9} 없음"})
                prefs["sale_link_off"] = [x for x in [lot9] if x]
                statefile.atomic_write_json(paths.state("ui_prefs.json"), prefs)
                return self._send(200, {"ok": True, "lot": lot9})
            if path == "/api/plan":
                for f9 in ("target", "stop"):
                    v9 = body.get(f9)
                    if v9 is None:
                        return self._send(400, {"error": f"{f9} 필요"})
                for f in ("memo",):
                    prefs[f] = body.get(f)
                self._send(200, {"ok": True})
            elif path in ("/api/ignore", "/api/ignore_bulk"):
                keys = body.get("keys") if path.endswith("_bulk") else [body.get("key")]
                self._send(200, {"added": len(keys)})
            else:
                self._send(404, {"error": "not found"})
        finally:
            if locked:
                web_ctx.prefs_lock().release()
'''


def tree(name, route_src):
    root = os.path.join(T.TMP, name)
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, "tools", "refactor"))
    with open(os.path.join(root, "src", "http_route.py"), "w", encoding="utf-8") as f:
        f.write(route_src)
    return root


r1 = tree("plan", BASE)
rows, bad, _imps = L.plan(r1)
chk(not bad and [r["paths"] for r in rows] == [["/api/sale_link"], ["/api/plan"], ["/api/ignore", "/api/ignore_bulk"]],
    "L1 잠금 안 사슬 몸통 3(한 줄 메서드 호출·잠금 밖 = 아님 · 묶인 경로 한 함수)", ([r["paths"] for r in rows], bad))
BADSRC = BASE.replace('                keys = body.get("keys")', '                path = path.lower()\n                keys = n and body.get("keys")')
_r, bad2, _i = L.plan(tree("plan_bad", BADSRC))
chk(any("C1" in b and "'n'" in b for b in bad2) and any("C2" in b and "path" in b for b in bad2), "L1 do_POST 지역 읽기(n)·대입(path) = 거부", bad2)

r2 = tree("lift", BASE)
L.apply(r2)
L.alpha(r2)
with open(os.path.join(r2, "src", "http_post_prefs.py"), encoding="utf-8") as f:
    NEW = f.read()
with open(os.path.join(r2, L.TABLE), encoding="utf-8") as f:
    TAB = json.load(f)
with open(os.path.join(r2, "src", "http_route.py"), encoding="utf-8") as f:
    ROUTE2 = f.read()
bad3, _tp = L.check(BASE, NEW, TAB)
alpha = {r["name"]: r["alpha"] for r in TAB["rows"]}
chk(not bad3, "L2 apply·alpha 뒤 check = 같음", bad3)
chk(alpha["post_plan"].get("f9") == "field" and alpha["post_plan"].get("self") == "h" and alpha["post_sale_link"].get("lot9") == "lot",
    "L2 알파 표(self → h · 끝 9 떼기 · 겹치는 f9 = 손 표 field)", alpha)
chk('f"{field} 필요"' in NEW and 'f"{lot} 없음"' in NEW and "[x for x in [lot] if x]" in NEW and "self" not in NEW.split("__all__")[1],
    "L2 f-문자열 안 식·컴프리헨션 이름도 바뀜 · 옮긴 함수에 self 0", NEW[-600:])
chk("return http_post_prefs.post_sale_link(self, path, body, prefs)" in ROUTE2 and "import http_post_prefs" in ROUTE2
    and "lot9" not in ROUTE2, "L2 사슬 자리 = 새 모듈 함수 한 줄 · import 한 줄", ROUTE2[:400])

MUT = {
    "남은 self": (NEW.replace('return h._send(400, {"error": f"{lot} 없음"})', 'return self._send(400, {"error": f"{lot} 없음"})'), "①"),
    "상수": (NEW.replace("len(lot) > 160", "len(lot) > 161"), "①"),
    "주석": (NEW.replace("# 세일 연결 끊기", "# 세일 연결  끊기"), "②"),
    "전역 따로 묶음": (NEW.replace("import paths\n", "import paths\nstatefile = None\n"), "모듈 꼴"),
    "조건 안 전역 다시 묶음": (NEW + "\nif True:\n    statefile = None\n", "모듈 꼴"),
    "함수 안 global 로 다시 묶음": (NEW + "\n\ndef _zz():\n    global statefile\n    statefile = None\n", "모듈 꼴"),
    "같은 이름 import 둘": (NEW.replace("import paths\n", "import paths\nimport json as statefile\n"), "③"),
    "최상위 호출": (NEW + "\nprint(1)\n", "모듈 꼴"),
    "내장 이름 묶음": (NEW.replace("import paths\n", "import paths\nfrom json import loads as len\n"), "③"),
    "TYPE_CHECKING 을 참인 값으로": (NEW.replace("from typing import TYPE_CHECKING", "from math import pi as TYPE_CHECKING")
                                .replace("    from http.server import BaseHTTPRequestHandler\n",
                                         "    from http.server import BaseHTTPRequestHandler\n    import json as statefile\n"), "모듈 꼴"),
    "인자 **로 전역 가림": (NEW.replace("def post_sale_link(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict):",
                                   "def post_sale_link(h: BaseHTTPRequestHandler, path: str, body: dict, prefs: dict, **statefile):"), "post_sale_link 인자 꼴"),
}
for name, (txt, mark) in MUT.items():
    b, _t = L.check(BASE, txt, TAB)
    chk(txt != NEW and any(x.startswith(mark) for x in b), "L3 잡음: " + name, b)
TAB2 = json.loads(json.dumps(TAB))
for r in TAB2["rows"]:
    if r["name"] == "post_sale_link":
        r["alpha"]["lot9"] = "statefile"
b, _t = L.check(BASE, NEW.replace("lot", "statefile"), TAB2)
chk(any("겹침" in x for x in b), "L3 잡음: 알파 새 이름이 기준 몸통의 다른 이름(전역)을 가림", b)
TAB3 = {"rows": [r for r in TAB["rows"] if r["name"] != "post_ignore"]}
b, _t = L.check(BASE, NEW, TAB3)
chk(any(x.startswith("④") for x in b), "L3 잡음: 표에서 경로 빠짐", b)
T.finish()
