'use strict';
(function () {
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (s, r) => (r || document).querySelector(s);
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
      if (!/^[0-9a-fA-F]{40}$/.test(b)) return { err: 'EVM 주소는 0x + 16진수 40자입니다 (지금 ' + b.length + '자)' };
      if (/^0+$/.test(b)) return { err: '0 주소는 추적할 수 없습니다' };
      if (b !== b.toLowerCase() && b !== b.toUpperCase()) {
        if (toChecksum(a) !== '0x' + b) return { err: '체크섬 불일치 — 한 글자가 틀렸을 수 있습니다. 원문을 다시 복사하세요' };
        return { kind: 'evm', addr: a, note: 'EVM · 체크섬 확인됨' };
      }
      return { kind: 'evm', addr: a, note: 'EVM · 체크섬 없는 주소(오타 주의)', warn: true };
    }
    if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a)) return { err: '0x… EVM 주소 또는 Solana 주소가 아닙니다' };
    if (b58len(a) !== 32) return { err: 'Solana 주소는 base58 32바이트여야 합니다' };
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
      if (!/^dydx1[02-9ac-hj-np-z]{38}$/i.test(a)) return { err: 'dYdX 주소는 dydx1 로 시작하는 43자입니다 (지금 ' + a.length + '자)' };
      return bech32Ok(a, 'dydx') ? { addr: a.toLowerCase(), note: 'dYdX 주소 확인됨' } : { err: 'dYdX 주소 체크섬 불일치 — 원문을 다시 복사하세요' };
    }
    const c = checkAddr(a);
    if (!c || c.err) return c;
    if (kind === 'evm' && c.kind !== 'evm') return { err: name + ' 은 0x… EVM 주소를 씁니다' };
    if (kind === 'sol' && c.kind !== 'sol') return { err: name + ' 는 Solana 주소를 씁니다' };
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
      if (!c || c.err) return { t, st: 'bad', err: c ? c.err : '주소가 아닙니다' };
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
    return '<li class="su-pi ' + x.st + '"><span class="su-pic" aria-hidden="true">' + W_IC[x.st] + '</span><div class="su-pib"><span class="su-pa num">' + esc(t) + '</span>'
      + (x.c ? ' <span class="pill ' + (x.c.kind === 'sol' ? 'ok' : 'a') + ' sm">' + (x.c.kind === 'sol' ? 'Solana' : 'EVM') + '</span>' : '')
      + '<div class="su-pis">' + esc(txt) + '</div>' + (se && x.c && x.st !== 'have' && x.st !== 'dup' ? '<div class="su-pis su-pise">지난 저장 실패 · ' + esc(se) + '</div>' : '') + '</div></li>';
  }
  const W_HINT = '0x… (EVM·BSC 공용) 또는 Solana 주소 · 여러 개는 쉼표나 줄바꿈(Enter)으로 나눠 한 번에 넣을 수 있어요 · 개인 키·시드는 절대 입력하지 마세요 — 주소만 필요합니다';
  function wMsgHTML(an) {
    if (!an.toks.length) return '<span class="cap">' + esc(W_HINT) + '</span>';
    const secret = an.secret ? '<div class="su-bad" role="alert"' + (an.multi ? ' style="margin-bottom:8px"' : '') + '>' + esc(W_SECRET[an.secret]) + '</div>' : '';
    if (!an.multi && an.secret) return secret;
    if (!an.multi) {
      const x = an.items[0];
      return x.st === 'bad' ? '<span class="su-bad">' + esc(x.err) + '</span>'
        : x.st === 'have' ? '<span class="su-bad">이미 같은 체인으로 등록된 주소예요' + (x.w && x.w.label ? ' (' + esc(x.w.label) + ')' : '') + '</span>'
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
      + (n > MAX_BATCH ? '<div class="su-bad" style="margin-top:6px">한 번에 최대 ' + MAX_BATCH + '개까지 추가할 수 있어요 — 지금 ' + n + '개, 나눠서 넣어 주세요</div>' : '')
      + (an.needChain ? '<div class="su-bad" style="margin-top:6px">아래에서 EVM 체인을 하나 이상 고르세요</div>' : '');
  }
  function wBtn(an) {
    if (!an.multi) return { t: U.busy.wadd ? '추가 중…' : '지갑 추가', dis: !!U.busy.wadd };
    const n = an.save.length;
    return { t: U.busy.wadd ? '추가 중…' : n ? '지갑 ' + n + '개 추가' : '추가할 주소 없음', dis: !!U.busy.wadd || !n || n > MAX_BATCH || an.needChain };
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
    upbit: { url: 'https://upbit.com/mypage/open_api_management', steps: ['업비트 웹 로그인 → 마이페이지 → Open API 관리', '권한은 <b>자산조회</b>만 체크 (주문하기·출금하기·입금하기는 체크하지 마세요)', '허용 IP 주소에 <b>이 서버의 공인 IP</b> 를 입력 (업비트는 IP 등록 필수)', 'Access Key·Secret Key 발급 — Secret 은 한 번만 보이니 바로 붙여넣으세요'], note: '키 유효기간(1년)이 지나면 다시 발급해야 합니다.' },
    bithumb: { url: 'https://www.bithumb.com/react/api-support/management-api', steps: ['빗썸 웹 로그인 → 마이페이지 → API 관리 → <b>API 2.0</b> 키 생성', '권한은 <b>자산조회</b>만 선택 (주문·출금 제외)', '허용 IP 에 이 서버 공인 IP 등록', 'API Key·Secret Key 를 붙여넣기'], note: '구 API(1.0) 키는 지원하지 않습니다.' },
    binance: { url: 'https://www.binance.com/en/my/settings/api-management', steps: ['Account → API Management → Create API → <b>System generated</b>', '권한은 <b>Enable Reading</b> 만 (Spot & Margin Trading·Futures·Withdrawals·Universal Transfer 모두 끔)', 'IP access restrictions → <b>Restrict access to trusted IPs only</b> → 이 서버 공인 IP', 'API Key·Secret Key 붙여넣기'], note: '저장할 때 키 권한을 확인해 거래·출금·이체 권한이 켜져 있으면 저장하지 않습니다.' },
    bybit: { url: 'https://www.bybit.com/app/user/api-management', steps: ['Account & Security → API → Create New Key → <b>System-generated API Keys</b>', '<b>API Transaction</b> 대신 <b>Read-Only</b> 선택', 'IP 제한: <b>Only IPs with permissions granted</b> → 이 서버 공인 IP', 'API Key·Secret 붙여넣기'], note: '통합 거래 계정(UTA) 기준으로 조회합니다.' },
    okx: { url: 'https://www.okx.com/account/my-api', steps: ['프로필 → API → Create API key', '권한은 <b>Read</b> 만 (Trade·Withdraw 체크 금지)', 'IP 주소 허용 목록에 이 서버 공인 IP', '만들 때 정한 <b>Passphrase</b> 도 함께 입력'], note: 'Passphrase 는 OKX 가 다시 보여주지 않으니 기억해 두세요.' },
    kucoin: { url: 'https://www.kucoin.com/account/api', steps: ['API Management → Create API → API Trading', '권한은 <b>General</b> 만 (Spot·Margin·Futures Trading, Transfer, Withdrawal 끔)', 'IP Restriction → 이 서버 공인 IP', 'API Key·Secret·<b>Passphrase</b> 입력'], note: '' },
    gate: { url: 'https://www.gate.io/myaccount/api_key_manage', steps: ['API Keys → Create API Key → <b>API v4 Key</b>', '권한: Spot·Wallet 을 <b>Read Only</b> 로 (나머지 끔)', 'IP 화이트리스트에 이 서버 공인 IP', 'API Key·Secret 붙여넣기'], note: '' }
  };
  const XP_HELP = {
    helius: { url: 'https://dashboard.helius.dev', why: 'Solana 지갑 수집에 필요합니다 (무료 플랜으로 충분).', steps: ['dashboard.helius.dev 가입(무료)', 'API Keys 에서 키 복사 → 붙여넣기'] },
    etherscan: { url: 'https://etherscan.io/myapikey', why: '선택 — Ethereum·Arbitrum·Polygon 과거 거래 백필이 수십 배 빨라집니다. 없어도 전 체인 동작합니다.', steps: ['etherscan.io 가입(무료) → API Keys → Add', '키 하나로 여러 체인 조회(V2) — 붙여넣기'] },
    opensea: { url: 'https://docs.opensea.io/reference/api-keys', why: '선택 · 추천 — 넣으면 기타 자산 › NFT 의 EVM 바닥가를 오픈시에서 먼저 받아(최우선) 작은 컬렉션까지 NFT 추적이 더 원활해요. 없으면 코인게코(무료 데모 키 권장). 미검증(키 없이 공개 문서만 보고 연결).', steps: ['opensea.io 계정 → API 키 신청(무료)', '받은 키 붙여넣기'] },
    coingecko: { url: 'https://www.coingecko.com/en/developers/dashboard', why: '선택 · 무료 — 기타 자산 › NFT 의 EVM 바닥가가 빨라져요(키 없으면 무료 호출 제한에 걸려 몇 시간 걸릴 수 있어요). 재시작 없이 바로 써요.', steps: ['coingecko.com 무료 가입 → Developers Dashboard', '+ Add New Key 로 Demo 키 만들기(무료)', '받은 키(CG-…) 붙여넣기'] }
  };
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
  function toast(msg, err) {
    const t = $('#toast'); if (!t) return;
    t.innerHTML = '<div class="toast' + (err ? ' e' : '') + '" role="status">' + esc(msg) + '</div>';
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.innerHTML = ''; }, err ? 4600 : 2600);
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
  function walletsHTML() {
    const st = U.st, ws = st.wallets || [];
    const an = wAnalyze(draft('w_addr')), wb = wBtn(an), nw = newW();
    const chips = (st.chains || []).filter(c => c && c.key && String(c.key)[0] !== '_').map(c => '<button class="su-chip' + (U.chains.has(c.key) ? ' on' : '') + '" data-su="chain" data-v="' + esc(c.key) + '" aria-pressed="' + U.chains.has(c.key) + '">' + esc(c.name) + '</button>').join('');
    let list = '';
    if (ws.length) {
      list = '<div class="su-list">' + ws.map(w => '<div class="su-row' + (nw.has(w.address) ? ' new' : '') + '"><div style="min-width:0;flex:1"><b>' + esc(w.label || '(이름 없음)') + '</b> ' + pill(w.kind === 'sol' ? 'ok' : 'a', w.kind === 'sol' ? 'Solana' : 'EVM')
        + (nw.has(w.address) ? ' <span class="pill w sm" title="이름은 설정 › 추적 지갑에서 이름을 누르면 바로 바꿀 수 있어요">새로 추가</span>' : '')
        + '<div class="su-addr num">' + esc(w.address) + '</div><div class="cap">' + w.chains.map(chainName).map(esc).join(' · ') + '</div>'
        + (w.reconDone && w.reconDone.length ? ' <span class="pill w sm" title="기초잔고 대조가 끝난 뒤 추가된 체인(' + esc(w.reconDone.map(chainName).join(', ')) + ') — 백필이 끝난 뒤 재구축(README › 백필)하면 이 지갑의 과거 보유분까지 맞춰집니다">과거 보유분 재구축 필요</span>' : '')
        + '</div><button class="btn sm" data-su="wdel" data-v="' + esc(w.address) + '" aria-label="지갑 삭제">삭제</button></div>').join('') + '</div>';
    }
    return '<div class="su-sec"><div class="su-h">추적할 지갑</div><div class="cap su-p">주소만으로 온체인 거래를 읽어 매매일지를 만듭니다. 서명·송금 권한은 필요 없고 요청하지도 않습니다. 새 지갑은 최근 ' + esc(st.backfillMonths) + '개월 거래부터 자동으로 불러옵니다.</div>'
      + '<div class="su-form su-wform"><textarea class="field su-grow su-ta" rows="1" data-su-in="w_addr" placeholder="0x… 또는 Solana 주소 (여러 개 가능)" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="지갑 주소 — 여러 개는 쉼표·줄바꿈으로 구분" aria-describedby="suVmsg"></textarea>'
      + '<input class="field' + (an.multi ? ' hidden' : '') + '" id="suWLabel" style="width:170px" data-su-in="w_label" placeholder="이름 (예: 메인)" maxlength="24" aria-label="지갑 이름"></div>'
      + '<div class="su-vmsg" id="suVmsg">' + wMsgHTML(an) + '</div>'
      + '<div class="su-chains' + (an.onlySol ? ' hidden' : '') + '" id="suChains"><div class="cap" style="margin-bottom:6px">EVM 체인 선택 · 같은 주소를 체인별로 추적합니다 <button class="link" data-su="chainAll">전체</button> · <button class="link" data-su="chainNone">해제</button></div><div class="su-chiprow">' + chips + '</div></div>'
      + '<div class="su-actions"><button class="btn pri" id="suWadd" data-su="wadd"' + (wb.dis ? ' disabled' : '') + '>' + esc(wb.t) + '</button><span class="cap su-kbd">Enter = 줄바꿈(다음 주소) · ⌘/Ctrl+Enter = 추가</span></div>'
      + wResHTML()
      + list + (ws.some(w => w.kind === 'sol') && st.solNeedsHelius && !st.explorers.helius.set ? '<div class="bnr w" style="margin-top:12px"><div><b>Solana 지갑은 Helius 키가 필요합니다</b><div class="bd">다음 단계에서 무료 키를 넣으면 Solana 수집이 시작됩니다.</div></div></div>' : '') + '</div>';
  }

  function fieldsHTML(gk, g, help) {
    const t = U.test[gk];
    const tr = t ? '<div class="su-test ' + (t.ok ? 'ok' : 'bad') + '">' + (t.ok ? '연결 성공 · ' : '실패 · ') + esc(t.detail || '') + (t.warn || []).map(w => '<div class="su-warnline">' + esc(w) + '</div>').join('') + '</div>' : '';
    return (help ? help : '') + '<div class="su-fields">' + g.fields.map(f => '<label class="su-fl"><span class="cap">' + esc(f.label) + (f.set ? ' · 저장됨 <span class="num">' + esc(f.masked) + '</span>' : '') + '</span>'
      + '<input class="field" type="password" autocomplete="off" spellcheck="false" data-su-in="k_' + esc(f.key) + '" placeholder="' + (f.set ? '바꾸려면 새 값 입력 (비우면 저장된 값 유지)' : esc(f.label) + ' 붙여넣기') + '" aria-label="' + esc(g.name + ' ' + f.label) + '"></label>').join('') + '</div>'
      + permHTML(gk, g)
      + '<div class="su-actions"><button class="btn" data-su="ktest" data-v="' + gk + '"' + (U.busy['t' + gk] ? ' disabled' : '') + '>' + (U.busy['t' + gk] ? '확인 중…' : '연결 테스트') + '</button>'
      + '<button class="btn pri" data-su="ksave" data-v="' + gk + '"' + (U.busy['s' + gk] ? ' disabled' : needAck(gk) && !U.ack[gk] ? ' disabled title="\'조회 권한만 켰음\'을 먼저 체크하세요"' : '') + '>' + (U.busy['s' + gk] ? '권한 확인 중…' : '저장') + '</button>' + (g.partial ? '<button class="btn danger" data-su="kdel" data-v="' + gk + '">삭제</button>' : '') + '</div>' + tr;
  }
  const needAck = gk => { const ex = U.st && U.st.exchanges && U.st.exchanges[gk]; return !!ex && !ex.permCheck; };
  function permHTML(gk, g) {
    const ex = U.st.exchanges && U.st.exchanges[gk];
    if (!ex) return '';
    const on = !!U.ack[gk];
    const saved = ex.perm && ex.perm.how ? '<div class="cap su-permnote">저장된 키 · ' + (ex.perm.how === 'api' ? '<span class="oktxt">조회 전용 자동 확인됨</span>' : '조회 전용 본인 확인') + (ex.perm.at ? ' <span class="num">' + esc(ago(ex.perm.at)) + '</span>' : '') + ' · <b>연결 테스트</b>(빈 칸)로 다시 검사할 수 있어요</div>' : '';
    const line = ex.permCheck
      ? '<div class="cap su-permnote">저장할 때 키 권한을 자동으로 확인해요 — <b>조회 말고 다른 권한(거래·출금·이체 등)이 켜져 있으면 저장하지 않아요.</b> 확인이 안 되면(연결 실패) 저장하지 않으니 잠시 뒤 다시 저장하세요.</div>'
      : '<div class="cap su-permnote">' + esc(g.name) + '는 API 로 키 권한을 확인할 수 없어요(자동 확인은 바이낸스·바이비트·OKX 만) — 발급 화면에서 <b>조회 권한만</b> 켰는지 직접 확인하고 체크하세요.</div>';
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
      + '<div style="min-width:0"><div class="su-permkick">' + esc(kick) + '</div><h3 id="suPermT">' + esc(p.title || '위험한 권한이 켜져 있습니다') + '</h3></div></div>'
      + '<div class="su-permsec"><b>켜져 있는 권한</b><ul>' + (p.danger || []).map(d => '<li><span class="pill e sm">' + esc(PERM_KIND[d.kind] || d.kind) + '</span> ' + esc(d.label) + '</li>').join('') + '</ul></div>'
      + '<div class="su-permsec"><b>왜 위험한가요</b><p id="suPermD">' + esc(p.why || '') + '</p></div>'
      + '<div class="su-permsec"><b>조회 전용 키로 다시 만드는 법</b><ol>' + (p.fix || []).map(x => '<li>' + esc(x) + '</li>').join('') + '</ol>'
      + (h.url ? '<a href="' + h.url + '" target="_blank" rel="noopener noreferrer">' + esc(p.name || '') + ' API 관리 페이지 ↗</a>' : '') + '</div>'
      + (p.stored ? '<div class="cap su-p">봇은 이 키로 조회만 하지만, 새로 만든 조회 전용 키를 저장하면 지금 키를 대체해요. 대체한 뒤 거래소에서 옛 키를 꼭 삭제하세요.</div>' : '')
      + '<div class="su-foot"><span class="sp"></span><button class="btn pri" data-su="permClose">알겠어요 — 조회 전용 키로 다시 넣을게요</button></div>'
      + '</div></div>';
  }
  function keysHTML() {
    const st = U.st;
    return '<div class="su-sec"><div class="su-h">탐색기 API 키</div><div class="cap su-p">키는 이 서버의 <code>.env</code>(권한 600)에만 저장되고 화면에는 •••• 로만 보입니다(값은 다시 표시하지 않음).</div>'
      + ['helius', 'etherscan', 'coingecko', 'opensea'].filter(k => st.explorers[k]).map(k => {
        const g = st.explorers[k], h = XP_HELP[k], open = U.xp === k || (U.xp == null && k === 'helius');
        return '<div class="su-acc' + (open ? ' open' : '') + '"><button class="su-acch" data-su="xp" data-v="' + k + '" aria-expanded="' + open + '"><b>' + esc(g.name) + '</b>'
          + (k === 'helius' && st.wallets.some(w => w.kind === 'sol') && st.solNeedsHelius ? ' ' + pill('w', 'Solana 필수') : ' ' + pill('g', k === 'helius' ? 'Solana 지갑이 있으면 필수' : k === 'coingecko' ? '선택 · 무료' : '선택'))
          + '<span class="sp"></span>' + pill(g.set ? 'ok' : 'g', g.set ? '저장됨' : '미설정') + '</button>'
          + (open ? '<div class="su-accb">' + fieldsHTML(k, g, '<div class="cap su-p">' + esc(h.why) + ' <a href="' + h.url + '" target="_blank" rel="noopener noreferrer">발급 페이지 ↗</a></div><ol class="su-ol">' + h.steps.map(s => '<li>' + esc(s) + '</li>').join('') + '</ol>') + '</div>' : '') + '</div>';
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
    const head = dp.count ? '입금주소 <b class="num">' + esc(dp.count) + '</b>개' + (dp.addresses && dp.addresses !== dp.count ? ' <span class="cap">(주소 ' + esc(dp.addresses) + '종 · 통화 ' + esc(dp.currencies) + '개)</span>' : '')
      : (keySet ? '입금주소 수집 대기' : '입금주소 없음');
    const when = dp.lastRefresh ? ' · 마지막 갱신 ' + esc(ago(dp.lastRefresh)) : (keySet ? ' · 곧 첫 수집' : '');
    const st9 = busy ? ' ' + pill('a', dp.running ? '수집 중…' : '요청됨') : dp.lastError ? ' <span class="pill w sm" title="' + esc(dp.lastError) + '">' + (dp.lastRefresh && dp.lastRefresh >= (dp.lastAttempt || 0) ? '일부 실패' : '실패 · 기존 주소 유지') + '</span>' : '';
    return '<div class="su-dep"><div style="min-width:0"><span>' + head + '</span><span class="cap">' + when + '</span>' + st9 + '</div><span class="sp"></span>'
      + (keySet ? '<button class="btn sm" data-su="dprefresh" data-v="' + esc(k) + '"' + (busy ? ' disabled' : '') + '>' + (busy ? '갱신 중' : '새로고침') + '</button>' : '') + '</div>';
  }
  function exchangesHTML() {
    const st = U.st;
    return '<div class="su-sec"><div class="su-h">거래소 API (선택 · 조회 전용)</div><div class="cap su-p">입금·체결·잔고를 가져와 온체인 전송과 짝지어 원가를 이어 줍니다. <b>조회(읽기) 권한만</b> 켠 키를 쓰세요 — 이 봇은 주문·출금 API 를 호출하지 않습니다.</div>'
      + '<div class="cap su-p">키를 저장하면 <b>내 계정 입금주소</b>를 자동으로 모읍니다(첫 수집 즉시 · 하루 1회 · 새 코인·네트워크가 생기면 바로). 이 주소들로 보낸 전송은 거래소 입금으로 자동 인식하고, 거래소가 주소를 바꿔도 옛 주소는 지우지 않습니다.</div>'
      + '<div class="su-ipbox"><div style="min-width:0"><b>이 서버의 공인 IP</b><div class="cap">거래소 키의 IP 화이트리스트에 넣을 값</div></div><span class="sp"></span>' + (U.ip ? '<code class="num">' + esc(U.ip) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(U.ip) + '">복사</button>' : '<button class="btn sm" data-su="ip">확인</button>') + '</div>'
      + EX_ORDER.map(k => {
        const g = st.exchanges[k], h = EX_HELP[k], open = U.ex === k;
        return '<div class="su-acc' + (open ? ' open' : '') + '"><button class="su-acch" data-su="ex" data-v="' + k + '" aria-expanded="' + open + '"><b>' + esc(g.name) + '</b><span class="sp"></span>' + pill(g.set ? 'ok' : g.partial ? 'w' : 'g', g.set ? '연결됨' : g.partial ? '일부 입력' : '미설정') + '</button>'
          + depRowHTML(k, (st.depaddr || {})[k], g.set)
          + (open ? '<div class="su-accb">' + fieldsHTML(k, g, '<ol class="su-ol">' + h.steps.map(s => '<li>' + s + '</li>').join('') + '</ol>' + (h.note ? '<div class="cap su-p">' + esc(h.note) + '</div>' : '') + '<div class="cap su-p"><a href="' + h.url + '" target="_blank" rel="noopener noreferrer">' + esc(g.name) + ' API 관리 페이지 ↗</a> · 저장하면 1분 안에 동기화가 시작됩니다(재시작 불필요)</div>') + '</div>' : '') + '</div>';
      }).join('') + '</div>';
  }
  function tgHTML() {
    const st = U.st, T = U.tg, tg = st.telegram || {};
    let body = '';
    if (T.phase === 'done' || (tg.connected && T.phase !== 'wait')) {
      body = '<div class="su-tgdone"><div class="su-big">' + pill('ok', '연결됨') + '</div><div><b>@' + esc(tg.bot || '?') + '</b> → ' + esc(tg.chatName || '채팅') + ' <span class="cap num">(' + esc(tg.chatMasked || '') + ')</span><div class="cap">목표가·손절 도달, 새 거래 분류, 검토 필요 알림이 이 채팅으로 옵니다 (시간당 최대 30통, 같은 종류는 묶어서). 어떤 알림을 받을지는 설정 › 알림(텔레그램)에서 골라요.</div></div></div>'
        + '<div class="su-actions"><button class="btn" data-su="tgtest">테스트 알림 보내기</button><button class="btn danger" data-su="tgoff">연결 해제</button></div>';
    } else if (T.phase === 'wait') {
      const mm = Math.max(0, Math.floor(T.left / 60)), ss = Math.max(0, T.left % 60);
      body = '<div class="su-tgwait"><div class="su-qrbox">' + (T.link ? qrSVG(T.link, 176) : '') + '<div class="cap" style="text-align:center;margin-top:6px">휴대폰 카메라로 스캔</div></div>'
        + '<div style="min-width:0;flex:1"><div class="su-h" style="margin:0 0 6px">봇 <span class="num">@' + esc(T.bot && T.bot.username) + '</span> 에게 /start 를 보내세요</div>'
        + '<ol class="su-ol"><li>아래 버튼(또는 QR)으로 텔레그램에서 봇을 엽니다</li><li><b>시작(Start)</b> 을 누르면 이 화면이 자동으로 채팅을 찾습니다</li><li>찾으면 테스트 메시지를 보내고 저장합니다</li></ol>'
        + '<div class="su-actions" style="margin-top:10px"><a class="btn pri" href="' + esc(T.link) + '" target="_blank" rel="noopener noreferrer">텔레그램에서 열기</a><button class="btn" data-su="copy" data-v="' + esc(T.start) + '">명령 복사: <span class="num">' + esc(T.start) + '</span></button></div>'
        + '<div class="su-wait"><span class="su-spin" aria-hidden="true"></span>/start 기다리는 중 · <span class="num">' + mm + ':' + (ss < 10 ? '0' : '') + ss + '</span> 남음</div>'
        + (T.err ? '<div class="su-bad" style="margin-top:8px">' + esc(T.err) + '</div>' : '')
        + '<div style="margin-top:10px"><button class="link" data-su="tgman">' + (T.manual ? '직접 입력 닫기' : 'chat_id 를 직접 입력할래요') + '</button> · <button class="link" data-su="tgcancel">다른 토큰으로</button></div>'
        + (T.manual ? '<div class="su-form" style="margin-top:8px"><input class="field su-grow" data-su-in="tg_chat" placeholder="chat_id (예: 123456789 / 그룹 -100…)" inputmode="text" aria-label="chat_id">'
          + (T.tok ? '' : '<input class="field su-grow" type="password" autocomplete="off" spellcheck="false" data-su-in="tg_mtoken" placeholder="봇 토큰 (chat_id 를 바꾸려면 다시 입력)" aria-label="텔레그램 봇 토큰">')
          + '<button class="btn" data-su="tgmanual">테스트 후 저장</button></div>' : '')
        + '</div></div>';
    } else {
      body = '<ol class="su-ol"><li>텔레그램에서 <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a> → <code>/newbot</code> → 이름·아이디 정하기</li><li>받은 토큰(<code>123456789:AA…</code>)을 붙여넣고 확인</li><li>알림 전용 <b>새 봇</b>을 쓰세요 — 다른 프로그램이 쓰는 봇은 업데이트를 뺏고 뺏겨 연결이 끊깁니다</li></ol>'
        + '<div class="su-form"><input class="field su-grow" type="password" autocomplete="off" spellcheck="false" data-su-in="tg_token" placeholder="봇 토큰 붙여넣기" aria-label="텔레그램 봇 토큰"><button class="btn pri" data-su="tgval"' + (U.busy.tg ? ' disabled' : '') + '>' + (U.busy.tg ? '확인 중…' : '토큰 확인') + '</button></div>'
        + (T.err ? '<div class="su-bad" style="margin-top:8px">' + esc(T.err) + '</div>' : '');
    }
    return '<div class="su-sec"><div class="su-h">텔레그램 알림 (선택)</div><div class="cap su-p">연결하지 않아도 모든 기능이 동작합니다. 알림은 연결하는 순간부터 새로 생긴 것만 보냅니다.</div>' + body + '</div>';
  }
  function applyHTML() {
    const a = U.st.apply || {};
    if (!a.runner) return '<div class="su-apply"><b>적용</b><div class="cap">이 설치는 유닛 러너 없이 실행 중입니다. 지갑·탐색기 키를 바꾼 뒤 한 번 재시작하세요 (거래소 키·텔레그램은 재시작 없이 1분 안에 반영).</div><div class="su-form" style="margin-top:8px"><code class="su-code su-grow">' + esc(a.manual) + '</code><button class="btn sm" data-su="copy" data-v="' + esc(a.manual) + '">복사</button></div></div>';
    const us = a.units || {};
    return '<div class="su-apply"><b>적용 상태</b><div class="cap">설정을 바꾸면 해당 유닛이 약 30초 안에 스스로 다시 시작합니다. 거래소 키·텔레그램은 재시작 없이 1분 안에 반영됩니다.</div><div class="su-units">'
      + Object.keys(UNIT_KO).map(u => { const x = us[u] || {}; const cls = x.state === 'applied' ? 'ok' : x.state === 'pending' ? 'a' : x.state === 'waiting' ? 'g' : 'g';
        const t = x.state === 'applied' ? '적용됨' : x.state === 'pending' ? '적용 중' : x.state === 'waiting' ? '대기' : '—';
        return '<div class="su-unit"><span>' + UNIT_KO[u] + '</span>' + pill(cls, t) + (x.state === 'waiting' && x.why ? '<div class="cap">' + esc(x.why) + '</div>' : '') + '</div>'; }).join('') + '</div></div>';
  }
  function finishHTML() {
    const st = U.st, cur = draft('cur') || st.prefs.currency || 'KRW', light = document.documentElement.getAttribute('data-theme') === 'light';
    const opt = (a, v, on, t, s) => '<button class="opt2' + (on ? ' on' : '') + '" data-su="' + a + '" data-v="' + v + '" aria-pressed="' + on + '"><b>' + t + '</b><span>' + s + '</span></button>';
    const exN = EX_ORDER.filter(k => st.exchanges[k].set).length;
    const rows = [['지갑', st.wallets.length ? st.wallets.length + '개 주소' : '없음 — 나중에 설정 탭에서 추가', st.wallets.length > 0],
      ['Helius (Solana)', st.explorers.helius.set ? '저장됨' : (st.wallets.some(w => w.kind === 'sol') ? '필요 — Solana 수집 대기' : '선택'), st.explorers.helius.set],
      ['Etherscan 가속', st.explorers.etherscan.set ? '저장됨' : '없음 (blockscout 로 동작)', st.explorers.etherscan.set],
      ['거래소', exN ? exN + '곳 연결' : '없음 (온체인만)', exN > 0], ['텔레그램', st.telegram.connected ? '@' + (st.telegram.bot || '') + ' 연결됨' : '연결 안 함', st.telegram.connected]];
    return '<div class="su-sec"><div class="su-h">표시</div><div class="cap" style="margin:10px 0 8px">기준 통화</div><div class="opts">' + opt('cur', 'KRW', cur === 'KRW', 'KRW', '업비트 USDT 환산') + opt('cur', 'USD', cur === 'USD', 'USD', '달러 원가 기준') + '</div>'
      + '<div class="cap" style="margin:14px 0 8px">테마</div><div class="opts">' + opt('theme', 'dark', !light, '다크', '기본') + opt('theme', 'light', light, '라이트', '밝은 배경') + '</div></div>'
      + '<div class="su-sec"><div class="su-h">요약</div>' + rows.map(r => '<div class="kv"><span>' + esc(r[0]) + '</span><span class="' + (r[2] ? 'oktxt' : 'mut') + '">' + esc(r[1]) + '</span></div>').join('') + applyHTML() + '</div>';
  }
  const PERP_FMT = { evm: '0x… EVM 주소', sol: 'Solana 주소', dydx: 'dydx1… 주소' };
  function perpDex() { const P = (U.st && U.st.perp) || {}, ds = P.dexes || []; return ds.find(d => d.key === U.pdex) || ds[0] || null; }
  function perpVmsg(d, raw) {
    const c = d ? checkPerpAddr(d.kind, raw, d.name) : null;
    return !c ? '<span class="cap">' + esc(d ? d.name + ' — ' + PERP_FMT[d.kind] : '') + ' · 개인 키·시드는 절대 입력하지 마세요 — 주소만 필요합니다</span>'
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
      return '<div class="su-row"><div style="min-width:0;flex:1"><b>' + esc(w.label || '(이름 없음)') + '</b> ' + pill('a', w.name)
        + '<div class="su-addr num">' + esc(w.address) + '</div><div>' + stH + (s9.unk ? ' <span class="cap" title="Lighter 체결 중 방향을 판정하지 못해 손익을 기록하지 않은 건수">· 손익 판정 못 한 체결 ' + esc(s9.unk) + '건</span>' : '') + '</div></div>'
        + '<button class="btn sm" data-su="pdel" data-v="' + esc(w.dex + '|' + w.address) + '" aria-label="퍼프 덱스 주소 삭제">삭제</button></div>';
    }).join('') + '</div>' : '';
    return '<div class="su-sec"><div class="su-h">퍼프 덱스 (선택 · 주소만)</div>'
      + '<div class="cap su-p">탈중앙 선물 거래소(퍼프 덱스) 주소를 넣으면 <b>현재 포지션·거래 내역·펀딩·청산</b>을 선물 화면에 거래소 선물과 나란히 보여 줍니다. 실현 손익·펀딩·수수료는 매매일지·세금 명세의 선물 정산에 같은 규칙으로 들어가요(USD 기준 · 원화 = 정산 시각 환율). 키·서명은 필요 없고 요청하지도 않습니다(공개 조회).</div>'
      + '<div class="cap su-p">덱스에 맡긴 담보·계정 가치는 총자산에 더하지 않아요(표시 전용 — Rabby 가 이미 잡는 경우 이중 계산 방지). 새 주소는 저장 후 15초 안에 수집을 시작하고, 과거 기록은 수집 시작일부터 받을 수 있는 만큼 몇 주기에 나눠 받습니다.</div>'
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
    return '<div class="su-bg" role="dialog" aria-modal="true" aria-labelledby="suTitle"><div class="su-wiz">'
      + '<div class="su-top"><div class="logo"><i></i><span id="suTitle">처음 설정</span></div>' + (st.demo ? pill('w', '데모 모드') : '') + '<span class="sp"></span><button class="iconbtn" data-su="close" aria-label="닫기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>'
      + '<div class="su-intro cap">온체인 지갑과 거래소 기록을 모아 매매일지·손익을 자동으로 만듭니다. 모든 데이터는 이 서버에만 저장되고, 화면은 이 컴퓨터(또는 테일넷)에서만 열립니다.</div>'
      + '<nav class="su-steps" aria-label="설정 단계">' + nav + '</nav>'
      + '<div class="su-body">' + SEC[s.k]() + '</div>'
      + '<div class="su-foot">' + (U.step > 0 ? '<button class="btn" data-su="prev">이전</button>' : '<span></span>') + '<span class="sp"></span>'
      + (U.step < STEPS.length - 1 ? (s.k !== 'wallets' ? '<button class="btn" data-su="next">건너뛰기</button>' : '') + '<button class="btn pri" data-su="next"' + (needW ? ' disabled title="지갑을 하나 이상 추가하세요"' : '') + '>다음</button>'
        : '<button class="btn pri" data-su="finish">설정 완료 · 대시보드로</button>') + '</div>'
      + (needW ? '<div class="su-skip"><button class="link" data-su="later">나중에 할게요 (설정 탭에서 언제든 가능)</button></div>' : '')
      + '</div></div>';
  }
  function panelHTML() {
    const st = U.st;
    const tabs = [['wallets', '지갑'], ['perp', '퍼프 덱스'], ['keys', '탐색기 키'], ['exchanges', '거래소'], ['telegram', '텔레그램']];
    const cur = U.where || 'wallets';
    const nW = (st.wallets || []).length, tg = st.telegram && st.telegram.connected, nP = ((st.perp || {}).wallets || []).length;
    const head = '<div class="row gap12" style="flex-wrap:wrap"><div class="h2">연결 · 키</div>' + (st.demo ? pill('w', '데모 모드') : '') + '<span class="cap">지갑 ' + nW + '개' + (nP ? ' · 퍼프 덱스 ' + nP + '개' : '') + ' · 텔레그램 ' + (tg ? '연결됨' : '미연결') + '</span><span class="sp"></span>'
      + (U.panelOpen ? '<button class="btn sm" data-su="wizard">설정 마법사 열기</button>' : '') + '<button class="btn sm" data-su="ptoggle" aria-expanded="' + !!U.panelOpen + '">' + (U.panelOpen ? '접기' : '관리하기') + '</button></div>';
    if (!U.panelOpen) return '<div class="card scard su-panel">' + head + '</div>';
    return '<div class="card scard su-panel">' + head
      + '<div class="desc">지갑·탐색기 키·거래소 조회 키·텔레그램을 여기서 관리합니다. 비밀값은 서버 <code>.env</code>(600)에만 있고 다시 표시되지 않습니다.</div>'
      + '<div class="subtabs" role="tablist">' + tabs.map(t => '<button role="tab" data-su="ptab" data-v="' + t[0] + '" class="' + (cur === t[0] ? 'on' : '') + '" aria-selected="' + (cur === t[0]) + '">' + t[1] + '</button>').join('') + '</div>'
      + SEC[cur]() + applyHTML() + '</div>';
  }

  let wizEl = null, panelEl = null, permEl = null;
  function onSettings() { return (location.hash || '').replace('#', '') === 'settings'; }
  function render() {
    if (!U.st || isLocked()) return;
    const keepFocus = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-su-in');
    const pos = keepFocus && document.activeElement.selectionStart;
    if (U.open) {
      if (!wizEl) { wizEl = document.createElement('div'); wizEl.id = 'suWizard'; document.body.appendChild(wizEl); }
      wizEl.innerHTML = wizardHTML();
      document.documentElement.classList.add('su-lock');
    } else if (wizEl) { wizEl.remove(); wizEl = null; document.documentElement.classList.remove('su-lock'); }
    if (!panelEl) { panelEl = document.createElement('section'); panelEl.id = 'suPanel'; panelEl.className = 'page su-pagetop'; const v = $('#view'); if (v) v.parentNode.insertBefore(panelEl, v); }
    panelEl.classList.toggle('hidden', !onSettings() || U.open);
    if (onSettings() && !U.open) panelEl.innerHTML = panelHTML();
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
    Object.assign(U.tg, { phase: 'idle', err: '', bot: null, link: '', start: '', left: 0, tok: '' });
    if (wizEl) { wizEl.remove(); wizEl = null; }
    if (permEl) { permEl.remove(); permEl = null; }
    const pn = panelEl || $('#suPanel'); if (pn) { pn.innerHTML = ''; pn.classList.add('hidden'); }
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
      if (r.ok && r.connected) { stopPoll(); U.tg.phase = 'done'; U.tg.err = ''; U.tg.tok = ''; toast('텔레그램 연결 완료 — 테스트 메시지를 보냈습니다'); await refreshStatus(); return; }
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
    if (an.save.length > MAX_BATCH) { toast('한 번에 최대 ' + MAX_BATCH + '개까지 — 나눠서 넣어 주세요', true); return; }
    if (an.needChain) { toast('EVM 체인을 하나 이상 고르세요', true); return; }
    U.busy.wadd = true; render();
    const r = await api('wallets/add_many', { addresses: an.save.map(x => x.t), chains: Array.from(U.chains) });
    U.busy.wadd = false;
    if (!r.ok) { toast(r.error || '추가 실패', true); render(); return; }
    const res = Array.isArray(r.results) ? r.results : [], failed = {};
    res.forEach(x => { if (x.status === 'invalid' || x.status === 'error') failed[x.input] = x.error || '저장 안 됨'; });
    const added = res.filter(x => x.status === 'added');
    const keep = an.items.filter(x => x.st === 'bad' || (failed[x.t] != null && x.st !== 'dup')).map(x => x.t);
    U.wErr = failed;
    U.wRes = { added: added.length, skipped: an.items.filter(x => x.st === 'have' || x.st === 'dup').length + res.filter(x => x.status === 'exists' || x.status === 'dup').length,
      left: keep.length, fails: an.items.filter(x => x.st === 'bad').map(x => ({ t: x.t, err: x.err })).concat(Object.keys(failed).map(t => ({ t, err: failed[t] }))) };
    if (keep.length) U.d.w_addr = keep.join('\n'); else delete U.d.w_addr;
    markNew(added.map(x => x.address));
    toast(added.length ? added.length + '개 추가됨 — 이름은 목록에서 붙여요' + (keep.length ? ' · ' + keep.length + '개는 칸에 남겼어요' : '') : '추가된 주소가 없어요' + (keep.length ? ' · ' + keep.length + '개는 칸에 남겼어요' : ''), !added.length);
    await refreshStatus();
    if (added.length) {
      const r0 = document.querySelector('#suWizard .su-row.new, #suPanel .su-row.new');
      if (r0) r0.scrollIntoView({ block: 'nearest' });
      if (window.__tj && window.__tj.refresh) window.__tj.refresh();
    }
  }
  const A = {
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
      toast('추가됨 · ' + label + ' — 수집기가 곧 최근 ' + U.st.backfillMonths + '개월 거래를 불러옵니다');
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
      if (!window.confirm('이 지갑을 추적 목록에서 뺄까요?\n' + a + '\n\n이미 기록된 거래는 원장에 남습니다(깨끗이 지우려면 README › 재백필).')) return;
      const r = await api('wallets/remove', { address: a });
      toast(r.ok ? '삭제했습니다' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
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
      toast('추가됨 · ' + label + ' (' + d.name + ') — 15초 안에 수집을 시작합니다');
      await refreshStatus();
    },
    async pdel(el) {
      const v = el.getAttribute('data-v') || '', i = v.indexOf('|'), dex = v.slice(0, i), a = v.slice(i + 1);
      const nm = (((U.st.perp || {}).dexes || []).find(x => x.key === dex) || {}).name || dex;
      if (!window.confirm(nm + ' 주소를 목록에서 뺄까요?\n' + a + '\n\n이 주소의 선물 포지션·정산이 화면과 매매일지 합계에서 바로 빠집니다.')) return;
      const r = await api('perp/remove', { dex, address: a });
      toast(r.ok ? '삭제했습니다' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
      if (r.ok && window.__tj && window.__tj.refresh) window.__tj.refresh();
    },
    chain(el) { const k = el.getAttribute('data-v'); if (U.chains.has(k)) U.chains.delete(k); else U.chains.add(k); render(); },
    chainAll() { (U.st.chains || []).forEach(c => U.chains.add(c.key)); render(); },
    chainNone() { U.chains.clear(); render(); },
    xp(el) { const k = el.getAttribute('data-v'); U.xp = (U.xp === k || (U.xp == null && k === 'helius')) ? '' : k; render(); },
    ex(el) { const k = el.getAttribute('data-v'); U.ex = U.ex === k ? null : k; render(); },
    async ktest(el) {
      const g = el.getAttribute('data-v');
      U.busy['t' + g] = true; render();
      const vals = groupVals(g), stored = Object.keys(vals).every(k => !vals[k]);
      const r = await api('keys/test', { group: g, values: vals });
      U.busy['t' + g] = false;
      U.test[g] = r.ok ? r.test : { ok: false, detail: r.error || '테스트 실패' };
      if (r.ok && r.test && r.test.permBlock) { U.perm = Object.assign({}, r.test.permBlock, { stored }); if (!stored) clearVals(g); }
      render();
    },
    async ksave(el) {
      const g = el.getAttribute('data-v'), grp = U.st.explorers[g] || U.st.exchanges[g], vals = groupVals(g);
      if (grp.fields.some(f => !vals[f.key])) { toast(grp.partial ? '바꾸려면 모든 칸을 새로 입력하세요' : '모든 칸을 채우세요', true); return; }
      if (needAck(g) && !U.ack[g]) { toast("'조회 권한만 켰음'을 먼저 체크하세요", true); return; }
      U.busy['s' + g] = true; render();
      const r = await api('keys/save', { group: g, values: vals, readOnlyAck: !!U.ack[g] });
      U.busy['s' + g] = false;
      if (!r.ok) {
        if (r.permBlock) { U.perm = Object.assign({}, r.permBlock, { stored: false }); clearVals(g); U.ack[g] = false; delete U.test[g]; }
        else if (r.needAck) { U.needAck[g] = r.reason || r.error || ''; U.ack[g] = false; toast(r.error || '조회 권한 확인이 필요합니다', true); }
        else toast(r.error || '저장 실패', true);
        render(); return;
      }
      clearVals(g); delete U.ack[g]; delete U.needAck[g]; toast(grp.name + ' 저장됨 · 값은 다시 표시되지 않습니다'); await refreshStatus();
    },
    async kdel(el) {
      const g = el.getAttribute('data-v'), grp = U.st.explorers[g] || U.st.exchanges[g];
      if (!window.confirm(grp.name + ' 키를 이 서버에서 지울까요?')) return;
      const r = await api('keys/delete', { group: g });
      delete U.test[g]; delete U.ack[g]; delete U.needAck[g]; toast(r.ok ? '삭제했습니다' : (r.error || '삭제 실패'), !r.ok); await refreshStatus();
    },
    kack(el) { const g = el.getAttribute('data-v'); U.ack[g] = !U.ack[g]; render(); },
    permClose() { const g = U.perm && U.perm.group; U.perm = null; render(); const b = g && $('[data-su="ex"][data-v="' + g + '"]'); if (b) b.focus(); },
    async dprefresh(el) {
      const k = el.getAttribute('data-v');
      const r = await api('depaddr/refresh', { exchange: k });
      if (!r.ok) { toast(r.error || '요청 실패', true); return; }
      U.dpWait[k] = Date.now();
      toast('입금주소 새로고침을 요청했습니다 — 수집기가 10초 안에 시작합니다');
      render(); dpPoll();
    },
    async ip() { const r = await api('public_ip', {}); if (r.ok) U.ip = r.ip; else toast(r.error || '조회 실패', true); render(); },
    copy(el) {
      const t = el.getAttribute('data-v') || '';
      const done = () => toast('복사했습니다');
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
      stopPoll(); U.tg.phase = 'done'; U.tg.tok = ''; delete U.d.tg_chat; delete U.d.tg_mtoken; toast('연결 완료 — 테스트 메시지를 보냈습니다'); await refreshStatus();
    },
    async tgtest() { const r = await api('telegram/test', {}); toast(r.ok ? '테스트 알림을 보냈습니다' : (r.error || '실패'), !r.ok); },
    async tgoff() {
      if (!window.confirm('텔레그램 알림 연결을 해제할까요? (봇 토큰·chat_id 를 이 서버에서 지웁니다)')) return;
      const r = await api('telegram/disconnect', {});
      U.tg.phase = 'idle'; toast(r.ok ? '연결을 해제했습니다' : (r.error || '실패'), !r.ok); await refreshStatus();
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
    goto(el) { U.step = +el.getAttribute('data-v'); render(); },
    prev() { U.step = Math.max(0, U.step - 1); render(); },
    next() { U.step = Math.min(STEPS.length - 1, U.step + 1); refreshStatus(); },
    ptoggle() { U.panelOpen = !U.panelOpen; SS.set('tj_su_open', U.panelOpen ? '1' : ''); render(); },
    async finish() { const r = await api('finish', {}); if (!r.ok) { toast(r.error || '저장 실패', true); return; } U.open = false; stopPollIfIdle(); toast('설정 완료 — 첫 수집이 끝나면 대시보드가 채워집니다'); await refreshStatus(); if (window.__tj) window.__tj.refresh(); },
    later() { SS.set('tj_setup_later', '1'); U.open = false; render(); },
    close() { SS.set('tj_setup_later', '1'); U.open = false; render(); },
    wizard() { U.open = true; U.step = 0; render(); },
    ptab(el) { U.where = el.getAttribute('data-v'); render(); }
  };
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
    if (!t || !(t.closest('#suWizard') || t.closest('#suPanel') || t.closest('#suPerm'))) return;
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
    if (ev.key === 'Escape' && U.open) { A.close(); return; }
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
    '.su-panel .su-sec{background:transparent;border:0;padding:4px 0 0;border-radius:0}',
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
    '.su-chiprow{display:flex;gap:6px;flex-wrap:wrap}',
    '.su-chip{padding:6px 11px;border-radius:99px;font-size:13px;font-weight:600;border:1px solid var(--line);background:var(--surface2);color:var(--text2)}',
    '.su-chip.on{background:var(--accentBg);color:var(--accent);border-color:transparent}',
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
    '.su-pagetop{padding-bottom:0}',
    '.su-panel .subtabs{margin-top:4px}',
    '.su-demo{position:relative;z-index:31;text-align:center;font-size:12.5px;font-weight:700;padding:5px 12px;background:var(--warnBg);color:var(--warn)}',
    '@media (max-width:640px){.su-perm{border-radius:0;min-height:100%;padding:18px 16px calc(24px + env(safe-area-inset-bottom));border-width:0 0 0 4px}.su-perm h3{font-size:19px}.su-bg{padding:0}.su-wiz{border-radius:0;min-height:100%;padding:16px 16px calc(24px + env(safe-area-inset-bottom));border:0}.su-step span{display:none}.su-step.on span{display:inline}.su-tgwait{flex-direction:column;align-items:center}.su-sec{padding:16px}.su-grow{min-width:0;flex-basis:100%}.su-form .field[style]{width:100%!important}.su-pagetop{padding-top:6px}.su-kbd{display:none}}'
  ].join('\n');
  document.head.appendChild(css);

  (async function init() {
    await load();
    if (!U.st) return;
    if (U.st.needsSetup && SS.get('tj_setup_later') !== '1') U.open = true;
    render();
  })();
  window.__tjSetup = { U, A, render, lock, qrEncode, toChecksum, checkAddr, keccak256, splitAddrs, wAnalyze, wSecret };
})();
