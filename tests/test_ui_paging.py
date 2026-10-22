#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

V2 = os.path.join(T.ROOT, "web", "v2")
APP = T.app_js_path()
rd = lambda n: open(os.path.join(V2, n), encoding="utf-8").read()  # noqa: E731
app, setup, wow, css = T.app_js(), rd("setup.js"), rd("wow.js"), T.v2_css()
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
    if k == "vnco:" and "vk9 = 'vnco:' + " in app and "uiPgSlice(vk9, all)" in app and "uiPgBar(vk9, all.length, {" in app:
        continue
    if k == "cyev:" and "cyK = 'cyev:' + p.key, cyP = uiPgSlice(cyK, " in app and "uiPgBar(cyK, evsAll.length, {" in app:
        continue
    if k == "dayr:" and "uiPgSlice(rk, items)" in app and "uiPgBar(rk, items.length, {" in app:
        continue
    miss.append(k + " " + v)
T.chk(not miss, "길어지던 목록 %d곳 = 쪽 넘김(uiPaged·uiPgSlice·uiPgBar)" % len(PAGED), miss)
T.chk("uiPaged(bk, bs, b => " in app, "일별 › 그날의 기록(폰 묶음) = 쪽 넘김")
old = [k for k in PAGED if re.search(r"uiMore\('" + re.escape(k), app)]
T.chk(not old, "그 목록들에 종전 uiMore(아래로 계속 붙음·한 번에 전부) 호출 없음", old)
T.chk(not re.search(r"S\.uiMore(?:\.\w+|\[[^\]]+\])\s*=\s*Infinity", app), "검색 찾아가기가 목록을 전부 펼치지 않음(S.uiMore[…] = Infinity 없음 → uiPgReveal)",
      re.findall(r"S\.uiMore(?:\.\w+|\[[^\]]+\])\s*=\s*Infinity", app)[:5])
for k in ("'ofp'", "'ofh'", "'ug:hid'", "'ug:' + p._cat", "'jcy'", "'evdays'", "'hold'", "'sxw'", "'lev:dr:' + L.tab"):
    T.chk("uiPgReveal(" + k in app, "검색 찾아가기 = 그 항목이 있는 쪽 열기 " + k)
OLD_ACTS = ("holdMore", "holdLess", "venueAll", "venueCoinAll", "jMore", "evMore", "evLess", "nftMore", "sxWalAll", "bestMore", "uiMore", "uiLess")
left = [a for a in OLD_ACTS if re.search(r"\n    " + a + r": (?:el|\(\)) =>", app)]
T.chk("const U_FIRST" not in app and "U_FIRST, U_STEP" not in app and not left, "미매칭 앞 8줄(U_FIRST)·옛 '모두 보기'·'더 보기' 열기/접기 동작(holdMore·jMore·sxWalAll·uiMore …) 없음", left)
T.chk("const jSig = [S.j.q, S.j.status, S.j.sort, S.g.period, S.g.from, S.g.to, S.src.mode, S.src.key]" in app,
      "사이클 목록 쪽 초기화 서명에 직접 지정 기간(S.g.from/to) — custom 기간을 바꾸면 첫 쪽으로")
T.chk("uiPgReveal('hold', holdPgHit(k))" in app and "!r.sub && r.g.key === k" not in app,
      "⌘K 보유 찾아가기 = Rabby 보강 하위 행(sub)도 대상(종전 !r.sub 가 대상 자체를 뺌)")
T.chk("function srchPgNext(" in search_js and "function srchPgClamp(" in search_js and "srchPgApply(ST.pgK, gr)" in search_js and "ST.pg " not in search_js
      and 'data-srch="pg" data-kind="' in search_js and "srchPgMove(ST.pgK || (ST.pgK = {}), ST.groups, kind9, d9)" in search_js,
      "검색 쪽 넘김 = 덜 찬 쪽에서 '다음'은 그 쪽을 마저 받음(건너뛰기 없음) · 쪽 번호는 받은 결과 수로 고침 · 묶음(kind)별 쪽·추가 받기 · 누른 묶음만")
T.chk("uiPgReset('ug:')" in app and "uiPgReset('ofh')" in app and "uiPgReset('jcy')" in app and "uiPgReset('evdays')" in app and "uiPgReset('hold')" in app,
      "거르기·검색·정렬이 바뀌면 그 목록 첫 쪽으로(미매칭 검색 · 보낸 내역 거르기 · 사이클 · 전체 이벤트 · 보유 정렬·구분)")
T.chk("const PS = suPgSize(20), shown = suPgSlice(rest, U.chPg, PS), offShown = suPgSlice(off, U.chOffPg, PS);" in setup
      and "suPgBar('chPg', U.chPg, rest.length, PS, '개')" in setup and "suPgBar('chOffPg', U.chOffPg, off.length, PS, '개')" in setup
      and "suPgBar('tPg', U.tierPg, rows.length, suPgSize(20), '곳')" in setup and "suPgSlice(rows, U.tierPg, suPgSize(20))" in setup,
      "설정 › 체인별 조회(다른 체인·꺼 둔 체인 = 바로 설정 쪽 크기씩) · 주소별 확인 주기 시트(설정 쪽 크기)")
