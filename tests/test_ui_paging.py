#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import os
import re
import shutil
import subprocess

V2 = os.path.join(T.ROOT, "web", "v2")
APP = os.path.join(V2, "app.js")
rd = lambda n: open(os.path.join(V2, n), encoding="utf-8").read()
app, setup, wow, css = rd("app.js"), rd("setup.js"), rd("wow.js"), rd("index.html")
search_js = rd("search.js")
SEARCH = os.path.join(V2, "search.js")

print("[1] 정적 — 길어지던 목록마다 쪽 넘김")
PAGED = {
    "nftc": "기타 자산 › NFT 후보", "nftt": "기타 자산 › NFT 추적 중", "nftsp": "NFT 스팸으로 거른 것", "nfth": "NFT 숨긴 컬렉션",
    "taxd:": "양도차익 명세 › 코인 펼침 체결 상세", "jcy": "매매일지 › 사이클 목록", "rc30": "일별 › 30일 목록", "evdays": "매매일지 › 전체 이벤트(날짜)",
    "evr:": "전체 이벤트 › 하루 안", "hold": "대시보드 › 보유 코인", "hev:": "보유 코인 펼침 › 최근 기록", "sxw": "설정 › 추적 지갑",
    "ug:": "미매칭 그룹·숨긴 항목", "ofp": "보낸 내역 › 확인 필요", "ofh": "보낸 내역 › 정리 내역", "oftx:": "보낸 내역 카드 › 전송 목록",
    "cyev:": "사이클 펼침 › 최근 기록", "cyr:": "사이클(가스·스테이킹) › 날짜별", "dayr:": "일별 › 그날의 기록", "lp:dash": "대시보드 LP 더보기",
    "lev:dash": "대시보드 레버리지 더보기", "lev:dr:": "레버리지 서랍 카드", "fut:rr": "선물 서랍 › 최근 정산", "vnco:": "보관처 서랍 › 들어 있는 코인",
    "venue": "대시보드 › 보관처별", "bestm": "최고의 날 시트", "frt:": "선물 영수증 › 청산", "frf:": "선물 영수증 › 펀딩", "sx:": "설정 긴 목록(sFold)",
    "ug:be": "미매칭 › 손익 0으로 처리한 매도", "evhid": "전체 이벤트 › 숨긴 이벤트(종전 200줄)", "krwm:": "원화 입출금 › 한 달", "wdd": "보낸 내역 › 출금 받은 주소(종전 60곳)",
    "watch": "대시보드 › 목표·손절 감시",
}
miss = []
for k, v in PAGED.items():
    pat = re.compile(r"(?:uiPaged|uiPgSlice|uiPgBar)\('" + re.escape(k))
    if pat.search(app):
        continue
    if k == "vnco:" and "vk9 = 'vnco:' + " in app and "uiPgSlice(vk9, all, VN_TOP, 20)" in app:
        continue
    if k == "cyev:" and "cyK = 'cyev:' + p.key, cyP = uiPgSlice(cyK, " in app and "uiPgBar(cyK, evsAll.length, 5, 20" in app:
        continue
    if k == "dayr:" and "uiPgSlice(rk, items, 8, 20)" in app and "uiPgBar(rk, items.length, 8, 20" in app:
        continue
    miss.append(k + " " + v)
T.chk(not miss, "길어지던 목록 %d곳 = 쪽 넘김(uiPaged·uiPgSlice·uiPgBar)" % len(PAGED), miss)
T.chk("uiPaged(bk, bs, 5, 10," in app, "일별 › 그날의 기록(폰 묶음) = 쪽 넘김")
old = [k for k in PAGED if re.search(r"uiMore\('" + re.escape(k), app)]
T.chk(not old, "그 목록들에 종전 uiMore(아래로 계속 붙음·한 번에 전부) 호출 없음", old)
T.chk(not re.search(r"S\.uiMore(?:\.\w+|\[[^\]]+\])\s*=\s*Infinity", app), "검색 찾아가기가 목록을 전부 펼치지 않음(S.uiMore[…] = Infinity 없음 → uiPgReveal)",
      re.findall(r"S\.uiMore(?:\.\w+|\[[^\]]+\])\s*=\s*Infinity", app)[:5])
