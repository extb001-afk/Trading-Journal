#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import shutil
import subprocess

APP = T.app_js_path()
app = open(APP, encoding="utf-8").read()

print("[1] 정적")
T.chk("t = t.replace(/([+\\-−]?)\\$([\\d,]+(?:\\.\\d+)?(?:[eE][+\\-]?\\d+)?)(?![\\d])/g, (a, sg, v) =>" in app,
      "C2: hs() '$' 금액 정규식이 지수 표기(e±N)까지 한 수로(moneyTxt 와 같은 꼴)")
T.chk("const step = Math.max(niceStep((hi - lo) * kr / 3), axRes);" in app, "C5: 눈금 간격 = max(종전 nice 간격, 눈금 글자 정밀도)")

print("[2] 함수(node)")
JS = r'''import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
try {
  // 숫자 표기 블록(nf · m · px · moneyTxt · hs …) — 실제 app.js 그대로(자르는 표식 = 코드 줄만 — 공개 빌드는 주석 문구를 바꾼다)
  const B = cut('  const NFC = {};', '  const hq = s => {');
  const S = { cur: 'KRW', hide: false, rand: false, mobile: false, D: { rate: 1385, rateLive: true } };
  const deps = { S, num: v => { const n = Number(v); return isFinite(n) ? n : 0; }, LS: { get: () => null }, window: { crypto: { getRandomValues(b) { b[0] = 123456789; } } },
    trimZeros: s => (s.indexOf('.') >= 0 ? s.replace(/0+$/, '').replace(/\.$/, '') : s), esc: v => String(v == null ? '' : v), fmtTs: v => String(v) };
  const names = Object.keys(deps);
  // chartSVG 눈금 계산(kr ~ lo/hi 맞춤) — 실제 줄 그대로 함수로
  const TK = cut('    const kr = (S.cur === ', '    const pad = (hi - lo) * 0.06;');
  const F = new Function(...names, B + '\nconst ticksOf = (lo, hi) => {\n' + TK + '\nreturn ticks; };\nreturn { hs, m, ticksOf };')(...names.map(k => deps[k]));
  // ── C2 ──
  S.cur = 'KRW';
  const a1 = F.hs('900,000,000.0000 PEPE 원가미상 보유 · 평균 매수가 $7.2e-06 → 원가 $6,480.00 적용', true);
  chk(a1 === '900,000,000 PEPE 원가 미확인 보유 · 평균 매수가 $7.2e-06 → 원가 ₩8,974,800 적용' && !/₩[\d,]+e/.test(a1), "C2 원화: 1 미만 지수 단가 = 원문 '$7.2e-06'(종전 '₩9,972e-06') · 옆 금액은 환산", a1);
  const a2 = F.hs('09-14 온체인 매수 1,000.0000 · ★원가 지정 $1.234e-05/개 적용★', true), a3 = F.hs('풀 유동성 $812.40 < $1,000 (가격 $3.1e-09)', true);
  chk(a2 === '09-14 온체인 매수 1,000 · 원가 지정 $1.234e-05/개 적용' && a3 === '풀 유동성 ₩1,125,174 < ₩1,385,000 (가격 $3.1e-09)', "C2 원화: '원가 지정 $1.234e-05/개' · 가격 이상 안내 '$3.1e-09' 원문(종전 ₩1,709e-05 · ₩4,294e-09)", [a2, a3]);
  const a4 = F.hs('$1.23457e+06', true), a5 = F.hs('−$1.5e+06 손실', true);
  chk(a4 === '₩1,709,879,450' && a5 === '−₩2,077,500,000 손실', "C2 원화: '$1.23457e+06' = ₩1,709,879,450 · '−$1.5e+06' = −₩2,077,500,000(종전 ₩1,710e+06)", [a4, a5]);
  S.cur = 'USD';
  const u1 = F.hs('$1.23457e+06', true), u2 = F.hs('평균 매수가 $7.2e-06 → 원가 $6,480.00 적용', true);
  chk(u1 === '$1,234,570' && u2 === '평균 매수가 $7.2e-06 → 원가 $6,480 적용', "C2 달러: '$1.23457e+06' = $1,234,570(종전 '$1.23e+06') · 작은 지수 원문", [u1, u2]);
  // 기존 문자열 출력 불변 — 수정 전 app.js 로 얻은 값 그대로
  const SAME = [
    ['KRW', '수수료 $12.50 · 가스 $0.30', '수수료 ₩17,313 · 가스 $0.3', '수수료 ₩17,313 · 가스 ₩416'],
    ['KRW', '평균 매수가 $0.94 → 원가 $17,719.00 적용', '평균 매수가 $0.94 → 원가 ₩24,540,815 적용', '평균 매수가 ₩1,302 → 원가 ₩24,540,815 적용'],
    ['KRW', '$1,234.50 매도', '₩1,709,783 매도', '₩1,709,783 매도'], ['KRW', '-$0.004', '-$0.004', '−₩6'], ['KRW', '+$0.5', '+$0.5', '+₩693'],
    ['KRW', '$12', '₩16,620', '₩16,620'], ['KRW', '수수료 0.30$', '수수료 ₩416', '수수료 ₩416'], ['KRW', '1,234.5678 ETH', '1,235 ETH', '1,235 ETH'],
    ['KRW', '$1,000,000.00', '₩1,385,000,000', '₩1,385,000,000'], ['KRW', '−$5', '−₩6,925', '−₩6,925'], ['KRW', '$0.999', '$0.999', '₩1,384'],
    ['KRW', '$99.999', '₩138,499', '₩138,499'], ['KRW', '+$0', '+$0', '₩0'], ['KRW', 'ERC20 $5e', 'ERC20 ₩6,925e', 'ERC20 ₩6,925e'],
    ['USD', '수수료 $12.50 · 가스 $0.30', '수수료 $12.5 · 가스 $0.3', '수수료 $12.5 · 가스 $0.3'], ['USD', '$1,234.50 매도', '$1,235 매도', '$1,235 매도'],
    ['USD', '평균 매수가 $0.94 → 원가 $17,719.00 적용', '평균 매수가 $0.94 → 원가 $17,719 적용', '평균 매수가 $0.94 → 원가 $17,719 적용'],
    ['USD', '-$0.004', '-$0.004', '$0'], ['USD', '$0.999', '$0.999', '$1'], ['USD', '$99.999', '$100', '$100'], ['USD', '−$5', '−$5', '−$5'],
  ];
  const diff = [];
  for (const [cur, t, e1, e2] of SAME) { S.cur = cur; const g1 = F.hs(t, true), g2 = F.hs(t, 2); if (g1 !== e1 || g2 !== e2) diff.push([cur, t, g1, g2]); }
  chk(!diff.length, 'C2: 지수 없는 기존 문자열 ' + SAME.length + '개 × (money true · 2) 출력 불변', diff);
  // ── C5 ──
  const KR = 1385, labels = (lo, hi) => F.ticksOf(lo, hi).map(v => F.m(v, { compact: true }).replace(/^₩|^\$/, S.cur === 'USD' ? '$' : ''));
  const uniq = a => new Set(a).size === a.length;
  const QUIET = [['KRW', 305250000 / KR, 305310000 / KR, '원화 3.05억 ±6만(검수 재현)'], ['KRW', 1200000000 / KR, 1201000000 / KR, '원화 12억 고저 100만(1주 · 스테이블 비중 큼)'],
    ['KRW', 30500000 / KR, 30500100 / KR, '원화 3,050만 ±50원'], ['USD', 2000000, 2000500, '달러 $2M ±$500'], ['USD', 25000, 25020, '달러 $25K ±$10']];
  for (const [cur, lo, hi, what] of QUIET) {
    S.cur = cur; const L = labels(lo, hi), tk = F.ticksOf(lo, hi);
    chk(L.length >= 2 && uniq(L) && tk[0] >= hi - 1e-9 && tk[tk.length - 1] <= lo + 1e-9, 'C5 조용한 곡선 — ' + what + ': 눈금 글자 서로 다름 · 맨 위/아래 눈금이 최고/최저를 감쌈', L);
  }
  // 평소 곡선 = 눈금 종전 그대로(종전 식으로 같은 입력 계산해 비교)
  const oldTicks = (lo, hi) => { const kr = S.cur === 'USD' ? 1 : KR; const ns = raw => { const e = Math.pow(10, Math.floor(Math.log10(raw))); for (const f of [1, 2, 2.5, 5, 10]) if (f * e >= raw) return f * e; return 10 * e; };
    const step = ns((hi - lo) * kr / 3), t0 = Math.floor(lo * kr / step + 1e-9) * step, t1 = Math.ceil(hi * kr / step - 1e-9) * step; const t = []; for (let v = t1; v >= t0 - step * 1e-6 && t.length < 8; v -= step) t.push(v / kr); return t; };
  const NORMAL = [['KRW', 1.4e9 / KR, 1.65e9 / KR], ['KRW', 2.9e8 / KR, 3.1e8 / KR], ['KRW', 5e6 / KR, 9e6 / KR], ['KRW', 3.0e8 / KR, 3.06e8 / KR], ['USD', 950000, 1200000], ['USD', 12000, 15500], ['USD', 120, 480], ['USD', 3.2, 7.9]];
  const nd = [];
  for (const [cur, lo, hi] of NORMAL) { S.cur = cur; const a = F.ticksOf(lo, hi).map(v => v.toFixed(6)).join(), b = oldTicks(lo, hi).map(v => v.toFixed(6)).join(); if (a !== b) nd.push([cur, lo, hi, a, b]); }
  chk(!nd.length, 'C5: 범위가 눈금 정밀도보다 넓은 평소 곡선 ' + NORMAL.length + '개 = 눈금 종전 그대로(Math.max 가 종전 간격)', nd);
  S.cur = 'KRW';
} catch (e) { chk(false, '실행 오류', String(e && e.stack || e)); }
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : ' — ' + JSON.stringify(d).slice(0, 600)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = shutil.which("node")
if not NODE:
    print("SKIP node 없음 — 함수 동작 시험 건너뜀")
else:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
