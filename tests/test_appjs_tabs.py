#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import re
import shutil
import subprocess

V2 = os.path.join(T.ROOT, "web", "v2")
sys.path.insert(0, T.SRC)
import http_assets

rd = lambda n: open(os.path.join(V2, n), encoding="utf-8").read()
app, idx = rd("app.js"), rd("index.html")
tabs = sorted(f for f in os.listdir(V2) if f.startswith("tab_") and f.endswith(".js"))
T.chk(bool(tabs), "화면 파일 있음", tabs)
T.chk(sorted(http_assets._V2_TABS) == tabs, "_V2_TABS = 폴더의 tab_*.js 전부", (http_assets._V2_TABS, tabs))
names = lambda s: [x.strip() for x in s.replace("\n", " ").split(",") if x.strip() and not x.strip().startswith("__late")]
ret_names = lambda s: names("\n".join(l for l in s.split("\n") if not l.strip().startswith(", __late:")))
rec = T.app_js()
STRIPPED = "★tab:" not in app
if STRIPPED:
    print("(공개 빌드 — 주석 표식 없음: 머리글·자리 표식 검사 건너뜀 · 되돌림은 코드 줄 구조)")
for fn in tabs:
    n = fn[4:-3]
    t = rd(fn)
    print(f"[1] {fn}")
    T.chk(fn in http_assets._V2_FILES and fn in http_assets._V2_VER_JS, f"{fn} 서빙 목록·버전 URL 안")
    si, sa = idx.find('<script src="/v2/' + fn + '"></script>'), idx.find('<script src="/v2/app.js"></script>')
    T.chk(si >= 0 and sa >= 0 and si < sa, f"{fn} index.html 에서 app.js 앞", (si, sa))
    if not STRIPPED:
        T.chk("여기서 하는 일:" in t[:2000] and "여기 없는 것:" in t[:2000], f"{fn} 머리 '여기서 하는 일 / 여기 없는 것'")
    T.chk(t.count("(window.__tjTabs = window.__tjTabs || {})." + n + " = function (X) {") == 1, f"{fn} 등록 꼴 하나")
    print(f"[2] {fn} ↔ app.js 자리")
    m_x = re.search(r"\n  const \{\n([^{}]*?)\n  \} = X;\n", t)
    m_r = re.search(r"\n  return \{\n(.*?)\n  \};\n\};\s*$", t, re.S)
    if STRIPPED:
        m_s = re.search(r"\n  const \{\n([^{}]*?)\n  \} = tjTab\('" + re.escape(n) + r"', \{\n([^{}]*?)\n  \}\);\n", app)
    else:
        m_s = re.search(r"\n  // ★tab:" + re.escape(n) + r"★[^\n]*\n  const \{\n([^{}]*?)\n  \} = tjTab\('" + re.escape(n) + r"', \{\n([^{}]*?)\n  \}\);   // ★/tab:" + re.escape(n) + "★\n", app)
    T.chk(bool(m_x and m_r and m_s), f"{fn} 빌려 쓰는 이름·돌려주는 이름·app.js 자리 찾음")
    if m_x and m_r and m_s:
        T.chk(names(m_s.group(2)) == names(m_x.group(1)), f"{fn} app.js 가 빌려 주는 이름 = tab 이 받는 이름", (len(names(m_s.group(2))), len(names(m_x.group(1)))))
        T.chk(names(m_s.group(1)) == ret_names(m_r.group(1)), f"{fn} tab 이 돌려주는 이름 = app.js 가 받는 이름", (names(m_s.group(1)), ret_names(m_r.group(1))))
        m_l = re.search(r"\n  \} = X;\n(?:  // 늦은 이름[^\n]*\n)?  let ([^;\n]+);\n  const __late = L => \{\n(.*?)\n  \};\n", t, re.S)
        lt = [l for l in app.split("\n") if (l.startswith("  tjLate_" + n + "(") if STRIPPED else ("// ★late:" + n + "★" in l))]
        if m_l:
            lets = names(m_l.group(1))
            sets = re.findall(r"if \('(\w+)' in L\) \1 = L\.\1;", m_l.group(2))
            filled = []
            for l in lt:
                m_c = re.match(r"  tjLate_" + re.escape(n) + r"\(\{ ([^}]*) \}\);(?:   // ★late:|$)", l)
                filled += names(m_c.group(1)) if m_c else ["?"]
            T.chk(sorted(lets) == sorted(sets) == sorted(filled) and len(filled) == len(set(filled)), f"{fn} 늦은 이름 let = 설정 목록 = 채움 줄 합집합(한 번씩)", (lets, sets, filled))
            T.chk(bool(lt) and all(app.index(l) > app.index("} = tjTab('" + n + "'") for l in lt), f"{fn} 채움 줄 {len(lt)}개 · 전부 화면 자리 뒤")
            T.chk("__late" in [x.strip() for x in m_r.group(1).replace("\n", " ").split(",")] and "__late: tjLate_" + n in m_s.group(1), f"{fn} __late 주고받음")
        else:
            T.chk(not lt and "__late" not in t, f"{fn} 늦은 이름 없음 = 채움 줄·__late 없음")
    if not STRIPPED:
        T.chk(app.count("★tab:" + n + "★") == 1 and app.count("★/tab:" + n + "★") == 1, f"{fn} app.js 자리 표식 하나")
    print(f"[3] {fn} 되돌린 글")
    T.chk("★tab:" + n + "★" not in rec and "tjTab('" + n + "'" not in rec and "tjLate_" + n + "(" not in rec, f"{fn} 되돌린 글에 자리·tjTab·채움 호출 없음")
    if STRIPPED:
        tl = t.split("\n"); i9 = tl.index("  } = X;") + 1
        if tl[i9].startswith("  let ") and tl[i9 + 1] == "  const __late = L => {":
            i9 = tl.index("  };", i9 + 1) + 1
        body = "\n".join(tl[i9:max(k for k, l in enumerate(tl) if l == "  return {")])
    else:
        b0, b1 = "  // ★BEGIN tab:%s★\n" % n, "  // ★END tab:%s★\n" % n
        body = t[t.index(b0) + len(b0):t.index(b1)]
    T.chk(len(body) > 1000 and body in rec, f"{fn} 본문 = 되돌린 글 안에 그대로", len(body))
