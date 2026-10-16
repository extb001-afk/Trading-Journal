#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import _harness as T

chk = T.chk
V2 = os.path.join(T.ROOT, "web", "v2")
rd = lambda n: open(os.path.join(V2, n), encoding="utf-8").read()
SJ, APP, CSS = rd("setup.js"), T.app_js(), rd("index.html")

blk = SJ[SJ.index("  const XP_HELP = {"):SJ.index("  const NODE_KEYS = [")]
keys = ["helius", "etherscan", "opensea", "coingecko", "nodereal", "ankr", "quicknode", "alchemy", "chainnodes"]
caps = {k: re.search(r"(?:XP_HELP\.%s = |    %s: )\{[^\n]*?cap: '((?:[^'\\]|\\.)*)'" % (k, k), blk) for k in keys}
chk(all(caps.values()) and all(len(m.group(1)) <= 60 for m in caps.values()), "R1a 키 9개 = 한 줄 cap(60자 이하)", {k: (m and len(m.group(1))) for k, m in caps.items()})
chk("why:" not in blk and all(re.search(r"(?:XP_HELP\.%s = |    %s: )\{[^\n]*need: '[^']+', cost: '[^']+'" % (k, k), blk) for k in keys),
    "R1b 종전 why 문단 없음 · 키마다 need·cost 알약", None)
chk("h.steps.map(s => '<li>' + esc(s) + '</li>')" in SJ and "su-xpbadge" in SJ and "suMore('xp:' + k" in SJ, "R1c 펼친 칸 = 알약 줄 + 한 줄 + 자세히 + 받는 법 그대로", None)
chk("document.addEventListener('toggle'" in SJ and "U.more[" in SJ, "R1d '자세히' 열림은 20초 다시 그리기에도 유지(U.more)", None)
chk("details.su-more" in CSS and ".su-mol" in CSS, "R1e 새 클래스 = index.html 맨 아래 한 블록", None)

nm = re.sub(r"//[^\n]*", "", SJ[SJ.index("function nodeMoreLines"):SJ.index("function nodeOrderHTML")])
chk("su-bbar" in SJ[SJ.index("function nodePlanHTML"):SJ.index("function nodeMoreLines")] and "① Chainnodes" in SJ and "③ 기본 노드" in SJ,
    "R2a 하루 몫 막대 · 넘겨받는 순서 알약", None)
lits = [x for x in re.findall(r"'(?:[^'\\\n]|\\.)*'", nm) if re.search(r"trace|getLogs|nonce", x)]
chk(not lits, "R2b 노드 '자세히' 줄에 trace·getLogs·nonce 없음", lits[:3])

vis = lambda s: re.sub(r'title="[^"]*"', "", s)
chk("(config rabby.enabled)" not in APP and "(config rabby.min_wallet_usd)" not in APP and "AI 평가 꺼짐 — config review." not in APP,
    "R3a 내부 설정 키 = title 에만", None)
chk("nonce = 하루" not in SJ and "EOA 확인 전" not in vis(SJ), "R3b 체인 추천 설명 nonce·EOA → 쉬운 말", None)

hint = SJ[SJ.index("  const NX_HINT = {"):SJ.index("  const BTC_FMT")]
chk(all(re.search(r"%s: \['[^']{1,40}', '" % k, hint) for k in ("tron", "sui", "ton", "btc", "hd")), "R4a 새 체인 안내 = 짧은 한 줄 + title", hint[:200])
chk("TJ_TONCENTER_KEY" in hint and "' + (nxOn() ? '' : 'Enter = 줄바꿈(다음 주소) · ') + '" in SJ, "R4b .env 이름 = title · 한 주소 모드 Enter 줄바꿈 안내 숨김", None)

def cut(src, a, b):
    i = src.index(a)
    return src[i:src.index(b, i + 1)]


js_fn = cut(APP, "  const BF_LIM = [", "  function sxHistBody()") + cut(APP, "  function covSplit(t)", "  function coverageBody() {")
JS = r'''
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, d]);
const pad2 = n => (n < 10 ? '0' : '') + n, isISO = s => /^\d{4}-\d{2}-\d{2}$/.test(String(s == null ? '' : s)), arr = v => (Array.isArray(v) ? v : []);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
let ST = null; const suSt = () => ST; const S = { D: { bfSince: { windowStart: '2026-05-12' } } };
const RealDate = Date;
globalThis.Date = class extends RealDate { constructor(...a) { if (!a.length) super('2026-10-12T09:00:00'); else super(...a); } };
''' + js_fn + r'''
const ex = o => ({ upbit: { set: !!o.upbit }, bithumb: { set: false }, binance: { set: !!o.binance }, bybit: { set: !!o.bybit }, okx: { set: !!o.okx }, kucoin: { set: !!o.kucoin }, gate: { set: !!o.gate } });
ST = { exchanges: ex({ upbit: 1, gate: 1 }), perp: { wallets: [] } };
chk(bfLimitWarn('2020-01-01') === '', '제한 없는 거래소(업비트·게이트)만 연결 = 경고 없음', bfLimitWarn('2020-01-01'));
ST = { exchanges: ex({ okx: 1, bybit: 1, kucoin: 1, binance: 1 }), perp: { wallets: [{ dex: 'hyperliquid' }] } };
const w = bfLimitWarn('2024-01-01');
chk(/OKX 체결은 7\/1 이전 못 받아요/.test(w), 'OKX = 3개월 전 달의 1일(10-12 → 7/1)', w);
chk(/바이비트 체결·손익은 2024-10-12 이전 못 받아요/.test(w), '바이비트 = 730일(2026-10-12 → 2024-10-12)', w);
chk(/쿠코인 체결은 약 2025-10-12 이전/.test(w) && /바이낸스 선물 손익은 약 2025-10-12 이전/.test(w), '쿠코인·바이낸스 선물 = 약 1년', w);
chk(/Hyperliquid 체결은 최근 1만 건까지만/.test(w) && /href="#settings\/data\/limits"/.test(w), 'Hyperliquid = 날짜가 창보다 옛날이면 1만 건 한 줄 · 수집 한계 링크', w);
const w2 = bfLimitWarn('2026-08-01');
chk(!/OKX/.test(w2) && !/바이비트/.test(w2) && !/Hyperliquid/.test(w2) && w2 === '', '한도 안 날짜 = 경고 없음', w2);
const w3 = bfLimitWarn('2026-06-15');
chk(/OKX/.test(w3) && !/바이비트/.test(w3) && !/Hyperliquid/.test(w3), '창 안·OKX 한도 밖 = OKX 만', w3);
const L = '약 4개월(3개월 전 달 1일) 이전 정산 내역(선물 손익·수수료)은 API 가 주지 않아요 — 그 기간 OKX 선물 손익은 빠져요';
const sp = covSplit(L);
chk(sp[0] === '약 4개월(3개월 전 달 1일) 이전 정산 내역(선물 손익·수수료)은 API 가 주지 않아요' && sp[1] === '그 기간 OKX 선물 손익은 빠져요', '긴 이유 = 첫 구절 + 나머지(접힘)', sp);
chk(covSplit('2년 이전 거부')[1] === '' && covSplit('짧은 이유. 끝')[1] === '', '짧은 이유 = 나누지 않음', covSplit('2년 이전 거부'));
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : ' — ' + JSON.stringify(d)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = shutil.which("node")
if not NODE:
    print("SKIP node 없음 — 화면 함수 동작 시험 건너뜀")
else:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        chk(ln.startswith("PASS "), "R5·R6 " + ln[5:])
    chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
