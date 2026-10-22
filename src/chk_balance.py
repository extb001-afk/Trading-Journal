from __future__ import annotations
import glob
import os
import re
import sqlite3
import time
import paths
import db as dbm
from chk_base import BAL_RB_LIVE_SEC
from chk_base import BAL_RB_WHY
from chk_base import BF_EXT_ORPHAN_SEC
from chk_base import CHAIN_NAME
from chk_base import EX_NAME
from chk_base import REST_LATE_MARGIN
from chk_base import REST_LATE_MAX
from chk_base import _read
from chk_base import _u
from chk_sources import fill_slow

def _disc_ents(disc, cfg) -> dict:
    try:
        import token_discovery as td9
        pairs9 = td9.load_state().get("pairs") or {}
        if cfg is not None:
            act9 = {td9.pair_key("bsc" if w.get("type") == "bsc_rpc" else w.get("chain"), w.get("address"))
                    for w in cfg.get("wallets") or [] if w.get("type", "evm") in ("evm", "bsc_rpc") and w.get("address")}
            pairs9 = {k: e for k, e in pairs9.items() if k in act9}
        ents9, nf9, nh9 = {}, 0, 0
        for k9, e9 in pairs9.items():
            if not isinstance(e9, dict):
                continue
            hard9 = list(td9.hard_fails(e9))
            if hard9:
                nf9 += 1
                ents9.update({f"fail:{k9}:{s9}": None for s9 in hard9})
            for ca9, why9 in (e9.get("skip") or {}).items():
                if not td9.skip_final(why9):
                    nh9 += 1
                    ents9[f"hold:{k9}:{ca9}"] = None
        if nf9 != int(disc.get("failPairs") or 0) or nh9 != int(disc.get("hold") or 0):
            return {}
        return ents9
    except Exception:   # noqa: BLE001 [fallback]
        return {}


def collect_balcheck(cfg: dict = None):
    p = paths.state("onchain_check.json")
    d = _read(p, None)
    if not isinstance(d, dict):
        return None
    mm = d.get("mismatches") or []
    conf = [m for m in mm if m.get("confirmed", True)]
    top = None
    if conf:
        m = max(conf, key=lambda x: abs(float(x.get("diffUsd") or 0)))
        top = f"{m.get('chain')} {m.get('sym')} 차이 ${abs(float(m.get('diffUsd') or 0)):,.0f}"
    items = [{"key": m.get("key"), "chain": m.get("chain"), "wallet": str(m.get("wallet") or ""), "sym": m.get("sym"), "ca": m.get("ca"),
              "diffUsd": float(m.get("diffUsd") or 0), "carried": bool(m.get("carried")),
              "ledger": m.get("ledger"), "onchain": m.get("onchain"),

              "carriedN": int(m.get("carriedN") or 0), "seenAt": m.get("seenAt"),
              "firstSeen": m.get("firstSeen")} for m in conf]
    fixed = [m for m in mm if m.get("ledgerFixed")]
    return {"checkedAt": d.get("checkedAt"), "confirmed": len(conf), "watch": len(mm) - len(conf) - len(fixed),
            "resolving": len(fixed),
            "errors": len(d.get("errors") or []), "top": top, "items": items,
            "unchecked": d.get("unchecked"), "capped": bool(d.get("capped")), "pairs": d.get("pairs"),
            "disc": (dict(d["disc"], ackEnts=_disc_ents(d["disc"], cfg)) if isinstance(d.get("disc"), dict) else None)}


