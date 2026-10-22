from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

__all__ = ["to_float", "to_int", "to_dec"]

_FLOAT_ERRS = (TypeError, ValueError)
_FLOAT_ERRS_OVF = (TypeError, ValueError, OverflowError)
_DEC_ERRS = (InvalidOperation, ValueError, TypeError)


def to_float(v: object, default: float | None = None, *, allow_bool: bool = True, catch_overflow: bool = False) -> float | None:
    if not allow_bool and isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (_FLOAT_ERRS_OVF if catch_overflow else _FLOAT_ERRS):
        return default
    return x if math.isfinite(x) else default


def to_int(v: object, default: int | None = None) -> int | None:
    try:
        return int(v)
    except _FLOAT_ERRS:
        return default


def to_dec(v: object, default: Decimal | None = None) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except _DEC_ERRS:
        return default
    return d if d.is_finite() else default
