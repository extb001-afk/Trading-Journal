'use strict';
(window.__tjTabs = window.__tjTabs || {}).out = function (X) {
  const {
    $, ago, AI_HIDE, arr, CHAIN_KO, clps, cls, errTxt, esc, evSkel, EX_NAMES, EX_ORDER, exLogo, fmtTs, hs, IC, icon, impChip, KST_MS, m, mN, nf, num,
    ofAuto, ofNetV, ofTraced, onUnauthorized, pad2, PCAT_ORDER, PCATS, pendSplitTxt, plainT, preData, prTxt, PVM, pvOn, pvW, px, q, renderView, rw, S,
    searchBox, short, shortL, spamNm, sum, UI_CHEV, uiCell, uiHidChip, uiOpen, uiPaged, uiPick, URL_NM, ymShift
  } = X;
  let locH, locNameM, ofByAddr, offcAsk, offcGroup, ownH, ownScrubM, SXI;
  const __late = L => {
    if ('locH' in L) locH = L.locH;
    if ('locNameM' in L) locNameM = L.locNameM;
    if ('ofByAddr' in L) ofByAddr = L.ofByAddr;
    if ('offcAsk' in L) offcAsk = L.offcAsk;
    if ('offcGroup' in L) offcGroup = L.offcGroup;
    if ('ownH' in L) ownH = L.ownH;
    if ('ownScrubM' in L) ownScrubM = L.ownScrubM;
    if ('SXI' in L) SXI = L.SXI;
  };
  const HIDE_LBL = { dust: '소액', scam: '스캠', info: '표시용 보정' };
  function pendMatch(p, ql) { return !ql || String(p.sym).toUpperCase().indexOf(ql) >= 0 || String(p.kind).toUpperCase().indexOf(ql) >= 0; }
  const PCAT_D1 = { unv: '매수 기록 없는 수량을 판 매도 — 원가를 정하면 실현손익에 반영', unkh: '원가를 모르는 보유 — 원가를 정하면 평가손익에 반영 · 금액 큰 순',
    lost: '옛 기록 수집 범위(5개월) 이전 보유분 처분 — 표시용 보정, 할 일 없음', xfer: '미등록 외부 주소로 나간 전송 — 내 지갑이면 설정에서 추가',
    prog: '컨트랙트를 거쳐 들어온 토큰 — 체결인지 에어드랍인지 확인', nodep: '거래소 입금 주소로 보냈는데 아직 입금 확인 없음', etc: '자동 매칭이 보류된 건',
    spam: '실매수 이력 없이 들어온 토큰 — 목록에서 뺐어요 · 실제 보유면 복원' };
  const uGrpHead = (v, open, label, badge, extra, d1, title, pvx) => '<div class="gh" role="button" tabindex="0" data-a="uGrp" data-v="' + v + '" aria-expanded="' + open + '"><span class="chev' + (open ? ' o' : '') + '" style="width:18px">' + IC.chev + '</span><span class="h3' + (pvx ? ' pvx' : '') + '">' + label + '</span>' + badge + extra + '<span class="sp"></span>'
    + '<div class="gd gd1' + (pvx ? ' pvx' : '') + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + d1 + '</div></div>';
  function vUnmatched() {
    const D = S.D;
    const ql = S.u.q.trim().toUpperCase();
    const ps = D.pendVis.filter(p => pendMatch(p, ql));
    const hid = D.pendHid.filter(p => pendMatch(p, ql));
    const byCat = {};
    ps.forEach(p => (byCat[p._cat] || (byCat[p._cat] = [])).push(p));
    const cats = PCAT_ORDER.filter(c => byCat[c]);
    if (S.u.open == null) S.u.open = new Set(cats.length ? [cats[0]] : []);
    const hc = { dust: 0, scam: 0, info: 0 };
    D.pendHid.forEach(p => { hc[p.hide] = (hc[p.hide] || 0) + 1; });
    const hcTxt = Object.keys(hc).filter(k => hc[k]).map(k => HIDE_LBL[k] + ' ' + hc[k]).join(' · ');
    const hidChip = D.pendHid.length ? uiHidChip(D.pendHid.length, 'uHidden', S.u.showHidden, '자동으로 숨긴 항목 ' + D.pendHid.length + '건' + (hcTxt ? '(' + hcTxt + ')' : '') + (S.u.showHidden ? ' — 누르면 닫아요' : ' — 누르면 목록 위에 보여요')) : '';
    const split = D.unkhSymN && D.pendN !== D.unkhSymN ? '<span class="pvx">' + esc(pendSplitTxt()) + '</span> · ' : '';
    const top = '<div class="filters uhead"><div style="min-width:0"><div class="cap ucap1" title="원가를 지정하거나 무시로 정리하면 목록에서 빠져요 · 원가가 붙으면 평균 매수가·실현손익이 다시 계산돼요"><b class="ucnt">확인할 것 ' + D.pendN + '개</b> · ' + split + '원가를 정하거나 숨기면 목록에서 빠져요</div></div><div class="sp"></div>'
      + '<div class="row gap8 srchrow">' + searchBox('uq', '코인·유형 검색', S.u.q) + hidChip
      + '</div></div>';
    const bal = balGroupHTML();
    const hidGrp = S.u.showHidden && hid.length ? '<div class="card ugrp" id="uHidGrp"><div class="gh" style="cursor:default"><span class="h3">숨긴 항목</span><span class="badge g">' + hid.length + '</span>' + (hcTxt ? '<span class="cap pvx">' + esc(hcTxt) + '</span>' : '') + '<span class="sp"></span>' + (hid.some(p => p._cat === 'spam') ? '<button class="btn sm warn" data-a="bulkSpam">스팸 ' + hid.filter(p => p._cat === 'spam').length + '건 목록에서 지우기</button>' : '') + '<div class="gd gd1" title="소액·확실한 스캠·표시용 보정이라 기본으로 숨겼어요. 실제 자산이면 [정상으로 복원]을 누르세요.">소액·스캠·표시용 보정 — 실제 자산이면 펼쳐서 [정상으로 복원]</div></div>'
      + uiPaged('ug:hid', hid, (p, i) => pItem(p, i, hid), { unit: '건' }) + '</div>' : '';
    const beg = beGroupHTML();
    if (!D.pendings.length) return top + bal + beg + (preData() ? '<div class="card empty"><div class="eic">' + IC.info + '</div><b>아직 수집 전이에요</b>지갑·거래소를 연결하고 첫 수집이 끝나면 매칭이 필요한 전송·입금을 여기서 보여줘요</div>'
      : '<div class="card empty"><div class="eic">' + IC.check + '</div><b>확인할 건이 없어요</b>모든 전송·입금이 자동으로 매칭됐어요</div>');
    if (!cats.length && !hid.length) return top + hidGrp + bal + (beg || '<div class="card empty"><b>"' + esc(S.u.q) + '"에 해당하는 건이 없어요</b></div>');
    const main = cats.length ? cats.map(c => {
      const list = byCat[c], open = S.u.open.has(c), meta = PCATS[c];
      const imp = sum(list, p => num(p.usd));
      const amt = imp >= 1 ? '<span class="cap num">' + mN(imp, { compact: true }) + '</span>' : '';
      if (c === 'unkh') {
        const rows = unkhRows(list);
        return '<div class="card ugrp">' + uGrpHead(c, open, meta.label, '<span class="badge">' + rows.length + '종</span>', (rows.length < list.length ? '<span class="cap pvx">보관처별 ' + list.length + '줄</span>' : '') + amt, PCAT_D1[c], meta.desc + ' 같은 코인은 한 줄로 묶었어요.')
          + (open ? clps('ug:' + c, uiPaged('ug:' + c, rows, (r, i) => r.grp ? pGrpItem(r.grp, list) : pItem(r.p, i, list), { unit: '줄' })) : '') + '</div>';
      }
      return '<div class="card ugrp">' + uGrpHead(c, open, meta.label, '<span class="badge' + (c === 'spam' ? ' g' : '') + '">' + list.length + '</span>', amt, PCAT_D1[c] || meta.desc, meta.desc)
        + (open ? clps('ug:' + c, uiPaged('ug:' + c, list, (p, i) => pItem(p, i, list), { unit: '건' })) : '') + '</div>';
    }).join('') : '<div class="card empty"><div class="eic">' + IC.check + '</div><b>애매한 건은 없어요</b>남은 건 모두 소액·스캠이라 숨겨 두었어요</div>';
    return top + offcAsk() + hidGrp + bal + main + beg;
  }
  function unkhRows(list) {
    const by = new Map();
    list.forEach(p => { const k0 = String(p.sym || '').toUpperCase() || p.key; if (!by.has(k0)) by.set(k0, []); by.get(k0).push(p); });
    return Array.from(by.values()).map(ms => ms.length > 1 ? { grp: ms.slice().sort((a, b) => num(b.usd) - num(a.usd)), usd: sum(ms, p => num(p.usd)) } : { p: ms[0], usd: num(ms[0].usd) })
      .sort((a, b) => b.usd - a.usd);
  }
  function beGroupHTML() {
    const D = S.D, ql = S.u.q.trim().toUpperCase();
    const L = arr(D.costDecided).filter(r => !ql || String(r.sym || '').toUpperCase().indexOf(ql) >= 0 || '손익 0'.indexOf(ql) >= 0);
    if (!L.length) return '';
    const open = S.u.open.has('be'), cmp = L.some(r => num(r.usd) >= 1e4), tot = sum(L, r => num(r.usd));
    const rows = uiPaged('ug:be', L, r => {
      const d0 = String(r.first || '').slice(5), d1 = String(r.last || '').slice(5);
      const desc = q(num(r.qty)) + ' ' + String(r.sym || '') + ' 매도 · ' + num(r.n) + '건 · ' + (d0 && d0 !== d1 ? d0 + '~' + d1 : d1);
      const chip = '<button class="pill ok bechip pvx" data-a="costBeUndo" data-k="' + esc(r.gkey) + '" data-s="' + esc(r.sym) + '" title="' + esc(fmtTs(r.until)) + ' 에 정함 · 누르면 되돌려요">손익 0으로 처리함 · <u>되돌리기</u></button>';
      return '<div class="uit"><div class="ih" style="cursor:default"><span class="who">' + icon(r.sym, 'sm', D0().symLogo[String(r.sym || '').toUpperCase()] || {}) + '<span class="ell"><b>' + esc(r.sym) + '</b> <span class="mut" style="font-size:13px">' + esc(r.chain && r.chain !== '—' ? r.chain : '') + '</span>'
        + '<span class="sub ell mob-only">' + esc(desc) + '</span><span class="mob-only" style="margin-top:6px">' + chip + '</span></span></span>'
        + '<span class="dsc bedsc"><span class="ell">' + esc(desc) + '</span>' + chip + '</span>'
        + '<span class="imp"><b class="num"' + (cmp ? ' title="' + esc(m(num(r.usd))) + '"' : '') + '>' + m(num(r.usd), { compact: cmp }) + '</b><span class="cap pvx">정산 · 손익 0</span></span><span></span></div></div>';
    }, { unit: '건' });
    return '<div class="card ugrp" id="uBeGrp">' + uGrpHead('be', open, '손익 0으로 처리한 매도', '<span class="badge" style="background:var(--okBg);color:var(--ok)">' + L.length + '</span>', tot >= 1 ? '<span class="cap num">' + mN(tot, { compact: true }) + '</span>' : '',
      '원가 모르는 매도를 매수가 = 매도가로 봐서 손익 0 · 되돌리면 원가 미확인으로', '원가를 모르는 매도를 매수가 = 매도가로 봐서 손익 0으로 계산하고 있어요. 되돌리면 다시 원가 미확인 매도로 돌아가요.', true) + (open ? clps('ug:be', rows) : '') + '</div>';
  }
  function balGroupHTML() {
    const D = S.D;
    if (!D.bc || !D.bc.mismatches.length) return '';
    const open = S.u.open.has('bal');
    const rows = D.bc.mismatches.slice().sort((a, b) => Math.abs(num(b.diffUsd)) - Math.abs(num(a.diffUsd))).map(x => {
      const conf = x.confirmed === undefined || !!x.confirmed;
      return '<div class="uit"><div class="ih" style="cursor:default"><span class="who">' + icon(x.sym, 'sm', { chain: x.chain }) + '<span class="ell"><b>' + esc(x.sym || '?') + '</b> <span class="mut">' + esc(x.wallet || '?') + ' · ' + esc(x.chain || '') + '</span></span></span>'
        + '<span class="dsc ell num">원장 ' + q(num(x.ledger)) + ' / 온체인 ' + q(num(x.onchain)) + (x.firstSeen ? ' · 최초 ' + esc(fmtTs(x.firstSeen)) : '') + '</span><span class="imp"><b class="num ' + cls(num(x.diffUsd)) + '">' + (x.diffUsd != null ? m(num(x.diffUsd), { sign: true }) : '—') + '</b>' + (conf ? '<span class="pill e sm">확정</span>' : '<span class="pill g sm">관찰 중</span>') + '</span><span></span></div></div>';
    }).join('');
    return '<div class="card ugrp">' + uGrpHead('bal', open, '잔고 대조 불일치', '<span class="badge">' + D.bcConfirmed.length + '</span>',
      (D.bcWatch.length ? '<span class="cap pvx">관찰 중 ' + D.bcWatch.length + '</span>' : '') + (D.bc.unchecked ? '<span class="cap wtxt pvx" title="대조 호출 상한에 걸려 이번 판에 못 본 (체인, 지갑) 쌍 — 다음 판에 이어서 봐요(그 쌍의 지난 불일치는 그대로 보여요)">이번 판 미대조 ' + D.bc.unchecked + '쌍</span>' : ''),
      '원장 ≠ 온체인 실잔고 — 알림 전용 · ' + esc(fmtTs(D.bc.checkedAt)) + ' 대조', '원장 잔고와 온체인 실잔고가 다른 지갑·토큰이에요(알림 전용 · 원장은 그대로). 두 번 연속 확인되면 "확정"으로 표시돼요.') + (open ? clps('ug:bal', rows) : '') + '</div>';
  }
  const pQty = p => { const v = p && p.qty; if (v == null || v === '') return ''; const qn = +v; return isFinite(qn) && qn !== 0 ? q(qn) + ' ' : ''; };
  function pDesc(p) {
    const qt = pQty(p), sym = String(p.sym || '');
    if (p._cat === 'unv') return qt + sym + ' 매도';
    if (p._cat === 'unkh') return qt + sym + ' 보유';
    if (p._cat === 'lost') return qt + sym + ' 창 이전 보유분 처분';
    if (p._cat === 'spam') return p.key === 'risk:summary' ? '저평가 격리분 일괄' : qt + (URL_NM.test(sym) ? (qt ? '개' : '토큰') : sym) + ' 수령';
    if (p._cat === 'xfer') return '→ ' + (p.to ? short(p.to) : hs(p.ex || '외부 주소'));
    if (p._cat === 'prog') return '컨트랙트 경유 수령 · ' + short(p.tx || p.onchain);
    return hs(p.onchain || p.gap || '');
  }
  const IMP_LBL = { unv: '정산', unkh: '평가', lost: '원가', spam: '평가' };
  function pSub(p, list) {
    const sym = String(p.sym || ''), dup = !!sym && sym !== '—' && arr(list).filter(x => x !== p && String(x.sym || '') === sym).length > 0;
    const chainTxt = p.chain && p.chain !== '—' && p.chain !== '?' ? p.chain : '';
    if (!dup || (p._cat !== 'unv' && p._cat !== 'unkh' && p._cat !== 'lost')) return chainTxt;
    const pos = p.gkey ? arr(S.D.positions).find(x => x.key === p.gkey) : null;
    const ven = chainTxt || (pos && pos.chain && pos.chain !== '?' ? pos.chain : '');
    return [ven, p._cat === 'unkh' ? '' : String(p.t || '').slice(0, 5)].filter(Boolean).join(' · ');
  }
  function pItem(p, _i, list) {
    const open = S.u.item.has(p.key);
    const lg = D0().symLogo[String(p.sym || '').toUpperCase()] || {};
    const who = p._cat === 'xfer' || p._cat === 'prog' ? '<span class="ic sm" style="background:var(--surface3);color:var(--text2)">' + (p._cat === 'xfer' ? IC.send : IC.info).replace('<svg', '<svg width="15" height="15"') + '</span>' : icon(p.sym, 'sm', lg);
    const symTxt = p.sym && p.sym !== '—' ? spamNm(p.sym) : (p._cat === 'xfer' ? '외부 전송' : p._cat === 'prog' ? '프로그램 수령' : '—');
    const cmp = arr(list).length ? arr(list).some(x => num(x.usd) >= 1e4) : num(p.usd) >= 1e4;
    const imp = p.usd != null ? '<b class="num"' + (cmp ? ' title="' + esc(m(num(p.usd))) + '"' : '') + '>' + m(num(p.usd), { compact: cmp }) + '</b><span class="cap">' + (IMP_LBL[p._cat] || '') + '</span>' : '<span class="cap num">' + esc(p.t) + '</span>';
    const rsn = p.hide ? '<span class="pill ' + (p.hide === 'scam' ? 'e' : 'g') + ' sm">' + esc(p.hideReason || HIDE_LBL[p.hide]) + '</span>' : '';
    return '<div class="uit' + (open ? ' open' : '') + '" data-anc="pending:' + esc(p.key) + '"><div class="ih" role="button" tabindex="0" data-a="uItem" data-k="' + esc(p.key) + '" aria-expanded="' + open + '">'
      + '<span class="who">' + who + '<span class="ell"><b>' + esc(symTxt) + '</b> <span class="mut" style="font-size:13px">' + esc(pSub(p, list)) + '</span><span class="sub ell mob-only">' + esc(pDesc(p)) + '</span>' + (rsn ? '<span class="mob-only" style="margin-top:3px">' + rsn + '</span>' : '') + '</span></span>'
      + '<span class="dsc ell">' + esc(pDesc(p)) + (rsn ? ' ' + rsn : '') + '</span><span class="imp">' + imp + '</span><span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></div>'
      + (open ? clps('u:' + p.key, pBody(p)) : '') + '</div>';
  }
  function pGrpItem(ms, list) {
    const p0 = ms[0], gk = 'usym:' + String(p0.sym || '').toUpperCase(), open = S.u.item.has(gk);
    const lg = D0().symLogo[String(p0.sym || '').toUpperCase()] || {};
    const cmp = arr(list).some(x => num(x.usd) >= 1e4), tot = sum(ms, p => num(p.usd));
    const locs = ms.map(p => pSub(p, list) || (p.ckey ? '업비트' : '지갑')).filter((v, i, a) => v && a.indexOf(v) === i);
    const gq = ms.every(p => pQty(p)) ? q(sum(ms, p => num(p.qty))) + ' ' : '';
    return '<div class="uit ugp' + (open ? ' open' : '') + '"><div class="ih" role="button" tabindex="0" data-a="uItem" data-k="' + esc(gk) + '" aria-expanded="' + open + '">'
      + '<span class="who">' + icon(p0.sym, 'sm', lg) + '<span class="ell"><b>' + esc(p0.sym) + '</b> <span class="mut" style="font-size:13px">' + ms.length + '곳</span><span class="sub ell mob-only">' + esc(gq + p0.sym + ' 보유 · ' + locs.join(' · ')) + '</span></span></span>'
      + '<span class="dsc ell" title="' + esc(ms.map(p => (pSub(p, list) || '—') + ' ' + (pQty(p) || '수량 — ') + '· ' + m(num(p.usd))).join('\n')) + '">' + esc(gq + p0.sym + ' 보유') + ' <span class="mut">· ' + esc(locs.join(' · ')) + '</span></span>'
      + '<span class="imp"><b class="num"' + (cmp ? ' title="' + esc(m(tot)) + '"' : '') + '>' + m(tot, { compact: cmp }) + '</b><span class="cap">평가 합</span></span><span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></div>'
      + (open ? clps('u:' + gk, '<div class="ugsub">' + ms.map((p, i) => pItem(p, i, list)).join('') + '</div>') : '') + '</div>';
  }
  const D0 = () => S.D;
  function pBody(p) {
    const k = esc(p.key);
    const cands = arr(p.cands);
    const isSrc = cands.length && cands[0].kind === 'src';
    const path = cands.length ? '<div class="tl"><div class="lab">' + (isSrc ? '자금 경로 · 어디서 왔나' : '연결 후보') + '</div>' + cands.map(c => {
      const pct = num(c.pct), lbl = hs(c.label, true), lvl = (String(c.label).match(/↳/g) || []).length;
      const btn = c.kind === 'src' ? (c.copy ? '<button class="cpy" data-a="copy" data-v="' + esc(c.copy) + '" title="' + esc(c.btn && c.btn !== '—' ? c.btn : '복사') + '" aria-label="' + esc(c.btn && c.btn !== '—' ? c.btn : '복사') + '">' + IC.copy + '</button>' : '')
        : '<button class="btn sm" disabled title="수동 연결은 아직 지원하지 않아요">연결</button>';
      const txt = lbl.replace(/^(↳\s*)+/, '');
      const cut = txt.indexOf(' ← ');
      return '<div class="st' + (lvl ? ' l' + Math.min(2, lvl) : '') + '"><span class="dt"></span><div style="min-width:0"><div class="tx1">' + esc(cut > 0 ? txt.slice(0, cut) : txt) + '</div>' + (cut > 0 ? '<div class="tx2">' + esc(txt.slice(cut + 3)) + '</div>' : '')
        + (!lvl && pct ? '<div class="row gap8"><div class="mbar" style="flex:1"><i style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></div><span class="cap num">' + (isSrc ? '비중 ' : '일치도 ') + pct + '%</span></div>' : '') + '</div>' + btn + '</div>';
    }).join('') + '</div>' : '';
    const acts = [];
    const gk = p.gkey || (String(p.key).match(/^risk:(g\d+)$/) || [])[1];
    if ((p._cat === 'unv' || p._cat === 'unkh' || p._cat === 'lost') && p.gkey) {
      const beBtn = p._cat === 'unv' ? '<button class="btn sm pvx" data-a="costBe" data-k="' + k + '">손익 0으로 처리</button>' : '';
      if (p.costOv) acts.push('<span class="pill a">원가 지정됨 · ' + esc(p.costOv.mode === 'market' ? '당시 시세' : '개당 ' + px(num(p.costOv.unit))) + '</span><button class="btn sm" data-a="costClear" data-k="' + k + '">원가 지정 해제</button>' + beBtn);
      else acts.push('<input class="field num" inputmode="decimal" placeholder="개당 원가 (USD)" data-pv="1" data-draft="cu:' + k + '" data-enter="costUnit" data-k="' + k + '" aria-label="개당 원가 (USD)"><button class="btn sm pri" data-a="costUnit" data-k="' + k + '">원가 적용</button><button class="btn sm" data-a="costMarket" data-k="' + k + '">당시 시세로 추정</button>' + beBtn);
    }
    else if (p._cat === 'unv' || p._cat === 'unkh' || p._cat === 'lost') {
      acts.push('<div class="fbnote nocost">' + (p.ckey ? '이 줄은 원가를 직접 넣을 수 없어요 — 업비트 잔고로만 보이는 보유라 원장에 원가를 붙일 기록(매수 체결·입금)이 없어요. 업비트 체결·입금이 원장에 잡히면 원가가 자동으로 붙어요.'
        : '이 줄은 원가를 직접 넣을 수 없어요 — 원장에서 이 보유를 묶을 코인 기록을 찾지 못했어요. 지갑·거래소 기록이 수집되면 원가를 넣을 수 있어요.') + '</div>');
    }
    if (p._cat === 'spam' && gk) {
      acts.push('<button class="btn sm pri" data-a="riskRestore" data-k="' + k + '">정상으로 복원</button>');
      if (!p.hide) acts.push('<button class="btn sm" data-a="riskSpam" data-k="' + k + '">스팸 확정</button>');
    }
    acts.push('<button class="btn sm danger" data-a="ignore" data-k="' + k + '">목록에서 숨기기</button>');
    const beInfo = p._cat === 'unv' && p.costBe ? '<div class="cap bewas pvx">' + esc(fmtTs(p.costBe.until)) + '까지의 매도는 손익 0으로 처리했어요 · 이 줄은 그 뒤 매도예요</div>' : '';
    const fbInfo = num(p.fbAvg) > 0 ? '<div class="cap" style="margin-top:8px">종목 평균 매수가 ' + px(num(p.fbAvg)) + (p.fbRealized ? ' · 평균가 대체 시 손익 ' + m(num(p.fbRealized), { sign: true }) : '') + (p.fbCost ? ' · 대체 원가 ' + m(num(p.fbCost)) : '') + '</div>' : '';
    const hidNote = p.hide ? '<div class="fbnote" style="margin:12px 0 0;background:var(--surface);color:var(--text2);border:1px solid var(--line)">자동 숨김 · <b>' + esc(p.hideReason || HIDE_LBL[p.hide]) + '</b></div>' : '';
    const onch = p._cat === 'xfer' || p._cat === 'prog' ? '<div class="row gap6"><span class="mono ell">' + esc(short(p.tx || p.onchain)) + '</span>' + (p.tx || p.onchain ? '<button class="cpy" data-a="copy" data-v="' + esc(p.tx || p.onchain) + '" aria-label="txid 복사">' + IC.copy + '</button>' : '') + '</div>' : '<div class="val2 num">' + (S.cur !== 'USD' && !S.hide && /\$\s?\d/.test(String(p.onchain || '')) ? '<span class="aprx" title="체결 시각 환율이 아니라 오늘 환율로 환산했어요">≈ </span>' : '') + esc(hs(p.onchain || '—', true)) + '</div>';
    return '<div class="ib">' + hidNote + '<div class="two" style="margin-top:12px"><div><div class="lab">온체인 기록' + (p.chain && p.chain !== '—' ? ' · ' + esc(p.chain) : '') + '</div>' + onch + '</div><div><div class="lab">' + (p._cat === 'xfer' ? '목적지' : '거래소 기록') + '</div><div class="val2">' + (p._cat === 'xfer' && p.to ? '<span class="mono">' + esc(short(p.to)) + '</span> <button class="cpy" data-a="copy" data-v="' + esc(p.to) + '" aria-label="주소 복사">' + IC.copy + '</button> <span class="cap">' + esc(hs(p.ex)) + '</span>' : esc(hs(p.ex || '—'))) + '</div><div class="lab" style="margin-top:8px">왜 보류됐나</div><div class="val2 t2" style="font-size:13.5px">' + esc(hs(p.gap || '—', true)) + '</div></div></div>'
      + (p._cat === 'xfer' ? aiOpBox(p.aiOp) : '')
      + '<div class="why">' + esc(hs(p.why || '', true)) + '</div>' + (p.candsHint ? '<div class="hint">' + esc(hs(p.candsHint)) + '</div>' : '') + fbInfo + beInfo + path
      + '<div class="acts">' + acts.join('') + '</div></div>';
  }

  const OF_CATS = ['송금·결제/선물', '세일 참가금', '분실·해킹', '기타'];
  const ofCatLbl = c => (c === '송금·결제/선물' ? '송금·결제·증여' : String(c == null ? '' : c));
  const OF_VERDICT = { own: ['내 지갑', 'ok', IC.wallet], exchange: ['거래소 입금 주소', 'a', IC.bank], external: ['외부 유출 확정', 'e', IC.send], spam: ['사칭·스팸 로그', 'g', IC.shield], returned: ['되돌려 받음 · 상쇄', 'ok', IC.undo], bridge: ['브릿지 → 내 지갑', 'ok', IC.send],
    system: ['시스템 주소 · 수수료 성격', 'g', IC.fuel] };
  const OF_BASIS = { txid: 'txid', amount_time: '수량·시간', address: '입금 주소', bridge: '브릿지 도착', hop_split: '경유 주소 분할 입금', roundtrip: '프로그램 예치 왕복' };
  const ofAutoTxt = r => '자동 매칭 (근거: ' + arr(r.autoMatch && r.autoMatch.basis).map(b => esc(OF_BASIS[b] || String(b))).join(' / ') + ')';
  function ofIcon(r) {
    const look = r.flags.some(f => f.kind === 'lookalike');
    if (look) return '<span class="aic e">' + IC.alert + '</span>';
    const v = OF_VERDICT[r.bucket];
    return v ? '<span class="aic ' + v[1] + '">' + v[2] + '</span>' : '<span class="aic">' + IC.send + '</span>';
  }
  function ofExPill(r) {
    if (!r.exwd || !r.exwd.length) return '';
    const ex = r.exwd.map(x => x.exName).filter((v, i, a) => v && a.indexOf(v) === i);
    return '<span class="pill a sm">' + esc(ex.join('·') + ' 출금') + (r.exwdN > 1 ? ' ' + r.exwdN + '건' : '') + '</span>'
      + (r.exwdOffc ? '<span class="pill g sm pvx" title="거래소 사용자끼리 체인 밖 이체 — 내 다른 계정이면 설정에서 내 계정 간 이동으로 볼 수 있어요">오프체인' + (r.exwdOffc.n > 1 ? ' ' + r.exwdOffc.n + '건' : '') + '</span>' : '');
  }
  function ofName(r) {
    if (!r) return '';
    if (!r.noAddr) return short(r.address);
    const x = r.exwd[r.exwd.length - 1] || {};
    return (x.exName || '거래소') + ' ' + (x.sym || '') + ' 출금(받는 주소 미상)';
  }
  function exwdBox(r) {
    if (!r.exwd || !r.exwd.length) return '';
    const EXW = { expired: '창 안에 내 지갑·거래소 도착 기록이 없어요', external: '외부로 판정해 둔 주소예요' };
    return '<div class="blk" style="margin-bottom:12px"><div class="ttl">거래소 출금 ' + r.exwdN + '건</div>' + r.exwd.slice(-6).reverse().map(x =>
      '<div class="kv" style="font-size:13px;align-items:flex-start"><span class="num">' + esc(fmtTs(x.ts).slice(5)) + '</span><span style="margin-left:0;flex:1;min-width:0;color:var(--text2);font-weight:500;overflow-wrap:anywhere">'
      + esc(x.exName) + ' → ' + (x.addr ? '<span class="mono">' + esc(short(x.addr)) + '</span>' : '<b>받는 주소 미상</b>') + ' · <span class="num">' + q(x.qty) + '</span> ' + esc(x.sym)
      + (x.net ? ' · ' + esc(x.net) + ' 네트워크' : '')
      + '<span class="cap" style="display:block">' + esc(EXW[x.why] || '') + (x.txid ? ' · txid <span class="mono">' + esc(short(x.txid)) + '</span>' : ' · txid 없음') + '</span></span>'
      + (x.txid ? '<button class="cpy" data-a="copy" data-v="' + esc(x.txid) + '" aria-label="txid 복사">' + IC.copy + '</button>' : '') + '</div>').join('') + '</div>';
  }
  function trTip(t) {
    const mins = Math.max(1, Math.round((Date.now() / 1000 - num(t.since)) / 60));
    return (t.from || '거래소') + ' → ' + (t.to || '도착지 확인 중') + (t.net ? ' · ' + t.net : '') + ' · ' + (mins < 120 ? mins + '분째' : Math.round(mins / 60) + '시간째')
      + (t.own ? ' · 내 계정으로 이동 중' : '') + (t.cover ? ' · 받는 쪽 기록 확인 중' : '') + ' — 도착이 기록되면 도착한 곳 보유로 바뀌어요';
  }
  function trChip(trs, name, inBtn) {
    const l = Array.isArray(trs) ? trs.filter(Boolean) : (trs ? [trs] : []);
    if (!l.length) return '';
    const tip = l.map(trTip).join(' / ');
    if (inBtn) return ' <span class="pill a sm" title="' + esc(tip) + '">전송 중' + (l.length > 1 ? ' ' + l.length : '') + '</span>';
    if (/전송 중/.test(String(name || ''))) return ' <button class="tipb" data-a="tipShow" data-v="' + esc(tip) + '" title="' + esc(tip) + '" aria-label="전송 중 설명">' + IC.info + '</button>';
    return ' <button class="pill a sm tipc" data-a="tipShow" data-v="' + esc(tip) + '" title="' + esc(tip) + '">전송 중' + (l.length > 1 ? ' ' + l.length : '') + '</button>';
  }
  function ofChains(r) { return r.chainNames.map((c, i) => '<span class="pill g sm">' + esc(c) + '</span>').join(' '); }
  function ofToks(r, n) {
    return r.tokens.slice(0, n || 3).map(t => '<span class="tk">' + icon(t.sym, 'xs', D0().symLogo[t.sym.toUpperCase()] || {}) + '<span class="num">' + q(t.qty) + '</span> ' + esc(t.sym) + impChip(t) + '</span>').join('') + (r.tokens.length > (n || 3) ? '<span class="cap">외 ' + (r.tokens.length - (n || 3)) + '</span>' : '')
      + (r.phantomN ? '<span class="cap" title="보유한 적 없는 토큰의 전송 로그(주소 오염) — 가치 0">사칭 토큰 ' + r.phantomN + '개 접음</span>' : '');
  }
  function vOutflows() {
    const D = S.D;
    if (!D.hasOF) return '<div class="card empty" style="margin-top:12px"><div class="eic">' + IC.tab.outflows + '</div><b>보낸 내역을 아직 만들지 못했어요</b>첫 수집이나 화면 계산(빌드)이 끝나면, 내가 외부 주소로 보낸 전송을 받는 주소별로 모아 내 지갑 · 거래소 입금 주소 · 외부 유출 중 무엇인지 정리할 수 있어요.<br>몇 분이 지나도 이 화면이면 <b>설정 › 상태 패널</b>에서 수집기(tj-core)와 화면(tj-web)이 돌고 있는지 확인하세요.</div>';
    const sh = S.of.showHidden;
    const val = r => (r.sendKnown ? r.usdAtSend : 0) || r.usdNow;
    const pendAll = D.of.filter(r => r.bucket === 'pending'), pend = (sh ? pendAll : D.ofPend.concat(D.ofBrU)).slice().sort((a, b) => val(b) - val(a) || b.lastTs - a.lastTs);
    const resAll = D.of.filter(r => r.bucket !== 'pending'), res = sh ? resAll : resAll.filter(r => r.bucket !== 'spam');
    const ext = resAll.filter(r => r.bucket === 'external' && !ofIsSale(r)), mine = resAll.filter(r => r.bucket === 'own' || r.bucket === 'exchange'), spam = resAll.filter(r => r.bucket === 'spam');
    const sendV = r => (r.sendKnown ? r.usdAtSend : 0);
    const capPend = (D.ofPend.length ? (D.ofBrU.length ? '미확인 ' + D.ofPend.length + '곳 ' : '') + (D.ofPendTr ? '<span title="돈 흐름 추적이 끝난 ' + D.ofPendTr + '곳은 추적 뒤 순유출(행 머리와 같은 값), 나머지는 보낸 값 − 되돌려 받음">순유출(추적 반영) ' : '순유출 ') + m(D.ofPendUsd, { compact: true }) + (D.ofPendTr ? '</span>' : '') : (D.ofPendN ? '' : '모두 정리됐어요')) + (D.ofBrU.length ? (D.ofPend.length ? ' · ' : '') + '브릿지 미추적 ' + D.ofBrU.length + '곳 포함' : '') + (D.ofRet.length ? ' · 되돌려 받음 ' + D.ofRet.length + '곳 별도' : '');
    const capExt = !ext.length && D.ofPendN ? '아직 확정한 곳 없음 · 확인 필요에서 정하면 여기로' : ext.length + '곳' + (ext.some(r => r.returnedUsd || r.linkTokenUsd) ? ' · 순유출 ' + m(sum(ext, ofNetV), { compact: true }) : '') + ' · 평가금액 ' + m(sum(ext, r => r.usdNow), { compact: true });
    const capMine = mine.length + '곳 · 자산에서 빠지지 않음', capSpam = '실제 유출 아님 · 자동 분류 · 숨김';
    const osOpen = uiOpen('ofsum', false);
    const sums = '<div class="card ofs1"><div class="ucells ofcells">'
      + uiCell('확인 필요', '<span class="' + (D.ofPendN ? 'wtxt' : 'oktxt') + '">' + D.ofPendN + '곳</span>', 'ofView', 'pending', plainT(capPend))
      + uiCell('외부 유출 확정', ext.length ? m(sum(ext, sendV), { compact: true }) : '<span class="mut">없음</span>', 'ofView', 'history', plainT(capExt))
      + uiCell('내 지갑 · 거래소', m(sum(mine, sendV), { compact: true }), 'ofView', 'history', capMine)
      + uiCell('사칭·스팸 <span class="mut">(숨김)</span>', spam.length + '곳', 'ofHidden', null, capSpam) + '</div>'
      + '<div class="jscap"><span class="cap num">' + (capPend ? capPend.split(' · ')[0] : capMine) + '</span><button type="button" class="link jsmore" data-a="uiFold" data-v="ofsum" aria-expanded="' + osOpen + '">' + (osOpen ? '접기' : '자세히') + UI_CHEV + '</button></div>'
      + (osOpen ? clps('uf:ofsum', '<div class="jsdl">' + [['확인 필요', capPend || '—'], ['외부 유출 확정', capExt], ['내 지갑 · 거래소', capMine], ['사칭·스팸 로그', spam.length + '곳 · ' + capSpam]].map(x => '<div class="jsr"><span class="k">' + x[0] + '</span><span class="v num">' + x[1] + '</span></div>').join('') + '</div>') : '') + '</div>';
    const nSale9 = D.of.filter(ofIsSale).length;
    const waitBar = nSale9 && D.ofWait.length ? '<div class="ofwait"><i class="wd"></i><span class="l">세일 참가 · 회수 대기</span><b class="num">' + D.ofWait.length + '건' + (D.ofWait.length ? ' ' + m(sum(D.ofWait, r => r.saleWait), { compact: true }) : '') + '</b>'
      + '<span class="cap">총자산에는 안 들어가요</span><button class="lnk" data-a="ofWaitGo">세일 참가금만 보기</button>'
      + '<button class="lnk mut" data-a="ofSaleAlert" aria-pressed="' + D.saleAlert + '" title="연결할 후보가 생기면 텔레그램으로 알려요">' + (D.saleAlert ? '후보 알림 켬' : '후보 알림 꺼짐') + '</button></div>' : '';
    const nHid = D.ofHidden.length, nDust = D.of.filter(r => r.dustPoison).length;
    const hidChip = nHid ? uiHidChip(nHid, 'ofHidden', sh, '자동으로 숨긴 전송 ' + nHid + '곳' + (spam.length ? ' · 사칭 토큰 로그 ' + spam.length : '') + (nDust ? ' · 소액·주소 오염 ' + nDust : '') + (sh ? ' — 누르면 다시 숨겨요' : ' — 누르면 목록에 함께 보여요')) : '';
    const seg = '<div class="stw"><div class="subtabs" role="tablist">' + [['pending', '확인 필요', pend.length], ['history', '정리됨', res.length]].concat(D.wdDest.length ? [['wdest', '출금 받은 주소', D.wdDestN]] : []).map(t => '<button role="tab" aria-selected="' + (S.of.view === t[0]) + '" class="' + (S.of.view === t[0] ? 'on' : '') + '" data-a="ofView" data-v="' + t[0] + '"' + (t[0] === 'history' ? ' title="정리된 내역"' : t[0] === 'wdest' ? ' title="거래소 출금 받은 주소"' : '') + '>' + t[1] + '<span class="n">' + t[2] + '</span></button>').join('') + '</div>'
      + (!nSale9 ? '<button class="pill g sm ofsl0" data-a="ofWaitGo" title="세일에 넣은 전송을 외부 → 세일 참가금으로 고르면 여기 모여요">세일 참가금 0</button>'
        : !D.ofWait.length ? '<button class="pill g sm ofsl0" data-a="ofWaitGo" title="세일 참가금 ' + nSale9 + '건 — 회수 대기 0건(모두 받은 것과 연결됨) · 총자산에는 안 들어가요">세일 참가금 <span class="pvx">' + nSale9 + '</span></button>' : '') + hidChip + '</div>';
    const head = '<div class="ofhd"><div class="cap">어디로 보냈는지 정하면 총자산·손익이 정확해져요</div></div>';
    let body;
    const ocb = offcAsk() + offcGroup();
    if (S.of.view === 'history') body = ofHistory(res);
    else if (S.of.view === 'wdest') body = wdDestHTML();
    else body = pend.length ? uiPaged('ofp', pend, r => ofCard(r), { unit: '곳' })
      : preData() ? '<div class="card empty"><div class="eic">' + IC.info + '</div><b>아직 수집 전이에요</b>첫 수집이 끝나면 외부로 나간 전송을 여기서 정리할 수 있어요</div>'
      : '<div class="card empty"><div class="eic">' + IC.check + '</div><b>확인할 전송이 없어요</b>외부로 나간 전송은 모두 정리됐어요</div>';
    return head + waitBar + sums + ocb + seg + body + ofSheet();

  }

  const ofIsSale = r => r.bucket === 'external' && r.category === '세일 참가금';
  const ofNm = r => { const t = String((r && (r.alias || r.memo)) || '').trim().slice(0, 40); if (!t || t === short(r.address)) return '';
    return ownH(t, r.alias ? 'w' : 'm'); };
  function mAlt(usd, o) { const c = S.cur; S.cur = c === 'USD' ? 'KRW' : 'USD'; try { return m(usd, o); } finally { S.cur = c; } }
  function ofChips(r, hist) {
    const look = r.flags.find(f => f.kind === 'lookalike'), v = OF_VERDICT[r.bucket];
    const chips = [];
    if (r._opt) chips.push(['w', '반영 중', '저장했어요 · 서버가 다시 계산하면 금액·상태가 그 값으로 바뀌어요']);
    const saleAuto = r.bucket === 'exchange' && r.autoMatch && arr(r.autoMatch.basis).indexOf('sale') >= 0;
    if (hist && v) chips.push(saleAuto ? ['a', '토큰 세일 입찰', '토큰 세일(경매) 입찰 자동 인식 · 받은 토큰이 입찰액을 원가로 이어받아요'] : [v[1], v[0], (r.matched ? (r.bucket === 'bridge' ? '브릿지 → 내 지갑 · ' : '거래소 입금 · ') + plainT(ofAutoTxt(r)) : r.retOk ? '되돌려 받음 · 흐름 추적으로 확인' : v[0]) + (r.category ? ' · ' + ofCatLbl(r.category) : '') + (r.alias ? ' · ' + r.alias : '') + (r.exchange ? ' · ' + (EX_NAMES[r.exchange] || r.exchange) : '')]);
    if (!hist) {
      if (look) chips.push(['e', '사칭 의심', '주소 오염(사칭) 의심 — 펼쳐서 확인']);
      if (r.applyWait) chips.push(['a', '곧 자동으로 수집 시작', '내 지갑으로 등록했어요 · 약 30초 안에 수집기가 자동으로 다시 시작하면 내 지갑 간 이동으로 바뀌어요']);
      else if (r.applying) chips.push(['w', '적용 중', '판정을 반영하는 중']);
      if (r.saleWait > 0) chips.push(['w', '회수 대기', '세일 참가 · 받은 것과 연결 전']);
      if (r.suggest && r.suggest.label) chips.push(['w', String(r.suggest.label), '제안 — 펼쳐서 확인']);
      if (r.flow && r.flow.score.level === 'high') chips.push(['ok', '내 지갑일 듯', '돈 흐름: 이 주소가 내 지갑일 가능성 높음 · 근거 ' + r.flow.score.n]);
      if (r.brU) chips.push(['a', '브릿지 미추적', '알려진 브릿지 → 추적 안 하는 체인']);
      if (!r.verdict && !r.hints.length && !chips.length && !r.exwd.length) chips.push(['g', '모르는 주소', '아직 어떤 주소인지 정하지 않았어요']);
    }
    if (r.exwd && r.exwd.length) { const ex = r.exwd.map(x => x.exName).filter((x, i, a) => x && a.indexOf(x) === i); chips.push(['a', ex.join('·') + ' 출금' + (r.exwdN > 1 ? ' ' + r.exwdN + '건' : ''), r.exwdOffc ? '오프체인 ' + r.exwdOffc.n + '건 포함 — 거래소 사용자끼리 체인 밖 이체' : '거래소 출금']); }
    if (!chips.length && r.hints.length) { const h0 = r.hints[0]; chips.push(h0.kind === 'burn' ? ['g', '발행·소각 주소', String(hs(h0.label))] : h0.chip ? ['ok', String(hs(h0.chip)), String(hs(h0.label))] : ['ok', String(hs(h0.label)), '알려진 주소']); }
    chips.forEach(c => { const mm = /^(.+?) 입금으로 자동 매칭\(근거: [^)]*\) · (\d+\/\d+)건/.exec(c[1]); if (mm) { c[2] = c[1]; c[1] = mm[1] + ' 입금 자동 매칭 · ' + mm[2] + '건'; } });
    return chips;
  }
  function ofCard(r, hist) {
    if (ofIsSale(r)) return ofSaleCard(r);
    const open = S.of.open.has(r.address);
    const look = r.flags.find(f => f.kind === 'lookalike');
    const fs = r.flow && ['queued', 'scanning', 'timeout', 'error'].indexOf(r.flow.status) >= 0 ? flowWait(r.flow) : '';
    const chips = ofChips(r, hist);
    const c0 = chips[0], chipTip = chips.map(c => c[1] + (c[2] && c[2] !== c[1] ? ' — ' + c[2] : '')).join('\n');
    const myH = r.hints.length && r.hints[0].kind === 'my_wallet' ? String(hs(r.hints[0].label)) : null, c0nm = !!(c0 && myH && c0[1] === myH);
    const chipNm = (hist && !!r.alias) || chips.some(c => myH && c[1] === myH);
    const chip = c0 ? '<span class="pill ' + c0[0] + ' sm"' + (chipNm ? ' data-pvl="w"' : '') + ' title="' + esc(chipNm ? locNameM(ownScrubM(chipTip, true)) : chipTip) + '">' + (c0nm ? ownH(String(hs(r.hints[0].label, 0, 1))) : esc(c0[1])) + (chips.length > 1 ? ' <span class="pvx">+' + (chips.length - 1) + '</span>' : '') + '</span>' : '';
    const dates = r.first === r.last ? r.last : (r.first + ' ~ ' + r.last);
    const nm = r.special ? (r.address === 'multi' ? '여러 주소' : '주소 특정 불가') : r.noAddr ? '받는 주소 미상' : (look ? shortL(r.address) : short(r.address));
    const nmU = !r.special && !r.noAddr && !look ? ofNm(r) : '';
    const netTxt = ofTraced(r) ? '순유출 ' + m(ofNetV(r), { compact: true })
      : (r.returnedUsd || r.linkTokenUsd) && (!r.linkTokenUsd || num(r.netUsd) >= 0.5) ? '순유출 ' + m(Math.max(0, num(r.netUsd)), { compact: true })
      : r.sendKnown && r.usdAtSend ? '지금 ' + m(r.usdNow, { compact: true }) : '평가금액 · 보낼 때 —';
    const amtTip = (fs ? fs.replace(/ · 마지막 시도.*$/, '') + ' · ' : '') + (r.sendKnown && r.usdAtSend ? '보낼 때 ' + m(r.usdAtSend) + ' · 지금 ' + m(r.usdNow) : '평가금액 ' + m(r.usdNow) + ' · 보낼 때 값 모름')
      + (ofTraced(r) ? ' · 추적 뒤 순유출 ' + m(ofNetV(r)) + ' = ' + (r.flow.held ? '보냄 − 돌려받음(직접·경유·거래소) · 남의 돈이 섞인 주소라 받은 곳 보유는 빼지 않았어요' : '보냄 − 돌려받음(직접·경유·거래소) − 거기 남음') + ' · 확인 필요 합계도 이 값' : '')
      + (r.returnedUsd ? ' · 되돌려 받음 ' + m(r.returnedUsd) : '') + (r.linkTokenUsd ? ' · 토큰으로 받음 ' + m(r.linkTokenUsd) : '');
    return '<div class="card of' + (open ? ' open' : '') + '" data-anc="outflow:' + esc(r.address) + '"><div class="oh" role="button" tabindex="0" data-a="ofTog" data-k="' + esc(r.address) + '" aria-expanded="' + open + '">'
      + '<div class="who">' + ofIcon(r) + '<div class="w2"><div class="l1">' + (nmU ? '<b class="ofnm ell" title="' + esc(r.address) + '">' + nmU + '</b>' : '<span class="addr"' + (r.special || r.noAddr ? ' style="font-family:inherit"' : '') + ' title="' + esc(r.noAddr ? '받는 주소 미상 — 거래소 출금 기록에 주소가 없어요' : r.address) + '">' + esc(nm) + '</span>') + '</div>'
      + '<div class="sub l2">' + chip + '<span class="ell">' + (nmU ? '<span class="mono">' + esc(nm) + '</span> · ' : '') + esc(r.chainNames.join(' · ')) + ' <span class="num">· ' + r.count + '건 · ' + esc(dates) + '</span>' + (r.memo && !(nmU && !r.alias) ? ' · ' + prTxt(r.memo, 'ofmm') : '') + '</span></div></div></div>'
      + '<div class="toks">' + ofToks(r) + '</div>'
      + '<div class="amt" title="' + esc(amtTip + (netTxt ? ' · ' + plainT(netTxt) : '')) + '"><b class="num">' + m(r.sendKnown && r.usdAtSend ? r.usdAtSend : r.usdNow, { compact: true }) + '</b><span class="cap num">' + ofAmtSub(r) + (fs && /안 끝|실패/.test(fs) ? ' <span class="wtxt">· ' + esc(fs.replace(/ · 마지막 시도.*$/, '')) + '</span>' : '') + '</span></div>'
      + '<span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></div>'
      + (open ? clps('of:' + r.address, ofBody(r, hist)) : '') + '</div>';
  }
  function ofAmtSub(r) {
    if (!(r.sendKnown && r.usdAtSend)) return '평가금액 · 보낼 때 —';
    const a = mAlt(r.usdAtSend, { compact: true }), now = num(r.usdNow), sd = num(r.usdAtSend);
    return '<span class="num">' + a + '</span>' + (sd > 0 && Math.abs(now - sd) > sd * 0.1 ? ' <span class="mut">· 지금 ' + mN(now, { compact: true }) + '</span>' : '');
  }
  const EXPL = { sol: ['https://solscan.io/tx/', 'https://solscan.io/account/'], eth: ['https://etherscan.io/tx/', 'https://etherscan.io/address/'],
    base: ['https://basescan.org/tx/', 'https://basescan.org/address/'], bsc: ['https://bscscan.com/tx/', 'https://bscscan.com/address/'],
    arbitrum: ['https://arbiscan.io/tx/', 'https://arbiscan.io/address/'], optimism: ['https://optimistic.etherscan.io/tx/', 'https://optimistic.etherscan.io/address/'],
    polygon: ['https://polygonscan.com/tx/', 'https://polygonscan.com/address/'], zksync: ['https://era.zksync.network/tx/', 'https://era.zksync.network/address/'],
    scroll: ['https://scrollscan.com/tx/', 'https://scrollscan.com/address/'], gnosis: ['https://gnosisscan.io/tx/', 'https://gnosisscan.io/address/'],
    hyperevm: ['https://hyperevmscan.io/tx/', 'https://hyperevmscan.io/address/'] };
  const EXPL_NX = { tron: ['https://tronscan.org/#/transaction/', ''], sui: ['https://suiscan.xyz/mainnet/tx/', 'https://suiscan.xyz/mainnet/account/'],
    ton: ['https://tonviewer.com/transaction/', ''], btc: ['https://mempool.space/tx/', ''] };
  const exUrl = (chain, id, addr) => { if (S.rand) return ''; if (EXPL_NX[chain]) { const p = EXPL_NX[chain][addr ? 1 : 0], t = chain === 'ton' && !addr ? String(id).split('.').pop() : id; return p ? p + encodeURIComponent(t) : ''; }
    const e = EXPL[chain] || (String(id).indexOf('0x') === 0 ? EXPL.eth : EXPL.sol); return e[addr ? 1 : 0] + encodeURIComponent(id); };
  const exLink = (chain, id, addr, txt) => { const u = exUrl(chain, id, addr); return u ? '<a class="fx-l" href="' + esc(u) + '" target="_blank" rel="noopener noreferrer" title="' + esc((addr ? '주소' : 'tx') + ' 탐색기에서 보기') + '">' + (txt || esc(short(id))) + '</a>' : '<span class="fx-l">' + (txt || esc(short(id))) + '</span>'; };
  const FL_KIND = { lookmine: ['ok', '내 지갑일 가능성 높음'], mine: ['ok', '내 지갑'], exchange: ['a', '거래소 입금 주소'], bridge: ['a', '브릿지'], contract: ['g', '컨트랙트'],
    eoa: ['w', '모르는 주소'], unknown: ['g', '주소 특정 불가'], self: ['g', '같은 주소 · 다른 체인'], burn: ['g', '발행·소각 주소'] };
  const coinsTxt = (cs, n) => cs.slice(0, n || 3).map(c => '<span class="num">' + q(c.qty) + '</span> ' + esc(c.sym)).join(' · ') + (cs.length > (n || 3) ? ' 외 ' + (cs.length - (n || 3)) + '종' : '');
  const dRange = (a, b) => { const x = a ? fmtTs(a).slice(0, 5) : '', y = b ? fmtTs(b).slice(0, 5) : ''; return x === y ? x : x + ' ~ ' + y; };
  function flowWait(f) {
    const now = Date.now() / 1000, el = f.scanSince > 0 ? now - f.scanSince : 0;
    const why = f.scanWhy === 'paused' ? '탐색기 한도로 쉬는 중' : f.scanWhy === 'budget' ? '호출 한도만큼씩 나눠 읽는 중' : f.scanWhy === 'error' ? '조회 오류' : '';
    if (f.status === 'timeout') return '흐름 조회가 ' + (el >= 3600 ? Math.floor(el / 3600) + '시간째' : '오래') + ' 안 끝났어요' + (why ? ' · ' + why : '') + (f.lastTry > 0 ? ' · 마지막 시도 ' + ago(f.lastTry) : '');
    if (f.status === 'error') return '흐름 조회 실패 — 잠시 뒤 다시 시도해요' + (f.lastTry > 0 ? ' · 마지막 시도 ' + ago(f.lastTry) : '');
    if (f.status === 'scanning') return '흐름 조회 중…' + (el >= 600 ? ' ' + (el >= 3600 ? Math.floor(el / 3600) + '시간' : Math.floor(el / 60) + '분') + '째' : '');
    return '흐름 조회 대기';
  }
  function flowRecip(r, x) {
    const k = r.address + '|' + x.addr, open = S.of.fr.has(k), fk = FL_KIND[x.kind] || FL_KIND.eoa;
    const ch = x.chains[0] || (r.chains[0] || '');
    const chip = '<span class="pill ' + fk[0] + ' sm">' + esc(x.kind === 'lookmine' ? fk[1] + ' · 근거 ' + x.score.n : (x.kind === 'eoa' && x.score.level === 'mid' ? '내 지갑 근거 ' + x.score.n + '건' : (x.label || fk[1]))) + '</span>';
    const brg = x.bridge ? '<span class="pill a sm">' + esc('브릿지 · ' + (x.bridge.name || '') + (x.bridge.dst ? ' → ' + (CHAIN_KO[x.bridge.dst] || x.bridge.dst) : '')) + '</span>' : '';
    const via = x.via > 0 ? '<div class="sub oktxt">그중 <b class="num">' + m(x.via, { compact: true }) + '</b> 는 나중에 이 주소에서 내 지갑·거래소로 돌아왔어요</div>' : '';
    const addr = x.addr === '?' ? '<span class="mut">받는 주소 특정 불가</span>' : exLink(ch, x.addr, true, '<span class="mono">' + esc(short(x.addr)) + '</span>') + '<button class="cpy" data-a="copy" data-v="' + esc(x.addr) + '" aria-label="주소 복사">' + IC.copy + '</button>';
    const head = '<div class="fr" role="button" tabindex="0" data-a="flowRec" data-k="' + esc(k) + '" aria-expanded="' + open + '"><i class="fr-d k-' + esc(x.kind) + '"></i>'
      + '<div class="fr-m"><div class="fr-t">' + addr + chip + brg + '</div>'
      + '<div class="sub">' + coinsTxt(x.coins) + ' · <span class="num">' + esc(dRange(x.first, x.last)) + ' · ' + x.n + '건</span>' + (x.chains.length ? ' · ' + x.chains.map(c => esc(CHAIN_KO[c] || c)).join('·') : '') + '</div>' + via + '</div>'
      + '<div class="fr-v"><b class="num">' + (x.approx ? '≈' : '') + m(x.usd, { compact: true }) + '</b><span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></div></div>';
    if (!open) return head;
    const ev = x.score.ev.length ? '<div class="fr-ev"><div class="lab">' + (x.score.level === 'high' ? '내 지갑일 가능성 높음' : x.score.level === 'mid' ? '내 지갑 근거 1건' : '내 지갑 근거 없음') + '</div>'
      + x.score.ev.map(e => '<div class="fr-e">' + IC.check.replace('<svg', '<svg width="14" height="14"') + '<span>' + esc(hs(e.t, 1)) + '</span></div>').join('') + '</div>'
      : (x.base === 'eoa' ? '<div class="fr-ev"><div class="lab">내 지갑 근거 없음</div><div class="cap">내 지갑과 주고받은 기록이 없어요 — 남에게 보낸 돈이거나, 아직 등록 안 된 다른 지갑일 수 있어요</div></div>' : '');
    const txs = x.txs.map(t => '<div class="kv fr-tx"><span class="num">' + esc(fmtTs(t.ts)) + '</span><span class="ell" style="margin-left:0;flex:1;color:var(--text2);font-weight:500">' + esc(CHAIN_KO[t.chain] || t.chain) + ' · <span class="num">' + q(t.qty) + '</span> ' + esc(t.sym) + '</span><span class="num">' + (t.usd != null ? m(t.usd) : '—') + '</span>' + exLink(t.chain, t.tx, false, IC.ext || '↗') + '</div>').join('');
    const reg = x.registerable && x.addr !== '?' ? '<div class="frm"><button class="btn sm' + (x.kind === 'lookmine' ? ' pri' : '') + '" data-a="flowReg" data-k="' + esc(x.addr) + '" data-v="' + esc(r.address) + '">' + IC.wallet + ' 내 지갑으로 등록</button><span class="cap">등록하면 과거 내역을 채우고 이 흐름이 내 지갑 이동으로 정리돼요</span></div>' : '';
    return head + '<div class="fr-b">' + ev + (txs ? '<div class="fr-txs">' + txs + '</div>' : '') + reg + '</div>';
  }
  function flowPanel(r) {
    const f = r.flow;
    if (!f) return '';
    const pend = f.status === 'queued' || f.status === 'scanning' || f.status === 'timeout' || f.status === 'error';
    const sc = f.score.level !== 'none' ? '<span class="pill ' + (f.score.level === 'high' ? 'ok' : 'w') + ' sm" title="' + esc(f.score.ev.map(e => hs(e.t, 1)).join(' · ')) + '">이 주소: ' + (f.score.level === 'high' ? '내 지갑일 가능성 높음' : '내 지갑 근거 1건') + ' · 근거 ' + f.score.n + '</span>' : '';
    const head = '<div class="fl-h"><div class="h3">돈 흐름</div><span class="cap">' + (f.status === 'timeout' || f.status === 'error' ? esc(flowWait(f)) : pend ? (f.status === 'scanning' ? '공개 탐색기로 조회 중이에요 — 몇 분 뒤 채워져요' + (f.scanSince > 0 && Date.now() / 1000 - f.scanSince >= 600 ? ' (' + esc(flowWait(f).replace('흐름 조회 중… ', '')) + ')' : '') : '조회 대기 중 — 백그라운드에서 곧 읽어요') : '보낸 뒤 이 주소가 돈을 어디로 보냈는지' + (f.scannedAt ? ' · ' + esc(fmtTs(f.scannedAt)) + ' 조회' : '')) + '</span><span class="sp"></span>' + sc + '</div>';
    const unex = f.unexplained;
    const segs = [['r', f.returned.usd], ['k', f.still.usd], ['e', f.elsewhere.usd], ['u', Math.max(0, unex)]];
    const tot = Math.max(f.sent, segs.reduce((a, b) => a + Math.max(0, b[1]), 0)) || 1;
    const bar = pend ? '' : '<div class="fl-bar" aria-hidden="true">' + segs.filter(x => x[1] > 0).map(x => '<i class="' + x[0] + '" style="width:' + Math.max(0.8, x[1] / tot * 100).toFixed(2) + '%"></i>').join('') + '</div>';
    const tile = (c, l, v, sub) => '<div class="fl-t"><div class="l"><i class="fs-d ' + c + '"></i>' + l + '</div><div class="v num">' + v + '</div>' + (sub ? '<div class="cap num">' + sub + '</div>' : '') + '</div>';
    const rsub = [f.returned.direct > 0 ? '직접 ' + mN(f.returned.direct, { compact: true }) : '', f.returned.hop > 0 ? '경유 ' + mN(f.returned.hop, { compact: true }) : '', f.returned.exchange > 0 ? '거래소 ' + mN(f.returned.exchange, { compact: true }) : '', f.returned.bridge > 0 ? '브릿지 ' + mN(f.returned.bridge, { compact: true }) : ''].filter(Boolean).join(' · ');
    const tiles = '<div class="fl-k">' + tile('s', '보냄', m(f.sent, { compact: true }), r.count + '건')
      + tile('r', '돌려받음', m(f.returned.usd, { compact: true }), rsub || '내 지갑·거래소로')
      + (pend ? '' : (f.held ? tile('k', '받은 곳 보유', mN(f.still.usd, { compact: true }), '내 통제 아님 · 순유출에 포함' + (f.still.all - f.still.usd > 0.5 ? ' · 받은 주소 전체 ' + mN(f.still.all, { compact: true }) : ''))
          : tile('k', '거기 남음' + (f.still.all - f.still.usd > 0.5 ? ' · 내 몫' : ''), mN(f.still.usd, { compact: true }), f.still.all - f.still.usd > 0.5 ? '받은 주소 전체 ' + mN(f.still.all, { compact: true }) : f.still.items.length ? coinsTxt(f.still.items, 2) : '잔고 없음'))
        + tile('e', '다른 곳으로' + (f.elsewhere.all - f.elsewhere.usd > 0.5 ? ' · 내 몫' : ''), mN(f.elsewhere.usd, { compact: true }), (f.elsewhere.all - f.elsewhere.usd > 0.5 ? '받은 주소 전체 ' + mN(f.elsewhere.all, { compact: true }) + (f.elsewhere.n ? ' · ' + f.elsewhere.n + '곳' : '') : f.elsewhere.n ? f.elsewhere.n + '곳' + (f.elsewhere.lookMine > 0 ? ' · 그중 내 지갑 같음 ' + mN(f.elsewhere.lookMine, { compact: true }) : '') : '없음'))
        + tile('u', Math.abs(unex) < Math.max(1, f.sent * 0.005) ? '설명 안 됨' : unex < 0 ? '가격 변화·기존 잔고' : '설명 안 됨', mN(unex, { compact: true, sign: unex < 0 }), Math.abs(unex) < Math.max(1, f.sent * 0.005) ? '거의 다 설명됨' : unex < 0 ? (f.returned.usd > f.sent ? '보낸 것보다 더 돌아왔어요' : '돌아오고 남은 게 보낸 것보다 많아요') : '스왑 손익·수수료·조회 밖')) + '</div>';
    const rc = f.recips;
    const faOpen = !f.capped || S.of.fa.has(r.address), nAll = Math.max(rc.length, f.elsewhere.n);
    const list = pend ? '' : rc.length ? (f.capped
      ? '<div class="fl-s"><button class="ttl fl-fa" data-a="flowAll" data-k="' + esc(r.address) + '" aria-expanded="' + faOpen + '">차액이 간 곳 <span class="mut" style="font-weight:500">주소 전체 ' + nAll + '곳' + (rc.length < nAll ? ' · 큰 ' + rc.length + '곳' : '') + ' · 남의 돈과 섞여 내 돈이 간 곳과 다를 수 있어요</span><span class="chev' + (faOpen ? ' o' : '') + '">' + IC.chev + '</span></button>' + (faOpen ? rc.map(x => flowRecip(r, x)).join('') : '') + '</div>'
      : '<div class="fl-s"><div class="ttl">차액이 간 곳 <span class="mut" style="font-weight:500">' + rc.length + '곳 · 금액 큰 순</span></div>' + rc.map(x => flowRecip(r, x)).join('') + '</div>')
      : '<div class="fl-s"><div class="ttl">차액이 간 곳</div><div class="cap">이 주소에서 다른 곳으로 나간 전송이 없어요' + (f.mineN ? ' — 나간 돈은 모두 내 지갑으로 왔어요' : '') + '</div></div>';
    const sw = f.swaps.n ? '<div class="fl-s fl-sw"><div class="ttl">이 주소가 한 스왑 <span class="mut" style="font-weight:500">' + f.swaps.n + '건</span></div><div class="fl-swr"><span class="lab">판 것</span><span>' + coinsTxt(f.swaps.sold, 4) + '</span></div><div class="fl-swr"><span class="lab">산 것</span><span>' + coinsTxt(f.swaps.bought, 4) + '</span></div></div>' : '';
    const notes = f.notes.length ? '<div class="fl-n">' + f.notes.map(n => '<div>· ' + esc(hs(n, 1)) + '</div>').join('') + '</div>' : '';
    return '<section class="flw" aria-label="돈 흐름">' + head + tiles + bar + list + sw + notes + (pend ? '' : flowSpoof(r)) + '</section>';
  }
  function flowSpoof(r) {
    const h = r.flow && r.flow.spoofHidden, n = h ? num(h.n) : 0;
    if (!n) return '';
    const open = S.of.fsp.has(r.address), it = arr(h.items);
    const rows = open ? it.map(t => '<div class="kv fr-tx"><span class="num">' + esc(fmtTs(t.ts)) + '</span><span class="ell" style="margin-left:0;flex:1;color:var(--text2);font-weight:500">' + esc(CHAIN_KO[t.chain] || t.chain || '') + ' · ' + (t.dir === 'in' ? '받음' : '보냄') + ' <span class="num">' + q(t.qty) + '</span> ' + esc(t.sym) + (t.cp && t.cp !== '?' ? ' · ' + (t.dir === 'in' ? '보낸 곳 ' : '받는 곳 ') + '<span class="mono">' + esc(short(t.cp)) + '</span>' : '') + '</span>' + (t.tx ? exLink(t.chain, t.tx, false, IC.ext || '↗') : '') + '</div>').join('')
      + (n > it.length ? '<div class="cap">최근 ' + it.length + '건만 보여요</div>' : '') : '';
    return '<div class="fl-s"><button class="ttl fl-fa" data-a="flowSpoof" data-k="' + esc(r.address) + '" aria-expanded="' + open + '">숨긴 낚시 토큰 이동 ' + n + '건 <span class="mut" style="font-weight:500">사칭·격리 토큰의 가짜 전송 기록 · 금액·받은 곳에 안 넣어요</span><span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span></button>' + rows + '</div>';
  }
  const AIOP_V = { exchange: 'a', personal: 'g', contract: 'g', burn: 'g', poison: 'e', unknown: 'g' };
  const AIOP_KO = { exchange: '거래소 주소', personal: '개인 지갑', contract: '컨트랙트', burn: '소각 주소', poison: '사칭 의심', unknown: '모름' };
  function aiOpBox(o) {
    if (!o || typeof o !== 'object' || !o.st) return '';
    const head = t => '<div class="aiop-h">' + SXI.spark + '<b>AI 의견</b>' + t + '<span class="aiop-t pvx">참고용 · ' + esc(o.by || 'AI') + '</span></div>';
    if (o.st === 'ok') {
      const pv9 = typeof pvOn === 'function' && pvOn();
      const why = pv9 ? '<li>' + esc(AI_HIDE) + '</li>' : arr(o.why).map(w => '<li>' + esc(hs(String(w == null ? '' : w))) + '</li>').join('');
      return '<div class="aiop">' + head('<span class="pill ' + (AIOP_V[o.v] || 'g') + ' sm aib-l">' + esc(pv9 ? (AIOP_KO[o.v] || '모름') : (o.label || '모름')) + '</span>') + (why ? '<ul class="aib">' + why + '</ul>' : '')
        + '<div class="aiop-m pvx">확신 ' + esc(o.conf || '낮음') + (num(o.at) > 0 ? ' · ' + esc(fmtTs(num(o.at))) : '') + (o.old ? ' · 그 뒤 기록이 바뀌어 곧 다시 만들어요' : '') + ' · 판정·장부는 바꾸지 않아요</div></div>';
    }
    const msg = o.st === 'limit' ? '오늘 만들 수 있는 만큼 다 만들었어요 — 내일 이어서 만들어요' : o.st === 'fail' ? 'AI 의견을 못 만들었어요 — 기록이 바뀌면 다시 시도해요' : '만드는 중 — 백그라운드에서 한 곳씩 천천히 만들어요';
    return '<div class="aiop wait">' + head('') + '<div class="aiop-m pvx">' + msg + '</div></div>';
  }
  function ofBody(r, hist) {
    const warn = r.flags.map(f => {
      if (f.kind === 'lookalike') return '<div class="warnbox">' + IC.alert + '<div><b>주소 오염(사칭) 의심</b> — ' + (f.label ? ownH(f.label) : '내 주소') + ' <span class="mono">' + esc(shortL(f.similarTo)) + '</span> 와 앞 4자리·끝 4자리가 같은 다른 주소예요(이 주소 <span class="mono">' + esc(shortL(r.address)) + '</span>). 주소를 복사해 붙여 넣다 바뀌었다면 사기일 수 있어요.</div></div>';
      if (f.kind === 'spoof_token') return '<div class="hintbox">' + esc(hs(f.note)) + '</div>';
      return f.note ? '<div class="hintbox">' + esc(hs(f.note)) + '</div>' : '';
    }).join('');
    const hints = r.hints.length ? '<div class="hintbox"><b>알려진 주소</b> · ' + [...new Set(r.hints.map(h => (h.kind === 'my_wallet' ? ownH(String(hs(h.label, 0, 1))) : esc(String(hs(h.label))))))].join(' · ') + '</div>' : '';
    const sugs = (!hist || r.bucket === 'returned') && r.suggestions.length ? '<div class="hintbox"><b>이렇게 보여요 — 확인해 주세요</b>' + r.suggestions.map(x => '<div style="margin-top:4px">· <b>' + esc(x.label || '') + '</b>' + (x.exchange ? ' (' + esc(EX_NAMES[x.exchange] || x.exchange) + ')' : '') + (x.evidence ? ' — ' + esc(x.evidence) : '') + (x.action === 'register_own' && !r.verdict ? ' <button class="btn sm" data-a="ofOwnQuick" data-k="' + esc(r.address) + '">' + IC.wallet + ' 내 지갑으로 등록</button>' : '') + (x.action === 'mark_returned' && !hist ? ' <button class="btn sm pri" data-a="ofRetQuick" data-k="' + esc(r.address) + '">' + IC.undo + ' 되돌려 받음으로 정리</button>' : '') + '</div>').join('') + '</div>' : '';
    const arrs = r.arrivals.length ? '<div class="blk" style="margin-top:12px"><div class="ttl">브릿지 도착 · 내 지갑 ' + r.arrivalsN + '건</div>' + r.arrivals.slice(0, 8).map(t => '<div class="kv" style="font-size:13px"><span class="num">' + esc(fmtTs(t.ts).slice(5)) + '</span><span class="ell" style="margin-left:0;flex:1;color:var(--text2);font-weight:500">' + esc(CHAIN_KO[t.chain] || t.chain || '') + ' · ' + esc(short(t.wallet || '')) + ' · ' + q(num(t.qty)) + ' ' + esc(t.sym || '') + ' · ' + Math.max(0, Math.round(num(t.dt) / 60)) + '분 뒤</span>' + (t.tx ? '<button class="cpy" data-a="copy" data-v="' + esc(t.tx) + '" aria-label="txid 복사">' + IC.copy + '</button>' : '') + '</div>').join('') + '</div>' : '';
    const flowRet = r.flow && r.flow.returned ? num(r.flow.returned.usd) : 0, dirRet = num(r.returnedUsd);
    const retNet = (() => { if (!ofTraced(r)) return ' · 순유출 ' + m(num(r.netUsd));
      const sr = num(r.netUsd), still = num(r.flow.still.usd), tn = ofNetV(r);
      return ' · 보낸 − 직접 돌려받음 = <span title="' + esc(m(sr)) + '">' + m(sr, { compact: true }) + '</span>' + (still >= 0.5 && Math.abs(sr - still - tn) < 1 ? ' · 그중 거기 남음 ' + m(still, { compact: true }) : '') + ' · 추적 뒤 순유출 ' + m(tn, { compact: true }); })();
    const retVia = flowRet - dirRet >= 0.5 ? '<div class="cap num" style="margin:-2px 0 6px">위 돈 흐름의 돌려받음 ' + mN(flowRet, { compact: true }) + ' = 직접 ' + mN(dirRet, { compact: true }) + ' + 경유·거래소·브릿지 ' + mN(flowRet - dirRet, { compact: true }) + '</div>' : '';
    const nLk = r.returned.filter(t => t.linked && t.where).length, nDir = r.returnedN - nLk;
    const rets = r.returned.length ? '<div class="blk" style="margin-top:12px"><div class="ttl">' + (ofTraced(r) ? '직접 돌려받음 ' : '되돌려 받음 ') + m(r.returnedUsd) + retNet + ' <span class="mut" style="font-weight:500">' + (nDir > 0 ? '이 주소 → 내 지갑 ' + nDir + '건' : '') + (nLk ? (nDir > 0 ? ' · ' : '') + '연결한 환불 ' + nLk + '건' : '') + '</span></div>' + (ofTraced(r) ? retVia : '') + r.returned.slice(0, 8).map(t => '<div class="kv" style="font-size:13px"><span class="num">' + esc(String(t.t || fmtTs(t.ts)).slice(5)) + '</span><span class="ell" style="margin-left:0;flex:1;color:var(--text2);font-weight:500">' + esc(CHAIN_KO[t.chain] || t.chain || '') + ' · ' + q(num(t.qty)) + ' ' + esc(t.sym || '') + (t.linked ? ' · 연결한 환불' : '') + '</span><span class="num">' + (t.usd != null ? m(num(t.usd)) : '') + '</span>' + (t.tx ? '<button class="cpy" data-a="copy" data-v="' + esc(t.tx) + '" aria-label="txid 복사">' + IC.copy + '</button>' : '') + '</div>').join('') + '</div>' : '';
    const mT = v => S.mobile ? m(v, { compact: true }) : m(v);
    const sendCol = r.sendKnown && r.tokens.some(t => t.usdAtSend != null);
    const toks = '<div class="mini-tw"><table class="mini-t" style="margin-top:4px"><thead><tr><th scope="col">토큰</th><th scope="col">수량</th>' + (sendCol ? '<th scope="col">보낼 때</th>' : '') + '<th scope="col">지금</th></tr></thead><tbody>' + r.tokens.map(t => '<tr><td><span class="row gap8">' + icon(t.sym, 'xs', D0().symLogo[t.sym.toUpperCase()] || {}) + '<b>' + esc(t.sym) + '</b>' + impChip(t) + (t.airdrop ? '<span class="pill g sm" title="실매수 이력 없이 들어온 토큰이라 격리했어요(스캠 확증은 없음) — 총자산·손익에 넣지 않아요. 실제 자산이면 미매칭 › 숨긴 항목에서 복원">' + (S.mobile ? '에어드랍 의심' : '에어드랍 의심(격리)') + '</span>' : t.phantom ? '<span class="pill g sm">사칭 토큰</span>' : '') + '</span></td><td class="num">' + q(t.qty) + '</td>' + (sendCol ? '<td class="num">' + (t.usdAtSend == null || !r.sendKnown ? '<span class="mut">—</span>' : mT(t.usdAtSend)) + '</td>' : '') + '<td class="num">' + mT(t.usdNow) + '</td></tr>').join('') + '</tbody></table></div>';
    const tvs = r.txsV || r.txs, nTx = Math.max(0, r.count - num(r.phTxN));
    const txRow = t => '<div class="kv" style="font-size:13px"><span class="num">' + esc(String(t.t || fmtTs(t.ts)).slice(5)) + '</span><span class="ell" style="margin-left:0;flex:1;color:var(--text2);font-weight:500">' + esc(CHAIN_KO[t.chain] || t.chain || '') + ' · ' + q(num(t.qty)) + ' ' + esc(t.sym || '') + (t.quar === 'airdrop' ? ' <span class="pill g sm">에어드랍 의심(격리)</span>' : t.phantom ? ' <span class="pill g sm" title="보유한 적 없는 토큰의 전송 로그(주소 오염) — 가치 0 · 실제 유출 아님">사칭 토큰</span>' : '') + ofTxMatch(r, t) + '</span><span class="num">' + (t.usdAtSend != null ? m(num(t.usdAtSend)) : '') + '</span>' + (t.tx ? '<button class="cpy" data-a="copy" data-v="' + esc(t.tx) + '" aria-label="txid 복사">' + IC.copy + '</button>' : '') + '</div>';
    const txOmit = num(r.txsCut) > 0 ? Math.max(0, nTx - new Set(tvs.map((t, i) => (t && (t.tx || t.key)) || '#' + i)).size) : 0;
    const txCutNote = txOmit > 0 ? '<div class="cap" style="margin-top:6px">' + (tvs.length ? '그 전 ' : '최근 목록(사칭 토큰 전송)보다 전 ') + '<span class="num pvx">' + nf('ko-KR').format(txOmit) + '</span>건은 목록에서 생략 — 검색에서 날짜로 그날 기록 보기 · 합계·건수는 전 건 기준</div>' : '';
    const txs = tvs.length || txCutNote ? '<div class="blk" style="margin-top:12px"><div class="ttl">전송 ' + nTx + '건' + (tvs.length && tvs.length < nTx ? ' <span class="mut" style="font-weight:500">최근 ' + tvs.length + '건</span>' : '') + (r.phTxN ? ' <span class="cap pvx" style="font-weight:500" title="보유한 적 없는 토큰의 전송 로그(주소 오염) — 가치 0 · 실제 유출 아님">사칭 토큰 전송 ' + r.phTxN + '건 접음</span>' : '') + '</div>' + uiPaged('oftx:' + r.address, tvs, txRow, { unit: '건' }) + txCutNote + '</div>' : '';
    const addrRow = r.noAddr ? ''
      : '<div class="row gap8" style="margin-bottom:12px"><span class="mono" style="font-size:13px;word-break:break-all">' + esc(r.address) + '</span><button class="cpy" data-a="copy" data-v="' + esc(r.address) + '" aria-label="주소 복사">' + IC.copy + '</button></div>';
    const part = !hist && r.autoMatch && !r.verdict ? '<div class="hintbox"><b>일부 ' + ofAutoTxt(r) + '</b> · ' + num(r.autoMatch.matched) + '/' + num(r.autoMatch.of) + '건 · ' + esc(r.autoMatch.exchange || '') + ' <button class="btn sm" data-a="ofUndo" data-k="' + esc(r.address) + '">' + IC.undo + ' 자동 매칭 끄기</button>' + ofMatchedList(r) + '</div>' : '';
    const left = '<div style="min-width:0">' + warn + (hist ? '' : aiOpBox(r.aiOp)) + part + sugs + hints + addrRow + exwdBox(r) + '<div class="blk"><div class="ttl">보낸 토큰</div>' + toks + '</div>' + (r.exwdOnly ? '' : txs) + arrs + rets + '</div>';
    return '<div class="ob">' + (r.flow ? '<div class="ob-flow">' + flowPanel(r) + '</div>' : '') + left + '<div>' + (hist ? ofResolved(r) : ofActions(r)) + '</div></div>';
  }
  const OF_MATCH_SHORT = { txid: 'txid', amount_time: '수량·시간', address: '입금 주소', bridge: '브릿지 도착', hop_split: '경유 분할', roundtrip: '예치 왕복', sale: '세일 입찰' };
  function ofTxMatchTip(t) {
    const mt = t.match || {}, b = String(mt.basis || '');
    if (b === 'bridge') return '브릿지 → 내 지갑 도착' + (mt.chain ? ' · ' + (CHAIN_KO[mt.chain] || mt.chain) : '') + (mt.sym ? ' ' + mt.sym : '') + (num(mt.dt) > 0 ? ' · ' + (num(mt.dt) >= 3600 ? Math.round(num(mt.dt) / 360) / 10 + '시간' : Math.max(1, Math.round(num(mt.dt) / 60)) + '분') + ' 뒤' : '');
    return (OF_BASIS[b] || b || '자동 매칭') + (mt.exchange ? ' · ' + mt.exchange : '');
  }
  function ofTxMatch(r, t) {
    if (!r.autoMatch || !t || t.phantom || t.ex) return '';
    if (t.match && t.match.basis) return ' <span class="pill ok sm" title="' + esc(ofTxMatchTip(t)) + '">자동 매칭 · ' + esc(OF_MATCH_SHORT[t.match.basis] || '근거 있음') + '</span>';
    return ' <span class="pill g sm" title="이 전송은 짝(거래소 입금·브릿지 도착)을 못 찾았어요 — 확인 필요">매칭 안 됨</span>';
  }
  function ofMatchedList(r) {
    const mx = arr(r.txs).filter(t => t && t.match && t.match.basis && !t.phantom);
    if (!mx.length) return '';
    return '<div class="cap" style="margin-top:4px">매칭된 전송: ' + mx.slice(0, 3).map(t => esc(String(t.t || fmtTs(t.ts)).slice(5)) + ' ' + esc(CHAIN_KO[t.chain] || t.chain || '') + ' · <span class="num">' + q(num(t.qty)) + '</span> ' + esc(t.sym || '') + ' → ' + esc(ofTxMatchTip(t))).join(' / ') + (mx.length > 3 ? ' 외 ' + (mx.length - 3) + '건' : '') + ' · 나머지는 아래 목록의 \'매칭 안 됨\'</div>';
  }
  function ofResolved(r) {
    const v = OF_VERDICT[r.bucket] || ['정리됨', 'g', IC.check];
    return '<div class="done"><span class="aic ' + v[1] + '" style="width:32px;height:32px;border-radius:10px;display:grid;place-items:center">' + v[2].replace('<svg', '<svg width="17" height="17"') + '</span><div style="min-width:0"><b>' + v[0] + '</b><div class="cap">' + [r.alias ? ownH(r.alias) : '', r.exchange ? esc(EX_NAMES[r.exchange] || r.exchange) : '', r.category ? esc(ofCatLbl(r.category)) : ''].filter(Boolean).join(' · ') + (r.decidedTs ? ' · ' + esc(fmtTs(r.decidedTs)) : '') + '</div>'
      + (r.applying ? '<div class="cap wtxt" style="margin-top:4px">' + (r.bucket === 'own' ? (ofAuto() ? '자동으로 다시 시작해 과거 내역을 채우는 중 · 끝나면 내 지갑 이동으로 다시 분류돼요' : '수집기 재시작 뒤 내 지갑 이동으로 다시 분류돼요') : '1분 안에 거래소 입금으로 다시 분류돼요') + '</div>' : '') + '</div>'
      + (r.bucket !== 'spam' && r.bucket !== 'system' ? '<button class="btn sm ofundo" data-a="ofUndo" data-k="' + esc(r.address) + '">' + IC.undo + ' 되돌리기</button>' : '') + '</div>'
      + (r.bucket !== 'spam' && r.bucket !== 'system' ? ofMemo(r) : '') + ofLinks(r);
  }
  function ofMemo(r) {
    const a = r.address;
    if (S.of.memoEd === a) return '<div class="ofmemo ed"><div class="frm"><input class="field" data-pr="1" maxlength="200" placeholder="예: 토큰 세일 참가금" data-draft="' + esc('ofm:' + a) + '" data-enter="ofMemoSave" data-k="' + esc(a) + '" aria-label="메모"><button class="btn sm pri" data-a="ofMemoSave" data-k="' + esc(a) + '">저장</button><button class="btn sm" data-a="ofMemoEd" data-k="">취소</button></div></div>';
    return '<div class="ofmemo">' + (r.memo ? '<span class="lab">메모</span>' + prTxt(r.memo, 't') + '<button class="btn sm ghost" data-a="ofMemoEd" data-k="' + esc(a) + '">고치기</button>'
      : '<button class="btn sm ghost" data-a="ofMemoEd" data-k="' + esc(a) + '">+ 메모</button>') + '</div>';
  }
  const OF_LK = { refund: ['환불', 'ok'], tokens: ['세일 토큰', 'a'] };
  function ofSaleNums(r) {
    const sent = r.sendKnown ? r.usdAtSend : r.usdNow, ret = num(r.returnedUsd), tok = num(r.linkTokenUsd), wait = Math.max(0, num(r.saleWait));
    return { sent, ret, tok, wait, done: !(wait > 0) };
  }
  function ofSaleCard(r) {
    const a = r.address, open = S.of.open.has(a), n = ofSaleNums(r), tx0 = r.txs[0] || {};
    const pct = n.sent > 0 ? Math.max(1, Math.round(n.wait / n.sent * 100)) : 100;
    const chip = '<span class="pill ' + (n.done ? 'ok' : 'w') + ' sm">세일 참가금 · ' + (n.done ? '회수 끝' : '회수 대기') + '</span>'
      + (r._opt ? ' <span class="pill w sm" title="저장했어요 · 서버가 다시 계산하면 금액이 그 값으로 바뀌어요">반영 중</span>' : '');
    const cbadge = r.candN > 0 ? ' <span class="pill a sm cbadge" title="보낸 뒤 들어온 원가 미확인 유입·환불 후보 — 펼쳐서 연결하세요">연결할 후보 ' + r.candN + '</span>' : '';
    const sub = esc([ofNm(r) ? short(a) : '', r.chainNames.join('·'), tx0.ts ? fmtTs(tx0.ts) : r.last, r.tokens.slice(0, 2).map(t => q(t.qty) + ' ' + t.sym).join(' · ')].filter(Boolean).join(' · '))
      + (r.memo && (r.alias || !ofNm(r)) ? ' · ' + prTxt(r.memo, 'ofmm') : '');
    const amt = '<div class="samt" title="' + esc(n.done ? '순유출 ' + plainT(m(Math.max(0, num(r.netUsd)))) : '회수 대기 ' + pct + '%') + '"><b class="num">' + m(n.sent, { compact: true }) + '</b><span class="num mut">'
      + mAlt(n.sent, { compact: true }) + '</span></div>';
    const nmU = ofNm(r);
    const tot = Math.max(n.sent, n.ret + n.tok + n.wait) || 1, seg = (c, v) => v > 0 ? '<i class="' + c + '" style="width:' + Math.max(1, v / tot * 100).toFixed(2) + '%"></i>' : '';
    const bar = '<div class="sbar" aria-hidden="true">' + seg('r', n.ret) + seg('t', n.tok) + seg('w', n.wait) + '</div>';
    const lg = (c, l, v) => '<span class="' + (v > 0 ? '' : 'z') + '"><i class="sd ' + c + '"></i>' + l + ' <b class="num">' + m(v, { compact: true }) + '</b></span>';
    const legend = '<div class="slg">' + lg('r', '돌려받음', n.ret) + lg('t', '토큰으로 받음', n.tok) + lg('w', '회수 대기', n.wait) + '</div>';
    const strip = window.TJSale && window.TJSale.candStrip ? window.TJSale.candStrip(r) : '';
    return '<div class="card of sale' + (open ? ' open' : '') + '" data-anc="outflow:' + esc(a) + '">' + strip + '<div class="shd" role="button" tabindex="0" data-a="ofTog" data-k="' + esc(a) + '" aria-expanded="' + open + '">'
      + '<span class="aic ' + (n.done ? 'ok' : 'w') + '">' + (n.done ? IC.check : IC.down) + '</span>'
      + '<div class="swho"><div class="row gap8 st">' + (nmU ? '<b class="ofnm ell" title="' + esc(a) + '">' + nmU + '</b>' : '<span class="addr" title="' + esc(a) + '">' + esc(short(a)) + '</span>') + '<span class="chip-d">' + chip + cbadge + '</span></div><div class="sub ell sub-d">' + sub + '</div></div>'
      + amt + '<span class="chev' + (open ? ' o' : '') + '">' + IC.chev + '</span>'
      + '<span class="chip-m">' + chip + cbadge + '</span></div>'
      + '<div class="sprog">' + bar + legend + '<div class="sub ell sub-m">' + sub + '</div></div>'
      + (open ? clps('of:' + a, ofSaleBody(r, n)) : '') + '</div>';
  }
  function ofSaleBody(r, n) {
    const a = r.address, L = r.links, tx0 = r.txs[0] || {};
    const memo = '<div class="sf"><label class="lab" for="' + esc('ofm-' + a) + '">메모</label><div class="frm"><input class="field" data-pr="1" id="' + esc('ofm-' + a) + '" maxlength="200" placeholder="예: 토큰 세일 참가금" value="' + esc(r.memo) + '" data-draft="' + esc('ofm:' + a) + '" data-enter="ofMemoSave" data-k="' + esc(a) + '" aria-label="메모"><button class="btn" data-a="ofMemoSave" data-k="' + esc(a) + '">저장</button></div></div>';
    let left;
    if (L.length) {
      const kv = (l, v, c, b) => '<div class="' + (b ? 'tt' : '') + '"><span>' + l + '</span><span class="num' + (c ? ' ' + c : '') + '">' + v + '</span></div>';
      const pl = window.TJSale && window.TJSale.salePnl ? window.TJSale.salePnl(r) : null;
      left = memo + '<div class="sbox">' + kv('보냄', m(n.sent)) + kv('− 돌려받음 (환불)', m(n.ret), 'oktxt') + kv('− 토큰으로 받음 (원가)', m(n.tok), 'atxt') + kv('<b>회수 대기</b>', '<b>' + m(n.wait) + '</b>', '', true)
        + (pl && pl.coinN ? kv('받은 코인 평가금액', pl.nowOk ? m(pl.now) : '시세 없음') + (pl.nowOk ? kv('세일 손익(지금 기준)', '<b>' + m(pl.pnl, { sign: true }) + '</b>', cls(pl.pnl)) : '') : '') + '</div>'
        + ofPaidNote(r, n.sent) + (L.some(l => l.st === 'mixed') || r.excludeLegs.length || r.txs.length > 1 ? ofLegs(r) : '');
    } else {
      const cats = '<div class="sf"><div class="lab">분류</div><div class="scat">' + OF_CATS.map(c => '<button class="' + (c === r.category ? 'on' : '') + '" data-a="ofCatSet" data-k="' + esc(a) + '" data-v="' + esc(c) + '" aria-pressed="' + (c === r.category) + '">' + esc(ofCatLbl(c)) + '</button>').join('') + '</div></div>';
      const sumb = '<div class="sbox"><div><span>보냄</span><span class="num">' + r.tokens.slice(0, 2).map(t => q(t.qty) + ' ' + esc(t.sym)).join(' · ') + ' · ' + m(n.sent) + '</span></div>'
        + (r.txs.length <= 1 && tx0.tx ? '<div><span>tx</span><span class="mono sm">' + esc(fmtTs(tx0.ts)) + ' · ' + esc(short(tx0.tx)) + ' <button class="cpy" data-a="copy" data-v="' + esc(tx0.tx) + '" aria-label="txid 복사">' + IC.copy + '</button></span></div>' : '') + '</div>'
        + (r.txs.length > 1 || r.excludeLegs.length ? ofLegs(r) : '');
      left = memo + cats + sumb + '<button class="lnk mut" data-a="ofUndo" data-k="' + esc(a) + '">분류 되돌리기</button>';
    }
    const pickOpen = S.of.lk && S.of.lk.a === a;
    let right;
    if (!L.length || (pickOpen && !S.mobile)) right = S.mobile ? '<button class="btn pri sbig" data-a="ofLkOpen" data-k="' + esc(a) + '">받은 것과 연결</button>' : ofSalePick(r, n, false);
    else {
      const rows = L.map(l => { const k = OF_LK[l.kind], bad = OF_LK_ST[l.st], per = l.kind === 'tokens' && l.costUsd != null && l.qty > 0 ? ' · 원가 ' + m(l.costUsd / l.qty) + '/개' : (l.where ? ' · ' + locH(l.where) : '');
        return '<div class="slk"><span class="pill ' + k[1] + ' sm">' + k[0] + '</span><span class="m"><b><span class="num">' + q(l.qty) + '</span> ' + esc(l.sym) + '</b><span class="cap">' + esc(fmtTs(l.ts)) + per + (bad ? ' · <span class="wtxt">' + esc(bad) + '</span>' : '') + '</span></span>'
          + '<span class="v num">' + (l.kind === 'refund' ? (l.usd != null ? m(l.usd, { compact: true }) : '') : (l.costUsd != null ? '원가 ' + m(l.costUsd, { compact: true }) : '')) + '</span>'
          + '<button class="x" data-a="ofLkUn" data-k="' + esc(a) + '" data-v="' + esc(l.key) + '" aria-label="연결 해제" title="연결 해제">' + IC.close + '</button></div>'; }).join('');
      const tk = L.filter(l => l.kind === 'tokens' && l.st === 'applied');
      right = '<div class="sconn"><div class="sh"><b>연결된 것 ' + L.length + '</b><button class="lnk" data-a="ofLkOpen" data-k="' + esc(a) + '">+ 더 연결</button></div>' + rows
        + (tk.length ? '<div class="cap">' + (tk.length === 1 ? esc(tk[0].sym) + ' 를 팔면 실현 = 판 금액 − ' + m(num(tk[0].costUsd), { compact: true }) : '세일 토큰을 팔면 실현 = 판 금액 − 각 원가') + '</div>' : '') + '</div>';
    }
    return '<div class="sob"><div class="sgl">' + left + '</div><div class="sgr">' + right + '</div></div>';
  }
  function ofLegs(r) {
    const ex = new Set(r.excludeLegs), a = r.address;
    const rows = r.txs.filter(t => t && t.key).slice(0, 12).map(t => { const off = ex.has(String(t.key));
      return '<div class="sleg' + (off ? ' off' : '') + '"><span class="m">' + esc(String(t.t || fmtTs(t.ts)).slice(5)) + ' · <span class="num">' + q(num(t.qty)) + '</span> ' + esc(t.sym || '') + (t.ex ? ' · ' + esc(t.ex) + ' 출금' : '') + '</span>'
        + '<span class="num v">' + (t.usdAtSend != null ? m(num(t.usdAtSend), { compact: true }) : '—') + '</span>'
        + '<button class="lnk' + (off ? '' : ' mut') + '" data-a="ofLegTog" data-k="' + esc(a) + '" data-v="' + esc(String(t.key)) + '" aria-pressed="' + off + '">' + (off ? '참가금에 넣기' : '참가금 아님') + '</button></div>'; }).join('');
    return rows ? '<div class="sbox slegs"><div class="lh"><span>보낸 레그</span><span class="cap">참가금 아닌 건 빼면 토큰 원가에서 빠져요</span></div>' + rows + '</div>' : '';
  }
  const ofPaidNote = (r, sent) => r.linkPaidUsd != null && Math.abs(r.linkPaidUsd - sent) >= 0.5
    ? '<div class="cap">수령 전 참가금 ' + m(r.linkPaidUsd) + ' / 전체 보냄 ' + m(sent) + ' — 토큰 원가는 수령 전 참가금으로 셈해요</div>' : '';
  function ofSalePick(r, n, sheet) {
    const a = r.address, c = S.of.lkc[a];
    if (!c) setTimeout(() => { if (!S.of.lkc[a]) ofLkLoad(a); }, 0);
    const lk = S.of.lk && S.of.lk.a === a ? S.of.lk : null, sel = lk ? lk.sel : new Map();
    const close = (S.of.lk && S.of.lk.a === a) && (sheet || r.links.length) ? '<button class="x" data-a="ofLkClose" aria-label="닫기" title="닫기">' + IC.close + '</button>' : '';
    const o = ofLkOpt(a), win = c && c.win;
    const head = '<div class="sh"><b>받은 것과 연결</b>' + (close || '<span class="cap">' + esc(fmtTs(r.firstTs).slice(0, 5)) + (o.all || (win && win.to == null) ? ' 이후 전체' : ' ~ ' + esc(fmtTs((win && win.to) || (r.firstTs + 60 * 86400)).slice(0, 5)) + ' 들어온 것') + '</span>') + '</div>';
    let body;
    if (!c || (c.st === 'load' && !c.rows)) body = '<label class="search">' + IC.search + '<input class="field" type="search" placeholder="코인 · 지갑 · tx" data-draft="oflq" data-input="oflq" aria-label="받은 내역 찾기" autocomplete="off" spellcheck="false"></label>'
      + '<div class="lkmeta" aria-busy="true"><span class="cap" role="status" aria-live="polite">받은 내역 찾는 중…</span>'
      + '<button class="lnk" data-a="ofLkAll" data-k="' + esc(a) + '" aria-pressed="' + o.all + '">' + (o.all ? '보낸 뒤 60일만' : '기간 넓히기(전체)') + '</button>'
      + '<button class="lnk mut" data-a="ofLkSpam" data-k="' + esc(a) + '" aria-pressed="' + o.spam + '">' + (o.spam ? '스팸 의심 빼기' : '스팸 의심 포함') + '</button></div>' + evSkel(4, 0);
    else if (c.st === 'err') body = '<div class="cap etxt">불러오지 못했어요 · ' + esc(errTxt(c.err || '')) + '</div><button class="btn sm" data-a="ofLkOpen" data-k="' + esc(a) + '">다시 시도</button>';
    else {
      const rows = c.rows.filter(x => !x.linked), tk = rows.filter(x => !x.stable), st = rows.filter(x => x.stable);
      const tab = S.of.lkTab === 'ref' && st.length ? 'ref' : (tk.length ? 'tok' : 'ref'), list = tab === 'ref' ? st : tk;
      const qv = String(S.drafts.oflq || '').trim().toLowerCase();
      const it = x => { const on = sel.has(x.key), sq = lkSq(x);
        return '<button class="lkc' + (on ? ' on' : '') + '" data-a="ofLkTog" data-k="' + esc(x.key) + '" data-v="' + esc(a) + '" data-q="' + esc(sq) + '" aria-pressed="' + on + '"' + (qv && lkHay(x).indexOf(qv) < 0 ? ' hidden' : '') + '><span class="ck">' + (on ? IC.check : '') + '</span><span class="m"><b><span class="num">' + q(x.qty) + '</span> ' + esc(x.sym) + '</b>'
          + '<span class="cap">' + esc(String(x.t).slice(5, 16)) + ' · ' + locH(x.where) + (x.stable ? '' : ' · 원가 미확인') + (x.fromSender ? ' · 보낸 지갑으로 들어옴' : '') + (x.dismissed ? ' · 아님으로 뺀 제안' : '') + (x.fromDest ? ' · 이 주소에서 옴' : '') + (x.sale ? ' · 세일 자동 연결됨' : '') + '</span></span>' + (x.quar ? '<span class="tg">스팸 의심</span>' : '') + '</button>'; };
      const nT = c.totalTok != null ? Math.max(c.totalTok, tk.length) : tk.length, nS = c.totalStable != null ? Math.max(c.totalStable, st.length) : st.length;
      const tabs = '<div class="stab"><button class="' + (tab === 'tok' ? 'on' : '') + '" data-a="ofLkTab" data-v="tok"' + (tk.length ? '' : ' disabled') + '>세일 토큰 ' + nT + '</button><button class="' + (tab === 'ref' ? 'on' : '') + '" data-a="ofLkTab" data-v="ref"' + (st.length ? '' : ' disabled') + '>환불' + (sheet ? '' : '(스테이블)') + ' ' + nS + '</button></div>'
        + '<div class="lkmeta"><span class="cap num">' + (c.total != null && c.total > c.rows.length ? '전체 ' + c.total + '건 중 ' + c.rows.length + '건' : c.rows.length + '건') + (c.st === 'load' ? ' · 찾는 중…' : '') + '</span>'
        + '<button class="lnk" data-a="ofLkAll" data-k="' + esc(a) + '" aria-pressed="' + o.all + '">' + (o.all ? '보낸 뒤 60일만' : '기간 넓히기(전체)') + '</button>'
        + '<button class="lnk mut" data-a="ofLkSpam" data-k="' + esc(a) + '" aria-pressed="' + o.spam + '">' + (o.spam ? '스팸 의심 빼기' : '스팸 의심 포함' + (c.quarN ? ' ' + c.quarN : '')) + '</button></div>';
      const refSel = sum([...sel.values()].filter(x => x.stable), x => x.qty);
      const cost = Math.max(0, n.sent - n.ret - refSel);
      body = '<label class="search">' + IC.search + '<input class="field" type="search" placeholder="코인 · 지갑 · tx" data-draft="oflq" data-input="oflq" aria-label="받은 내역 찾기" autocomplete="off" spellcheck="false"></label>' + tabs
        + (rows.length ? '<div class="lkl">' + list.map(it).join('') + '<div class="cap lke"' + (!qv || list.some(x => lkHay(x).indexOf(qv) >= 0) ? ' hidden' : '') + '>찾는 내역이 없어요</div></div>'
          : '<div class="cap">보낸 뒤 내 지갑·거래소로 받은 연결할 내역이 없어요</div>')
        + '<div class="sft"><span class="cap">토큰 원가 = 참가금 − 환불 = <b class="num">' + m(cost, { compact: true }) + '</b></span><button class="btn pri" data-a="ofLkSave" data-k="' + esc(a) + '"' + (sel.size ? '' : ' disabled') + '>' + (sel.size ? sel.size + '건 연결' : '연결') + '</button></div>';
    }
    return '<div class="spick' + (sheet ? ' sheet' : '') + '" data-addr="' + esc(a) + '">' + (sheet ? '<i class="hdl"></i>' : '') + head + body + '</div>';
  }
  function ofSheet() {
    if (!S.mobile || !S.of.lk) return '';
    const r = ofByAddr(S.of.lk.a);
    if (!r || !ofIsSale(r)) return '';
    return '<div class="sdim" data-a="ofLkClose"></div><div class="ssheet" role="dialog" aria-modal="true" aria-label="받은 것과 연결">' + ofSalePick(r, ofSaleNums(r), true) + '</div>';
  }
  const OF_LK_ST = { other_path: '다른 원가 경로(내 전송·브릿지)가 먼저라 적용 안 됨', missing: '원장에서 못 찾음 — 재구축 중이면 곧 다시 붙어요', no_cost: '참가금 금액을 몰라 원가를 못 붙였어요', invalid: '연결할 수 없는 유입', dup: '같은 유입이 이미 다른 연결로 잡혀 있어요 — 한 번만 세요', mixed: '참가금에 다른 토큰 섞임 — 확인(원가 안 붙임)', self_overlap: '자기 전송과 겹침 — 확인(원가 안 붙임)', excl_missing: '제외 기록 확인 필요(원가 안 붙임)', off: '외부 유출 확정일 때만 적용돼요' };
  function ofLinks(r) {
    if (r.bucket !== 'external') return '';
    const a = r.address, L = r.links, pick = S.of.lk && S.of.lk.a === a;
    const tok = L.filter(l => l.kind === 'tokens' && l.st === 'applied'), cost = sum(tok, l => num(l.costUsd));
    const rows = L.map(l => { const k = OF_LK[l.kind], bad = OF_LK_ST[l.st];
      return '<div class="lkr"><span class="pill ' + k[1] + ' sm">' + k[0] + '</span><span class="m"><span class="q"><span class="num">' + q(l.qty) + '</span> ' + esc(l.sym) + '</span>'
        + '<span class="cap">' + esc(fmtTs(l.ts)) + (l.where ? ' · ' + locH(l.where) : '') + (bad ? ' · <span class="wtxt">' + esc(bad) + '</span>' : '') + '</span></span>'
        + '<span class="v num">' + (l.kind === 'refund' ? (l.usd != null ? m(l.usd) : '') : (l.costUsd != null ? '원가 ' + m(l.costUsd) : '')) + '</span>'
        + '<button class="cpy" data-a="ofLkUn" data-k="' + esc(a) + '" data-v="' + esc(l.key) + '" aria-label="연결 해제" title="연결 해제">' + IC.close + '</button></div>'; }).join('');
    const sent = r.sendKnown ? r.usdAtSend : 0;
    const note = tok.length ? '세일 토큰 원가 ' + m(cost) + ' = 보낸 ' + m(sent) + (r.linkRefundUsd ? ' − 환불 ' + m(r.linkRefundUsd) : '') + (tok.length > 1 ? ' · 수령 ' + tok.length + '건에 수량 비례' : '')
      : r.saleWait > 0 ? '회수 대기 ' + m(r.saleWait) + (r.returnedUsd > 0 ? ' = 보낸 ' + m(sent) + ' − 돌려받음 ' + m(r.returnedUsd) : '') + ' — 환불·세일 토큰을 받으면 연결하세요'
        : L.length ? '' : '환불이나 세일 토큰을 받으면 연결하세요 — 세일 토큰 원가가 이 참가금으로 잡혀요';
    const retHint = r.returnedUsd > 0 && !L.some(l => l.kind === 'refund') && !r.returned.some(t => t.linked) ? '<div class="cap" style="margin-top:6px">이 주소에서 ' + m(r.returnedUsd) + ' 되돌려 받았어요 — 환불이면 ‘환불’로 연결해야 원가에서 빠져요</div>' : '';
    return '<div class="blk lkbox"><div class="ttl">받은 것과 연결' + (L.length ? ' <span class="mut" style="font-weight:500">' + L.length + '건</span>' : '') + '</div>' + rows
      + (note ? '<div class="cap"' + (rows ? ' style="margin-top:6px"' : '') + '>' + note + '</div>' : '') + ofPaidNote(r, sent) + retHint
      + (pick ? ofLkPick(r) : '<div class="frm"><button class="btn sm" data-a="ofLkOpen" data-k="' + esc(a) + '">받은 것과 연결</button></div>') + '</div>';
  }
  const lkSq = x => (x.sym + ' ' + x.tx + ' ' + x.t).toLowerCase();
  const lkHay = x => (x.sym + ' ' + x.where + ' ' + x.tx + ' ' + x.t).toLowerCase();
  function ofLkPick(r) {
    const a = r.address, c = S.of.lkc[a], sel = S.of.lk.sel;
    if (!c || c.st === 'load') return '<div class="lkpick" data-addr="' + esc(a) + '"><div class="cap">받은 내역을 불러오는 중…</div></div>';
    if (c.st === 'err') return '<div class="lkpick" data-addr="' + esc(a) + '"><div class="cap etxt">불러오지 못했어요 · ' + esc(errTxt(c.err || '')) + '</div><div class="frm"><button class="btn sm" data-a="ofLkOpen" data-k="' + esc(a) + '">다시 시도</button><button class="btn sm" data-a="ofLkClose">닫기</button></div></div>';
    const qv = String(S.drafts.oflq || '').trim().toLowerCase();
    const it = x => { const on = sel.has(x.key), sq = lkSq(x);
      return '<button class="lkc' + (on ? ' on' : '') + '" data-a="ofLkTog" data-k="' + esc(x.key) + '" data-q="' + esc(sq) + '" aria-pressed="' + on + '"' + (qv && lkHay(x).indexOf(qv) < 0 ? ' hidden' : '') + '><span class="ck">' + (on ? IC.check : '') + '</span><span class="m"><span class="num">' + q(x.qty) + '</span> <b>' + esc(x.sym) + '</b>'
        + '<span class="cap">' + esc(String(x.t).slice(0, 16)) + ' · ' + locH(x.where) + (x.fromSender ? ' · 보낸 지갑으로 들어옴' : '') + (x.dismissed ? ' · 아님으로 뺀 제안' : '') + (x.fromDest ? ' · 이 주소에서 옴' : '') + (x.sale ? ' · 세일 자동 연결됨' : '') + (x.quar ? ' · 스팸 의심(숨김)' : '') + '</span></span></button>'; };
    const rows = c.rows.filter(x => !x.linked), tk = rows.filter(x => !x.stable), st = rows.filter(x => x.stable);
    const list = (tk.length ? '<div class="lab">세일 토큰 후보 · 원가 미확인</div>' + tk.map(it).join('') : '') + (st.length ? '<div class="lab">스테이블 · 환불 후보</div>' + st.map(it).join('') : '');
    return '<div class="lkpick" data-addr="' + esc(a) + '"><label class="search">' + IC.search + '<input class="field" type="search" placeholder="코인 · 지갑 · tx 찾기" data-draft="oflq" data-input="oflq" aria-label="받은 내역 찾기" autocomplete="off" spellcheck="false"></label>'
      + (list ? '<div class="lkl">' + list + '<div class="cap lke"' + (qv && rows.some(x => lkHay(x).indexOf(qv) >= 0) || !qv ? ' hidden' : '') + '>찾는 내역이 없어요</div></div>'
        : '<div class="cap" style="margin-top:8px">보낸 뒤 내 지갑·거래소로 받은 연결할 내역이 없어요</div>')
      + '<div class="frm"><button class="btn sm pri" data-a="ofLkSave" data-k="' + esc(a) + '"' + (sel.size ? '' : ' disabled') + '>연결' + (sel.size ? ' ' + sel.size + '건' : '') + '</button><button class="btn sm" data-a="ofLkClose">닫기</button></div>'
      + '<div class="cap" style="margin-top:6px">스테이블은 환불(손익 0), 그 밖은 세일 토큰으로 연결돼요 — 원가 = 보낸 값 − 환불</div></div>';
  }
  function ofLkFilter(v, box0) {
    const q0 = String(v || '').trim().toLowerCase(), box = box0 || document.querySelector('.lkpick, .spick'); if (!box) return;
    let any = false;
    const c9 = S.of.lkc[box.getAttribute('data-addr') || ''], by9 = new Map(arr(c9 && c9.rows).map(x => [x.key, x]));
    box.querySelectorAll('.lkc').forEach(o => { const x9 = by9.get(o.getAttribute('data-k')), hay = x9 ? lkHay(x9) : String(o.getAttribute('data-q') || '');
      const ok = !q0 || hay.indexOf(q0) >= 0; o.hidden = !ok; if (ok) any = true; });
    const e = box.querySelector('.lke'); if (e) e.hidden = any;
  }
  function ofLkInput(t) {
    const box = t.closest ? t.closest('.spick, .lkpick') : null, a0 = (box && box.getAttribute('data-addr')) || (S.of.lk && S.of.lk.a) || '';
    ofLkFilter(t.value, box);
    if (!a0) return;
    clearTimeout(S.of.lkT);
    S.of.lkT = setTimeout(() => { ofLkOpt(a0).q = String(t.value || '').trim(); ofLkLoad(a0); }, 350);
  }
  const ofLkOpt = a => S.of.lkOpt[a] || (S.of.lkOpt[a] = { all: false, spam: false, q: '' });
  function ofLkLoad(a) {
    const o = ofLkOpt(a), vk = (o.all ? 'a' : '') + (o.spam ? 's' : '');
    const prev = S.of.lkc[a] && S.of.lkc[a].vk === vk ? S.of.lkc[a] : null;
    const g = S.of.lkGen[a] = (S.of.lkGen[a] || 0) + 1;
    S.of.lkc[a] = { st: 'load', vk, rows: prev && prev.rows, total: prev && prev.total, totalTok: prev && prev.totalTok, totalStable: prev && prev.totalStable, quarN: prev && prev.quarN, win: prev && prev.win };
    fetch('/api/outflow_candidates?address=' + encodeURIComponent(a) + (o.all ? '&all=1' : '') + (o.spam ? '&spam=1' : '') + (o.q ? '&q=' + encodeURIComponent(o.q) : ''), { cache: 'no-store' }).then(r => {
      if (r.status === 401) { onUnauthorized(); return null; }
      return r.json().catch(() => null).then(j => (r.ok && j && j.ok) ? j : Promise.reject(new Error((j && j.error) || ('HTTP ' + r.status))));
    }).then(j => {
      if (!j || S.of.lkGen[a] !== g) return;
      S.of.lkc[a] = { st: 'ok', vk, total: num(j.total), shown: num(j.shown), totalTok: num(j.totalTok), totalStable: num(j.totalStable), quarN: num(j.quarN),
        win: j.window && typeof j.window === 'object' ? { from: num(j.window.from), to: j.window.to == null ? null : num(j.window.to) } : null, rows: arr(j.cands).filter(x => x && x.key).map(x => ({ key: String(x.key), sym: String(x.sym || '?'), qty: num(x.qty), ts: num(x.ts), t: String(x.t || ''),
        where: String(x.where || ''), tx: String(x.tx || ''), stable: !!x.stable, sale: !!x.sale, fromDest: !!x.fromDest, fromSender: !!x.fromSender, dismissed: !!x.dismissed, quar: !!x.quar, linked: x.linked || null })) };
    }).catch(e => { if (S.of.lkGen[a] === g) S.of.lkc[a] = { st: 'err', vk, err: (e && e.message) || '' }; }).then(() => {
      if (S.tab !== 'outflows' || S.of.lkGen[a] !== g) return;
      const ae = document.activeElement, foc = !!(ae && ae.getAttribute && ae.getAttribute('data-input') === 'oflq'), pos = foc ? ae.selectionStart : 0;
      renderView();
      if (foc) { const n = $('[data-input="oflq"]'); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e2) {  } } }
    });
  }
  function ofActions(r) {
    const a = r.address, sel = S.of.form[a] || '';
    const b = (v, t, s, ic, tone) => '<button class="vbtn' + (sel === v ? ' on' : '') + '" data-a="ofPick" data-k="' + esc(a) + '" data-v="' + v + '" aria-pressed="' + (sel === v) + '"><span class="vi ico ' + tone + '">' + ic + '</span><span><b>' + t + '</b><span class="s">' + s + '</span></span></button>';
    let form = '';
    const dk = k => 'of:' + a + ':' + k;
    const recOnly = r.noAddr || (r.exwdOnly && !r.chains.length);
    if (sel === 'own' && recOnly) {
      form = '<div class="vform"><div class="lab">지갑 이름 (선택)</div><input class="field" style="width:100%" placeholder="예: 트론 지갑" data-draft="' + esc(dk('alias')) + '" aria-label="지갑 이름">'
        + '<div class="frm"><button class="btn pri" data-a="ofSave" data-k="' + esc(a) + '" data-v="own">내 지갑으로 기록</button><span class="cap">추적 안 하는 내 지갑으로 기록만 해요(수집 대상 추가 없음)</span></div></div>';
    } else if (sel === 'own') {
      const chs = S.drafts[dk('chains')] != null ? String(S.drafts[dk('chains')]).split(',').filter(Boolean) : r.chains.slice();
      form = '<div class="vform"><div class="lab">지갑 이름</div><input class="field" style="width:100%" placeholder="예: 콜드 3" data-draft="' + esc(dk('alias')) + '" aria-label="지갑 이름"><div class="lab" style="margin-top:10px">추적할 체인</div><div class="optline">'
        + (r.chains.length ? r.chains : ['eth']).map(c => '<button class="fbtn' + (chs.indexOf(c) >= 0 ? ' on' : '') + '" data-a="ofChain" data-k="' + esc(a) + '" data-v="' + esc(c) + '" aria-pressed="' + (chs.indexOf(c) >= 0) + '">' + esc(CHAIN_KO[c] || c) + '</button>').join('') + '</div>'
        + '<div class="frm"><button class="btn pri" data-a="ofSave" data-k="' + esc(a) + '" data-v="own">내 지갑으로 등록</button><span class="cap">' + (ofAuto() ? '등록하면 곧 자동으로 수집을 시작해 과거 내역도 채워요' : '등록 뒤 수집기가 다시 시작되면 과거 내역도 채워져요') + '</span></div></div>';
    } else if (sel === 'exchange') {
      const ex = S.drafts[dk('ex')] || '';
      form = '<div class="vform"><div class="lab">어느 거래소 입금 주소인가요?</div><div class="optline">' + EX_ORDER.map(k => '<button class="fbtn' + (ex === k ? ' on' : '') + '" data-a="ofEx" data-k="' + esc(a) + '" data-v="' + k + '" aria-pressed="' + (ex === k) + '">' + exLogo(k) + EX_NAMES[k] + '</button>').join('') + '</div>'
        + '<div class="frm"><button class="btn pri" data-a="ofSave" data-k="' + esc(a) + '" data-v="exchange"' + (ex ? '' : ' disabled') + '>거래소 입금으로 저장</button></div></div>';
    } else if (sel === 'external') {
      const cat = S.drafts[dk('cat')] || '';
      form = '<div class="vform"><div class="lab">사유</div><div class="optline">' + OF_CATS.map(c => '<button class="fbtn' + (cat === c ? ' on' : '') + '" data-a="ofCat" data-k="' + esc(a) + '" data-v="' + esc(c) + '" aria-pressed="' + (cat === c) + '">' + esc(ofCatLbl(c)) + '</button>').join('') + '</div>'
        + '<div class="lab" style="margin-top:10px">메모 (선택)</div><input class="field" data-pr="1" style="width:100%" maxlength="200" placeholder="예: OTC 정산, 친구 송금" data-draft="' + esc(dk('memo')) + '" aria-label="메모">'
        + '<div class="frm"><button class="btn solid-danger" data-a="ofSave" data-k="' + esc(a) + '" data-v="external"' + (cat ? '' : ' disabled') + '>외부 유출로 확정</button></div></div>';
    }
    return '<div class="lab" style="margin-bottom:8px">' + (r.special ? '받는 주소를 특정하지 못했어요 — 외부 유출로만 정리할 수 있어요' : r.exwd.length ? (r.noAddr ? '이 출금은 어디로 갔나요?' : '이 주소가 어떤 주소인가요?') : '이 주소는…') + '</div><div class="vact">'
      + (r.special ? '' : b('own', '내 지갑이에요', recOnly ? '추적 안 하는 내 지갑 — 기록만 남겨요' : '이름을 붙여 추적 지갑으로 등록', IC.wallet, 'ok')
      + b('exchange', '거래소 입금 주소예요', '거래소 입금으로 원가를 이어요', IC.bank, 'a'))
      + b('external', '외부 유출 확정', '송금·결제 · 세일 참가금 · 분실·해킹 · 기타', IC.send, 'e')
      + '</div>' + (form ? '<div style="margin-top:10px">' + form + '</div>' : '') + (sel === 'external' ? '' : ofMemo(r));
  }
  function wdDestHTML() {
    const D = S.D, st = D.wdDestStats, EXN = k => EX_NAMES[k] || k;
    const head = '<div class="cap" style="margin:-2px 0 12px">거래소 출금 목적지 ' + (num(st.wallet) + num(st.wallet_untracked) + num(st.exchange) + num(st.unknown)) + '건 · 등록 지갑 ' + (num(st.wallet) + num(st.wallet_untracked)) + (num(st.wallet_untracked) ? '(미수집 네트워크 ' + num(st.wallet_untracked) + ')' : '')
      + ' · 내 거래소 입금 주소 ' + num(st.exchange) + ' · <b>미등록 ' + num(st.unknown) + '</b>. 미등록 주소가 내 지갑이면 등록하세요' + ' — 그 지갑 과거 이력을 가져와 원가가 이어져요. ★ = 그 주소가 내 거래소·지갑으로 다시 보낸 기록이 있어요.</div>';
    const wdRow = u => {
      const sig = [];
      if (num(u.hop)) sig.push('내 거래소 입금으로 이어짐 ' + u.hop + '건');
      if (num(u.sentToMine)) sig.push('내 거래소로 보냄 ' + u.sentToMine + '건');
      if (num(u.walletTx)) sig.push('내 지갑과 거래 ' + u.walletTx + '건');
      return '<div class="card" style="padding:14px 16px;margin-bottom:10px"><div class="row gap8" style="flex-wrap:wrap;align-items:center">'
        + (u.strong ? '<span class="pill ok sm" title="내 지갑일 가능성이 높아요">★ 내 지갑 신호</span>' : '')
        + (num(u.offcN) ? '<span class="pill g sm pvx" title="거래소 사용자끼리 체인 밖 이체(오프체인) — 이 주소는 다른 거래소 사용자의 입금 주소예요">오프체인 ' + num(u.offcN) + '건</span>' : '')
        + '<button class="addr" data-a="copy" data-v="' + esc(u.address) + '" title="복사 · ' + esc(u.address) + '" style="font-family:var(--mono,monospace)">' + esc(short(u.address)) + '</button>'
        + '<span class="cap num">출금 ' + u.n + '건 · 원가 ' + mN(num(u.costUsd), { compact: true }) + '</span>'
        + (num(u.resolveUsd) >= 1 ? '<span class="pill a sm num" title="' + esc('등록하면 원가가 이어질 수 있는 원가 미확인 매도(추정): ' + arr(u.resolveSyms).map(x => x[0] + ' ' + m(num(x[1]), { compact: true })).join(' · ')) + '">원가 연결 가능 ≈ ' + m(num(u.resolveUsd), { compact: true }) + '</span>' : '') + '<span class="sp"></span>'
        + '<button class="btn sm pri" data-a="wdReg" data-v="' + esc(u.address) + '">내 지갑으로 등록</button>' + '</div>'
        + '<div class="cap" style="margin-top:6px">' + esc(arr(u.exchanges).map(EXN).join('·')) + ' → ' + esc(arr(u.networks).join(', ') || '네트워크 미상') + ' · ' + esc(arr(u.syms).join(', '))
        + ' · ' + esc(fmtYMD(u.first)) + (fmtYMD(u.last) !== fmtYMD(u.first) ? ' ~ ' + esc(fmtYMD(u.last)) : '') + (sig.length ? ' · <b class="oktxt">' + esc(sig.join(' · ')) + '</b>' : '') + '</div></div>';
    };
    const wd60 = D.wdDest.slice(0, 60), rows = wd60.length ? uiPaged('wdd', wd60, u => wdRow(u), { unit: '곳' }) : '';
    const moreN = D.wdDestN - Math.min(60, D.wdDest.length);
    return head + (rows || '<div class="card empty"><b>미등록 목적지가 없어요</b></div>') + (rows && moreN > 0 ? '<div class="cap" style="margin:4px 0 12px">외 ' + moreN + '곳</div>' : '');
  }
  const fmtYMD = ts => { const d = new Date(num(ts) * 1000 + KST_MS); return isNaN(d) || !ts ? '' : d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()); };
  function saleBox(p) {
    const ls = arr(S.D.saleLinks).filter(x => String(x.sym).toUpperCase() === String(p.sym).toUpperCase());
    if (!ls.length || p._lp) return '';
    return '<div class="pbox"><div class="ttl">토큰 세일 매수 <span class="cap">경매 입찰 원가를 받은 토큰에 이었어요</span></div>'
      + ls.map(x => '<div class="kv" style="align-items:center;gap:8px"><span style="min-width:0;overflow-wrap:anywhere;white-space:normal">' + esc(x.label || '토큰 세일')
        + '<span class="cap" style="display:block;overflow-wrap:anywhere;white-space:normal">참여 ' + esc(m(num(x.paidUsd))) + ' · 환불 ' + esc(m(num(x.refundUsd))) + ' · 단가 ' + (x.unit == null ? '미확인' : S.hide ? '$' + pvW(PVM.px) : '$' + esc(rw(String(Number(num(x.unit).toPrecision(6))))))
        + ' · 받은 ' + esc(q(num(x.qty))) + (x.receiptSym ? ' (' + esc(x.receiptSym) + ' 교환)' : '')
        + '<br>연결 ' + esc(q(num(x.usedQty))) + ' · 원가 ' + esc(m(num(x.usedCost))) + ' · 입찰 지갑 ' + esc(short(x.bidder)) + (x.bidderMine ? '' : ' (미등록)')
        + (!x.off && num(x.payN) > 0 ? '<br>결제 코인 사용 ' + esc(q(num(x.payQty))) + ' ' + esc(x.cur || '') + ' · 원래 원가 ' + esc(m(num(x.payCost)))
          + ' · 대가 ' + esc(m(num(x.payProceeds))) + ' · 실현 ' + esc(m(num(x.payRealized))) + (num(x.payUnkQty) > 0 ? ' · 원가 미상 ' + esc(q(num(x.payUnkQty))) : '') : '')
        + (x.off ? ' · <span class="wtxt">끊음 — 원가 미확인으로 계산 중</span>' : '') + (x._opt ? ' · <span class="wtxt">반영 중</span>' : '') + '</span></span>'
        + '<button class="btn sm' + (x.off ? ' pri' : '') + '" data-a="saleTog" data-v="' + esc(x.lot) + '" data-off="' + (x.off ? '0' : '1') + '">' + (x.off ? '다시 연결' : '연결 끊기') + '</button></div>').join('')
      + '</div>';
  }
  function xferBox(p) {
    const ls = S.D.xferLinks.filter(x => String(x.sym).toUpperCase() === String(p.sym).toUpperCase());
    if (!ls.length || p._lp) return '';
    const EXN = k => EX_NAMES[k] || k;
    return '<div class="pbox"><div class="ttl">거래소 간 연결 <span class="cap">txid 가 달라 금액·시간·주소로 이었어요</span></div>'
      + ls.map(x => '<div class="kv" style="align-items:center;gap:8px"><span style="min-width:0;overflow-wrap:anywhere">' + esc(EXN(x.wdEx)) + ' → ' + esc(EXN(x.depEx)) + ' <b class="num">' + esc(q(num(x.qty))) + '</b>'
        + '<span class="cap" style="display:block;overflow-wrap:anywhere">' + esc(String(x.label || '').replace(/^연결: /, '')) + (x.off ? ' · <span class="wtxt">끊음 — 원가 미확인으로 계산 중</span>' : '') + (x._opt ? ' · <span class="wtxt">반영 중</span>' : '') + '</span></span>'
        + '<button class="btn sm' + (x.off ? ' pri' : '') + '" data-a="xferTog" data-v="' + esc(x.dep) + '" data-off="' + (x.off ? '0' : '1') + '">' + (x.off ? '다시 연결' : '연결 끊기') + '</button></div>').join('')
      + '</div>';
  }
  function ofHistory(res) {
    const f = S.of;
    const now = Date.now() / 1000;
    const inPer = r => f.period === 'all' || (f.period === '30d' ? r.lastTs >= now - 30 * 86400 : f.period === '90d' ? r.lastTs >= now - 90 * 86400 : f.period === 'thismonth' ? String(r.last || '').slice(0, 7) === ymShift(0) : true);
    const rsn = r => f.reason === '' || (f.reason === 'own' ? r.bucket === 'own' : f.reason === 'exchange' ? r.bucket === 'exchange' : f.reason === 'spam' ? r.bucket === 'spam' : f.reason === 'returned' ? r.bucket === 'returned' : f.reason === 'bridge' ? r.bucket === 'bridge' : r.bucket === 'external' && r.category === f.reason);
    const coinOk = r => !f.coin || r.tokens.some(t => t.sym === f.coin);
    const list = res.filter(r => inPer(r) && rsn(r) && coinOk(r)).sort((a, b) => b.lastTs - a.lastTs);
    const coins = []; res.forEach(r => r.tokens.forEach(t => { if (coins.indexOf(t.sym) < 0) coins.push(t.sym); }));
    const bar = '<div class="filters ofhf">' + uiPick('ofPeriod', [['all', '전체 기간'], ['thismonth', '이번 달'], ['30d', '최근 30일'], ['90d', '최근 3개월']], f.period, '기간', { act: true })
      + uiPick('ofCoin', [['', '모든 코인']].concat(coins.sort().map(c => [c, c])), f.coin, '코인', { act: true })
      + uiPick('ofReason', [['', '모든 사유']].concat(OF_CATS.map(c => [c, '외부 · ' + ofCatLbl(c)])).concat([['own', '내 지갑'], ['exchange', '거래소 입금 주소'], ['returned', '되돌려 받음'], ['bridge', '브릿지 → 내 지갑'], ['spam', '사칭·스팸 로그']]), f.reason, '사유', { act: true })
      + '<div class="sp"></div><span class="cap num">' + list.length + '곳 · 보낼 때 <b style="color:var(--text)">' + m(sum(list, r => (r.sendKnown ? r.usdAtSend : 0))) + '</b>' + (list.some(r => !r.sendKnown) ? '<span title="보낸 시점 값을 모르는 항목 제외">*</span>' : '') + ' · 지금 ' + mN(sum(list, r => r.usdNow)) + '</span></div>';
    return bar + (list.length ? uiPaged('ofh', list, r => ofCard(r, true), { unit: '곳' })
      : f.reason === '세일 참가금' ? '<div class="card empty"><b>아직 세일 참가금으로 고른 전송이 없어요</b>확인 필요에서 그 전송을 펼쳐 외부 → 세일 참가금을 고르거나, 일별 기록에서 그 줄을 눌러 고르면 여기 모여요</div>'
      : '<div class="card empty"><b>조건에 맞는 정리 내역이 없어요</b>필터를 넓혀 보세요</div>');
  }
  return {
    D0, EXPL, exUrl, mAlt, ofCatLbl, ofLkInput, ofLkLoad, ofLkOpt, ofName, saleBox, trChip, vOutflows, vUnmatched, xferBox, __late
  };
};
