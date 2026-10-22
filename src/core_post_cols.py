__all__ = ["LEG_SQL"]

LEG_SQL = {
    "_stable_regroup.1": "UPDATE positions SET qty_norm=?, qty_unknown_norm=?, cost_alloc_usd=? WHERE group_id=? AND location=?",
    "_stable_regroup.2": "INSERT INTO positions (group_id, location, qty_norm, qty_unknown_norm, cost_alloc_usd) VALUES (?,?,?,?,?)",
    "_stable_regroup.3": "DELETE FROM positions WHERE group_id=?",
    "_exf_fix_place_apply.1": "DELETE FROM postings WHERE posting_id=?",
    "_exf_fix_place_apply.2": "UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?",
    "_exf_fix_place_apply.3": "INSERT INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, ?, ?, ?, ?, ?, NULL, NULL,"
        " 'opening', 'EXF_ADJUST', ?)",
    "_exf_debt_redate_once.1": "UPDATE postings SET event_ts=?, qty_base=? WHERE posting_id=?",
    "_exf_debt_redate_once.2": "INSERT OR IGNORE INTO postings (source_kind, source_ns, source_id, leg_seq, event_ts, asset_id, location, qty_base,"
        " cost_usd, cost_krw, leg_kind, event, classifier_ver) VALUES ('exchange', ?, ?, 2, ?, ?, ?, ?, NULL, NULL, 'opening',"
        " 'EXF_ADJUST', ?)",
    "_out_px_band_fix_once.1": "UPDATE postings SET cost_usd=NULL, cost_krw=NULL WHERE posting_id=?",
    "_price_tx.1": "UPDATE postings SET cost_usd=?, cost_krw=? WHERE posting_id=?"
        " AND (cost_usd IS NULL OR (event='SWAP' AND leg_kind IN ('disp','acq')))",
    "krw_fill_pass.1": "UPDATE postings SET cost_krw=? WHERE posting_id=? AND cost_krw IS NULL AND cost_usd=?",
    "price_pass.1": "UPDATE postings SET cost_usd=? WHERE posting_id=?"
        " AND cost_usd IS NULL",
    "price_pass.2": "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_ns=? AND source_id=?"
        " AND leg_seq IN (0, 1) AND cost_usd IS NULL",
    "_price_upbit_quote_fills.1": "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_ns='upbit:order' AND source_id=?"
        " AND leg_seq IN (0, 1) AND cost_usd IS NULL",
    "_exf_ext_settle_repair.1": "UPDATE postings SET event_ts=? WHERE posting_id=? AND event_ts=?",
    "_exf_ext_redate.1": "UPDATE postings SET event_ts=? WHERE posting_id=?",
    "_exf_redate_once.1": "UPDATE postings SET event_ts=? WHERE posting_id=?",
    "_reclass_plain_xfer_once.1": "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_kind='chain_tx' AND source_ns=?"
        " AND source_id=? AND leg_kind='gas' AND asset_id=? AND location=? AND qty_base=?"
        " AND cost_usd IS NULL",
    "_reclass_added_lp_mgrs_once.1": "UPDATE postings SET cost_usd=?, cost_krw=? WHERE source_kind='chain_tx' AND source_ns=?"
        " AND source_id=? AND leg_kind='gas' AND asset_id=? AND location=? AND qty_base=?"
        " AND cost_usd IS NULL",
}
