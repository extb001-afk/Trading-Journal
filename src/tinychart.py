from __future__ import annotations

import math
import struct
import zlib

_F = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "$": ["00100", "01111", "10100", "01110", "00101", "11110", "00100"],
    "₩": ["10001", "10001", "11111", "10101", "11111", "01010", "01010"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    " ": ["00000"] * 7,
    "억": ["0110001", "1001011", "1001001", "1001001", "0110001", "0000000", "1111111", "0000001", "0000001"],
    "만": ["1111010", "1001010", "1001011", "1111010", "0000010", "0000000", "1000000", "1000000", "1111111"],
}
_F["−"] = _F["-"]


def _hex(c):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


class _Img:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def blend(self, x, y, col, a):
        if a <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        a = min(1.0, a)
        i = (y * self.w + x) * 3
        p = self.px
        p[i] = int(p[i] + (col[0] - p[i]) * a)
        p[i + 1] = int(p[i + 1] + (col[1] - p[i + 1]) * a)
        p[i + 2] = int(p[i + 2] + (col[2] - p[i + 2]) * a)

    def hline(self, x0, x1, y, col, a=1.0):
        for x in range(max(0, int(x0)), min(self.w, int(x1) + 1)):
            self.blend(x, int(y), col, a)

    def disk(self, cx, cy, r, col, a=1.0):
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                self.blend(x, y, col, a * max(0.0, min(1.0, r - d + 0.5)))

    def line(self, x0, y0, x1, y1, col, width=3.0):
        r = width / 2
        minx, maxx = int(min(x0, x1) - r - 1), int(max(x0, x1) + r + 2)
        miny, maxy = int(min(y0, y1) - r - 1), int(max(y0, y1) + r + 2)
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy or 1e-9
        for y in range(max(0, miny), min(self.h, maxy)):
            for x in range(max(0, minx), min(self.w, maxx)):
                px, py = x + 0.5, y + 0.5
                t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
                d = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
                cov = r - d + 0.5
                if cov > 0:
                    i = (y * self.w + x) * 3
                    self.blend(x, y, col, min(1.0, cov))

    def text(self, x, y, s, col, scale=2, a=1.0):
        for ch in s:
            g = _F.get(ch)
            if g is None:
                continue
            gh, gw = len(g), len(g[0])
            oy = y + (7 - gh) * scale // 2 if gh < 7 else y - (gh - 7) * scale // 2
            for r, row in enumerate(g):
                for c, bit in enumerate(row):
                    if bit == "1":
                        for yy in range(scale):
                            for xx in range(scale):
                                self.blend(x + c * scale + xx, oy + r * scale + yy, col, a)
            x += (gw + 1) * scale
        return x

    def text_w(self, s, scale=2):
        return sum((len(_F[ch][0]) + 1) * scale for ch in s if ch in _F)

    def png(self) -> bytes:
        raw = bytearray()
        row = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw += self.px[y * row:(y + 1) * row]

        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def money_short(v, cur="KRW") -> str:
    a = abs(float(v))
    sg = "−" if v < 0 else ""
    if cur == "KRW":
        if a >= 1e8:
            return f"{sg}₩{a / 1e8:,.2f}억"
        if a >= 1e4:
            return f"{sg}₩{a / 1e4:,.0f}만"
        return f"{sg}₩{a:,.0f}"
    for div, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sg}${a / div:,.2f}{u}"
    return f"{sg}${a:,.0f}"


def flow_ret(first, last, flow_sum=0.0):
    try:
        f0, l0, s0 = float(first), float(last), float(flow_sum or 0.0)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(f0) and math.isfinite(l0) and math.isfinite(s0)) or f0 == 0:
        return None
    return (l0 - f0 - s0) / f0 * 100


def _split(vals, flows=None):
    pts = []
    fl_on = flows is not None
    for i, x in enumerate(vals or ()):
        fl = None
        if isinstance(x, (list, tuple)):
            fl_on = True
            fl = x[1] if len(x) > 1 else None
            x = x[0] if x else None
        elif flows is not None:
            fl = flows[i] if i < len(flows) else None
        try:
            fv = float(x)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(fv):
            continue
        try:
            fl = float(fl) if fl is not None and math.isfinite(float(fl)) else None
        except (TypeError, ValueError):
            fl = None
        pts.append((fv, fl))
    return [a for a, _b in pts], ([b for _a, b in pts] if fl_on else None)


