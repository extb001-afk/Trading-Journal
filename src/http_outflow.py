from __future__ import annotations
import bf_engine
import logs, paths, statefile
import copy
import depaddr
import os
import re
import salelink
import settings_store
import time
import urllib.request
import web_ctx
import xchain_match
import xfer_match
from datetime import datetime
from view_builder import StateBuilder
from timeutil import KST
import logging

log = logging.getLogger('tj-web')


class OutflowMixin:

    EX_KEYS = {"업비트": "upbit", "바이낸스": "binance", "바이빗": "bybit", "okx": "okx", "쿠코인": "kucoin",
               "게이트": "gate", "게이트아이오": "gate", "gate.io": "gate", "빗썸": "bithumb",
               "하이퍼리퀴드": "hyperliquid", "Hyperliquid": "hyperliquid", "코인베이스": "coinbase", "Coinbase": "coinbase"}

    @classmethod
    def _exchange_key(cls, v) -> str:
        s = str(v or "").strip()
        k = s.lower()
        if k in {"upbit", "binance", "bybit", "okx", "kucoin", "gate", "bithumb", "hyperliquid", "coinbase"}:
            return k
        return cls.EX_KEYS.get(s) or cls.EX_KEYS.get(k) or s

    def _wd_dest_register(self, body: dict):
        if not self._write_guard(need_json=False):
            return
        a = xfer_match.norm_addr(body.get("address"))
        cands = getattr(web_ctx.builder(), "_wd_dest_unknown", None)
        if cands is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "출금 목적지 후보를 계산하는 중 — 잠시 뒤 다시 시도하세요"})
        u9 = cands.get(a)
        if not u9:
            return self._send(404, {"ok": False, "error": "거래소 출금 목적지 후보에 없는 주소"})
        alias = str(body.get("alias") or "").strip()
        if len(alias) > 40 or any(ord(c) < 32 for c in alias):
            return self._send(400, {"ok": False, "error": "지갑 이름은 40자 이내 한 줄"})
        chains = sorted({c9 for c9 in (depaddr.chain_of(n9, None, a) for n9 in (u9.get("networks") or [])) if c9})
        import wallet_register
        if not chains:
            chains, bad_reply = self._reg_chains_pick(a, body)
            if bad_reply:
                return self._send(*bad_reply)
        try:
            reg = wallet_register.register_wallet(a, chains, alias or f"{a[:6]}…{a[-4:]}", source="exchange_withdraw", idempotent=True,
                                                  confirm=body.get("confirm") is True)
        except wallet_register.NeedConfirm as e:
            return self._send(409, {"ok": False, "needConfirm": True, "error": str(e)})
        except (ValueError, OSError) as e:
            if isinstance(e, OSError):
                return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
            return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {logs.safe_err(e)}"})
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
        web_ctx.builder().kick_refresh()
        apply9 = reg.get("apply") or {}
        return self._send(200, {"ok": True, "address": a, "chains": reg.get("chains") or chains, "restartNeeded": not apply9.get("runner"),
                                "warn": reg.get("warn") or ""})

    def _reg_chains_pick(self, a: str, body: dict):
        if not a.startswith("0x"):
            return ["sol"], None
        allowed_chains = [k for k, _n in settings_store.evm_chains(settings_store.read_config_raw())]
        body_chains = body.get("chains")
        if isinstance(body_chains, list) and 0 < len(body_chains) <= 12 and all(isinstance(c, str) and c in allowed_chains for c in body_chains):
            return sorted(set(body_chains)), None
        if body_chains is not None:
            return None, (400, {"ok": False, "error": "chains 는 고를 수 있는 EVM 체인 이름 배열(1~12)"})
        suggest = [c for c in ("eth", "bsc", "base", "arbitrum") if c in allowed_chains] or allowed_chains[:4]
        return None, (409, {"ok": False, "needChains": True, "chains": suggest, "options": allowed_chains,
                            "error": "어느 체인의 지갑인지 몰라요 — 등록할 체인을 확인해 주세요"})

    def _flow_register(self, body: dict):
        if not self._write_guard():
            return
        a = xchain_match.norm(str(body.get("address") or "").strip())
        cands = getattr(web_ctx.builder(), "_flow_recips", None)
        if cands is None:
            web_ctx.builder().kick_refresh()
            return self._send(503, {"ok": False, "error": "돈 흐름을 계산하는 중 — 잠시 뒤 다시 시도하세요"})
        u9 = cands.get(a)
        if not u9 or u9.get("level") not in ("high", "mid"):
            return self._send(404, {"ok": False, "error": "돈 흐름 추적에서 내 지갑 근거가 있는 상대 주소가 아니에요"})
        if not isinstance(body.get("alias") or "", str):
            return self._send(400, {"ok": False, "error": "alias 는 문자열"})
        alias = str(body.get("alias") or "").strip()
        if len(alias) > 24 or any(ord(c) < 32 for c in alias):
            return self._send(400, {"ok": False, "error": "지갑 이름은 24자 이내 한 줄"})
        chains = sorted(c9 for c9 in (u9.get("chains") or ()) if isinstance(c9, str) and re.fullmatch(r"[a-z0-9_-]{1,24}", c9))
        import wallet_register
        if not chains:
            chains, bad_reply = self._reg_chains_pick(a, body)
            if bad_reply:
                return self._send(*bad_reply)
        try:
            reg = wallet_register.register_wallet(a, chains, alias or f"{a[:6]}…{a[-4:]}", source="flow_trace", idempotent=True,
                                                  confirm=body.get("confirm") is True)
        except wallet_register.NeedConfirm as e:
            return self._send(409, {"ok": False, "needConfirm": True, "error": str(e)})
        except (ValueError, OSError) as e:
            if isinstance(e, OSError):
                return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
            return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {logs.safe_err(e)}"})
        log.info("flow_register: %s %s (목적지 %s)", a, chains, ",".join(sorted(u9.get("dests") or ()))[:200])
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
        web_ctx.builder().kick_refresh()
        apply9 = reg.get("apply") or {}
        return self._send(200, {"ok": True, "address": a, "chains": reg.get("chains") or chains, "restartNeeded": not apply9.get("runner"),
                                "note": reg.get("note") or "", "warn": reg.get("warn") or ""})

    def _outflow_resolve(self, body: dict):
        if not self._write_guard():
            return
        a = str(body.get("address") or "").strip()
        a = a.lower() if a.startswith("0x") else a
        if body.get("op") == "salealert":
            if not isinstance(body.get("on"), bool):
                return self._send(400, {"ok": False, "error": "on 은 true/false"})
            pr9 = web_ctx.builder().prefs()
            pr9["sale_cand_alert"] = bool(body["on"])
            statefile.atomic_write_json(paths.state("ui_prefs.json"), pr9)
            with web_ctx.builder().lock:
                web_ctx.builder().cache = None
            return self._send(200, {"ok": True, "on": pr9["sale_cand_alert"]})
        if body.get("op") is not None:
            return self._outflow_op(a, body)
        verdict = str(body.get("verdict") or "")
        if verdict not in ("own", "exchange", "external", "clear"):
            return self._send(400, {"ok": False, "error": "verdict 는 own|exchange|external|clear"})
        if not isinstance(body.get("memo") or "", str):
            return self._send(400, {"ok": False, "error": "메모는 문자열"})
        memo = str(body.get("memo") or "").strip()
        if len(memo) > 200 or any(ord(c) < 32 for c in memo):
            return self._send(400, {"ok": False, "error": "메모는 200자 이내 한 줄"})
        ch_in = body.get("chains")
        if ch_in is not None and (not isinstance(ch_in, list) or len(ch_in) > 12
                                  or any(not isinstance(c, str) or not re.fullmatch(r"[a-z0-9_-]{1,24}", c) for c in ch_in)):
            return self._send(400, {"ok": False, "error": "chains 는 체인 이름 배열(≤12)"})
        for f9 in ("alias", "exchange", "category"):
            if body.get(f9) is not None and not isinstance(body.get(f9), str):
                return self._send(400, {"ok": False, "error": f"{f9} 는 문자열"})
        if len(str(body.get("alias") or "")) > 40:
            return self._send(400, {"ok": False, "error": "지갑 이름은 40자 이내"})
        dests = getattr(web_ctx.builder(), "_outflow_dests", None)
        if dests is None:
            web_ctx.builder().build()
            dests = getattr(web_ctx.builder(), "_outflow_dests", None) or {}
        cur = web_ctx.builder().outflow_decisions()
        if a not in dests and a not in cur:
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        ent = {"verdict": verdict, "ts": int(time.time())}
        restart = False
        apply9 = None
        exw9 = a.startswith("wd:") or (a in (getattr(web_ctx.builder(), "_outflow_exwd", None) or set()) and not (body.get("chains") or dests.get(a)))
        if verdict == "own" and exw9:
            ent.update({"alias": str(body.get("alias") or "").strip() or "내 지갑(추적 밖)", "chains": []})
        elif verdict == "own":
            chains = [str(c) for c in (body.get("chains") or dests.get(a) or [])][:12]
            alias = str(body.get("alias") or "").strip() or f"{a[:6]}…{a[-4:]}"
            import chain_registry as _cr9
            nx9 = _cr9.key_parse(a)
            if nx9 and (nx9[0] not in _cr9.SPECS or not set(chains) <= {nx9[0]} or nx9[1].startswith("bw")):
                nx9 = None
            import wallet_register
            try:
                if nx9:
                    try:
                        r9 = wallet_register.register_chain_wallet(nx9[0], address=_cr9.display_owner(*nx9), label=alias[:24], source="outflow")
                        reg = {"chains": [nx9[0]], "apply": r9.get("apply") or {}}
                    except ValueError as e9:
                        if "이미 등록된" not in str(e9):
                            raise
                        reg = {"chains": [nx9[0]], "apply": wallet_register.apply_info(), "note": "이미 등록된 주소·체인"}
                else:
                    reg = wallet_register.register_wallet(a, chains, alias, source="outflow", idempotent=True, confirm=body.get("confirm") is True)
            except wallet_register.NeedConfirm as e:
                return self._send(409, {"ok": False, "needConfirm": True, "error": str(e)})
            except (ValueError, OSError) as e:
                if isinstance(e, OSError):
                    return self._send(400, {"ok": False, "error": "지갑 등록 실패: 설정 파일을 읽거나 저장할 수 없습니다"})
                return self._send(400, {"ok": False, "error": f"지갑 등록 실패: {logs.safe_err(e)}"})
            ent.update({"alias": alias, "chains": reg.get("chains") or chains})
            apply9 = reg.get("apply") or {}
            restart = not apply9.get("runner")
        elif verdict == "exchange":
            ex = self._exchange_key(body.get("exchange"))
            if not ex or len(ex) > 24 or any(c in ex for c in "<>\"'`") or any(ord(c) < 32 for c in ex):
                return self._send(400, {"ok": False, "error": "exchange(거래소 이름, 1~24자) 필요"})
            ent.update({"exchange": ex, "chains": [] if a.startswith("wd:") else [str(c) for c in (body.get("chains") or dests.get(a) or [])][:12]})
        elif verdict == "external":
            cat = str(body.get("category") or "")
            if cat not in StateBuilder.OUTFLOW_CATEGORIES:
                return self._send(400, {"ok": False, "error": "category 는 " + " | ".join(StateBuilder.OUTFLOW_CATEGORIES)})
            ent["category"] = cat
        d = statefile.read_json(web_ctx.builder().OUTFLOW_PATH, {}) if os.path.exists(web_ctx.builder().OUTFLOW_PATH) else {}
        if not isinstance(d, dict):
            d = {}
        decs = d.setdefault("decisions", {})
        if not isinstance(decs, dict):
            decs = d["decisions"] = {}
        old9 = copy.deepcopy(decs.get(a)) if isinstance(decs.get(a), dict) else None
        prev0 = decs.get(a) if isinstance(decs.get(a), dict) else {}
        if "memo" not in body and prev0.get("memo"):
            memo = str(prev0["memo"])
        if memo:
            ent["memo"] = memo
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("links"), list) and prev0["links"]:
            ent["links"] = prev0["links"]
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("excludeLegs"), list) and prev0["excludeLegs"]:
            ent["excludeLegs"] = prev0["excludeLegs"]
        if verdict == "external" and prev0.get("verdict") == "external" and isinstance(prev0.get("dismiss"), list) and prev0["dismiss"]:
            ent["dismiss"] = prev0["dismiss"]
        if verdict == "clear":
            st9 = (getattr(web_ctx.builder(), "_outflow_status", None) or {}).get(a)
            if not prev0.get("verdict") and (st9 in ("exchange_matched", "returned", "bridge_matched", "bridge_untracked")
                                             or a in (getattr(web_ctx.builder(), "_outflow_autorows", None) or set())):
                ent = {"verdict": "clear", "noAuto": True, "ts": ent["ts"]}
                if memo:
                    ent["memo"] = memo
                decs[a] = ent
            elif memo:
                ent = decs[a] = {"memo": memo, "ts": ent["ts"]}
            else:
                decs.pop(a, None)
                ent = None
        else:
            prev = decs.get(a) or {}
            if {k: v for k, v in prev.items() if k != "ts"} == {k: v for k, v in ent.items() if k != "ts"}:
                ent["ts"] = prev.get("ts", ent["ts"])
            decs[a] = ent
        d["version"] = 1
        d["updated"] = int(time.time())
        statefile.atomic_write_json(web_ctx.builder().OUTFLOW_PATH, d)
        self._of_after_save(a, old9, decs.get(a))
        return self._send(200, {"ok": True, "address": a, "decision": decs.get(a), "row": web_ctx.bcall("of_row_patch", a, decs.get(a), old9),
                                "restartNeeded": restart, "apply": apply9,
                                "note": ("config 등록 완료 — tj-evm·tj-sol·tj-bsc·tj-core 재기동 뒤 백필·내 지갑 이동으로 재분류" if restart
                                         else ("등록 완료 — 약 30초 안에 수집기·core 가 자동으로 다시 시작해 백필·재분류" if (verdict == "own" and not exw9)
                                               else ("tj-core 가 60초 안에 재분류(거래소 입금 원가 승계)" if verdict == "exchange" else "저장됨")))})

    def _outflow_op(self, a: str, body: dict):
        op = body.get("op")
        if op not in ("memo", "link", "unlink", "exclude", "include", "ret", "dismiss", "undismiss"):
            return self._send(400, {"ok": False, "error": "op 는 memo | link | unlink | exclude | include | ret | dismiss | undismiss"})
        dests = getattr(web_ctx.builder(), "_outflow_dests", None)
        if dests is None:
            web_ctx.builder().build()
            dests = getattr(web_ctx.builder(), "_outflow_dests", None) or {}
        d = statefile.read_json(web_ctx.builder().OUTFLOW_PATH, {}) if os.path.exists(web_ctx.builder().OUTFLOW_PATH) else {}
        if not isinstance(d, dict):
            d = {}
        decs = d.setdefault("decisions", {})
        if not isinstance(decs, dict):
            decs = d["decisions"] = {}
        if not a or (a not in dests and a not in decs):
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        old9 = copy.deepcopy(decs.get(a)) if isinstance(decs.get(a), dict) else None
        ent = dict(decs.get(a)) if isinstance(decs.get(a), dict) else {}
        now9 = int(time.time())
        if op == "ret":
            if not isinstance(body.get("on"), bool):
                return self._send(400, {"ok": False, "error": "on 은 true/false"})
            if ent.get("verdict") not in (None, "clear"):
                return self._send(409, {"ok": False, "error": "이미 판정한 목적지예요 — 판정을 되돌린 뒤 정리해 주세요"})
            if body["on"]:
                ent.update(verdict="clear", ret=True, ts=now9)
            else:
                ent.pop("ret", None)
                if ent.get("verdict") == "clear" and not ent.get("noAuto"):
                    ent.pop("verdict", None)
        elif op == "memo":
            if not isinstance(body.get("memo"), str):
                return self._send(400, {"ok": False, "error": "메모는 문자열"})
            memo = body["memo"].strip()
            if len(memo) > 200 or any(ord(c) < 32 for c in memo):
                return self._send(400, {"ok": False, "error": "메모는 200자 이내 한 줄"})
            if memo:
                ent["memo"] = memo
                ent.setdefault("ts", now9)
            else:
                ent.pop("memo", None)
        elif op in ("dismiss", "undismiss"):
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 제안을 정리할 수 있어요"})
            k9 = body.get("key")
            cur9 = [str(x9) for x9 in (ent.get("dismiss") or []) if isinstance(x9, str)]
            if not isinstance(k9, str) or not k9 or len(k9) > 300:
                return self._send(400, {"ok": False, "error": "key 는 후보 키 문자열"})
            if op == "dismiss":
                if k9 not in (getattr(web_ctx.builder(), "_of_cands", None) or {}):
                    return self._send(400, {"ok": False, "error": "지금 후보에 없는 유입이에요"})
                cur9 = [x9 for x9 in cur9 if x9 != k9] + [k9]
            else:
                if k9 not in cur9:
                    return self._send(400, {"ok": False, "error": "뺀 제안이 아니에요"})
                cur9 = [x9 for x9 in cur9 if x9 != k9]
            if len(cur9) > 200:
                return self._send(400, {"ok": False, "error": "아님은 200개까지"})
            if cur9:
                ent["dismiss"] = cur9
            else:
                ent.pop("dismiss", None)
        elif op in ("exclude", "include"):
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 참가금 레그를 고를 수 있어요"})
            k9 = body.get("key")
            cur9 = [x9 for x9 in (ent.get("excludeLegs") or []) if isinstance(x9, (str, dict))]
            if not isinstance(k9, str) or not k9 or len(k9) > 300:
                return self._send(400, {"ok": False, "error": "key 는 레그 키 문자열"})
            ek9 = lambda x9: str(x9.get("key") if isinstance(x9, dict) else x9)
            if op == "exclude":
                if k9 not in ((getattr(web_ctx.builder(), "_outflow_legkeys", None) or {}).get(a) or set()):
                    return self._send(400, {"ok": False, "error": "이 목적지로 보낸 레그가 아니에요"})
                mt9 = ((getattr(web_ctx.builder(), "_outflow_legmeta", None) or {}).get(a) or {}).get(k9) or (None, None)
                cur9 = [x9 for x9 in cur9 if ek9(x9) != k9] + [{"key": k9, "asset": mt9[0], "qb": mt9[1]}]
            else:
                if k9 not in [ek9(x9) for x9 in cur9]:
                    return self._send(400, {"ok": False, "error": "참가금에서 뺀 레그가 아니에요"})
                cur9 = [x9 for x9 in cur9 if ek9(x9) != k9]
            if len(cur9) > 200:
                return self._send(400, {"ok": False, "error": "참가금 아님은 200개까지"})
            if cur9:
                ent["excludeLegs"] = cur9
            else:
                ent.pop("excludeLegs", None)
        else:
            if ent.get("verdict") != "external":
                return self._send(409, {"ok": False, "error": "외부 유출로 확정한 목적지만 받은 것과 연결할 수 있어요"})
            links = [l9 for l9 in (ent.get("links") or []) if isinstance(l9, dict)]
            if op == "unlink":
                k9 = body.get("key")
                if not isinstance(k9, str) or k9 not in {str(l9.get("key")) for l9 in links}:
                    return self._send(400, {"ok": False, "error": "이 목적지에 연결되지 않은 유입"})
                links = [l9 for l9 in links if str(l9.get("key")) != k9]
            else:
                req9 = body.get("links")
                if not isinstance(req9, list) or not 1 <= len(req9) <= 20 or not all(isinstance(x9, dict) for x9 in req9):
                    return self._send(400, {"ok": False, "error": "links 는 [{kind, key}] 1~20개"})
                cands = getattr(web_ctx.builder(), "_of_cands", None) or {}
                first9 = (getattr(web_ctx.builder(), "_outflow_first", None) or {}).get(a)
                taken9 = {str(l9.get("key")): a9 for a9, v9 in decs.items() if a9 != a and isinstance(v9, dict)
                          for l9 in (v9.get("links") or []) if isinstance(l9, dict)}
                for x9 in req9:
                    kind9, k9 = x9.get("kind"), x9.get("key")
                    if kind9 not in StateBuilder.OF_LINK_KINDS or not isinstance(k9, str) or len(k9) > 300:
                        return self._send(400, {"ok": False, "error": "kind 는 refund | tokens · key 는 문자열"})
                    c9 = cands.get(k9)
                    if not c9:
                        return self._send(400, {"ok": False, "error": "연결 후보에 없는 유입(내 지갑·거래소로 받은 것만)"})
                    if first9 is None or int(c9["ts"]) < int(first9):
                        return self._send(400, {"ok": False, "error": "보낸 시각 이전에 받은 유입은 연결할 수 없어요"})
                    if (kind9 == "refund") != bool(c9.get("stable")):
                        return self._send(400, {"ok": False, "error": "환불은 스테이블 유입만, 세일 토큰은 스테이블이 아닌 유입만"})
                    own9 = (getattr(web_ctx.builder(), "_of_claims", None) or {}).get(k9)
                    if own9 and not any(isinstance(l0, dict) and str(l0.get("key")) == own9[1]
                                        for l0 in ((decs.get(own9[0]) or {}).get("links") or [])):
                        own9 = None
                    if k9 in taken9 or (own9 and own9[0] != a):
                        return self._send(409, {"ok": False, "error": "다른 보낸 내역에 이미 연결된 유입"})
                    alias9 = {k9} | ({own9[1]} if own9 else set())
                    links = [l9 for l9 in links if str(l9.get("key")) not in alias9]
                    links.append({"kind": kind9, "key": k9, "asset": c9.get("asset"), "qb": c9.get("qb"), "sym": c9.get("sym"),
                                  "qty": c9.get("qty"), "ts": int(c9["ts"]), "where": c9.get("where"), "tx": c9.get("ref"), "lts": now9})
                if len(links) > StateBuilder.OF_LINK_MAX:
                    return self._send(400, {"ok": False, "error": f"한 목적지에 연결은 {StateBuilder.OF_LINK_MAX}개까지"})
            if links:
                ent["links"] = links
            else:
                ent.pop("links", None)
        if set(ent) <= {"ts"}:
            decs.pop(a, None)
            ent = None
        else:
            decs[a] = ent
        d["version"] = 1
        d["updated"] = now9
        statefile.atomic_write_json(web_ctx.builder().OUTFLOW_PATH, d)
        self._of_after_save(a, old9, ent)
        return self._send(200, {"ok": True, "address": a, "decision": ent, "row": web_ctx.bcall("of_row_patch", a, ent, old9)})

    def _of_after_save(self, a, old, new):
        if web_ctx.bcall("of_memo_only", a, old, new) and web_ctx.bcall("mpatch", {"of_memo"}):
            try:
                if salelink.dest_name(a, old if isinstance(old, dict) else {}) != salelink.dest_name(a, new if isinstance(new, dict) else {}):
                    web_ctx.builder().soft_invalidate()
            except Exception:   # noqa: BLE001 [fallback]
                web_ctx.builder().soft_invalidate()
            return
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None

    OF_CAND_CAP = 300

    OF_CAND_CAP_STABLE = 100

    def _send_outflow_cands(self, query):
        qs = urllib.parse.parse_qs(query)
        a = (qs.get("address") or [""])[0].strip()
        a = a.lower() if a.startswith("0x") else a
        q9 = (qs.get("q") or [""])[0].strip().lower()
        all9 = (qs.get("all") or [""])[0] == "1"
        spam9 = (qs.get("spam") or [""])[0] == "1"
        if not a or len(a) > 200 or len(q9) > 80:
            return self._send(400, {"ok": False, "error": "address 필요 · q 는 80자 이내"})
        web_ctx.builder().snapshot()
        first9 = (getattr(web_ctx.builder(), "_outflow_first", None) or {}).get(a)
        if first9 is None:
            return self._send(404, {"ok": False, "error": "보낸 내역에 없는 목적지 주소"})
        first9 = int(first9)
        to9 = None if all9 else first9 + StateBuilder.OF_CAND_WINDOW
        decs = web_ctx.builder().outflow_decisions()
        mine9 = {str(l9.get("key")): l9.get("kind") for l9 in ((decs.get(a) or {}).get("links") or []) if isinstance(l9, dict)} \
            if isinstance(decs.get(a), dict) else {}
        taken9 = {str(l9.get("key")) for a9, v9 in decs.items() if a9 != a and isinstance(v9, dict)
                  for l9 in (v9.get("links") or []) if isinstance(l9, dict)}
        ret9 = (getattr(web_ctx.builder(), "_outflow_rettx", None) or {}).get(a) or set()
        fw9 = (getattr(web_ctx.builder(), "_outflow_from_w", None) or {}).get(a) or set()
        dis9 = {str(x9) for x9 in (((decs.get(a) or {}) if isinstance(decs.get(a), dict) else {}).get("dismiss") or []) if isinstance(x9, str)}
        cl9 = getattr(web_ctx.builder(), "_of_claims", None) or {}
        where = web_ctx.builder()._of_where
        quar9 = getattr(web_ctx.builder(), "_risk_quarantined", None) or set()
        out, quar_n = [], 0
        for c9 in (getattr(web_ctx.builder(), "_of_cands", None) or {}).values():
            own9 = cl9.get(c9["key"])
            ts9 = int(c9["ts"])
            if ts9 < first9 or (to9 is not None and ts9 > to9) or c9["key"] in taken9 or (own9 and own9[0] != a):
                continue
            x9 = {"key": c9["key"], "sym": c9["sym"], "qty": c9["qty"], "ts": ts9,
                  "t": datetime.fromtimestamp(ts9, KST).strftime("%Y-%m-%d %H:%M"), "where": where(c9.get("where") or ""),
                  "chain": c9.get("chain") or "", "tx": c9.get("ref") or "", "stable": bool(c9.get("stable")),
                  "sale": bool(c9.get("sale")), "fromDest": str(c9.get("ref") or "").lower() in ret9, "quar": c9.get("gid") in quar9,
                  "linked": mine9.get(c9["key"]) or (own9[2] if own9 and own9[0] == a else None),
                  "fromSender": str(c9.get("where") or "") in fw9, "dismissed": c9["key"] in dis9}
            if q9 and q9 not in (x9["sym"] + " " + x9["where"] + " " + x9["tx"] + " " + x9["t"]).lower():
                continue
            if x9["quar"] and not spam9 and not x9["linked"]:
                quar_n += 1
                continue
            out.append(x9)
        out.sort(key=lambda x9: (x9["stable"], x9["dismissed"], not x9["fromSender"], x9["ts"] - first9))
        tok9 = [x9 for x9 in out if not x9["stable"]]
        st9 = [x9 for x9 in out if x9["stable"]]
        shown = tok9[:self.OF_CAND_CAP] + st9[:self.OF_CAND_CAP_STABLE]
        self._send(200, {"ok": True, "address": a, "firstTs": first9, "total": len(out), "totalTok": len(tok9), "totalStable": len(st9),
                         "shown": len(shown), "quarN": quar_n, "window": {"from": first9, "to": to9, "all": all9}, "spam": spam9, "q": q9,
                         "cands": shown})

    def _backfill_request(self, body: dict):
        if not self._write_guard(origin_err="출처(Origin) 확인 실패"):
            return
        path = StateBuilder.BF_REQ_PATH
        cur = statefile.read_json(path, {}) if os.path.exists(path) else {}
        if not isinstance(cur, dict):
            cur = {}
        if body.get("clear"):
            if os.path.exists(path):
                os.remove(path)
            return self._send(200, {"ok": True, "request": {}})
        secs = set(web_ctx.builder()._backfill_since_view()["sections"]) | {"okx", "binance", "bybit", "kucoin", "gate", "bithumb", "coinbase"}
        today = datetime.now(KST).strftime("%Y-%m-%d")

        def _d(v):
            v = str(v or "").strip()
            if not re.fullmatch(r"20\d\d-\d\d-\d\d", v) or not bf_engine.parse_date_ts(v):
                raise ValueError("날짜는 YYYY-MM-DD")
            if v > today or v < "2015-01-01":
                raise ValueError("날짜 범위(2015-01-01 ~ 오늘)")
            return v
        try:
            new = dict(cur)
            if body.get("since"):
                v = _d(body["since"])
                new["since"] = min(v, cur["since"]) if cur.get("since") else v
            per_in = body.get("per") or {}
            if not isinstance(per_in, dict):
                raise ValueError("per 는 {섹션: 날짜}")
            per = dict(new.get("per") or {})
            for k, v in per_in.items():
                if k not in secs:
                    raise ValueError(f"모르는 섹션: {str(k)[:20]}")
                v = _d(v)
                per[k] = min(v, per[k]) if per.get(k) else v
            if per:
                new["per"] = per
            if not new.get("since") and not new.get("per"):
                raise ValueError("since 또는 per 필요")
        except ValueError as e:
            return self._send(400, {"ok": False, "error": logs.safe_err(e)})
        new["updated"] = int(time.time())
        statefile.atomic_write_json(path, new)
        with web_ctx.builder().lock:
            web_ctx.builder().cache = None
        return self._send(200, {"ok": True, "request": new,
                                "note": "수집기가 다음 주기(≤1분)에 옛 구간을 가져오고, 끝나면 tj-core 가 원장을 자동 재구축합니다(≈4분 소비 정지)"})