T.chk('data-su="chAll"' not in setup and "chAll()" not in setup and 'data-v="-1"' not in setup and "모두 보기</button>" not in setup and "더 보기 · 모두 조회 중" not in setup
      and "U.chPg = 0; U.chOffPg = 0;" in setup,
      "체인 목록 '다른 체인 N개 더 보기'·'꺼 둔 체인 N개 모두 보기'·'접기'(-1) 없음 · 초기화 = 첫 쪽(종전 -1 = 접힘)")
T.chk(".su-chmore{padding:8px 0 2px;display:flex;justify-content:center}" in css, "체인 더 보기·쪽 바 = 가운데")
T.chk('data-w="psPg"' in wow and ".slice(0, 60)" not in wow and "PS = wPgSize()" in wow and "if (st.ps.sz !== v) { st.ps.sz = v; st.ps.p = 0; }" in wow,
      "계획 점수 목록(종전 최근 60건 한 번에) = 설정 쪽 크기씩 쪽 · 크기가 바뀌면 첫 쪽")
print("[1a] 정적 — pg19 '모두 보기' 없애고 바로 다음(오너 10-12)")


def calls(src, name):
    out = []
    for m in re.finditer(r"(?<![\w.])" + name + r"\(", src):
        ls = src.rfind("\n", 0, m.start()) + 1
        pre = src[ls:m.start()]
        if pre.lstrip().startswith(("//", "*", "/*")) or re.search(r"(^|\s)//\s", pre) or re.search(r"function\s+$", pre):
            continue
        j, d, q, cur, args = m.end(), 1, None, "", []
        while j < len(src) and d > 0:
            ch = src[j]
            if q:
                if ch == "\\":
                    cur += src[j:j + 2]; j += 2; continue
                if ch == q:
                    q = None
            elif ch in "'\"`":
                q = ch
            elif ch in "([{":
                d += 1
            elif ch in ")]}":
                d -= 1
                if d == 0:
                    break
            if ch == "," and d == 1 and not q:
                args.append(cur.strip()); cur = ""
            else:
                cur += ch
            j += 1
        args.append(cur.strip())
        out.append((src.count("\n", 0, m.start()) + 1, args))
    return out


bad = [("uiPgSlice", ln, a[:4]) for ln, a in calls(app, "uiPgSlice") if len(a) != 2]
bad += [("uiPgBar", ln, a[:4]) for ln, a in calls(app, "uiPgBar") if not 2 <= len(a) <= 3]
bad += [("uiPaged", ln, [x[:30] for x in a[:5]]) for ln, a in calls(app, "uiPaged") if not 3 <= len(a) <= 4 or re.match(r"^\d", a[2])]
T.chk(not bad, "쪽 넘김 도우미 호출 = 앞 n개·목록별 크기 숫자 인자 없음(uiPgSlice(key, items) · uiPgBar(key, total, o) · uiPaged(key, items, row, o))", bad[:6])
opts = [(ln, a[3]) for ln, a in calls(app, "uiPaged") if len(a) == 4]
lab = [ln for ln, o in opts if re.search(r"\blabel\s*:", o)]
T.chk(not lab and not [ln for ln, a in calls(app, "uiPgBar") if len(a) == 3 and re.search(r"\blabel\s*:", a[2])],
      "닫힌 단추 글자(label — 'N개 모두 보기'·'그 밖 N종'·'이날 N건 모두 보기' …) 넘기는 호출 없음", lab)
more_keys = sorted(set(re.findall(r"uiPaged\('([^']+)'", "\n".join(app.split("\n")[ln - 1] for ln, o in opts if re.search(r"\bmore\s*:", o)))))
T.chk(more_keys == ["lev:dash", "lp:dash"], "카드 'N개 더'(o.more — 누르기 전 단추) = 대시보드 LP·레버리지 두 곳만(오너 '2개만 보여주고 더보기' · 오너 확인 필요로 남김)", more_keys)
T.chk(app.count('data-a="uiPgOpen"') == 1 and app.count('data-a="uiPgClose"') == 1 and "const fold = o.fold ?" in app and "fold: !!o.more" in app,
      "uiPgOpen 단추 = uiPaged o.more 한 곳 · 접기(uiPgClose) = o.fold(카드 펼침)일 때만 — 긴 목록 쪽 바엔 접기 없음")
OLD_FRAG = ("u + ' 모두 보기'", "종 모두 보기' + IC.right", "곳 모두 보기</button>", 'data-a="holdMore"', 'data-a="uiPgOpen" data-v="venue"', "'개 모두 보기')",
            "건 모두 보기 <span", "묶음 모두 보기 <span", "칸</span> 모두 보기", "개 모두 보기</span> — ", "건 모두 보기' })", "'<span class=\"pvx\">그 밖 '")
T.chk(not [x for x in OLD_FRAG if x in app], "손 만든 '모두 보기'(보유 '나머지 N종 · 합계 | N종 모두 보기' · 보관처 'N곳 모두 보기' · 그 밖 N종 …) 코드 없음",
      [x for x in OLD_FRAG if x in app])
