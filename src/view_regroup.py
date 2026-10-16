from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from view_common import DAILY_V
from view_common import STABLE_GROUPS
import logging
import calcguard

log = logging.getLogger('tj-web')


def _daily_krw(daily, today_key):
    for row9 in daily or ():
        u9 = row9.get("usdt")
        if row9.get("date") != today_key and isinstance(u9, (int, float)) and not isinstance(u9, bool) and u9 > 0 \
                and isinstance(row9.get("val"), (int, float)):
            row9["valKrw"] = round(float(row9["val"]) * float(u9))
    return daily


def _daily_reset(daily: dict, today_kst) -> dict:
    out = dict({"_v": DAILY_V}, **{k9: daily[k9] for k9 in ("_risk_rev", "_live", "_live_ok") if k9 in daily})
    y9 = (today_kst - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        ra9 = float(daily.get("_reset_at") or 0)
    except (TypeError, ValueError):
        ra9 = 0.0
    if ra9 and y9 not in daily and ra9 >= today_kst.replace(hour=0, minute=0, second=0, microsecond=0).timestamp():
        out["_reset_at"] = daily["_reset_at"]
    return out


def _stable_regroup_aliases(conn) -> dict:
    try:
        cur9 = {int(r[0]): int(r[1]) for r in conn.execute(
            "SELECT a.asset_id, a.group_id FROM assets a JOIN asset_groups g ON g.group_id=a.group_id"
            " WHERE a.kind='token' AND g.name IN (%s)" % ",".join("?" * len(STABLE_GROUPS)), sorted(STABLE_GROUPS))}
        if not cur9:
            return {}
        out = {}
        for gid9, name9 in conn.execute(
                "SELECT group_id, name FROM asset_groups WHERE name LIKE '%#%'"
                " AND group_id NOT IN (SELECT group_id FROM assets WHERE group_id IS NOT NULL)"):
            _h9, sep9, aid9 = str(name9).rpartition("#")
            if sep9 and aid9.isdigit() and int(aid9) in cur9 and cur9[int(aid9)] != int(gid9):
                out[str(gid9)] = str(cur9[int(aid9)])
        return out
    except Exception as e:
        calcguard.swallowed("view_regroup:_stable_regroup_aliases", e)
        log.warning("스테이블 재그룹 별칭 조회 실패: %s", e)
        return {}


def _relabel_daily_gids(daily, dpx, aliases) -> int:
    if not aliases:
        return 0
    snaps = [c for c in (daily or {}).values() if isinstance(c, dict)]
    snaps += [e.get("partial") for e in (dpx or {}).values() if isinstance(e, dict) and isinstance(e.get("partial"), dict)]
    n = 0
    for c in snaps:
        if isinstance(c.get("z"), list):
            z9 = sorted({str(aliases.get(str(k), str(k))) for k in c["z"]})
            if z9 != sorted(str(k) for k in c["z"]):
                c["z"] = z9
                n += 1
        g = c.get("g")
        if not isinstance(g, dict):
            continue
        for old, new in aliases.items():
            if old not in g:
                continue
            v = Decimal(str(g.pop(old)))
            g[new] = float(Decimal(str(g.get(new) or 0)) + v)
            n += 1
    return n
