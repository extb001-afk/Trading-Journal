#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import email.message  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

import web_ctx  # noqa: E402


class _Snap:
    def __init__(self, hero):
        self.hero, self.at, self.gen, self.ver = hero, time.time(), 0, "0123456789abcdef"


class _Builder:
    SNAP_STALE_MAX = 3600

    def __init__(self):
        self.lock, self.cache, self._build_err, self._inval, self.doc = threading.Lock(), "built", None, 0, {}
        self.snaps = type("Snaps", (), {})()
        self.snaps.cur = None

    def prefs(self):
        return self.doc


FB = _Builder()
web_ctx.register(builder=lambda: FB)

import alert_prefs  # noqa: E402
import http_assets  # noqa: E402
import http_post_prefs  # noqa: E402
import http_route  # noqa: E402
import paths  # noqa: E402
import review_daily  # noqa: E402
import statefile  # noqa: E402
import view_hero  # noqa: E402
import web  # noqa: E402
from timeutil import KST  # noqa: E402

print("[U] 서버 설정")
uv = view_hero.ui_prefs_view
T.chk(uv({}) == {"show_networth": False} and uv(None) == {"show_networth": False}, "U1 기본 = 전체 순자산 보이기 끔", uv({}))
T.chk(uv({"show_networth": "true"})["show_networth"] is False and uv({"show_networth": True})["show_networth"] is True,
      "U2 진짜 true 만 켬(글자 = 끔)")
T.chk(uv({"show_total": False, "total_note": 1, "show_networth": True}) == {"show_networth": True},
      "U3 옛 키(show_total·total_note)가 저장 파일에 남아 있어도 화면 칸에 안 나감")
_nl, lk = http_route.post_routes()
T.chk(lk.get("/api/ui_pref") is http_post_prefs.post_ui_pref and "post_ui_pref" in http_post_prefs.__all__, "U4 POST /api/ui_pref = 잠금 안 표(설정 잠금)")


class _H:
    def __init__(self):
        self.out = []

    def _send(self, code, body):
        self.out.append((code, body))


UP = paths.state("ui_prefs.json")


def post(body):
    pr = statefile.read_json(UP, {}) if os.path.exists(UP) else {}
    h = _H()
    FB.cache = "built"
    http_post_prefs.post_ui_pref(h, "/api/ui_pref", body, pr)
    return h.out[-1], (statefile.read_json(UP, {}) if os.path.exists(UP) else {})


(c1, b1), d1 = post({"key": "show_networth", "on": True})
T.chk(c1 == 200 and b1.get("ok") and d1.get("show_networth") is True and uv(d1)["show_networth"] is True and FB.cache is None,
      "U5 켬 저장 → 파일 show_networth true · 화면 칸 켬 · 빌드 캐시 무효화", (c1, b1, d1))
(c2, _b2), d2 = post({"key": "show_networth", "on": False})
T.chk(c2 == 200 and d2.get("show_networth") is False and uv(d2)["show_networth"] is False, "U6 끔 저장 왕복", d2)
bad = [post(b)[0][0] for b in ({"key": "show_networth", "on": "true"}, {"key": "show_total", "on": True}, {"key": "total_note", "on": True}, {})]
T.chk(bad == [400, 400, 400, 400] and statefile.read_json(UP, {}).get("show_networth") is False and "show_total" not in statefile.read_json(UP, {}),
      "U7 잘못된 본문·옛 키 = 400 · 저장값 그대로", bad)

print("[H] 첫 화면 HTML")
TK = datetime.now(KST).strftime("%m-%d")
HERO = {"total": 123456.78, "prev": 120000.0, "prevKrw": 165000000, "flow": 0.0, "month": 2500.5, "monthKrw": 3400000, "monthAp": False,
        "tr": 10.0, "trKrw": 13800, "rate": 1380.0, "todayKey": TK,
        "series": [["10-04", 100000.0, 138000000, 0], ["10-05", 110000.0, None, 1], [TK, 123456.78, None, 0]]}


class _Resp(web.Handler):
    def __init__(self):   # noqa: D107
        self.headers = email.message.Message()
        self.client_address = ("127.0.0.1", 0)
        self.close_connection = True
        self.wfile = io.BytesIO()
        self.sent, self.status = [], None

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, name, value):
        self.sent.append((name.lower(), value))

    def end_headers(self):
        pass


def page(doc):
    FB.doc = doc
    FB.snaps.cur = _Snap(HERO)
    h = _Resp()
    h._send_v2_index(http_assets._asset(os.path.join(T.ROOT, "web", "v2", "index.html")))
    raw = h.wfile.getvalue().decode("utf-8", "replace")
    tag = '<script id="tjHero" type="application/json">'
    i9 = raw.find(tag)
    js = raw[i9 + len(tag):raw.find("</script>", i9)] if i9 >= 0 else ""
    return h.status, (json.loads(js) if js else None)