def headline(vals, flows=None):
    v, fl = _split(vals, flows)
    if len(v) < 2:
        return {"day": 0.0, "period": 0.0, "rising": True, "net": False}
    if fl is None:
        day = (v[-1] / v[-2] - 1) * 100 if v[-2] else 0.0
        chg = (v[-1] / v[0] - 1) * 100 if v[0] else 0.0
        return {"day": day, "period": chg, "rising": v[-1] >= v[0], "net": False}
    d9 = flow_ret(v[-2], v[-1], fl[-1]) if fl[-1] is not None else None
    known = all(x is not None for x in fl[1:])
    p9 = flow_ret(v[0], v[-1], sum(fl[1:])) if known else None
    rising = (p9 >= 0) if p9 is not None else ((d9 >= 0) if d9 is not None else v[-1] >= v[0])
    return {"day": d9, "period": p9, "rising": rising, "net": True}


def render(vals, w=720, h=300, axis=True, cur="KRW", up=None, theme="dark", flows=None) -> bytes:
    v, fl = _split(vals, flows)
    hd = headline(list(zip(v, fl)) if fl is not None else v)
    if len(v) < 2:
        v = (v or [0.0]) * 2
    dark = theme != "light"
    bg = _hex("0E1621" if dark else "FFFFFF")
    grid = _hex("1F2B38" if dark else "E6E9EF")
    lab = _hex("8FA3B6" if dark else "6B7280")
    rising = hd["rising"] if up is None else bool(up)
    col = _hex("F25F5C" if rising else "4F8CFF")
    im = _Img(w, h, bg)
    padL, padR, padT, padB = 18, (150 if axis else 18), 44, 22
    lo, hi = min(v), max(v)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo -= span * 0.08
    hi += span * 0.08
    X = lambda i: padL + (w - padL - padR) * i / (len(v) - 1)
    Y = lambda x: padT + (h - padT - padB) * (1 - (x - lo) / (hi - lo))
    for k in range(4):
        gy = padT + (h - padT - padB) * k / 3
        im.hline(padL, w - padR, gy, grid, 1.0)
    pts = [(X(i), Y(x)) for i, x in enumerate(v)]
    base = h - padB
    for xi in range(int(padL), int(w - padR) + 1):
        t = (xi - padL) / max(1e-9, (w - padL - padR)) * (len(v) - 1)
        j = min(len(v) - 2, max(0, int(t)))
        f = t - j
        yv = pts[j][1] + (pts[j + 1][1] - pts[j][1]) * f
        for yy in range(int(yv), int(base)):
            a = 0.22 - 0.20 * (yy - yv) / max(1.0, base - yv)
            im.blend(xi, yy, col, a)
    for i in range(len(pts) - 1):
        im.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], col, 3.2)
    lx, ly = pts[-1]
    im.disk(lx, ly, 7.5, col, 0.25)
    im.disk(lx, ly, 4.5, col, 1.0)
    day = hd["day"]
    dcol = _hex("F25F5C" if day >= 0 else "4F8CFF") if day is not None else col
    im.line(pts[-2][0], pts[-2][1], pts[-1][0], pts[-1][1], dcol, 4.6)
    im.disk(lx, ly, 4.5, dcol, 1.0)
    chg = hd["period"]
    big = f"{'+' if day >= 0 else '−'}{abs(day):.1f}%" if day is not None else ""
    if big:
        im.text(padL, 12, big, dcol, 3)
    if len(v) > 2 and chg is not None:
        im.text(padL + (im.text_w(big, 3) + 12 if big else 0), 20 if big else 12, f"{len(v)}D {'+' if chg >= 0 else '−'}{abs(chg):.1f}%", lab, 2)
    if axis:
        tx = w - padR + 12
        clamp = lambda yy: int(max(padT - 6, min(h - padB - 14, yy - 7)))
        put = [(v[-1], clamp(ly), col)]
        for val in (max(v), min(v)):
            ty = clamp(Y(val))
            if all(abs(ty - p[1]) >= 18 for p in put):
                put.append((val, ty, lab))
        for val, ty, c in put:
            im.text(tx, ty, money_short(val, cur), c, 2)
    return im.png()


def png_size(b: bytes):
    if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", b[16:24])
