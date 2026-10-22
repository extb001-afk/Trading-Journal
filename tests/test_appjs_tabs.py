#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

V2 = os.path.join(T.ROOT, "web", "v2")
sys.path.insert(0, T.SRC)
import http_assets  # noqa: E402

rd = lambda n: open(os.path.join(V2, n), encoding="utf-8").read()  # noqa: E731
app, idx = rd("app.js"), rd("index.html")
tabs = sorted(f for f in os.listdir(V2) if f.startswith("tab_") and f.endswith(".js"))
T.chk(bool(tabs), "화면 파일 있음", tabs)
T.chk(sorted(http_assets._V2_TABS) == tabs, "_V2_TABS = 폴더의 tab_*.js 전부", (http_assets._V2_TABS, tabs))
names = lambda s: [x.strip() for x in s.replace("\n", " ").split(",") if x.strip() and not x.strip().startswith("__late")]  # noqa: E731
ret_names = lambda s: names("\n".join(l for l in s.split("\n") if not l.strip().startswith(", __late:")))  # noqa: E731
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
for n9 in ("app.css", "mods.css", "wow.css"):
    h9 = http_assets._asset(os.path.join(V2, n9))["hash"]
    T.chk(http_assets._V2_FILES.get(n9) == "text/css; charset=utf-8" and n9 in http_assets._V2_VER_CSS
          and a.count('<link rel="stylesheet" href="/v2/%s?v=%s"' % (n9, h9)) == 1 and "/v2/%s\"" % n9 not in a,
          f"{n9} 서빙 목록(text/css)·버전 URL(?v=파일 해시) 한 번 · 버전 없는 주소 0")
T.chk(0 < a.find("/v2/app.css?v=") < a.find("/v2/mods.css?v=") < a.find("/v2/wow.css?v=") < a.find("</head>"), "CSS 차례 = app.css → mods.css → wow.css(모듈 글이 index 글 뒤 — 종전 차례) · 머리 안")
T.chk(re.search(r'<link rel="stylesheet" href="/v2/wow\.css\?v=[0-9a-f]{16}" id="wowCss" media="not all">', a) is not None,
      "wow.css = 미리 받되 꺼 둠(media=\"not all\" · id wowCss — wow.js css() 가 열기·대시보드 자리 때 켬)")

print("[5] node")
NODE = T.node_bin("node 문법 검사·탭 등록 실행")
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
        import json  # noqa: E402
        try:
            o = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            o = {"raw": r.stdout[-300:], "err": r.stderr[-300:]}
        m_r = re.search(r"\n  return \{\n(.*?)\n  \};\n\};\s*$", rd(fn), re.S)
        T.chk(o.get("n") == [fn[4:-3]], f"{fn} 등록 이름", o)
        T.chk(isinstance(o.get("keys"), list) and [k for k in o["keys"] if k != "__late"] == ret_names(m_r.group(1)), f"{fn} tjTab 실행 = 돌려주는 이름 그대로", o)
        T.chk(o.get("miss") == "[tj] 화면 파일 없음: tab_nope.js", "없는 화면 = '화면 파일 없음' 오류", o)
print("[6] tjdom.js 자리")
from html.parser import HTMLParser  # noqa: E402