allv = sorted(re.findall(r'data-a="(\w+)"[^>]*>모두 보기</button>', app))
T.chk(allv == ["go", "toggleDust"], "남은 '모두 보기' 단추 = 다른 화면 링크(정리할 것 → 미매칭)·소액 숨김 토글만(쪽 넘김 아님 · 범위 밖)", allv)
T.chk("S.uiMore" not in app and "function uiMore(" not in app and "uiLim" not in app, "옛 앞 n개 + 더 보기 도우미(uiMore·uiLim·S.uiMore) 없음")
T.chk("if (i >= 0) uiPgReveal('lev:dr:' + L.tab" in app, "레버리지 서랍 찾아가기 = 첫 쪽 안이어도 그 쪽(종전 i >= 4 = 앞 4개 밖만)")
print("[1b] 정적 — ui18 쪽 크기 설정(10|20 · 기본 10)")
T.chk("const uiPageSize = () => { if (S.pgSz !== 10 && S.pgSz !== 20) { let v = null; try { v = LS.get('tj_v2_pgsize'); } catch (e) { v = null; } S.pgSz = v === '20' ? 20 : 10; } return S.pgSz; };" in app,
      "공통 getter = 이 기기 저장값(tj_v2_pgsize) '20' 만 20 · 그 밖 10 · 저장소 막힘 = 10(try)")
T.chk(app.count("const size = uiPageSize(), P = uiPgS()") == 2 and "function uiPgSlice(key, items) {" in app and "function uiPgBar(key, total, o) {" in app
      and "function uiPaged(key, items, row, o) {" in app and "uiPgN" not in app,
      "uiPgSlice·uiPgBar = 설정 쪽 크기 그대로(앞 n개·목록별 크기 인자 없음 · uiPaged 는 uiPgSlice 를 씀 — slice·bar·찾아가기 같은 값)")
for frag, what in (("const pgH = uiPgSlice('hold', rows), shown = ", "보유 코인(앞 12·15줄 + 나머지 N종 · 합계 | 모두 보기 없음 · rev1012 줄 단위)"),
                   ("(pz.last > 0 ?", "값 없는 토큰 앵커"), ("(pg9.last > 0 ?", "숨긴 이벤트 앵커"),
                   ("(pgT.last > 0 ?", "NFT 추적 중 앵커"), ("(pgJ.last > 0 ?", "사이클 목록 앵커"),
                   ("(pgV.last > 0 ?", "보관처별 앵커(외 N곳 · 합 | 모두 보기 없음)"), ("(pgC.last > 0 ?", "보관처 서랍 › 들어 있는 코인 앵커"),
                   ("(cyP.last > 0 ?", "사이클 최근 기록 앵커"), ("(pgD.last > 0 ?", "그날의 기록 앵커"), ("pgW.last > 0 ?", "설정 › 추적 지갑 쪽 바"),
                   ("const PG9 = uiPgSz(ATTD_PG), pages = Math.max(1, Math.ceil(N / PG9))", "자산 변동 분해 시트(공통 도우미 밖 쪽 넘김)")):
    T.chk(frag in app, "도우미 밖 직접 계산도 같은 값 — " + what)
T.chk(not re.search(r"\.length > 20 \? '<div class=\"upga\"", app), "쪽 넘김 앵커에 하드코딩 '> 20' 남지 않음", re.findall(r".{40}\.length > 20 \? '<div class=\"upga\"", app)[:3])
T.chk("sxSeg('pgSize', [['10', '10개', uiPageSize() === 10], ['20', '20개', uiPageSize() === 20]], '목록 한 쪽 개수')" in app and "id=\"sx-display-pgsize\"" not in app
      and "sxIt('sx-display-pgsize', '목록 한 쪽'," in app and "'#sx-display-pgsize'" in app, "설정 › 화면 '목록 한 쪽' = 칩(seg · aria-pressed · select 아님) · 설정 검색 색인")
i9 = app.find("    pgSize: el => {")
pa = app[i9:app.find("\n", i9)] if i9 >= 0 else ""
T.chk("LS.set('tj_v2_pgsize', String(v))" in pa and "S.pgSz = v;" in pa and "uiPgReset('')" in pa and "S.attdUI.pg = 0" in pa and "render()" in pa,
      "고르기 = 저장(막혀도 이 탭 동안 메모리) · 열린 목록 전부 첫 쪽 · 분해 시트 첫 쪽 · 다시 그림", pa[:200])
T.chk("tj_v2_nologo: 1, tj_v2_pgsize: 1 }" in app and "tj_v2_rand: 1, tj_v2_pgsize: 1 };" in app,
      "화면 초기화(KEEP_LS)·로그아웃 정리(wipeLocal KEEP) = 기기 취향 남김")
T.chk("pgSize: uiPageSize," in app and "window.TJ.pgSize" in search_js and "window.TJ.pgSize" in wow and "window.TJ.pgSize" in setup,
      "검색·계획 점수·확인 주기 시트 = 앱 공통 값(window.TJ.pgSize · 없으면 10)")
T.chk("<select" not in app[app.find("function sxDisplayBody()"):app.find("// ── 원가 계산 ──")], "설정 › 화면에 브라우저 기본 select 없음")
search = rd("search.js")
T.chk("let SRCH_PG = srchPgSize();" in search and "SRCH_PG = srchPgSize();" in search and "effQ() + '|' + scope + '|' + SRCH_PG" in search and 'data-srch="pg"' in search and "gr.items.slice(p * SRCH_PG, p * SRCH_PG + SRCH_PG)" in search and 'data-srch="srvmore"' not in search,
      "⌘K 검색 한 종류 결과 = 설정 쪽 크기(10|20)씩 쪽(다음 쪽이 안 받은 자리면 서버 다음 쪽 · 종전 '더 보기'로 아래에 계속 붙음) · 크기가 바뀌면 첫 쪽(서명)")