s0, j0 = page({})
s1, j1 = page({"show_networth": True, "show_total": False})
T.chk(s0 == 200 and j0 is not None and j0.get("total") == 123456.78 and j0.get("series") == HERO["series"] and "hid" not in j0,
      "H1 #tjHero = 총자산·곡선 원값 그대로(기본 설정)", j0)
T.chk(s1 == 200 and j1 == j0, "H2 설정(전체 순자산 켬 · 옛 show_total 끔)과 무관하게 같은 요약", j1)

print("[A] 텔레그램 눈금 · AI 리뷰 입력")
d0 = alert_prefs.default_doc()
doff, _e = alert_prefs.apply_post(d0, {"th": {"digest_axis": False}})
don, _e = alert_prefs.apply_post(doff, {"th": {"digest_axis": True}})
T.chk(d0["th"]["digest_axis"] is True and doff["th"]["digest_axis"] is False and don["th"]["digest_axis"] is True and "axis_set" not in don
      and "digestAxisEff" not in alert_prefs.view({}), "A1 하루 요약 그림 눈금 = 알림 설정 digest_axis 값 그대로(다른 설정 연동·표식 없음)",
      [d0["th"]["digest_axis"], doff["th"]["digest_axis"], don])
T.chk(not hasattr(alert_prefs, "digest_axis_eff") and not hasattr(review_daily, "show_total_pref"),
      "A2 총자산 설정 연동 함수 없음 — 눈금·AI 리뷰 입력 총자산은 늘 종전대로")

print("[J] 화면(node)")
JS = r'''
// app.js(화면 파일을 되돌려 붙인 글)에서 실제 함수 글을 잘라 가짜 S·m 등과 함께 돌린다(잘라 내기는 node 쪽)
const app = require('fs').readFileSync(process.env.TJ_APP, 'utf8');
const cut = (a, b, tail) => { const i = app.indexOf(a), j = i < 0 ? -1 : app.indexOf(b, i); return i < 0 || j < 0 ? '' : app.slice(i, j + tail); };
const blk = cut('  const nwShow = () =>', '  const uiPrefPut = ', 0) + cut('  const uiPrefPut = ', '\n', 0);
const dash = cut('  const oaDashM = (v, o) =>', '\n  }\n', 4);
console.log((blk && dash ? 'PASS ' : 'FAIL ') + 'J0 app.js 스위치·전체 순자산 줄 블록 찾음');
new Function(String.raw`
const S = { cur: 'KRW', hide: false, rand: false, uiPrefs: {}, oa: { d: { items: [1] }, st: 'ok' } };
const m = (v, o) => (v == null ? '—' : '₩' + String(v));
const IC = { right: '>' }, esc = s => String(s), errTxt = s => String(s), pvMoney = () => '₩8,888';
let need = 0; const oaNeed = () => { need++; }, nftNeed = () => {}, nftIncl = () => ({ on: false }), oaItems = () => [{}], oaBrkPend = () => [];
const oaTot = () => ({ net: 100, coin: 80, assets: 30, debt: 10, nftOn: false, nfMask: false, pend: 0 }), oaPendTxt = () => '';
` + blk + '\n' + dash + '\n' + String.raw`
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, d]);
chk(nwShow() === false && oaDashLine() === '' && need === 0, 'J1 기본(설정 없음) = 전체 순자산 줄 없음 · 기타 자산 조회도 안 함', [oaDashLine(), need]);
S.uiPrefs = { show_networth: true };
const ln = oaDashLine();
chk(/전체 순자산/.test(ln) && /₩100/.test(ln) && /코인 ₩80/.test(ln) && /부채 ₩10/.test(ln) && need === 1, 'J2 켬 = 전체 순자산 = 코인 + 기타 − 부채 줄', ln);
S.uiPrefs = { show_total: true }; chk(oaDashLine() === '', 'J3 옛 키(show_total)로는 안 켜짐');
S.uiPrefs = {}; uiPrefPut('show_networth', true); chk(nwShow() === true, 'J4 스위치 켬 = 바로 반영');
let u = uiPrefsMerge({ show_networth: false });
chk(u.show_networth === true, 'J5 저장 직후 옛 상태(폴링) = 방금 바꾼 값 유지', u);
u = uiPrefsMerge({ show_networth: true }); S.uiPrefs = u;
chk(u.show_networth === true && Object.keys(S.uiPend).length === 0, 'J6 서버가 같은 값을 주면 대기 표식 지움', S.uiPend);
u = uiPrefsMerge({ show_networth: false }); chk(u.show_networth === false, 'J7 그 뒤 서버 값을 따름(다른 기기에서 끔)', u);
chk(uiPrefsMerge(undefined).show_networth === undefined, 'J8 옛 서버(칸 없음) = 설정 없음 = 줄 없음');
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok || d === undefined ? '' : '  — ' + JSON.stringify(d)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
`)();
'''
NODE = T.node_bin("전체 순자산 줄 화면")
if NODE:
    p = subprocess.run([NODE, "-"], input=JS, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=60,
                       env=dict(os.environ, TJ_APP=T.app_js_path()))
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
