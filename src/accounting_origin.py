from __future__ import annotations


class OriginLookup:

    def __init__(orx, *, _net_na, oc_fresh, origin_pending, originin):
        orx._net_na = _net_na
        orx.conn = originin.conn
        orx.oc_fresh = oc_fresh
        orx.origin_cache = originin.origin_cache
        orx.origin_pending = origin_pending
        orx.raw_chains9 = originin.raw_chains
        orx.snap_cache = originin.snap_cache

    def resolve_origin(orx, x):
        ref = str(x.get("ref") or "")
        if x.get("from") is not None or not (ref.startswith("0x") and len(ref) == 66):
            return x
        key9 = ref.lower()
        if key9 in orx.snap_cache:
            row9 = orx.snap_cache[key9]
        else:
            sel9 = ("SELECT chain, json_extract(snapshot,'$.tx.from') AS f, json_extract(snapshot,'$.tx.to') AS t,"
                    " json_extract(snapshot,'$.tx.from.hash') AS fh, json_extract(snapshot,'$.tx.to.hash') AS th FROM raw_txs WHERE ")
            ch9 = x.get("chain")
            if ch9:
                row9 = orx.conn.execute(sel9 + "chain=? AND txhash IN (?, ?) LIMIT 1", (ch9, key9, ref)).fetchone()
            elif orx.raw_chains9:
                row9 = orx.conn.execute(sel9 + "chain IN (" + ",".join("?" * len(orx.raw_chains9)) + ") AND txhash IN (?, ?)"
                                    " ORDER BY rowid LIMIT 1", (*orx.raw_chains9, key9, ref)).fetchone()
            else:
                row9 = None
            orx.snap_cache[key9] = row9
        if row9:
            frm = str(row9["fh"] or row9["f"] or "").lower() or None
            to = str(row9["th"] or row9["t"] or "").lower() or None
            if frm and frm.startswith("{"):
                frm = None
            x["from"], x["to"], x["chain"] = frm, to, (row9["chain"] or x.get("chain"))
        elif key9 in orx.origin_cache:
            oc = orx.origin_cache[key9]
            x["from"], x["to"], x["chain"] = (oc.get("from") or None), (oc.get("to") or None), (oc.get("chain") or x.get("chain"))
            if oc.get("na"):
                x["oc_na"] = str(oc["na"])
            elif not x["from"] and orx._net_na(key9):
                x["oc_na"] = orx._net_na(key9)
            if not orx.oc_fresh(key9):
                orx.origin_pending.add(key9)
            elif not x["from"] and not x.get("oc_na"):
                x["oc_fail"] = int(oc.get("t") or 0) + 86400
        else:
            if orx._net_na(key9):
                x["oc_na"] = orx._net_na(key9)
            orx.origin_pending.add(key9)
        return x
