(function () {
  'use strict';
  if (window.TJSale) return;
  const X = () => (window.TJ && window.TJ.ext) || null;
  const Y = () => window.__tjSearchApi || null;
  const Z = () => window.__tjSheets || null;
  const ready = () => !!(X() && Y());
  const CATS = ['세일 참가금', '송금·결제/선물', '분실·해킹', '기타'];
  const SALE = '세일 참가금';
  const SALE_WORDS = /세일|참가금|참여금|예치|회수\s*대기|청약|\bsale\b|\bido\b|\bico\b/i;
  const esc0 = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const esc = s => (X() ? X().esc(s) : esc0(s));
  const num = v => { const n = typeof v === 'number' ? v : parseFloat(String(v == null ? '' : v).replace(/[^0-9.\-]/g, '')); return isFinite(n) ? n : 0; };
  const arr = v => (Array.isArray(v) ? v : []);
  const pvOn = () => { const x = X(); return !!(x && x.pvOn()); };
  const short = a => { const s = String(a || ''); return s.length > 12 ? s.slice(0, 6) + '…' + s.slice(-4) : s; };

  const REG = [], KEYS = new Map();
  function regId(e) {
    const o = e.of || e.ofc || {};
    const k = [o.tx || e.tx || '', o.a || '', e.sym || '', e.t || '', o.key || '', e.of ? 'o' : 'c'].join('|');
    let id = KEYS.get(k);
    if (id == null) { id = REG.length; KEYS.set(k, id); REG.push(e); } else REG[id] = e;
    return id;
  }
  function lock() {
    REG.length = 0; KEYS.clear();
    const x = X(), S9 = x && x.S;
    if (!S9) return;
    if (S9.drafts) Object.keys(S9.drafts).forEach(k => { if (k.indexOf('slm:') === 0) delete S9.drafts[k]; });
    if (S9.sheet && S9.sheet.k === 'sl') S9.sheet = null;
  }
  function nmMask(t, kind) { return '<span class="pvl"' + (kind === 'w' || kind === 'm' ? ' data-pk="' + kind + '"' : '') + '>' + nmMask0(t, kind) + '</span>'; }
  function nmMask0(t, kind) {
    const s = String(t == null ? '' : t), y = Y();
    if (pvOn() && y && typeof y.ownNm === 'function') return esc(kind === 'w' || kind === 'm' ? y.ownNm(s, kind) : y.locName(s));
    if (!pvOn() || !/\d/.test(s) || !y) return esc(s);
    return s.split(/(0x[0-9a-fA-F]{40}|[A-Za-z0-9]{4,10}…[A-Za-z0-9]{3,6}|[1-9A-HJ-NP-Za-km-z]{32,44})/).map((x, i) => (i % 2 ? esc(x) : esc(x).replace(/\d[\d,.]*/g, () => y.pvW(y.PVM.n)))).join('');
  }
  function labHTML(lab, nm, kind) {
    const y = Y(); const t = String(lab || '');
    if (!nm || t.indexOf(nm) < 0) return esc(y.hs(t));
    const i = t.indexOf(nm);
    return esc(y.hs(t.slice(0, i))) + ' ' + nmMask(nm, kind) + ' ' + esc(y.hs(t.slice(i + nm.length)));
  }
  const ofRow = a => { const x = X(); return x && x.S.D ? arr(x.S.D.of).find(r => r.address === a) || null : null; };
  function destKind(a, t) {
    const r = ofRow(a), s9 = String(t || '').trim();
    if (r && r.alias && String(r.alias).trim().slice(0, 40) === s9) return 'w';
    if (r && r.memo && String(r.memo).trim().slice(0, 40) === s9) return 'm';
    return !s9 || /^(?:0x[0-9a-fA-F]{6,64}|[A-Za-z0-9]{3,12}…[A-Za-z0-9]{3,10}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(s9) || /^(?:여러 수령처|수령처 미상)$/.test(s9) ? undefined : r && r.alias ? 'w' : 'm';
  }
  function curCls(e) {
    const o = e.of || {}, r = ofRow(o.a || (e.ofc || {}).a);
    if (r) {
      if (r.bucket === 'external') return { c: r.category === SALE ? 'sale' : 'ext', cat: r.category || '', r };
      if (r.autoMatch && arr(r.autoMatch.basis).indexOf('sale') >= 0) return { c: 'sale_auto', cat: '', r };
      if (r.bucket === 'own' || r.bucket === 'exchange' || r.bucket === 'returned' || r.bucket === 'spam' || r.bucket === 'system' || r.bucket === 'bridge') return { c: r.bucket, cat: '', r };
      return { c: 'pending', cat: '', r };
    }
    return { c: o.c || 'pending', cat: o.cat || '', r: null };
  }
  const CLS_KO = { sale: '세일 참가', sale_auto: '토큰 세일 입찰', ext: '외부 유출', own: '내 지갑', exchange: '거래소 입금주소', returned: '되돌려 받음', ret: '되돌려 받음', spam: '사칭·스팸 로그', system: '시스템 주소', bridge: '브릿지 → 내 지갑', pending: '확인 필요' };
  const CLS_TONE = { sale: 'w', sale_auto: 'a', ext: 'e', own: 'ok', exchange: 'a', returned: 'ok', ret: 'ok', spam: 'g', system: 'g', bridge: 'ok', pending: 'w' };

  function rowHTML(e) {
    if (!ready() || !e) return null;
    const y = Y(), id = regId(e);
    let h = '';
    if (e.of) {
      const o = e.of, cc = curCls(e);
      const stale = cc.r && cc.c !== o.c && !(o.c === 'ret' && cc.c === 'returned');
      h = '<button type="button" class="slrow" data-a="slOpen" data-v="' + id + '" aria-haspopup="dialog">'
        + (stale ? '<span class="pill ' + (CLS_TONE[cc.c] || 'g') + ' sm">' + esc(CLS_KO[cc.c] || '') + '</span> ' : '')
        + labHTML(o.lab, o.nm, destKind(o.a, o.nm)) + '<span class="slgo" aria-hidden="true">›</span></button>';
    } else h = esc(y.hs(e.d));
    if (e.ofc && !e.of) {
      const c = e.ofc, r = ofRow(c.a);
      const linked = r && arr(r.links).some(l => l.key === c.key);
      if (!linked && r && r.bucket === 'external' && r.category === SALE) h += ' <button type="button" class="pill a sm slsug" data-a="slOpen" data-v="' + id + '">' + nmMask(c.nm, destKind(c.a, c.nm)) + '에 연결?</button>';
    }
    return h;
  }
  function rowText(e) {
    if (!ready() || !e || !e.of) return null;
    const cc = curCls(e);
    return (CLS_KO[cc.c] || CLS_KO.pending) + (cc.c === 'ext' && CATS.indexOf(cc.cat) >= 0 ? ' · ' + cc.cat : '') + ' · 눌러서 자세히';
  }

  function mAlt(usd, o) { const x = X(), S = x.S, c = S.cur; S.cur = c === 'USD' ? 'KRW' : 'USD'; try { return x.m(usd, o); } finally { S.cur = c; } }
  const usdOfA = a => { const s = String(a == null ? '' : a); return /^\s*[-−]?\$/.test(s) ? Math.abs(num(s)) : null; };
  function salePnl(r) {
    const x = X(); if (!x || !r) return null;
    const D = x.S.D || {}, sent = r.sendKnown ? num(r.usdAtSend) : num(r.usdNow), ret = num(r.returnedUsd);
    const raw = r._opt ? ofRawRow(r.address) : null;
    const toks = arr(raw ? raw.links : r.links).filter(l => l && l.kind === 'tokens' && l.st === 'applied');
    let now = 0, ok = true;
    toks.forEach(l => { const g = arr(D.groups).find(g0 => String(g0.sym || '').toUpperCase() === String(l.sym || '').toUpperCase());
      const px = g && num(g.qty) > 0 ? num(g.value) / num(g.qty) : 0; if (px > 0) now += px * num(l.qty); else ok = false; });
    return { sent, ret, tokCost: num(r.linkTokenUsd), wait: Math.max(0, num(r.saleWait)), coinN: toks.length, now, nowOk: ok && toks.length > 0, pnl: ret + now - sent, opt: !!r._opt };
  }
  function ofRawRow(a) { const x = X(), f = x && x.S.data && x.S.data.fields; return f ? arr(f.outflows).find(z => z && z.address === a) || null : null; }
  const OPT_PILL = '<span class="pill w sm">반영 중</span>';
  const candLive = r => { const ks = new Set(arr(r && r.links).map(l => String(l && l.key))); return arr(r && r.candTop).filter(c => c && !ks.has(String(c.key))); };

  function candLine(r, c, small) {
    const x = X(), when = c.ts ? x.fmtTs(c.ts).slice(5, 16) : '';
    const what = c.stable ? '환불' : '새 코인';
    return '<span class="slc-m">' + (c.fromSender ? '<span class="pill ok sm">보낸 지갑으로 들어옴</span> ' : '') + '<b><span class="num">' + (pvOn() ? Y().pvW(Y().PVM.q) : esc(x.q(num(c.qty)))) + '</span> ' + esc(c.sym) + '</b>'
      + '<span class="cap"> ' + esc(what) + ' · ' + esc(when) + (c.where ? ' · ' + nmMask(c.where) : '') + '</span></span>'
      + '<span class="slc-b"><button type="button" class="btn sm pri" data-a="slLink" data-k="' + esc(r.address) + '" data-v="' + esc(c.key) + '">연결</button>'
      + '<button type="button" class="btn sm ghost" data-a="slNo" data-k="' + esc(r.address) + '" data-v="' + esc(c.key) + '">아님</button></span>';
  }
  function candStrip(r) {
    const cs = candLive(r);
    if (!ready() || !r || !cs.length) return '';
    const c = cs[0], more = Math.max(0, num(r.candN) - 1 - (arr(r.candTop).length - cs.length));
    return '<div class="slcand" data-kbskip="1" role="group" aria-label="연결 제안">' + '<span class="slc-t">연결할까요?</span>' + candLine(r, c)
      + (more ? '<button type="button" class="lnk slc-more" data-a="ofLkOpen" data-k="' + esc(r.address) + '">+' + more + '건 더 보기</button>' : '') + '</div>';
  }

  function kv(k, v, cl) { return '<div class="slkv' + (cl ? ' ' + cl : '') + '"><span class="k">' + k + '</span><span class="v">' + v + '</span></div>'; }
  function walletName(w) {
    const x = X(); if (!w) return '';
    const wr = arr(x.S.D && x.S.D.f && x.S.D.f.walletRows).find(z => String(z.addr || '').toLowerCase() === String(w).toLowerCase());
    return wr && wr.alias ? nmMask(wr.alias, 'w') + ' <span class="mono cap">' + esc(short(w)) + '</span>' : '<span class="mono">' + esc(short(w)) + '</span>';
  }
  function sheetBody(id) {
    const e = REG[num(id)], x = X(), y = Y();
    if (!e || !x || !y) return '<div class="cap">기록을 찾지 못했어요 — 다시 열어 주세요</div>';
    if (!e.of && e.ofc) return sugBody(e);
    const o = e.of, cc = curCls(e), r = cc.r, a = o.a || '';
    const chain = (y.CHAIN_KO && y.CHAIN_KO[o.ch]) || o.ch || '';
    const xl = (u, t) => u ? '<a class="mono" href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(t) + ' ↗</a>' : '<span class="mono">' + esc(t) + '</span>';
    const txL = o.tx ? xl(y.exUrl(o.ch, o.tx), short(o.tx)) : '—';
    const adL = a && a !== 'multi' && a !== '?' ? xl(y.exUrl(o.ch, a, true), short(a)) : nmMask(o.nm || '', destKind(a, o.nm));
    const nmU = r ? (r.alias || r.memo) : '';
    const hint = r && arr(r.hints)[0] ? nmMask(r.hints[0].label || '', r.hints[0].kind === 'my_wallet' ? 'w' : undefined) : '';
    const ai = r && r.aiOp && r.aiOp.st === 'ok' ? '<span class="pill g sm">AI 의견</span> ' + '<span class="aib">' + (pvOn() ? 'AI 설명 — 가림 모드에서는 숨겨요' : nmMask(r.aiOp.label || '모름')) + '</span>' + ' <span class="cap">확신 ' + esc(String(r.aiOp.conf || '낮음')) + ' · 참고용</span>' : '';
    const usd = usdOfA(e.a);
    const qty = pvOn() ? y.pvW(y.PVM.q) : esc(String(e.q == null ? '' : e.q));
    let h = '<div class="slhd"><span class="pill ' + (CLS_TONE[cc.c] || 'g') + '">' + esc(CLS_KO[cc.c] || '확인 필요') + (cc.cat && cc.c === 'ext' ? ' · ' + esc(cc.cat) : '') + '</span>'
      + (r && r._opt ? OPT_PILL : '') + '<span class="cap num">' + esc(String(e.iso || e.t || '')) + (chain ? ' · ' + esc(chain) : '') + '</span></div>'
      + '<div class="slamt"><b class="num">' + y.evA(e) + '</b>' + (usd != null ? '<span class="num mut">' + mAlt(usd) + '</span>' : '') + '<span class="cap">' + esc(e.sym || '') + ' <span class="num">' + qty + '</span> · 보낼 때 가치</span></div>'
      + '<div class="slbox">'
      + kv('받는 곳', (nmU ? '<b>' + nmMask(nmU, r.alias ? 'w' : 'm') + '</b> ' : '') + adL + (hint ? '<span class="cap" style="display:block">' + hint + '</span>' : '') + (ai ? '<span style="display:block;margin-top:4px">' + ai + '</span>' : ''))
      + kv('보낸 지갑', walletName(o.w) || '—') + kv('전송', txL) + (o.cost ? kv('원가', esc(y.hs(String(o.cost).replace(/^원가\s*/, ''), true))) : '') + '</div>';
    if (cc.c === 'sale_auto') {
      h += '<div class="cap" style="margin:10px 0">토큰 세일(경매) 입찰로 자동 인식했어요 — 받은 토큰이 입찰액을 원가로 이어받아요.</div>';
    } else if (cc.c === 'own' || cc.c === 'exchange' || cc.c === 'returned' || cc.c === 'bridge' || cc.c === 'spam' || cc.c === 'system') {
      h += '<div class="cap" style="margin:10px 0">보낸 내역에서 이미 정리된 전송이에요.</div>';
    } else {
      const on = cc.c === 'sale' ? SALE : cc.c === 'ext' ? cc.cat : '';
      h += '<div class="sllh"><span class="lab">무엇이었나요?</span>' + (cc.c === 'pending' ? '' : '<button type="button" class="lnk mut" data-a="slClear" data-k="' + esc(a) + '">분류 풀기</button>') + '</div><div class="optline slcats">' + CATS.map(c => '<button type="button" class="fbtn' + (on === c ? ' on' : '') + '" data-a="slCat" data-k="' + esc(a) + '" data-v="' + esc(c) + '" aria-pressed="' + (on === c) + '">' + esc(c === SALE ? '세일 참여' : c) + '</button>').join('')
        + '<button type="button" class="fbtn" data-a="slGo" data-k="' + esc(a) + '" data-v="own">내 지갑·거래소예요</button></div>'
        + (cc.c === 'pending' ? '<div class="cap">고르기 전까지는 확인 필요로 남아요(총자산에서는 이미 빠져 있어요)</div>' : '');
      if (cc.c === 'sale' && r) h += saleBox(r);
    }
    const memo = r ? r.memo : '';
    h += '<div class="lab sllab">메모</div>' + (pvOn() ? '<div class="cap">' + (memo ? y.pvW('메모 내용 8,888') : '없음') + ' · 가림을 끄면 고칠 수 있어요</div>'
      : '<div class="frm slmemo"><input class="field" data-pr="1" maxlength="200" placeholder="예: 어느 세일 · 몇 차" data-draft="' + esc('slm:' + a) + '" data-enter="slMemo" data-k="' + esc(a) + '" value="' + esc(memo) + '" aria-label="메모"><button type="button" class="btn" data-a="slMemo" data-k="' + esc(a) + '">저장</button></div>');
    h += '<div class="slft"><button type="button" class="btn" data-a="slGo" data-k="' + esc(a) + '">보낸 내역에서 보기</button></div>';
    return h;
  }
  function saleBox(r) {
    const x = X(), p = salePnl(r);
    let h = (p.opt ? '<div class="cap" style="margin:4px 0 8px">' + OPT_PILL + ' 저장했어요 · 서버가 다시 계산하면 금액이 그 값으로 바뀌어요</div>' : '') + '<div class="slbox slsale">' + kv('넣은 돈', x.m(p.sent) + ' <span class="cap">' + mAlt(p.sent) + '</span>') + kv('환불', x.m(p.ret), 'ok')
      + kv('받은 코인 원가', x.m(p.tokCost)) + (p.coinN ? kv('받은 코인 지금 가치', p.nowOk ? x.m(p.now) : '시세 없음') : '') + kv('<b>회수 대기</b>', '<b>' + x.m(p.wait) + '</b>')
      + (p.coinN && p.nowOk ? kv('세일 손익(지금 기준)', '<b class="' + x.cls(p.pnl) + '">' + x.m(p.pnl, { sign: true }) + '</b>') : '') + '</div>';
    const cs = candLive(r);
    if (cs.length) h += '<div class="lab sllab">연결할까요?</div>' + cs.map(c => '<div class="slcand in">' + candLine(r, c) + '</div>').join('');
    h += '<div class="cap">환불이나 받은 코인은 연결해야 넣은 돈에서 빠져요 · 받은 코인 원가 = 넣은 돈 − 환불</div>';
    return h;
  }
  function sugBody(e) {
    const x = X(), y = Y(), c = e.ofc, r = ofRow(c.a);
    const qty = pvOn() ? y.pvW(y.PVM.q) : esc(String(e.q == null ? '' : e.q).replace(/^\+/, ''));
    const big = usdOfA(e.a) != null ? y.evA(e) : '<span class="num">' + qty + '</span> ' + esc(e.sym || '');
    let h = '<div class="slhd"><span class="pill a">' + (c.kind === 'refund' ? '환불 후보' : '새 코인 후보') + '</span><span class="cap num">' + esc(String(e.iso || e.t || '')) + '</span></div>'
      + '<div class="slamt"><b class="num">' + big + '</b><span class="cap">' + esc(e.sym || '') + ' · ' + (c.kind === 'refund' ? '같은 코인이 돌아옴(환불일 수 있어요)' : '새 코인이 들어옴(세일 토큰일 수 있어요)') + (c.fromSender ? ' · 보낸 지갑으로 들어옴' : '') + '</span></div>'
      + '<div class="slbox">' + kv('세일', '<b>' + nmMask(c.nm, destKind(c.a, c.nm)) + '</b> <span class="mono cap">' + esc(short(c.a)) + '</span>') + (r ? kv('넣은 돈', x.m(r.sendKnown ? r.usdAtSend : r.usdNow) + ' <span class="cap">' + mAlt(r.sendKnown ? r.usdAtSend : r.usdNow) + '</span>') + kv('회수 대기', x.m(Math.max(0, num(r.saleWait)))) : '') + '</div>'
      + '<div class="slft"><button type="button" class="btn pri" data-a="slLink" data-k="' + esc(c.a) + '" data-v="' + esc(c.key) + '">연결</button>'
      + '<button type="button" class="btn" data-a="slNo" data-k="' + esc(c.a) + '" data-v="' + esc(c.key) + '">아님</button>'
      + '<button type="button" class="btn ghost" data-a="slGo" data-k="' + esc(c.a) + '">보낸 내역에서 보기</button></div>'
      + '<div class="cap">연결하면 ' + (c.kind === 'refund' ? '이 환불만큼 넣은 돈이 회수돼요' : '이 코인 원가 = 넣은 돈 − 환불이 돼요') + ' · 언제든 풀 수 있어요</div>';
    return h;
  }

  const ACTS = {
    slOpen: el => { const z = Z(), e = REG[num(el.getAttribute('data-v'))]; if (!z || !e) return; z.open('sl', String(el.getAttribute('data-v')), e.of ? '보낸 전송' : '세일 연결 제안', el); },
    slCat: el => { const x = X(), a = el.getAttribute('data-k'), c = el.getAttribute('data-v'), r = ofRow(a); if (!x || !a || CATS.indexOf(c) < 0) return;
      if (r && r.bucket === 'external' && r.category === c) return;
      x.post('/api/outflow_resolve', { address: a, verdict: 'external', category: c }, (c === SALE ? '세일 참여로 정했어요' : c + '(으)로 정했어요') + ' · 보낸 내역과 같이 바뀌어요').then(() => { const z = Z(); if (z) z.redraw(); }); },
    slClear: el => { const x = X(), a = el.getAttribute('data-k'); if (!x || !a) return; x.post('/api/outflow_resolve', { address: a, verdict: 'clear' }, '분류를 풀었어요 · 확인 필요로 돌아가요').then(() => { const z = Z(); if (z) z.redraw(); }); },
    slMemo: el => { const x = X(), a = el.getAttribute('data-k'); if (!x || !a || pvOn()) return;
      const d = x.S.drafts['slm:' + a], r = ofRow(a), v = String(d == null ? (r ? r.memo : '') : d).trim();
      if (v.length > 200) { x.toast('메모는 200자까지예요', true); return; }
      x.post('/api/outflow_resolve', { address: a, op: 'memo', memo: v }, v ? '메모를 저장했어요' : '메모를 지웠어요').then(dd => { if (dd) delete x.S.drafts['slm:' + a]; }); },
    slGo: el => { const x = X(), z = Z(), a = el.getAttribute('data-k'); if (z) z.close(true); if (x && a) setTimeout(() => x.revealAndHighlight('outflow:' + a), 0); },
    slLink: el => { const x = X(), a = el.getAttribute('data-k'), k = el.getAttribute('data-v'), r = ofRow(a); if (!x || !a || !k) return;
      const c = r ? arr(r.candTop).find(y => y.key === k) : null, sug = REG.find(e => e && e.ofc && e.ofc.key === k);
      const kind = c ? c.kind : sug ? sug.ofc.kind : null; if (!kind) { x.toast('후보를 다시 불러온 뒤 시도해 주세요', true); return; }
      x.post('/api/outflow_resolve', { address: a, op: 'link', links: [{ kind, key: k }] }, kind === 'refund' ? '환불로 연결했어요' : '받은 코인으로 연결했어요 · 원가 = 넣은 돈 − 환불').then(d => { const z = Z(); if (d && z && sug) z.close(true); }); },
    slNo: el => { const x = X(), a = el.getAttribute('data-k'), k = el.getAttribute('data-v'); if (!x || !a || !k) return;
      x.post('/api/outflow_resolve', { address: a, op: 'dismiss', key: k }, '제안에서 뺐어요 · 보낸 내역 연결 고르기에는 남아요').then(d => { const z = Z(); if (d && z) z.close(true); }); },
  };

  const isSale = r => r && r.bucket === 'external' && r.category === SALE;
  const isAuto = r => r && r.autoMatch && arr(r.autoMatch.basis).indexOf('sale') >= 0;
  function searchItems(P, h) {
    const x = X(); if (!x || !x.S.D || !P) return [];
    const raw = String(P.raw || P.text || '');
    if (!SALE_WORDS.test(raw)) return [];
    const rows = arr(x.S.D.of).filter(r => isSale(r) || isAuto(r));
    const m = x.m, out = [], rt = (h && h.rtHTML) || ((a, b) => '<div class="tjs-rt"><b>' + (a || '') + '</b>' + (b ? '<span>' + b + '</span>' : '') + '</div>');
    const sal = rows.filter(isSale), sent = sal.reduce((s, r) => s + (r.sendKnown ? num(r.usdAtSend) : num(r.usdNow)), 0);
    const wait = sal.reduce((s, r) => s + Math.max(0, num(r.saleWait)), 0), ret = sal.reduce((s, r) => s + num(r.returnedUsd), 0), tok = sal.reduce((s, r) => s + num(r.linkTokenUsd), 0);
    const go = () => { const T = window.__tj; if (T && T.A && T.A.ofWaitGo) T.A.ofWaitGo(); const yy = Y(); if (yy) yy.goTab('outflows'); };
    out.push({ kind: 'sale', id: 'sale:sum', sc: 1000, title: '세일 참가 ' + sal.length + '곳' + (rows.length > sal.length ? ' · 자동 입찰 ' + (rows.length - sal.length) + '곳' : '') + ' · 지금 예치 중(회수 대기) ' + m(wait, { compact: true }),
      sub: sal.length ? '넣은 돈 ' + m(sent, { compact: true }) + ' · 돌려받음 ' + m(ret, { compact: true }) + ' · 코인으로 받음 ' + m(tok, { compact: true })
        : '아직 세일 참가금으로 고른 전송이 없어요 — 보낸 내역 확인 필요나 일별 기록 그 줄에서 고르면 여기 모여요',
      rt: rt(m(wait, { compact: true }), mAlt(wait, { compact: true })), tab: 'outflows', go, iso: '' });
    rows.slice().sort((p, q) => num(q.lastTs) - num(p.lastTs)).forEach(r => {
      const nm = r.alias || r.memo || '', p = salePnl(r), st = isAuto(r) && !isSale(r) ? '토큰 세일 입찰(자동)' : p.wait > 0.5 ? (p.ret + p.tokCost > 0.5 ? '일부 회수' : '회수 대기') : '회수 끝';
      out.push({ kind: 'sale', id: 'sale:' + r.address, sc: 900, addr: r.address, chains: arr(r.chains), iso: r.lastTs ? new Date(num(r.lastTs) * 1000 + 9 * 3600e3).toISOString().slice(0, 10) : '',
        title: (nm ? nmMask(nm, r.alias ? 'w' : 'm') + ' <span class="tjs-mono tjs-mut">' + esc(short(r.address)) + '</span>' : '<span class="tjs-mono">' + esc(short(r.address)) + '</span>') + ' <span class="pill ' + (st === '회수 끝' ? 'ok' : 'w') + ' sm">' + esc(st) + '</span>',
        sub: esc(arr(r.chainNames).slice(0, 2).join(' · ')) + (r.first ? ' · ' + esc(String(r.first).slice(0, 10)) + ' 참가' : '') + ' · 넣은 돈 ' + m(p.sent, { compact: true }) + (p.ret ? ' · 환불 ' + m(p.ret, { compact: true }) : '') + (p.tokCost ? ' · 코인 ' + m(p.tokCost, { compact: true }) : ''),
        rt: rt(m(p.sent, { compact: true }), mAlt(p.sent, { compact: true })), anc: 'outflow:' + r.address, tab: 'outflows', usd: p.sent });
    });
    return out;
  }

  const CSS = '.slrow{all:unset;cursor:pointer;display:inline;color:inherit;border-bottom:1px dashed var(--line2)}.slrow:hover{color:var(--text)}.slrow:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}'
    + '.slrow .slgo{margin-left:4px;color:var(--faint)}.slsug{cursor:pointer;margin-left:4px}'
    + '.slhd{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}.slamt{display:flex;flex-direction:column;gap:2px;margin-bottom:12px}.slamt b{font-size:22px}.slamt .mut{font-size:13px}'
    + '.slbox{border:1px solid var(--line);border-radius:12px;padding:4px 12px;margin-bottom:12px;background:var(--surface2)}.slkv{display:flex;gap:12px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--line);font-size:13.5px}'
    + '.slkv:last-child{border-bottom:0}.slkv .k{flex:0 0 92px;color:var(--muted)}.slkv .v{flex:1;min-width:0;overflow-wrap:anywhere;text-align:right}.slkv.ok .v{color:var(--ok)}.slkv a{color:var(--accent);text-decoration:none}'
    + '.sllab{margin:12px 0 6px}.sllh{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:12px 0 6px}.sllh .lnk{background:none;border:0;color:var(--muted);font-size:12.5px;cursor:pointer;padding:4px 0}.slcats{margin-bottom:6px}.slmemo{display:flex;gap:8px}.slmemo .field{flex:1;min-width:0}.slft{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 6px}'
    + '.slcand{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:9px 14px;border-bottom:1px dashed var(--line);background:color-mix(in srgb,var(--warn) 7%,var(--surface));font-size:13px}'
    + '.slcand.in{border:1px solid var(--line);border-radius:10px;margin-bottom:6px;background:var(--surface)}.slcand .slc-t{font-weight:650;color:var(--warn)}.slcand .slc-m{flex:1;min-width:0}.slcand .slc-b{display:flex;gap:6px}'
    + '.slcand .btn{min-height:32px}.slc-more{margin-left:auto}.ofnm{font-weight:650;max-width:100%}.ofsl0{cursor:pointer;margin-left:6px}'
    + '@media (max-width:640px){.slkv .k{flex-basis:80px}.slcand{padding:9px 12px}.slcand .slc-b{width:100%;justify-content:flex-end}.slcand .btn{min-height:40px;padding:0 16px}}';
  function addCss() { if (document.getElementById('tjSlCss')) return; const s = document.createElement('style'); s.id = 'tjSlCss'; s.textContent = CSS; document.head.appendChild(s); }

  function boot() {
    addCss();
    const z = Z(); if (z) z.reg('sl', sheetBody);
    const T = window.__tj; if (T && T.A) Object.keys(ACTS).forEach(k => { if (!T.A[k]) T.A[k] = ACTS[k]; });
    if (!(z && T && T.A)) { setTimeout(boot, 200); return; }
    try { if (X()) X().render(); } catch (e) {  }
  }
  window.TJSale = { rowHTML, rowText, candStrip, salePnl, searchItems, lock, mAlt: (u, o) => (ready() ? mAlt(u, o) : ''), _reg: REG, _acts: ACTS, _sheet: sheetBody, SALE_WORDS };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
