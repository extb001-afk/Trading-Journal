from __future__ import annotations

import os
import re

import address_codec
import logs
import paths
import settings_store
import statefile

__all__ = ["wallet_list", "add_wallet", "add_wallets", "remove_wallet", "rename_wallet", "addr_key", "cap_error", "MAX_ADDRESSES", "MAX_BATCH",
           "chain_wallet_list", "validate_chain_wallet", "add_chain_wallet", "remove_chain_wallet", "rename_chain_wallet",
           "perp_list", "add_perp", "remove_perp", "MAX_PERP"]


MAX_ADDRESSES = 500


def cap_error(n_now: int) -> str:
    return (f"지갑은 최대 {MAX_ADDRESSES}개까지 등록할 수 있습니다 (지금 {n_now}개) — 안 쓰는 주소를 목록에서 빼면 그만큼 더 넣을 수 있어요."
            " 이미 등록된 주소에 체인을 더하는 건 개수와 상관없이 됩니다")


def _label_ok(label: str) -> str:
    s = (label or "").strip()
    if not s or len(s) > 24 or any(ord(c) < 32 for c in s) or any(c in s for c in "<>\"'`"):
        raise ValueError("이름은 1~24자, 꺾쇠·따옴표 없이 입력하세요")
    return s


def wallet_list(cfg: dict) -> list:
    by = {}
    for w in cfg.get("wallets") or []:
        t = w.get("type", "evm")
        a = w.get("address") or ""
        key = a if t == "sol" else a.lower()
        e = by.setdefault(key, {"address": a if t == "sol" else a.lower(), "kind": "sol" if t == "sol" else "evm",
                                "label": w.get("label") or "", "chains": []})
        ch = "sol" if t == "sol" else w.get("chain") or "?"
        if ch not in e["chains"]:
            e["chains"].append(ch)
        if not e["label"] and w.get("label"):
            e["label"] = w["label"]
    return list(by.values())


def add_wallet(address: str, label: str, chains: list) -> dict:
    kind, addr, note = address_codec.validate_address(address)
    label = _label_ok(label)
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        wallets = cfg.setdefault("wallets", [])
        keys9 = {addr_key(w) for w in wallets}
        if addr not in keys9 and len(keys9) >= MAX_ADDRESSES:
            raise ValueError(cap_error(len(keys9)))
        have = {(w.get("type", "evm"), w.get("chain"), (w.get("address") or "") if w.get("type") == "sol"
                 else (w.get("address") or "").lower()) for w in wallets}
        added = []
        if kind == "sol":
            ent = ("sol", "sol", addr)
            if ent not in have:
                wallets.append({"type": "sol", "chain": "sol", "address": addr, "label": label})
                added.append("sol")
        else:
            allowed = {k for k, _ in settings_store.evm_chains(cfg)}
            sel = [c for c in (chains or []) if c in allowed]
            if not sel:
                raise ValueError("체인을 하나 이상 고르세요")
            for c in sel:
                t = "bsc_rpc" if c == "bsc" else "evm"
                if (t, c, addr) in have:
                    continue
                wallets.append({"type": t, "chain": c, "address": addr, "label": label})
                added.append(c)
        if not added:
            raise ValueError("이미 같은 체인으로 등록된 주소입니다")
        settings_store.write_config_raw(cfg)
    return {"kind": kind, "address": addr, "chains": added, "note": note}


MAX_BATCH = 50


def addr_key(w: dict) -> str:
    a = w.get("address") or ""
    return a if w.get("type") == "sol" else a.lower()


def _auto_label(kind: str, n: int, used: set) -> str:
    stem = "Solana" if kind == "sol" else "지갑"
    while f"{stem} {n}" in used:
        n += 1
    return f"{stem} {n}"