for k in ("'ofp'", "'ofh'", "'ug:hid'", "'ug:' + p._cat", "'jcy'", "'evdays'", "'hold'", "'sxw'", "'lev:dr:' + L.tab"):
    T.chk("uiPgReveal(" + k in app, "검색 찾아가기 = 그 항목이 있는 쪽 열기 " + k)
T.chk("const U_FIRST = 8, U_STEP = 20;" in app and "holdMore: () => { uiPgS().hold = 0;" in app and "jMore: () => { uiPgS().jcy = 0;" in app,
      "미매칭 20줄씩 · 보유 코인·사이클 옛 단추 = 쪽 넘김 열기(종전 50·40줄씩 더)")
T.chk("const jSig = [S.j.q, S.j.status, S.j.sort, S.g.period, S.g.from, S.g.to, S.src.mode, S.src.key]" in app,
      "up708 MEDIUM: 사이클 목록 쪽 초기화 서명에 직접 지정 기간(S.g.from/to) — custom 기간을 바꾸면 첫 쪽으로")
T.chk("uiPgReveal('hold', holdPgHit(k))" in app and "!r.sub && r.g.key === k" not in app,
      "up708 HIGH: ⌘K 보유 찾아가기 = Rabby 보강 하위 행(sub)도 대상(종전 !r.sub 가 대상 자체를 뺌)")
T.chk("function srchPgNext(" in search_js and "function srchPgClamp(" in search_js and "srchPgApply(ST.pgK, gr)" in search_js and "ST.pg " not in search_js
      and 'data-srch="pg" data-kind="' in search_js and "srchPgMove(ST.pgK || (ST.pgK = {}), ST.groups, kind9, d9)" in search_js,
      "up708·up713 HIGH: 검색 쪽 넘김 = 덜 찬 쪽에서 '다음'은 그 쪽을 마저 받음(건너뛰기 없음) · 쪽 번호는 받은 결과 수로 고침 · 묶음(kind)별 쪽·추가 받기 · 누른 묶음만")
T.chk("uiPgReset('ug:')" in app and "uiPgReset('ofh')" in app and "uiPgReset('jcy')" in app and "uiPgReset('evdays')" in app and "uiPgReset('hold')" in app,
      "거르기·검색·정렬이 바뀌면 그 목록 첫 쪽으로(미매칭 검색 · 보낸 내역 거르기 · 사이클 · 전체 이벤트 · 보유 정렬·구분)")
T.chk("suPgBar('chPg', U.chPg, rest.length, 10" in setup and "suPgBar('chOffPg', U.chOffPg, off.length, 10" in setup and "suPgBar('tPg', U.tierPg, rows.length, 20" in setup
      and "suPgSlice(rows, U.tierPg, 20)" in setup, "설정 › 체인별 조회(다른 체인·꺼 둔 체인 10개씩) · 주소별 확인 주기 시트(20곳씩)")
T.chk(".su-chmore{padding:8px 0 2px;display:flex;justify-content:center}" in setup, "체인 더 보기·쪽 바 = 가운데")
T.chk('data-w="psPg"' in wow and ".slice(0, 60)" not in wow, "계획 점수 목록(종전 최근 60건 한 번에) = 20건씩 쪽")
search = rd("search.js")
T.chk("SRCH_PG = 20" in search and 'data-srch="pg"' in search and "gr.items.slice(p * SRCH_PG, p * SRCH_PG + SRCH_PG)" in search and 'data-srch="srvmore"' not in search,
      "⌘K 검색 한 종류 결과 = 20건씩 쪽(다음 쪽이 안 받은 자리면 서버 다음 쪽 · 종전 '더 보기'로 아래에 계속 붙음)")
T.chk("'<span class=\"upgt num pvx\" aria-live=\"polite\">'" in app and "aria-label=\"쪽 넘기기\"" in app and "aria-label=\"목록 접기\"" in app,
      "쪽 바 = 그룹 이름 · 건수 칸 알림(aria-live) · 접기 이름(폰 = 아이콘만)")
T.chk(".upg{display:inline-flex" in css and ".upg .upgb[disabled]{opacity:.38" in css
      and "@media (max-width:640px){ .upg{gap:6px;flex-wrap:nowrap} .upg .ubtn{min-height:44px}" in css and ".upga{height:0;scroll-margin-top" in css,
      "CSS = 쪽 바 · 끝 쪽 단추 흐림 · 폰 한 줄 44px · 쪽 넘기면 목록 맨 위(앵커)")

