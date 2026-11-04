(function () {
  'use strict';
  const K = window.TJWow && window.TJWow._kit; if (!K) return;
  const { X, st, A, VIEWS, open, paint, num, arr, M, P, cls, ICO, chCol, XB, skelRows, todayISO, isoShift, KST, $, reduce, HV } = K;
  const esc = TJDOM.esc;
  const HV_KIND = { claim: '클레임', push: '받음', native: '네이티브', mixed: '클레임·받음' };
  const HV_FOLD = {
    push: ['받음 — 출처 확인', '남이 보낸 수령(클레임 아님) — 미연동 거래소 출금·OTC·개인 이체일 수 있어요. '
      + '미매칭 탭에서 원가 지정 또는 발신 지갑 등록, 에어드랍이 맞으면 정상으로', 'pd'],
    suspect: ['의심', '유동성 있는 시세·실제 매도·사용자 정상 지정이 하나도 없는 토큰 — 가치 0 · 실제로 받아 가진 것이면 정상으로', 'w'],
    scam: ['격리·확인 필요', '사칭·가짜·확인 필요·스캠 확증·주소 오염 초소액 — 보유표와 같은 규칙으로 숨겼어요(팔아서 돈이 된 건 판 금액에 표식으로)', 'e'],
    native: ['네이티브 수령', '환불·리워드처럼 프로그램이 돌려준 ETH·SOL 같은 코인 그룹 — 에어드랍이 아니라 따로 접어요(처분·합계 밖)', 'n']
  };
  const HV_FOLDS = ['push', 'suspect', 'scam', 'native'];
  const HV_SORT = [['harv', '거둔 돈 순'], ['wait', '기다린 값 순'], ['recent', '최근 받은 순']];
  const HV_TOP = 7;
  const hvBuilt = () => { const x = X(); return x && x.S.D ? x.S.D.builtAt : null; };
  const hvOn = () => { const x = X(); return !!(x && x.S.tab === 'journal' && x.S.j && x.S.j.view === 'harvest'); };
  const hvRedraw = () => {
    const x = X(); if (!x || x.S.tab !== 'journal') return;
    try { (typeof x.renderView === 'function' ? x.renderView : x.render)(); } catch (e) {  }
  };
  function hvRange() {
    const x = X(), g = (x && x.S.g) || {}, t = todayISO(), m = t.slice(0, 7);
    const ok = v => (/^\d{4}-\d{2}-\d{2}$/.test(String(v || '')) ? v : null);
    if (g.period === 'thismonth') return [m + '-01', null];
    if (g.period === 'lastmonth') { const e = isoShift(m + '-01', -1); return [e.slice(0, 7) + '-01', e]; }
    if (g.period === '90d') return [isoShift(t, -90), null];
    if (g.period === 'custom') return [ok(g.from), ok(g.to)];
    return [null, null];
  }
  const hvKey = () => hvRange().join('~');
  const hvFresh = j => { const bt = hvBuilt(); return !!j && (bt == null || j.builtAt === bt); };
  function hvFetch(force) {
    const H = st.hv, k = hvKey();
    if ((!force && hvFresh(H.cache[k])) || H.busy === k) return;
    H.busy = k; H.err = '';
    const seq = ++H.seq, r9 = hvRange();
    const q = [r9[0] ? 'since=' + r9[0] : '', r9[1] ? 'until=' + r9[1] : ''].filter(Boolean).join('&');
    fetch('/api/harvest' + (q ? '?' + q : ''), { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json()).then(j => {
      if (seq !== H.seq) return;
      H.busy = ''; if (j && j.ok) H.cache[k] = j; else H.err = (j && j.error) || '못 받았어요 — 잠시 뒤 다시';
      hvRedraw();
    }).catch(() => { if (seq !== H.seq) return; H.busy = ''; H.err = '못 받았어요 — 잠시 뒤 다시'; hvRedraw(); });
  }
  const hvLazy = () => {
    const k = hvKey() + '|' + hvBuilt(); if (st.hv.lazy === k) return;
    st.hv.lazy = k; setTimeout(() => hvFetch(false), 0);
  };
  function hvCount() { const d = st.hv.cache[hvKey()]; if (!hvFresh(d)) hvLazy(); return d && d.n ? String(num(d.n.ok)) : ''; }
  function hvPoll(bt0, n) {
    if (!hvOn() || n > 15) { st.hv.wait = ''; return; }
    fetch('/api/harvest', { cache: 'no-store', credentials: 'same-origin' }).then(r => r.json()).then(j => {
      if (!hvOn()) return;
      if (j && j.ok && j.builtAt !== bt0) { st.hv.wait = ''; st.hv.cache = {}; hvFetch(true); return; }
      setTimeout(() => hvPoll(bt0, n + 1), 8000);
    }).catch(() => setTimeout(() => hvPoll(bt0, n + 1), 8000));
  }
  const hvQ = v => { const x = X(); return x && typeof x.q === 'function' ? x.q(num(v)) : String(num(v)); };
  const hvBase = r => (num(r.pxQty) > 0 && num(r.recvUsd) > 0 ? num(r.recvUsd) * Math.max(1, num(r.recv) / num(r.pxQty)) : 0);
  const hvVs = r => { const b = hvBase(r); return b > 0 ? (num(r.soldUsd) + num(r.leftUsd)) / b * 100 - 100 : null; };
  const hvApx = r => !!r.est || (num(r.pxQty) > 0 && num(r.pxQty) < num(r.recv) * 0.999);
  const TGx = (c, t) => '<span class="wtg' + (c ? ' ' + c : '') + '">' + t + '</span>';
  function hvBadge(r, hid) {
    return (r.est ? TGx('w', '≈ 추정') : '') + (r.retUnk ? TGx('', '반환 판정 없음') : '')
      + (r.conv ? TGx('', '전환됨(추정)') : '') + (r.brhist ? TGx('', '브릿지 출발 이력') : '')
      + (num(r.leftHid) > 0 ? TGx('w', '일부 격리 보관(가치 0)') : '') + (hid && r.soldUsd > 0 ? TGx('w', '접힘 자산 매도') : '');
  }
  function hvAv(r) {
    const x = X(), lg9 = x && x.S.D && x.S.D.symLogo && x.S.D.symLogo[r.sym], c0 = arr(r.chains)[0] || '';
    const ic = x && typeof x.icon === 'function' ? x.icon(r.sym, 'sm', lg9 ? { ck: lg9.ck, ca: lg9.ca } : {})
      : '<span class="av n">' + esc(String(r.sym).slice(0, 1)) + '</span>';
    const ch = c0 ? '<i style="background:' + (chCol(c0) || 'var(--k6)') + '">' + esc(String(c0).slice(0, 1)) + '</i>' : '';
    return '<span class="whx-av" aria-hidden="true">' + ic + ch + '</span>';
  }
  function hvDetail(r, cls, noAct) {
    const w = arr(r.w).map(x => '<div class="whv-w"><span class="pvl">' + esc(x.loc) + '</span><span><span class="pvx">' + num(x.n)
      + '건</span> · ' + hvQ(x.qty) + '</span></div>').join('');
    const gk = esc(r.gkey || r.key);
    const fix = cls === 'push' || cls === 'suspect' || cls === 'scam';
    const act = noAct ? '' : cls === 'ok' ? '<button type="button" class="wbtn sm" data-w="hvSpam" data-k="' + gk + '">스팸으로 숨김</button>'
      : fix ? '<button type="button" class="wbtn sm" data-w="hvOk" data-k="' + gk + '">정상으로 복원</button>' : '';
    const unit = num(r.pxQty) > 0 ? ' · 최초 인식 단가 ' + M(num(r.recvUsd) / num(r.pxQty)) + '(가격 확인 ' + hvQ(r.pxQty) + '개)' : '';
    const meta = esc(r.first) + ' ~ ' + esc(r.last) + unit + (r.pxSrc ? ' · 출처 ' + esc(r.pxSrc) : '')
      + (r.nopx ? ' · 시세 없는 처분 ' + num(r.nopx) + '건' : '');
    const nt = act || noAct ? '숨김·정상으로는 보유표·총자산·일별 기록에도 같이 적용돼요(스캠 판정 지정)' : '';
    return '<div class="whv-d">' + (r.reason ? '<div class="wnote">' + esc(r.reason) + '</div>' : '')
      + '<div class="wnote">' + meta + '</div>' + w + '<div class="whv-act">' + act + '<span class="wnote">' + nt + '</span></div></div>';
  }
  function hvStatus(d, N) {
    const H = st.hv, wait = H.wait || (!hvFresh(d) ? '새 빌드 받는 중…' : ''), pushL = arr((d.fold || {}).push), pushN = num(N.push);
    const ps = pushL.reduce((a, r) => a + num(r.soldUsd), 0);
    const w = wait ? '<div class="whx-st" role="status"><span class="wdot w"></span><span class="t">' + esc(wait) + '</span></div>' : '';
    if (!pushN) return w;
    return w + '<div class="whx-st" role="status"><span class="wdot pd"></span><span class="t">출처 확인 대기 — 받음 <span class="pvx">' + pushN
      + '종</span>'
      + (ps > 0 ? ' · 판 <b>' + M(ps, { compact: true }) + '</b>은 합계 밖' : '') + ' · 아래 \'합계에서 뺀 것\'에서 확인해 주세요</span>'
      + '<button type="button" class="wbtn sm" data-w="hvGoPush">출처 확인하기 ›</button></div>';
  }
  function hvBands(recv, pre) {
    if (!(recv > 0 && pre > 0)) return '';
    const gain = pre - recv, up = gain >= 0, w1 = up ? recv / pre * 100 : pre / recv * 100;
    const n1 = up ? '받은 날 시세' : '거둔 몫', n2 = up ? '기다려서 더' : '기다려서 덜';
    const band = (cl, nm, v, w, sg) => '<span class="b ' + cl + '" style="width:' + w.toFixed(1) + '%"><span class="nm">' + nm
      + '</span><b>'
      + M(v, { compact: true, sign: sg }) + '</b><span class="pvx">' + w.toFixed(0) + '%</span></span>';
    return '<div class="whx-band" role="img" aria-label="' + n1 + ' ' + w1.toFixed(0) + '% · ' + n2 + ' ' + (100 - w1).toFixed(0) + '%">'
      + band('n', n1, up ? recv : pre, w1) + band(up ? 'up' : 'down', n2, gain, 100 - w1, true) + '</div>'
      + '<div class="whx-bl"><span>' + n1 + '</span><span>' + n2 + '</span></div>';
  }
  function hvHero(T, rows, ref) {
    const sold = num(T.soldUsd), left = num(T.leftUsd), gas = num(T.gasUsd), recv = num(T.recvUsd), pre = sold + left, harv = pre - gas;
    const pct = recv > 0 ? (pre - recv) / recv * 100 : null, r9 = hvRange(), all = !r9[0] && !r9[1];
    const estN = rows.filter(r => r.est).length, noPx = rows.reduce((a, r) => a + Math.max(0, num(r.n) - num(r.pxN)), 0);
    const allN = rows.filter(r => num(r.sold) > 0 && !(num(r.left) > 0)).length,
      partN = rows.filter(r => num(r.sold) > 0 && num(r.left) > 0).length;
    const cell = (l, v, s) => '<div><span class="l">' + l + '</span><span class="v">' + M(v, { compact: true })
      + '</span><span class="s pvx">' + s + '</span></div>';
    const hid = num(T.soldHidN) > 0 ? ' · 접힘 ' + num(T.soldHidN) + '건 ' + M(T.soldHidUsd, { compact: true }) + ' 따로' : '';
    const tg = pct != null ? '<span class="wtg ' + cls(pct) + '"><span>가스 빼기 전 받은 날보다 ' + P(pct, 0, true) + '</span></span>' : '';
    return '<section class="wcard whx-hero" aria-label="에어드랍으로 거둔 돈"><span class="lead pvx">' + (all ? '지금까지' : '이 기간')
      + ' 에어드랍 ' + num(T.recvN) + '건으로</span><div class="hl"><span class="big">' + M(harv, { compact: true }) + '</span>'
      + '<span class="vb">거뒀어요</span>' + tg + '</div>' + hvBands(recv, pre) + '<div class="whx-cells">'
      + cell('받은 날 가치', recv, num(T.recvN) + '건' + (estN ? ' · ≈ 추정 ' + estN + '종' : '') + (noPx ? ' · 시세 없음 ' + noPx + '건' : ''))
      + cell('판 금액 · 수수료 뺀', sold, num(T.soldN) + '건' + (allN || partN ? ' · 다 판 ' + allN + '종 · 일부 ' + partN + '종' : '') + hid)
      + cell('남은 지금 가치', left, rows.filter(r => num(r.left) > 0).length + '종')
      + cell('클레임 가스', gas, num(T.gasN) + '건' + (gas > 0 && harv > 0 ? ' · 가스의 ' + Math.round(harv / gas) + '배 수확' : '')
        + ' · ' + (ref.gasOn === false ? '실현엔 안 넣음(가스 설정 끔)' : '실현엔 이미 반영')) + '</div></section>';
  }
  function hvBook(T, ref) {
    const op = !!st.hv.book;
    const body = (T.est ? '추정 = 실매수와 섞인 코인은 판 몫을 비례로 나눴어요(이동평균). ' : '')
      + (ref.fsOn === false ? '최초 인식 시가가 꺼져 있어 보냈다가 돌아온 코인을 못 가려요(받은 수량 추정). ' : '')
      + (num(ref.stakeN) ? '스테이킹·거래소 지급 ' + num(ref.stakeN) + '건 ' + M(ref.stakeUsd, { compact: true })
        + '은 받은 날 소득으로 따로 잡혀요(세금 명세). ' : '')
      + '받은 날 가치는 장부에선 원가(손익 아님) · 판 것의 오른 몫은 장부 실현, 안 판 것의 오른 몫은 평가손익, '
      + '클레임 가스는 실현의 \'가스(매매 외)\' 줄이에요. 스캠 거르기 = 보유표와 같은 판정(사칭·가짜·고플러스·확인 필요) '
      + '+ 유동성 없는 토큰은 의심으로 · 남이 보낸 큰 수령은 출처 확인으로.';
    return '<section class="wcard whx-book" aria-label="장부와 맞춰 보기"><button type="button" class="whx-bk" data-w="hvBook" aria-expanded="'
      + op + '">'
      + '<h4>장부와 맞춰 보기</h4><span class="t">이 보드는 보기 전용 — 총자산·실현 숫자는 그대로예요 · 이 보드는 받은 날, 장부는 판 날 기준</span>'
      + '<span class="sp"></span><span class="m">' + (op ? '접기' : '펼치기') + '</span>' + ICO.dn + '</button>'
      + (op ? '<div class="wnote whx-bkb">' + body + '</div>' : '') + '</section>';
  }
  function hvSorted(rows) {
    const s = st.hv.sort || 'harv', h = r => num(r.soldUsd) + num(r.leftUsd) - num(r.gas), L = rows.slice();
    const vz = r => { const v = hvVs(r); return v == null ? -1e9 : v; };
    if (s === 'wait') L.sort((a, b) => vz(b) - vz(a));
    else if (s === 'recent') L.sort((a, b) => (String(a.last) < String(b.last) ? 1 : String(a.last) > String(b.last) ? -1 : 0));
    else L.sort((a, b) => h(b) - h(a));
    return L;
  }
  function hvRow(r, mob) {
    const open = !!st.hv.open[r.key], vs = hvVs(r), got = num(r.soldUsd) + num(r.leftUsd), lft = num(r.left) > 0, k = esc(r.key);
    const vsT = vs != null ? '<span class="num ' + cls(vs) + '">' + P(vs, 0, true) + '</span>' : '<span class="mut">—</span>';
    const sub = esc(arr(r.chains).join('·')) + ' · ' + (HV_KIND[r.kind] || esc(r.kind)) + ' <span class="pvx">' + num(r.n) + '건 · '
      + esc(String(r.last || '').slice(5)) + '</span>';
    const qty = '<small class="num">' + hvQ(r.recv) + ' 받음 · ' + hvQ(r.sold) + ' 팜</small>';
    const leftT = lft ? hvQ(r.left) + ' 남음 · ' + M(r.leftUsd, { compact: true }) : num(r.sold) > 0 ? '다 팜' : '안 팜';
    const nm = '<span class="nm"><b>' + esc(r.sym) + '</b>' + hvBadge(r, false) + '</span><small>' + sub + '</small>' + qty;
    const tog = '" data-w="hvTog" data-k="' + k + '" aria-expanded="' + open + '"';
    if (mob) {
      return '<button type="button" class="whx-cr' + tog + ' aria-label="' + esc(r.sym) + ' 자세히">' + hvAv(r) + '<span class="c">' + nm
        + '</span>'
        + '<span class="hrv"><b>' + M(got, { compact: true }) + '</b><small>기다린 값 ' + vsT + '</small><small>' + leftT
        + '</small></span></button>'
        + (open ? hvDetail(r, 'ok') : '');
    }
    const w = vs == null ? 0 : Math.min(100, Math.abs(vs)) / 2;
    const f = vs == null ? '' : '<span class="f ' + (vs >= 0 ? 'up' : 'down') + '" style="left:' + (vs >= 0 ? 50 : 50 - w).toFixed(1)
      + '%;width:'
      + w.toFixed(1) + '%"></span>';
    const rv = r.pxN ? (hvApx(r) ? '≈' : '') + M(r.recvUsd, { compact: true }) : '<span class="mut">시세 없음</span>';
    return '<div class="whx-tr' + (open ? ' open' : '') + '"><button type="button" class="whx-nb' + tog + '>' + hvAv(r) + '<span class="c">'
      + nm
      + '</span></button><span class="r">' + rv + '</span><span class="r"><b>' + M(got, { compact: true }) + '</b><small>' + leftT
      + '</small></span>'
      + '<span class="vs"><span class="whx-trk" aria-hidden="true"><span class="z"></span>' + f + '</span>' + vsT + '</span>'
      + '<span class="r mut">' + (r.gasN ? M(r.gas, { compact: true }) : '—') + '</span>'
      + '<button type="button" class="wbtn sm txt" data-w="hvSpam" data-k="' + esc(r.gkey || r.key) + '">숨김</button></div>'
      + (open ? hvDetail(r, 'ok', true) : '');
  }
  function hvTable(rows, N) {
    const x = X(), mob = !!(x && x.S.mobile), L = hvSorted(rows), sh = st.hv.all ? L : L.slice(0, HV_TOP), s = st.hv.sort || 'harv';
    const seg = '<span class="wseg" role="group" aria-label="정렬">' + HV_SORT.map(o => '<button type="button" class="'
      + (s === o[0] ? 'on' : '')
      + '" aria-pressed="' + (s === o[0]) + '" data-w="hvSort" data-v="' + o[0] + '">' + o[1] + '</button>').join('') + '</span>';
    const lgd = mob ? '' : '<span class="whx-lgd"><span><i class="z"></i>받자마자 팔았을 때</span><span><i class="up"></i>더 벌었다</span>'
      + '<span><i class="down"></i>덜 벌었다</span></span>';
    const th = mob ? '' : '<div class="whx-th"><span>코인 · 체인 · 받은 날 · 수량</span><span class="r">받은 날 시세</span><span class="r">실제 거둔 돈</span>'
      + '<span class="vs">받자마자 팔았으면 대비 (±100%에서 자름)</span><span class="r">클레임 가스</span><span class="r">동작</span></div>';
    const more = L.length > HV_TOP ? '<button type="button" class="whx-more" data-w="hvAll" aria-expanded="' + !!st.hv.all + '">'
      + (st.hv.all ? '접기' : '나머지 <span class="pvx">' + (L.length - HV_TOP) + '종</span> 더 보기') + ICO.dn + '</button>' : '';
    const body = sh.length ? sh.map(r => hvRow(r, mob)).join('') : '<div class="wempty">이 기간에 받은 에어드랍이 없어요</div>';
    return '<section class="wcard whx-list" aria-label="클레임한 코인"><div class="whx-lh"><h4>클레임한 코인 <span class="pvx">' + num(N.ok)
      + '종</span></h4>'
      + '<span class="sp"></span>' + lgd + seg + '</div>' + th + body + more
      + (num(N.ok) > L.length ? '<div class="wnote">상위 <span class="pvx">' + L.length + '종</span>만 보여요</div>' : '')
      + '<p class="wnote">받은 날 시세 = 받은 날 시가(≈ = 가격 확인 못 한 수량이 섞여 추정) · 실제 거둔 돈 = 판 돈(수수료 뺀 순수령) + 안 판 것 지금 가치 · '
      + '받자마자 팔았으면 대비 = 받은 수량 전부를 받은 날 시세로 친 값과 비교 · \'숨김\'·\'정상으로\'는 보유표에도 함께 적용돼요</p></section>';
  }
  function hvFolds(d, N) {
    const fs = HV_FOLDS.map(k => {
      const L = arr((d.fold || {})[k]), n = num(N[k]); if (!n) return '';
      const op = !!st.hv.fold[k], sold = L.reduce((a, r) => a + num(r.soldUsd), 0);
      const rt = k === 'native' ? '<span class="mut">합계 밖</span>' : sold > 0 ? '판 <b>' + M(sold, { compact: true }) + '</b> · 합계 밖' : '가치 '
        + M(0);
      const fb = op ? '<div class="whx-fb">' + L.map(r => hvFoldRow(r, k)).join('')
        + (L.length < n ? '<div class="wnote">상위 ' + L.length + '종만 보여요</div>' : '') + '</div>' : '';
      return '<button type="button" class="whx-fold" data-w="hvFold" data-v="' + k + '" aria-expanded="' + op + '"'
        + (k === 'push' ? ' id="whxPush"' : '')
        + '><span class="bar ' + HV_FOLD[k][2] + '"></span><span class="c"><span class="t">' + HV_FOLD[k][0] + ' <span class="pvx">' + n
        + '종</span></span>'
        + '<span class="s">' + esc(HV_FOLD[k][1]) + '</span></span><span class="rt">' + rt + '</span>' + ICO.dn + '</button>' + fb;
    }).join('');
    if (!fs) return '';
    return '<section class="wcard whx-folds" aria-label="합계에서 뺀 것"><div class="whx-lh"><h4>합계에서 뺀 것</h4>'
      + '<span class="wnote">보유표 판정과 같아요 · 판 금액은 접힌 줄마다 따로</span></div>' + fs + '</section>';
  }
  function hvFoldRow(r, k) {
    const open = !!st.hv.open[r.key];
    const sub = '<span class="pvx">' + num(r.n) + '건</span> · ' + hvQ(r.recv) + '개 · ' + esc(arr(r.chains).join('·')) + ' · '
      + esc(String(r.last || '').slice(5));
    return '<div class="whx-fi"><button type="button" class="whx-nb" data-w="hvTog" data-k="' + esc(r.key) + '" aria-expanded="' + open
      + '">'
      + '<span class="c"><span class="nm"><b>' + esc(r.sym) + '</b>' + hvBadge(r, true) + '</span><small>' + sub
      + '</small></span></button>'
      + '<span class="r">' + (num(r.soldUsd) > 0 ? '판 ' + M(r.soldUsd, { compact: true }) : '') + '</span></div>' + (open ? hvDetail(r,
      k) : '');
  }
  function hvPage() {
    const H = st.hv, k = hvKey(), d = H.cache[k];
    const rk = d ? d.builtAt + '|' + hvBuilt() + '|' + k : '';
    if (d && !hvFresh(d) && H.refetched !== rk) { H.refetched = rk; setTimeout(() => hvFetch(true), 0); }
    if (!d && !H.err) hvLazy();
    const bar = '<div class="whx-bar"><span class="wnote">받은 날 기준 · 기간 = 위 기간 칩 · 원가·손익 장부 숫자는 그대로</span><span class="sp"></span>'
      + '<button type="button" class="wbtn sm txt" data-w="hvCyc">매매일지 사이클로 ›</button></div>';
    if (!d) {
      return '<div class="whx">' + bar + (H.err ? '<div class="wcard wempty wemp"><span class="eic">' + ICO.gift
        + '</span><b>에어드랍 수확을 못 받았어요</b>'
        + '<span>' + esc(H.err) + '</span><button type="button" class="wbtn" data-w="hvRetry">다시 시도</button></div>' : skelRows(5))
        + '</div>';
    }
    const T = d.tot || {}, N = d.n || {}, rows = arr(d.rows), ref = d.ref || {};
    return '<div class="whx">' + bar + hvStatus(d, N) + hvHero(T, rows, ref) + hvBook(T, ref) + hvTable(rows, N) + hvFolds(d, N)
      + '<p class="wnote">정상 = 유동성 있는 시세가 있거나 · 실제로 팔았거나 · 직접 정상으로 표시한 것만(보수적) · '
      + '이 보드는 표시 전용이라 원장·원가·손익 숫자를 바꾸지 않아요 · 기간을 바꾸면 받은 날 기준으로 다시 세요</p></div>';
  }
  function hvMark(k, verdict) {
    const x = X(); if (!x || !/^g\d+$/.test(String(k || ''))) return;
    const spam = verdict === 'spam', msg = spam ? '숨겼어요 · 새 빌드를 확인하면 다시 받아요' : '복원했어요 · 새 빌드를 확인하면 다시 받아요';
    x.confirmAsk({ title: spam ? '스팸으로 숨길까요?' : '정상 자산으로 복원할까요?',
      body: (spam ? '이 코인을 스팸 격리로 옮겨요. ' : '이 코인을 스팸 격리에서 풀어요. ')
        + '보유표·총자산·일별 기록에도 같이 적용돼요(스캠 판정 지정 — 설정에서 되돌릴 수 있어요).',
      ok: spam ? '숨김' : '복원',
      run: () => x.post('/api/risk_override', { key: k, verdict }, msg)
        .then(() => { const bt0 = hvBuilt(); st.hv.wait = '새 빌드 기다리는 중…'; hvRedraw(); hvPoll(bt0, 0); }) });
  }
  const hvFlip = (o, k) => { o[k] = !o[k]; hvRedraw(); };
  const hvGoPush = () => {
    st.hv.fold.push = true; hvRedraw();
    setTimeout(() => {
      const t = $('#whxPush'); if (!t) return;
      try { t.scrollIntoView({ block: 'start',
        behavior: reduce() ? 'auto' : 'smooth' }); t.focus({ preventScroll: true }); } catch (e) {  }
    }, 30);
  };
  Object.assign(A, {
    hvRetry: () => { st.hv.err = ''; hvFetch(true); },
    hvTog: el => hvFlip(st.hv.open, el.getAttribute('data-k')),
    hvFold: el => hvFlip(st.hv.fold, el.getAttribute('data-v')),
    hvBook: () => hvFlip(st.hv, 'book'),
    hvAll: () => hvFlip(st.hv, 'all'),
    hvSort: el => { st.hv.sort = el.getAttribute('data-v') || 'harv'; hvRedraw(); },
    hvGoPush,
    hvCyc: () => { const x = X(); if (x && x.S.j) { x.S.j.view = 'cycles'; hvRedraw(); } },
    hvSpam: el => hvMark(el.getAttribute('data-k'), 'spam'),
    hvOk: el => hvMark(el.getAttribute('data-k'), 'visible')
  });
  const hvRoute = h => {
    if (!/^#journal\/harvest$/.test(String(h || ''))) return false;
    const x = X(); if (!x || !x.S.j) return false;
    x.S.j.view = 'harvest'; return true;
  };
  window.addEventListener('hashchange',
    ev => { let h = location.hash; try { h = new URL(ev.newURL).hash; } catch (e) {  } if (hvRoute(h)) hvRedraw(); });

  const HALT_URL = { upbit: 'upbit.com/service_center/notice', bithumb: 'feed.bithumb.com/notice',
    binance: 'www.binance.com/en/support/announcement', bybit: 'announcements.bybit.com/',
    okx: 'www.okx.com/help/section/announcements-latest-announcements', kucoin: 'www.kucoin.com/announcement',
    gate: 'www.gate.io/announcements' };
  const hlRow = () => { const x = X(), L = arr(x && x.S.D && x.S.D.exHalt); return L[st.halt.i] || null; };
  const hlHm = ts => { const d = new Date(num(ts) * 1000 + KST), t = new Date(Date.now() + KST), p = n => String(n).padStart(2, '0');
    return (d.toISOString().slice(0, 10) === t.toISOString().slice(0, 10) ? '' : p(d.getUTCMonth() + 1) + '-' + p(d.getUTCDate()) + ' ')
      + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()); };
  const hlDur = s => (s < 3600 ? Math.max(1, Math.floor(s / 60)) + '분' : s < 86400 ? Math.floor(s / 3600) + '시간' : Math.floor(s / 86400)
    + '일');
  document.addEventListener('click', ev => {
    const t = ev.target && ev.target.closest ? ev.target.closest('[data-a="haltInfo"]') : null; if (!t) return;
    const x = X(), i = num(t.getAttribute('data-v')); if (!x || !x.S.D || !arr(x.S.D.exHalt)[i]) return;
    ev.preventDefault(); ev.stopPropagation(); st.halt.i = i; st.halt.old = false; open('halt', { sm: true, opener: t });
  }, true);
  const hlTitle = r => r.exN + ' ' + (r.dir === 'm' ? '입출금 점검 중' : r.sym + ' ' + (r.part ? '일부 네트워크 ' : '') + ({ d: '입금',
    w: '출금' }[r.dir] || '입출금') + ' 중지');
  function hlRail(r) {
    const now = Date.now() / 1000, s0 = num(r.since), eo = num(r.eo) > now ? num(r.eo) : 0, f = s0 > 0 ? (eo ? Math.min(0.95,
      (now - s0) / (eo - s0)) : 0.78) : 0;
    if (!(s0 > 0)) return '';
    const w = (f * 100).toFixed(1), du = hlDur(Math.max(0, now - s0));
    return '<div class="whl-rail" role="img" aria-label="' + esc(hlHm(s0) + '부터 중지 · 지금 ' + hlHm(now) + ' · ' + du + '째 · ' + (eo ? '재개 예정 '
      + hlHm(eo) : '재개 예정 안내 없음')) + '">'
      + '<span class="f" style="width:' + w + '%"></span>' + (eo ? '' : '<span class="whl-tl" style="left:' + w + '%"></span>')
      + '<span class="tk" style="left:' + w + '%"></span></div>'
      + '<div class="whl-rl" aria-hidden="true"><span class="a"><span class="num">' + hlHm(s0) + '</span> 중지</span><span class="n'
      + (f < 0.35 ? ' lf' : '') + '" style="left:' + w + '%">지금 <span class="num">'
      + hlHm(now) + '</span> · ' + du + '째</span><span class="b">' + (eo ? '재개 예정 <span class="num">' + hlHm(eo) + '</span>' : '재개 미정')
      + '</span></div>';
  }
  VIEWS.halt = {
    head: () => { const r = hlRow(); return { bare: true, k: '입출금 중지', t: r ? esc(hlTitle(r)) : '입출금 중지' }; },
    body: () => {
      const r = hlRow(), x = X(); if (!r || !x) return '<div class="wempty">이 중지는 이미 풀렸어요</div>' + XB;
      const D = x.S.D, mt = r.dir === 'm', same = arr(D.exHalt).filter(z => z.ex === r.ex && z.sym === r.sym),
        on = k => mt || same.some(z => z.dir === k);
      const body = mt ? '코인 여럿의 입출금이 한꺼번에 막혔어요(점검으로 보여요) — 끝날 때까지 보내거나 빼지 마세요.'
        : r.dir === 'd' ? '지금 이 거래소로 보내면 안 들어가요 — 팔려면 다른 곳을 쓰거나 풀릴 때까지 기다리세요.'
          : '이 거래소에 있는 코인을 밖으로 옮길 수 없어요(거래소 안에서 팔기는 될 수 있어요).';
      const tile = (l, k) => '<div class="whl-st' + (on(k) ? ' on' : '') + '"><span class="l">' + l + '</span><span class="v">'
        + (on(k) ? ICO.x + (mt ? '점검 중' : '중지') : '중지 아님') + '</span></div>';
      const lg9 = !mt && D.symLogo && D.symLogo[r.sym];
      const av = !mt && typeof x.icon === 'function' ? x.icon(r.sym, 'sm', lg9 ? { ck: lg9.ck, ca: lg9.ca } : {}) : '<span class="av n">'
        + esc(String(r.exN).slice(0, 1)) + '</span>';
      const dl = (l, v) => (v ? '<div class="whl-dl"><span>' + l + '</span><span>' + v + '</span></div>' : '');
      const where = arr(r.where).map(w => '<span class="pvl">' + esc(w) + '</span>').join(mt ? ', ' : ' · ');
      const pre = arr(D.exHaltPre), url = HALT_URL[r.ex];
      return '<div class="whl-h">' + av + '<div class="c" aria-hidden="true"><span class="ey">입출금 중지</span><span class="t">'
        + esc(hlTitle(r)) + '</span></div>' + XB + '</div>'
        + '<div class="whl-tg"><span class="wtg">' + esc(r.exN) + '</span><span class="wcap">거래소 상태 확인 '
        + (num(r.age) < 60 ? '방금' : hlDur(num(r.age)) + ' 전') + '</span></div>'
        + '<p class="whl-p">' + esc(body) + ' 풀리면 이 표시는 사라져요.</p>'
        + '<div class="whl-sts">' + tile('입금', 'd') + tile('출금', 'w') + '</div>' + hlRail(r)
        + '<div class="whl-dls"><div class="whl-dl big"><span>내 보유</span><span>' + M(num(r.usd), { compact: true }) + '</span></div>'
        + dl(mt ? '영향받는 내 코인' : '보유 위치', where) + dl('막힌 네트워크', esc(arr(r.nets).join(', '))) + '</div>'
        + (r.bs ? '<div class="wnote">참고: 블록 상태 ' + esc({ delayed: '지연', inactive: '멈춤' }[r.bs] || r.bs) + ' — 반영이 늦을 수 있어요</div>' : '')
        + (pre.length ? '<button type="button" class="wbtn sm txt whl-old" data-w="hlOld" aria-expanded="' + !!st.halt.old
        + '">처음 볼 때부터 막혀 있던 보유 <span class="pvx">' + pre.length + '개</span> ›</button>'
          + (st.halt.old ? '<div class="wnote">감시를 시작했을 때 이미 막혀 있던 입출금이에요(계정·지역 제한이나 오래된 중지가 많아요) — 칩·알림은 내지 않아요.</div>'
            + '<div class="whl-dls">'
            + pre.map(z => dl(esc(z.exN + ' ' + z.sym + ' ' + (z.dir === 'd' ? '입금' : '출금')), M(num(z.usd), { compact: true }))).join('')
            + '</div>' : '') : '')
        + '<div class="whl-act">' + (url ? '<a class="wbtn" href="https://' + esc(url) + '" target="_blank" rel="noopener noreferrer"'
        + ' aria-label="'
        + esc(r.exN) + ' 공지 열기 — 새 창">' + esc(r.exN) + ' 공지 열기</a>' : '')
        + '<button type="button" class="wbtn" disabled aria-label="이 코인' + (mt ? '' : '(' + esc(r.sym) + ')')
        + ' 중지 알림 끄기 — 준비 중">이 코인 알림 끄기</button></div>'
        + '<div class="wcap whl-nt">코인별 알림 끄기는 준비 중이에요 — 지금은 설정 › 알림의 \'보유 코인 입출금 중지\'로 통째로 끌 수 있어요</div>'
        + '<button type="button" class="wbtn pri whl-ok" data-w="close">확인</button>';
    }
  };
  A.hlOld = () => { st.halt.old = !st.halt.old; paint(); };
  HV.page = hvPage; HV.count = hvCount;
  if (hvRoute((window.__tjSearchApi && window.__tjSearchApi.initHash) || location.hash) || hvOn()) setTimeout(hvRedraw, 0);
})();