def add_wallets(addresses, chains: list) -> list:
    if isinstance(addresses, str):
        addresses = address_codec.split_addresses(addresses)
    if not isinstance(addresses, list) or not addresses:
        raise ValueError("추가할 주소가 없습니다")
    if len(addresses) > MAX_BATCH:
        raise ValueError(f"한 번에 최대 {MAX_BATCH}개까지 추가할 수 있습니다 (지금 {len(addresses)}개) — {MAX_BATCH}개씩 나눠서 여러 번 넣어 주세요"
                         f" (전체 최대 {MAX_ADDRESSES}개)")
    if not isinstance(chains, list) or len(chains) > 40 or any(not isinstance(c, str) for c in chains):
        raise ValueError("chains 는 체인 이름 배열입니다")
    why = address_codec.secret_like(addresses)
    if why:
        raise ValueError(why)
    out = []
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        wallets = cfg.setdefault("wallets", [])
        if not isinstance(wallets, list):
            raise ValueError("config.json wallets 형식 오류")
        allowed = {k for k, _ in settings_store.evm_chains(cfg)}
        sel = [c for c in dict.fromkeys(chains) if c in allowed]
        key_of = addr_key
        have = {(w.get("type", "evm"), w.get("chain"), key_of(w)) for w in wallets}
        labels = {}
        for w in wallets:
            if w.get("label") and key_of(w) not in labels:
                labels[key_of(w)] = w["label"]
        used = {w.get("label") for w in wallets if w.get("label")}
        n_addr = len({key_of(w) for w in wallets})
        seen = set()
        wrote = False
        for raw in addresses:
            r = {"input": raw if isinstance(raw, str) else "", "chains": []}
            out.append(r)
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 128:
                r.update(status="invalid", error="주소 형식이 아닙니다")
                continue
            try:
                kind, addr, note = address_codec.validate_address(raw)
            except ValueError as e:
                r.update(status="invalid", error=logs.safe_err(e))
                continue
            r.update(kind=kind, address=addr, note=note)
            if addr in seen:
                r.update(status="dup", error="이번 입력에 같은 주소가 또 있습니다")
                continue
            seen.add(addr)
            known = addr in labels or any(k == addr for _t, _c, k in have)
            if kind == "sol":
                todo = [] if any(t == "sol" and k == addr for t, _c, k in have) else ["sol"]
            else:
                if not sel:
                    r.update(status="error", error="체인을 하나 이상 고르세요")
                    continue
                todo = [c for c in sel if ("bsc_rpc" if c == "bsc" else "evm", c, addr) not in have]
            if not todo:
                r.update(status="exists", error="이미 같은 체인으로 등록된 주소입니다", label=labels.get(addr) or "")
                continue
            if not known:
                if n_addr >= MAX_ADDRESSES:
                    r.update(status="error", error=cap_error(n_addr))
                    continue
                n_addr += 1
                labels[addr] = _auto_label(kind, n_addr, used)
                used.add(labels[addr])
            label = labels.get(addr) or _auto_label(kind, n_addr, used)
            for c in todo:
                t = "sol" if kind == "sol" else ("bsc_rpc" if c == "bsc" else "evm")
                wallets.append({"type": t, "chain": c, "address": addr, "label": label})
                have.add((t, c, addr))
            r.update(status="added", chains=todo, label=label)
            wrote = True
        if wrote:
            settings_store.write_config_raw(cfg)
    return out


def remove_wallet(address: str) -> int:
    a = (address or "").strip()
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        before = len(cfg.get("wallets") or [])
        cfg["wallets"] = [w for w in (cfg.get("wallets") or [])
                          if not ((w.get("address") or "") == a or (w.get("type") != "sol"
                                  and (w.get("address") or "").lower() == a.lower()))]
        n = before - len(cfg["wallets"])
        if n:
            settings_store.write_config_raw(cfg)
    return n


def rename_wallet(address: str, label: str) -> int:
    label = _label_ok(label)
    a = (address or "").strip()
    n = 0
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        for w in cfg.get("wallets") or []:
            wa = w.get("address") or ""
            if wa == a or (w.get("type") != "sol" and wa.lower() == a.lower()):
                w["label"] = label
                n += 1
        if n:
            settings_store.write_config_raw(cfg)
    return n


def chain_wallet_list(cfg: dict) -> list:
    import chain_registry as reg
    return [{"chain": r["chain"], "name": reg.display_name(r["chain"]), "key": r["key"], "display": r["display"], "label": r["label"],
             "mode": r["mode"], "available": reg.available(r["chain"])} for r in reg.wallets(cfg)]


