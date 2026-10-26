__all__ = ["log_word0", "LINK_KEEP", "strip_links", "like_escape"]


def log_word0(data) -> int:
    s = str(data)
    if s[:2] in ("0x", "0X"):
        s = s[2:]
    return int(s[:64], 16)


_LINK_RES = None
LINK_KEEP = frozenset((
    "gate.io", "crypto.com", "xt.com",
    "pump.fun", "letsbonk.fun", "bonk.fun", "four.meme", "bags.fm",
    "jup.ag", "li.fi", "gas.zip", "ether.fi", "friend.tech", "io.net",
    "gmgn.ai", "axiom.trade",
    "opensea.io", "magiceden.io", "blur.io",
))


def strip_links(text):
    global _LINK_RES  # noqa: PLW0603
    if not isinstance(text, str) or not text:
        return text
    if _LINK_RES is None:
        import re as _re9
        _LINK_RES = (
            _re9.compile(r"(?i)(?:https?|wss?|ftp|tg)://\S+"),
            _re9.compile(r"([A-Za-z0-9._%+-]+)@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}"),
            _re9.compile(r"(?<![A-Za-z0-9._%+@-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:[a-z]{2,24}|(?i:com|net|org|xyz|info)))"
                         r"(?![A-Za-z0-9-])([/?#]\S*|:\d+\S*)?"),
            _re9.compile(r"(?<![A-Za-z0-9_.@])@[A-Za-z][A-Za-z0-9_]+"),
            _re9.compile(r"\(\s*\)|\[\s*\]"),
            _re9.compile(r"[ \t]{2,}"),
            _re9.compile(r"\s+([.,;:!?)])(?!\d)"),
            _re9.compile(r"\d[\d.]*"),
        )
    url, mail, dom, handle, empty, spaces, before_p, num = _LINK_RES
    s = url.sub("", text)
    s = mail.sub(lambda m: m.group(1) if num.fullmatch(m.group(1)) else "", s)
    s = dom.sub(lambda m: m.group(0) if m.group(1).lower() in LINK_KEEP and not m.group(2) else "", s)
    s = handle.sub("", s)
    if s == text:
        return text
    s = empty.sub("", s)
    s = spaces.sub(" ", s)
    s = before_p.sub(r"\1", s)
    return s.strip()


def like_escape(s: object) -> str:
    return str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
