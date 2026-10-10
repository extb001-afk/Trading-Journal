#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
import common
import db as dbm
import ledger_backup as lb

STREAMS = ("evm", "sol", "bsc", "ex")
MARGIN_H = 12
PRE_RESTORE_KEEP = 2
UNIT_SCRIPTS = ("core.py", "unit_runner.py", "evm_watch.py", "sol_watch.py", "bsc_watch.py", "upbit_link.py", "ex_foreign.py", "web.py")
STOP_HINT = "pm2 stop tj-core tj-evm tj-sol tj-bsc tj-ex tj-exf tj-web"
START_HINT = "pm2 start tj-core  →  (몇 분 뒤) pm2 start tj-evm tj-sol tj-bsc tj-ex tj-exf tj-web"
BSC_BLOCK_S = 0.45
SEEN_NOTIME = "#notime"
SIG_RX = re.compile(r"[1-9A-HJ-NP-Za-km-z]{64,90}")


def _kst(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(ts) + 9 * 3600)) + " KST"
    except (TypeError, ValueError):
        return "?"


def _gb(n) -> str:
    return f"{(n or 0) / 1024 ** 3:.2f}GB"


def _ro(path: str) -> sqlite3.Connection:
    imm = not os.path.exists(path + "-wal")
    c = sqlite3.connect(common.sqlite_ro_uri(path, immutable=imm), uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def backups(state_dir: str = None) -> list:
    sd = state_dir or common.STATE_DIR
    out = []
    bdir = os.path.join(sd, "backups")
    try:
        for n in os.listdir(bdir):
            if re.match(r"^ledger_\d{8}\.db$", n):
                out.append(os.path.join(bdir, n))
    except OSError:
        pass
    base = os.path.basename(common.DB_PATH)
    try:
        for n in os.listdir(sd):
            if n.startswith(base + ".pre_") and not n.endswith(("-wal", "-shm")):
                out.append(os.path.join(sd, n))
    except OSError:
        pass
    rows = []
    for p in out:
        try:
            st = os.stat(p)
        except OSError:
            continue
        rows.append({"path": p, "name": os.path.relpath(p, sd), "size": st.st_size, "mtime": int(st.st_mtime)})
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def resolve(arg: str, state_dir: str = None) -> str:
    sd = state_dir or common.STATE_DIR
    rows = backups(sd)
    if arg.isdigit() and 1 <= int(arg) <= len(rows):
        return rows[int(arg) - 1]["path"]
    for cand in (arg, os.path.join(sd, arg), os.path.join(sd, "backups", arg)):
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    raise SystemExit(f"백업을 찾지 못했어요: {arg} — python3 tools/ledger_restore.py list 의 번호나 파일 이름")


def inspect(path: str) -> dict:
    c = _ro(path)
    try:
        has = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        meta = {r["k"]: r["v"] for r in c.execute("SELECT k, v FROM meta WHERE k IN ('schema_version', 'rebuild_incomplete', 'ext_rebuilt_at', 'data_rev')")} \
            if "meta" in has else {}
        offs = {r["stream"]: (int(r["seg"]), int(r["off"])) for r in c.execute("SELECT stream, seg, off FROM inbox_offsets")} \
            if "inbox_offsets" in has else {}
        t = []
        if "raw_txs" in has:
            t += [r[0] for r in c.execute("SELECT ingested_at FROM raw_txs ORDER BY rowid DESC LIMIT 500") if r[0]]
        if "raw_ex" in has:
            t += [r[0] for r in c.execute("SELECT observed_at FROM raw_ex ORDER BY rowid DESC LIMIT 500") if r[0]]
        n_post = c.execute("SELECT max(rowid) FROM postings").fetchone()[0] if "postings" in has else None
    finally:
        c.close()
    mt = int(os.path.getmtime(path))
    data_t = int(max(t)) if t else None
    return {"meta": meta, "offsets": offs, "data_until": data_t, "mtime": mt,
            "T": min(data_t, mt) if data_t else mt, "postings_max_rowid": n_post, "tables": sorted(has)}


def check(path: str, full: bool = False) -> dict:
    try:
        info = inspect(path)
    except sqlite3.DatabaseError as e:
        return {"ok": False, "why": [f"열기 실패: {common.safe_err(e)}"], "info": None, "full": full}
    why = []
    sv = info["meta"].get("schema_version")
    if sv is None or str(sv) != str(dbm.SCHEMA_VERSION):
        why.append(f"원장 세대 {sv} ≠ 코드 {dbm.SCHEMA_VERSION}")
    if info["meta"].get("rebuild_incomplete"):
        why.append("재파생 미완 표식(rebuild_incomplete)")
    try:
        dr9 = int(str(info["meta"].get("data_rev") or 0).strip())
        if dr9 > dbm.DATA_REV:
            why.append(f"데이터 개정 {dr9} > 코드 {dbm.DATA_REV}(코드를 먼저 최신으로)")
    except ValueError:
        why.append("데이터 개정 번호(meta data_rev) 해석 불가")
    for t9 in ("postings", "raw_txs", "raw_ex", "inbox_offsets"):
        if t9 not in info["tables"]:
            why.append(f"표 없음: {t9}")
    c = _ro(path)
    try:
        rows = c.execute("PRAGMA integrity_check" if full else "PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as e:
        rows = [(f"열기 실패: {e}",)]
    finally:
        c.close()
    res = [r[0] for r in rows]
    if res != ["ok"]:
        why.append(("무결성" if full else "빠른 검사") + " 실패: " + "; ".join(res[:3]))
    return {"ok": not why, "why": why, "info": info, "full": full}


def coverage(offsets: dict, inbox_dir: str = None) -> dict:
    ib = inbox_dir or common.INBOX_DIR
    out = {}
    for s in STREAMS:
        seg, off = offsets.get(s, (1, 0))
        segs = lb.inbox_segments(ib, s)
        try:
            short9 = seg in segs and os.path.getsize(os.path.join(ib, s, f"{seg:09d}.jsonl")) < off
        except OSError:
            short9 = True
        if (seg in segs and not short9) or (not segs and (seg, off) == (1, 0)):
            out[s] = {"state": "replay", "seg": seg, "off": off, "segs": [segs[0], segs[-1]] if segs else None}
        elif short9:
            out[s] = {"state": "gap", "seg": seg, "off": off, "segs": [segs[0], segs[-1]], "why": f"세그먼트 {seg} 가 백업 위치보다 짧음(새 인박스)"}
        elif segs and segs[0] > seg:
            out[s] = {"state": "gap", "seg": seg, "off": off, "segs": [segs[0], segs[-1]], "why": f"세그먼트 {seg}~{segs[0] - 1} 이미 지워짐"}
        elif not segs:
            out[s] = {"state": "gap", "seg": seg, "off": off, "segs": None, "why": "인박스 비어 있음"}
        else:
            out[s] = {"state": "gap", "seg": seg, "off": off, "segs": [segs[0], segs[-1]], "why": "백업 위치가 지금 인박스 밖"}
    return out


def running_units(root: str = ROOT, scripts=UNIT_SCRIPTS) -> list:
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    src = os.path.realpath(os.path.join(root, "src"))
    me = os.getpid()
    hits = []
    for ln in out.splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit() or int(parts[0]) == me:
            continue
        pid, cmd = int(parts[0]), parts[1]
        for tok in cmd.split():
            name = os.path.basename(tok)
            if name not in scripts:
                continue
            if os.path.isabs(tok):
                if os.path.realpath(os.path.dirname(tok)) != src:
                    continue
            else:
                try:
                    cwd = os.readlink(f"/proc/{pid}/cwd")
                    if os.path.realpath(os.path.join(cwd, os.path.dirname(tok))) != src:
                        continue
                except OSError:
                    pass
            toks9 = cmd.split()
            i9 = toks9.index(tok) if tok in toks9 else -1
            arg9 = toks9[i9 + 1] if name == "unit_runner.py" and 0 <= i9 < len(toks9) - 1 else ""
            hits.append((pid, f"{name} {arg9}".strip()))
            break
    return hits


def _load_cfg() -> dict:
    try:
        import settings_store
        cfg = settings_store.load_config_quiet()
        if isinstance(cfg, dict):
            return cfg
    except (Exception, SystemExit):
        pass
    return _read_json(common.CONFIG_PATH, {}) or {}


def _backup_sets(path: str, cut: int) -> dict:
    c = _ro(path)
    try:
        tx = {}
        for ch, h in c.execute("SELECT chain, txhash FROM raw_txs"):
            tx.setdefault(ch, set()).add(h if ch == "sol" else str(h).lower())
        anchor = {}
        for ch, b in c.execute("SELECT chain, max(CAST(block AS INTEGER)) FROM raw_txs WHERE chain != 'sol' AND block IS NOT NULL"
                               " AND ingested_at <= ? GROUP BY chain", (cut,)):
            if b is not None:
                anchor[ch] = int(b)
        bsc_max = c.execute("SELECT max(block) FROM raw_txs WHERE chain='bsc'").fetchone()[0]
        wallets = {}
        for ch, a in c.execute("SELECT chain, address FROM wallets"):
            wallets.setdefault(ch, set()).add(a if ch == "sol" else str(a).lower())
        sol_anchor = {}
        for h, slot, ts9, snap in c.execute("SELECT txhash, block, ts, snapshot FROM raw_txs WHERE chain='sol' AND ts IS NOT NULL AND ts <= ?"
                                            " ORDER BY ts DESC, block DESC", (cut,)):
            if not SIG_RX.fullmatch(str(h or "")):
                continue
            try:
                rec = json.loads(snap)
            except (TypeError, ValueError):
                continue
            addrs = set()
            if rec.get("fee_payer"):
                addrs.add(str(rec["fee_payer"]))
            for d in rec.get("deltas") or []:
                if isinstance(d, dict) and d.get("asset") == "native" and d.get("owner"):
                    o = str(d["owner"])
                    addrs.add(o.split(":stake:", 1)[1] if ":stake:" in o else o)
            for a in addrs:
                if a not in sol_anchor:
                    sol_anchor[a] = (h, slot)
        ex = {}
        for exn, kind, uid, rev, payload in c.execute(
                "SELECT exchange, kind, uuid, revision, CASE WHEN kind IN ('deposit', 'withdraw') THEN payload END"
                " FROM raw_ex ORDER BY exchange, kind, uuid, revision"):
            d = ex.setdefault(exn, {}).setdefault(kind, {})
            if kind in ("deposit", "withdraw"):
                try:
                    p = json.loads(payload)
                except (TypeError, ValueError):
                    p = {}
                d[uid] = {"state": str(p.get("state") or ""), "txid": bool(p.get("txid")), "address": bool(p.get("address"))}
            else:
                d[uid] = True
    finally:
        c.close()
    return {"tx": tx, "anchor": anchor, "bsc_max": int(bsc_max) if bsc_max is not None else None, "wallets": wallets,
            "sol_anchor": sol_anchor, "ex": ex}


def _evm_wallet_keys(cur: dict) -> list:
    return [k for k, v in cur.items() if re.fullmatch(r"0x[0-9a-fA-F]{40}", k) and isinstance(v, int) and not isinstance(v, bool)]


_EVM_PER_WALLET = ("_cov:", "_disc:", "_bf:", "_bfes:", "_bk:", "_nw:")
_EVM_PER_WALLET_MAPS = ("_ns", "_bkns", "_hq", "_nonces", "_first_own")


def _drop_wallet_evm(cur: dict, w: str):
    for k in [w] + [p + w for p in _EVM_PER_WALLET]:
        cur.pop(k, None)
    for m in _EVM_PER_WALLET_MAPS:
        if isinstance(cur.get(m), dict):
            cur[m].pop(w, None)
    es = cur.get("_es_int")
    if isinstance(es, dict) and isinstance(es.get("seen"), dict):
        es["seen"].pop(w, None)


EVM_BPD_DEFAULT = 43200
BLOCK_SEC_SAFETY = 0.8


def block_sec(sd: str, ch: str, cfg: dict = None):
    cands = []
    hb = _read_json(os.path.join(sd, "health", "evm.json"), {}) or {}
    for k9 in (ch, f"{ch}:rpclog"):
        v9 = ((hb.get("sources") or {}).get(k9) or {}).get("block_sec_est") if isinstance(hb, dict) else None
        if isinstance(v9, (int, float)) and not isinstance(v9, bool) and 0.01 <= v9 <= 600:
            cands.append((float(v9), "수집기 관측"))
    bpd = ((cfg or {}).get("chains") or {}).get(ch, {}).get("blocks_per_day") if isinstance(((cfg or {}).get("chains") or {}).get(ch), dict) else None
    if bpd is None:
        try:
            import chaincatalog
            bpd = (chaincatalog.CATALOG.get(ch) or {}).get("blocks_per_day")
        except Exception:
            bpd = None
    try:
        if bpd and float(bpd) > 0:
            cands.append((86400.0 / float(bpd), "설정 blocks_per_day"))
    except (TypeError, ValueError):
        pass
    if not cands:
        cands.append((86400.0 / EVM_BPD_DEFAULT, "기본값"))
    sec, src = min(cands)
    return sec * BLOCK_SEC_SAFETY, src


def _time_back(sd, ch, cfg, cut, now):
    sec, src = block_sec(sd, ch, cfg)
    return int(max(0, now - cut) / sec) + 1, f"블록 시간 {sec:.3g}초({src} × {BLOCK_SEC_SAFETY:g})"


def plan_evm(sd: str, B: dict, notes: list, cut: int = None, now: int = None, cfg: dict = None) -> dict:
    now = int(time.time()) if now is None else int(now)
    cut = now if cut is None else int(cut)
    files = {}
    dropped = {}
    for n in sorted(os.listdir(sd)):
        m = re.match(r"^emitted_(evm|rpc)_([\w.-]+)\.json$", n)
        if m:
            ch = m.group(2)
            em = _read_json(os.path.join(sd, n), [])
            if isinstance(em, list):
                keep = [h for h in em if str(h).lower() in B["tx"].get(ch, set())]
                if len(keep) != len(em):
                    files[n] = keep
                    dropped.setdefault(ch, set()).update(str(h).lower() for h in em if str(h).lower() not in B["tx"].get(ch, set()))
                    notes.append(f"{n}: 방출 기록 {len(em)} → {len(keep)}(백업에 없는 {len(em) - len(keep)}건 다시 보냄)")
    for n in sorted(os.listdir(sd)):
        m = re.match(r"^cursor_(evm|rpc)_([\w.-]+)\.json$", n)
        if not m:
            continue
        kind, ch = m.groups()
        cur = _read_json(os.path.join(sd, n), None)
        if not isinstance(cur, dict):
            notes.append(f"★{n}: 읽지 못함(손상) — 그대로 둠 · 이 체인 그 사이 거래가 빠질 수 있어요(파일을 확인한 뒤 다시 미리보기)★")
            continue
        new = json.loads(json.dumps(cur))
        b = B["anchor"].get(ch)
        if kind == "rpc":
            fb = new.get("from_block")
            if not isinstance(fb, int) or isinstance(fb, bool):
                notes.append(f"{n}: from_block 없음(아직 첫 수집 전) — 그대로")
            elif b is not None:
                if fb > b:
                    new["from_block"] = b
                notes.append(f"{n}: from_block {fb} → {min(fb, b)}(기준 블록 {b} 이하)")
            else:
                back, why = _time_back(sd, ch, cfg, cut, now)
                new["from_block"] = max(0, fb - back)
                notes.append(f"★{n}: 기준 블록 없음(백업에 이 체인 거래가 여유 이전에 없음) — from_block {fb} → {new['from_block']}"
                             f"(시간으로 되감음 · {why})★")
            new.pop("_scan", None)
        else:
            rpc_track = "_rpc_v" in new
            known = B["wallets"].get(ch, set())
            timed = []
            for w in _evm_wallet_keys(new):
                if known and w.lower() not in known:
                    _drop_wallet_evm(new, w)
                    notes.append(f"{n}: 백업 뒤 넣은 지갑 {w[:10]}… — 새 지갑처럼 처음부터 다시 받음")
                    continue
                if b is None:
                    cov = new.get("_cov:" + w)
                    if not rpc_track and isinstance(cov, int) and not isinstance(cov, bool):
                        if new[w] > cov:
                            new[w] = cov
                            new.pop("_disc:" + w, None)
                            notes.append(f"{n}: 기준 블록 없음 → {w[:10]}… 창 처음({cov})부터 다시 훑음")
                        else:
                            notes.append(f"{n}: 기준 블록 없음 · {w[:10]}… 커서가 이미 창 처음({cov}) — 그대로")
                        continue
                    back, why = _time_back(sd, ch, cfg, cut, now)
                    lo = max([x for x in (cov, new.get("_start")) if isinstance(x, int) and not isinstance(x, bool)] or [0])
                    old9 = new[w]
                    new[w] = max(lo, old9 - back) if old9 > lo else old9
                    new.pop("_disc:" + w, None)
                    if isinstance(new.get("_ns"), dict):
                        new["_ns"].pop(w, None)
                    timed.append((w, old9, new[w], why))
                    continue
                if new[w] > b:
                    new[w] = b
                    new.pop("_disc:" + w, None)
                    if rpc_track:
                        if isinstance(new.get("_ns"), dict):
                            new["_ns"].pop(w, None)
            if timed:
                notes.append(f"★{n}: 기준 블록 없음(백업에 이 체인 거래가 여유 이전에 없음) — {'RPC 트랙 ' if rpc_track else ''}지갑 {len(timed)}개 시간으로 되감음"
                             f"({timed[0][3]} · 예 {timed[0][0][:10]}… {timed[0][1]} → {timed[0][2]})★")
            if rpc_track and dropped.get(ch):
                pp9 = f"pending_detail_{ch}.json"
                pend9 = _read_json(os.path.join(sd, pp9), {})
                pend9 = dict(pend9) if isinstance(pend9, dict) else {}
                n0 = len(pend9)
                for h9 in sorted(dropped[ch]):
                    if re.fullmatch(r"0x[0-9a-f]{64}", h9):
                        pend9.setdefault(h9, 0)
                if len(pend9) != n0:
                    files[pp9] = pend9
                    notes.append(f"{pp9}: 백업 뒤 방출한 {len(pend9) - n0}건을 해시로 다시 받음(로그 없는 네이티브 이동 포함 — 되감은 첫 구간은 잔고 기준점 없이 시작)")
                cc9 = ((cfg or {}).get("chains") or {}).get(ch)
                cc9 = cc9 if isinstance(cc9, dict) else {}
                lanes9 = isinstance(new.get("_handover"), dict) and cc9.get("rpc_lanes") is not False
                tm9 = str(cc9.get("rpc_trace") or "").lower() or ("own" if lanes9 else "all")
                if tm9 == "own" and not lanes9:
                    notes.append(f"★{n}: 이 체인은 trace 범위가 '내 지갑 발신만'(rpc_trace=own · 단일 차선)이라 복구 구간의 외부발 internal 입금(외부 → 컨트랙트 → 내 지갑)은"
                                 f" 다시 받을 때 trace 되지 않아 빠질 수 있어요 — tj-evm 을 켜기 전에 config.json chains.{ch}.rpc_trace 를 지우거나 \"all\" 로 바꾸면"
                                 f" 재시도 큐({pp9})가 전부 trace 해 다시 받아요(큐가 빈 뒤 되돌리기)★")
                if tm9 == "own" and lanes9:
                    hq9 = new.get("_hq") if isinstance(new.get("_hq"), dict) else {}
                    h0 = len(hq9)
                    for h9 in sorted(dropped[ch]):
                        if re.fullmatch(r"0x[0-9a-f]{64}", h9):
                            hq9.setdefault(h9, 0)
                    if len(hq9) != h0:
                        new["_hq"] = hq9
                        notes.append(f"{n}: 차선 모드(내 지갑 발신만 trace) — 복구 해시 {len(hq9) - h0}건을 인계 큐(_hq)에도(외부 → 컨트랙트 → 내 지갑 internal 입금도 trace)")
            if b is not None:
                notes.append(f"{n}: 지갑 커서 → 블록 {b} 이하")
            for k9 in ("_scan", "_bkscan"):
                new.pop(k9, None)
        for k9 in ("_synced_at", "_synced_tok_at"):
            new.pop(k9, None)
        if not any(n in x for x in notes):
            notes.append(f"{n}: 지갑 없음 — 동기화 도장만 지움")
        if new != cur:
            files[n] = new
    if any(n.startswith("cursor_evm_") for n in files):
        files["addr_tier_req.json"] = {"v": 1, "reqs": {"*": int(time.time())}, "updatedAt": int(time.time())}
        notes.append("addr_tier_req.json: 쉬는 지갑 전부 '지금 확인'")
    return files


def plan_sol(sd: str, B: dict, cfg: dict, cut: int, notes: list) -> dict:
    files = {}
    em = _read_json(os.path.join(sd, "emitted_sol.json"), None)
    if isinstance(em, list):
        keep = [h for h in em if h in B["tx"].get("sol", set())]
        if len(keep) != len(em):
            files["emitted_sol.json"] = keep
            notes.append(f"emitted_sol.json: {len(em)} → {len(keep)}")
    cur = _read_json(os.path.join(sd, "cursor_sol.json"), None)
    if not isinstance(cur, dict):
        return files
    new = json.loads(json.dumps(cur))
    owners = {w.get("address") for w in (cfg.get("wallets") or []) if isinstance(w, dict) and w.get("type") == "sol"}
    known = B["wallets"].get("sol", set())
    stake = {k[len("_stk:"):] for k in new if k.startswith("_stk:")}
    n_set = n_drop = 0
    for a in [k for k, v in new.items() if not k.startswith("_") and isinstance(v, str)]:
        side = ("_slot:", "_vat:", "_pnv:", "_pnmiss:")
        if a in owners and known and a not in known:
            for p in ("",) + side + ("_cov_ts:", "_cov_sig:", "_persp:"):
                new.pop(p + a, None)
            notes.append(f"cursor_sol: 백업 뒤 넣은 지갑 {a[:8]}… — 처음부터 다시 받음")
            n_drop += 1
            continue
        anc = B["sol_anchor"].get(a)
        if anc:
            new[a] = anc[0]
            if isinstance(anc[1], int):
                new["_slot:" + a] = anc[1]
            else:
                new.pop("_slot:" + a, None)
            for p in side[1:]:
                new.pop(p + a, None)
            n_set += 1
        elif a in owners:
            notes.append(f"★cursor_sol: 지갑 {a[:8]}… 기준 서명 없음(여유 이전 네이티브 변화·수수료 tx 없음) — 커서 그대로(토큰 이동은 토큰 계정 되감기로 받음)★")
        else:
            for p in ("",) + side:
                new.pop(p + a, None)
            n_drop += 1
    for a in stake:
        stk = new.get("_stk:" + a)
        if isinstance(stk, dict) and isinstance(stk.get("rwd_next"), int):
            back = int((time.time() - cut) // 172800) + 2
            stk["rwd_next"] = max(0, stk["rwd_next"] - back)
    new.pop("_synced_at", None)
    for k9 in [k9 for k9 in new if k9.startswith(("_hl:", "_fbw:"))]:
        new.pop(k9, None)
    if new != cur:
        files["cursor_sol.json"] = new
        notes.append(f"cursor_sol.json: 기준 서명으로 되감은 주소 {n_set} · 처음부터 다시 받을 주소 {n_drop}")
    return files


def plan_bsc(sd: str, B: dict, cut: int, now: int, notes: list) -> dict:
    files = {}
    L = B["tx"].get("bsc", set())
    em = _read_json(os.path.join(sd, "emitted_bsc.json"), None)
    if isinstance(em, list):
        keep = [h for h in em if str(h).lower() in L]
        if len(keep) != len(em):
            files["emitted_bsc.json"] = keep
            notes.append(f"emitted_bsc.json: {len(em)} → {len(keep)}")
    cur = _read_json(os.path.join(sd, "cursor_bsc.json"), None)
    if isinstance(cur, dict):
        new = json.loads(json.dumps(cur))
        fb = new.get("from_block")
        if isinstance(fb, int):
            back = int((max(0, now - cut)) / BSC_BLOCK_S)
            b = fb - back
            if B["bsc_max"] is not None:
                b = max(b, min(fb, B["bsc_max"]) - int(MARGIN_H * 3600 / BSC_BLOCK_S))
            cov = new.get("_cov")
            b = max(b, cov) if isinstance(cov, int) else b
            if b < fb:
                new["from_block"] = max(0, b)
                notes.append(f"cursor_bsc.json: from_block {fb} → {new['from_block']}")
        for k9 in ("_scan", "_synced_at", "_live", "_lscan"):
            new.pop(k9, None)
        if new != cur:
            files["cursor_bsc.json"] = new
    nst = _read_json(os.path.join(sd, "bsc_nonce.json"), None)
    if isinstance(nst, dict) and isinstance(nst.get("w"), dict):
        new = json.loads(json.dumps(nst))
        for w, ws in new["w"].items():
            if not isinstance(ws, dict):
                continue
            hs = ws.get("hashes") if isinstance(ws.get("hashes"), dict) else {}
            ws["hashes"] = {h: b for h, b in hs.items() if str(h).lower() in L}
            ws["blocks"] = sorted(ws["hashes"].values())
            ws.pop("pend", None)
            ws.pop("missing", None)
        if new != nst:
            files["bsc_nonce.json"] = new
            notes.append("bsc_nonce.json: 발신 색인 = 백업에 있는 것만(로그 없는 BNB 발신 다시 찾기)")
    xst = _read_json(os.path.join(sd, "bsc_xin.json"), None)
    if isinstance(xst, dict) and isinstance(xst.get("tx"), dict):
        new = json.loads(json.dumps(xst))
        new["tx"] = {h: m for h, m in new["tx"].items() if not (isinstance(m, dict) and m.get("r") == "emit" and str(h).lower() not in L)}
        if new != xst:
            files["bsc_xin.json"] = new
            notes.append("bsc_xin.json: 백업에 없는 회수 기록 지움(다시 회수)")
    return files


def _rewind_seen_wd(st: dict, bex: dict) -> int:
    rows = {}
    for kind in ("deposit", "withdraw"):
        rows.update(bex.get(kind) or {})
    seen = st.get("seen") if isinstance(st.get("seen"), dict) else {}
    st_tx = st.get("seen_txids") if isinstance(st.get("seen_txids"), dict) else {}
    st_dest = st.get("seen_dest") if isinstance(st.get("seen_dest"), dict) else {}
    n = 0
    for u in list(seen):
        b = rows.get(u)
        if b is None:
            seen.pop(u, None)
            st_tx.pop(u, None)
            st_dest.pop(u, None)
            n += 1
            continue
        if str(seen[u]).replace(SEEN_NOTIME, "").upper() != b["state"].upper():
            seen[u] = b["state"]
            n += 1
        if not b["txid"] and st_tx.pop(u, None) is not None:
            n += 1
        if not b["address"] and st_dest.pop(u, None) is not None:
            n += 1
    return n


def plan_ex(sd: str, B: dict, cut: int, notes: list) -> dict:
    files = {}
    ups = _read_json(os.path.join(sd, "upbit_orders_state.json"), None)
    if isinstance(ups, dict):
        new = json.loads(json.dumps(ups))
        known = set((B["ex"].get("upbit") or {}).get("order") or {})
        uu = [u for u in (new.get("uuids") or []) if u in known]
        if len(uu) != len(new.get("uuids") or []):
            notes.append(f"upbit_orders_state.json: 주문 uuid {len(new.get('uuids') or [])} → {len(uu)}")
        new["uuids"] = uu
        bu = new.get("backfilled_until")
        if isinstance(bu, (int, float)) and bu > cut - 30 * 86400:
            new["backfilled_until"] = cut - 30 * 86400
        new["complete"] = False
        if new != ups:
            files["upbit_orders_state.json"] = new
    exs = _read_json(os.path.join(sd, "exf_state.json"), None)
    if isinstance(exs, dict):
        new = json.loads(json.dumps(exs))
        for exn, st in new.items():
            if not isinstance(st, dict):
                continue
            bex = B["ex"].get(exn) or {}
            n_wd = _rewind_seen_wd(st, bex)
            if isinstance(st.get("backfilled_until"), (int, float)) and st["backfilled_until"] > cut:
                st["backfilled_until"] = cut
            fst = st.get("fills") if isinstance(st.get("fills"), dict) else None
            n_f = 0
            if fst is not None:
                trades = bex.get("trade") or {}
                fseen = fst.get("seen") if isinstance(fst.get("seen"), dict) else {}
                if exn == "hyperliquid":
                    for k in [k for k, v in fseen.items() if not isinstance(v, (int, float)) or v >= cut * 1000]:
                        fseen.pop(k)
                        n_f += 1
                else:
                    for k in [k for k in fseen if k not in trades]:
                        fseen.pop(k)
                        n_f += 1
                if isinstance(fst.get("backfilled_until"), (int, float)) and fst["backfilled_until"] > cut:
                    fst["backfilled_until"] = cut
                for k9, v9 in fst.items():
                    if k9.startswith("cv") and isinstance(v9, dict) and isinstance(v9.get("until"), (int, float)) and v9["until"] > cut:
                        v9["until"] = cut
                if exn == "binance":
                    n_f += _rewind_binance(fst, trades)
            if exn == "hyperliquid":
                for a, ast in (st.get("hl") or {}).items():
                    for k9 in ("led", "fil"):
                        s9 = ast.get(k9) if isinstance(ast, dict) else None
                        if isinstance(s9, dict) and isinstance(s9.get("next"), (int, float)) and s9["next"] > cut * 1000:
                            s9["next"] = cut * 1000
                sl = st.get("seen_led") if isinstance(st.get("seen_led"), dict) else {}
                for k in [k for k, v in sl.items() if not isinstance(v, (int, float)) or v >= cut * 1000]:
                    sl.pop(k)
            if n_wd or n_f:
                notes.append(f"exf_state.json {exn}: 입출금 기록 {n_wd}건 · 체결 기록 {n_f}건 되돌림(다시 받음)")
        if new != exs:
            files["exf_state.json"] = new
        for n in sorted(os.listdir(sd)):
            if re.match(r"^exf_balances_[\w-]+\.json(\.pending)?$", n):
                files[n] = None
        if any(v is None for k, v in files.items() if k.startswith("exf_balances_")):
            notes.append("exf_balances_*.json: 치움 — tj-exf 가 다시 받은 뒤 새 잔고로 대사")
    return files


def _rewind_binance(fst: dict, trades: dict) -> int:
    mx = {}
    for u in trades:
        p = u.split(":")
        if len(p) == 3 and p[0] == "binance" and p[2].isdigit():
            mx[("s", p[1])] = max(mx.get(("s", p[1]), -1), int(p[2]))
        elif len(p) == 4 and p[0] == "binance" and p[1] in ("m", "mi") and p[3].isdigit():
            ck = ("c:" if p[1] == "m" else "i:") + p[2]
            mx[("m", ck)] = max(mx.get(("m", ck), -1), int(p[3]))
    n = 0
    for key, chk, kind in (("pair_cursor", "pair_chk", "s"), ("margin_cursor", "margin_chk", "m")):
        cur = fst.get(key) if isinstance(fst.get(key), dict) else {}
        ck9 = fst.setdefault(chk, {}) if isinstance(fst.get(chk, {}), dict) else {}
        for p9, v in list(cur.items()):
            want = mx.get((kind, p9), -1) + 1
            if isinstance(v, (int, float)) and v > want:
                cur[p9] = want
                ck9[p9] = 0
                n += 1
    return n


def plan(backup: str, streams=None, margin_h: float = MARGIN_H, now: int = None, state_dir: str = None) -> dict:
    sd = state_dir or common.STATE_DIR
    now = int(time.time()) if now is None else int(now)
    try:
        info = inspect(backup)
    except sqlite3.DatabaseError as e:
        raise SystemExit(f"백업 열기 실패: {common.safe_err(e)} — 깨졌거나 원장 백업 파일이 아니에요(list 의 다른 번호로)")
    miss9 = [t9 for t9 in ("meta", "raw_txs", "raw_ex", "inbox_offsets", "wallets") if t9 not in info["tables"]]
    if miss9:
        raise SystemExit(f"원장 백업이 아니에요(표 없음: {', '.join(miss9)}) — 빈 파일·다른 파일이면 list 의 다른 번호로")
    T = info["T"]
    cut = int(T - margin_h * 3600)
    cov = coverage(info["offsets"], os.path.join(sd, "inbox"))
    rewind = [s for s in STREAMS if (streams is None and cov[s]["state"] == "gap") or (streams is not None and s in streams)]
    notes, files = [], {}
    if rewind:
        B = _backup_sets(backup, cut)
        cfg = _read_json(common.CONFIG_PATH, {}) or {}
        if "evm" in rewind:
            files.update(plan_evm(sd, B, notes, cut=cut, now=now, cfg=_load_cfg()))
        if "sol" in rewind:
            files.update(plan_sol(sd, B, cfg, cut, notes))
        if "bsc" in rewind:
            files.update(plan_bsc(sd, B, cut, now, notes))
        if "ex" in rewind:
            files.update(plan_ex(sd, B, cut, notes))
            notes.append("업비트 입출금: tj-ex 를 다시 시작하면 창 전체를 다시 보냄(파일 커서 없음)")
    return {"backup": backup, "T": T, "cut": cut, "margin_h": margin_h, "info": info, "coverage": cov, "rewind": rewind,
            "files": files, "notes": notes, "decisions_after": decisions_after(T)}


def decisions_after(T: int, live: str = None):
    live = live or common.DB_PATH
    if not os.path.exists(live):
        return None
    try:
        c = _ro(live)
        try:
            return int(c.execute("SELECT count(*) FROM decisions WHERE created_at > ?", (int(T),)).fetchone()[0])
        finally:
            c.close()
    except sqlite3.Error:
        return None


def invalidate_curves(sd: str):
    try:
        os.remove(os.path.join(sd, "daily_cache.json"))
    except FileNotFoundError:
        pass
    common.mark_hist_dirty(0, state_dir=sd)


def copy_ledger(src: str, dst: str):
    fd = os.open(dst, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    if os.path.exists(src + "-wal") and os.path.getsize(src + "-wal") > 0:
        s = sqlite3.connect(common.sqlite_ro_uri(src), uri=True, timeout=30)
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
            d.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            d.close()
            s.close()
    else:
        shutil.copyfile(src, dst)
    os.chmod(dst, 0o600)


def reset_inbox_offsets(path: str, streams: list) -> list:
    if not streams:
        return []
    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA journal_mode=DELETE").fetchone()
        c.executemany("DELETE FROM inbox_offsets WHERE stream=?", [(s,) for s in streams])
        c.commit()
    finally:
        c.close()
    for sfx in ("-wal", "-shm", "-journal"):
        if os.path.exists(path + sfx) and os.path.getsize(path + sfx) == 0:
            os.remove(path + sfx)
    return list(streams)


def apply(p: dict, full_check: bool = False, proc_check: bool = True, state_dir: str = None, log=print,
          keep_pre: int = PRE_RESTORE_KEEP) -> dict:
    sd = state_dir or common.STATE_DIR
    live = common.DB_PATH
    if proc_check:
        run = running_units()
        if run is None:
            raise SystemExit("프로세스 목록(ps)을 못 읽어 유닛 정지를 확인할 수 없어요 — 정지를 직접 확인했다면 --no-proc-check")
        if run:
            raise SystemExit("먼저 유닛을 멈추세요: " + STOP_HINT + "\n  떠 있는 것: " + ", ".join(f"{n}(pid {pid})" for pid, n in run))
    ck = check(p["backup"], full=full_check)
    if not ck["ok"]:
        raise SystemExit("백업 검사 실패 — 되돌리지 않았어요: " + " · ".join(ck["why"]))
    need = int(os.path.getsize(p["backup"]) * 1.1) + (512 << 20)
    free = shutil.disk_usage(sd).free
    if free < need:
        raise SystemExit(f"디스크 여유 부족 — 여유 {_gb(free)} < 필요 {_gb(need)}(백업 복사본). 오래된 보존본(state/ledger.db.pre_*)을 정리한 뒤 다시")
    lock = os.path.join(sd, "restore.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise SystemExit(f"다른 복구가 진행 중이에요(또는 지난 복구가 중간에 멈춤): {lock} — 확인 뒤 지우고 다시")
    rec_dir = tmp = None
    changed = []
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        base9, k9 = ts, 1
        while os.path.exists(os.path.join(sd, f"restore_{ts}")) or os.path.exists(live + f".pre_restore_{ts}"):
            k9 += 1
            ts = f"{base9}_{k9}"
        rec_dir = os.path.join(sd, f"restore_{ts}")
        os.makedirs(rec_dir, mode=0o700)
        tmp = live + f".restore_{ts}.tmp"
        try:
            copy_ledger(p["backup"], tmp)
            for sfx in ("-wal", "-shm", "-journal"):
                if os.path.exists(tmp + sfx):
                    os.remove(tmp + sfx)
            reset_inbox_offsets(tmp, [s for s, cv in p["coverage"].items() if cv["state"] == "gap"])
            c = sqlite3.connect(common.sqlite_ro_uri(tmp, immutable=True), uri=True)
            try:
                ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            finally:
                c.close()
            if not ok:
                raise SystemExit("복사본 빠른 검사 실패 — 되돌리지 않았어요(디스크 확인)")
            for name, obj in sorted(p["files"].items()):
                src9 = os.path.join(sd, name)
                if os.path.exists(src9):
                    shutil.copy2(src9, os.path.join(rec_dir, name))
                if obj is None:
                    if os.path.exists(src9):
                        os.remove(src9)
                        changed.append(f"치움 {name}")
                else:
                    common.atomic_write_json(src9, obj)
                    changed.append(f"고침 {name}")
            if not os.path.exists(live):
                for sfx in ("-wal", "-shm"):
                    if os.path.exists(live + sfx):
                        os.replace(live + sfx, live + f".orphan_{ts}{sfx}")
            res = lb.swap_in(live, tmp, live + f".pre_restore_{ts}")
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            try:
                common.atomic_write_json(os.path.join(rec_dir, "plan.json"), {"ts": int(time.time()), "backup": p["backup"], "failed": True,
                                                                             "changed": changed})
            except OSError:
                pass
            raise
        log(f"원장 교체 완료 — 이전 원장: {os.path.basename(res['kept']) if res['kept'] else '(없었음)'}"
            + ("" if res["linked"] or not res["kept"] else " · 하드 링크 불가라 이름 바꾸기로"))
        invalidate_curves(sd)
        gone = prune_pre_restore(sd, keep_pre, keep_path=res["kept"])
        if gone:
            log("오래된 복구 전 보존본 정리(최근 %d개만): %s" % (keep_pre, ", ".join(os.path.basename(g) for g in gone)))
        rec = {"ts": int(time.time()), "backup": p["backup"], "T": p["T"], "cut": p["cut"], "margin_h": p["margin_h"],
               "coverage": p["coverage"], "rewind": p["rewind"], "changed": changed, "notes": p["notes"],
               "kept": res["kept"], "originals": rec_dir, "pre_restore_pruned": [os.path.basename(g) for g in gone]}
        common.atomic_write_json(os.path.join(rec_dir, "plan.json"), rec)
        lb.fsync_dir(sd)
        return rec
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def prune_pre_restore(sd: str, keep: int = PRE_RESTORE_KEEP, keep_path: str = None) -> list:
    keep = max(1, int(keep))
    pre = os.path.basename(common.DB_PATH) + ".pre_restore_"
    try:
        names = sorted((n for n in os.listdir(sd) if n.startswith(pre) and not n.endswith(("-wal", "-shm"))),
                       key=lambda n: os.path.getmtime(os.path.join(sd, n)), reverse=True)
    except OSError:
        return []
    if keep_path:
        kp = os.path.basename(keep_path)
        names = [kp] + [n for n in names if n != kp] if kp in names else names
    gone = []
    for n in names[keep:]:
        for sfx in ("", "-wal", "-shm"):
            q = os.path.join(sd, n + sfx)
            try:
                os.remove(q)
                if not sfx:
                    gone.append(q)
            except FileNotFoundError:
                pass
            except OSError:
                break
    return gone


FILES_STOP_HINT = "pm2 stop tj-web tj-review"
FILES_UNITS = ("web.py", "unit_runner.py web", "review_daily.py")
_SEED_LOCAL_RX = re.compile(r"^seed_local__([\w.-]+(?:__[\w.-]+)*\.json)$")


def files_days(state_dir: str = None) -> list:
    bdir = os.path.join(state_dir or common.STATE_DIR, "backups")
    days = set()
    try:
        for n in os.listdir(bdir):
            m = re.match(r"^(?:files_(\d{8})|prefs_(\d{8})\.json)$", n)
            if m:
                days.add(m.group(1) or m.group(2))
    except OSError:
        pass
    return sorted(days, reverse=True)


def files_plan(day: str, state_dir: str = None) -> dict:
    sd = state_dir or common.STATE_DIR
    if not re.fullmatch(r"\d{8}", str(day or "")):
        raise SystemExit("날짜는 YYYYMMDD — python3 tools/ledger_restore.py files 로 목록")
    bdir = os.path.join(sd, "backups")
    fdir = os.path.join(bdir, f"files_{day}")
    items, manual, info = [], [], []
    if os.path.isdir(fdir):
        for n in sorted(os.listdir(fdir)):
            src = os.path.join(fdir, n)
            if not os.path.isfile(src) or n.endswith(".tmp"):
                continue
            m = _SEED_LOCAL_RX.match(n)
            if n in lb.FILES_STATE or lb.FILES_STATE_RX.match(n):
                items.append((src, n))
            elif m and ".." not in m.group(1).split("__"):
                items.append((src, os.path.join("seed_local", *m.group(1).split("__"))))
            elif n == "config_subset.json":
                manual.append(f"{src} — config.json 의 지갑 목록(wallets)·거래소 입금주소(exchange_addresses) 사본: 필요하면 손으로 옮기세요(키·토큰은 원래 안 담김)")
    pj = os.path.join(bdir, f"prefs_{day}.json")
    if os.path.isfile(pj):
        d9 = _read_json(pj, None)
        if not isinstance(d9, dict):
            raise SystemExit(f"열기 실패: {pj} — 깨진 사본(다른 날짜로)")
        for key, name in (("ui_prefs", "ui_prefs.json"), ("outflow_decisions", "outflow_decisions.json")):
            if isinstance(d9.get(key), (dict, list)):
                items.append((("json", d9[key], pj), name))
        if isinstance(d9.get("decisions"), list):
            info.append(f"원장 판정(decisions) {len(d9['decisions'])}건은 원장 안 표라 이 명령으로 안 바뀌어요 — 원장째 되돌리기 = restore")
    if not items and not manual:
        raise SystemExit(f"{day} 사본이 없어요(state/backups/files_{day}/ · prefs_{day}.json) — files 로 목록")
    return {"day": day, "items": items, "manual": manual, "info": info}


def files_payloads(fp: dict) -> tuple:
    ok, bad = [], []
    for src, rel in fp["items"]:
        if os.path.isabs(rel) or ".." in rel.split(os.sep):
            bad.append(f"{rel}: 경로 이상")
            continue
        if isinstance(src, tuple):
            ok.append((rel, json.dumps(src[1], ensure_ascii=False, indent=1).encode("utf-8")))
            continue
        try:
            with open(src, "rb") as f:
                data = f.read()
            val = json.loads(data.decode("utf-8"))
            if not isinstance(val, (dict, list)):
                raise ValueError("JSON 객체·배열이 아님")
        except (OSError, ValueError, UnicodeDecodeError) as e:
            bad.append(f"{rel}: {common.safe_err(e)[:80]}")
            continue
        ok.append((rel, data))
    return ok, bad


def files_apply(fp: dict, proc_check: bool = True, state_dir: str = None, log=print) -> dict:
    sd = state_dir or common.STATE_DIR
    if proc_check:
        run = running_units(scripts=UNIT_SCRIPTS + ("review_daily.py",))
        if run is None:
            raise SystemExit("프로세스 목록(ps)을 못 읽어 유닛 정지를 확인할 수 없어요 — 정지를 직접 확인했다면 --no-proc-check")
        web9 = [(pid, n) for pid, n in run if n in FILES_UNITS]
        if web9:
            raise SystemExit("먼저 화면·리뷰 유닛을 멈추세요: " + FILES_STOP_HINT + "\n  떠 있는 것: " + ", ".join(f"{n}(pid {pid})" for pid, n in web9))
    payloads, bad = files_payloads(fp)
    if bad:
        raise SystemExit("깨진 사본이 있어 아무것도 안 바꿨어요(하나라도 깨지면 전체 거부): " + " · ".join(bad[:5])
                         + " — 다른 날짜로: python3 tools/ledger_restore.py files")
    base9 = os.path.join(sd, "restore_files_" + time.strftime("%Y%m%d_%H%M%S"))
    keep, k9 = base9, 1
    while os.path.exists(keep):
        k9 += 1
        keep = f"{base9}_{k9}"
    os.makedirs(keep, mode=0o700)
    done = []
    for rel, data in payloads:
        dst = os.path.join(sd, rel)
        if os.path.exists(dst):
            os.makedirs(os.path.dirname(os.path.join(keep, rel)), mode=0o700, exist_ok=True)
            shutil.copy2(dst, os.path.join(keep, rel))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp9 = dst + ".restore_tmp"
        fd = os.open(tmp9, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp9, dst)
        done.append(rel)
    if "daily_px.json" in done:
        invalidate_curves(sd)
    common.atomic_write_json(os.path.join(keep, "plan.json"), {"ts": int(time.time()), "day": fp["day"], "restored": done})
    log(f"되돌림 {len(done)}개: " + ", ".join(done) + f"\n지금 것 보존: {keep}")
    return {"restored": done, "kept": keep}


COLLECTOR_UNITS = ("evm_watch.py", "sol_watch.py", "bsc_watch.py", "upbit_link.py", "ex_foreign.py",
                   "unit_runner.py evm", "unit_runner.py sol", "unit_runner.py bsc")
COLLECT_STOP_HINT = "pm2 stop tj-evm tj-sol tj-bsc tj-ex tj-exf"


def new_ledger(apply_: bool, fresh_collect: bool = False, state_dir: str = None, log=print, proc_check: bool = True) -> int:
    sd = state_dir or common.STATE_DIR
    if apply_ and fresh_collect and proc_check:
        run = running_units()
        if run is None:
            raise SystemExit("프로세스 목록(ps)을 못 읽어 수집기 정지를 확인할 수 없어요 — 정지를 직접 확인했다면 --no-proc-check")
        col9 = [(pid, n) for pid, n in run if n in COLLECTOR_UNITS or n.split()[0] in COLLECTOR_UNITS[:5]]
        if col9:
            raise SystemExit("먼저 수집기를 멈추세요: " + COLLECT_STOP_HINT + "\n  떠 있는 것: " + ", ".join(f"{n}(pid {pid})" for pid, n in col9))
    if os.path.exists(common.DB_PATH):
        log(f"원장이 있어요({common.DB_PATH}) — 새 원장 표식은 원장이 없을 때만")
        return 1
    ev = lb.prior_ledger_evidence(sd)
    log("예전 원장 흔적: " + (" · ".join(ev) if ev else "없음(첫 설치 — 표식 없이도 유닛 러너가 만듦)"))
    moved = []
    if fresh_collect:
        pats = (r"^cursor_(evm|rpc)_[\w.-]+\.json$", r"^emitted_(evm|rpc)_[\w.-]+\.json$", r"^cursor_(sol|bsc)\.json$", r"^emitted_(sol|bsc)\.json$",
                r"^(upbit_orders_state|exf_state|bsc_nonce|bsc_xin|backfill_done)(\.json)?$")
        moved = [n for n in sorted(os.listdir(sd)) if any(re.match(x, n) for x in pats)]
        log("수집 기록 옆으로(처음부터 다시 받음): " + (", ".join(moved) if moved else "없음"))
    else:
        log("수집기 커서는 그대로 — 새 원장엔 커서 이후 거래만 들어와요(처음부터 다시 받으려면 --fresh-collect)")
    if not apply_:
        log("미리보기 — 적용하려면 --apply")
        return 0
    if moved:
        aside = os.path.join(sd, f"fresh_aside_{time.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(aside, mode=0o700)
        for n in moved:
            os.replace(os.path.join(sd, n), os.path.join(aside, n))
        log(f"옮김: {aside}")
    invalidate_curves(sd)
    common.atomic_write_json(os.path.join(sd, lb.NEW_LEDGER_OK), {"ts": int(time.time()), "by": "ledger_restore new"})
    log(f"새 원장 허용 표식 기록(1시간 · 한 번) — 유닛 러너가 다음 확인(15초) 때 빈 원장을 만들어요. pm2 직접 실행이면: TJ_ALLOW_NEW_LEDGER=1 로 core 1회")
    return 0


def _print_plan(p: dict, log=print):
    i = p["info"]
    log(f"백업: {p['backup']}")
    log(f"  데이터 시각 {_kst(i['data_until']) if i['data_until'] else '?'} · 파일 시각 {_kst(i['mtime'])} · 세대 {i['meta'].get('schema_version')}")
    log(f"  기준 시각 T = {_kst(p['T'])} · 되감기 기준 = T − {p['margin_h']:g}시간 = {_kst(p['cut'])}")
    for s, c in p["coverage"].items():
        if c["state"] == "replay":
            log(f"  인박스 {s:3}: 백업 위치 {c['seg']}:{c['off']} 그대로 있음 → core 가 다시 읽어 채움")
        else:
            log(f"  인박스 {s:3}: {c.get('why')} → 원장의 인박스 위치를 처음으로(지금 인박스 전부 다시 읽음) + 수집기 되감기"
                + ("" if s in p["rewind"] else " (되감기는 이번엔 안 함)"))
    if not p["rewind"]:
        log("  수집기 되감기 필요 없음")
    for n in p["notes"]:
        log("  · " + n)
    if p["files"]:
        log(f"  바꿀 상태 파일 {len(p['files'])}개: " + ", ".join(sorted(p["files"])))
    da9 = p.get("decisions_after")
    if da9:
        log(f"  ★지금 원장의 판정(매칭 확인·원가 지정 등) {da9}건이 백업 뒤에 생겼어요 — 되돌리면 원장에서 사라져요(화면에서 다시 · "
            "원장 밖 화면 설정·보낸 내역 판정은 그대로)★")


EPILOG = """순서: list → restore <번호>(미리보기) → pm2 stop tj-core tj-evm tj-sol tj-bsc tj-ex tj-exf tj-web → restore <번호> --apply
      → pm2 start tj-core → (몇 분 뒤) pm2 start tj-evm tj-sol tj-bsc tj-ex tj-exf tj-web
지금 원장은 state/ledger.db.pre_restore_<시각> 으로 보존(최근 2개만 — --keep-pre) · 바꾼 수집기 상태 파일 원본은 state/restore_<시각>/.
백업 뒤 수집분: 인박스에 백업 위치가 남았으면(다 읽은 세그먼트 기본 8일 · 스트림당 512MiB 상한 — TJ_INBOX_RETAIN_DAYS) core 가 그대로 다시 읽고,
  아니면 수집기 커서를 '백업 시각 − 여유(12시간)' 이전에 들어온 마지막 블록으로 되감는다(기준 블록이 없는 체인은 시간으로 되감고 ★ 안내).
되돌리면 원장 안 판정(매칭 확인·원가 지정 등 decisions)도 백업 시점으로 — 그 뒤 판정은 다시(미리보기가 건수를 알려 줌).
원장 밖 사본(지난날 고정가·AI 리뷰·기타 자산·설정·메모·화면 설정): files → files <YYYYMMDD> → pm2 stop tj-web tj-review → --apply.
원장이 없고 정말 새로 시작: new --apply (수집도 처음부터면 --fresh-collect)."""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="원장 복구 도구(백업 목록·검사·되돌리기)", epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="백업 목록")
    c1 = sub.add_parser("check", help="무결성 검사")
    c1.add_argument("backup")
    c1.add_argument("--quick", action="store_true", help="빠른 검사(quick_check)만")
    r = sub.add_parser("restore", help="백업으로 되돌리기(기본 = 미리보기)")
    r.add_argument("backup")
    r.add_argument("--apply", action="store_true")
    r.add_argument("--margin-hours", type=float, default=MARGIN_H, help="되감기 여유(기본 12시간)")
    r.add_argument("--rewind", default="auto", help="auto(인박스에 없는 스트림만) | all | none | evm,sol,bsc,ex")
    r.add_argument("--full-check", action="store_true", help="적용 전 integrity_check(느림 · 기본은 quick_check)")
    r.add_argument("--no-proc-check", action="store_true", help="유닛 정지 확인을 못 하는 환경에서만")
    r.add_argument("--keep-pre", type=int, default=PRE_RESTORE_KEEP, help=f"복구 전 보존본(ledger.db.pre_restore_*) 최근 몇 개 남길지(기본 {PRE_RESTORE_KEEP} · 최소 1)")
    fl = sub.add_parser("files", help="원장 밖 사본(files_<날짜>/ · prefs_<날짜>.json) 되돌리기(기본 = 미리보기)")
    fl.add_argument("day", nargs="?", help="YYYYMMDD — 없으면 목록")
    fl.add_argument("--apply", action="store_true")
    fl.add_argument("--no-proc-check", action="store_true", help="화면 유닛 정지 확인을 못 하는 환경에서만")
    n = sub.add_parser("new", help="정말 새 원장으로 시작")
    n.add_argument("--apply", action="store_true")
    n.add_argument("--fresh-collect", action="store_true", help="수집 커서·방출 기록도 옆으로(처음부터 다시 받음 — 수집기를 먼저 멈춤)")
    n.add_argument("--no-proc-check", action="store_true", help="수집기 정지 확인을 못 하는 환경에서만")
    a = ap.parse_args(argv)
    common.ensure_dirs()
    if a.cmd == "list":
        rows = backups()
        if not rows:
            print("백업이 없어요(state/backups · state/ledger.db.pre_*)")
            return 1
        print(f"원장: {common.DB_PATH} " + ("(있음)" if os.path.exists(common.DB_PATH) else "(없음)"))
        for k, r9 in enumerate(rows, 1):
            try:
                i = inspect(r9["path"])
                cov = coverage(i["offsets"])
                rep = " ".join(f"{s}:{'이어읽기' if c['state'] == 'replay' else '되감기'}" for s, c in cov.items())
                extra = f"데이터 {_kst(i['data_until']) if i['data_until'] else '?'} · 세대 {i['meta'].get('schema_version')} · {rep}"
            except sqlite3.DatabaseError as e:
                extra = f"열기 실패: {e}"
            print(f"{k:2}. {r9['name']}  {_gb(r9['size'])}  {_kst(r9['mtime'])}  {extra}")
        print("\n다음: python3 tools/ledger_restore.py restore <번호>   (미리보기 → --apply)")
        return 0
    if a.cmd == "files":
        if not a.day:
            days = files_days()
            if not days:
                print("원장 밖 사본이 없어요(state/backups/files_<날짜>/ · prefs_<날짜>.json — tj-core 정기 백업이 매일 만듦)")
                return 1
            print("원장 밖 사본 날짜(새 것부터): " + " ".join(days))
            print("다음: python3 tools/ledger_restore.py files <YYYYMMDD>   (미리보기 → --apply)")
            return 0
        fp = files_plan(a.day)
        for src, rel in fp["items"]:
            print(f"  되돌림 대상: state/{rel}  ← " + (f"{os.path.basename(src[2])} 의 칸" if isinstance(src, tuple) else os.path.relpath(src, common.STATE_DIR)))
        for x in fp["manual"] + fp["info"]:
            print("  · " + x)
        for x in files_payloads(fp)[1]:
            print("  ★깨짐(적용 거부): " + x + "★")
        if not a.apply:
            print(f"\n미리보기예요(아무것도 안 바꿈). 적용: {FILES_STOP_HINT} → 같은 명령 + --apply → pm2 start tj-web tj-review")
            return 0
        files_apply(fp, proc_check=not a.no_proc_check)
        print("다음: pm2 start tj-web tj-review")
        return 0
    if a.cmd == "check":
        res = check(resolve(a.backup), full=not a.quick)
        print(("정상" if res["ok"] else "문제: " + " · ".join(res["why"])) + f" ({'integrity_check' if res['full'] else 'quick_check'})")
        return 0 if res["ok"] else 1
    if a.cmd == "restore":
        bk = resolve(a.backup)
        if os.path.realpath(bk) == os.path.realpath(common.DB_PATH):
            raise SystemExit("지금 원장 자체는 백업이 아니에요")
        streams = None if a.rewind == "auto" else (list(STREAMS) if a.rewind == "all" else
                                                   [] if a.rewind == "none" else [s for s in a.rewind.split(",") if s in STREAMS])
        if a.apply and not a.no_proc_check:
            run = running_units()
            if run:
                raise SystemExit("먼저 유닛을 멈추세요: " + STOP_HINT + "\n  떠 있는 것: " + ", ".join(f"{n9}(pid {pid})" for pid, n9 in run))
        p = plan(bk, streams=streams, margin_h=a.margin_hours)
        _print_plan(p)
        if not a.apply:
            run = running_units()
            if run:
                print("\n떠 있는 유닛: " + ", ".join(f"{n9}(pid {pid})" for pid, n9 in run) + f" — 적용 전에 {STOP_HINT}")
            print("\n미리보기예요(아무것도 안 바꿈). 적용: 같은 명령 + --apply")
            return 0
        rec = apply(p, full_check=a.full_check, proc_check=not a.no_proc_check, keep_pre=a.keep_pre)
        print(f"\n완료 — 기록·원본: {rec['originals']}")
        print("다음: " + START_HINT)
        return 0
    if a.cmd == "new":
        return new_ledger(a.apply, a.fresh_collect, proc_check=not a.no_proc_check)
    return 2


if __name__ == "__main__":
    sys.exit(main())
