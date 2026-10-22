from __future__ import annotations

import os
import time

import chain_registry as reg
import paths, statefile

MAX_TRIES = 12
BACKOFF_MIN, BACKOFF_MAX = 30, 6 * 3600
EMITTED_KEEP = 200000
GAP_RETRY_SEC = 6 * 3600


class ChainState:
    def __init__(self, chain: str, state_dir: str = None):
        self.spec = reg.spec(chain)
        self.chain = chain
        sd = state_dir or paths.STATE_DIR
        self.path = os.path.join(sd, self.spec.cursor_file)
        self.emitted_path = os.path.join(sd, self.spec.emitted_file)
        d = statefile.read_json(self.path, None)
        self.d = d if isinstance(d, dict) and d.get("v") == 1 else {"v": 1, "lanes": {}, "pending": {}, "gaps": [], "status": {}}
        for k, dv in (("lanes", {}), ("pending", {}), ("gaps", []), ("status", {})):
            if not isinstance(self.d.get(k), type(dv)):
                self.d[k] = dv
        e = statefile.read_json(self.emitted_path, None)
        self.em = e if isinstance(e, dict) and isinstance(e.get("uids"), dict) else {"v": 1, "uids": {}}
        self._em_dirty = False

    def save(self) -> None:
        statefile.atomic_write_json(self.path, self.d)
        if self._em_dirty:
            u = self.em["uids"]
            if len(u) > EMITTED_KEEP:
                for k in sorted(u, key=lambda x: (u[x].get("t") if isinstance(u[x], dict) else u[x]) or 0)[:len(u) - EMITTED_KEEP]:
                    u.pop(k, None)
            r9 = self.em.get("res")
            if isinstance(r9, dict) and len(r9) > EMITTED_KEEP:
                for k in sorted(r9, key=lambda x: (r9[x].get("t") if isinstance(r9[x], dict) else 0) or 0)[:len(r9) - EMITTED_KEEP]:
                    r9.pop(k, None)
            statefile.atomic_write_json(self.emitted_path, self.em)
            self._em_dirty = False

    def lane(self, lane: str) -> dict:
        return dict(self.d["lanes"].get(lane) or {})

    def save_cursor(self, lane: str, cursor, fingerprint: str, upper=None) -> None:
        cur = self.d["lanes"].get(lane)
        if cur and cur.get("fp") and cur.get("fp") != fingerprint:
            raise ValueError(f"{self.chain}:{lane} 질의 지문이 바뀜 — 커서를 옮기지 말고 reset_lane(안전 경계부터 겹쳐 다시)")
        self.d["lanes"][lane] = {"cursor": cursor, "fp": fingerprint, "upper": upper, "updated": int(time.time()),
                                 "safe": (cur or {}).get("safe")}
        self.save()

    def mark_safe(self, lane: str, boundary) -> None:
        ln = self.d["lanes"].setdefault(lane, {})
        ln["safe"] = boundary
        self.save()

    def reset_lane(self, lane: str, why: str) -> None:
        cur = self.d["lanes"].get(lane) or {}
        self.d["lanes"][lane] = {"cursor": None, "fp": None, "upper": None, "updated": int(time.time()), "safe": cur.get("safe"),
                                 "reset_why": str(why)[:120]}
        self.save()

    def pending_upsert(self, items) -> int:
        n = 0
        now = int(time.time())
        for sid, ref in items:
            sid = str(sid)
            if sid in self.d["pending"]:
                continue
            em9 = self.em["uids"].get(sid)
            if em9 is not None and (not isinstance(em9, dict) or (ref or {}).get("owner") in (em9.get("o") or ())
                                    or (ref or {}).get("owner") is None):
                continue
            self.d["pending"][sid] = {"ref": ref, "first": now, "tries": 0, "next": 0, "why": ""}
            n += 1
        return n

    def due(self, now: float = None, limit: int = 50, lane: str = None) -> list:
        now = time.time() if now is None else now
        rows = [(sid, p) for sid, p in self.d["pending"].items()
                if float(p.get("next") or 0) <= now and (lane is None or (p.get("ref") or {}).get("lane") == lane)]
        rows.sort(key=lambda x: (x[1].get("first") or 0, x[0]))
        return rows[:max(0, int(limit))]

    def reschedule(self, sid: str, why: str, now: float = None) -> str:
        now = time.time() if now is None else now
        p = self.d["pending"].get(sid)
        if p is None:
            return "gone"
        p["tries"] = int(p.get("tries") or 0) + 1
        p["why"] = str(why)[:160]
        if p["tries"] >= MAX_TRIES:
            self.d["pending"].pop(sid, None)
            o9 = (p.get("ref") or {}).get("owner")
            self.d["gaps"] = [g for g in self.d["gaps"] if not (isinstance(g, dict) and str(g.get("id")) == str(sid)
                                                                 and (g.get("ref") or {}).get("owner") == o9)]
            self.d["gaps"].append({"id": sid, "ref": p.get("ref"), "why": p["why"], "tries": p["tries"], "at": int(now)})
            self.save()
            return "gap"
        p["next"] = int(now + min(BACKOFF_MAX, BACKOFF_MIN * (2 ** (p["tries"] - 1))))
        self.save()
        return "retry"

    def requeue_gaps(self, owners, now: float = None) -> int:
        now = time.time() if now is None else now
        at = {}
        for g in self.d["gaps"]:
            if isinstance(g, dict):
                k = (str(g.get("id")), (g.get("ref") or {}).get("owner"))
                try:
                    at[k] = max(at.get(k, 0), int(g.get("at") or 0))
                except (TypeError, ValueError):
                    at[k] = max(at.get(k, 0), 0)
        n = 0
        for sid, ref, _eo in self.unresolved_gaps():
            if ref.get("lane") == "reorg" or ref.get("owner") not in owners or sid in self.d["pending"] \
                    or now - at.get((sid, ref.get("owner")), 0) < GAP_RETRY_SEC:
                continue
            self.d["pending"][sid] = {"ref": ref, "first": int(now), "tries": MAX_TRIES - 1, "next": 0, "why": "gap 재시도"}
            n += 1
        if n:
            self.save()
        return n

    def mark_emitted(self, sid: str, tx_uid: str, owners=None, covered=()) -> None:
        self.d["pending"].pop(str(sid), None)
        now = int(time.time())
        ow = sorted(owners or ())
        self.em["uids"][str(tx_uid)] = {"t": now, "o": ow}
        for s9 in {str(sid)} | {str(x) for x in covered or ()}:
            if s9 != str(tx_uid):
                res = self.em.get("res") if isinstance(self.em.get("res"), dict) else self.em.setdefault("res", {})
                old = res.get(s9) if isinstance(res.get(s9), dict) else {}
                res[s9] = {"u": str(tx_uid), "o": sorted(set(ow) | set(old.get("o") or ())), "t": now}
        self._em_dirty = True

    def emitted(self, tx_uid: str) -> bool:
        return str(tx_uid) in self.em["uids"]

    def _gap_resolved(self, sid: str, owner) -> bool:
        em9 = self.em["uids"].get(sid)
        if em9 is not None and (not isinstance(em9, dict) or owner in (em9.get("o") or ())):
            return True
        r9 = (self.em.get("res") or {}).get(sid) if isinstance(self.em.get("res"), dict) else None
        return isinstance(r9, dict) and owner in (r9.get("o") or ())

    def unresolved_gaps(self) -> list:
        out, seen = [], set()
        for g9 in self.d["gaps"]:
            if not isinstance(g9, dict):
                continue
            sid9, ref9 = str(g9.get("id")), dict(g9.get("ref") or {})
            if (sid9, ref9.get("owner")) in seen or self._gap_resolved(sid9, ref9.get("owner")):
                continue
            seen.add((sid9, ref9.get("owner")))
            em9 = self.em["uids"].get(sid9)
            r9 = (self.em.get("res") or {}).get(sid9) if isinstance(self.em.get("res"), dict) else None
            eo9 = set((em9 or {}).get("o") or ()) if isinstance(em9, dict) else set()
            eo9 |= set((r9 or {}).get("o") or ()) if isinstance(r9, dict) else set()
            out.append((sid9, ref9, eo9))
        return sorted(out, key=lambda x: (x[0], str(x[1].get("owner"))))

    def drop_owner(self, owner_keys_left: set) -> int:
        gone = [sid for sid, p in self.d["pending"].items() if (p.get("ref") or {}).get("owner") not in owner_keys_left]
        for sid in gone:
            self.d["pending"].pop(sid, None)
        for o in [o for o in self.d["status"] if o not in owner_keys_left]:
            self.d["status"].pop(o, None)
        return len(gone)

    SYNC_MAX_AGE = 600

    def mark_synced(self, now: float = None) -> None:
        self.d["synced_at"] = int(time.time() if now is None else now)
        self.save()

    def owner_done(self, owner: str) -> bool:
        st = self.d["status"].get(owner) or {}
        if st.get("details_complete_through") is None:
            return False
        if any((p.get("ref") or {}).get("owner") == owner for p in self.d["pending"].values()):
            return False
        return not any(r9.get("owner") == owner for _s9, r9, _o9 in self.unresolved_gaps())

    def ready(self, owners, now: float = None, max_age: float = None) -> bool:
        now = time.time() if now is None else now
        t = self.d.get("synced_at")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or now - t > (max_age or self.SYNC_MAX_AGE):
            return False
        return bool(owners) and all(self.owner_done(o) for o in owners)

    STATUS_FIELDS = ("requested_from", "available_from", "scanned_through", "details_complete_through", "balance_snapshot_at")

    def set_status(self, owner: str, **kw) -> None:
        st = self.d["status"].setdefault(owner, {})
        for k, v in kw.items():
            if k not in self.STATUS_FIELDS:
                raise ValueError(f"모르는 상태 칸: {k}")
            st[k] = v

    def status_view(self) -> dict:
        out = {}
        pend = {}
        for p in self.d["pending"].values():
            o = (p.get("ref") or {}).get("owner")
            pend[o] = pend.get(o, 0) + 1
        gaps = {}
        for g in self.d["gaps"]:
            o = (g.get("ref") or {}).get("owner")
            gaps[o] = gaps.get(o, 0) + 1
        gopen = {}
        for _s9, r9, _o9 in self.unresolved_gaps():
            gopen[r9.get("owner")] = gopen.get(r9.get("owner"), 0) + 1
        for o, st in self.d["status"].items():
            req, avail = st.get("requested_from"), st.get("available_from")
            partial = avail is not None and req is not None and avail > req
            done = (st.get("details_complete_through") is not None and not pend.get(o) and not gopen.get(o) and not partial)
            out[o] = dict(st, pending=pend.get(o, 0), gaps=gaps.get(o, 0), gaps_open=gopen.get(o, 0),
                          coverage="partial" if partial else "full", complete=bool(done))
        return out