def collect_bal_busy(now: float, extrb=None, bf=None) -> dict:
    out = {"global": [], "chains": {}, "wallets": {}}

    def addc(ch, why):
        lst = out["chains"].setdefault(str(ch), [])
        if why not in lst:
            lst.append(why)
    try:
        conn = dbm.connect(paths.sqlite_ro_uri(paths.DB_PATH), uri=True, timeout=2)
        try:
            rows = conn.execute("SELECT k, v FROM meta WHERE k LIKE 'ext_prewindow:%'").fetchall()
        finally:
            conn.close()
        for k, v in rows:
            try:
                if int(v) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            ch = str(k)[len("ext_prewindow:"):]
            if re.fullmatch(r"[a-z0-9]{2,20}", ch):
                addc(ch, "옛 기록을 반영하는 재계산 대기")
            else:
                if "재계산 대기" not in out["global"]:
                    out["global"].append("재계산 대기")
    except sqlite3.Error:
        out["unknown"] = True
    if isinstance(extrb, dict) and extrb.get("running"):
        out["global"].append("재계산 중")
    for unit, items in ((bf or {}).items() if isinstance(bf, dict) else ()):
        if not isinstance(items, dict) or str(unit).startswith("_"):
            continue
        for key, it in items.items():
            if not isinstance(it, dict) or not (str(key).endswith(":extend") or it.get("phase") == "extend") or it.get("phase") == "done":
                continue
            try:
                if now - float(it.get("updated") or 0) > 7 * 86400:
                    continue
            except (TypeError, ValueError):
                continue
            ch = {"bsc": "bsc", "sol": "sol", "ex": "upbit"}.get(unit) or (str(key).split(":", 1)[0] if unit == "evm" else None)
            if ch:
                addc(ch, "과거 기록 범위를 넓히는 중")
    cb = _read(paths.state("cursor_bsc.json"), None)
    nw = cb.get("_neww") if isinstance(cb, dict) else None
    if isinstance(nw, dict):
        for w in nw.get("wallets") or []:
            out["wallets"].setdefault(f"bsc|{str(w).lower()}", []).append("새 지갑 과거 기록 수집 중")
    bn = _read(paths.state("bsc_nonce.json"), None)
    for w, ws in ((bn.get("w") or {}).items() if isinstance(bn, dict) and isinstance(bn.get("w"), dict) else ()):
        try:
            miss = int((ws or {}).get("missing") or 0)
        except (TypeError, ValueError):
            continue
        if miss > 0:
            out["wallets"].setdefault(f"bsc|{str(w).lower()}", []).append(f"로그 없는 송금 {miss}건 회수 중")
    return out


def bal_busy_reasons(it: dict, bb: dict, sync_bad: dict) -> list:
    ch = str(it.get("chain") or "")
    w = str(it.get("wallet") or "")
    w = w if ch == "sol" else w.lower()
    out = []
    for x in list((bb or {}).get("global") or []) + list(((bb or {}).get("chains") or {}).get(ch) or []) \
            + list(((bb or {}).get("wallets") or {}).get(f"{ch}|{w}") or []):
        if x not in out:
            out.append(x)
    if ch in (sync_bad or {}):
        out.append(sync_bad[ch])
    if it.get("carried"):
        out.append("이번 판에 다시 대조하지 못함(다음 판에 이어서)")
    return out


def bal_rb_wait(why) -> bool:
    return any(w in BAL_RB_WHY for w in (why or ()))


