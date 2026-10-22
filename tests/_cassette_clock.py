from __future__ import annotations

import datetime as _dt
import itertools
import os
import random
import time
import uuid

_REAL = time.time
_RDT = _dt.datetime
KST = _dt.timezone(_dt.timedelta(hours=9))
NOW = 1760000000.0
MONO_BASE = 1_000_000.0


class Clock:

    def __init__(self):
        self.now, self.tick, self.n = NOW, 0.0, 0
        self.off = None

    def t(self) -> float:
        if self.off is not None:
            return _REAL() + self.off
        return self.now + self.n * self.tick


CLOCK = Clock()
FROZEN = []
SHIFTED = []
MONO_OFF = [0.0]


class _FDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(CLOCK.t(), tz)

    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(CLOCK.t(), _dt.timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.fromtimestamp(CLOCK.t())


class _FD(_dt.date):
    @classmethod
    def today(cls):
        return cls.fromtimestamp(CLOCK.t())


class Fn:
    __slots__ = ("f",)

    def __init__(self, f):
        self.f = f

    def __call__(self, *a, **k):
        return self.f(*a, **k)


def uuid_n(n: int) -> uuid.UUID:
    return uuid.UUID("%08x-5eed-4eed-8eed-%012x" % (int(n), int(n)))


def _install_time() -> None:
    gm, lt, sf, ct, at = time.gmtime, time.localtime, time.strftime, time.ctime, time.asctime
    time.time = Fn(CLOCK.t)
    time.time_ns = Fn(lambda: int(CLOCK.t() * 1e9))
    time.gmtime = Fn(lambda secs=None: gm(CLOCK.t() if secs is None else secs))
    time.localtime = Fn(lambda secs=None: lt(CLOCK.t() if secs is None else secs))
    time.ctime = Fn(lambda secs=None: ct(CLOCK.t() if secs is None else secs))
    time.strftime = Fn(lambda fmt, t=None: sf(fmt, lt(CLOCK.t()) if t is None else t))
    time.asctime = Fn(lambda t=None: at(lt(CLOCK.t()) if t is None else t))
    _dt.datetime, _dt.date = _FDT, _FD


def shift(kst: str = "12:00:00", off: float | None = None) -> float:
    if FROZEN:
        raise RuntimeError("shift() 는 freeze() 와 같이 쓰지 않는다")
    if off is None:
        now = _REAL()
        hh, mm, ss = (int(x) for x in kst.split(":"))
        off = _RDT.fromtimestamp(now, KST).replace(hour=hh, minute=mm, second=ss, microsecond=0).timestamp() - now
    CLOCK.off = float(off)
    if not SHIFTED:
        SHIFTED.append(True)
        _install_time()
    return CLOCK.off


def freeze(now: float = NOW, tick: float = 0.0, seed: int = 1) -> Clock:
    if SHIFTED:
        raise RuntimeError("freeze() 는 shift() 와 같이 쓰지 않는다")
    CLOCK.now, CLOCK.tick, CLOCK.n = float(now), float(tick), 0
    if FROZEN:
        return CLOCK
    FROZEN.append(True)
    os.environ["TZ"] = "UTC"
    time.tzset()
    _install_time()
    mono_real = time.monotonic
    m0 = mono_real()
    time.monotonic = Fn(lambda: MONO_BASE + (mono_real() - m0) + MONO_OFF[0])
    time.monotonic_ns = Fn(lambda: int(time.monotonic() * 1e9))
    random.seed(seed)
    rng = random.Random(seed)
    os.urandom = Fn(lambda n: bytes(rng.getrandbits(8) for _ in range(int(n))))
    cnt = itertools.count(1)
    uuid.uuid4 = Fn(lambda: uuid_n(next(cnt)))
    return CLOCK
