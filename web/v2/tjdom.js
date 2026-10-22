(function () {
  'use strict';
  if (typeof TJDOM === 'object' && TJDOM !== null && Object.isFrozen(TJDOM)) return;

  const MODE = 'enforce';
  const STYLE = true;
  const HTML_NS = 'http://www.w3.org/1999/xhtml', SVG_NS = 'http://www.w3.org/2000/svg', XMLNS_NS = 'http://www.w3.org/2000/xmlns/';
  const words = s => new Set(s.split(/\s+/).filter(Boolean));

  const EL_HTML = words('a article aside b br button code col colgroup dd details div dl dt h1 h2 h3 h4 i img input kbd label li mark nav'
    + ' ol p s section small span summary table tbody td textarea tfoot th thead title tr u ul wbr');
  const EL_SVG = words('circle defs ellipse g line lineargradient path polyline rect stop svg text title');
  const AT = words('alt autocapitalize autocomplete class colspan cx cy d decoding enterkeyhint fill fill-opacity font-family font-size'
    + ' font-weight for height href id inputmode letter-spacing loading maxlength offset placeholder points preserveaspectratio r rel role'
    + ' rows rx ry scope shape-rendering spellcheck stroke stroke-dasharray stroke-dashoffset stroke-linecap stroke-linejoin stroke-opacity'
    + ' stroke-width style tabindex target text-anchor title transform type value vector-effect viewbox width x x1 x2 xmlns y y1 y2'
    + ' autofocus disabled hidden open');
  const ST = words('align-items background border border-bottom border-color border-radius border-top color cursor display fill flex'
    + ' flex-direction flex-wrap font-family font-size font-weight gap grid-column grid-row height justify-content justify-self left'
    + ' line-height margin margin-bottom margin-left margin-top max-height max-width min-height min-width opacity overflow overflow-wrap'
    + ' overflow-x padding padding-top place-items position stop-color stop-opacity stroke text-align top transform white-space width'
    + ' word-break');
  const CP_EL_HTML = words('abbr bdi bdo blockquote caption cite data del dfn em figcaption figure footer h5 h6 header hgroup hr ins main'
    + ' meter optgroup option output pre progress q rp rt ruby samp select strong sub sup time var');
  const CP_EL_SVG = words('desc polygon radialgradient tspan');
  const CP_AT = words('abbr align checked cols datetime dir headers label lang max min minlength multiple readonly required reversed'
    + ' rowspan selected size span src start step translate valign wrap'
    + ' alignment-baseline baseline-shift clip-rule display dominant-baseline dx dy font-style fr fx fy fill-rule gradienttransform'
    + ' gradientunits lengthadjust opacity overflow paint-order pathlength rotate spreadmethod stop-color stop-opacity'
    + ' stroke-miterlimit text-decoration textlength visibility');
  const CP_ST = words('align-content align-self background-color border-left border-right border-style border-width bottom box-shadow'
    + ' box-sizing column-gap flex-basis flex-grow flex-shrink font-style font-variant-numeric grid-template-columns'
    + ' letter-spacing list-style margin-right order outline overflow-y padding-bottom padding-left padding-right right row-gap'
    + ' text-decoration text-overflow text-transform vertical-align visibility word-spacing');
  const FORBID_EL = words('script style link meta base iframe frame frameset object embed applet param form math foreignobject template'
    + ' noscript noembed noframes xmp plaintext portal fencedframe animate set animatemotion animatetransform animatecolor mpath discard'
    + ' use image feimage handler listener');
  const FORBID_AT = words('srcdoc formaction action xlink:href ping attributename values from to by begin end');
  const URL_AT = words('href src poster background cite data srcset lowsrc dynsrc longdesc usemap manifest codebase archive icon profile');

  const LOG = new Map();
  const NOTE = { must: 0, compat: 0, drop: 0 };
  let policyErr = '';
  function rec(kind, key) {
    NOTE[kind]++;
    const k = kind + ' ' + key;
    if (LOG.has(k) || LOG.size < 500) LOG.set(k, (LOG.get(k) || 0) + 1);
  }

  const esc = v => String(v == null ? '' : v)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const NAMED = { colon: ':', tab: '\t', newline: '\n', sol: '/', period: '.', num: '#', quest: '?' };
  function deRef(s) {
    return s.replace(/&(?:#(\d+)|#[xX]([0-9a-fA-F]+)|([A-Za-z]+));?/g, (m, d, x, n) => {
      if (d || x) { const c = parseInt(d || x, d ? 10 : 16); return c > 0 && c < 0x110000 ? String.fromCodePoint(c) : ''; }
      const t = NAMED[n.toLowerCase()];
      return t === undefined ? m : t;
    });
  }
  function scheme(s) {
    const t = s.replace(/^[\u0000- ]+|[\u0000- ]+$/g, '').replace(/[\t\n\r]/g, '');
    const m = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(t);
    return { t, s: m ? m[1].toLowerCase() : '' };
  }
  function urlOk1(s, img) {
    const u = scheme(s);
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(u.t)) return false;
    if (!u.s) return true;
    if (u.s === 'http' || u.s === 'https' || u.s === 'mailto' || u.s === 'tel') return true;
    if (u.s === 'blob') return u.t.slice(5, 6 + location.origin.length) === location.origin + '/';
    if (u.s === 'data') return !!img && /^data:image\/(png|jpeg|gif|webp)[;,]/i.test(u.t);
    return false;
  }
  const urlOk = (v, img) => { const s = String(v); return urlOk1(s, img) && urlOk1(deRef(s), img); };
  function safeUrl(u, kind) {
    if (u == null) return '';
    return urlOk(u, kind === 'img') ? String(u) : '#';
  }

  const ST_BAD = new RegExp('url\\(|image\\(|image-set\\(|cross-fade\\(|element\\(|paint\\(|expression\\(|@|\\\\|/\\*|<|javascript:'
    + '|[\\u0000-\\u0008\\u000b\\u000e-\\u001f\\u007f]', 'i');
  function decls(s, bad) {
    const out = [], nl = c => c === '\n' || c === '\r' || c === '\f';
    let q = '', d = 0, b = 0, x = false;
    const cut = j => { const t = s.slice(b, j); if (t.trim()) { if (x && bad) bad.add(out.length); out.push(t); } b = j + 1; x = false; };
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (c === '\\') { if (q || !nl(s[i + 1])) i += s.startsWith('\r\n', i + 1) ? 2 : 1; }
      else if (q) { if (c === q) q = ''; else if (nl(c)) { q = ''; x = true; } }
      else if (c === '"' || c === "'") q = c; else if (c === '(') d++; else if (c === ')') d--;
      else if (c === ';' && d <= 0) cut(i);
    }
    cut(s.length);
    return out;
  }
  function declBad(name, val) {
    if (ST_BAD.test(name) || ST_BAD.test(val) || name === 'behavior' || name === '-moz-binding') return true;
    const v = val.trim().toLowerCase();
    if (name === 'position') return !/^(relative|absolute|sticky|static)$/.test(v);
    if (name === 'z-index') return !/^(auto|-?[0-9])$/.test(v);
    return false;
  }
  function styleKeep(s, tag, names) {
    const keep = [];
    let changed = false;
    const bad = new Set();
    for (const [i, d0] of decls(s, bad).entries()) {
      const k = d0.indexOf(':');
      const name = (k < 0 ? d0 : d0.slice(0, k)).trim().toLowerCase(), val = k < 0 ? '' : d0.slice(k + 1);
      if (bad.has(i) || declBad(name, val)) { rec('must', 'style:' + tag + ':' + (k < 0 ? '?' : name)); changed = true; continue; }
      if (names && k >= 0 && !ST.has(name) && !/^--[a-z0-9-]+$/.test(name)) {
        rec(CP_ST.has(name) ? 'compat' : 'drop', 'style:' + tag + ':' + name);
        if (MODE === 'enforce' || !CP_ST.has(name)) { changed = true; continue; }
      }
      keep.push(d0);
    }
    return { text: changed ? keep.join(';') : s, changed };
  }

  const SVG_FN = words('rgb rgba hsl hsla var calc min max clamp translate translatex translatey rotate scale scalex scaley matrix'
    + ' skewx skewy');
  const PAINT = /^\s*(#[0-9a-f]{3,8}|[a-z]+|(rgba?|hsla?)\([^()]*\)|var\(--[a-z0-9-]+\)|url\(#[a-z_][\w.-]*\))\s*$/i;
  function svgValBad(name, v) {
    if (/[\\\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]|javascript:|expression\(/i.test(v)) return true;
    const fns = v.toLowerCase().match(/[a-z-]+(?=\s*\()/g) || [];
    for (const f of fns) {
      if (f === 'url') { if (!((name === 'fill' || name === 'stroke') && /^\s*url\(#[a-z_][\w.-]*\)\s*$/i.test(v))) return true; }
      else if (!SVG_FN.has(f)) return true;
    }
    return false;
  }

  function elKind(el) {
    const ns = el.namespaceURI, n = el.localName.toLowerCase();
    if (ns !== HTML_NS && ns !== SVG_NS) return 'must';
    if (FORBID_EL.has(n) || el.hasAttribute('is')) return 'must';
    if (n.indexOf('-') >= 0) return 'drop';
    const ok = ns === SVG_NS ? EL_SVG : EL_HTML, cp = ns === SVG_NS ? CP_EL_SVG : CP_EL_HTML;
    return ok.has(n) ? 'ok' : cp.has(n) ? 'compat' : 'drop';
  }
  function attrKind(el, a, tag) {
    const nm = a.name.toLowerCase(), ns = a.namespaceURI, svg = el.namespaceURI === SVG_NS, v = a.value;
    if (/^on/.test(nm) || FORBID_AT.has(nm)) return 'must';
    if (ns !== null) return ns === XMLNS_NS && nm === 'xmlns' && svg && v === SVG_NS ? 'ok' : 'must';
    if (nm === 'is') return 'must';
    if (URL_AT.has(nm) && !urlOk(v, tag === 'img' && nm === 'src')) return 'must';
    if (svg && !/^(class|id|role|tabindex|data-.*|aria-.*)$/.test(nm) && svgValBad(nm, v)) return 'must';
    if (AT.has(nm) || /^(data|aria)-[a-z0-9_.-]+$/.test(nm)) {
      if (svg && (nm === 'fill' || nm === 'stroke') && !PAINT.test(v)) return 'compat';
      return 'ok';
    }
    return CP_AT.has(nm) ? 'compat' : 'drop';
  }
  function cleanAttrs(el) {
    const tag = (el.namespaceURI === SVG_NS ? 'svg:' : '') + el.localName.toLowerCase();
    for (const a of Array.from(el.attributes)) {
      const nm = a.name.toLowerCase();
      if (nm === 'style' || (STYLE && nm === 'data-tjst')) {
        const left = STYLE && nm === 'style';
        if (left) {
          rec('compat', 'attr:' + tag + ':style');
          if (MODE === 'enforce') { el.removeAttributeNode(a); continue; }
        }
        const r = styleKeep(a.value, tag, STYLE && !left);
        if (r.changed) { if (r.text.trim()) a.value = r.text; else el.removeAttributeNode(a); }
        continue;
      }
      const k = attrKind(el, a, tag);
      if (k === 'ok') continue;
      rec(k, 'attr:' + tag + ':' + nm);
      if (k !== 'compat' || MODE === 'enforce') el.removeAttributeNode(a);
    }
  }
  function clean(root) {
    const st = [root];
    while (st.length) {
      const p = st.pop();
      for (let n = p.firstChild, nx; n; n = nx) {
        nx = n.nextSibling;
        if (n.nodeType === 1) {
          const k = elKind(n);
          if (k !== 'ok') rec(k, 'el:' + (n.namespaceURI === SVG_NS ? 'svg:' : n.namespaceURI === HTML_NS ? '' : 'ns:') + n.localName);
          if (k === 'ok' || (k === 'compat' && MODE !== 'enforce')) { cleanAttrs(n); st.push(n); } else n.remove();
        } else if (n.nodeType !== 3 && n.nodeType !== 8) n.remove();
      }
    }
  }

  const RAW = words('textarea title script style xmp iframe noembed noframes noscript');
  function tjst(s) {
    const n = s.length, low = s.toLowerCase();
    let out = '', i = 0, svg = 0;
    while (i < n) {
      const lt = s.indexOf('<', i);
      if (lt < 0) { out += s.slice(i); break; }
      out += s.slice(i, lt);
      i = lt;
      let e = -1;
      if (s.startsWith('<!--', i)) e = (k => k < 0 ? n : k + 3)(s.indexOf('-->', i + 4));
      else if (svg && s.startsWith('<![CDATA[', i)) e = (k => k < 0 ? n : k + 3)(s.indexOf(']]>', i + 9));
      else if (s[i + 1] === '!' || s[i + 1] === '?') e = (k => k < 0 ? n : k + 1)(s.indexOf('>', i));
      if (e >= 0) { out += s.slice(i, e); i = e; continue; }
      const close = s[i + 1] === '/';
      if (!/[A-Za-z]/.test(s[i + (close ? 2 : 1)] || '')) { out += '<'; i++; continue; }
      let j = i + (close ? 2 : 1);
      while (j < n && !/[\s/>]/.test(s[j])) j++;
      const name = low.slice(i + (close ? 2 : 1), j);
      out += s.slice(i, j);
      i = j;
      for (;;) {
        while (i < n && /[\s/]/.test(s[i])) out += s[i++];
        if (i >= n) break;
        if (s[i] === '>') { out += '>'; i++; break; }
        let k = i + (s[i] === '=' ? 1 : 0);
        while (k < n && !/[\s/>=]/.test(s[k])) k++;
        let m = k;
        while (m < n && /\s/.test(s[m])) m++;
        if (s[m] !== '=') { out += s.slice(i, k); i = k; continue; }
        m++;
        while (m < n && /\s/.test(s[m])) m++;
        let ve = m;
        if (s[m] === '"' || s[m] === "'") { const q = s.indexOf(s[m], m + 1); ve = q < 0 ? n : q + 1; }
        else while (ve < n && !/[\s>]/.test(s[ve])) ve++;
        const ren = !close && s[m] === '"' && low.slice(i, k) === 'style';
        out += (ren ? 'data-tjst' : s.slice(i, k)) + s.slice(k, ve);
        i = ve;
      }
      if (name === 'svg') svg = Math.max(0, svg + (close ? -1 : 1));
      if (!close && !svg && RAW.has(name)) {
        const k = low.indexOf('</' + name, i);
        const z = k < 0 ? n : k;
        out += s.slice(i, z);
        i = z;
      }
    }
    return out;
  }
  function applyStyle(frag) {
    for (const el of Array.from(frag.querySelectorAll('[data-tjst]'))) {
      const v = el.getAttribute('data-tjst');
      el.removeAttribute('data-tjst');
      if (el.style) el.style.cssText = v;
    }
  }

  const INERT = document.implementation.createHTMLDocument('');
  const TT = window.trustedTypes;
  let POLICY = null;
  try {
    POLICY = TT ? TT.createPolicy('tj-html', { createHTML: s => s }) : null;
  } catch (e) {
    policyErr = String(e && e.name || e);
  }
  function ctxFor(node, adj) {
    if (node.nodeType !== 1 || (adj && node.localName === 'html' && node.namespaceURI === HTML_NS)) return INERT.createElement('body');
    return INERT.createElementNS(node.namespaceURI, node.localName);
  }
  function frag(node, html, adj) {
    const s = STYLE ? tjst(html) : html;
    const ctx = ctxFor(node, adj);
    ctx.innerHTML = POLICY ? POLICY.createHTML(s) : s;
    clean(ctx);
    const f = document.createDocumentFragment();
    for (const n of Array.from(ctx.childNodes)) f.appendChild(document.importNode(n, true));
    if (STYLE) applyStyle(f);
    return f;
  }
  const str = v => v === null ? '' : String(v);
  function need(el) {
    if (!el || el.nodeType !== 1) throw new TypeError('TJDOM: 대상이 요소가 아님');
  }

  function set(el, html) {
    need(el);
    const s = str(html);
    if (s === '') { el.replaceChildren(); return; }
    el.replaceChildren(frag(el, s));
  }
  function clear(el) {
    need(el);
    el.replaceChildren();
  }
  function insert(el, pos, html) {
    need(el);
    const p = String(pos).toLowerCase(), s = str(html);
    if (p === 'beforebegin' || p === 'afterend') {
      const par = el.parentNode;
      if (!par || par.nodeType === 9) throw new DOMException('TJDOM: 부모 없는 요소의 바깥에 넣을 수 없음', 'NoModificationAllowedError');
      const f = frag(par, s, true);
      if (p === 'beforebegin') el.before(f); else el.after(f);
    } else if (p === 'afterbegin' || p === 'beforeend') {
      const f = frag(el, s, true);
      if (p === 'afterbegin') el.prepend(f); else el.append(f);
    } else throw new DOMException('TJDOM: 자리 이름이 틀림 ' + p, 'SyntaxError');
  }
  function replace(el, html) {
    need(el);
    const s = str(html), par = el.parentNode;
    if (!par) return;
    if (par.nodeType === 9) throw new DOMException('TJDOM: 문서의 바로 아래 요소는 바꿀 수 없음', 'NoModificationAllowedError');
    el.replaceWith(frag(par, s, true));
  }
  function report() {
    return Object.freeze({
      mode: MODE, style: STYLE, policy: !!POLICY, policyErr, must: NOTE.must, compat: NOTE.compat, drop: NOTE.drop,
      items: Object.freeze(Array.from(LOG, ([k, n]) => Object.freeze([k.slice(0, k.indexOf(' ')), k.slice(k.indexOf(' ') + 1), n]))),
    });
  }

  window.TJDOM = Object.freeze({ set, insert, replace, clear, esc, safeUrl, report });
})();
