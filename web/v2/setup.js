'use strict';
(function () {
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (s, r) => (r || document).querySelector(s);
  const suOwn = t => { const a = window.__tjSearchApi; try { return a && typeof a.ownNm === 'function' ? a.ownNm(t, 'w') : String(t); } catch (e) { return String(t); } };
  const LS = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) {  } }
  };
  const SS = {
    get(k) { try { return window.sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.sessionStorage.setItem(k, v); } catch (e) {  } }
  };

  const M64 = (1n << 64n) - 1n;
  const RC = ['0x1', '0x8082', '0x800000000000808a', '0x8000000080008000', '0x808b', '0x80000001', '0x8000000080008081', '0x8000000000008009',
    '0x8a', '0x88', '0x80008009', '0x8000000a', '0x8000808b', '0x800000000000008b', '0x8000000000008089', '0x8000000000008003',
    '0x8000000000008002', '0x8000000000000080', '0x800a', '0x800000008000000a', '0x8000000080008081', '0x8000000000008080', '0x80000001', '0x8000000080008008'].map(BigInt);
  const ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]];
  const rotl = (v, n) => (n === 0 ? v : (((v << BigInt(n)) | (v >> BigInt(64 - n))) & M64));
  function keccakF(s) {
    for (let r = 0; r < 24; r++) {
      const C = [], D = [];
      for (let x = 0; x < 5; x++) C[x] = s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20];
      for (let x = 0; x < 5; x++) D[x] = C[(x + 4) % 5] ^ rotl(C[(x + 1) % 5], 1);
      for (let i = 0; i < 25; i++) s[i] ^= D[i % 5];
      const B = new Array(25);
      for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) B[y + 5 * ((2 * x + 3 * y) % 5)] = rotl(s[x + 5 * y], ROT[x][y]);
      for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) s[x + 5 * y] = B[x + 5 * y] ^ ((~B[(x + 1) % 5 + 5 * y] & M64) & B[(x + 2) % 5 + 5 * y]);
      s[0] ^= RC[r];
    }
  }
  function keccak256(bytes) {
    const rate = 136, msg = Array.from(bytes); msg.push(1);
    while (msg.length % rate) msg.push(0);
    msg[msg.length - 1] |= 0x80;
    const s = new Array(25).fill(0n);
    for (let off = 0; off < msg.length; off += rate) {
      for (let i = 0; i < rate / 8; i++) { let v = 0n; for (let b = 7; b >= 0; b--) v = (v << 8n) | BigInt(msg[off + i * 8 + b]); s[i] ^= v; }
      keccakF(s);
    }
    const out = [];
    for (let i = 0; i < 4; i++) { let v = s[i]; for (let b = 0; b < 8; b++) { out.push(Number(v & 255n)); v >>= 8n; } }
    return out;
  }
  const hex = a => a.map(b => (b < 16 ? '0' : '') + b.toString(16)).join('');
  function toChecksum(addr) {
    const a = addr.toLowerCase().replace(/^0x/, '');
    const h = hex(keccak256(Array.from(a).map(c => c.charCodeAt(0))));
    return '0x' + Array.from(a).map((c, i) => (/[a-f]/.test(c) && parseInt(h[i], 16) >= 8 ? c.toUpperCase() : c)).join('');
  }
  const B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  function b58len(s) {
    let n = 0n;
    for (const c of s) { const i = B58.indexOf(c); if (i < 0) return -1; n = n * 58n + BigInt(i); }
    let len = 0; while (n > 0n) { n >>= 8n; len++; }
    return len + (s.length - s.replace(/^1+/, '').length);
  }
  function checkAddr(raw) {
    const a = String(raw || '').trim();
    if (!a) return null;
    if (/^0x/i.test(a)) {
      const b = a.slice(2);
      if (!/^[0-9a-fA-F]{40}$/.test(b)) return { err: 'EVM 주소는 0x + 16진수 40자예요 (지금 ' + b.length + '자)' };
      if (/^0+$/.test(b)) return { err: '0 주소는 추적할 수 없어요' };
      if (b !== b.toLowerCase() && b !== b.toUpperCase()) {
        if (toChecksum(a) !== '0x' + b) return { err: '체크섬 불일치 — 한 글자가 틀렸을 수 있어요. 원문을 다시 복사하세요' };
        return { kind: 'evm', addr: a, note: 'EVM · 체크섬 확인됨' };
      }
      return { kind: 'evm', addr: a, note: 'EVM · 체크섬 없는 주소(오타 주의)', warn: true };
    }
    if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a)) return { err: '지원하지 않는 주소예요 — EVM(0x…)·Solana 주소만 넣을 수 있어요' };
    if (b58len(a) !== 32) return { err: '지원하지 않는 주소예요 — EVM(0x…)·Solana 주소만 넣을 수 있어요' };
    return { kind: 'sol', addr: a, note: 'Solana 주소' };
  }

  const BECH = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  function bech32Ok(str, hrp) {
    const s0 = String(str || '');
    if (s0 !== s0.toLowerCase() && s0 !== s0.toUpperCase()) return false;
    const s1 = s0.toLowerCase();
    if (!s1.startsWith(hrp + '1')) return false;
    const data = s1.slice(hrp.length + 1);
    if (data.length < 7 || /[^qpzry9x8gf2tvdw0s3jn54khce6mua7l]/.test(data)) return false;
    const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    let chk = 1;
    const vals = Array.from(hrp).map(c => c.charCodeAt(0) >> 5).concat([0], Array.from(hrp).map(c => c.charCodeAt(0) & 31), Array.from(data).map(c => BECH.indexOf(c)));
    for (const v of vals) { const b = chk >>> 25; chk = (((chk & 0x1ffffff) << 5) ^ v) >>> 0; for (let i = 0; i < 5; i++) if ((b >>> i) & 1) chk = (chk ^ GEN[i]) >>> 0; }
    return chk === 1;
  }
  function checkPerpAddr(kind, raw, name) {
    const a = String(raw || '').trim();
    if (!a) return null;
    if (kind === 'dydx') {
      if (!/^dydx1[02-9ac-hj-np-z]{38}$/i.test(a)) return { err: 'dYdX 주소는 dydx1 로 시작하는 43자예요 (지금 ' + a.length + '자)' };
      return bech32Ok(a, 'dydx') ? { addr: a.toLowerCase(), note: 'dYdX 주소 확인됨' } : { err: 'dYdX 주소 체크섬 불일치 — 원문을 다시 복사하세요' };
    }
    const c = checkAddr(a);
    if (!c || c.err) return c;
    if (kind === 'evm' && c.kind !== 'evm') return { err: name + ' 은 0x… EVM 주소를 써요' };
    if (kind === 'sol' && c.kind !== 'sol') return { err: name + ' 는 Solana 주소를 써요' };
    return { addr: c.addr, note: c.note };
  }

  const ADDR_SPLIT = /[\s,;，；、]+/;
  const splitAddrs = raw => String(raw == null ? '' : raw).split(ADDR_SPLIT).filter(Boolean);
  const MAX_BATCH = 50;
  const ckMemo = new Map();
  const checkAddrM = t => { if (!ckMemo.has(t)) { if (ckMemo.size > 400) ckMemo.clear(); ckMemo.set(t, checkAddr(t)); } return ckMemo.get(t); };
  const wKey = c => (c.kind === 'sol' ? c.addr : c.addr.toLowerCase());
  const ADDR_SPLIT_G = new RegExp(ADDR_SPLIT.source, 'g');
  const W_SECRET = {
    key: '개인 키(16진수 64자)처럼 보이는 값이 있어요 — 칸을 비우세요. 주소만 필요하고 개인 키는 절대 입력하지 마세요. 이 입력은 저장하지 않아요',
    seed: '시드 문구(단어 12·24개)처럼 보여요 — 칸을 비우세요. 주소만 필요하고 시드·개인 키는 절대 입력하지 마세요. 이 입력은 저장하지 않아요'
  };
  function wSecret(raw) {
    const s = String(raw == null ? '' : raw);
    if (/[0-9a-fA-F]{64}/.test(s.replace(ADDR_SPLIT_G, ''))) return 'key';
    return splitAddrs(s).filter(t => /^[A-Za-z]{3,8}$/.test(t)).length >= 12 ? 'seed' : '';
  }
  function wAnalyze(raw) {
    const toks = splitAddrs(raw), have = {}, seen = new Set(), sel = Array.from(U.chains || []), secret = wSecret(raw);
    if (secret) {
      return { toks, items: toks.map(t => ({ t, st: 'bad', err: secret === 'key' ? '개인 키처럼 보이는 입력이 섞여 있어 저장하지 않아요' : '시드 문구처럼 보이는 입력이 섞여 있어 저장하지 않아요' })),
        save: [], multi: toks.length > 1, onlySol: false, needChain: false, secret };
    }
    ((U.st && U.st.wallets) || []).forEach(w => { have[w.kind === 'sol' ? w.address : String(w.address || '').toLowerCase()] = w; });
    const items = toks.map(t => {
      const c = checkAddrM(t);
      if (!c || c.err) return { t, st: 'bad', err: c ? c.err : '주소가 아니에요' };
      const k = wKey(c);
      if (seen.has(k)) return { t, st: 'dup', c };
      seen.add(k);
      const w = have[k];
      if (w) {
        const nc = c.kind === 'sol' ? [] : sel.filter(x => (w.chains || []).indexOf(x) < 0);
        return nc.length ? { t, st: 'more', c, w, newCh: nc } : { t, st: 'have', c, w };
      }
      return { t, st: c.warn ? 'warn' : 'ok', c };
    });
    const save = items.filter(x => x.st === 'ok' || x.st === 'warn' || x.st === 'more'), valid = items.filter(x => x.c);
    return { toks, items, save, multi: toks.length > 1, onlySol: valid.length > 0 && valid.every(x => x.c.kind === 'sol'),
      needChain: save.some(x => x.c.kind === 'evm') && !sel.length, secret: '' };
  }
  const W_IC = { ok: '✓', warn: '!', more: '+', have: '=', dup: '=', bad: '✗' };
  function wItemHTML(x) {
    const t = x.t.length > 90 ? x.t.slice(0, 88) + '…' : x.t, se = U.wErr && U.wErr[x.t];
    const txt = x.st === 'ok' ? (x.c.kind === 'sol' ? 'Solana 주소' : '체크섬 확인됨')
      : x.st === 'warn' ? '체크섬 없음 — 오타 주의(대소문자 섞인 원문이면 더 안전해요)'
      : x.st === 'more' ? '이미 등록됨 · 체인 추가: ' + x.newCh.map(chainName).join(' · ')
      : x.st === 'have' ? '이미 등록됨' + (x.w && x.w.label ? ' (' + x.w.label + ')' : '') + ' — 건너뛰어요'
      : x.st === 'dup' ? '중복 입력 — 한 번만 추가해요' : x.err;
    const txtH = x.st === 'have' ? '이미 등록됨' + (x.w && x.w.label ? ' (<span class="pvl" data-pk="w">' + esc(suOwn(x.w.label)) + '</span>)' : '') + ' — 건너뛰어요' : esc(txt);
    return '<li class="su-pi ' + x.st + '"><span class="su-pic" aria-hidden="true">' + W_IC[x.st] + '</span><div class="su-pib"><span class="su-pa num">' + esc(t) + '</span>'
      + (x.c ? ' <span class="pill ' + (x.c.kind === 'sol' ? 'ok' : 'a') + ' sm">' + (x.c.kind === 'sol' ? 'Solana' : 'EVM') + '</span>' : '')
      + '<div class="su-pis' + (x.st === 'have' ? ' pvl' : '') + '">' + txtH + '</div>' + (se && x.c && x.st !== 'have' && x.st !== 'dup' ? '<div class="su-pis su-pise">지난 저장 실패 · ' + esc(se) + '</div>' : '') + '</div></li>';
  }
  const W_HINT = '0x… (EVM·BSC 공용) 또는 Solana 주소 · 여러 개는 쉼표나 줄바꿈(Enter)으로 나눠 한 번에 넣을 수 있어요 · 개인 키·시드는 절대 입력하지 마세요 — 주소만 필요해요';
  function wMsgHTML(an) {
    if (!an.toks.length) return '<span class="cap">' + esc(W_HINT) + '</span>';
    const secret = an.secret ? '<div class="su-bad" role="alert"' + (an.multi ? ' style="margin-bottom:8px"' : '') + '>' + esc(W_SECRET[an.secret]) + '</div>' : '';
    if (!an.multi && an.secret) return secret;
    if (!an.multi) {
      const x = an.items[0];
      return x.st === 'bad' ? '<span class="su-bad">' + esc(x.err) + '</span>'
        : x.st === 'have' ? '<span class="su-bad pvl">이미 같은 체인으로 등록된 주소예요' + (x.w && x.w.label ? ' (<span class="pvl" data-pk="w">' + esc(suOwn(x.w.label)) + '</span>)' : '') + '</span>'
        : '<span class="' + (x.st === 'warn' ? 'su-warnt' : 'su-good') + '">' + esc(x.c.note) + (x.st === 'more' ? ' · 이미 등록된 주소 — 새 체인 추가: ' + esc(x.newCh.map(chainName).join(' · ')) : '') + '</span>';
    }
    const cnt = k => an.items.filter(x => x.st === k).length, n = an.save.length;
    const sum = ['추가 <b class="num">' + n + '</b>개'].concat(cnt('warn') ? ['체크섬 없음 ' + cnt('warn')] : [], cnt('have') ? ['이미 등록됨 ' + cnt('have')] : [],
      cnt('dup') ? ['중복 입력 ' + cnt('dup')] : [], cnt('bad') ? ['<span class="su-badt">오류 ' + cnt('bad') + ' — 고칠 때까지 칸에 남아요</span>'] : []).join(' · ');
    const shown = an.items.slice(0, 100);
    return secret
      + '<div class="su-mnote" role="note"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/></svg><span>여러 개는 추가한 뒤 목록에서 이름·메모를 붙여요</span></div>'
      + '<ul class="su-prev" aria-label="추가할 주소 미리 보기">' + shown.map(wItemHTML).join('') + (an.items.length > shown.length ? '<li class="su-pi have"><span class="su-pic" aria-hidden="true">…</span><div class="su-pib"><div class="su-pis">외 ' + (an.items.length - shown.length) + '개</div></div></li>' : '') + '</ul>'
      + '<div class="su-psum" aria-live="polite">' + sum + '</div>'
      + (n > MAX_BATCH ? '<div class="su-warnt pvx" style="margin-top:6px">한 번에 ' + MAX_BATCH + '개씩 넣어요 — 지금 ' + n + '개 · \'앞의 ' + MAX_BATCH + '개 먼저 추가\'를 누르면 나머지 ' + (n - MAX_BATCH) + '개는 칸에 남아 이어서 넣을 수 있어요</div>' : '')
      + wCapHTML(an)
      + (an.needChain ? '<div class="su-bad" style="margin-top:6px">아래에서 EVM 체인을 하나 이상 고르세요</div>' : '');
  }
  function wBtn(an) {
    if (!an.multi) return { t: U.busy.wadd ? '추가 중…' : '지갑 추가', dis: !!U.busy.wadd };
    const n = an.save.length;
    return { t: U.busy.wadd ? '추가 중…' : n > MAX_BATCH ? '앞의 ' + MAX_BATCH + '개 먼저 추가' : n ? '지갑 ' + n + '개 추가' : '추가할 주소 없음', dis: !!U.busy.wadd || !n || an.needChain };
  }
  function wCapHTML(an) {
    const cap = U.st && U.st.walletCap, T = U.tier;
    if (!cap) return '';
    if (!T && an.save.length) loadTier();
    const fresh = an.save.filter(x => x.st !== 'more').slice(0, MAX_BATCH), nNew = fresh.length, have = ((U.st && U.st.wallets) || []).length;
    let out = '';
    if (nNew && have + nNew > cap.max) out += '<div class="su-bad pvx" style="margin-top:6px">지갑은 최대 ' + cap.max + '개 — 지금 ' + have + '개 등록 · 새 주소 ' + nNew + '개 중 ' + Math.max(0, cap.max - have) + '개만 들어가요(안 쓰는 주소를 빼면 그만큼 더 넣을 수 있어요)</div>';
    else if (nNew) out += '<div class="cap pvx" style="margin-top:6px">추가하면 ' + (have + nNew) + ' / ' + cap.max + '개</div>';
    if (nNew && T && T.pairCost) {
      const add = {}, chs = Array.from(U.chains || []), nEvm = fresh.filter(x => x.c && x.c.kind === 'evm').length, nSol = nNew - nEvm;
      chs.forEach(c => { const pc = T.pairCost[c]; if (pc && nEvm) add[pc.prov] = (add[pc.prov] || 0) + pc.day * nEvm; });
      if (nSol) add.helius = (add.helius || 0) + nSol * 1440 * 1.5;
      const es = (T.budget || {}).etherscan, x = add.etherscan || 0;
      if (x) out += '<div class="cap pvx">새 주소는 처음 이력을 받는 동안 지금 주기예요 — 이더스캔 하루 +' + fmtN(x) + '콜' + (es ? ' (지금 예상 ' + fmtN(es.perDay) + ' → ' + fmtN(es.perDay + x) + ' / 상한 ' + fmtN(es.cap) + ')' : '')
        + ((es && es.perDay + x > es.cap) ? ' · <span class="su-badt">상한을 넘으면 확인 간격을 자동으로 늘려요</span>' : '') + ' · 이력을 다 받고 쉬는 주소가 되면 거의 0이에요</div>';
    }
    return out;
  }
  const NEWW = 'tj_new_wallets', NEWW_TTL = 2 * 3600 * 1000;
  function newW() { try { const v = JSON.parse(SS.get(NEWW) || 'null'); if (v && Array.isArray(v.keys) && Date.now() - v.ts < NEWW_TTL) return new Set(v.keys); } catch (e) {  } return new Set(); }
  function markNew(keys) { const s = newW(); keys.forEach(k => { if (k) s.add(String(k)); }); SS.set(NEWW, JSON.stringify({ ts: Date.now(), keys: Array.from(s).slice(-120) })); }
  function autoGrow(el) {
    if (!el || el.tagName !== 'TEXTAREA') return;
    el.style.height = 'auto';
    if (el.scrollHeight) el.style.height = Math.min(el.scrollHeight + 2, 240) + 'px';
  }

  const QR_ECC_M = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  const QR_BLK_M = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
  function qrRawModules(v) {
    let r = (16 * v + 128) * v + 64;
    if (v >= 2) { const n = Math.floor(v / 7) + 2; r -= (25 * n - 10) * n - 55; if (v >= 7) r -= 36; }
    return r;
  }
  function gfMul(x, y) { let z = 0; for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11D); z ^= ((y >>> i) & 1) * x; } return z & 255; }
  function rsDivisor(deg) {
    const r = new Array(deg).fill(0); r[deg - 1] = 1; let root = 1;
    for (let i = 0; i < deg; i++) {
      for (let j = 0; j < r.length; j++) { r[j] = gfMul(r[j], root); if (j + 1 < r.length) r[j] ^= r[j + 1]; }
      root = gfMul(root, 0x02);
    }
    return r;
  }
  function rsRemainder(data, div) {
    const r = new Array(div.length).fill(0);
    for (const b of data) { const f = b ^ r.shift(); r.push(0); div.forEach((c, i) => { r[i] ^= gfMul(c, f); }); }
    return r;
  }
  function qrEncode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let ver = 0;
    for (let v = 1; v <= 10; v++) {
      const cap = Math.floor(qrRawModules(v) / 8) - QR_ECC_M[v] * QR_BLK_M[v];
      if (4 + (v < 10 ? 8 : 16) + bytes.length * 8 <= cap * 8) { ver = v; break; }
    }
    if (!ver) throw new Error('QR 로 담기엔 긴 텍스트');
    const size = ver * 4 + 17, dataCap = Math.floor(qrRawModules(ver) / 8) - QR_ECC_M[ver] * QR_BLK_M[ver];
    const bits = [];
    const put = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    put(4, 4); put(bytes.length, ver < 10 ? 8 : 16); bytes.forEach(b => put(b, 8));
    put(0, Math.min(4, dataCap * 8 - bits.length)); put(0, (8 - bits.length % 8) % 8);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) { let b = 0; for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j]; data.push(b); }
    for (let p = 0xEC; data.length < dataCap; p ^= 0xEC ^ 0x11) data.push(p);
    const nb = QR_BLK_M[ver], ecl = QR_ECC_M[ver], raw = Math.floor(qrRawModules(ver) / 8);
    const nShort = nb - raw % nb, shortLen = Math.floor(raw / nb), div = rsDivisor(ecl), blocks = [];
    for (let i = 0, k = 0; i < nb; i++) {
      const dat = data.slice(k, k + shortLen - ecl + (i < nShort ? 0 : 1)); k += dat.length;
      const ecc = rsRemainder(dat, div);
      if (i < nShort) dat.push(-1);
      blocks.push(dat.concat(ecc));
    }
    const cw = [];
    for (let i = 0; i < blocks[0].length; i++) blocks.forEach(b => { if (b[i] !== -1) cw.push(b[i]); });
    const mod = [], fn = [];
    for (let y = 0; y < size; y++) { mod.push(new Array(size).fill(false)); fn.push(new Array(size).fill(false)); }
    const setF = (x, y, d) => { mod[y][x] = d; fn[y][x] = true; };
    for (let i = 0; i < size; i++) { setF(6, i, i % 2 === 0); setF(i, 6, i % 2 === 0); }
    const finder = (cx, cy) => {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy)), x = cx + dx, y = cy + dy;
        if (x >= 0 && x < size && y >= 0 && y < size) setF(x, y, d !== 2 && d !== 4);
      }
    };
    finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
    if (ver >= 2) {
      const n = Math.floor(ver / 7) + 2, step = Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2, pos = [6];
      for (let i = 0; i < n - 1; i++) pos.splice(1, 0, size - 7 - i * step);
      pos.forEach((y, i) => pos.forEach((x, j) => {
        if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0)) return;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setF(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }));
    }
    const drawFormat = mask => {
      const d = (0 << 3) | mask; let r = d;
      for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537);
      const b = ((d << 10) | r) ^ 0x5412, g = i => ((b >>> i) & 1) !== 0;
      for (let i = 0; i <= 5; i++) setF(8, i, g(i));
      setF(8, 7, g(6)); setF(8, 8, g(7)); setF(7, 8, g(8));
      for (let i = 9; i < 15; i++) setF(14 - i, 8, g(i));
      for (let i = 0; i < 8; i++) setF(size - 1 - i, 8, g(i));
      for (let i = 8; i < 15; i++) setF(8, size - 15 + i, g(i));
      setF(8, size - 8, true);
    };
    drawFormat(0);
    if (ver >= 7) {
      let r = ver; for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1F25);
      const b = (ver << 12) | r;
      for (let i = 0; i < 18; i++) { const bit = ((b >>> i) & 1) !== 0, a = size - 11 + i % 3, c = Math.floor(i / 3); setF(a, c, bit); setF(c, a, bit); }
    }
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) {
        const x = right - j, up = ((right + 1) & 2) === 0, y = up ? size - 1 - vert : vert;
        if (!fn[y][x] && i < cw.length * 8) { mod[y][x] = ((cw[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0; i++; }
      }
    }
    const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, x => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => x * y % 2 + x * y % 3 === 0,
      (x, y) => (x * y % 2 + x * y % 3) % 2 === 0, (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0];
    const applyMask = m => { for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && MASKS[m](x, y)) mod[y][x] = !mod[y][x]; };
    const penalty = () => {
      let p = 0, dark = 0;
      const line = get => {
        let run = 1, prev = get(0);
        for (let k = 1; k < size; k++) { const c = get(k); if (c === prev) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else { run = 1; prev = c; } }
        const s = Array.from({ length: size }, (_, k) => (get(k) ? '1' : '0')).join('');
        p += 40 * ((s.match(/(?=10111010000)/g) || []).length + (s.match(/(?=00001011101)/g) || []).length);
      };
      for (let y = 0; y < size; y++) { line(x => mod[y][x]); for (let x = 0; x < size; x++) if (mod[y][x]) dark++; }
      for (let x = 0; x < size; x++) line(y => mod[y][x]);
      for (let y = 0; y < size - 1; y++) for (let x = 0; x < size - 1; x++) { const c = mod[y][x]; if (c === mod[y][x + 1] && c === mod[y + 1][x] && c === mod[y + 1][x + 1]) p += 3; }
      const tot = size * size; p += (Math.ceil(Math.abs(dark * 20 - tot * 10) / tot) - 1) * 10;
      return p;
    };
    let best = 0, bestP = Infinity;
    for (let m = 0; m < 8; m++) { applyMask(m); drawFormat(m); const p = penalty(); if (p < bestP) { bestP = p; best = m; } applyMask(m); }
    applyMask(best); drawFormat(best);
    return mod;
  }
  function qrSVG(text, px) {
    const m = qrEncode(text), n = m.length, q = 4, tot = n + q * 2;
    let d = '';
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (m[y][x]) d += 'M' + (x + q) + ' ' + (y + q) + 'h1v1h-1z';
    return '<svg class="su-qr" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + tot + ' ' + tot + '" width="' + px + '" height="' + px + '" shape-rendering="crispEdges" role="img" aria-label="텔레그램 봇 연결 QR 코드"><rect width="' + tot + '" height="' + tot + '" fill="#fff"/><path d="' + d + '" fill="#000"/></svg>';
  }

  const EX_HELP = {
    upbit: { url: 'https://upbit.com/mypage/open_api_management', steps: ['업비트 웹 로그인 → 마이페이지 → Open API 관리', '권한은 <b>자산조회</b>만 체크 (주문하기·출금하기·입금하기는 체크하지 마세요)', '허용 IP 주소에 <b>이 서버의 공인 IP</b> 를 입력 (업비트는 IP 등록 필수)', 'Access Key·Secret Key 발급 — Secret 은 한 번만 보이니 바로 붙여넣으세요'], note: '키 유효기간(1년)이 지나면 다시 발급해야 해요.' },
    bithumb: { url: 'https://www.bithumb.com/react/api-support/management-api', steps: ['빗썸 웹 로그인 → 마이페이지 → API 관리 → <b>API 2.0</b> 키 생성', '권한은 <b>자산조회</b>만 선택 (주문·출금 제외)', '허용 IP 에 이 서버 공인 IP 등록', 'API Key·Secret Key 를 붙여넣기'], note: '구 API(1.0) 키는 지원하지 않아요.' },
    binance: { url: 'https://www.binance.com/en/my/settings/api-management', steps: ['Account → API Management → Create API → <b>System generated</b>', '권한은 <b>Enable Reading</b> 만 (Spot & Margin Trading·Futures·Withdrawals·Universal Transfer 모두 끔)', 'IP access restrictions → <b>Restrict access to trusted IPs only</b> → 이 서버 공인 IP', 'API Key·Secret Key 붙여넣기'], note: '저장할 때 키 권한을 확인해 거래·출금·이체 권한이 켜져 있으면 저장하지 않아요.' },
    bybit: { url: 'https://www.bybit.com/app/user/api-management', steps: ['Account & Security → API → Create New Key → <b>System-generated API Keys</b>', '<b>API Transaction</b> 대신 <b>Read-Only</b> 선택', 'IP 제한: <b>Only IPs with permissions granted</b> → 이 서버 공인 IP', 'API Key·Secret 붙여넣기'], note: '통합 거래 계정(UTA) 기준으로 조회해요.' },
    okx: { url: 'https://www.okx.com/account/my-api', steps: ['프로필 → API → Create API key', '권한은 <b>Read</b> 만 (Trade·Withdraw 체크 금지)', 'IP 주소 허용 목록에 이 서버 공인 IP', '만들 때 정한 <b>Passphrase</b> 도 함께 입력'], note: 'Passphrase 는 OKX 가 다시 보여주지 않으니 기억해 두세요.' },
    kucoin: { url: 'https://www.kucoin.com/account/api', steps: ['API Management → Create API → API Trading', '권한은 <b>General</b> 만 (Spot·Margin·Futures Trading, Transfer, Withdrawal 끔)', 'IP Restriction → 이 서버 공인 IP', 'API Key·Secret·<b>Passphrase</b> 입력'], note: '' },
    gate: { url: 'https://www.gate.io/myaccount/api_key_manage', steps: ['API Keys → Create API Key → <b>API v4 Key</b>', '권한: Spot·Wallet 을 <b>Read Only</b> 로 (나머지 끔)', 'IP 화이트리스트에 이 서버 공인 IP', 'API Key·Secret 붙여넣기'], note: '' }
  };
  const XP_HELP = {
    helius: { url: 'https://dashboard.helius.dev', why: 'Solana 지갑 수집에 필요해요 (무료 플랜으로 충분).', steps: ['dashboard.helius.dev 가입(무료)', 'API Keys 에서 키 복사 → 붙여넣기'] },
    etherscan: { url: 'https://etherscan.io/myapikey', why: 'EVM 지갑이 있으면 필수(무료) — Ethereum·Arbitrum·Polygon 거래를 빠르고 빠짐없이 받아요. 없으면 공개 노드(RPC)로만 받아 옛 기록이 늦게 채워져요(최신 거래는 바로 보여요).', steps: ['etherscan.io 가입(무료) → API Keys → Add', '키 하나로 여러 체인 조회(V2) — 붙여넣기'] },
    opensea: { url: 'https://docs.opensea.io/reference/api-keys', why: '선택 · 추천 — 넣으면 기타 자산 › NFT 의 EVM 바닥가를 오픈시에서 먼저 받아(최우선) 작은 컬렉션까지 NFT 추적이 더 원활해요. 없으면 코인게코(무료 데모 키 권장). 미검증(키 없이 공개 문서만 보고 연결).', steps: ['opensea.io 계정 → API 키 신청(무료)', '받은 키 붙여넣기'] },
    coingecko: { url: 'https://www.coingecko.com/en/developers/dashboard', why: '선택 · 무료 — 넣으면 코인게코 시세·DEX 토큰 시세·차트·원가 시세·NFT 바닥가를 키 한도로 받아 더 빠르고 덜 막혀요(바이낸스·바이빗 가격이 있는 코인은 그대로 거래소 가격 — 키 몫이 모자라거나 실패하면 그 조회만 무료(무키)로). 키 없으면 공용 무료 한도라 NFT 바닥가는 몇 시간 걸릴 수 있어요. 유료(Pro) 키도 그대로 넣으면 데모·프로를 자동으로 알아보고, 프로는 다른 곳과 같이 쓰는 키일 수 있어 플랜 한도의 10%(기본 · 25·50·80% 로 바꿀 수 있음)만 써요. 재시작 없이 바로 써요.', steps: ['coingecko.com 무료 가입 → Developers Dashboard', '+ Add New Key 로 Demo 키 만들기(무료) — 유료 플랜 키(Pro)가 있으면 그 키를 넣어도 돼요', '받은 키(CG-…) 붙여넣기 → 저장하면 데모·프로 자동 판별'] }
  };
  XP_HELP.nodereal = { url: 'https://dashboard.nodereal.io', why: '선택 · 무료 키로도 됨 — BSC 옛 기록(아카이브)을 빠르게 받아요(한 번에 5만 블록). 없으면 BSC 옛 기록은 무료 공개 노드로 천천히 받아요(최신 기록은 늘 공개 노드로 바로). Base 는 지원 안 해요.', steps: ['nodereal.io 가입(무료) → Dashboard → Create API Key', 'BSC 엔드포인트 주소 끝의 키만(…/v1/ 뒤) 붙여넣기'] };
  XP_HELP.ankr = { url: 'https://www.ankr.com/rpc/', why: 'EVM 지갑이 있으면 필수(무료 Freemium) — 오래 안 쓴 지갑에 들어온 토큰을 10분마다 빠르게 확인하고, BSC·Base 옛 기록(아카이브)을 키 하나로 받아요(한 번에 3천 블록). 같은 키로 지갑 토큰 찾기도 보조해요(Advanced API). 없으면 무료 공개 노드로만 받아 늦을 수 있어요. 무료 한도의 80% 아래로만 써요. 저장할 때 연결을 한 번 확인해요(키가 거부되면 저장하지 않아요).', steps: ['ankr.com 가입(무료 Freemium) → Projects 에서 API 키', 'rpc.ankr.com/…/ 뒤의 키만 붙여넣기 → 저장(연결 확인 1번)'] };
  XP_HELP.quicknode = { url: 'https://dashboard.quicknode.com', why: '선택 · 유료만(무료 등급 없음) — 이미 쓰는 유료 엔드포인트가 있으면 체인별 주소를 그대로 넣으세요(BSC·Base 아카이브 · 한 번에 1만 블록). 다른 곳에서 쓰던 키일 수 있어 기본은 월 한도의 10% 만 써요.', steps: ['QuickNode 대시보드 → Endpoints', 'BSC·Base 엔드포인트 주소(https://….quiknode.pro/…/)를 각 칸에 붙여넣기'] };
  XP_HELP.alchemy = { url: 'https://dashboard.alchemy.com/signup', why: 'EVM 지갑이 있으면 필수(무료) — 지갑이 한 번이라도 주고받은 토큰 전부와 지금 잔고를 찾아 오래 들고만 있던 토큰도 빠뜨리지 않아요(Base·Ethereum·Arbitrum 등). 없으면 옛 보유 토큰 찾기가 약해져요(탐색기 한 곳만). 무료 한도의 80% 아래로만 써요.', steps: ['dashboard.alchemy.com/signup 가입(무료)', 'Create new app → 네트워크는 전부 켠 채로(기본값) → API Key 복사', '키만(https://…/v2/ 뒤의 값) 붙여넣기 → 연결 테스트(Ethereum·Base 1번씩)'] };
  const NODE_KEYS = ['nodereal', 'ankr', 'quicknode', 'alchemy'];
  const EX_ORDER = ['upbit', 'bithumb', 'binance', 'bybit', 'okx', 'kucoin', 'gate'];
  const STEPS = [{ k: 'wallets', t: '지갑' }, { k: 'keys', t: '탐색기 키' }, { k: 'exchanges', t: '거래소' }, { k: 'telegram', t: '텔레그램' }, { k: 'finish', t: '표시·완료' }];
  const UNIT_KO = { evm: 'EVM 수집기', sol: 'Solana 수집기', bsc: 'BSC 수집기', core: '원장(core)', web: '웹' };

  const U = {
    st: null, err: null, open: false, step: 0, where: null, panelOpen: SS.get('tj_su_open') === '1',
    d: {}, chains: null, ex: null, xp: null, test: {}, ip: '', busy: {}, dpWait: {}, dpPoll: null,
    ack: {}, needAck: {}, perm: null,
    wRes: null, wErr: {},
    tg: { phase: 'idle', err: '', bot: null, link: '', start: '', left: 0, manual: false, poll: null }
  };

  const isLocked = () => !!(U.locked || (window.TJ && typeof window.TJ.isLocked === 'function' && window.TJ.isLocked()));
  async function load() {
    if (isLocked()) return;
    try {
      const r = await fetch('/api/setup/status', { cache: 'no-store' });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) return;
      const d = await r.json();
      if (isLocked()) return;
      if (!r.ok || !d.ok) throw new Error(d.error || 'HTTP ' + r.status);
      U.st = d; U.err = null;
      if (d.telegram && d.telegram.pending && U.tg.phase === 'idle') {
        Object.assign(U.tg, { phase: 'wait', bot: { username: d.telegram.pending.bot }, link: d.telegram.pending.link, start: d.telegram.pending.start });
        startPoll();
      }
      if (d.telegram && d.telegram.connected && U.tg.phase !== 'wait') U.tg.phase = 'done';
      if (!U.chains && d.chains) U.chains = new Set(d.chains.filter(c => ['eth', 'base', 'arbitrum', 'bsc'].indexOf(c.key) >= 0).map(c => c.key));
    } catch (e) { U.err = (e && e.message) || String(e); }
    try { window.dispatchEvent(new Event('tj:setup')); } catch (e) {  }
  }
  async function api(action, body) {
    if (isLocked()) return { ok: false, error: '잠겼어요 — 다시 로그인해 주세요' };
    for (let attempt = 0; attempt < 2; attempt++) {
      if (!U.st || !U.st.csrf) await load();
      let r, d;
      try {
        r = await fetch('/api/setup/' + action, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-TJ-CSRF': (U.st && U.st.csrf) || '' }, body: JSON.stringify(body || {}) });
        try { d = await r.json(); } catch (e) { d = null; }
      } catch (e) {
        if (attempt === 0) { await new Promise(res => setTimeout(res, 2500)); continue; }
        return { ok: false, error: '서버 연결 실패 — 웹이 재시작 중이면 잠시 후 다시' };
      }
      if (isLocked()) return { ok: false, error: '잠겼어요 — 다시 로그인해 주세요' };
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) return { ok: false, error: '로그인이 필요해요 — 로그인 화면으로 이동해요' };
      if (r.status === 403 && d && /CSRF/.test(d.error || '') && attempt === 0) { U.st = null; continue; }
      return d || { ok: false, error: 'HTTP ' + r.status };
    }
    return { ok: false, error: '요청 실패' };
  }
  function toast(msg, err, ms) {
    const t = $('#toast'); if (!t) return;
    t.innerHTML = '<div class="toast' + (err ? ' e' : '') + '">' + esc(msg) + '</div>';
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.innerHTML = ''; }, ms || (err ? 4600 : 2600));
  }
  const draft = (k, v) => { if (v === undefined) return U.d[k] || ''; U.d[k] = v; };

  const pill = (cls, t) => '<span class="pill ' + cls + '">' + esc(t) + '</span>';
  const chainName = k => ((U.st && U.st.chains) || []).concat([{ key: 'sol', name: 'Solana' }]).reduce((a, c) => (c.key === k ? c.name : a), k);

  function wResHTML() {
    const r = U.wRes;
    if (!r) return '';
    const parts = [r.added ? '<b>' + r.added + '개 추가했어요</b>' : '<b>새로 추가한 주소가 없어요</b>'];
    if (r.skipped) parts.push('건너뜀 ' + r.skipped + '개(이미 등록·중복)');
    if (r.left) parts.push('<span class="su-badt">칸에 남김 ' + r.left + '개 — 고친 뒤 다시 추가하세요</span>');
    const nameTip = U.open ? '이름은 마법사를 마친 뒤 설정 › 추적 지갑에서 이름을 누르면 바로 바꿀 수 있어요.' : '이름은 아래 추적 지갑 목록에서 이름을 누르면 바로 바꿀 수 있어요.';
    return '<div class="su-wres' + (r.added ? '' : ' none') + '" role="status">' + parts.join(' · ')
      + (r.fails.length ? '<ul class="su-wfail">' + r.fails.slice(0, 10).map(f => '<li><span class="num">' + esc(f.t.length > 46 ? f.t.slice(0, 44) + '…' : f.t) + '</span> — ' + esc(f.err) + '</li>').join('') + '</ul>' : '')
      + (r.added ? '<div class="cap" style="margin-top:4px">' + esc(nameTip) + ' 새 지갑은 ' + (U.st.apply && U.st.apply.runner ? '약 30초 안에 수집기가 다시 시작되면' : '수집기를 다시 시작하면') + ' 최근 ' + esc(U.st.backfillMonths) + '개월 거래부터 불러와요.'
        + (!U.open && document.getElementById('walCard') ? ' <button class="link" data-su="wgo">추적 지갑으로 가기</button>' : '') + '</div>' : '')
      + '</div>';
  }
  function walletsHTML(noList) {
    const st = U.st, ws = st.wallets || [];
    const an = wAnalyze(draft('w_addr')), wb = wBtn(an), nw = newW();
    const chips = (st.chains || []).filter(c => c && c.key && String(c.key)[0] !== '_').map(c => '<button class="su-chip' + (U.chains.has(c.key) ? ' on' : '') + '" data-su="chain" data-v="' + esc(c.key) + '" aria-pressed="' + U.chains.has(c.key) + '">' + esc(c.name) + '</button>').join('');
    let list = '';
    if (ws.length && !noList) {
      list = '<div class="su-list">' + ws.map(w => '<div class="su-row' + (nw.has(w.address) ? ' new' : '') + '"><div style="min-width:0;flex:1"><b class="pvl"' + (w.label ? ' data-pk="w"' : '') + '>' + esc(w.label ? suOwn(w.label) : '(이름 없음)') + '</b> ' + pill(w.kind === 'sol' ? 'ok' : 'a', w.kind === 'sol' ? 'Solana' : 'EVM')
        + (nw.has(w.address) ? ' <span class="pill w sm" title="이름은 설정 › 추적 지갑에서 이름을 누르면 바로 바꿀 수 있어요">새로 추가</span>' : '')
        + '<div class="su-addr num">' + esc(w.address) + '</div><div class="cap">' + w.chains.map(chainName).map(esc).join(' · ') + '</div>'
        + (w.reconDone && w.reconDone.length ? ' <span class="pill w sm" title="기초잔고 대조가 끝난 뒤 추가된 체인(' + esc(w.reconDone.map(chainName).join(', ')) + ') — 옛 기록 수집이 끝난 뒤 재구축(README › 백필)하면 이 지갑의 과거 보유분까지 맞춰져요">과거 보유분 재구축 필요</span>' : '')
        + '</div><button class="btn sm" data-su="wdel" data-v="' + esc(w.address) + '" aria-label="지갑 삭제">삭제</button></div>').join('') + '</div>';
    }
    return '<div class="su-sec"><div class="su-h">추적할 지갑</div><div class="cap su-p">주소만으로 온체인 거래를 읽어 매매일지를 만들어요. 서명·송금 권한은 필요 없고 요청하지도 않아요. 새 지갑은 최근 ' + esc(st.backfillMonths) + '개월 거래부터 자동으로 불러와요.</div>'
      + '<div class="su-form su-wform"><textarea class="field su-grow su-ta" rows="1" data-su-in="w_addr" placeholder="0x… 또는 Solana 주소 (여러 개 가능)" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="지갑 주소 — 여러 개는 쉼표·줄바꿈으로 구분" aria-describedby="suVmsg"></textarea>'
      + '<input class="field' + (an.multi ? ' hidden' : '') + '" id="suWLabel" style="width:170px" data-su-in="w_label" placeholder="이름 (예: 메인)" maxlength="24" aria-label="지갑 이름"></div>'
      + '<div class="su-vmsg" id="suVmsg">' + wMsgHTML(an) + '</div>'
      + '<div class="su-chains' + (an.onlySol ? ' hidden' : '') + '" id="suChains"><div class="cap" style="margin-bottom:6px">EVM 체인 선택 · 같은 주소를 체인별로 추적해요 <button class="link" data-su="chainAll">전체</button> · <button class="link" data-su="chainNone">해제</button></div><div class="su-chiprow">' + chips + '</div></div>'
      + '<div class="su-actions"><button class="btn pri" id="suWadd" data-su="wadd"' + (wb.dis ? ' disabled' : '') + '>' + esc(wb.t) + '</button><span class="cap su-kbd">Enter = 줄바꿈(다음 주소) · ⌘/Ctrl+Enter = 추가</span></div>'
      + wResHTML()
      + list + (ws.some(w => w.kind === 'sol') && st.solNeedsHelius && !st.explorers.helius.set ? '<div class="bnr w" style="margin-top:12px"><div><b>Solana 지갑은 Helius 키가 필요해요</b><div class="bd">다음 단계에서 무료 키를 넣으면 Solana 수집이 시작돼요.</div></div></div>' : '')
      + evmKeyBanner(st) + '</div>';
  }

  async function nodePlanSave(p, patch) {
    const n = U.st && U.st.nodes && U.st.nodes[p];
    if (!n || U.busy['np' + p]) return;
    const body = Object.assign({ provider: p, plan: n.plan, share: n.share, month: n.month == null ? null : n.month }, patch);
    U.busy['np' + p] = true; render();
    const r = await api('keys/nodeplan', body);
    U.busy['np' + p] = false;
    toast(r.ok ? n.name + (r.apply && r.apply.restart === false ? ' 설정을 바꿨어요 — 재시작 없이 바로 써요' : ' 사용 한도를 바꿨어요 — 수집기가 곧 다시 시작해요') : (r.error || '저장 실패'), !r.ok);
    await refreshStatus();
  }
  function fieldsHTML(gk, g, help) {
    const t = U.test[gk];
    const tr = t ? '<div class="su-test ' + (t.ok ? 'ok' : 'bad') + '">' + (t.ok ? '연결 성공 · ' : '실패 · ') + esc(t.detail || '') + (t.warn || []).map(w => '<div class="su-warnline">' + esc(w) + '</div>').join('') + '</div>' : '';
    return (help ? help : '') + '<div class="su-fields">' + g.fields.map(f => '<label class="su-fl"><span class="cap">' + esc(f.label) + (f.set ? ' · 저장됨 <span class="num">' + esc(f.masked) + '</span>' : '') + '</span>'
      + '<input class="field" type="password" autocomplete="off" spellcheck="false" data-su-in="k_' + esc(f.key) + '" placeholder="' + (f.set ? '바꾸려면 새 값 입력 (비우면 저장된 값 유지)' : esc(f.label) + ' 붙여넣기') + '" aria-label="' + esc(g.name + ' ' + f.label) + '"></label>').join('') + '</div>'
      + permHTML(gk, g)
      + '<div class="su-actions"><button class="btn" data-su="ktest" data-v="' + gk + '"' + (U.busy['t' + gk] ? ' disabled' : '') + '>' + (U.busy['t' + gk] ? '확인 중…' : '연결 테스트') + '</button>'
      + '<button class="btn pri" data-su="ksave" data-v="' + gk + '"' + (U.busy['s' + gk] ? ' disabled' : needAck(gk) && !U.ack[gk] ? ' disabled title="\'조회 권한만 켰음\'을 먼저 체크하세요"' : '') + '>' + (U.busy['s' + gk] ? (U.st.exchanges && U.st.exchanges[gk] ? '권한 확인 중…' : '확인 중…') : '저장') + '</button>' + (g.partial ? '<button class="btn danger" data-su="kdel" data-v="' + gk + '">삭제</button>' : '') + '</div>' + tr;
  }
  const needAck = gk => { const ex = U.st && U.st.exchanges && U.st.exchanges[gk]; return !!ex && !ex.permCheck; };
  function permHTML(gk, g) {
    const ex = U.st.exchanges && U.st.exchanges[gk];
    if (!ex) return '';
    const on = !!U.ack[gk];
    const saved = ex.perm && ex.perm.how ? '<div class="cap su-permnote">저장된 키 · ' + (ex.perm.how === 'api' ? '<span class="oktxt">조회 전용 자동 확인됨</span>' : '조회 전용 본인 확인') + (ex.perm.at ? ' <span class="num">' + esc(ago(ex.perm.at)) + '</span>' : '') + ' · <b>연결 테스트</b>(빈 칸)로 다시 검사할 수 있어요</div>' : '';
    const line = ex.permCheck
      ? '<div class="cap su-permnote">저장할 때 키 권한을 자동으로 확인해요 — <b>조회 말고 다른 권한(거래·출금·이체 등)이 켜져 있으면 저장하지 않아요.</b> 확인이 안 되면(연결 실패) 저장하지 않으니 잠시 뒤 다시 저장하세요.</div>'
      : '<div class="cap su-permnote">' + esc(g.name) + '는 API 로 키 권한을 확인할 수 없어요(자동 확인은 바이낸스·바이빗·OKX 만) — 발급 화면에서 <b>조회 권한만</b> 켰는지 직접 확인하고 체크하세요.</div>';
    const why = U.needAck[gk] && ex.permCheck ? '<div class="su-warnline">' + esc(U.needAck[gk]) + '</div>' : '';
    const box = needAck(gk) ? '<button type="button" class="su-ack' + (on ? ' on' : '') + '" role="checkbox" aria-checked="' + on + '" data-su="kack" data-v="' + gk + '"><i aria-hidden="true"></i><span>이 키는 <b>조회(읽기) 권한만</b> 켰어요 — 주문·거래·출금·이체 권한은 모두 껐어요</span></button>' : '';
    return '<div class="su-permbox">' + line + why + box + saved + '</div>';
  }
  const PERM_KIND = { trade: '거래', withdraw: '출금', transfer: '이체', other: '기타' };
  function permModalHTML() {
    const p = U.perm, h = EX_HELP[p.group] || {};
    const kick = p.stored ? '저장된 키 검사 결과 · 키는 그대로 두었어요' : '이 키는 저장하지 않았어요';
    return '<div class="su-bg su-permbg" role="alertdialog" aria-modal="true" aria-labelledby="suPermT" aria-describedby="suPermD"><div class="su-perm">'
      + '<div class="su-permhead"><svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4.5M12 17.5v.01"/></svg>'
      + '<div style="min-width:0"><div class="su-permkick">' + esc(kick) + '</div><h3 id="suPermT">' + esc(p.title || '위험한 권한이 켜져 있어요') + '</h3></div></div>'
      + '<div class="su-permsec"><b>켜져 있는 권한</b><ul>' + (p.danger || []).map(d => '<li><span class="pill e sm">' + esc(PERM_KIND[d.kind] || d.kind) + '</span> ' + esc(d.label) + '</li>').join('') + '</ul></div>'
      + '<div class="su-permsec"><b>왜 위험한가요</b><p id="suPermD">' + esc(p.why || '') + '</p></div>'
      + '<div class="su-permsec"><b>조회 전용 키로 다시 만드는 법</b><ol>' + (p.fix || []).map(x => '<li>' + esc(x) + '</li>').join('') + '</ol>'
      + (h.url ? '<a href="' + h.url + '" target="_blank" rel="noopener noreferrer">' + esc(p.name || '') + ' API 관리 페이지 ↗</a>' : '') + '</div>'
      + (p.stored ? '<div class="cap su-p">봇은 이 키로 조회만 하지만, 새로 만든 조회 전용 키를 저장하면 지금 키를 대체해요. 대체한 뒤 거래소에서 옛 키를 꼭 삭제하세요.</div>' : '')
      + '<div class="su-foot"><span class="sp"></span><button class="btn pri" data-su="permClose">알겠어요 — 조회 전용 키로 다시 넣을게요</button></div>'
      + '</div></div>';
  }
  function cgPlanHTML(g) {
    const p = g && g.set && g.plan;
    if (!p || !p.text) return '';
    const sh = p.plan === 'pro' && Array.isArray(p.shares) && p.shares.length
      ? '<div class="su-chiprow su-cgshare" role="group" aria-label="코인게코 프로 키 사용 비율" style="align-items:center;margin-top:6px"><span class="cap">사용 비율</span>'
        + p.shares.map(v => { const on = Number(v) === Number(p.share); return '<button class="su-chip' + (on ? ' on' : '') + '" data-su="cgshare" data-v="' + esc(v) + '" aria-pressed="' + on + '"' + (U.busy.cgshare ? ' disabled' : '') + '>' + esc(v) + '%</button>'; }).join('')
        + '</div><div class="cap" style="margin-top:4px">다른 곳에서 쓰던 유료 키인 경우가 많아 기본은 플랜 한도의 10% 만 써요(최대 80%) — 이번 달 몫을 남은 날에 고르게 나누고, 다른 곳 사용량이 많으면 더 줄여요</div>'
      : '';
    return '<div class="cap su-p su-cgplan">등급: <b>' + esc(p.text) + '</b>' + (p.budgetText ? '<br>' + esc(p.budgetText) : '') + sh + '</div>';
  }
  const freshKeySet = (st, k) => { const g = st && st.explorers && st.explorers[k]; return !!(g && (g.set || g.partial)); };
  function nodePlanHTML(st, k) {
    if (k === 'helius') return heliusFreshHTML(st);
    const n = st && st.nodes && st.nodes[k];
    if (!n) return '';
    const unit = n.unitKo || (n.unit === 'cu' ? 'CU' : '콜');
    const busy = !!U.busy['np' + k];
    const plan = n.paidOnly ? '' : '<div class="su-chiprow" role="group" aria-label="' + esc(n.name) + ' 요금제" style="align-items:center;margin-top:6px"><span class="cap">요금제</span>'
      + [['free', '무료 키'], ['paid', '유료 키']].map(([v, t]) => { const on = n.plan === v; return '<button class="su-chip' + (on ? ' on' : '') + '" data-su="nplan" data-p="' + esc(k) + '" data-v="' + v + '" aria-pressed="' + on + '"' + (busy ? ' disabled' : '') + '>' + t + '</button>'; }).join('') + '</div>';
    const paid = n.plan === 'paid'
      ? '<div class="su-chiprow" role="group" aria-label="' + esc(n.name) + ' 사용 비율" style="align-items:center;margin-top:6px"><span class="cap">사용 비율</span>'
        + (n.shares || []).map(v => { const on = Number(v) === Number(n.share); return '<button class="su-chip' + (on ? ' on' : '') + '" data-su="nshare" data-p="' + esc(k) + '" data-v="' + esc(v) + '" aria-pressed="' + on + '"' + (busy ? ' disabled' : '') + '>' + esc(v) + '%</button>'; }).join('') + '</div>'
        + '<label class="su-fl" style="margin-top:6px"><span class="cap">내 요금제 월 한도(' + unit + ' · 모르면 비워 두면 무료 한도 ' + fmtN(n.freeMonth) + ' 기준)</span>'
        + '<input class="field" inputmode="numeric" data-su-in="nm_' + esc(k) + '" placeholder="' + (n.month ? esc(fmtN(n.month)) : '예: 50000000') + '" aria-label="' + esc(n.name) + ' 월 한도"></label>'
        + '<div class="su-actions"><button class="btn sm" data-su="nmonth" data-p="' + esc(k) + '"' + (busy ? ' disabled' : '') + '>월 한도 저장</button></div>'
      : '';
    const use = (n.chains && n.chains.length ? '지금 쓰는 체인: ' + n.chains.map(c => c.toUpperCase()).join('·') + ' · ' : '')
      + (n.plan === 'paid' ? '월 한도 × ' + n.share + '%' : '무료 한도의 ' + n.pct + '%') + ' = 하루 약 ' + fmtN(n.perDay) + ' ' + unit
      + (typeof n.usedToday === 'number' ? ' · 오늘 쓴 양 ' + fmtN(n.usedToday) + (n.bursting ? ' · 버스트 중' : '') : '')
      + (typeof n.burstCap === 'number' ? ' · 실시간 하루 약 ' + fmtN(n.rtDay || 0) + ' · 오늘 백필 상한 ' + fmtN(n.burstCap) : '');
    const note = k === 'ankr' && n.pool !== false
      ? '쉬는 지갑에 들어온 토큰을 10분마다 확인하고(받음 탐지), 옛 기록은 처음 한 번만 채워요 — 최신 기록은 늘 공개 노드로 먼저 받고, 이 키는 받음 탐지·옛 기록·옛 거래 상세에 써요(진행·남은 시간 = 상단 상태 칩). 바꾸면 수집기가 자동으로 다시 시작해요.'
      : n.pool === false
      ? '지갑 토큰·잔고 찾기에만 써요 — 처음 한 번 전부 확인하고, 그 뒤엔 무료 노드로 움직임이 보인 지갑만 다시 물어요(감시·옛 기록은 무료 노드). 하루 몫을 다 쓰면 그날(UTC)은 쉬고 다음 날 이어서 해요. 키는 저장하면 바로 쓰고, 요금제를 바꾸면 수집기가 자동으로 다시 시작해요.'
      : '옛 기록은 처음 한 번만 채우고, 최신 기록은 늘 공개 노드로 먼저 받아요 — 이 키는 옛 기록·옛 거래 상세에만 써요(진행·남은 시간 = 상단 상태 칩). 바꾸면 수집기가 자동으로 다시 시작해요.';
    const fresh = n.burstX > 1 && freshKeySet(st, k) ? '<div class="su-chiprow" role="group" aria-label="' + esc(n.name) + ' 새로 받은 키" style="align-items:center;margin-top:6px">'
      + '<button class="su-chip' + (n.freshSince ? ' on' : '') + '" data-su="nfresh" data-p="' + esc(k) + '" aria-pressed="' + !!n.freshSince + '"' + (busy ? ' disabled' : '') + '>새로 받은 키(지난 사용 없음)</button>'
      + '<span class="cap">' + esc(n.freshSince ? n.freshSince + ' 에 새로 받은 키로 봐요 — 그 전 기록 없는 날은 0(키를 바꿔 저장하면 꺼져요)' : '다른 곳에서 쓰던 키가 아니면 켜세요 — 끄면 기록 없는 지난날을 평소 몫으로 셈(업그레이드 뒤 한 달은 버스트가 거의 없음)') + '</span></div>' : '';
    const bnote = n.burstX > 1 ? ' 백필·첫 전수 중엔 실시간 실측(× 1.5 · 앞으로 30일 몫)만 남기고 하루 몫의 ' + n.burstX + '배(열흘치)까지 당겨 써요 — 최근 31일 합은 월 한도의 ' + n.pct + '% 안 · 실시간이 늘면 백필이 바로 물러나요.' : '';
    return '<div class="cap su-p su-cgplan">' + esc(use) + plan + paid + fresh + '<div class="cap" style="margin-top:4px">' + esc(note + bnote) + '</div></div>';
  }
  function heliusFreshHTML(st) {
    if (!freshKeySet(st, 'helius')) return '';
    const h = st && st.heliusFresh;
    if (!h || !h.burst) return '';
    const busy = !!U.busy.nphelius, on = !!h.since;
    return '<div class="cap su-p su-cgplan"><div class="su-chiprow" role="group" aria-label="Helius 새로 받은 키" style="align-items:center;margin-top:6px">'
      + '<button class="su-chip' + (on ? ' on' : '') + '" data-su="nfresh" data-p="helius" aria-pressed="' + on + '"' + (busy ? ' disabled' : '') + '>새로 받은 키(지난 사용 없음)</button>'
      + '<span class="cap">' + esc(on ? h.since + ' 에 새로 받은 키로 봐요 — 그 전 기록 없는 날은 0(키를 바꿔 저장하면 꺼져요)' : '다른 곳에서 쓰던 키가 아니면 켜세요 — 끄면 기록 없는 지난날을 평소 몫으로 셈(업그레이드 뒤 한 달은 버스트가 거의 없음)') + '</span></div></div>';
  }
  function evmKeyBanner(st) {
    return etherscanBanner(st) + alchemyBanner(st) + ankrBanner(st);
  }
  function etherscanBanner(st) {
    if (!st || !st.evmNeedsKeys || !st.explorers.etherscan || st.explorers.etherscan.set) return '';
    return '<div class="bnr w" style="margin-top:12px"><div><b>EVM 지갑은 Etherscan 키가 필요해요(무료)</b><div class="bd">탐색기 키 단계에서 무료 키를 넣으면 거래를 빠르고 빠짐없이 받아요 — 없으면 공개 노드로만 받아 옛 기록이 늦게 채워져요(최신 거래는 바로 보여요).</div></div></div>';
  }
  function alchemyBanner(st) {
    if (!st || !st.evmNeedsAlchemy || !st.explorers.alchemy || st.explorers.alchemy.set) return '';
    return '<div class="bnr w" style="margin-top:12px"><div><b>EVM 지갑은 Alchemy 키가 필요해요(무료)</b><div class="bd">지갑이 주고받은 토큰 전부와 지금 잔고를 찾아 옛 보유 토큰을 빠뜨리지 않게 해요 — 없으면 옛 보유 토큰 찾기가 약해져요(탐색기 한 곳만). 거래 수집·감시는 그대로 돌아요.</div></div></div>';
  }
  function ankrBanner(st) {
    if (!st || !st.evmNeedsAnkr || !st.explorers.ankr || st.explorers.ankr.set) return '';
    return '<div class="bnr w" style="margin-top:12px"><div><b>EVM 지갑은 Ankr 키가 필요해요(무료)</b><div class="bd">오래 안 쓴 지갑에 들어온 토큰을 10분마다 확인하고 BSC·Base 옛 기록을 빨리 받아요 — 없으면 공개 노드로만 받아 늦을 수 있어요. 거래 수집·감시는 그대로 돌아요.</div></div></div>';
  }
  function xpPill(st, k, desc) {
    if (k === 'helius') return st.wallets.some(w => w.kind === 'sol') && st.solNeedsHelius ? pill('w', 'Solana 필수') : pill('g', 'Solana 지갑이 있으면 필수');
    if (k === 'etherscan') return st.evmNeedsKeys ? pill('w', 'EVM 필수') : pill('g', 'EVM 지갑이 있으면 필수');
    if (k === 'alchemy' && 'evmNeedsAlchemy' in st) return st.evmNeedsAlchemy ? pill('w', 'EVM 필수') : pill('g', 'EVM 지갑이 있으면 필수');
    if (k === 'ankr' && 'evmNeedsAnkr' in st) return st.evmNeedsAnkr ? pill('w', 'EVM 필수') : pill('g', 'EVM 지갑이 있으면 필수');
    if (desc) return '<span class="pill g su-xpd">' + esc('선택 · ' + desc) + '</span>';
    return pill('g', k === 'coingecko' ? '선택 · 무료' : '선택');
  }
  function xpName(name) {
    const s9 = String(name || ''), i = s9.indexOf(' (');
    if (i <= 0 || s9.slice(-1) !== ')') return { t: s9, d: '' };
    const d = s9.slice(i + 2, -1);
    return /—|,/.test(d) || d.length > 14 ? { t: s9.slice(0, i), d } : { t: s9, d: '' };
  }
  function keysHTML() {
    const st = U.st;
    return '<div class="su-sec"><div class="su-h">탐색기 API 키</div><div class="cap su-p">키는 이 서버의 <code>.env</code>(권한 600)에만 저장되고 화면에는 •••• 로만 보여요(값은 다시 표시하지 않음).</div>'
      + evmKeyBanner(st)
      + ['helius', 'etherscan', 'alchemy', 'ankr', 'coingecko', 'opensea'].concat(NODE_KEYS.filter(k => k !== 'alchemy' && k !== 'ankr')).filter(k => st.explorers[k]).map(k => {
        const g = st.explorers[k], h = XP_HELP[k], open = U.xp === k || (U.xp == null && k === 'helius'), nm = xpName(g.name);
        return '<div class="su-acc' + (open ? ' open' : '') + '"><button class="su-acch" data-su="xp" data-v="' + k + '" aria-expanded="' + open + '"' + (nm.d ? ' title="' + esc(g.name) + '"' : '') + '><b>' + esc(nm.t) + '</b>'
          + ' ' + xpPill(st, k, nm.d)
          + '<span class="sp"></span>' + pill(g.set ? 'ok' : 'g', g.set ? '저장됨' + (g.plan && g.plan.plan ? ' · ' + (g.plan.plan === 'pro' ? '프로' : '데모') : '') : '미설정') + '</button>'
          + (open ? '<div class="su-accb">' + fieldsHTML(k, g, cgPlanHTML(g) + nodePlanHTML(st, k) + '<div class="cap su-p">' + esc(h.why) + ' <a href="' + h.url + '" target="_blank" rel="noopener noreferrer">발급 페이지 ↗</a></div><ol class="su-ol">' + h.steps.map(s => '<li>' + esc(s) + '</li>').join('') + '</ol>') + '</div>' : '') + '</div>';
      }).join('') + '</div>';
  }
  function ago(ts) {
    if (!ts) return '';
    const s = Math.max(0, Date.now() / 1000 - ts);
    return s < 60 ? '방금 전' : s < 3600 ? Math.floor(s / 60) + '분 전' : s < 86400 ? Math.floor(s / 3600) + '시간 전' : Math.floor(s / 86400) + '일 전';
  }
  function depRowHTML(k, dp, keySet) {
    if (!dp && !keySet) return '';
    dp = dp || {};
    const busy = dp.running || dp.requested || U.dpWait[k];
    const head = dp.count ? '입금 주소 <b class="num">' + esc(dp.count) + '</b>개' + (dp.addresses && dp.addresses !== dp.count ? ' <span class="cap">(주소 ' + esc(dp.addresses) + '종 · 통화 ' + esc(dp.currencies) + '개)</span>' : '')
      : (keySet ? '입금 주소 수집 대기' : '입금 주소 없음');
    const when = dp.lastRefresh ? ' · 마지막 갱신 ' + esc(ago(dp.lastRefresh)) : (keySet ? ' · 곧 첫 수집' : '');
    const st9 = busy ? ' ' + pill('a', dp.running ? '수집 중…' : '요청됨') : dp.lastError ? ' <span class="pill w sm" title="' + esc(dp.lastError) + '">' + (dp.lastRefresh && dp.lastRefresh >= (dp.lastAttempt || 0) ? '일부 실패' : '실패 · 기존 주소 유지') + '</span>' : '';
    return '<div class="su-dep"><div style="min-width:0"><span>' + head + '</span><span class="cap">' + when + '</span>' + st9 + '</div><span class="sp"></span>'
      + (keySet ? '<button class="btn sm" data-su="dprefresh" data-v="' + esc(k) + '"' + (busy ? ' disabled' : '') + '>' + (busy ? '갱신 중' : '새로고침') + '</button>' : '') + '</div>';
  }
  function exchangesHTML() {
    const st = U.st;
    return '<div class="su-sec"><div class="su-h">거래소 API (선택 · 조회 전용)</div><div class="cap su-p">입금·체결·잔고를 가져와 온체인 전송과 짝지어 원가를 이어 줘요. <b>조회(읽기) 권한만</b> 켠 키를 쓰세요 — 이 봇은 주문·출금 API 를 호출하지 않아요.</div>'
      + '<div class="cap su-p">키를 저장하면 <b>내 계정 입금 주소</b>를 자동으로 모아요(첫 수집 즉시 · 하루 1회 · 새 코인·네트워크가 생기면 바로). 이 주소들로 보낸 전송은 거래소 입금으로 자동 인식하고, 거래소가 주소를 바꿔도 옛 주소는 지우지 않아요.</div>'
      + '<div class="su-ipbox"><div style="min-width:0"><b>이 서버의 공인 IP</b><div class="cap">거래소 키의 IP 화이트리스트에 넣을 값</div></div><span class="sp"></span>' + (U.ip ? '<code class="num">' + esc(U.ip) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(U.ip) + '">복사</button>' : '<button class="btn sm" data-su="ip">확인</button>') + '</div>'
      + EX_ORDER.map(k => {
        const g = st.exchanges[k], h = EX_HELP[k], open = U.ex === k;
        return '<div class="su-acc' + (open ? ' open' : '') + '"><button class="su-acch" data-su="ex" data-v="' + k + '" aria-expanded="' + open + '"><b>' + esc(g.name) + '</b><span class="sp"></span>' + pill(g.set ? 'ok' : g.partial ? 'w' : 'g', g.set ? '연결됨' : g.partial ? '일부 입력' : '미설정') + '</button>'
          + depRowHTML(k, (st.depaddr || {})[k], g.set)
          + (open ? '<div class="su-accb">' + fieldsHTML(k, g, '<ol class="su-ol">' + h.steps.map(s => '<li>' + s + '</li>').join('') + '</ol>' + (h.note ? '<div class="cap su-p">' + esc(h.note) + '</div>' : '') + '<div class="cap su-p"><a href="' + h.url + '" target="_blank" rel="noopener noreferrer">' + esc(g.name) + ' API 관리 페이지 ↗</a> · 저장하면 1분 안에 동기화가 시작돼요(재시작 불필요)</div>') + '</div>' : '') + '</div>';
      }).join('') + '</div>';
  }
  function tgHTML() {
    const st = U.st, T = U.tg, tg = st.telegram || {};
    let body = '';
    if (T.phase === 'done' || (tg.connected && T.phase !== 'wait')) {
      body = '<div class="su-tgdone"><div class="su-big">' + pill('ok', '연결됨') + '</div><div><b>@' + (tg.bot ? '<span class="pvl" data-pk="w">' + esc(suOwn(tg.bot)) + '</span>' : '?') + '</b> → ' + (tg.chatName ? '<span class="pvl" data-pk="w">' + esc(suOwn(tg.chatName)) + '</span>' : '채팅') + ' <span class="cap num">(' + esc(tg.chatMasked || '') + ')</span><div class="cap">목표가·손절 도달, 새 거래 분류, 검토 필요 알림이 이 채팅으로 와요 (시간당 최대 30통, 같은 종류는 묶어서). 어떤 알림을 받을지는 설정 › 알림(텔레그램)에서 골라요.</div></div></div>'
        + '<div class="su-actions"><button class="btn" data-su="tgtest">테스트 알림 보내기</button><button class="btn danger" data-su="tgoff">연결 해제</button></div>';
    } else if (T.phase === 'wait') {
      const mm = Math.max(0, Math.floor(T.left / 60)), ss = Math.max(0, T.left % 60);
      const pv9 = (() => { const a9 = window.__tjSearchApi; try { return !!(a9 && typeof a9.pvOn === 'function' && a9.pvOn()); } catch (e) { return false; } })();
      if (pv9) body = '<div class="su-tgwait"><div style="min-width:0;flex:1"><div class="su-h" style="margin:0 0 6px">텔레그램 연결 대기 중</div><div class="cap">가림 모드에서는 연결 코드를 숨겨요 — 가림을 끄면 QR·연결 버튼이 다시 보여요</div>'
        + '<div class="su-wait"><span class="su-spin" aria-hidden="true"></span>/start 기다리는 중 · <span class="num">' + mm + ':' + (ss < 10 ? '0' : '') + ss + '</span> 남음</div>'
        + '<div style="margin-top:10px"><button class="link" data-su="tgcancel">다른 토큰으로</button></div></div></div>';
      else body = '<div class="su-tgwait"><div class="su-qrbox">' + (T.link ? qrSVG(T.link, 176) : '') + '<div class="cap" style="text-align:center;margin-top:6px">휴대폰 카메라로 스캔</div></div>'
        + '<div style="min-width:0;flex:1"><div class="su-h" style="margin:0 0 6px">봇 <span class="num">@' + (T.bot && T.bot.username ? '<span class="pvl" data-pk="w">' + esc(suOwn(T.bot.username)) + '</span>' : '') + '</span> 에게 /start 를 보내세요</div>'
        + '<ol class="su-ol"><li>아래 버튼(또는 QR)으로 텔레그램에서 봇을 열어요</li><li><b>시작(Start)</b> 을 누르면 이 화면이 자동으로 채팅을 찾아요</li><li>찾으면 테스트 메시지를 보내고 저장해요</li></ol>'
        + '<div class="su-actions" style="margin-top:10px"><a class="btn pri" href="' + esc(T.link) + '" target="_blank" rel="noopener noreferrer">텔레그램에서 열기</a><button class="btn" data-su="copy" data-v="' + esc(T.start) + '">명령 복사: <span class="num">' + esc(T.start) + '</span></button></div>'
        + '<div class="su-wait"><span class="su-spin" aria-hidden="true"></span>/start 기다리는 중 · <span class="num">' + mm + ':' + (ss < 10 ? '0' : '') + ss + '</span> 남음</div>'
        + (T.err ? '<div class="su-bad" style="margin-top:8px">' + esc(T.err) + '</div>' : '')
        + '<div style="margin-top:10px"><button class="link" data-su="tgman">' + (T.manual ? '직접 입력 닫기' : 'chat_id 를 직접 입력할래요') + '</button> · <button class="link" data-su="tgcancel">다른 토큰으로</button></div>'
        + (T.manual ? '<div class="su-form" style="margin-top:8px"><input class="field su-grow" data-su-in="tg_chat" placeholder="chat_id (예: 123456789 / 그룹 -100…)" inputmode="text" aria-label="chat_id">'
          + (T.tok ? '' : '<input class="field su-grow" type="password" autocomplete="off" spellcheck="false" data-su-in="tg_mtoken" placeholder="봇 토큰 (chat_id 를 바꾸려면 다시 입력)" aria-label="텔레그램 봇 토큰">')
          + '<button class="btn" data-su="tgmanual">테스트 후 저장</button></div>' : '')
        + '</div></div>';
    } else {
      body = '<ol class="su-ol"><li>텔레그램에서 <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a> → <code>/newbot</code> → 이름·아이디 정하기</li><li>받은 토큰(<code>123456789:AA…</code>)을 붙여넣고 확인</li><li>알림 전용 <b>새 봇</b>을 쓰세요 — 다른 프로그램이 쓰는 봇은 업데이트를 뺏고 뺏겨 연결이 끊겨요</li></ol>'
        + '<div class="su-form"><input class="field su-grow" type="password" autocomplete="off" spellcheck="false" data-su-in="tg_token" placeholder="봇 토큰 붙여넣기" aria-label="텔레그램 봇 토큰"><button class="btn pri" data-su="tgval"' + (U.busy.tg ? ' disabled' : '') + '>' + (U.busy.tg ? '확인 중…' : '토큰 확인') + '</button></div>'
        + (T.err ? '<div class="su-bad" style="margin-top:8px">' + esc(T.err) + '</div>' : '');
    }
    return '<div class="su-sec"><div class="su-h">텔레그램 알림 (선택)</div><div class="cap su-p">연결하지 않아도 모든 기능이 동작해요. 알림은 연결하는 순간부터 새로 생긴 것만 보내요.</div>' + body + '</div>';
  }
  function applyHTML() {
    const a = U.st.apply || {};
    if (!a.runner) return '<div class="su-apply"><b>적용</b><div class="cap">수집기를 따로 실행 중이에요 — 지갑·키를 바꾼 뒤 한 번 재시작하세요 (거래소 키·텔레그램은 재시작 없이 1분 안에 반영).</div><div class="su-form" style="margin-top:8px"><code class="su-code su-grow">' + esc(a.manual) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(a.manual) + '">복사</button></div></div>';
    const us = a.units || {};
    const rl = a.mode === 'reload';
    return '<div class="su-apply"><b>적용 상태</b><div class="cap">' + (rl ? '지갑을 넣으면 약 30초 안에 수집기가 자동으로 다시 시작해요. 탐색기 키를 바꾸면 한 번 재시작하세요 (거래소 키·텔레그램은 재시작 없이 1분 안에 반영).' : '설정을 바꾸면 해당 수집기가 약 30초 안에 스스로 다시 시작해요. 거래소 키·텔레그램은 재시작 없이 1분 안에 반영돼요.') + '</div><div class="su-units">'
      + Object.keys(UNIT_KO).map(u => { const x = us[u] || {}; const cls = x.state === 'applied' ? 'ok' : x.state === 'pending' ? 'a' : x.state === 'manual' ? 'w' : x.state === 'waiting' ? 'g' : 'g';
        const t = x.state === 'applied' ? '적용됨' : x.state === 'pending' ? '적용 중' : x.state === 'manual' ? '재시작 필요' : x.state === 'waiting' ? '대기' : '—';
        return '<div class="su-unit"><span>' + UNIT_KO[u] + '</span>' + pill(cls, t) + (x.state === 'waiting' && x.why ? '<div class="cap">' + esc(x.why) + '</div>' : '') + '</div>'; }).join('') + '</div>'
      + (rl && Object.keys(us).some(u => (us[u] || {}).state === 'manual') ? '<div class="su-form" style="margin-top:8px"><code class="su-code su-grow">' + esc(a.manual) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(a.manual) + '">복사</button></div>' : '') + '</div>';
  }
  function finishHTML() {
    const st = U.st, cur = draft('cur') || st.prefs.currency || 'KRW', light = document.documentElement.getAttribute('data-theme') === 'light';
    const opt = (a, v, on, t, s) => '<button class="opt2' + (on ? ' on' : '') + '" data-su="' + a + '" data-v="' + v + '" aria-pressed="' + on + '"><b>' + t + '</b><span>' + s + '</span></button>';
    const exN = EX_ORDER.filter(k => st.exchanges[k].set).length;
    const rows = [['지갑', st.wallets.length ? st.wallets.length + '개 주소' : '없음 — 나중에 설정 탭에서 추가', st.wallets.length > 0],
      ['Helius (Solana)', st.explorers.helius.set ? '저장됨' : (st.wallets.some(w => w.kind === 'sol') ? '필요 — Solana 수집 대기' : '선택'), st.explorers.helius.set],
      ['Etherscan', st.explorers.etherscan.set ? '저장됨' : (st.evmNeedsKeys ? '필요 — EVM 지갑이 있어요(무료 키)' : '없음 (EVM 지갑이 생기면 필요)'), st.explorers.etherscan.set],
    ].concat(st.explorers.alchemy ? [['Alchemy', st.explorers.alchemy.set ? '저장됨' : (st.evmNeedsAlchemy ? '필요 — EVM 지갑이 있어요(무료 키)' : '없음 (EVM 지갑이 생기면 필요)'), st.explorers.alchemy.set]] : []).concat(
      st.explorers.ankr && 'evmNeedsAnkr' in st ? [['Ankr', st.explorers.ankr.set ? '저장됨' : (st.evmNeedsAnkr ? '필요 — EVM 지갑이 있어요(무료 키)' : '없음 (EVM 지갑이 생기면 필요)'), st.explorers.ankr.set]] : []).concat([
      ['거래소', exN ? exN + '곳 연결' : '없음 (온체인만)', exN > 0], ['텔레그램', st.telegram.connected ? '@' + (st.telegram.bot || '') + ' 연결됨' : '연결 안 함', st.telegram.connected]]);
    return '<div class="su-sec"><div class="su-h">표시</div><div class="cap" style="margin:10px 0 8px">기준 통화</div><div class="opts">' + opt('cur', 'KRW', cur === 'KRW', 'KRW', '업비트 USDT 환산') + opt('cur', 'USD', cur === 'USD', 'USD', '달러 원가 기준') + '</div>'
      + '<div class="cap" style="margin:14px 0 8px">테마</div><div class="opts">' + opt('theme', 'dark', !light, '다크', '기본') + opt('theme', 'light', light, '라이트', '밝은 배경') + '</div></div>'
      + '<div class="su-sec"><div class="su-h">요약</div>' + rows.map(r => '<div class="kv"><span>' + esc(r[0]) + '</span><span class="' + (r[2] ? 'oktxt' : 'mut') + '">' + esc(r[1]) + '</span></div>').join('') + evmKeyBanner(st) + applyHTML() + '</div>';
  }
  const PERP_FMT = { evm: '0x… EVM 주소', sol: 'Solana 주소', dydx: 'dydx1… 주소' };
  function perpDex() { const P = (U.st && U.st.perp) || {}, ds = P.dexes || []; return ds.find(d => d.key === U.pdex) || ds[0] || null; }
  function perpVmsg(d, raw) {
    const c = d ? checkPerpAddr(d.kind, raw, d.name) : null;
    return !c ? '<span class="cap">' + esc(d ? d.name + ' — ' + PERP_FMT[d.kind] : '') + ' · 개인 키·시드는 절대 입력하지 마세요 — 주소만 필요해요</span>'
      : c.err ? '<span class="su-bad">' + esc(c.err) + '</span>' : '<span class="su-good">' + esc(c.note) + '</span>';
  }
  function perpHTML() {
    const P = (U.st && U.st.perp) || {}, ds = P.dexes || [], ws = P.wallets || [], stt = P.state || {};
    if (P.error) return '<div class="su-sec"><div class="su-h">퍼프 덱스</div><div class="bnr w"><div><b>퍼프 덱스 설정을 읽지 못했어요</b><div class="bd">' + esc(P.error) + '</div></div></div></div>';
    const d = perpDex();
    const chips = ds.map(x => '<button class="su-chip' + (d && d.key === x.key ? ' on' : '') + '" data-su="pdex" data-v="' + esc(x.key) + '" aria-pressed="' + !!(d && d.key === x.key) + '">' + esc(x.name) + '</button>').join('');
    const ago9 = ts => (ts ? '마지막 수집 ' + ago(ts) : '수집 대기');
    const list = ws.length ? '<div class="su-list">' + ws.map(w => {
      const s9 = ((stt[w.dex] || {}).accts || {})[w.address] || {}, wait = (stt[w.dex] || {}).wait;
      const stH = s9.err || wait ? '<span class="pill w sm" title="' + esc(s9.err || wait) + '">' + (s9.ts ? '지연' : '오류') + '</span> <span class="cap">' + esc(String(s9.err || wait).slice(0, 60)) + '</span>'
        : '<span class="cap">' + esc(ago9(s9.ts)) + (s9.ts && s9.equity != null ? ' · 계정 가치 $' + esc(Number(s9.equity).toLocaleString('en-US', { maximumFractionDigits: 2 })) : '') + '</span>';
      return '<div class="su-row"><div style="min-width:0;flex:1"><b class="pvl"' + (w.label ? ' data-pk="w"' : '') + '>' + esc(w.label ? suOwn(w.label) : '(이름 없음)') + '</b> ' + pill('a', w.name)
        + '<div class="su-addr num">' + esc(w.address) + '</div><div>' + stH + (s9.unk ? ' <span class="cap" title="Lighter 체결 중 방향을 판정하지 못해 손익을 기록하지 않은 건수">· 손익 판정 못 한 체결 ' + esc(s9.unk) + '건</span>' : '') + '</div></div>'
        + '<button class="btn sm" data-su="pdel" data-v="' + esc(w.dex + '|' + w.address) + '" aria-label="퍼프 덱스 주소 삭제">삭제</button></div>';
    }).join('') + '</div>' : '';
    return '<div class="su-sec"><div class="su-h">퍼프 덱스 (선택 · 주소만)</div>'
      + '<div class="cap su-p">탈중앙 선물 거래소(퍼프 덱스) 주소를 넣으면 <b>현재 포지션·거래 내역·펀딩·청산</b>을 선물 화면에 거래소 선물과 나란히 보여 줘요. 실현 손익·펀딩·수수료는 매매일지·세금 명세의 선물 정산에 같은 규칙으로 들어가요(USD 기준 · 원화 = 정산 시각 환율). 키·서명은 필요 없고 요청하지도 않아요(공개 조회).</div>'
      + '<div class="cap su-p">덱스에 맡긴 담보·계정 가치는 총자산에 더하지 않아요(표시 전용 — Rabby 가 이미 잡는 경우 이중 계산 방지). 새 주소는 저장 후 15초 안에 수집을 시작하고, 옛 기록은 수집 시작일부터 받을 수 있는 만큼 몇 주기에 나눠 받아요.</div>'
      + '<div class="su-chiprow" role="group" aria-label="퍼프 덱스 고르기" style="margin-bottom:10px">' + chips + '</div>'
      + '<div class="su-form"><input class="field su-grow" data-su-in="p_addr" placeholder="' + esc(d ? d.name + ' 주소 (' + PERP_FMT[d.kind] + ')' : '주소') + '" autocomplete="off" spellcheck="false" aria-label="퍼프 덱스 주소">'
      + '<input class="field" style="width:170px" data-su-in="p_label" placeholder="이름 (예: 메인)" maxlength="24" aria-label="퍼프 덱스 주소 이름"></div>'
      + '<div class="su-vmsg" id="suPvmsg">' + perpVmsg(d, draft('p_addr')) + '</div>'
      + '<div class="su-actions"><button class="btn pri" data-su="padd"' + (U.busy.padd || !d ? ' disabled' : '') + '>주소 추가</button></div>'
      + list
      + '<div class="cap su-p" style="margin-top:12px">주소만으로는 못 읽는 곳: Aster·Paradex·GRVT·edgeX(덱스 API 키·서명 필요) · Drift(공개 데이터 API 응답 없음) · Vertex(종료). 덱스별로 받는 범위·못 받는 것은 <b>설정 › 수집 한계 › 거래소·체인별 한계 정리 › 퍼프 덱스</b>에 적어 두었어요.</div></div>';
  }
  const SEC = { wallets: walletsHTML, perp: perpHTML, keys: keysHTML, exchanges: exchangesHTML, telegram: tgHTML, finish: finishHTML };

  function wizardHTML() {
    const st = U.st, s = STEPS[U.step];
    const nav = STEPS.map((x, i) => '<button class="su-step' + (i === U.step ? ' on' : '') + (i < U.step ? ' done' : '') + '" data-su="goto" data-v="' + i + '"' + (i === U.step ? ' aria-current="step"' : '') + '><i>' + (i + 1) + '</i><span>' + x.t + '</span></button>').join('');
    const needW = s.k === 'wallets' && !st.wallets.length;
    return '<div class="su-bg" role="dialog" aria-modal="true" aria-labelledby="suTitle"><div class="su-wiz" tabindex="-1">'
      + '<div class="su-top"><div class="logo"><i></i><span id="suTitle">처음 설정</span></div>' + (st.demo ? pill('w', '데모 모드') : '') + '<span class="sp"></span><button class="iconbtn" data-su="close" aria-label="닫기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>'
      + '<div class="su-intro cap">온체인 지갑과 거래소 기록을 모아 매매일지·손익을 자동으로 만들어요. 모든 데이터는 이 서버에만 저장되고, 화면은 이 컴퓨터(또는 테일넷)에서만 열려요.</div>'
      + '<nav class="su-steps" aria-label="설정 단계">' + nav + '</nav>'
      + '<div class="su-body">' + SEC[s.k]() + '</div>'
      + '<div class="su-foot">' + (U.step > 0 ? '<button class="btn" data-su="prev">이전</button>' : '<span></span>') + '<span class="sp"></span>'
      + (U.step < STEPS.length - 1 ? (s.k !== 'wallets' ? '<button class="btn" data-su="next">건너뛰기</button>' : '') + '<button class="btn pri" data-su="next"' + (needW ? ' disabled title="지갑을 하나 이상 추가하세요"' : '') + '>다음</button>'
        : '<button class="btn pri" data-su="finish">설정 완료 · 대시보드로</button>') + '</div>'
      + (needW ? '<div class="su-skip"><button class="link" data-su="later">나중에 할게요 (설정 탭에서 언제든 가능)</button></div>' : '')
      + '</div></div>';
  }
  const TIER_SHORT = ['지금 주기', '1시간마다'];
  const PROV_NAME = p => p === 'etherscan' ? '이더스캔' : p === 'helius' ? '헬리우스(Solana)' : /^blockscout:/.test(p) ? '블록스카웃 ' + chainName(p.split(':')[1]) : /^rpc:/.test(p) ? '공개 RPC ' + chainName(p.split(':')[1]) : p;
  const fmtN = n => (n == null ? '—' : Math.round(n).toLocaleString('ko-KR'));
  function inSec(ts) { const s = Math.round(ts - Date.now() / 1000); return s <= 60 ? '곧' : s < 3600 ? Math.round(s / 60) + '분 뒤' : s < 86400 ? Math.round(s / 3600) + '시간 뒤' : Math.round(s / 86400) + '일 뒤'; }
  async function loadTier(force, q) {
    if (isLocked() || U.tierBusy) return;
    if (!force && U.tier && Date.now() - U.tierAt < 60000) return;
    if (!force && U.tierErrAt && Date.now() - U.tierErrAt < Math.min(60000, 5000 * Math.pow(2, Math.max(0, (U.tierErrN || 1) - 1)))) return;
    U.tierBusy = true;
    try {
      const r = await fetch('/api/setup/tier' + (q || ''), { cache: 'no-store' });
      let d = null; try { d = await r.json(); } catch (e) { d = null; }
      if (isLocked()) { U.tierBusy = false; return; }
      if (d && d.ok) { U.tier = d; U.tierAt = Date.now(); U.tierErr = ''; U.tierErrN = 0; U.tierErrAt = 0; } else { U.tierErr = (d && d.error) || ('HTTP ' + r.status); U.tierErrN = (U.tierErrN || 0) + 1; U.tierErrAt = Date.now(); }
    } catch (e) { if (isLocked()) { U.tierBusy = false; return; } U.tierErr = '연결 실패'; U.tierErrN = (U.tierErrN || 0) + 1; U.tierErrAt = Date.now(); }
    U.tierBusy = false;
    if (!(document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-su-in'))) fill();
  }
  function tierRows() {
    const T = U.tier || {}, lab = {};
    ((U.st && U.st.wallets) || []).forEach(w => { lab[w.kind === 'sol' ? w.address : String(w.address).toLowerCase()] = w; });
    return Object.keys(T.addrs || {}).map(k => ({ k, w: lab[k], pairs: T.addrs[k] })).filter(r => r.w)
      .sort((a, b) => Math.min(...a.pairs.map(p => p.t)) - Math.min(...b.pairs.map(p => p.t)) || String(a.w.label).localeCompare(String(b.w.label)));
  }
  function periodTxt(sec) { sec = Math.round(sec || 0); return sec >= 120 ? Math.round(sec / 60) + '분' : sec + '초'; }
  function pairChip(p) {
    const T = U.tier || {}, ht = (T.holdText || {})[p.h] || '';
    const HS = { code: '계약·위임', hist: '이력 받는 중', boot: '준비 중', nosent: '확인 중', req: '확인 요청됨', path: '수집 방식상', off: '꺼짐' };
    const sc9 = (T.scopes || {})[p.c] || {}, slow9 = !p.h && !p.e && p.t === 0 && sc9.period && sc9.basePoll && sc9.period > sc9.basePoll * 1.01;
    const lbl = p.h ? '지금 주기' + (HS[p.h] ? '(' + HS[p.h] + ')' : '') : p.e ? '빈 지갑 · 1시간마다' : (slow9 ? periodTxt(sc9.period) + '마다' : (TIER_SHORT[p.t] || '')) + (p.f ? ' · 옛 기록 채우는 중' : '');
    return '<span class="pill ' + (p.t === 0 ? 'ok' : 'g') + ' sm su-tc pvx" title="' + esc(chainName(p.c) + ' · ' + lbl + (ht ? ' — ' + ht : '') + (p.full ? ' · 마지막 확인 ' + ago(p.full) : '') + (p.f ? ' · 처음 넣은 지갑은 옛 기록부터 채워서, 첫날은 새 거래 확인이 평소보다 늦을 수 있어요' : '')) + '">' + esc(chainName(p.c)) + ' · ' + esc(lbl) + (p.wake ? ' · 확인 중' : '') + '</span>';
  }
  function tierWHTML(el) {
    const T = U.tier, k0 = el && el.getAttribute('data-w') || '';
    if (!T) { loadTier(); return '<div class="cap">' + (U.tierErr ? '확인 주기 정보를 못 불러왔어요 · ' + esc(U.tierErr) + ' <button class="link" data-su="tload">다시</button>' : '확인 주기 불러오는 중…') + '</div>'; }
    const k = /^0x/i.test(k0) ? k0.toLowerCase() : k0, ps = (T.addrs || {})[k] || [];
    if (!ps.length) return '<div class="cap">확인 주기 — 수집기가 이 주소를 아직 장부에 올리지 않았어요(다음 주기에)</div>';
    const rest = ps.filter(p => p.t > 0 && !p.h), lastFull = Math.max(0, ...ps.map(p => p.full || 0));
    const nxt = rest.map(p => p.nextAct).filter(Boolean);
    return '<div class="su-tw pvx"><div class="cap su-twh">확인 주기 · ' + (rest.length ? '쉬는 체인 ' + rest.length + '/' + ps.length + (nxt.length ? ' · 다음 점검 ' + inSec(Math.min(...nxt)) : '') : '모든 체인 지금 주기') + (lastFull ? ' · 마지막 전체 확인 ' + esc(ago(lastFull)) : '') + (ps.some(p => p.f) ? ' · 처음 넣은 지갑은 옛 기록부터 채워서, 첫날은 새 거래 확인이 평소보다 늦을 수 있어요' : '') + '</div>'
      + '<div class="su-tcs">' + ps.map(pairChip).join('') + '</div>'
      + (rest.length ? '<button class="btn sm" data-su="tcheck" data-v="' + esc(k) + '">지금 확인</button> <span class="cap">다음 수집 주기에 이 주소를 탐색기로 한 번 확인해요</span>' : '') + '</div>';
  }
  function budgetRows(T, extra) {
    const b = T.budget || {}, keys = Object.keys(b);
    const main = keys.filter(k => b[k].limit), pub = keys.filter(k => !b[k].limit);
    const row = k => {
      const e = b[k], add = extra && extra[k] || 0, v = e.perDay + add, cap = e.cap || 0, pct = cap ? Math.min(100, Math.round(100 * v / e.limit)) : 0;
      return '<div class="su-brow"><div class="su-brh"><b>' + esc(PROV_NAME(k)) + '</b><span class="num">' + fmtN(v) + ' / ' + fmtN(e.limit) + '<span class="cap"> 하루</span></span></div>'
        + '<div class="su-bbar" role="img" aria-label="' + esc(PROV_NAME(k) + ' 예상 ' + pct + '% · 상한 ' + T.budgetPct + '%') + '"><i class="' + (v > cap ? 'o' : '') + '" style="width:' + pct + '%"></i><s style="left:' + T.budgetPct + '%"></s></div>'
        + '<div class="cap">' + (add ? '추가 전 ' + fmtN(e.perDay) + ' → 추가 직후 ' + fmtN(v) + ' · ' : '') + '상한(' + T.budgetPct + '%) ' + fmtN(cap) + (v > cap ? ' · <span class="su-badt">넘어요 — 확인 간격을 자동으로 늘려요</span>' : '') + '</div></div>';
    };
    const pubSum = pub.reduce((a, k) => a + b[k].perDay, 0);
    return main.map(row).join('')
      + (pub.length ? '<div class="cap su-bpub">공개 RPC·블록스카웃 ' + pub.length + '곳 · 하루 합 약 ' + fmtN(pubSum) + '콜 — 공표 하루 한도가 없는 곳이라 노드별 속도 제한(게이트)으로 천천히 불러요'
        + ' <button class="link" data-su="tpub" aria-expanded="' + !!U.tierPub + '">' + (U.tierPub ? '접기' : '곳별 보기') + '</button></div>'
        + (U.tierPub ? '<ul class="su-bpl">' + pub.sort((x, y) => b[y].perDay - b[x].perDay).map(k => '<li>' + esc(PROV_NAME(k)) + ' <span class="num">' + fmtN(b[k].perDay) + '</span></li>').join('') + '</ul>' : '') : '');
  }
  function tierHTML() {
    const T = U.tier;
    if (!T) { loadTier(); return '<div class="cap">' + (U.tierErr ? '확인 주기 정보를 못 불러왔어요 · ' + esc(U.tierErr) + ' <button class="link" data-su="tload">다시</button>' : '확인 주기 불러오는 중…') + '</div>'; }
    loadTier();
    const all = [].concat(...Object.values(T.addrs || {})), cnt = TIER_SHORT.map(() => 0);
    all.forEach(p => { cnt[p.h ? 0 : Math.min(TIER_SHORT.length - 1, p.t)]++; });
    const holds = {}; all.filter(p => p.h).forEach(p => { holds[p.h] = (holds[p.h] || 0) + 1; });
    const cap = T.cap || {}, es = T.esToday || {}, hl = T.helToday || {}, sc = Object.values(T.scopes || {}), nF = all.filter(p => p.f).length;
    const gate = sc.some(x => x.gate), str = Math.max(1, ...sc.map(x => x.stretch || 1));
    const tiles = '<div class="su-ttiles"><div><b class="num">' + fmtN(cap.n) + '<span class="cap">/' + fmtN(cap.max) + '</span></b><span>등록 주소</span></div>'
      + '<div><b class="num">' + fmtN(all.length - cnt[0]) + '<span class="cap">/' + fmtN(all.length) + '</span></b><span>쉬는 주소·체인</span></div>'
      + '<div><b class="num">' + fmtN(es.n) + '</b><span>이더스캔 오늘(UTC)</span></div></div>';
    const steps = '<div class="su-tsteps">' + cnt.map((n, i) => '<span class="pill ' + (i === 0 ? 'ok' : 'g') + ' sm">' + TIER_SHORT[i] + ' <b class="num">' + n + '</b></span>').join('') + '</div>'
      + (Object.keys(holds).length ? '<div class="cap">지금 주기 이유 · ' + Object.keys(holds).map(h => esc((T.holdText || {})[h] || h) + ' ' + holds[h]).join(' · ') + '</div>' : '')
      + ((nF || hl.fillFirst) ? '<div class="cap">옛 기록 채우는 중' + (nF ? ' ' + nF + '곳' : '') + ' — 하루 한도 안에서 실시간 확인 몫(실측 × 1.25)만 남기고 옛 기록을 몰아서 받아요(실시간이 늘면 옛 기록이 바로 물러나요)'
        + (nF && es.rt != null ? ' · 이더스캔 실시간 확인 몫 하루 ' + fmtN(es.rt) + '콜 · 오늘 남은 옛 기록 몫 ' + fmtN(es.fillLeft || 0) + '콜' : '')
        + (hl.fillFirst && hl.rt != null ? ' · 헬리우스(Solana) 실시간 확인 몫 하루 ' + fmtN(hl.rt) + '크레딧 · 오늘 남은 옛 기록 몫 ' + fmtN(hl.fillLeft || 0) + '크레딧' : '') + '</div>' : '')
      + (hl.pn ? '<div class="cap">Solana 새 거래 확인 = 공개 노드(' + esc(hl.pn.host || 'publicnode') + ') 먼저 · 백업 헬리우스'
        + (hl.pn.hlClosedUntil ? ' — 오늘 헬리우스 한도를 다 써서 ' + kstHM9(hl.pn.hlClosedUntil) + '까지 공개 노드로만 이어 받아요'
          : (hl.pn.ok ? (hl.pn.rate != null ? ' · 최근 응답 ' + Math.round(hl.pn.rate * 100) + '%' : '') + (hl.pn.floorPct != null ? ' · 헬리우스 실시간 몫 하루 ' + hl.pn.floorPct + '%(남는 몫은 옛 기록에)' : '')
            : ' — 지금 공개 노드 응답이 고르지 않아 헬리우스로 확인 중(헬리우스 몫을 더 써요)')) + '</div>' : '')
      + (all.some(p => p.e) ? '<div class="cap">빈 지갑 ' + all.filter(p => p.e).length + '곳 — 기록이 하나도 없어도 10분마다 활동을 보고 1시간마다 탐색기로 확인해요(토큰 입금도 1시간 안에 기록 — 시각·수량은 그대로)</div>' : '')
      + Object.keys(T.scopes || {}).filter(k => { const x = T.scopes[k]; return x && x.period && x.basePoll && x.period > x.basePoll * 1.01; })
        .map(k => { const x = T.scopes[k]; return '<div class="cap">' + esc(chainName(k)) + ' 지갑 ' + fmtN(x.pairs || 0) + '개라 ' + periodTxt(x.period) + '마다 확인해요(하루 한도 안 · 최근에 쓴 지갑 ' + fmtN(x.t0 || 0) + '개 기준)'
          + (k === 'sol' && hl.fillFirst ? ' — 지금은 옛 기록부터 채워서 새 거래 확인이 이보다 늦을 수 있어요' : '') + '</div>'; }).join('')
      + (T.rpcFb || []).map(x => '<div class="cap">' + esc(chainName(x.c)) + ' — ' + esc(x.text) + '</div>').join('')
      + (T.inflow && T.inflow.sec && (T.inflow.rows || []).some(x => x.n) ? '<div class="cap">쉬는 지갑 토큰 받음 확인 ' + periodTxt(T.inflow.sec) + '마다(받은 주소만 바로 탐색기로) · '
        + T.inflow.rows.filter(x => x.n).map(x => esc(chainName(x.c)) + ' ' + (x.at ? esc(ago(x.at)) : '아직 확인 전') + (x.node ? '(' + esc(x.node) + ')' : '') + (x.ok ? '' : ' — 직전 확인 실패, 곧 다시')).join(' · ') + '</div>' : '');
    const warn = gate ? '<div class="bnr w su-tw2"><div><b>이더스캔 하루 예산(' + T.budgetPct + '%)에 가까워 아껴 쓰는 중</b><div class="bd">지금 주기 주소도 공개 RPC 로 먼저 보고 바뀐 게 있을 때만 이더스캔을 불러요' + (str > 1 ? ' · 확인 간격 ×' + str : '') + ' — 토큰 입금만 조금 늦게(최대 ' + Math.round(10 * str) + '분) 기록돼요</div></div></div>' : '';
    const stale = sc.filter(x => x.stale).length ? '<div class="cap su-badt">수집기 장부가 30분 넘게 갱신되지 않았어요 — 수집기 상태를 확인하세요</div>' : '';
    return '<div class="su-tier pvx">' + tiles + steps + warn + stale
      + '<div class="su-th">하루 예상 호출 <span class="cap">(지금 등록 상태 · 쉬는 주소는 1시간마다 탐색기 확인)</span></div>' + budgetRows(T)
      + '<div class="cap su-tnote">쉬는 주소(7일 넘게 안 보낸 주소)도 10분마다 잔고를 보고 1시간마다 탐색기로 확인해요 — 들어온 입금은 늦어도 약 1시간 안에 기록돼요(거래소에서 내 지갑으로 보낸 출금이 전송 중이면 그 주소는 10분마다 확인). 내가 보내면(서명) 바로 지금 주기로 돌아와요.</div>'
      + '<div class="su-actions"><button class="btn sm" data-su="tsheet">주소별 확인 주기 (' + fmtN(Object.keys(T.addrs || {}).length) + ')</button><button class="btn sm" data-su="tcheck">모두 지금 확인</button></div></div>';
  }
  function tierSheetHTML() {
    const rows = tierRows();
    return '<div class="su-bg su-tbg" role="dialog" aria-modal="true" aria-labelledby="suTierT"><div class="su-tsheet">'
      + '<div class="su-tsh"><h3 id="suTierT">주소별 확인 주기</h3><button class="btn sm" data-su="tclose" aria-label="닫기">닫기</button></div>'
      + '<div class="cap su-p pvx">지금 주기 = 매 수집 주기 · 쉬는 주소 = 10분마다 잔고만 보고(그 점검은 탐색기 0콜) 바뀌면 그때 탐색기로 복구 · 토큰 입금은 10분마다 따로 확인(받은 주소만 바로 탐색기로) · 탐색기 받침 확인은 1시간마다</div>'
      + '<div class="su-tlist">' + rows.map(r => {
        const rest = r.pairs.some(p => p.t > 0 && !p.h), lf = Math.max(0, ...r.pairs.map(p => p.full || 0));
        return '<div class="su-trow"><div class="su-trm"><b class="pvl"' + (r.w.label ? ' data-pk="w"' : '') + '>' + esc(r.w.label ? suOwn(r.w.label) : '(이름 없음)') + '</b> <span class="num su-tad">' + esc(r.k.length > 14 ? r.k.slice(0, 6) + '…' + r.k.slice(-4) : r.k) + '</span>'
          + (lf ? '<span class="cap pvx"> · 확인 ' + esc(ago(lf)) + '</span>' : '') + '<div class="su-tcs">' + r.pairs.map(pairChip).join('') + '</div></div>'
          + (rest ? '<button class="btn sm" data-su="tcheck" data-v="' + esc(r.k) + '">지금 확인</button>' : '') + '</div>';
      }).join('') + '</div></div></div>';
  }
  let tierEl = null;
  function renderTierSheet() {
    if (U.tierSheet && U.tier) {
      if (!tierEl) { tierEl = document.createElement('div'); tierEl.id = 'suTier'; document.body.appendChild(tierEl); }
      tierEl.innerHTML = tierSheetHTML();
      document.documentElement.classList.add('su-lock');
    } else if (tierEl) { tierEl.remove(); tierEl = null; if (!U.open && !U.perm) document.documentElement.classList.remove('su-lock'); }
  }
  const CH_COLOR = { eth: '#7C9CFF', base: '#5B8DEF', arbitrum: '#7FC4E8', optimism: '#F25F5C', sol: '#4FC3A1', bsc: '#F2C661', linea: '#B49CFF', blast: '#E5D86A',
    zksync: '#8B93A4', scroll: '#E0B88A', polygon: '#A07CF0', gnosis: '#3E9C8C', robinhood: '#9AD57A', arc: '#6FA8DC' };
  const chColor = k => CH_COLOR[k] || ('hsl(' + (Array.from(String(k)).reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7)) + ' 45% 62%)');
  const CH_ST = { ok: ['ok', '정상'], filling: ['a', '옛 기록 채우는 중'], empty: ['g', '빈 지갑'], off: ['g', '꺼 둠'] };
  const CH_LOCK = { sep: '따로 수집', rpc: '노드 직접 읽기', last: '마지막 EVM', boot: '첫 수집 중' };
  const CH_REC_IC = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 3.5v8"/><path d="M6.6 6.8a7.5 7.5 0 1 0 10.8 0"/></svg>';
  function chMoney(usd) {
    const E = window.TJ && window.TJ.ext;
    if (E && typeof E.m === 'function') return typeof E.pvm === 'function' ? E.pvm(E.m(usd)) : '<span class="pvm">' + esc(E.m(usd)) + '</span>';
    return '<span class="pvm">$' + esc(Math.round(usd).toLocaleString('en-US')) + '</span>';
  }
  const chEvery = s => (s == null ? '' : s < 60 ? s + '초마다' : (Math.round(s / 6) / 10).toString().replace(/\.0$/, '') + '분마다');
  const chDay = ts => { const d = new Date(ts * 1000 + 32400000); return String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0'); };
  function kstHM9(ts) { const d = new Date(ts * 1000 + 32400000); return String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0'); }
  async function loadChains(force) {
    if (isLocked() || U.chBusy) return;
    if (!force && U.ch && Date.now() - U.chAt < 60000) return;
    if (!force && U.chErrAt && Date.now() - U.chErrAt < Math.min(60000, 5000 * Math.pow(2, Math.max(0, (U.chErrN || 1) - 1)))) return;
    U.chBusy = true;
    try {
      const r = await fetch('/api/setup/chains', { cache: 'no-store' });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) { U.chBusy = false; return; }
      let d = null; try { d = await r.json(); } catch (e) { d = null; }
      if (isLocked()) { U.chBusy = false; return; }
      if (d && d.ok) { U.ch = d; U.chAt = Date.now(); U.chErr = ''; U.chErrN = 0; U.chErrAt = 0; } else { U.chErr = (d && d.error) || ('HTTP ' + r.status); U.chErrN = (U.chErrN || 0) + 1; U.chErrAt = Date.now(); }
    } catch (e) { if (isLocked()) { U.chBusy = false; return; } U.chErr = '연결 실패'; U.chErrN = (U.chErrN || 0) + 1; U.chErrAt = Date.now(); }
    U.chBusy = false;
    if (!(document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-su-in'))) fill();
  }
  function chSpark(r) {
    if (!r.on) return '<span class="su-chdash" aria-hidden="true"></span><span class="su-chn">조회 안 함</span>';
    if (r.sent30 == null) return '<span class="su-chn">—</span>';
    const sp = Array.isArray(r.spark) ? r.spark : [], mx = Math.max(1, ...sp), col = chColor(r.key);
    return '<span class="su-chsp" aria-hidden="true">' + sp.map(v => v ? '<i style="height:' + Math.max(2, Math.round(20 * v / mx)) + 'px;background:' + col + '"></i>' : '<i class="z"></i>').join('') + '</span>'
      + '<span class="su-chn">' + fmtN(r.sent30) + '건</span>';
  }
  function chSub(r) {
    if (!r.on) return '조회 안 함 · 알림 없음' + (r.offAt ? ' · ' + chDay(r.offAt) + (r.autoOff ? '에 자동으로 끔(활동 없음)' : '에 끔') : '') + ' · 지갑 ' + fmtN(r.wallets) + '개';
    const p = ['지갑 ' + fmtN(r.wallets) + '개' + (r.pollSec ? ' · <b>' + esc(chEvery(r.pollSec)) + '</b> 확인' : '')];
    if (r.rest) p.push('오래 안 쓴 ' + fmtN(r.rest) + '곳은 쉬어요');
    if (r.status === 'filling') p.push('처음 넣은 지갑은 옛 기록부터 채워서, 첫날은 새 거래 확인이 평소보다 늦을 수 있어요');
    if (!r.can) p.push(esc(r.why || '여기서 못 꺼요'));
    else if (r.auto) p.push('활동이 보여 자동으로 켠 체인' + (r.autoNewDays != null ? ' · 끄기 추천은 ' + fmtN(Math.max(1, (U.ch.autoGraceDays || 30) - r.autoNewDays)) + '일 뒤부터' : ''));
    return p.join(' · ');
  }
  function chRow(r, first) {
    const st = CH_ST[r.status], name = esc(r.name || r.key);
    const sw = '<button class="sw2' + (r.on ? ' on' : '') + '" data-su="chTog" data-v="' + esc(r.key) + '" role="switch" aria-checked="' + !!r.on + '" aria-label="' + name + ' 조회"' + (r.can ? '' : ' disabled title="' + esc(r.why || '') + '"') + '></button>';
    const rec = r.recommend ? '<div class="su-chrec">' + '<span class="su-chri">' + CH_REC_IC + '</span><span class="su-chrt"><b>끄는 걸 추천해요</b><span> — 이 체인에서 보낸 거래가 지갑마다 ' + fmtN(U.ch.nonceMax) + '번 이하예요</span></span>'
      + '<span class="su-chrm">가장 많은 지갑도 ' + fmtN(r.maxNonce) + '번' + (r.calls ? ' · 하루 −' + fmtN(r.calls.perDay) + '콜' : '') + (r.big ? ' · <b class="su-chbig">잔고 ' + chMoney(r.usd) + ' 있음</b>' : '') + '</span></div>' : '';
    return '<div class="su-chr' + (r.recommend ? ' rec' : '') + (r.on ? '' : ' off') + (first ? ' first' : '') + '" data-ch="' + esc(r.key) + '"><div class="su-chm"><div class="su-chh"><i class="su-chd" style="background:' + chColor(r.key) + '"></i><b>' + name + '</b>'
      + (st ? pill(st[0] + ' sm', st[1]) : '') + (r.can ? '' : pill('g sm', CH_LOCK[r.lock] || '끄기 잠금')) + '</div><div class="su-chs">' + chSub(r) + '</div></div>'
      + '<div class="su-chc">' + chSpark(r) + '</div>' + sw + rec + '</div>';
  }
  function chAutoHTML(C, off) {
    const ao = C.autoOffOn !== false, nAuto = (off || []).filter(r => r.autoOff).length;
    return '<div class="su-chauto"><span class="su-cham"><b>추천 체인 자동으로 끄기</b>'
      + '<span>‘끄는 걸 추천해요’ 체인 중 남은 값이 소액 기준 이하인 체인은 점검 때 자동으로 꺼요' + (ao ? '' : ' · 지금은 꺼 둠 — 추천만 보여 줘요') + '</span>'
      + (!ao && nAuto ? '<span class="su-chaon">이미 자동으로 꺼 둔 체인 ' + fmtN(nAuto) + '개는 그대로예요 — 다시 켜려면 아래 꺼 둔 체인에서 직접 켜세요</span>' : '')
      + '</span><button class="sw2' + (ao ? ' on' : '') + '" data-su="chAutoTog" role="switch" aria-checked="' + ao + '" aria-label="추천 체인 자동으로 끄기"' + (U.chAutoBusy ? ' disabled' : '') + '></button></div>';
  }
  async function chAutoSet(on) {
    if (isLocked() || U.chAutoBusy || !U.ch) return;
    U.chAutoBusy = true;
    fill();
    let ok = false, err = '';
    try {
      if (!U.st || !U.st.csrf) await load();
      const r = await fetch('/api/chain_auto_off', { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-TJ-CSRF': (U.st && U.st.csrf) || '' }, body: JSON.stringify({ on }) });
      if (r.status === 401 && typeof window.__tjLoginCheck === 'function' && window.__tjLoginCheck(r)) { U.chAutoBusy = false; return; }
      let d = null; try { d = await r.json(); } catch (e) { d = null; }
      ok = !!(r.ok && d && d.ok);
      err = (d && d.error) || ('HTTP ' + r.status);
    } catch (e) { err = '서버 연결 실패'; }
    U.chAutoBusy = false;
    if (isLocked()) return;
    if (!ok) { toast(err || '저장 실패', true); fill(); return; }
    if (U.ch) U.ch.autoOffOn = on;
    toast(on ? '추천 체인 자동 끄기를 켰어요' : '추천 체인 자동 끄기를 껐어요 — 이미 꺼 둔 체인은 그대로예요');
    await loadChains(true);
  }
  function chainsHTML() {
    const C = U.ch;
    if (!C) { loadChains(); return '<div class="cap">' + (U.chErr ? '체인 목록을 못 불러왔어요 · ' + esc(U.chErr) + ' <button class="link" data-su="chLoad">다시</button>' : '체인 목록 불러오는 중…') + '</div>'; }
    loadChains();
    const rows = Array.isArray(C.rows) ? C.rows : [];
    const on = rows.filter(r => r.on), off = rows.filter(r => !r.on);
    const rec = on.filter(r => r.recommend), rest = on.filter(r => !r.recommend).sort((a, b) => (b.sent30 || 0) - (a.sent30 || 0) || (b.wallets || 0) - (a.wallets || 0));
    const LIM = 6, all = !!U.chAll, shown = all ? rest : rest.slice(0, LIM);
    const head = '<div class="su-chtop"><b class="su-cht">체인별 조회</b><span class="su-chmeta">켜짐 ' + fmtN(C.nOn) + ' · 꺼짐 ' + fmtN(C.nOff) + ' · 지갑 ' + fmtN(C.nWallets) + '개</span><span class="sp"></span>'
      + (C.nRec ? pill('w sm su-chrb', '끄기 추천 ' + C.nRec) : '') + '</div>'
      + '<p class="su-chp">안 쓰는 체인을 끄면 조회·알림이 멈추고 컴퓨터·API 한도를 아껴요. 언제든 다시 켤 수 있어요(켜면 빠진 기간을 이어 받아요).</p>'
      + chAutoHTML(C, off);
    const steps = Array.isArray(C.pollSteps) && C.pollSteps.length ? '<div class="su-chinfo"><b>확인 주기는 지갑 수에 맞춰 늘어나요</b><div class="su-tsteps">' + C.pollSteps.map(x => pill('g sm', String(x.label || ''))).join('') + '</div></div>' : '';
    const colh = '<div class="su-chr su-chcol" aria-hidden="true"><span class="su-chm">체인 · 상태 · 확인 주기</span><span class="su-chc">최근 30일 보낸 거래</span><span class="su-chsw">조회</span></div>';
    const list = rec.map((r, i) => chRow(r, i === 0)).join('') + shown.map((r, i) => chRow(r, !rec.length && i === 0)).join('')
      + (rest.length > LIM ? '<div class="su-chmore"><button class="btn sm" data-su="chAll" aria-expanded="' + all + '">' + (all ? '접기' : '다른 체인 ' + fmtN(rest.length - LIM) + '개 더 보기 · 모두 조회 중') + '</button></div>' : '');
    const offH = off.length ? '<div class="su-choh">꺼 둔 체인 ' + fmtN(off.length) + '<span>조회·알림 멈춤 · 그동안 새 거래·잔고 변화는 안 들어와요 · 다시 켜면 끈 날부터 이어 받아요</span></div>' + off.map((r, i) => chRow(r, i === 0)).join('') : '';
    const calls = C.callsDay != null ? '<div class="su-chfoot"><div class="su-chfh"><b>하루 예상 호출</b><span class="cap">켜진 체인 ' + fmtN(C.nOn) + '개 · 수집기 장부 기준</span><span class="sp"></span><span class="num">' + fmtN(C.callsDay) + '콜</span></div>'
      + (C.recCallsDay ? '<div class="cap">추천 ' + fmtN(C.nRec) + '개를 끄면 하루 약 ' + fmtN(C.recCallsDay) + '콜 줄어요</div>' : '') + '</div>' : '';
    const swept = C.sweptAt ? '<div class="cap su-chnote">nonce = 하루 한 번 점검 기준(' + esc(ago(C.sweptAt)) + ') · 모르는 지갑(EOA 확인 전·점검 실패·이틀 넘은 값)이 하나라도 있거나, 최근 30일 안에 보낸 거래가 있거나, 옛 기록을 채우는 중이면 추천하지 않아요</div>' : '';
    return '<section class="su-ch pvx" aria-label="체인별 조회">' + head + steps + colh + list + offH + calls + swept + '</section>';
  }
  function chApplyTxt(ap) {
    if (ap && ap.mode === 'reload') return '저장하면 약 30초 안에 수집기·웹이 자동으로 다시 시작해 적용돼요';
    return ap && ap.runner ? '저장하면 15초 안에 자동으로 적용돼요' : '적용하려면 웹·수집기 재시작이 필요해요(' + esc((ap && ap.manual) || 'pm2 restart tj-evm tj-core tj-web') + ')';
  }
  function chAsk(r) {
    const E = window.TJ && window.TJ.ext, name = r.name || r.key, ap = U.ch && U.ch.apply;
    const run = () => chSet(r.key, !r.on);
    let title, body, ok;
    if (r.on) {
      title = name + ' 조회를 끌까요?';
      const kv = (k, v) => '<span class="su-mdk">' + k + '</span><span class="su-mdv">' + v + '</span>';
      body = '<span class="su-md pvx"><span class="su-mdp">끄는 동안 이 체인의 새 거래·잔고 변화가 안 들어와요' + (r.usd != null ? ' — 지금까지 기록과 잔고(지금 <b>' + chMoney(r.usd) + '</b>)는 그대로 남지만 멈춘 값이에요' : ' — 지금까지 기록은 그대로 남아요') + '.<br>다시 켜면 끈 날부터 빠진 기간을 이어 받아요.</span>'
        + '<span class="su-mdc"><span class="su-mdh"><i class="su-chd" style="background:' + chColor(r.key) + '"></i><b>' + esc(name) + '</b><span class="cap">지갑 ' + fmtN(r.wallets) + '개' + (r.pollSec ? ' · ' + esc(chEvery(r.pollSec)) + ' 확인 중' : '') + '</span><span class="sp"></span>' + (r.recommend ? pill('w sm', '끄기 추천') : '') + '</span>'
        + '<span class="su-mdg">' + kv('멈춰요', '이 체인 조회 · 입금·출금 알림 · 미추적 체인 경고') + kv('남아요', '지금까지 기록' + (r.usd != null ? ' · 잔고 ' + chMoney(r.usd) + '(멈춘 값)' : '') + ' — 켜면 다시 따라가요') + (r.calls ? kv('아껴요', '하루 약 ' + fmtN(r.calls.perDay) + '콜') : '') + '</span>'
        + '<span class="su-mdf">' + (r.recommend ? '보낸 거래가 지갑마다 ' + fmtN(U.ch.nonceMax) + '번 이하라 추천했어요 · 가장 많은 지갑도 ' + fmtN(r.maxNonce) + '번' : '추천 조건(지갑 전부 보낸 거래 ' + fmtN(U.ch.nonceMax) + '번 이하 확인 · 최근 30일 0건)에 안 맞는 체인이에요 — 쓰는 체인인지 한 번 더 확인하세요')
        + (r.big ? ' · <b class="su-chbig">잔고 ' + chMoney(r.usd) + ' 있음</b>' : '') + '</span></span>'
        + '<span class="su-mda">' + chApplyTxt(ap) + '</span></span>';
      ok = '끄기';
    } else {
      title = name + ' 조회를 다시 켤까요?';
      body = '<span class="su-md pvx"><span class="su-mdp">' + (r.offAt ? chDay(r.offAt) + '에 끈 뒤로 ' : '') + '빠진 기간을 이어 받아요 — 그동안 거래가 많았으면 다 받을 때까지 조금 걸려요.<br>조회·입금·출금 알림도 다시 켜져요.</span>'
        + '<span class="su-mda">' + chApplyTxt(ap) + '</span></span>';
      ok = '켜기';
    }
    if (E && typeof E.confirmAsk === 'function') E.confirmAsk({ title, bodyHtml: body, ok, run, pvx: true });
    else if (window.confirm(title)) run();
  }
  async function chSet(key, on) {
    if (U.chSetBusy) return;
    U.chSetBusy = true;
    const r = await api('chains/set', { chain: key, on });
    U.chSetBusy = false;
    if (!r || !r.ok) { toast((r && r.error) || '저장 실패', true); return; }
    const row = U.ch && (U.ch.rows || []).find(x => x.key === key), nm = row ? row.name : key;
    toast(nm + (on ? ' 조회를 다시 켰어요' : ' 조회를 껐어요') + (r.apply && r.apply.mode === 'reload' ? ' — 곧 자동으로 다시 시작해 적용돼요' : r.apply && !r.apply.runner ? ' — 웹·수집기 재시작 뒤 적용돼요' : ''));
    await loadChains(true);
  }
  const ipHTML = () => (U.ip ? '<code class="num">' + esc(U.ip) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(U.ip) + '">복사</button>' : '<button class="btn sm" data-su="ip">확인</button>');
  const SLOTS = { keys: keysHTML, exchanges: exchangesHTML, telegram: tgHTML, wadd: () => walletsHTML(true), perp: perpHTML, apply: applyHTML, ip: ipHTML, tier: tierHTML, tierw: tierWHTML, chains: chainsHTML };
  let wizEl = null, permEl = null;
  function onSettings() { return /^settings(\/|$)/.test((location.hash || '').replace('#', '')); }
  function slotErrHTML() { return '<div class="su-bad" style="padding:8px 0">연결·키 상태를 불러오지 못했어요' + (U.err ? ' · ' + esc(U.err) : '') + ' <button class="link" data-su="retry">다시 시도</button></div>'; }
  function fill() {
    if (isLocked()) return;
    const els = document.querySelectorAll('[data-su-slot]');
    if (!els.length) return;
    if (!U.st) { if (U.err) els.forEach(el => { el.innerHTML = slotErrHTML(); }); return; }
    els.forEach(el => { const f = SLOTS[el.getAttribute('data-su-slot')]; if (f) el.innerHTML = U.open ? '' : f(el); });
    document.querySelectorAll('[data-su-slot] [data-su-in]').forEach(el => { const k = el.getAttribute('data-su-in'); if (U.d[k] != null) el.value = U.d[k]; });
    document.querySelectorAll('[data-su-slot] textarea[data-su-in]').forEach(autoGrow);
  }
  function render() {
    if (!U.st || isLocked()) { if (!isLocked()) fill(); return; }
    const keepFocus = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-su-in');
    const pos = keepFocus && document.activeElement.selectionStart;
    const ae9 = document.activeElement, wfk = wizEl && ae9 && wizEl.contains(ae9) && ae9.getAttribute && ae9.getAttribute('data-su') ? [ae9.getAttribute('data-su'), ae9.getAttribute('data-v')] : null;
    if (U.open) {
      const fresh = !wizEl;
      if (fresh) { U.retFocus = ae9 && ae9 !== document.body ? ae9 : null; wizEl = document.createElement('div'); wizEl.id = 'suWizard'; document.body.appendChild(wizEl); }
      wizEl.innerHTML = wizardHTML();
      document.documentElement.classList.add('su-lock');
      if (!keepFocus && !(U.perm)) {
        const back = wfk ? [...wizEl.querySelectorAll('[data-su="' + wfk[0] + '"]')].find(x => x.getAttribute('data-v') === wfk[1] && !x.disabled) : null;
        const box = wizEl.querySelector('.su-wiz');
        if (back) back.focus({ preventScroll: true });
        else if (box && (fresh || !wizEl.contains(document.activeElement))) box.focus({ preventScroll: true });
      }
    } else if (wizEl) {
      wizEl.remove(); wizEl = null; document.documentElement.classList.remove('su-lock');
      const rf = U.retFocus; U.retFocus = null;
      if (rf && rf.isConnected) { try { rf.focus({ preventScroll: true }); } catch (e) {  } }
    }
    fill();
    renderTierSheet();
    document.querySelectorAll('[data-su-in]').forEach(el => { const k = el.getAttribute('data-su-in'); if (U.d[k] != null) el.value = U.d[k]; });
    document.querySelectorAll('textarea[data-su-in]').forEach(autoGrow);
    if (keepFocus) { const el = $('[data-su-in="' + keepFocus + '"]'); if (el) { el.focus(); try { el.setSelectionRange(pos, pos); } catch (e) {  } } }
    if (U.perm) {
      if (!permEl) { permEl = document.createElement('div'); permEl.id = 'suPerm'; document.body.appendChild(permEl); }
      permEl.innerHTML = permModalHTML();
      document.documentElement.classList.add('su-lock');
      const b = permEl.querySelector('[data-su="permClose"]'); if (b && !permEl.contains(document.activeElement)) b.focus();
    } else if (permEl) { permEl.remove(); permEl = null; if (!U.open) document.documentElement.classList.remove('su-lock'); }
    const demo = $('#suDemo');
    if (U.st.demo && !demo) { const d = document.createElement('div'); d.id = 'suDemo'; d.className = 'su-demo'; d.textContent = '데모 모드 · 합성 데이터 (실제 지갑·거래 아님)'; document.body.insertBefore(d, document.body.firstChild); }
  }
  async function refreshStatus() { await load(); render(); }
  function lock() {
    U.locked = true;
    stopPoll(); if (U.dpPoll) { clearInterval(U.dpPoll); U.dpPoll = null; }
    U.st = null; U.err = null; U.d = {}; U.test = {}; U.busy = {}; U.dpWait = {}; U.wRes = null; U.wErr = {}; U.perm = null; U.open = false; U.ack = {}; U.needAck = {}; U.ip = '';
    U.tier = null; U.tierErr = ''; U.tierErrN = 0; U.tierErrAt = 0; U.tierSheet = false; if (tierEl) { tierEl.remove(); tierEl = null; }
    U.ch = null; U.chErr = ''; U.chErrN = 0; U.chErrAt = 0; U.chAll = false;
    Object.assign(U.tg, { phase: 'idle', err: '', bot: null, link: '', start: '', left: 0, tok: '' });
    if (wizEl) { wizEl.remove(); wizEl = null; }
    if (permEl) { permEl.remove(); permEl = null; }
    document.querySelectorAll('[data-su-slot]').forEach(el => { el.innerHTML = ''; });
    document.documentElement.classList.remove('su-lock');
  }

  function startPoll() {
    stopPoll();
    U.tg.poll = setInterval(async () => {
      if (U.tg.phase !== 'wait' || document.hidden) return;
      if (U.tg._inflight) return;
      U.tg._inflight = true;
      const r = await api('telegram/poll', {});
      U.tg._inflight = false;
      if (U.tg.phase !== 'wait') return;
      if (r.ok && r.connected) { stopPoll(); U.tg.phase = 'done'; U.tg.err = ''; U.tg.tok = ''; toast('텔레그램 연결 완료 — 테스트 메시지를 보냈어요'); await refreshStatus(); return; }
      if (r.ok && r.waiting) { U.tg.left = r.left; U.tg.err = r.hint || ''; }
      else if (!r.ok) { U.tg.err = r.error || '확인 실패'; if (r.expired) { stopPoll(); U.tg.phase = 'idle'; } }
      render();
    }, 2500);
  }
  function stopPoll() { if (U.tg.poll) clearInterval(U.tg.poll); U.tg.poll = null; }
  function groupVals(g) {
    const grp = U.st.explorers[g] || U.st.exchanges[g], vals = {};
    grp.fields.forEach(f => { vals[f.key] = (draft('k_' + f.key) || '').trim(); });
    return vals;
  }
  function clearVals(g) { const grp = U.st.explorers[g] || U.st.exchanges[g]; grp.fields.forEach(f => { delete U.d['k_' + f.key]; }); }
  async function waddMany(an) {
    if (an.secret) { toast(W_SECRET[an.secret], true); return; }
    if (!an.save.length) { toast(an.items.some(x => x.st === 'bad') ? '오류 난 주소를 고쳐 주세요' : '새로 추가할 주소가 없어요 (모두 이미 등록됨·중복)', true); return; }
    if (an.needChain) { toast('EVM 체인을 하나 이상 고르세요', true); return; }
    const send = an.save.slice(0, MAX_BATCH), later = an.save.slice(MAX_BATCH).map(x => x.t);
    U.busy.wadd = true; render();
    const r = await api('wallets/add_many', { addresses: send.map(x => x.t), chains: Array.from(U.chains) });
    U.busy.wadd = false;
    if (!r.ok) { toast(r.error || '추가 실패', true); render(); return; }
    const res = Array.isArray(r.results) ? r.results : [], failed = {};
    res.forEach(x => { if (x.status === 'invalid' || x.status === 'error') failed[x.input] = x.error || '저장 안 됨'; });
    const added = res.filter(x => x.status === 'added');
    const keep = an.items.filter(x => x.st === 'bad' || (failed[x.t] != null && x.st !== 'dup')).map(x => x.t).concat(later);
    U.wErr = failed;
    U.wRes = { added: added.length, skipped: an.items.filter(x => x.st === 'have' || x.st === 'dup').length + res.filter(x => x.status === 'exists' || x.status === 'dup').length,
      left: keep.length, fails: an.items.filter(x => x.st === 'bad').map(x => ({ t: x.t, err: x.err })).concat(Object.keys(failed).map(t => ({ t, err: failed[t] }))) };
    if (keep.length) U.d.w_addr = keep.join('\n'); else delete U.d.w_addr;
    markNew(added.map(x => x.address));
    toast(added.length ? added.length + '개 추가됨 — 이름은 목록에서 붙여요' + (later.length ? ' · 남은 ' + later.length + '개는 칸에 — 한 번 더 누르면 이어서 추가' : keep.length ? ' · ' + keep.length + '개는 칸에 남겼어요' : '') : '추가된 주소가 없어요' + (keep.length ? ' · ' + keep.length + '개는 칸에 남겼어요' : ''), !added.length);
    U.tierAt = 0;
    await refreshStatus();
    if (added.length) {
      const r0 = document.querySelector('#suWizard .su-row.new, #walCard .newrow');
      if (r0) r0.scrollIntoView({ block: 'nearest' });
      if (window.__tj && window.__tj.refresh) window.__tj.refresh();
    }
  }
  const A = {
    async tcheck(el) {
      const a = el.getAttribute('data-v') || '';
      if (!a && !window.confirm('쉬는 주소까지 모두 다음 수집 주기에 탐색기로 한 번씩 확인할까요?\n(이더스캔 호출이 한 번에 늘어요 — 보통은 주소별 \'지금 확인\'으로 충분해요)')) return;
      el.disabled = true;
      const r = await api('wallets/check_now', a ? { address: a } : {});
      toast(r.ok ? (r.same ? '방금 요청했어요 — 곧 확인해요' : (a ? '이 주소를' : '모든 주소를') + ' 다음 수집 주기(1~2분 안)에 확인해요') : (r.error || '요청 실패'), !r.ok);
      el.disabled = false;
      setTimeout(() => loadTier(true), 2500);
    },
    tsheet() { U.tierSheet = true; renderTierSheet(); const b = document.querySelector('#suTier [data-su="tclose"]'); if (b) b.focus(); },
    tclose() { U.tierSheet = false; renderTierSheet(); const b = document.querySelector('[data-su="tsheet"]'); if (b) b.focus(); },
    tload() { U.tierErr = ''; loadTier(true); },
    tpub() { U.tierPub = !U.tierPub; fill(); },
    chTog(el) { const k = el.getAttribute('data-v'), r = U.ch && (U.ch.rows || []).find(x => x.key === k); if (r && r.can) chAsk(r); },
    chLoad() { U.chErr = ''; loadChains(true); },
    chAll() { U.chAll = !U.chAll; fill(); },
    chAutoTog() { if (U.ch) chAutoSet(U.ch.autoOffOn === false); },
    async wadd() {
      if (U.busy.wadd) return;
      const an = wAnalyze(draft('w_addr'));
      if (an.multi) return waddMany(an);
      const x0 = an.items[0], chk = x0 && x0.c;
      if (an.secret) { toast(W_SECRET[an.secret], true); return; }
      if (!chk) { toast(x0 ? x0.err : '주소를 입력하세요', true); return; }
      const label = draft('w_label').trim() || (chk.kind === 'sol' ? 'Solana' : '지갑') + ' ' + ((U.st.wallets.length || 0) + 1);
      U.busy.wadd = true; render();
      const r = await api('wallets/add', { address: chk.addr, label, chains: chk.kind === 'sol' ? [] : Array.from(U.chains) });
      U.busy.wadd = false;
      if (!r.ok) { toast(r.error || '추가 실패', true); render(); return; }
      delete U.d.w_addr; delete U.d.w_label; U.wRes = null; U.wErr = {};
      if (r.added && r.added.address) markNew([r.added.address]);
      toast('추가됨 · ' + suOwn(label) + ' — 수집기가 곧 최근 ' + U.st.backfillMonths + '개월 거래를 불러와요');
      await refreshStatus();
      if (window.__tj && window.__tj.refresh) window.__tj.refresh();
    },
    wgo() {
      const c = document.getElementById('walCard'); if (!c) return;
      const r0 = c.querySelector('.newrow'), e = r0 && r0.querySelector('[data-a="aliasEdit"]');
      (r0 || c).scrollIntoView({ block: r0 ? 'center' : 'start' });
      if (e) e.focus({ preventScroll: true });
    },
    async wdel(el) {
      const a = el.getAttribute('data-v');
      if (!window.confirm('이 지갑을 추적 목록에서 뺄까요?\n' + a + '\n\n이미 기록된 거래는 원장에 남아요(깨끗이 지우려면 README › 재백필).')) return;
      const r = await api('wallets/remove', { address: a });
      toast(r.ok ? '삭제했어요' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
    },
    pdex(el) { U.pdex = el.getAttribute('data-v'); render(); },
    async padd() {
      const d = perpDex(), c = d ? checkPerpAddr(d.kind, draft('p_addr'), d.name) : null;
      if (!c || c.err) { toast(c ? c.err : '주소를 입력하세요', true); return; }
      const label = draft('p_label').trim() || d.name + ' ' + ((((U.st.perp || {}).wallets || []).filter(w => w.dex === d.key).length) + 1);
      U.busy.padd = true; render();
      const r = await api('perp/add', { dex: d.key, address: c.addr, label });
      U.busy.padd = false;
      if (!r.ok) { toast(r.error || '추가 실패', true); render(); return; }
      delete U.d.p_addr; delete U.d.p_label;
      toast('추가됨 · ' + suOwn(label) + ' (' + d.name + ') — 15초 안에 수집을 시작해요');
      await refreshStatus();
    },
    async pdel(el) {
      const v = el.getAttribute('data-v') || '', i = v.indexOf('|'), dex = v.slice(0, i), a = v.slice(i + 1);
      const nm = (((U.st.perp || {}).dexes || []).find(x => x.key === dex) || {}).name || dex;
      if (!window.confirm(nm + ' 주소를 목록에서 뺄까요?\n' + a + '\n\n이 주소의 선물 포지션·정산이 화면과 매매일지 합계에서 바로 빠져요.')) return;
      const r = await api('perp/remove', { dex, address: a });
      toast(r.ok ? '삭제했어요' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
      if (r.ok && window.__tj && window.__tj.refresh) window.__tj.refresh();
    },
    chain(el) { const k = el.getAttribute('data-v'); if (U.chains.has(k)) U.chains.delete(k); else U.chains.add(k); render(); },
    chainAll() { (U.st.chains || []).forEach(c => U.chains.add(c.key)); render(); },
    chainNone() { U.chains.clear(); render(); },
    xp(el) { const k = el.getAttribute('data-v'); U.xp = (U.xp === k || (U.xp == null && k === 'helius')) ? '' : k; render(); },
    ex(el) { const k = el.getAttribute('data-v'); U.ex = U.ex === k ? null : k; render(); },
    async ktest(el) {
      const g = el.getAttribute('data-v');
      U.busy['t' + g] = true; delete U.test[g]; render();
      const vals = groupVals(g), stored = Object.keys(vals).every(k => !vals[k]);
      const r = await api('keys/test', { group: g, values: vals });
      U.busy['t' + g] = false;
      U.test[g] = r.ok ? r.test : { ok: false, detail: r.error || '테스트 실패' };
      if (r.ok && r.test && r.test.permBlock) { U.perm = Object.assign({}, r.test.permBlock, { stored }); if (!stored) clearVals(g); }
      render();
    },
    async ksave(el) {
      const g = el.getAttribute('data-v'), grp = U.st.explorers[g] || U.st.exchanges[g], vals = groupVals(g);
      const node = NODE_KEYS.indexOf(g) >= 0;
      if (node ? grp.fields.every(f => !vals[f.key]) : grp.fields.some(f => !vals[f.key])) { toast(node ? '값을 넣으세요' : grp.partial ? '바꾸려면 모든 칸을 새로 입력하세요' : '모든 칸을 채우세요', true); return; }
      if (needAck(g) && !U.ack[g]) { toast("'조회 권한만 켰음'을 먼저 체크하세요", true); return; }
      U.busy['s' + g] = true; render();
      const r = await api('keys/save', { group: g, values: vals, readOnlyAck: !!U.ack[g] });
      U.busy['s' + g] = false;
      if (!r.ok) {
        if (r.permBlock) { U.perm = Object.assign({}, r.permBlock, { stored: false }); clearVals(g); U.ack[g] = false; delete U.test[g]; }
        else if (r.needAck) { U.needAck[g] = r.reason || r.error || ''; U.ack[g] = false; toast(r.error || '조회 권한 확인이 필요해요', true); }
        else toast(r.error || '저장 실패', true);
        render(); return;
      }
      clearVals(g); delete U.ack[g]; delete U.needAck[g]; delete U.test[g];
      toast(xpName(grp.name).t + ' 저장됨' + (r.cg && r.cg.plan ? ' · ' + r.cg.text : '') + (r.note ? ' · ' + r.note : ' · 값은 다시 표시되지 않아요') + (r.apply && r.apply.restart === false ? ' · 재시작 없이 바로 써요' : ''), false, r.note ? 9000 : 0); await refreshStatus();
    },
    async kdel(el) {
      const g = el.getAttribute('data-v'), grp = U.st.explorers[g] || U.st.exchanges[g];
      if (!window.confirm(grp.name + ' 키를 이 서버에서 지울까요?')) return;
      const r = await api('keys/delete', { group: g });
      delete U.test[g]; delete U.ack[g]; delete U.needAck[g]; toast(r.ok ? '삭제했어요' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
    },
    async nplan(el) { await nodePlanSave(el.getAttribute('data-p'), { plan: el.getAttribute('data-v') }); },
    async nshare(el) { await nodePlanSave(el.getAttribute('data-p'), { share: Number(el.getAttribute('data-v')) }); },
    async nfresh(el) {
      const p = el.getAttribute('data-p'), n = U.st && U.st.nodes && U.st.nodes[p];
      if (p === 'helius') {
        const h = U.st && U.st.heliusFresh;
        if (!h || U.busy.nphelius) return;
        U.busy.nphelius = true; render();
        const r = await api('keys/nodeplan', { provider: 'helius', fresh: !h.since });
        U.busy.nphelius = false;
        toast(r.ok ? 'Helius 설정을 바꿨어요 — 재시작 없이 바로 써요' : (r.error || '저장 실패'), !r.ok);
        await refreshStatus();
        return;
      }
      await nodePlanSave(p, { fresh: !(n && n.freshSince) });
    },
    async nmonth(el) {
      const p = el.getAttribute('data-p'), raw = draft('nm_' + p).replace(/[,\s]/g, '');
      if (raw && !/^[1-9][0-9]{0,11}$/.test(raw)) { toast('월 한도는 숫자만(쉼표 없이)', true); return; }
      await nodePlanSave(p, { month: raw ? Number(raw) : null });
      delete U.d['nm_' + p];
    },
    async cgshare(el) {
      const v = Number(el.getAttribute('data-v'));
      if (U.busy.cgshare) return;
      U.busy.cgshare = true; render();
      const r = await api('keys/cgshare', { share: v });
      U.busy.cgshare = false;
      toast(r.ok ? '코인게코 프로 키 사용 비율 ' + v + '% 로 바꿨어요' : (r.error || '저장 실패'), !r.ok);
      await refreshStatus();
    },
    kack(el) { const g = el.getAttribute('data-v'); U.ack[g] = !U.ack[g]; render(); },
    permClose() { const g = U.perm && U.perm.group; U.perm = null; render(); const b = g && $('[data-su="ex"][data-v="' + g + '"]'); if (b) b.focus(); },
    async dprefresh(el) {
      const k = el.getAttribute('data-v');
      const r = await api('depaddr/refresh', { exchange: k });
      if (!r.ok) { toast(r.error || '요청 실패', true); return; }
      U.dpWait[k] = Date.now();
      toast('입금 주소 새로고침을 요청했어요 — 수집기가 10초 안에 시작해요');
      render(); dpPoll();
    },
    async ip() { const r = await api('public_ip', {}); if (r.ok) U.ip = r.ip; else toast(r.error || '조회 실패', true); render(); },
    copy(el) {
      const t = el.getAttribute('data-v') || '';
      const done = () => toast('복사했어요');
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, () => window.prompt('직접 복사하세요', t));
      else { try { window.prompt('직접 복사하세요 (Ctrl/Cmd+C)', t); } catch (e) {  } }
    },
    async tgval() {
      const tok = draft('tg_token').trim();
      if (!tok) { U.tg.err = '토큰을 붙여넣으세요'; render(); return; }
      U.busy.tg = true; U.tg.err = ''; render();
      const r = await api('telegram/validate', { token: tok });
      U.busy.tg = false;
      if (!r.ok) { U.tg.err = r.error || '확인 실패'; render(); return; }
      delete U.d.tg_token;
      Object.assign(U.tg, { phase: 'wait', bot: r.bot, link: r.link, start: r.start, left: 600, err: '', tok: tok });
      startPoll(); render();
    },
    tgman() { U.tg.manual = !U.tg.manual; render(); },
    tgcancel() { stopPoll(); Object.assign(U.tg, { phase: 'idle', err: '', manual: false, tok: '' }); render(); },
    async tgmanual() {
      const tok = U.tg.tok || (draft('tg_mtoken') || '').trim();
      if (!tok) { U.tg.err = 'chat_id 를 바꾸려면 봇 토큰을 같이 입력하세요'; render(); return; }
      const r = await api('telegram/manual', { chat_id: draft('tg_chat').trim(), token: tok });
      if (!r.ok) { U.tg.err = r.error || '실패'; render(); return; }
      stopPoll(); U.tg.phase = 'done'; U.tg.tok = ''; delete U.d.tg_chat; delete U.d.tg_mtoken; toast('연결 완료 — 테스트 메시지를 보냈어요'); await refreshStatus();
    },
    async tgtest() { const r = await api('telegram/test', {}); toast(r.ok ? '테스트 알림을 보냈어요' : (r.error || '실패'), !r.ok); },
    async tgoff() {
      if (!window.confirm('텔레그램 알림 연결을 해제할까요? (봇 토큰·chat_id 를 이 서버에서 지워요)')) return;
      const r = await api('telegram/disconnect', {});
      U.tg.phase = 'idle'; toast(r.ok ? '연결을 해제했어요' : (r.error || '실패'), !r.ok); await refreshStatus();
    },
    cur(el) {
      const v = el.getAttribute('data-v'); draft('cur', v); LS.set('tj_v2_cur', v);
      const b = $('#curSeg [data-v="' + v + '"]'); if (b && !b.classList.contains('on')) b.click();
      api('prefs', { currency: v }); render();
    },
    theme(el) {
      const v = el.getAttribute('data-v'); document.documentElement.setAttribute('data-theme', v); LS.set('tj_v2_theme', v);
      if (window.__tj && window.__tj.refresh) window.__tj.refresh();
      render();
    },
    goto(el) { U.step = +el.getAttribute('data-v'); wizKeep(); render(); },
    prev() { U.step = Math.max(0, U.step - 1); wizKeep(); render(); },
    next() { U.step = Math.min(STEPS.length - 1, U.step + 1); wizKeep(); refreshStatus(); },
    async finish() { const r = await api('finish', {}); if (!r.ok) { toast(r.error || '저장 실패', true); return; } U.open = false; SS.set('tj_su_wiz', '0'); SS.set('tj_su_step', '0'); stopPollIfIdle(); toast('설정 완료 — 첫 수집이 끝나면 대시보드가 채워져요'); await refreshStatus(); if (window.__tj) window.__tj.refresh(); },
    later() { SS.set('tj_setup_later', '1'); U.open = false; SS.set('tj_su_wiz', '0'); render(); },
    close() { SS.set('tj_setup_later', '1'); U.open = false; SS.set('tj_su_wiz', '0'); render(); },
    wizard() { U.open = true; U.step = wizStep(); wizKeep(); render(); },
    async retry() { U.err = null; await refreshStatus(); },
  };
  function wizStep() { const n = parseInt(SS.get('tj_su_step') || '0', 10); return n >= 0 && n < STEPS.length ? n : 0; }
  function wizKeep() { SS.set('tj_su_step', String(U.step)); SS.set('tj_su_wiz', U.open ? '1' : '0'); }
  function dpPoll() {
    if (U.dpPoll) return;
    U.dpPoll = setInterval(async () => {
      if (isLocked()) { clearInterval(U.dpPoll); U.dpPoll = null; return; }
      if (document.hidden) return;
      await load();
      const dp = (U.st && U.st.depaddr) || {}, now = Date.now();
      Object.keys(U.dpWait).forEach(k => {
        const d = dp[k] || {};
        const doneAfter = (d.lastAttempt || 0) * 1000 >= U.dpWait[k] - 2000 && !d.running && !d.requested;
        if (doneAfter || now - U.dpWait[k] > 600000) delete U.dpWait[k];
      });
      if (!Object.keys(U.dpWait).length) { clearInterval(U.dpPoll); U.dpPoll = null; }
      render();
    }, 5000);
  }
  function stopPollIfIdle() { if (U.tg.phase !== 'wait') stopPoll(); }

  document.addEventListener('click', ev => {
    const t = ev.target.closest && ev.target.closest('[data-su]');
    if (!t || !(t.closest('#suWizard') || t.closest('[data-su-scope]') || t.closest('#suPerm') || t.closest('#suTier'))) return;
    if (U.perm && !t.closest('#suPerm')) return;
    if (t.tagName === 'A') return;
    ev.preventDefault();
    const fn = A[t.getAttribute('data-su')];
    if (fn && !t.disabled) fn(t, ev);
  });
  document.addEventListener('input', ev => {
    const t = ev.target, k = t.getAttribute && t.getAttribute('data-su-in');
    if (!k) return;
    U.d[k] = t.value;
    if (k === 'w_addr') {
      const an = wAnalyze(t.value), m = $('#suVmsg'), ch = $('#suChains'), lb = $('#suWLabel'), b = $('#suWadd'), wb = wBtn(an);
      if (m) m.innerHTML = wMsgHTML(an);
      if (ch) ch.classList.toggle('hidden', an.onlySol);
      if (lb) lb.classList.toggle('hidden', an.multi);
      if (b) { b.textContent = wb.t; b.disabled = wb.dis; }
      if (U.wRes) { U.wRes = null; const wr = $('.su-wres'); if (wr) wr.remove(); }
      autoGrow(t);
    }
    if (k === 'p_addr') { const m = $('#suPvmsg'); if (m) m.innerHTML = perpVmsg(perpDex(), t.value); }
  });
  document.addEventListener('keydown', ev => {
    const t = ev.target, k = t.getAttribute && t.getAttribute('data-su-in');
    if (ev.key === 'Escape' && U.perm) { A.permClose(); return; }
    if (ev.key === 'Escape' && U.tierSheet) { A.tclose(); return; }
    if (ev.key === 'Escape' && U.open) { A.close(); return; }
    const trap = U.perm ? permEl : U.open ? wizEl : null;
    if (ev.key === 'Tab' && trap) {
      const f = [...trap.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(x => x.getClientRects().length);
      if (!f.length) return;
      const i = f.indexOf(document.activeElement);
      if (ev.shiftKey ? i <= 0 : (i < 0 || i === f.length - 1)) { ev.preventDefault(); f[ev.shiftKey ? f.length - 1 : 0].focus(); }
      return;
    }
    if (ev.key !== 'Enter' || !k) return;
    if (k === 'w_addr' && !(ev.metaKey || ev.ctrlKey)) return;
    ev.preventDefault();
    if (k === 'w_addr' || k === 'w_label') A.wadd();
    else if (k === 'p_addr' || k === 'p_label') A.padd();
    else if (k === 'tg_token') A.tgval();
    else if (k === 'tg_chat') A.tgmanual();
  });
  window.addEventListener('hashchange', render);
  setInterval(() => { if (!document.hidden && (U.open || onSettings()) && !(document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-su-in'))) refreshStatus(); }, 20000);

  const css = document.createElement('style');
  css.textContent = [
    'html.su-lock,html.su-lock body{overflow:hidden}',
    '.su-bg{position:fixed;inset:0;z-index:80;background:var(--dim);display:flex;align-items:flex-start;justify-content:center;padding:40px 20px;overflow-y:auto}',
    '.su-wiz{width:780px;max-width:100%;background:var(--bg);border:1px solid var(--line2);border-radius:22px;box-shadow:var(--pop);padding:22px 26px 20px}',
    '.su-wiz:focus{outline:none}',
    '.su-top{display:flex;align-items:center;gap:10px}',
    '.su-intro{margin:10px 0 16px;line-height:1.6}',
    '.su-steps{display:flex;gap:6px;margin-bottom:18px;overflow-x:auto;scrollbar-width:none}',
    '.su-steps::-webkit-scrollbar{display:none}',
    '.su-step{display:flex;align-items:center;gap:8px;padding:8px 12px 8px 8px;border-radius:12px;font-size:14px;font-weight:600;color:var(--muted);white-space:nowrap;border:1px solid transparent}',
    '.su-step i{font-style:normal;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:12.5px;background:var(--surface2);border:1px solid var(--line)}',
    '.su-step.on{color:var(--text);background:var(--surface);border-color:var(--line)}',
    '.su-step.on i{background:var(--accent);color:var(--bg);border-color:var(--accent)}',
    '.su-step.done i{background:var(--okBg);color:var(--ok);border-color:transparent}',
    '.su-body{display:flex;flex-direction:column;gap:14px}',
    '.su-sec{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px 20px;min-width:0}',
    '.su-h{font-size:16px;font-weight:700}',
    '.su-p{margin:4px 0 12px;line-height:1.6}',
    '.su-form{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '.su-grow{flex:1;min-width:200px}',
    '.su-vmsg{margin:8px 0 4px;font-size:13px;min-height:20px}',
    '.su-good{color:var(--ok);font-weight:600}',
    '.su-bad{color:var(--danger);font-weight:600;font-size:13.5px}',
    '.su-warnline{color:var(--warn);font-size:13px;margin-top:4px;line-height:1.55}',
    '.su-permbox{margin-top:12px;display:flex;flex-direction:column;gap:8px}',
    '.su-permnote{line-height:1.6}',
    '.su-ack{display:flex;gap:10px;align-items:flex-start;text-align:left;padding:10px 12px;border-radius:10px;border:1px solid var(--line2);background:var(--surface2);font-size:13.5px;line-height:1.55;color:var(--text)}',
    '.su-ack i{flex:none;width:18px;height:18px;margin-top:1px;border-radius:5px;border:2px solid var(--line2);background:var(--bg)}',
    '.su-ack.on{border-color:var(--ok);background:var(--okBg)}',
    '.su-ack.on i{border-color:var(--ok);background:var(--ok);box-shadow:inset 0 0 0 3px var(--bg)}',
    '.su-ack:focus-visible{outline:2px solid var(--accent);outline-offset:2px}',
    '.su-permbg{z-index:95;align-items:center}',
    '.su-perm{width:600px;max-width:100%;background:var(--bg);border:2px solid var(--danger);border-radius:22px;box-shadow:var(--pop);padding:24px 26px 20px}',
    '.su-permhead{display:flex;gap:14px;align-items:flex-start;color:var(--danger);padding-bottom:14px;border-bottom:1px solid var(--line)}',
    '.su-permhead svg{flex:none}',
    '.su-permkick{font-size:13px;font-weight:700;letter-spacing:.02em}',
    '.su-perm h3{margin:4px 0 0;font-size:22px;line-height:1.35;color:var(--danger);font-weight:800}',
    '.su-permsec{margin-top:14px;font-size:14px;line-height:1.65}',
    '.su-permsec>b{display:block;margin-bottom:4px}',
    '.su-permsec p{margin:0;color:var(--text2)}',
    '.su-permsec ul{list-style:none;margin:0;padding:10px 12px;border-radius:12px;background:var(--dangerBg)}',
    '.su-permsec li{margin:3px 0}',
    '.su-permsec ol{margin:4px 0 8px 20px;color:var(--text2)}',
    '.su-wform{align-items:flex-start}',
    'textarea.field.su-ta{height:38px;min-height:38px;max-height:240px;padding:8px 12px;line-height:20px;resize:none;font-family:inherit;display:block;overflow-y:auto;word-break:break-all;color:var(--text)}',
    '.su-warnt{color:var(--warn);font-weight:600}',
    '.su-badt{color:var(--danger);font-weight:600}',
    '.su-mnote{display:flex;gap:8px;align-items:center;padding:8px 12px;border-radius:10px;background:var(--accentBg);color:var(--text);font-size:13.5px;font-weight:600;margin-bottom:8px}',
    '.su-mnote svg{flex:none;color:var(--accent)}',
    '.su-prev{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:12px;max-height:320px;overflow-y:auto;background:var(--bg)}',
    '.su-pi{display:flex;gap:10px;align-items:flex-start;padding:8px 12px;border-top:1px solid var(--line);font-size:13px;min-width:0}',
    '.su-pi:first-child{border-top:0}',
    '.su-pic{flex:none;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:800;margin-top:1px;background:var(--surface2);color:var(--muted)}',
    '.su-pi.ok .su-pic,.su-pi.more .su-pic{background:var(--okBg);color:var(--ok)}',
    '.su-pi.warn .su-pic{background:var(--warnBg);color:var(--warn)}',
    '.su-pi.bad .su-pic{background:var(--dangerBg);color:var(--danger)}',
    '.su-pi.have .su-pa,.su-pi.dup .su-pa{color:var(--muted);text-decoration:line-through;text-decoration-color:var(--line2)}',
    '.su-pib{min-width:0;flex:1}',
    '.su-pa{font-size:12.5px;word-break:break-all;color:var(--text)}',
    '.su-pis{font-size:12.5px;color:var(--text2);margin-top:2px;line-height:1.5}',
    '.su-pi.bad .su-pis,.su-pise{color:var(--danger);font-weight:600}',
    '.su-pi.warn .su-pis{color:var(--warn)}',
    '.su-psum{margin-top:8px;font-size:12.5px;color:var(--text2);line-height:1.6}',
    '.su-kbd{font-size:12px}',
    '.su-wres{margin-top:12px;padding:10px 14px;border-radius:12px;background:var(--okBg);font-size:13.5px;line-height:1.6;min-width:0}',
    '.su-wres.none{background:var(--surface2)}',
    '.su-wfail{margin:6px 0 2px 18px;padding:0;font-size:12.5px;color:var(--danger);word-break:break-all}',
    '.su-row.new{background:var(--accentBg);border-radius:12px;padding:12px;margin-top:6px;border-bottom-color:transparent}',
    '.su-chains{margin-top:8px}',
    '.su-tier{display:flex;flex-direction:column;gap:10px}',
    '.su-ttiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}',
    '.su-ttiles>div{background:var(--surface2);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:2px;min-width:0}',
    '.su-ttiles b{font-size:18px;line-height:1.2} .su-ttiles span{font-size:12px;color:var(--text2)}',
    '.su-tsteps,.su-tcs{display:flex;gap:6px;flex-wrap:wrap}',
    '.su-tcs{margin:6px 0}',
    '.su-th{font-weight:700;font-size:14px;margin-top:4px}',
    '.su-brow{padding:8px 0;border-bottom:1px solid var(--line)}',
    '.su-brh{display:flex;justify-content:space-between;gap:8px;font-size:13.5px;flex-wrap:wrap}',
    '.su-bbar{position:relative;height:8px;border-radius:99px;background:var(--surface2);margin:6px 0 4px;overflow:hidden}',
    '.su-bbar i{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:var(--accent)} .su-bbar i.o{background:var(--danger)}',
    '.su-bbar s{position:absolute;top:0;bottom:0;width:2px;background:var(--text2);opacity:.55}',
    '.su-bpub{line-height:1.6} .su-bpl{margin:4px 0 0 18px;padding:0;font-size:12.5px;color:var(--text2);columns:2}',
    '.su-tnote{line-height:1.6}',
    '.su-tw{margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)} .su-twh{line-height:1.5}',
    '.su-tsheet{width:640px;max-width:100%;background:var(--bg);border-radius:22px;box-shadow:var(--pop);padding:20px 22px}',
    '.su-tsh{display:flex;justify-content:space-between;align-items:center;gap:10px} .su-tsh h3{margin:0;font-size:18px}',
    '.su-tlist{margin-top:8px;border-top:1px solid var(--line)}',
    '.su-trow{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--line)} .su-trm{min-width:0;flex:1} .su-tad{font-size:12.5px;color:var(--text2)}',
    '.su-ch{display:flex;flex-direction:column;min-width:0}',
    '.su-chtop{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap} .su-cht{font-size:15px;font-weight:700} .su-chmeta{font-size:12.5px;color:var(--text2);font-variant-numeric:tabular-nums}',
    '.su-chtop .sp,.su-chfh .sp,.su-mdh .sp{flex:1}',
    '.su-chp{margin:6px 2px 12px;font-size:13px;line-height:1.55;color:var(--text2)}',
    '.su-chinfo{background:var(--surface2);border-radius:12px;padding:12px 14px;margin-bottom:8px;font-size:13px;display:flex;flex-direction:column;gap:8px}',
    '.su-chr{display:grid;grid-template-columns:minmax(0,1fr) 128px 46px;column-gap:18px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}',
    '.su-chr.first,.su-chcol+.su-chr{border-top-color:transparent}',
    '.su-chcol{padding:10px 0 6px;border-top:0;border-bottom:1px solid var(--line);font-size:12px;font-weight:600;color:var(--muted)} .su-chcol .su-chm{padding-left:18px} .su-chcol .su-chc,.su-chcol .su-chsw{text-align:right}',
    '.su-chr.rec{background:color-mix(in srgb,var(--warn) 6.5%,transparent);border-radius:12px;padding:10px 12px;margin:4px -12px;border-top-color:transparent}',
    '.su-chr.rec+.su-chr{border-top-color:transparent}',
    '.su-chm{min-width:0} .su-chh{display:flex;align-items:center;gap:8px;min-width:0} .su-chh b{font-size:14.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.su-chd{width:10px;height:10px;border-radius:3px;flex:none;display:inline-block}',
    '.su-chs{font-size:12.5px;line-height:1.45;color:var(--text2);margin-top:2px;padding-left:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .su-chs b{color:var(--text);font-weight:600}',
    '.su-chr.off .su-chh b{color:var(--text2)} .su-chr.off .su-chd{opacity:.35} .su-chr.off .su-chs{color:var(--muted)}',
    '.su-chc{display:flex;flex-direction:column;align-items:flex-end;gap:3px;min-width:0}',
    '.su-chsp{display:flex;align-items:flex-end;gap:3px;height:20px} .su-chsp i{width:4px;border-radius:1.5px;opacity:.85} .su-chsp i.z{height:2px;background:var(--line2);opacity:1;border-radius:1px}',
    '.su-chdash{width:102px;height:20px;border-bottom:1px dashed var(--line2);display:block;box-sizing:border-box;margin-bottom:-10px}',
    '.su-chn{font-size:12px;line-height:1.5;color:var(--muted);font-variant-numeric:tabular-nums}',
    '.su-chr .sw2{justify-self:end}',
    '.su-chauto{display:flex;align-items:center;gap:14px;background:var(--surface2);border-radius:12px;padding:12px 14px;margin:0 0 10px;min-width:0}',
    '.su-cham{min-width:0;flex:1;display:flex;flex-direction:column;gap:3px;font-size:13px;line-height:1.5} .su-cham b{font-size:13.5px;font-weight:650;color:var(--text)} .su-cham span{color:var(--text2)} .su-cham .su-chaon{color:var(--warn)}',
    '.su-chauto .sw2{position:relative;flex:none} .su-chauto .sw2::before{content:"";position:absolute;inset:-9px -4px}',
    '.su-chrec{grid-column:1/-1;display:flex;align-items:center;gap:8px;margin-top:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.su-chri{color:var(--warn);display:grid;place-items:center;flex:none}',
    '.su-chrt{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1} .su-chrt b{color:var(--warn);font-weight:650} .su-chrt span{color:var(--text)}',
    '.su-chrm{font-size:12px;color:var(--text2);white-space:nowrap;font-variant-numeric:tabular-nums;flex:none}',
    '.su-chbig{color:var(--warn);font-weight:650}',
    '.su-chmore{padding:8px 0 2px}',
    '.su-choh{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--text2);font-weight:650;margin:16px 0 2px} .su-choh span{font-size:12px;font-weight:500;color:var(--muted)}',
    '.su-chfoot{border-top:1px solid var(--line);margin-top:4px;padding:12px 0 4px;display:flex;flex-direction:column;gap:4px} .su-chfh{display:flex;align-items:baseline;gap:8px;font-size:13.5px;flex-wrap:wrap}',
    '.su-chnote{margin-top:8px;line-height:1.55}',
    '.su-md{display:block} .su-mdp{display:block;line-height:1.65}',
    '.su-mdc{display:block;margin-top:14px;background:var(--surface2);border-radius:12px;padding:12px 14px;color:var(--text)}',
    '.su-mdh{display:flex;align-items:center;gap:8px;flex-wrap:wrap} .su-mdh b{font-size:14px;font-weight:600}',
    '.su-mdg{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:5px 14px;margin-top:10px;font-size:13px;line-height:1.5;font-variant-numeric:tabular-nums}',
    '.su-mdk{color:var(--text2);white-space:nowrap} .su-mdv{color:var(--text);min-width:0}',
    '.su-mdf{display:block;margin-top:8px;padding-top:8px;border-top:1px dashed var(--line2);font-size:12.5px;color:var(--muted)}',
    '.su-mda{display:block;margin-top:10px;font-size:12.5px;color:var(--text2)}',
    '@media (max-width:640px){.su-chr{grid-template-columns:minmax(0,1fr) auto 46px;column-gap:10px}.su-chs{white-space:normal}.su-chsp,.su-chdash{display:none}.su-chcol .su-chc{font-size:11px;max-width:64px;white-space:normal;line-height:1.3}.su-chrec{flex-wrap:wrap}.su-chrt{white-space:normal}.su-chrm{flex-basis:100%;white-space:normal;padding-left:23px}.su-chr.rec{margin:4px -8px;padding:10px 8px}}',
    '.su-chiprow{display:flex;gap:6px;flex-wrap:wrap}',
    '.su-chip{padding:6px 11px;border-radius:99px;font-size:13px;font-weight:600;border:1px solid var(--line);background:var(--surface2);color:var(--text2)}',
    '.su-chip.on{background:var(--accentBg);color:var(--accent);border-color:transparent}',
    '.su-chip.on::before{content:"✓ ";font-weight:700}',
    '.su-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center}',
    '.su-list{margin-top:14px;border-top:1px solid var(--line)}',
    '.su-row{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--line)}',
    '.su-addr{font-size:12.5px;color:var(--text2);word-break:break-all;margin:2px 0}',
    '.su-acc{border:1px solid var(--line);border-radius:14px;margin-top:10px;background:var(--surface)}',
    '.su-acch{display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:13px 16px;font-size:14.5px;flex-wrap:wrap}',
    '.su-accb{padding:0 16px 16px;border-top:1px solid var(--line)}',
    '.su-ol{margin:10px 0 6px 20px;font-size:13.5px;color:var(--text2);line-height:1.75}',
    '.su-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-top:10px}',
    '.su-fl{display:flex;flex-direction:column;gap:5px;min-width:0}',
    '.su-fl .field{width:100%}',
    '.su-test{margin-top:10px;padding:10px 12px;border-radius:10px;font-size:13.5px;line-height:1.55}',
    '.su-test.ok{background:var(--okBg);color:var(--ok)} .su-test.bad{background:var(--dangerBg);color:var(--danger)}',
    '.su-dep{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:0 16px 12px;font-size:13.5px}',
    '.su-dep .cap{font-size:12.5px}',
    '.su-ipbox{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--surface2);border-radius:12px;padding:10px 14px;margin-bottom:4px}',
    '.su-tgwait{display:flex;gap:20px;align-items:flex-start;margin-top:6px}',
    '.su-qrbox{flex:none;background:#fff;border-radius:14px;padding:8px}',
    '.su-qr{display:block}',
    'html.pvh .su-tgwait .su-qrbox,html.pvh .su-tgwait .su-actions{display:none}',
    '.su-wait{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:13.5px;color:var(--text2)}',
    '.su-spin{width:14px;height:14px;border-radius:50%;border:2px solid var(--line2);border-top-color:var(--accent);animation:suspin .9s linear infinite}',
    '@keyframes suspin{to{transform:rotate(360deg)}}',
    '@media (prefers-reduced-motion:reduce){.su-spin{animation:none}}',
    '.su-tgdone{display:flex;gap:12px;align-items:flex-start;margin-top:6px}',
    '.su-apply{margin-top:14px;padding:12px 14px;border-radius:12px;background:var(--surface2);font-size:14px}',
    '.su-units{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:10px}',
    '.su-unit{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:13px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:space-between}',
    '.su-unit .cap{flex-basis:100%;font-size:12px}',
    '.su-code{font-size:12.5px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:7px 10px;word-break:break-all}',
    'code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}',
    '.su-foot{display:flex;gap:8px;align-items:center;margin-top:18px}',
    '.su-skip{text-align:center;margin-top:12px}',
    '.su-demo{position:relative;z-index:31;text-align:center;font-size:12.5px;font-weight:700;padding:5px 12px;background:var(--warnBg);color:var(--warn)}',
    '@media (max-width:640px){.su-tsheet{border-radius:0;min-height:100%;padding:16px 16px calc(24px + env(safe-area-inset-bottom))}.su-bpl{columns:1}.su-ttiles b{font-size:16px}}',
    '@media (max-width:640px){.su-perm{border-radius:0;min-height:100%;padding:18px 16px calc(24px + env(safe-area-inset-bottom));border-width:0 0 0 4px}.su-perm h3{font-size:19px}.su-bg{padding:0}.su-wiz{border-radius:0;min-height:100%;padding:16px 16px calc(24px + env(safe-area-inset-bottom));border:0}.su-step span{display:none}.su-step.on span{display:inline}.su-tgwait{flex-direction:column;align-items:center}.su-sec{padding:16px}.su-grow{min-width:0;flex-basis:100%}.su-form .field[style]{width:100%!important}.su-kbd{display:none}}'
  ].join('\n');
  document.head.appendChild(css);

  (async function init() {
    await load();
    if (!U.st) return;
    if ((U.st.needsSetup && SS.get('tj_setup_later') !== '1') || SS.get('tj_su_wiz') === '1') { U.open = true; U.step = wizStep(); }
    render();
  })();
  window.__tjSetup = { U, A, render, fill, lock, qrEncode, toChecksum, checkAddr, keccak256, splitAddrs, wAnalyze, wSecret };
})();