T.chk("'<span class=\"upgt num pvx\" aria-live=\"polite\">'" in app and "aria-label=\"쪽 넘기기\"" in app and "aria-label=\"목록 접기\"" in app,
      "쪽 바 = 그룹 이름 · 건수 칸 알림(aria-live) · 접기 이름(폰 = 아이콘만)")
T.chk(".upg{display:inline-flex" in css and ".upg .upgb[disabled]{opacity:.38" in css
      and "@media (max-width:640px){ .upg{gap:6px;flex-wrap:nowrap} .upg .ubtn{min-height:44px}" in css and ".upga{height:0;scroll-margin-top" in css,
      "CSS = 쪽 바 · 끝 쪽 단추 흐림 · 폰 한 줄 44px · 쪽 넘기면 목록 맨 위(앵커)")

print("[2] 화면 함수(node)")
JS = r'''// 쪽 넘김 도우미 — 실제 app.js 블록(uiWrapBtn ~ uiHidChip 앞 + sFold)을 가짜 의존성으로 돌린다
import fs from 'node:fs';
const APP = fs.readFileSync(process.env.TJ_TEST_APP, 'utf8');
const cut = (a, b) => { const i = APP.indexOf(a), j = i < 0 ? -1 : APP.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('블록을 못 찾음: ' + a.slice(0, 50)); return APP.slice(i, j); };
const B = [cut('  const uiWrapBtn = (b, o) =>', '  const uiHidChip = '), cut('  function sFold(rows, key) {', '\n  }\n') + '\n  }'].join('\n');
const R = [];
const chk = (ok, msg, d) => R.push([!!ok, msg, ok ? undefined : d]);
const S = { uiPg: {} };
let nView = 0, nOv = 0;
const deps = {
  S, esc: t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]),
  nf: () => ({ format: v => Number(v).toLocaleString('en-US') }), IC: { chev: '<svg class="c"></svg>' }, UI_CHEV: '<span class="uchev"></span>',
  uiHas: (o, k) => Object.prototype.hasOwnProperty.call(o, k), renderView: () => { nView++; }, renderOverlay: () => { nOv++; }, uiReduce: () => true,
  document: { querySelectorAll: () => [], documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => '' }), setTimeout: f => 0, window: { innerHeight: 800 },
  LS: { get: k => { if (LSV.throw) throw new Error('blocked'); return Object.prototype.hasOwnProperty.call(LSV, k) ? LSV[k] : null; } },
};
const LSV = {};
const names = Object.keys(deps);
const F = new Function(...names, B + '\nreturn { uiPaged, uiPgSlice, uiPgBar, uiPgReveal, uiPgReset, uiPgGo, uiPgS, sFold, uiPageSize, uiPgSz };')(...names.map(k => deps[k]));
const L = Array.from({ length: 45 }, (_, i) => 'r' + i);
const row = (x, i) => '<i data-i="' + i + '">' + x + '</i>';
const idx = h => [...h.matchAll(/data-i="(\d+)"/g)].map(x => +x[1]);
const txt = h => h.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const reset = () => { S.uiPg = {}; S.uiPgFind = {}; nView = 0; nOv = 0; S.pgSz = 20; };   // 아래 검사 = 쪽 크기 20(설정 '20개') · 10 은 [3]

// ── pg19(오너 10-12 '모두 보기 싹 다 없애고 바로 다음'): 처음부터 쪽 크기만큼 + 바로 쪽 바 ──
reset();
let h = F.uiPaged('k', L, row, { unit: '건' });
chk(idx(h).length === 20 && idx(h)[0] === 0 && idx(h)[19] === 19 && /class="upga" data-pga="k"/.test(h), '처음(키 없음 — 옛 접힘 상태도) = 바로 1~20번째 + 앵커', idx(h));
chk(!/uiPgOpen|uiPgClose|모두 보기|접기/.test(h), "'모두 보기'·'접기' 단추 없음", txt(h));
chk(/data-a="uiPg" data-v="k" data-p="-1" disabled aria-label="이전 쪽">‹ 이전/.test(h) && /data-a="uiPg" data-v="k" data-p="1" aria-label="다음 쪽">다음 ›/.test(h), '첫 쪽 = 이전 막힘 · 다음 = 2쪽(바로)');
chk(/1–20 <span class="mut">\/ 45<span class="upgu">건<\/span>/.test(h) && !('k' in S.uiPg), "바 = '1–20 / 45건' · 그리기만으로 상태를 쓰지 않음", { t: txt(h), pg: S.uiPg });
S.uiPg.k = 1; h = F.uiPaged('k', L, row, { unit: '건' });
chk(idx(h)[0] === 20 && idx(h).length === 20 && /21–40/.test(h) && !/data-p="0" disabled/.test(h), "둘째 쪽 = 21~40번째 · '21–40 / 45'", txt(h));
S.uiPg.k = 2; h = F.uiPaged('k', L, row, { unit: '건' });
chk(idx(h).join() === '40,41,42,43,44' && /41–45/.test(h) && /data-p="3" disabled aria-label="다음 쪽"/.test(h), '마지막 쪽 = 41~45 · 다음 막힘', txt(h));
S.uiPg.k = 99; h = F.uiPaged('k', L, row, { unit: '건' });
chk(idx(h)[0] === 40 && S.uiPg.k === 2, '범위 밖 쪽(목록이 줄어듦) = 마지막 쪽으로', { first: idx(h)[0], p: S.uiPg.k });
reset(); h = F.uiPaged('k', L.slice(0, 20), row, {});
chk(idx(h).length === 20 && !/upga|umore|upg/.test(h), '딱 한 쪽(20개) = 전부 · 바·앵커 없음', txt(h));
h = F.uiPaged('k', L.slice(0, 5), row, {});
chk(idx(h).length === 5 && !/upga|umore/.test(h), '한 쪽 이하(5개) = 바·앵커 없음', h);
chk(F.uiPaged('k', [], row, {}) === '', '빈 목록 = 빈 글자');
h = F.uiPaged('k', L.slice(0, 21), row, {});
chk(idx(h).length === 20 && /1–20 <span class="mut">\/ 21/.test(h), '21개 = 20개 + 바로 1–20 / 21(종전 앞 n개 + 모두 보기)', txt(h));
// 찾아가기(검색 ⌘K)
reset(); F.uiPgReveal('k', x => x === 'r33'); h = F.uiPaged('k', L, row, {});
chk(S.uiPg.k === 1 && idx(h).indexOf(33) >= 0, '찾아가기: 34번째 = 둘째 쪽', { p: S.uiPg.k });
reset(); F.uiPgReveal('k', x => x === 'r3'); h = F.uiPaged('k', L, row, {});
chk(S.uiPg.k === 0 && idx(h).indexOf(3) >= 0, '찾아가기: 첫 쪽 안 = 첫 쪽', S.uiPg);
reset(); S.uiPg.k = 2; F.uiPgReveal('k', x => x === 'r3'); h = F.uiPaged('k', L, row, {});
chk(S.uiPg.k === 0 && idx(h).indexOf(3) >= 0, '찾아가기: 다른 쪽을 보던 중이면 그 항목 쪽으로', S.uiPg);
reset(); F.uiPgReveal('k', x => x === 'zz'); h = F.uiPaged('k', L, row, {});
chk(!('k' in S.uiPg) && !S.uiPgFind.k && idx(h)[0] === 0, '찾아가기: 없는 항목 = 그대로(첫 쪽) · 찾기 한 번만 씀', S.uiPg);
// 필터·검색이 바뀜 = 첫 쪽(넘긴 목록만 · 다른 키 그대로)
reset(); S.uiPg = { 'ug:a': 3, 'ug:b': 0, ofh: 2 }; F.uiPgReset('ug:');
chk(S.uiPg['ug:a'] === 0 && S.uiPg['ug:b'] === 0 && S.uiPg.ofh === 2 && !('ug:c' in S.uiPg), "uiPgReset('ug:') = 미매칭 목록만 첫 쪽", S.uiPg);
// 표 모양
reset(); S.uiPg.t = 1; h = F.uiPaged('t', L, (x, i) => '<tr><td>' + i + '</td></tr>', { tr: 6, unit: '일' });
chk(/^<tr class="upga" data-pga="t"><td colspan="6"><\/td><\/tr>/.test(h) && /<tr class="umtr"><td colspan="6"><div class="umore"><div class="upg"/.test(h) && /21–40/.test(h), '표(tr) = 앵커·바도 표 줄(칸 6)', h.slice(0, 120));
// 바만
reset(); h = F.uiPgBar('x', 30, { unit: '묶음' });
chk(/1–20 <span class="mut">\/ 30<span class="upgu">묶음/.test(h) && !/upgx|uiPgOpen/.test(h), "바 단독 = '1–20 / 30묶음' · 접기 없음", txt(h));
chk(F.uiPgBar('x', 20, {}) === '' && F.uiPgBar('x', 0, {}) === '', '한 쪽 이하 = 바 없음');
// 대시보드 카드 'N개 더'(o.more — LP·레버리지 · 오너 10-09 '2개만 + 더보기' 그대로)
reset(); h = F.uiPaged('m', L.slice(0, 5), row, { cls: 'lvmore', more: n => n + '개 더' });
chk(idx(h).length === 0 && /<div class="upga" data-pga="m"><\/div><div class="umore lvmore"><button type="button" class="ubtn" data-a="uiPgOpen" data-v="m">5개 더<span class="uchev"><\/span><\/button><\/div>$/.test(h), "카드 펼침 전 = 앵커 + 'N개 더' 단추만", h);
S.uiPg.m = 0; h = F.uiPaged('m', L.slice(0, 5), row, { cls: 'lvmore', more: n => n + '개 더' });
chk(idx(h).length === 5 && /data-a="uiPgClose" data-v="m" aria-label="목록 접기"><span class="upgxt">접기/.test(h) && !/data-a="uiPg"/.test(h), '카드 펼침(한 쪽) = 5줄 + 접기만', txt(h));
S.uiPg.m = 1; h = F.uiPaged('m', L, row, { more: n => n + '개 더' });
chk(idx(h)[0] === 20 && /21–40/.test(h) && /<div class="upg"[^>]*>[\s\S]*다음 ›<\/button><button type="button" class="ubtn upgx" data-a="uiPgClose"/.test(h), '카드 펼침(여러 쪽) = 쪽 바 + 같은 줄 접기', txt(h));
// 단추 누름 → 상태 + 다시 그림(서랍 안 = 서랍만)
reset(); const el = (a, v, p, ov) => ({ dataset: { a, v, p }, getAttribute: k => (k === 'aria-label' ? '다음 쪽' : null), closest: s => (ov && s === '#overlay' ? {} : null) });
F.uiPgGo(el('uiPg', 'k', '2'), 2); chk(S.uiPg.k === 2 && nView === 1, '다음 = 그 쪽 + 화면 다시 그림');
F.uiPgGo(el('uiPgOpen', 'm'), 0); chk(S.uiPg.m === 0 && nView === 2 && nOv === 0, "카드 'N개 더' = 펼침(첫 쪽)");
F.uiPgGo(el('uiPgClose', 'm'), null); chk(!('m' in S.uiPg) && nView === 3, '카드 접기 = 상태 지움');
F.uiPgGo(el('uiPg', 'd', '1', true), 1); chk(S.uiPg.d === 1 && nOv === 1 && nView === 3, '서랍(#overlay) 안 단추 = 서랍만 다시 그림');
// sFold(설정 긴 목록 — 거래소 입금 주소 등) — 한 쪽 이하 = 그대로 · 넘으면 바로 쪽 넘김
reset(); const rows9 = Array.from({ length: 30 }, (_, i) => '<div data-i="' + i + '">a</div>');
chk(F.sFold(rows9.slice(0, 20), 'deps') === rows9.slice(0, 20).join(''), 'sFold: 한 쪽 이하 = 전부 그대로(바 없음)');
h = F.sFold(rows9, 'deps');
chk(idx(h).length === 20 && /1–20 <span class="mut">\/ 30<span class="upgu">개/.test(h) && !/모두 보기|uiPgOpen/.test(h), "sFold: 바로 1–20 / 30개(종전 앞 8 + '30개 모두 보기')", txt(h));
S.uiPg['sx:deps'] = 1; h = F.sFold(rows9, 'deps');
chk(idx(h).join() === '20,21,22,23,24,25,26,27,28,29' && /21–30/.test(h), 'sFold 둘째 쪽 = 21–30', idx(h));
// up708 HIGH: ⌘K 보유 찾아가기 — Rabby 보강 하위 행(sub · '#rb:OKB')도 그 쪽을 연다
{ let hp = null; try { const i9 = APP.indexOf('  const holdPgHit = '); hp = i9 < 0 ? null : new Function('return ' + APP.slice(i9 + '  const holdPgHit = '.length, APP.indexOf('\n', i9)).replace(/;\s*(\/\/.*)?$/, ''))(); } catch (e) { hp = null; }
  chk(typeof hp === 'function', '보유 찾아가기 술어(holdPgHit) 있음');
  if (hp) {
    reset(); const HR = Array.from({ length: 25 }, (_, i) => ({ g: { key: 'C' + i } })); HR.splice(21, 0, { g: { key: '#rb:OKB' }, sub: true });
    F.uiPgReveal('hold', hp('#rb:OKB')); const s9 = F.uiPgSlice('hold', HR);
    chk(S.uiPg.hold === 1 && s9.rows.some(r => r.g.key === '#rb:OKB'), 'Rabby 하위 행(22번째) 찾아가기 = 둘째 쪽 열림', { p: S.uiPg.hold });
    reset(); S.uiPg.hold = 1; F.uiPgReveal('hold', hp('C3')); const s8 = F.uiPgSlice('hold', HR);
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
// ── ui18: 쪽 크기 설정(10|20 · 기본 10) · pg19: 모든 목록 = 이 값 그대로 ──
{ const sz = (v, thr) => { for (const k of Object.keys(LSV)) delete LSV[k]; LSV.throw = !!thr; if (v !== undefined) LSV.tj_v2_pgsize = v; delete S.pgSz; const r = F.uiPageSize(); LSV.throw = false; return r; };
  chk(sz() === 10 && sz('20') === 20 && sz('10') === 10 && sz('15') === 10 && sz('abc') === 10 && sz('') === 10 && sz('20', true) === 10, '저장값 없음·딴 값·저장소 막힘 = 10 · \'20\' 만 20', null);
  S.pgSz = 10; chk(F.uiPgSz(20) === 10 && F.uiPgSz(12) === 10 && F.uiPgSz(5) === 5, '도우미 밖 직접 쪽(분해 시트 uiPgSz) = 설정 값 이하', null);
  const rows = n => Array.from({ length: n }, (_, i) => 'r' + i);
  const seen = {};
  for (const n of [0, 1, 9, 10, 11, 20, 21]) { S.uiPg = {}; S.uiPgFind = {}; S.pgSz = 10; const h0 = F.uiPaged('t', rows(n), row, { unit: '개' });
    seen[n] = [idx(h0).length, /uiPgOpen|모두 보기/.test(h0), (txt(h0).match(/\d+–\d+ \/ \d+/) || [''])[0]].join('|'); }
  chk(seen[0] === '0|false|' && seen[1] === '1|false|' && seen[9] === '9|false|' && seen[10] === '10|false|' && seen[11] === '10|false|1–10 / 11'
      && seen[20] === '10|false|1–10 / 20' && seen[21] === '10|false|1–10 / 21', '10개씩: 0/1/9/10줄 = 바 없음 · 11/20/21줄 = 처음부터 10개 + 바로 1–10 / N(모두 보기 단계 없음)', seen);
  reset(); S.pgSz = 10; S.uiPg.k = 4; let h = F.uiPaged('k', L, row, { unit: '건' });
  chk(idx(h).join() === '40,41,42,43,44' && /41–45/.test(h) && /data-p="5" disabled aria-label="다음 쪽"/.test(h), '10개씩 마지막 쪽 = 41–45 · 다음 막힘', txt(h));
  reset(); S.uiPg = { k: 2, 'ug:a': 1 }; S.pgSz = 10; F.uiPgReset(''); h = F.uiPaged('k', L, row, {});
  chk(S.uiPg.k === 0 && S.uiPg['ug:a'] === 0 && idx(h).join() === '0,1,2,3,4,5,6,7,8,9', "20→10 바꿈 = 넘긴 목록 전부 첫 쪽(uiPgReset('')) · 1–10", S.uiPg);
  reset(); S.pgSz = 10; F.uiPgReveal('k', x => x === 'r33'); h = F.uiPaged('k', L, row, {});
  chk(S.uiPg.k === 3 && idx(h)[0] === 30 && idx(h).indexOf(33) >= 0, '찾아가기(34번째) = 10개씩 넷째 쪽(31–40) · 20 이면 둘째 쪽(위 검사)', { p: S.uiPg.k });
  reset(); S.pgSz = 10; h = F.uiPaged('k', L, row, {});
  chk(idx(h).length === 10 && !/모두 보기/.test(h), 'pg19: 앞 n개(3·5·8·12·15) 미리보기 없음 = 처음부터 설정 쪽 크기(10)', txt(h));
  reset(); S.pgSz = 10; h = F.uiPaged('m', L, row, { more: n => n + '개 더' });
  chk(idx(h).length === 0 && /45개 더/.test(h), "카드 'N개 더'(LP·레버리지) = 10 이어도 펼치기 전 0줄 + 단추(그대로)", txt(h));
  S.uiPg.m = 0; h = F.uiPaged('m', L, row, { more: n => n + '개 더' });
  chk(idx(h).length === 10 && /1–10/.test(h) && /uiPgClose/.test(h), '카드 펼침 = 10개씩 + 접기', txt(h));
  reset(); S.pgSz = 20; S.uiPg.t = 1; h = F.uiPaged('t', L.slice(0, 30), (x, i) => '<tr><td>' + i + '</td></tr>', { tr: 6, unit: '일' });
  chk(/21–30/.test(h) && /<tr class="umtr">/.test(h), 'pg19: 20 이면 종전 10개씩이던 목록(30일 목록 등)도 20개씩(목록별 크기 없음)', txt(h));
  // Rabby 하위 행 — rev1012(오너 10-12 '스테이킹된 것도 10개 안에 포함'): 하위 행도 한 줄 → 경계 하위 행은 다음 쪽 맨 위(한 쪽 = 정확히 10줄).
  //   종전 ui17 기대(본행 쪽에 붙어 첫 쪽 11줄)는 쪽마다 줄 수가 달라 쪽 바 위치가 바뀌어 오너 지시로 바꿈 — 보유표 실제 그림은 test_ui_hold_pg_rows
  reset(); S.pgSz = 10; const HR = Array.from({ length: 25 }, (_, i) => ({ k: 'C' + i })); HR.splice(10, 0, { k: '#rb:C9', sub: true });
  S.uiPg.hold = 0; const q0 = F.uiPgSlice('hold', HR).rows; S.uiPg.hold = 1; const q1 = F.uiPgSlice('hold', HR).rows;
  chk(q0.length === 10 && q0[9].k === 'C9' && q1.length === 10 && q1[0].k === '#rb:C9' && q1[1].k === 'C10', 'Rabby 하위 행(10번째 본행 바로 뒤) = 줄 단위 — 첫 쪽 정확히 10줄 · 하위 행은 둘째 쪽 맨 위', q0.slice(-2).map(r => r.k).concat(q1.slice(0, 2).map(r => r.k)));
  // 바 a–b 와 slice 가 같은 값(바·자르기 어긋남 없음)
  reset(); S.pgSz = 10; S.uiPg.k = 1; const s9 = F.uiPgSlice('k', L), b9 = F.uiPgBar('k', L.length, {});
  chk(s9.from === 10 && s9.rows.length === 10 && s9.last === 4 && /11–20/.test(b9), 'uiPgSlice·uiPgBar 같은 크기(11–20)', { from: s9.from, n: s9.rows.length });
}
// setup.js 쪽 바(체인별 조회·확인 주기 시트) — 접기 없음 · 한 쪽 이하 = 없음 · 쪽 크기 = 앱 설정
{ let SU = null; try { const SJ = fs.readFileSync(process.env.TJ_TEST_SETUP, 'utf8'); const c9 = (a, b) => { const i = SJ.indexOf(a), j = i < 0 ? -1 : SJ.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error('없음 ' + a); return SJ.slice(i, j); };
    SU = new Function('window', 'fmtN', c9('  function suPgBar(', '\n  }\n') + '\n  }\n' + c9('  const suPgSize = ', '\n') + '\n' + c9('  const suPgSlice = ', '\n') + '\nreturn { suPgBar, suPgSize, suPgSlice };')({ TJ: { pgSize: () => 10 } }, v => String(v)); } catch (e) { SU = null; }
  chk(!!SU, 'setup.js 쪽 바 도우미(suPgBar·suPgSize·suPgSlice) 있음');
  if (SU) {
    const b1 = SU.suPgBar('chPg', 0, 25, SU.suPgSize(20), '개'), b2 = SU.suPgBar('chPg', 2, 25, 10, '개');
    chk(SU.suPgSize(20) === 10 && /1–10 <span class="mut">\/ 25/.test(b1) && /data-su="chPg" data-v="1" aria-label="다음 쪽"/.test(b1) && !/upgx|접기/.test(b1), "체인 25개 = 바로 '1–10 / 25' · 접기 없음", b1);
    chk(/21–25/.test(b2) && /data-v="3" disabled aria-label="다음 쪽"/.test(b2) && SU.suPgBar('chPg', 0, 10, 10, '개') === '', '마지막 쪽 = 21–25 · 다음 막힘 · 한 쪽 이하 = 바 없음', b2);
    chk(SU.suPgSlice(Array.from({ length: 25 }, (_, i) => i), -1, 10).join() === '0,1,2,3,4,5,6,7,8,9', '옛 접힘 값(-1)·없음 = 첫 쪽', null);
  } }
// 검색 쪽 크기 getter(search.js srchPgSize) — 앱 값(window.TJ.pgSize) · 없거나 오류면 10
{ let g = null; try { const SJ = fs.readFileSync(process.env.TJ_TEST_SEARCH, 'utf8'); const i9 = SJ.indexOf('  const srchPgSize = '); g = i9 < 0 ? null : SJ.slice(i9, SJ.indexOf('\n', i9)); } catch (e) { g = null; }
  chk(!!g, '검색 쪽 크기 getter(srchPgSize) 있음');
  if (g) { const mk = w => new Function('window', g + '\nreturn srchPgSize();')(w);
    chk(mk({}) === 10 && mk({ TJ: { pgSize: () => 20 } }) === 20 && mk({ TJ: { pgSize: () => 10 } }) === 10 && mk({ TJ: { pgSize: () => { throw new Error('x'); } } }) === 10 && mk({ TJ: { pgSize: () => 7 } }) === 10,
      '검색 = 앱 설정 값 · 앱 없음·오류·딴 값 = 10', null); }
  try { const SJ = fs.readFileSync(process.env.TJ_TEST_SEARCH, 'utf8'); const c9 = (a, b) => { const i = SJ.indexOf(a), j = SJ.indexOf(b, i + 1); return SJ.slice(i, j); };
    const P10 = new Function('const SRCH_PG = 10;\n' + c9('  function srchPgNext(', '\n  }\n') + '\n  }\n' + c9('  function srchPgClamp(', '\n') + '\nreturn { srchPgNext, srchPgClamp };')();
    let pg = 0, n = 30; const seen = []; const rr = () => (P10.srchPgClamp(pg, n) * 10 + 1) + '–' + Math.min(n, P10.srchPgClamp(pg, n) * 10 + 10);
    seen.push(rr()); pg = P10.srchPgNext(pg, 1, n, true).pg; seen.push(rr()); const r2 = P10.srchPgNext(pg, 1, n, true); pg = r2.pg; seen.push(rr());
    chk(seen.join(' > ') === '1–10 > 11–20 > 21–30' && r2.load, '검색 10개씩: 받은 30건 = 1–10 > 11–20 > 21–30(끝 쪽에서 서버 다음 쪽 미리 받기 · 받는 수는 그대로)', seen);
  } catch (e) { chk(false, '검색 10개씩 쪽 넘김 실행', String(e)); } }
for (const [ok, msg, d] of R) console.log((ok ? 'PASS ' : 'FAIL ') + msg + (ok ? '' : ' — ' + JSON.stringify(d)));
console.log('RESULT ' + R.filter(x => x[0]).length + '/' + R.length);
'''
NODE = T.node_bin("화면 함수 동작 시험")
if NODE:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TJ_")}
    env["TJ_TEST_APP"] = APP
    env["TJ_TEST_SEARCH"] = SEARCH
    env["TJ_TEST_SETUP"] = os.path.join(V2, "setup.js")
    p = subprocess.run([NODE, "--input-type=module", "-"], input=JS, env=env, cwd=T.TMP, capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = (p.stdout or "").splitlines()
    got = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
    for ln in got:
        T.chk(ln.startswith("PASS "), ln[5:])
    T.chk(p.returncode == 0 and got and any(ln.startswith("RESULT ") for ln in lines), "node 화면 함수 시험이 끝까지 돌았음", (p.stderr or "")[-600:])
T.finish()
