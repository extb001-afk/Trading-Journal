#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T

import contextlib
import hashlib
import io
import json
import os

import paths
import runner_fp
import chain_registry as reg
import btc_descriptor as bd
import btc_watch as bw
import ledger_backup as lb

sys.path.insert(0, os.path.join(T.ROOT, "tools"))
import ledger_restore as LR

XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
DESC = bd.descriptor_from_xpub(XPUB, "wpkh", "mainnet")
HD = {"chain": "btc", "mode": "descriptor", "descriptor": DESC}
ADDR = {"chain": "btc", "address": "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"}
BASE = {"chains": {}, "wallets": []}


def cfg(*rows):
    return dict(BASE, chain_wallets=list(rows))


def fp(unit, config):
    return runner_fp.unit_inputs(unit, config, {})[2]


def old_chain_fp(unit, config):
    keys = sorted(r["key"] for r in reg.wallets(config, unit))
    sp = reg.spec(unit)
    key = os.environ.get(sp.key_env, "") if sp.key_env else ""
    kh = hashlib.sha256(key.encode()).hexdigest()[:8] if key else ""
    return runner_fp._h([keys, (config.get(reg.CFG_CHAIN_KEY) or {}).get(unit), kh])


def old_core_fp(config):
    import nodekeys
    parts = [[], config.get("exchange_addresses"), "", nodekeys.fingerprint(),
             config.get("backfill_months"), config.get("backfill_full_history")]
    nev = runner_fp._nonevm_core_view(config)
    if nev:
        parts += [nev, [(c, old_chain_fp(c, config)) for c in sorted({c for c, _ in nev})]]
    return runner_fp._h(parts)


for unit in ("btc", "core"):
    base = fp(unit, cfg(HD))
    T.chk(fp(unit, cfg(dict(HD, gap_limit=100))) != base, f"HD gap change restarts {unit}")
    T.chk(fp(unit, cfg(dict(HD, range_end=200))) != base, f"HD range change restarts {unit}")
    T.chk(fp(unit, cfg(dict(HD, gap_limit=20, range_end=None))) == base, f"default HD values normalize for {unit}")
    T.chk(fp(unit, cfg(dict(HD, label="renamed"))) == base, f"HD label alone keeps {unit} fingerprint")
    T.chk(fp(unit, cfg(dict(HD, mode=None))) == base, f"implicit descriptor mode keeps {unit} fingerprint")
    for value in (False, True, -1, bw.MAX_INDEX, "200", 2.5):
        T.chk(fp(unit, cfg(dict(HD, range_end=value))) == base,
              f"ignored HD range {value!r} normalizes for {unit}")
    for value in (0, bw.MAX_INDEX - 1):
        T.chk(fp(unit, cfg(dict(HD, range_end=value))) != base,
              f"valid HD range boundary {value} changes {unit}")
    T.chk(fp(unit, cfg(HD, ADDR)) == fp(unit, cfg(ADDR, HD)), f"wallet order keeps {unit} fingerprint")
    T.chk(fp(unit, cfg(HD, dict(HD, gap_limit=100))) == base,
          f"ignored duplicate HD entry keeps {unit} fingerprint")
    one = cfg(ADDR)
    T.chk(fp(unit, cfg(dict(ADDR, gap_limit=100, range_end=200, label="new"))) == fp(unit, one),
          f"single-address irrelevant HD values keep {unit} fingerprint")

nonbtc = cfg({"chain": "tron", "address": "41" + "11" * 20},
             {"chain": "sui", "address": "0x" + "21" * 32},
             {"chain": "ton", "address": "0:" + "31" * 32})
for label, config in (("legacy", BASE), ("non-BTC", nonbtc), ("single-address BTC", cfg(ADDR))):
    T.chk(fp("core", config) == old_core_fp(config), f"{label} core fingerprint remains byte-identical")
    for unit in reg.CHAINS:
        T.chk(fp(unit, config) == old_chain_fp(unit, config), f"{label} {unit} fingerprint remains byte-identical")
for unit in ("evm", "sol", "bsc", "tron", "sui", "ton"):
    T.chk(fp(unit, cfg(HD)) == fp(unit, cfg(dict(HD, gap_limit=100, range_end=200))),
          f"HD changes leave unrelated {unit} fingerprint unchanged")

ad0 = bw.BtcAdapter(cfg(HD))
ad1 = bw.BtcAdapter(cfg(dict(HD, gap_limit=100, range_end=200)))
wid = reg.wallets(cfg(HD), "btc")[0]["key"]
T.chk(ad0._fp(wid, "state") != ad1._fp(wid, "state"), "new adapter updates existing state fingerprint")
T.chk(ad1._wcfg(wid)["gap"] == 100 and ad1._wcfg(wid)["range_end"] == 200,
      "new adapter consumes the changed normalized HD values")

cp = os.path.join(T.TMP, "config.json")
wallets = nonbtc["chain_wallets"] + [dict(HD, gap_limit=100, range_end=200), ADDR]
source = dict(BASE, chain_wallets=wallets, exchange_addresses=[{"address": "synthetic"}],
              nonevm={"btc": {"esplora": ["https://synthetic.invalid"]}},
              secret="synthetic_secret_not_backed_up")
with open(cp, "w", encoding="utf-8") as f:
    json.dump(source, f)
with open(os.path.join(T.TMP, ".env"), "w", encoding="utf-8") as f:
    f.write("SYNTHETIC_SECRET=not_backed_up\n")
lb.backup_files("20261011", paths.STATE_DIR, cp)
subset_path = os.path.join(paths.state("backups"), "files_20261011", "config_subset.json")
with open(subset_path, encoding="utf-8") as f:
    subset = json.load(f)
T.chk(subset.get("chain_wallets") == wallets, "backup preserves all registered chain wallets and HD fields")
T.chk(set(subset) == {"wallets", "chain_wallets", "exchange_addresses"}, "backup remains limited to the three configuration lists")
T.chk(subset.get("wallets") == source["wallets"] and subset.get("exchange_addresses") == source["exchange_addresses"],
      "existing backup configuration lists remain unchanged")
T.chk(os.stat(subset_path).st_mode & 0o777 == 0o600, "configuration backup retains private permissions")
T.chk(not os.path.exists(os.path.join(os.path.dirname(subset_path), ".env")), "backup still excludes .env")
with open(cp, "w", encoding="utf-8") as f:
    json.dump(BASE, f)
lb.backup_files("20261012", paths.STATE_DIR, cp)
with open(os.path.join(paths.state("backups"), "files_20261012", "config_subset.json"), encoding="utf-8") as f:
    legacy = json.load(f)
T.chk(legacy == {"wallets": []}, "absent chain_wallets stays absent in legacy backup")

output = io.StringIO()
with contextlib.redirect_stdout(output):
    try:
        LR.main(["--help"])
    except SystemExit as exc:
        T.chk(exc.code == 0, "restore help exits successfully")
for name, text in (("stop", LR.STOP_HINT), ("start", LR.START_HINT),
                   ("fresh collector stop", LR.COLLECT_STOP_HINT), ("CLI help", output.getvalue())):
    T.chk(all("tj-" + c in text for c in reg.CHAINS), f"{name} guidance includes every registered collector")
T.chk(LR.START_HINT.startswith("pm2 start tj-core"), "restore guidance still starts core first")
plan = LR.files_plan("20261011")
T.chk(any("chain_wallets" in s for s in plan["manual"]), "manual configuration restore guidance names chain_wallets")
T.chk(all(row[0] != "config_subset.json" for row in LR.files_payloads(plan)[0]),
      "configuration subset remains manual-only; no automatic settings restore")

T.finish()