def _fmt_left(sec) -> str:
    sec = max(0, int(sec))
    if sec < 3600:
        return f"{max(1, sec // 60)}분"
    if sec < 86400:
        h, m = divmod(sec // 60, 60)
        return f"{h}시간" + (f" {m}분" if m and h < 10 else "")
    d, h = divmod(sec // 3600, 24)
    return f"{d}일" + (f" {h}시간" if h else "")


def _bf_ext_pending(bf) -> list:
    def path9(key):
        ch9, _, rest9 = str(key).partition(":")
        return (ch9.lower(), rest9 if rest9 in ("extend", "job", "rpc") else None)
    out = []
    for unit, items in ((bf or {}).items() if isinstance(bf, dict) else ()):
        if not isinstance(items, dict) or str(unit).startswith("_"):
            continue
        last = {}
        for key, it in items.items():
            ch9, p9 = path9(key)
            if p9 and isinstance(it, dict):
                try:
                    u9 = float(it.get("updated") or 0)
                except (TypeError, ValueError):
                    u9 = 0.0
                last[(ch9, p9)] = max(last.get((ch9, p9), 0.0), u9)
        for key, it in items.items():
            if not isinstance(it, dict) or not (str(key).endswith(":extend") or it.get("phase") == "extend") or it.get("phase") == "done":
                continue
            ch9, p9 = path9(key)
            if p9 and max(last.get((ch9, q9), -1.0) for q9 in ("extend", "job", "rpc")) > last.get((ch9, p9), 0.0):
                continue
            out.append((unit, key, it))
    return out


def bf_ext_phrase(bf, now: float) -> str:
    acc = {}
    for unit, key, it in _bf_ext_pending(bf):
        try:
            if now - float(it.get("updated") or 0) >= 3 * 3600:
                continue
            dn, tt, eta = float(it.get("done") or 0), float(it.get("total") or 0), float(it.get("eta_sec") or 0)
        except (TypeError, ValueError):
            continue
        ch = {"bsc": "bsc", "sol": "sol", "ex": "upbit"}.get(unit) or str(key).split(":", 1)[0]
        a = acc.setdefault(ch, [0.0, 0.0, 0.0])
        a[0] += max(0.0, dn)
        a[1] += max(0.0, tt)
        a[2] = max(a[2], eta)
    out = []
    for ch, (dn, tt, eta) in sorted(acc.items(), key=lambda kv: (-kv[1][2], kv[0])):
        bits = ([f"지금 {min(99, int(dn * 100 / tt))}%"] if tt > 0 else []) + ([f"약 {_fmt_left(eta)} 남음"] if eta > 0 else [])
        out.append(f"{CHAIN_NAME.get(ch) or EX_NAME.get(ch) or ch} 과거 기록 넓히기" + (f"({' · '.join(bits)})" if bits else ""))
    return " · ".join(out[:2]) + (f" 외 {len(out) - 2}개" if len(out) > 2 else "")


def bf_ext_live(obs: dict, now: float, stall_sec: float = 3600) -> bool:
    for unit, key, it in _bf_ext_pending((obs or {}).get("bf")):
        try:
            upd = float(it.get("updated") or 0)
            moved = float(it.get("moved_at") or it.get("started") or upd or 0)
        except (TypeError, ValueError):
            continue
        if now - upd < BAL_RB_LIVE_SEC and (now - moved <= float(stall_sec or 3600) or fill_slow(obs, unit, key, it, now)):
            return True
    return False


def bf_ext_open(obs: dict, chain=None) -> bool:
    pre = (str(chain).lower() + ":") if chain else ""
    now = float((obs or {}).get("now") or time.time())
    for _u, key, it in _bf_ext_pending((obs or {}).get("bf")):
        if pre and not str(key).lower().startswith(pre):
            continue
        try:
            if now - float(it.get("updated") or 0) >= BF_EXT_ORPHAN_SEC:
                continue
        except (TypeError, ValueError):
            continue
        return True
    return False


def rb_wait_sentence(bf, now: float) -> str:
    ph = bf_ext_phrase(bf, now)
    return (f"{ph}가 끝나면 원장 자동 재계산으로 사라져요 — 기다리면 됨" if ph
            else "원장 자동 재계산이 끝나면 사라져요 — 기다리면 됨")


def _fq(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "?"
    s9 = f"{v:,.2f}" if abs(v) >= 1000 else f"{v:,.6g}"
    return s9.replace("-", "−")


def bal_guess(it: dict) -> str:
    try:
        lq, oq = float(it.get("ledger")), float(it.get("onchain"))
    except (TypeError, ValueError):
        return ""
    if abs(lq) < 1e-12 and oq > 0:
        return "장부에 이 코인이 아예 없어요 — 들어온 기록을 못 받은 듯해요"
    if abs(oq) < 1e-12 and lq > 0:
        return "실제로는 다 빠져나갔어요 — 장부에 없는 출금이 있는 듯해요"
    if oq > lq:
        return "실제가 더 많아요 — 장부에 없는 입금(로그 없는 입금·내부 이동 등)이 있는 듯해요"
    if lq > oq:
        return "장부가 더 많아요 — 장부에 없는 출금·수수료(로그 없는 송금 등)가 있는 듯해요"
    return ""


def bal_line(it: dict) -> str:
    ch = it.get("chain")
    d9 = f"(차이 ${abs(float(it.get('diffUsd') or 0)):,.0f})"
    qty9 = it.get("ledger") is not None and it.get("onchain") is not None
    if ch == "upbit":
        return f"업비트 {it.get('sym')} — " + (f"장부 {_fq(it.get('ledger'))} · 업비트 잔고 {_fq(it.get('onchain'))} {d9}" if qty9 else d9)
    return (f"{CHAIN_NAME.get(ch, ch)} 지갑 {_short_addr(it.get('wallet'))} 의 {it.get('sym')} — "
            + (f"장부 {_fq(it.get('ledger'))} · 실제 {_fq(it.get('onchain'))} {d9}" if qty9 else d9))


def bal_text(items: list, more: bool = False) -> str:
    items = sorted(items or [], key=lambda x: -abs(float(x.get("diffUsd") or 0)))
    n = len(items)
    lines = [f"🔴 잔고가 장부와 하루 넘게 다른 곳이 {n}곳 더 생겼어요" if more else f"🔴 잔고가 장부와 하루 넘게 달라요 · {n}곳"]
    stuck = sorted({w9 for x in items for w9 in (x.get("stuck") or [])})
    if stuck:
        lines.append("할 일: 기다리기 — " + " · ".join(stuck[:3]) + "이(가) 3일 넘게 안 끝났어요. 상태 패널에서 진행을 확인하세요.")
        rbw9 = next((str(x["rbw"]) for x in items if x.get("rbw")), "")
        if rbw9:
            lines.append(f"  {rbw9}")
    else:
        lines.append("할 일: 앱 › 잔고 맞추기에서 이 지갑·코인을 열어 빠진 입출금이 있는지 보세요(장부는 자동으로 고치지 않아요) — 수집·재계산은 다 끝났어요.")
    for it in items[:5]:
        lines.append(bal_line(it))
        g9 = bal_guess(it)
        if g9:
            lines.append(f"  짐작: {g9}")
    if n > 5:
        lines.append(f"… 외 {n - 5}곳(앱 › 잔고 맞추기)")
    return "\n".join(lines)


def _short_addr(a: str) -> str:
    a = str(a or "")
    return a[:6] + "…" + a[-4:] if len(a) > 14 else a


def tier_rest_map() -> dict:
    out = {}
    for f in glob.glob(paths.state("addr_tier_*.json")):
        if os.path.basename(f) == "addr_tier_req.json":
            continue
        d = _read(f, None)
        if not isinstance(d, dict) or not isinstance(d.get("pairs"), dict) or not d.get("scope"):
            continue
        sc = str(d["scope"])
        for w, p in d["pairs"].items():
            if isinstance(p, dict) and (int(p.get("tier") or 0) > 0 or p.get("rest") is True) and not p.get("hold"):
                out.setdefault(sc, {})[w if sc == "sol" else str(w).lower()] = int(p.get("full") or 0)
    return out


def rest_late(it: dict, rest: dict, now: float = None) -> bool:
    now = time.time() if now is None else now
    ch = it.get("chain")
    w = it.get("wallet") or ""
    w = w if ch == "sol" else str(w).lower()
    full = (rest.get(ch) or {}).get(w)
    if full is None:
        return False
    try:
        fs = float(it["firstSeen"])
    except (KeyError, TypeError, ValueError):
        return False
    return full < fs + REST_LATE_MARGIN and 0 <= now - fs < REST_LATE_MAX


def balcheck_split(bc: dict, sources) -> tuple:
    pw, pnw, bfw = {}, {}, {}
    for s9 in sources or []:
        k9 = str(s9.get("key") or "")
        if k9.startswith("chain:") and s9.get("backfill_wallets"):
            bfw[k9[6:]] = [str(x).lower() for x in s9["backfill_wallets"]]
        if s9.get("partial") and k9.startswith("chain:"):
            pw[k9[6:]] = [str(x).lower() for x in (s9.get("partial_wallets") or [])]
            pnw[k9[6:]] = [str(x).lower() for x in (s9.get("partial_native_wallets") or [])]
    now9, late9 = [], []
    try:
        rest9 = tier_rest_map()
    except Exception:   # noqa: BLE001 [fallback]
        rest9 = {}
    for it in bc.get("items") or []:
        ch, w = it.get("chain"), str(it.get("wallet") or "").lower()
        if rest9 and rest_late(it, rest9):
            late9.append(it)
        elif ch in pw and w and any(p9 and w.startswith(p9) for p9 in pw[ch]):
            late9.append(it)
        elif ch in bfw and w and any(p9 and w.startswith(p9) for p9 in bfw[ch]):
            late9.append(it)
        elif ch in pnw and w and not it.get("ca") and any(p9 and w.startswith(p9) for p9 in pnw[ch]):
            late9.append(it)
        else:
            now9.append(it)
    return now9, late9