print("[4] 서버 index.html 버전 URL")
http_assets.V2_DIR, http_assets.V2_FONT_DIR = V2, os.path.join(V2, "fonts")
a = http_assets._asset(os.path.join(V2, "index.html"))["raw"].decode("utf-8")
for fn in tabs:
    T.chk(re.search(r'<script src="/v2/' + re.escape(fn) + r'\?v=[0-9a-f]{16}"></script>', a) is not None, f"{fn} 버전 URL")
T.chk(a.find("/v2/" + tabs[0] + "?v=") < a.find("/v2/app.js?v="), "버전 URL 판에서도 화면 파일이 app.js 앞")

print("[5] node")
NODE = shutil.which("node")
if NODE:
    for fn in tabs + ["app.js"]:
        r = subprocess.run([NODE, "--check", os.path.join(V2, fn)], capture_output=True, text=True, timeout=60)
        T.chk(r.returncode == 0, f"node --check {fn}", r.stderr[-400:])
    js = r'''
const fs = require('fs');
const win = {}; global.window = win;
const fn = process.argv[1];
new Function('window', fs.readFileSync(fn, 'utf8'))(win);
const n = Object.keys(win.__tjTabs || {});
// app.js 의 tjTab 함수 원문만 떼어 돌림(앱 전체는 브라우저가 필요)
const app = fs.readFileSync(process.argv[2], 'utf8');
const m = app.match(/\n  function tjTab\(n, X\) \{\n[\s\S]*?\n  \}\n/);
const tjTab = new Function('window', m[0] + '; return tjTab;')(win);
let got = null, miss = '';
const X = new Proxy({}, { get: (o, k) => (k === 'S' ? { oa: {}, lev: null } : (k === 'A' || k === 'UI_SHEETS' || k === 'LS' || k === 'IC' || k === 'PVM' || k === 'CHAIN_KO') ? new Proxy({}, { get: () => () => '' }) : () => '') });
global.setInterval = () => 0;
global.document = new Proxy({}, { get: () => () => null });   // 설치 때 문서 위임 리스너 등록(영수증 이름표 hover 등) = 아무것도 안 함
try { got = tjTab(n[0], X); } catch (e) { got = 'ERR ' + e.message; }
try { tjTab('nope', X); } catch (e) { miss = e.message; }
console.log(JSON.stringify({ n, keys: got && typeof got === 'object' ? Object.keys(got) : got, miss }));
'''
    for fn in tabs:
        r = subprocess.run([NODE, "-e", js, os.path.join(V2, fn), os.path.join(V2, "app.js")], capture_output=True, text=True, timeout=60)
        import json
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            o = {"raw": r.stdout[-300:], "err": r.stderr[-300:]}
        m_r = re.search(r"\n  return \{\n(.*?)\n  \};\n\};\s*$", rd(fn), re.S)
        T.chk(o.get("n") == [fn[4:-3]], f"{fn} 등록 이름", o)
        T.chk(isinstance(o.get("keys"), list) and [k for k in o["keys"] if k != "__late"] == ret_names(m_r.group(1)), f"{fn} tjTab 실행 = 돌려주는 이름 그대로", o)
        T.chk(o.get("miss") == "[tj] 화면 파일 없음: tab_nope.js", "없는 화면 = '화면 파일 없음' 오류", o)
else:
    print("(node 없음 — 건너뜀)")
T.finish()