def validate_chain_wallet(chain: str, address=None, mode: str = "address", descriptor=None, gap_limit=20, network: str = "mainnet",
                          script_type=None) -> dict:
    import address_codec as ac
    import chain_registry as reg
    if not reg.is_nonevm(chain):
        raise ValueError("지원하지 않는 체인이에요")
    raw = [x for x in (address, descriptor) if isinstance(x, str)]
    strip9 = [re.sub(r"^\s*(0x[0-9a-fA-F]{64}|-?\d{1,3}[:_][0-9a-fA-F]{64})\s*$", "", x) if chain in ("sui", "ton") else x for x in raw]
    why = address_codec.secret_like(strip9) or (ac.PRIVATE_HINT if any(ac.has_private_material(x) for x in strip9) else "") \
        or (ac.PRIVATE_HINT if any("privkey" in x.lower() for x in raw) else "")
    if why:
        raise ValueError(why)
    if not reg.available(chain):
        raise ValueError(f"{reg.display_name(chain)} 지갑 수집은 준비 중이에요 — 수집기가 들어간 판부터 등록할 수 있어요")
    if chain == "btc":
        ent = {"chain": "btc", "network": network, "mode": mode}
        if mode == "descriptor":
            d9 = str(descriptor or "").strip()
            if re.fullmatch(r"[xyz]pub[1-9A-HJ-NP-Za-km-z]{100,115}", d9):
                import btc_descriptor
                st9 = str(script_type) if script_type in ("pkh", "sh(wpkh)", "wpkh", "tr") else None
                d9 = btc_descriptor.descriptor_from_xpub(d9, st9, network)
            ent.update(descriptor=d9, gap_limit=gap_limit)
        else:
            ent.update(mode="address", address=str(address or ""))
        src = reg.btc_source(ent, network)
        if src["mode"] == "descriptor":
            ent["descriptor"] = src["descriptor"]
        else:
            ent["address"] = src["address"]
        return {"entry": ent, "key": src["key"], "display": src["display"],
                "note": "이 주소만 추적해요 — 잔돈·다른 받는 주소는 빠질 수 있어요(HD 지갑 전체는 디스크립터로)" if src["mode"] == "address"
                else "받는 주소·잔돈 주소를 공개 키로 찾아요(개인 키 없음 · 화면엔 가려 보여요)"}
    key = reg.owner_key(chain, str(address or ""), network)
    stored = ac.ton_raw(key) if chain == "ton" else reg.display_owner(chain, key)
    return {"entry": {"chain": chain, "network": network, "address": stored}, "key": key, "display": reg.display_owner(chain, key),
            "note": f"{reg.display_name(chain)} 주소 형식 확인됨"}


def _btc_hd_scripts(row: dict) -> set:
    import btc_descriptor as bd
    import chain_registry as reg
    e = row["entry"]
    plan = bd.plan_from_descriptor(str(e.get("descriptor") or ""), row["network"])
    gap = e.get("gap_limit", 20)
    gap = gap if isinstance(gap, int) and not isinstance(gap, bool) and 1 <= gap <= 1000 else 20
    rend = e.get("range_end")
    rend = rend if isinstance(rend, int) and not isinstance(rend, bool) and 0 <= rend < 100000 else None
    br = {}
    try:
        st = statefile.read_json(paths.state(reg.spec("btc").cursor_file), None)
        br = ((((st or {}).get("btc") or {}).get("wallets") or {}).get(row["key"]) or {}).get("br") or {}
    except Exception:   # noqa: BLE001 [fallback]
        br = {}
    out = set()
    for b in plan.branches:
        try:
            used = int((br.get(str(b)) or {}).get("used", -1))
        except (TypeError, ValueError):
            used = -1
        end = used + gap if rend is None else max(used + gap, rend)
        for i in range(0, min(end, 100000 - 1) + 1):
            out.add(plan.derive(b, i)[0].lower())
    return out


_BTC_NO_MOVE = (" 같은 지갑 그대로의 삭제·재등록은 되지만, 이미 기록한 단일 주소를 HD 지갑으로(또는 HD 지갑을 단일 주소로) 바꾸는 이전은"
                " 지원하지 않아요(지워도 기록이 남아 두 번 세져요) — 처음부터 HD 지갑 하나 또는 단일 주소로만 등록하세요")


def _btc_overlap(have: list, ent: dict, key: str):
    import chain_registry as reg
    rows = [r for r in have if r["chain"] == "btc"]
    new = {"key": key, "entry": ent, "network": ent.get("network") or "mainnet", "mode": ent.get("mode")}
    if ent.get("mode") == "descriptor":
        singles = [r for r in rows if r["mode"] == "address"]
        if not singles:
            return None
        mine = _btc_hd_scripts(new)
        hit = [r for r in singles if reg.btc_source(r["entry"], r["network"])["script"].lower() in mine]
        if hit:
            return (f"이미 등록된 단일 주소 지갑({hit[0]['label'] or '이름 없음'})이 이 HD 지갑에 들어 있어요 — 같은 BTC 를 두 번 세지 않게 막았어요."
                    + _BTC_NO_MOVE)
        return None
    spk = reg.btc_source(ent, new["network"])["script"].lower()
    for r in rows:
        if r["mode"] == "descriptor" and spk in _btc_hd_scripts(r):
            return (f"이 주소는 이미 등록된 HD 지갑({r['label'] or '이름 없음'})에 들어 있어요 — 따로 추가하지 않아도 그 지갑으로 기록돼요."
                    + _BTC_NO_MOVE)
    return None