class _Order(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seq, self._cur = [], None

    def handle_comment(self, data):
        if data.strip() == "HERO":
            self.seq.append(("hero",))

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        d = dict(attrs)
        if d.get("src"):
            self.seq.append(("src", d["src"].split("?", 1)[0]))
        elif (d.get("type") or "").startswith("application/json"):
            self.seq.append(("data",))
        else:
            self._cur = []

    def handle_data(self, data):
        if self._cur is not None:
            self._cur.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._cur is not None:
            self.seq.append(("inline", "".join(self._cur)))
            self._cur = None


def _order(html):
    o = _Order()
    o.feed(html)
    return o.seq


T.chk("tjdom.js" in http_assets._V2_FILES and "tjdom.js" in http_assets._V2_VER_JS, "tjdom.js 서빙 목록·버전 URL 안")
for tag6, seq6 in (("원본", _order(idx)), ("서버 판(버전 URL)", _order(a))):
    kinds6 = [x[0] if x[0] != "src" else x[1] for x in seq6]
    hero6 = next((k for k, x in enumerate(kinds6) if x == "hero"), -1)
    fp6 = next((k for k in range(hero6 + 1, len(kinds6)) if kinds6[k] == "inline"), -1) if hero6 >= 0 else -1
    tj6 = [k for k, x in enumerate(kinds6) if x == "/v2/tjdom.js"]
    rest6 = [k for k, x in enumerate(kinds6) if str(x).startswith("/v2/") and x != "/v2/tjdom.js"]
    T.chk(len(tj6) == 1 and 0 <= hero6 < fp6 < tj6[0] and rest6 and min(rest6) > tj6[0] and kinds6[tj6[0] + 1] == "/v2/health.js",
          "%s: tjdom.js 한 번 · 첫 페인트 인라인 뒤 · 바로 다음 health.js · 화면 파일·app.js 모두 그 뒤" % tag6, kinds6)
NODE6 = T.node_bin("인라인 스크립트 TJDOM 미사용 확인")
inl6 = [x[1] for x in _order(idx) if x[0] == "inline"]
if NODE6:
    js6 = ("const fs = require('fs'); const xs = JSON.parse(fs.readFileSync(0, 'utf8')); const out = [];\n"
           "for (const b of xs) { try { new Function(b); out.push(/(^|[^\\w$.])TJDOM([^\\w$]|$)/.test(b) ? 'TJDOM' : 'ok'); } catch (e) { out.push('syntax ' + e.message); } }\n"
           "console.log(JSON.stringify(out));\n")
    import json as _json6  # noqa: E402
    r6 = subprocess.run([NODE6, "-e", js6], input=_json6.dumps(inl6), capture_output=True, text=True, timeout=60)
    T.chk(len(inl6) >= 4 and r6.stdout.strip() == _json6.dumps(["ok"] * len(inl6)).replace(" ", ""),
          "index.html 인라인 스크립트 %d개(머리·글꼴·첫 페인트·부팅 감시) = 구문 OK · TJDOM 안 씀" % len(inl6), (r6.stdout[-300:], r6.stderr[-300:]))
boot6 = inl6[-1:]
js6b = ("const b = require('fs').readFileSync(0, 'utf8'); const ids = {};\n"
        "const mk = t => ({ t, a: {}, k: [], style: {}, setAttribute(n, v) { this.a[n] = v; }, append(...k) { this.k.push(...k); },\n"
        "  replaceChildren(...k) { this.k = k; }, addEventListener() {}, set className(v) { this.a.class = v; } });\n"
        "ids.view = mk('main'); global.window = { __tjBoot: {}, __tjErrs: ['e1'] }; global.localStorage = { getItem: () => null };\n"
        "global.document = { getElementById: i => ids[i] || (ids[i] = mk(i)), createElement: mk }; console.error = () => {};\n"
        "new Function(b)(); const c = ids.view.k[0] || {}; console.log(JSON.stringify([c.t, c.a.class, c.a.role, c.k.length]));\n")
r6b = subprocess.run([NODE6, "-e", js6b], input=boot6[0] if len(boot6) == 1 else "", capture_output=True, text=True, timeout=60) if NODE6 else None
T.chk(r6b is None or r6b.stdout.strip() == '["div","card empty","alert",4]', "부팅 감시 = 첫 페인트 도우미 없이도 오류 카드(자기 DOM API)",
      (len(boot6), r6b and r6b.stdout[-200:], r6b and r6b.stderr[-300:]))
print("[7] 복구 경로 — TJDOM 이 실패해도 글자 카드")
import _sec_lint as L7  # noqa: E402
D7 = L7.js_defs(T.app_js(), ["rescue", "rescueCard", "rescueText"])
NODE7 = T.node_bin("복구 카드 실행")
T.chk(len(D7) == 3, "rescue·rescueCard·rescueText 정의 찾음", sorted(D7))
if NODE7 and len(D7) == 3:
    js7 = ("const mk = t => ({ t, cls: '', kids: [], st: '', at: {}, dataset: {}, set className(v) { this.cls = v; }, set textContent(v) { this.kids = [String(v)]; },\n"
           "  style: { set cssText(v) { this._p.st = v; } }, setAttribute(k, v) { this.at[k] = v; }, append(...xs) { this.kids.push(...xs); },\n"
           "  replaceChildren(...xs) { this.kids = xs; }, set open(v) { this.at.open = v; } });\n"
           "const el = t => { const e = mk(t); e.style._p = e; return e; };\n"
           "global.document = { createElement: el };\n"
           "const VIEW = el('main'); const $ = () => VIEW; const IC = { alert: '' }; const esc = v => String(v);\n"
           "const S = { data: null, rescue: null }; const errTxt = t => String(t); const logError = () => {};\n"
           "const TJDOM = { set() { throw new TypeError('tjdom 깨짐'); } };\n"
           + "\n".join(D7[k] for k in ("rescueCard", "rescueText", "rescue")) + "\n"
           "rescue(new Error('합성 오류 7'), 'view');\n"
           "const txt = n => typeof n === 'string' ? n : (n.kids || []).map(txt).join('');\n"
           "const card = VIEW.kids[0] || {};\n"
           "const btn = []; (function w(n) { if (n && n.t === 'button') btn.push(n.dataset.a); (n && n.kids || []).forEach(w); })(card);\n"
           "console.log(JSON.stringify({ n: VIEW.kids.length, cls: card.cls, role: card.at && card.at.role, text: txt(card), btn, h: VIEW.__h }));\n")
    r7 = subprocess.run([NODE7, "-e", js7], capture_output=True, text=True, timeout=60)
    import json as _json7  # noqa: E402
    try:
        o7 = _json7.loads(r7.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        o7 = {"raw": r7.stdout[-300:], "err": r7.stderr[-300:]}
    T.chk(o7.get("n") == 1 and o7.get("cls") == "card empty" and o7.get("role") == "alert" and o7.get("btn") == ["resetPrefs", "reloadPage"]
          and o7.get("h") == "" and "화면을 그리지 못했어요" in str(o7.get("text")) and "[view] 합성 오류 7" in str(o7.get("text")),
          "TJDOM.set 예외 → #view = 글자 카드 하나(role=alert · 버튼 resetPrefs·reloadPage · 오류 글 그대로)", o7)
T.finish()