print("[2] 화면 함수(node)")
JS = r'''// 쪽 넘김 도우미 — 실제 app.js 블록(uiLim ~ uiHidChip 앞 + sFold)을 가짜 의존성으로 돌린다
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const B = [cut('  const uiLim = (key, n)', '  const uiHidChip = '), cut('  function sFold(rows, n, tail, key) {', '\n  }\n') + '\n  }'].join('\n');
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { uiMore: {}, uiPg: {} };
let nView = 0, nOv = 0;
const deps = {
  S, esc: t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]),
  nf: () => ({ format: v => Number(v).toLocaleString('en-US') }), IC: { chev: '<svg class="c"></svg>' }, UI_CHEV: '<span class="uchev"></span>',
  uiHas: (o, k) => Object.prototype.hasOwnProperty.call(o, k), renderView: () => { nView++; }, renderOverlay: () => { nOv++; }, uiReduce: () => true,
  document: { querySelectorAll: () => [], documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => '' }), setTimeout: f => 0, window: { innerHeight: 800 },
};
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { uiPaged, uiPgSlice, uiPgBar, uiPgReveal, uiPgReset, uiPgGo, uiPgS, sFold };')(...names.map(k => deps[k]));
const L = Array.from({ length: 45 }, (_, i) => 'r' + i);
const row = (x, i) => '<i data-i="' + i + '">' + x + '</i>';
const idx = h => [...h.matchAll(/data-i="(\d+)"/g)].map(x => +x[1]);
const txt = h => h.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const reset = () => { S.uiPg = {}; S.uiPgFind = {}; nView = 0; nOv = 0; };

reset();
let h = F.uiPaged('k', L, 5, 20, row, { unit: '건' });
chk(idx(h).join() === '0,1,2,3,4' && /data-a="uiPgOpen" data-v="k">45건 모두 보기/.test(h) && /class="upga" data-pga="k"/.test(h), "닫힘 = 앞 5개 + '45건 모두 보기' + 앵커", txt(h));
S.uiPg.k = 0; h = F.uiPaged('k', L, 5, 20, row, { unit: '건' });
chk(idx(h).length === 20 && idx(h)[0] === 0 && idx(h)[19] === 19, '열림 첫 쪽 = 1~20번째(20개)', idx(h));
chk(/data-a="uiPg" data-v="k" data-p="-1" disabled aria-label="이전 쪽">‹ 이전/.test(h) && /data-a="uiPg" data-v="k" data-p="1" aria-label="다음 쪽">다음 ›/.test(h), '첫 쪽 = 이전 막힘 · 다음 = 2쪽');
chk(/1–20 <span class="mut">\/ 45<span class="upgu">건<\/span>/.test(h) && /data-a="uiPgClose" data-v="k" aria-label="목록 접기"><span class="upgxt">접기/.test(h), "바 = '1–20 / 45건' + 접기(같은 줄)", txt(h));
S.uiPg.k = 1; h = F.uiPaged('k', L, 5, 20, row, { unit: '건' });
chk(idx(h)[0] === 20 && idx(h).length === 20 && /21–40/.test(h) && !/data-p="0" disabled/.test(h), "둘째 쪽 = 21~40번째 · '21–40 / 45'", txt(h));
S.uiPg.k = 2; h = F.uiPaged('k', L, 5, 20, row, { unit: '건' });
chk(idx(h).join() === '40,41,42,43,44' && /41–45/.test(h) && /data-p="3" disabled aria-label="다음 쪽"/.test(h), '마지막 쪽 = 41~45 · 다음 막힘', txt(h));
S.uiPg.k = 99; h = F.uiPaged('k', L, 5, 20, row, { unit: '건' });
chk(idx(h)[0] === 40 && S.uiPg.k === 2, '범위 밖 쪽(목록이 줄어듦) = 마지막 쪽으로', { first: idx(h)[0], p: S.uiPg.k });
reset(); h = F.uiPaged('k', L.slice(0, 5), 5, 20, row, {});
chk(idx(h).length === 5 && !/upga|umore/.test(h), '앞 n개 이하 = 바·앵커 없음', h);
S.uiPg.k = 0; h = F.uiPaged('k', L.slice(0, 12), 5, 20, row, {});
chk(idx(h).length === 12 && /uiPgClose/.test(h) && !/data-a="uiPg"/.test(h), '열었는데 한 쪽뿐 = 12개 + 접기만', txt(h));
// 찾아가기(검색 ⌘K)
reset(); F.uiPgReveal('k', x => x === 'r33'); h = F.uiPaged('k', L, 5, 20, row, {});
chk(S.uiPg.k === 1 && idx(h).indexOf(33) >= 0, '찾아가기: 접힌 목록의 34번째 = 둘째 쪽을 연다', { p: S.uiPg.k });
reset(); F.uiPgReveal('k', x => x === 'r3'); h = F.uiPaged('k', L, 5, 20, row, {});
chk(!('k' in S.uiPg) && idx(h).indexOf(3) >= 0, '찾아가기: 앞 n개 안 = 접힌 채(이미 보임)', S.uiPg);
reset(); S.uiPg.k = 2; F.uiPgReveal('k', x => x === 'r3'); h = F.uiPaged('k', L, 5, 20, row, {});
chk(S.uiPg.k === 0 && idx(h).indexOf(3) >= 0, '찾아가기: 열린 목록이 다른 쪽이면 그 항목 쪽으로', S.uiPg);
reset(); F.uiPgReveal('k', x => x === 'zz'); h = F.uiPaged('k', L, 5, 20, row, {});
chk(!('k' in S.uiPg) && !S.uiPgFind.k, '찾아가기: 없는 항목 = 그대로 · 찾기 한 번만 씀', S.uiPg);
// 필터·검색이 바뀜 = 첫 쪽(열린 것만 · 다른 키 그대로)
reset(); S.uiPg = { 'ug:a': 3, 'ug:b': 0, ofh: 2 }; F.uiPgReset('ug:');
chk(S.uiPg['ug:a'] === 0 && S.uiPg['ug:b'] === 0 && S.uiPg.ofh === 2 && !('ug:c' in S.uiPg), "uiPgReset('ug:') = 열린 미매칭 목록만 첫 쪽", S.uiPg);
// 표 모양
reset(); S.uiPg.t = 1; h = F.uiPaged('t', L, 10, 10, (x, i) => '<tr><td>' + i + '</td></tr>', { tr: 6, unit: '일' });
chk(/^<tr class="upga" data-pga="t"><td colspan="6"><\/td><\/tr>/.test(h) && /<tr class="umtr"><td colspan="6"><div class="umore"><div class="upg"/.test(h) && /11–20/.test(h), '표(tr) = 앵커·바도 표 줄(칸 6)', h.slice(0, 120));
// 라벨 바꿈(닫힘)
reset(); h = F.uiPgBar('x', 30, 3, 10, { label: t => t + '묶음 모두 보기' });
chk(/>30묶음 모두 보기<span class="uchev">/.test(h), '닫힘 라벨 = o.label(전체 수)', h);
// 단추 누름 → 상태 + 다시 그림(서랍 안 = 서랍만)
reset(); const el = (a, v, p, ov) => ({ dataset: { a, v, p }, getAttribute: k => (k === 'aria-label' ? '다음 쪽' : null), closest: s => (ov && s === '#overlay' ? {} : null) });
F.uiPgGo(el('uiPgOpen', 'k'), 0); chk(S.uiPg.k === 0 && nView === 1 && nOv === 0, '모두 보기 = 첫 쪽 열기 + 화면 다시 그림');
F.uiPgGo(el('uiPg', 'k', '2'), 2); chk(S.uiPg.k === 2 && nView === 2, '다음 = 그 쪽');
F.uiPgGo(el('uiPgClose', 'k'), null); chk(!('k' in S.uiPg) && nView === 3, '접기 = 상태 지움(앞 n개로)');
F.uiPgGo(el('uiPg', 'd', '1', true), 1); chk(S.uiPg.d === 1 && nOv === 1 && nView === 3, '서랍(#overlay) 안 단추 = 서랍만 다시 그림');
// sFold(설정 긴 목록) — 앞 n + 2 이하 = 그대로 · 넘으면 쪽 넘김
reset(); const rows9 = Array.from({ length: 30 }, (_, i) => '<div data-i="' + i + '">a</div>');
chk(F.sFold(rows9.slice(0, 10), 8, '개 더 보기', 'deps') === rows9.slice(0, 10).join(''), 'sFold: n+2 이하 = 전부 그대로');
h = F.sFold(rows9, 8, '개 더 보기', 'deps');
chk(idx(h).length === 8 && /data-v="sx:deps">30개 모두 보기/.test(h), "sFold: 앞 8 + '30개 모두 보기'", txt(h));
S.uiPg['sx:deps'] = 1; h = F.sFold(rows9, 8, '개 더 보기', 'deps');
chk(idx(h).join() === '20,21,22,23,24,25,26,27,28,29' && /21–30/.test(h), 'sFold 열림 = 20줄씩 쪽', idx(h));
// up708 HIGH: ⌘K 보유 찾아가기 — Rabby 보강 하위 행(sub · '#rb:OKB')도 그 쪽을 연다
{ let hp = null; try { const i9 = APP.indexOf('  const holdPgHit = '); hp = i9 < 0 ? null : new Function('return ' + APP.slice(i9 + '  const holdPgHit = '.length, APP.indexOf('\n', i9)).replace(/;\s*(\/\/.*)?$/, ''))(); } catch (e) { hp = null; }
  chk(typeof hp === 'function', '보유 찾아가기 술어(holdPgHit) 있음');
  if (hp) {
    reset(); const HR = Array.from({ length: 25 }, (_, i) => ({ g: { key: 'C' + i } })); HR.splice(21, 0, { g: { key: '#rb:OKB' }, sub: true });
    F.uiPgReveal('hold', hp('#rb:OKB')); const s9 = F.uiPgSlice('hold', HR, 15, 20);
    chk(S.uiPg.hold === 1 && s9.rows.some(r => r.g.key === '#rb:OKB'), 'Rabby 하위 행(22번째) 찾아가기 = 둘째 쪽 열림', { p: S.uiPg.hold });
    reset(); S.uiPg.hold = 1; F.uiPgReveal('hold', hp('C3')); const s8 = F.uiPgSlice('hold', HR, 15, 20);
    chk(S.uiPg.hold === 0 && s8.rows.some(r => r.g.key === 'C3'), '다른 쪽을 보던 중 본행 찾아가기 = 그 쪽', { p: S.uiPg.hold });
  } }
// up708 HIGH: 검색 쪽 넘김(search.js 도우미 — 서버 첫 쪽 30건 · 화면 20건씩 · 더 받으면 50건씩)
{ let SP = null; try { const SJ = fs.readFileSync(process.env.TJ_TEST_SEARCH, 'utf8'); const c9 = (a, b) => { const i = SJ.indexOf(a), j = i < 0 ? -1 : SJ.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('없음 ' + a); return SJ.slice(i, j); };
    SP = new Function('const SRCH_PG = ' + ((SJ.match(/SRCH_PG = (\d+)/) || [0, 20])[1]) + ';\n' + c9('  function srchPgNext(', '\n  }\n') + '\n  }\n' + c9('  function srchPgClamp(', '\n') + '\n'
      + (SJ.indexOf('  function srchPgApply(') >= 0 ? c9('  function srchPgApply(', '\n') + '\n' + c9('  function srchPgMove(', '\n') + '\n' : '')
      + 'return { srchPgNext, srchPgClamp, srchPgApply: typeof srchPgApply === "function" ? srchPgApply : null, srchPgMove: typeof srchPgMove === "function" ? srchPgMove : null };')(); } catch (e) { SP = null; }
  chk(!!SP, '검색 쪽 넘김 도우미(srchPgNext·srchPgClamp) 있음');
  if (SP) {
    const PG = 20, rng = (pg, n) => { const p = SP.srchPgClamp(pg, n); return (p * PG + 1) + '–' + Math.min(n, p * PG + PG); };
    let n = 30, pg = 0, more = true; const seen = [rng(pg, n)];
    let r = SP.srchPgNext(pg, 1, n, more); pg = r.pg; seen.push(rng(pg, n)); const load1 = r.load;
    n = 80; seen.push(rng(pg, n));   // 서버 다음 쪽 도착
    r = SP.srchPgNext(pg, 1, n, more); pg = r.pg; seen.push(rng(pg, n));
    chk(load1 && seen.join(' > ') === '1–20 > 21–30 > 21–40 > 41–60', "다음 = 1–20 → 21–30(받는 중) → 21–40(도착) → 41–60 · 31–40 건너뛰지 않음", seen);
    r = SP.srchPgNext(1, 1, 30, true);
    chk(r.pg === 1 && r.load, '덜 찬 쪽(21–30)에서 다음 = 그 쪽에 머물러 마저 받음', r);
    chk(SP.srchPgClamp(3, 30) === 1 && SP.srchPgNext(SP.srchPgClamp(3, 30), -1, 30, false).pg === 0, "결과가 80→30 으로 줄면 쪽 번호 = 마지막 쪽(1) · '이전' = 첫 쪽", null);
    chk(SP.srchPgNext(0, 1, 20, false).pg === 0 && !SP.srchPgNext(0, 1, 20, false).load, '서버에 더 없고 한 쪽뿐 = 다음 없음', null);
    // up713: 여러 묶음(지갑·주소 범위 = wallet + deposit) — 쪽 번호·추가 받기 = 묶음별 · 누른 묶음만 움직임 · 갱신·추가 응답 뒤 유지
    chk(!!(SP.srchPgApply && SP.srchPgMove), '묶음별 쪽 도우미(srchPgApply·srchPgMove) 있음');
    if (SP.srchPgApply && SP.srchPgMove) {
      const mk = (kind, n, more) => ({ kind, items: Array.from({ length: n }, (_, i) => kind + i), srvMore: more });
      const show = (K, gs) => gs.map(g => { SP.srchPgApply(K, g); return g.kind + ' ' + (g.pg * PG + 1) + '–' + (g.pg * PG + g.shown.length); }).join(' | ');
      let K = {}, gs = [mk('wallet', 30, true), mk('deposit', 5, false)]; show(K, gs);
      const ld = SP.srchPgMove(K, gs, 'wallet', 1), s1 = show(K, gs), s1b = show(K, gs);   // 다시 그림(run 재실행)
      gs = [mk('wallet', 80, true), mk('deposit', 5, false)]; const s2 = show(K, gs);   // 지갑 추가 응답(offset=30)
      chk(ld === 'wallet' && s1 === 'wallet 21–30 | deposit 1–5' && s1b === s1 && s2 === 'wallet 21–40 | deposit 1–5', "지갑 30개·입금 5개: 지갑 '다음' = 21–30 · 짧은 입금 묶음이 덮지 않음 · 추가 응답 뒤 21–40 유지", [ld, s1, s1b, s2]);
      K = {}; gs = [mk('wallet', 5, false), mk('deposit', 30, true)]; show(K, gs);
      const ld2 = SP.srchPgMove(K, gs, 'deposit', 1), t1 = show(K, gs);
      gs = [mk('wallet', 5, false), mk('deposit', 80, true)]; const t2 = show(K, gs);
      const ld3 = SP.srchPgMove(K, gs, 'deposit', 1), t3 = show(K, gs);
      chk(ld2 === 'deposit' && t1 === 'wallet 1–5 | deposit 21–30' && t2 === 'wallet 1–5 | deposit 21–40' && t3 === 'wallet 1–5 | deposit 41–60' && ld3 === null,
        "지갑 5개·입금 30개: 둘째 묶음 '다음' = 입금 21–30 · 입금 자기 추가 받기(offset 30) · 31번째 이후 41–60", [ld2, t1, t2, ld3, t3]);
      const ld4 = SP.srchPgMove(K, gs, 'wallet', 1);
      chk(ld4 === null && K.wallet === 0 && K.deposit === 2, '다른 묶음(지갑 한 쪽뿐) 다음 = 그 묶음만 그대로 · 입금 쪽 안 건드림', K);
      gs = [mk('wallet', 5, false), mk('deposit', 30, false)]; show(K, gs);
      chk(K.deposit === 1, '같은 질의 결과가 80→30 으로 줄면 입금 쪽 = 마지막 쪽(2 → 1)', K);
    }
    r = SP.srchPgNext(0, 1, 40, true);
    chk(r.pg === 1 && r.load && SP.srchPgNext(1, 1, 40, true).pg === 1, '딱 40건 받음 · 서버에 더 = 둘째 쪽으로 가며 미리 받기 · 받기 전 다음 = 그 쪽에 머묾', r);
  } }
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : ' — ' + JSON.stringify(d)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = shutil.which("node")
if not NODE:
    print("SKIP node 없음 — 화면 함수 동작 시험 건너뜀")
else:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    env["TJ_TEST_SEARCH"] = SEARCH
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