def add_chain_wallet(chain: str, address=None, label=None, mode: str = "address", descriptor=None, gap_limit=20, script_type=None) -> dict:
    import chain_registry as reg
    v = validate_chain_wallet(chain, address, mode, descriptor, gap_limit, script_type=script_type)
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        lst = cfg.get(reg.CFG_KEY)
        if lst is None:
            lst = cfg[reg.CFG_KEY] = []
        if not isinstance(lst, list):
            raise ValueError("config.json chain_wallets 형식 오류")
        have = reg.wallets(cfg)
        if any(r["chain"] == chain and r["key"] == v["key"] for r in have):
            raise ValueError("이미 등록된 지갑입니다")
        why9 = _btc_overlap(have, v["entry"], v["key"]) if chain == "btc" else None
        if why9:
            raise ValueError(why9)
        if len(have) >= reg.MAX_CHAIN_WALLETS:
            raise ValueError(f"새 체인 지갑은 최대 {reg.MAX_CHAIN_WALLETS}개까지예요")
        n_all = len({addr_key(w) for w in cfg.get("wallets") or [] if isinstance(w, dict)}) + len(have)
        if n_all >= MAX_ADDRESSES:
            raise ValueError(cap_error(n_all))
        if label is None or not str(label).strip():
            used = {str(w.get("label")) for w in (cfg.get("wallets") or []) + lst if isinstance(w, dict) and w.get("label")}
            n = 1 + sum(1 for r in have if r["chain"] == chain)
            label = f"{reg.display_name(chain)} {n}"
            while label in used:
                n += 1
                label = f"{reg.display_name(chain)} {n}"
        ent = dict(v["entry"], label=_label_ok(label))
        lst.append(ent)
        settings_store.write_config_raw(cfg)
    return {"chain": chain, "key": v["key"], "display": v["display"], "label": ent["label"], "note": v["note"]}


def _chain_wallet_match(chain: str, ident: str):
    import chain_registry as reg

    def same(r):
        if r["chain"] != chain:
            return False
        if ident in (r["key"], r["display"]):
            return True
        try:
            return chain != "btc" and reg.owner_key(chain, ident) == r["key"]
        except ValueError:
            return False
    return same


def remove_chain_wallet(chain: str, ident: str) -> int:
    import chain_registry as reg
    ident = str(ident or "").strip()
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        lst = cfg.get(reg.CFG_KEY)
        if not isinstance(lst, list):
            return 0
        same = _chain_wallet_match(chain, ident)
        keep = [w for w in lst if not any(same(r) for r in reg.wallets({reg.CFG_KEY: [w]}))]
        n = len(lst) - len(keep)
        if n:
            cfg[reg.CFG_KEY] = keep
            settings_store.write_config_raw(cfg)
    return n


def rename_chain_wallet(chain: str, ident: str, label: str) -> int:
    import chain_registry as reg
    label = _label_ok(label)
    ident = str(ident or "").strip()
    n = 0
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        same = _chain_wallet_match(chain, ident)
        for w in cfg.get(reg.CFG_KEY) or []:
            if any(same(r) for r in reg.wallets({reg.CFG_KEY: [w]})):
                w["label"] = label
                n += 1
        if n:
            settings_store.write_config_raw(cfg)
    return n


MAX_PERP = 30


def perp_list(cfg: dict) -> list:
    import perp_dex
    return [{"dex": d, "name": perp_dex.NAMES[d], "address": a["address"], "label": a["label"]}
            for d, lst in perp_dex.configured(cfg).items() for a in lst]


def add_perp(dex: str, address: str, label: str) -> dict:
    import perp_dex
    addr, note = perp_dex.validate_address(dex, address)
    label = _label_ok(label)
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        pw = cfg.setdefault("perp_wallets", [])
        if not isinstance(pw, list):
            raise ValueError("config.json perp_wallets 형식 오류")
        have = {(d, a["address"]) for d, lst in perp_dex.configured(cfg).items() for a in lst}
        if (dex, addr) in have:
            raise ValueError("이미 등록된 주소입니다")
        if len(have) >= MAX_PERP:
            raise ValueError(f"퍼프 덱스 주소는 최대 {MAX_PERP}개까지 등록할 수 있습니다")
        pw.append({"dex": dex, "address": addr, "label": label})
        settings_store.write_config_raw(cfg)
    return {"dex": dex, "address": addr, "note": note}


def remove_perp(dex: str, address: str) -> int:
    import perp_dex
    a = (address or "").strip()
    with settings_store.LOCK:
        cfg = settings_store.read_config_raw()
        before = list(cfg.get("perp_wallets") or [])

        def same(w):
            if not isinstance(w, dict) or w.get("dex") != dex:
                return False
            wa = str(w.get("address") or "")
            return wa == a or (perp_dex.DEXES.get(dex, {}).get("kind") != "sol" and wa.lower() == a.lower())
        cfg["perp_wallets"] = [w for w in before if not same(w)]
        n = len(before) - len(cfg["perp_wallets"])
        if n:
            settings_store.write_config_raw(cfg)
    return n
