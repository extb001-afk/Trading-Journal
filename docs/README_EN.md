# tj-bot (English)

← [README.md](../README.md)

## English

**tj-bot** is a self-hosted, **read-only** crypto trade journal. Give it wallet addresses (EVM chains, BNB Chain, Solana, plus
optional extra EVM chains; Tron, Sui, TON and Bitcoin — single address or a watch-only HD wallet from a public descriptor/xpub — are added in
Settings > wallets, keyless by default with optional free TronGrid/toncenter keys; see docs/COLLECTION_LIMITS.md for their limits) and, optionally, **read-only** API keys for Upbit, Bithumb, Binance, Bybit, OKX, KuCoin, Gate and Coinbase.
It merges on-chain swaps, transfers and LP positions with exchange deposits, withdrawals and fills into one local SQLite ledger and
shows cost basis, realized/unrealized PnL, a daily PnL calendar with per-day trade notes, trade "receipts" with buy/sell charts,
a long-range net-worth curve, an "other assets" tab (real estate, stocks, gold, cash, debt), a capital-gains statement (reference only), bridge/transfer
tracking and a review queue for unknown-cost inflows and spam tokens. The UI is Korean and times are KST.

**Cost basis = moving weighted average (WAC), not FIFO.** One average cost per asset group (`known cost ÷ known quantity`); within a single transaction the
disposal leg is valued at the pre-transaction average before the acquisition leg updates it; moves between your own wallets/exchanges keep the average;
quantities with unknown cost are kept outside the average and flagged as unknown cost when sold. Realized PnL and the capital-gains
statement use this average.

- **Requirements:** macOS or Linux, Python 3.9+ (standard library only). Node.js + pm2 optional (recommended for auto-restart).
- **Always-on server:** use a fixed-IP Linux box (Ubuntu 24.04; 2–4 cores, 4–8 GB RAM — add 4 GB swap on 4 GB, 40–80 GB SSD) and whitelist that IP on your exchange API keys. Keep the web UI bound to 127.0.0.1; open it with `ssh -L 8023:127.0.0.1:8023 user@server` or an HTTPS tunnel/reverse proxy with login on — never expose the port directly.
  On Linux with 2+ cores the screen build runs in a forked tj-web child; with 4+ cores that child is pinned to the highest-numbered core and every other
  unit stays off it (falls back to building in tj-web on failure; macOS and single-core machines are unchanged; `TJ_BUILD_PROC=auto|off|fork`, also read
  from `.env` or `config.json` `build_proc` — restart all units). Rotate logs with `pm2 install pm2-logrotate` or `tools/rotate_logs.sh` from cron, not both.
- **Start:** `bash tools/setup.sh` (creates `config.json` and `.env` (both mode 600) and `state/`; installs nothing), then
  `pm2 start ecosystem.config.js` and open http://127.0.0.1:8023/ — a setup wizard handles wallets (paste many at once), keys and Telegram.
  `bash tools/setup.sh --demo` shows synthetic data without saving anything.
- **Keys:** free keys are required for Helius (Solana wallets) and for Etherscan, Alchemy and Ankr (EVM wallets — the three EVM keys are a warning only:
  without them collection still runs on public nodes, newest transactions first, but old history fills more slowly, old-holding discovery is weaker and idle
  wallets' incoming tokens are checked less often). Alchemy (`TJ_ALCHEMY_KEY`, https://dashboard.alchemy.com/signup) finds every token a wallet ever touched
  plus current balances so long-held tokens are not missed (watching and backfill stay on free nodes; metered under 80% of the free 30M CU/month; saving the key
  needs no restart). Ankr (`TJ_ANKR_KEY`, https://www.ankr.com/rpc/) checks idle wallets for incoming tokens every 10 minutes, speeds up BNB Chain/Base archive
  backfill, reads old-block balances for the BNB Chain balance watch (plain BNB sent to you) and backs token discovery. Every key is checked with one read-only call when saved (a refused key is not saved). NodeReal and QuickNode node keys are optional (QuickNode = one multichain endpoint URL from a paid plan or the 1-month free trial — there is no permanent free plan; if the key keeps being refused, e.g. the trial ended, the bot drops it and falls back to the default nodes; used for Base internal-transfer traces and, with what is left, old BNB Chain/Base balances, never for getLogs); an optional free Chainnodes key (`TJ_CHAINNODES_KEY`, Core plan 12.5M requests/month) is tried first for Base internal-transfer traces only (order Chainnodes → QuickNode → default nodes);
  free node keys may burst up to 10x the daily share while catching up, after keeping the measured real-time share (rolling 31-day total stays under 80% of the
  monthly limit; judged from this bot's own recorded use — nothing to switch on). CoinGecko (demo or pro — detected automatically) and OpenSea keys are optional; exchange keys must be **read-only**
  with an IP whitelist (keys with trade/withdraw/transfer permissions are refused where the exchange lets us check).
  Defaults run on free keys and public nodes only; external APIs are paced to 80% of their published limits.
- **First run:** the default backfill is the last 5 months; expect minutes to a few hours depending on wallets and trades.
  Progress is shown in the status panel and in Settings > collection limits. Every collection path (explorers, EVM RPC chains, BNB Chain, Solana) looks at
  the newest blocks first and fills old history in a side lane with whatever quota real-time checks leave, so new transactions show up within minutes even
  on the first day (a fresh install never starts on Blockscout). Until a chain's or exchange's old history is in, today's holdings and total use the actual current
  balance (most of it within minutes of starting; allow about 30 minutes until every initial balance shows — newly found tokens need a price and auto-enabled chains join after their check); cost, PnL and past curves become exact once old history is complete (progress and time left are shown under the curve).
- **Hyperliquid · NFT · prices:** Hyperliquid (HyperCore spot fills/transfers, perps cash and staked HYPE booked like an exchange and reconciled —
  opt in with `"hyperliquid": {"spot": true}`); NFT holdings with floor prices (auto-tracks collections with a floor and recent volume,
  candidate list, spam filtering with reasons, watch-only collections, an "include in total" switch that is off by default, CryptoPunks and
  other pre-ERC-721 NFTs detected automatically; display only, never in the ledger). EVM floors come from OpenSea first when the optional
  `TJ_OPENSEA_KEY` is set (covers smaller collections), otherwise CoinGecko; an optional CoinGecko key (`TJ_COINGECKO_KEY` — a free **demo**
  key or a paid **pro** key; the plan is detected automatically when you save or test it, pro keys use `pro-api.coingecko.com` and, since a pro
  key is usually shared with other tools, only 10% of the plan's per-minute and monthly limits by default — a "usage share" switch in the same
  row offers 10/25/50/80%, 80% being the hard cap; the monthly part is spread evenly over the rest of the month and shrinks further when other
  tools already used most of the month) fills floors much faster. The same key is also used for CoinGecko USD prices of coins no exchange
  priced, DEX token prices, historical prices for cost basis and charts, and DEX pool candles; when its share runs out or it fails, that call
  falls back to the old keyless request (see `docs/API_KEYS.md`). USD prices follow Binance → Bybit → CoinGecko, Upbit/Bithumb USDT and BTC markets are never used, and same-ticker
  different coins are filtered out. The daily card breaks the price move down per coin, and a "month at a glance" card sits under the calendar.
- **Telegram alerts:** three tiers — **now** (sound, even in quiet hours: bot stopped, target/stop hit, a large withdrawal you did not make,
  stablecoin depeg, near liquidation, optional big moves), a **daily digest** (one silent message at a set time) and **system** (never sent,
  status panel only). Presets (recommended/minimal/all), thresholds and quiet hours; the same problem is sent at most twice (raised and ✅ resolved).
  A single chain running late is off by default (status panel only; on with the "all" preset), while a whole collector stopping is always sent.
- **Look back at your trading:** a time machine (drag the curve to see that day's holdings vs. "if you had held"), a money-flow map
  (deposits → exchanges → wallets → where it is now), a sell preview (expected realized PnL and this year's taxable gain), a year-end card set,
  a plan-keeping score, trading habits by weekday/hour and holding time, a one-year realized-PnL heatmap and a BTC comparison line (the "never sold" line is hidden for now — sold coins lack current prices; it will come back once fixed).
- **Old holdings:** tokens held since before the collection window are found when a wallet is registered — per-chain sources are merged (Etherscan, Routescan,
  Blockscout, Alchemy, Ankr, the Rabby portfolio (only when `rabby.enabled` is on — off by default), RPC log scans and genuine tokens already in the ledger) and opening balances come from same-block balances (spam skipped).
  Keyed APIs are called once per (wallet, chain) and again only when free signals show activity. Base, BNB Chain and X Layer need a free Alchemy/Ankr key for this
  (`seed/coverage/token_sources.json`). If a missed token is later sent out and the ledger goes negative, the balance one block earlier is read and a "found-at-discovery
  opening balance" (cost unknown) is booked. One-time tools for existing wallets: `tools/token_recheck.py` (preview-only scan) → `tools/negabs.py --recheck <file>`
  (preview, then `--apply`). `seed/coverage/evm_chains.json` lists the 73 Alchemy-supported EVM mainnets (free vs Alchemy-only paths); being listed does not mean tracked.
  Tokens only ever received before the window (opening balance only) are valued only when CoinGecko has a price for that contract, so received scam tokens do not
  inflate the total; `tools/negabs.py --genuine <CA> --chain <chain> --wallet <address>` registers a plain token as genuine for a negative cell.
  Switches: `"token_discovery": {"enabled": false}`, `"negabs_enabled": false`.
- **Borrowed coins:** `loan_short` in `config.json` — confirmed exchange-loan periods only, e.g. (synthetic) `[{"exchange": "okx", "asset": "ETH", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}]` —
  gives coins borrowed and withdrawn (exchange balance pushed below zero, later refilled on the same exchange) a cost at the borrow-time price; the difference on refill is realized
  (a "대출 상환" row in the statement; display calculation only, with first-seen pricing on — the default; empty = off).
- **How cost and PnL are calculated** (details in Korean under [원가 · 손익 계산 방식](FEATURES.md#원가--손익-계산-방식)). Everything is computed in USD; KRW figures use Upbit's KRW-USDT price (kimchi premium included).
  The ledger stores each leg's USD price at that moment; averages, realized PnL and the statement are recomputed from the ledger on every build.
  - **Average cost (moving weighted average, not FIFO)** per asset group: a chain's native coin (plus its official wrapped token) is one group across chains,
    each whitelisted stablecoin is one group by name, other tokens are per contract, and exchange balances are per exchange and coin. Realized = proceeds − average × quantity sold.
  - Within one transaction the sell leg uses the pre-trade average; same-second trades are ordered by block/tx position or fill time.
  - Moves between your own wallets and exchanges carry the departing average cost (no PnL); the destination re-averages if it already holds that coin.
  - Fees: exchange buy fees and swap-buy gas add to cost; sell fees and swap-sell gas reduce that sale's PnL; non-trading gas and withdrawal/bridge fees are
    that day's expense (switch "gas into cost/PnL", default on). A coin spent as a fee is a disposal at market price.
  - Unknown-cost quantities (pre-window balances, airdrops, unmatched deposits) are priced at the first-seen day's price by default (marked as estimates);
    otherwise they stay outside the average and their sales show as "unknown cost". Manual cost, break-even and average-price fallback (off by default) are in the UI.
  - Unrealized = (price − average) × quantity with known cost. Futures use exchange-reported realized PnL, fees and funding; LP fees and staking rewards are income at receipt-time price.
  - Stablecoins are valued at $1. Realized KRW = USD PnL × the sell-time rate. The capital-gains statement uses the same average (KRW cost at buy-time rates) and is reference only.
- **Release notes:** what changed in each release (Coinbase (CDP View-only key), Binance dividend/airdrop/Earn payouts booked as income (replacing reconciliation adjustments that had covered them), a status-panel monitor for unexplained reconciliation adjustments (red = bug-shaped, yellow = large), fixes from an external review (sub-account slots, restore cursors, OKX boundaries, native-mirror tokens, stablecoin cost, fee rebates, UI save races), `__Host-` login cookies over HTTPS (sign in once more), enforced CSP, no coin-logo fetching, Rabby off by default, README split into `docs/` and tests renamed by feature — all units restart, no rebuild — on 2026-10-22; exchange sub-account keys for Binance, Bybit, OKX, KuCoin and Gate counted as the same exchange with a "서브N" tag, a one-time alert when Alchemy keeps refusing the key (monthly capacity, 402, 401/403), unexpected calculation errors shown in red on the status panel instead of being swallowed, a new "how costs and P&L are calculated" section, and an internal restructuring into smaller modules verified to give identical results — all units restart, no rebuild — on 2026-10-16; the tax statement's "coin spent as a fee" disposals shown as one row per day and coin — amounts are the per-fill sums, display only, `pm2 restart tj-web` — on 2026-10-13 (2); the "never sold" comparison line hidden until sold coins get current prices — display only, `pm2 restart tj-web` — on 2026-10-13; two remaining first-reconciliation display fixes from a re-review — Bithumb coin quantity with partial fills across a snapshot, Solana stake read before the wallet and a failed re-read skips that round — plus an "allow about 30 minutes for initial balances" note on 2026-10-12 (7); three display fixes from an external review — Bithumb KRW with partial fills across a balance snapshot, transfers in flight to an exchange before its first reconciliation, Solana stake accounts re-read with current balances — on 2026-10-12 (6); a fresh install shows today's total from current balances within minutes — exchange balances read first, exchange and all-chain on-chain current balances before the first reconciliation, no double-counted transfers in flight, Bithumb KRW rolled forward from its snapshot, a 20 CU Alchemy gate slot, 20 screenshots retaken on this release (the rest are from 2026-10-12 (3)) — on 2026-10-12 (5); the spot-realized gas line renamed "가스(매매 외)" (gas, non-trading) with a dimmed reference line below it
  for the day's trading gas and fees, already in cost basis (buys) or PnL (sells) and outside the sum — display only, `pm2 restart tj-web` after `git pull`, screenshots are from 2026-10-12 (3) — on 2026-10-12 (4); a screen polish pass — one number font, unified titles and colors, long explanations folded into one line
  plus "자세히", no jump-to-top when tapping lower settings rows —, an exchange-retention warning when fetching older history, an AI review "fill all" button and small
  external-review fixes — deferred receipt evaluations, no redirects on authenticated requests, tightened `state/` and `.env` permissions, prefetch of today's receipts
  and `bg=1` limited to internal requests — on 2026-10-12 (3); fixes from two independent external reviews — TON spam jettons no longer holding the whole
  TON reconciliation, a TON deposit during the first reconciliation no longer cancelled, Toncoin priced from its new GRAM ticker, new-chain transactions retried
  every 6 hours, held-reconciliation and missing-unit health warnings, oversized Transfer log data, warnings for new funds on auto-disabled chains, journal KRW and
  conversion rows on wide ranges, holdings paged by row, CoinGecko price age and fewer NFT/GeckoTerminal calls — plus an optional receipt chart candle prefetch on
  2026-10-12 (2); read-only Tron, Sui, TON and Bitcoin wallets; fixes from a full external review — own-wallet
  reclassification double count, CCA refunds and manually linked sale payments, BNB Chain recheck after a ledger restore, verified backups kept by disk cleanup,
  token discovery paging —; dismissible health warnings, 10/20-row pages that open on the first page, node selection by measured speed, Alchemy fill for old
  Base internal transfers, a free Chainnodes key for Base traces, QuickNode as an optional paid/trial key, same-block transaction order and a new-chain
  missing-details warning — on 2026-10-12; fixes for two more external reviews — net-zero partial fills of same-coin Upbit orders, same-block BNB
  deposits, gap and shortfall recovery under continuous inflow, late in-window old transactions absorbed into the opening balance at once, past curves marked from
  adjusted anchors, CCA payment-coin disposals, trace node order and deadlines, rebuild cause codes and disk cleanup, one QuickNode multichain key for Base traces,
  automatic node-key bursts and HyperEVM — on 2026-10-11 (2); fixes for two more external reviews — KRW of unbooked Upbit fills rewound in past days, BNB received during a long
  balance-watch gap recovered, the original cost of coins refunded by a token sale (CCA), late ledger rows at the first cycle and around midnight, an absolute trace
  deadline with persisted deferrals for EVM catch-up, long lists paged 20 at a time and tap-to-explain asset-change breakdown rows — on 2026-10-11;
  external review fixes — exchange margin/loan debt subtracted from the total, partial fills of open Upbit orders,
  late transactions re-computing closed past days, plain BNB received on BNB Chain found by a balance watch, an EVM back-lane budget, a GoPlus response cap,
  urgent-alert backoff and fallback-FX notes — on 2026-10-10 (3); newest blocks first on every collection path for fresh installs — RPC side lanes, BNB Chain and Solana —,
  no Blockscout as a first path, a required free Ankr key and a one-call connection check when any key is saved, idle wallets checked at least hourly with
  10-minute incoming-token checks, catch-up bursts of up to ten days of free quota, today's holdings at the actual current balance before a chain's first
  reconciliation (no double counting with in-transit withdrawals), late trace filling, past-curve LP and exchange-key fixes, hidden spam/impersonation rows,
  response caps on the remaining direct lookups and real AI failure reasons — on 2026-10-10 (2); old-holding discovery, found-at-discovery opening balances, the Alchemy key field, node-key catch-up bursts,
  an EVM chain table, settlement-time prices for coin-settled futures, response size caps on the shared request path, faster Base backfill, Bybit futures fees/funding at payment time,
  borrowed-coin cost and a Bithumb fill-time tool — on 2026-10-10; fixes from an external re-verification — corrupt-ledger hold, version and data-revision display,
  restore tool fixes, first-seen price safeguards, fee/bridge cost rules, replay order, futures/liquidation watch, slow-connection limits, instant
  valuation of new LP positions, plus balance changes for unclassified transactions, unverified DEX prices, "needs check" major symbols with a genuine list,
  exchange server time, KuCoin HF fills and a dashboard LP card — on the night of 2026-10-09; external full-review fixes — futures booked at settlement time, stablecoin KRW FX gains in the
  tax statement, first-seen cost estimates, one fee-cost rule, a curve redesign and off-site backup/restore — on the afternoon of 2026-10-09; day-card realized
  wording early on 2026-10-09; re-verification fixes on 2026-10-09; external review fixes on the evening of 2026-10-08; futures receipts and the separate build
  process earlier on 2026-10-08) is in [CHANGELOG.md](../CHANGELOG.md). To update, follow [업데이트](../README.md#업데이트) (stop → check backup → `git pull` →
  `bash tools/setup.sh` → `pm2 start ecosystem.config.js`); realized PnL and statement numbers may change (estimated rows are marked).
- **Backup and restore:** tj-core keeps a daily ledger backup in `state/backups/` (3 by default). `tools/ledger_restore.py` lists, checks and restores backups
  and re-collects what came after; `tools/offsite_backup.py` sends a compressed, sha256-verified copy to another machine over ssh (or leaves it in an outbox
  for the other side to pull) — `backup.offsite` in `config.json`, off by default. tj-core waits instead of creating an empty ledger when the old one is missing.
  `tools/exf_fut_place.py` previews or undoes the one-time futures settlement re-placement (after an undo it is not re-applied automatically until `--apply`).
  A corrupt ledger is not started ("원장 손상 — 복구 필요"); `tools/ledger_restore.py files` restores the off-ledger copies. One-time repair tools:
  `tools/latefix_move.py`, `tools/upbit_trades_fill.py`, `tools/repair_wrap_legs.py`, `tools/bithumb_filltime.py` (dry run by default).
- **Search:** ⌘K or / searches coins, addresses, tx hashes, dates, amounts, notes and reviews with a filter syntax
  (`coin:` `chain:` `type:` `after:` `before:` `pnl:` `amt:` …) and plain-sentence queries (rule-based by default; no external calls).
- **Broker adapters** in the other-assets tab are **UNVERIFIED** — written from public documentation only and never tested
  against a real account; all are disabled by default.
- **Privacy:** random-amount mode multiplies amounts by a per-page random factor (not stored by default — it can be pinned per browser in
  Settings › 표시 for consistent screenshots, never shown while the mode is on) with a "랜덤값" (random) watermark; explorer links are removed;
  hide mode (Shift+H) blurs amounts. Both are display-only. In either mode, names and notes you wrote yourself (wallet names, aliases,
  notes, Telegram bot/chat names) are shown as generic labels such as "지갑 A" / "메모", the Telegram link QR and code are hidden, and
  recent searches are cleared. All screenshots above were taken in random-amount mode (amounts are randomized) with fake addresses
  and position numbers (NFT collection names and floors are also hidden in the NFT shots, and other-asset names are replaced with "<type> A").
- **Login (on by default):** on first run, open http://127.0.0.1:8023/ on the machine itself to create a password (10+ characters);
  every device then needs it. Sessions last 30 days (7 days idle). Passwords are stored as PBKDF2-SHA256 hashes; 5 wrong tries in
  10 minutes lock that IP for 15 minutes (doubling on repeat). Change it or log out everywhere in Settings › 로그인; forgot it →
  `python3 tools/reset_password.py` (or `--set`) on the machine. Disable only with `"web": {"login": {"enabled": false}}` + restart tj-web.
  The first-password form also asks for a one-time **setup code** — the contents of `state/auth_setup_code` (0600, `cat state/auth_setup_code`
  on the machine; deleted once used), so nobody behind a header-less proxy can claim the first password.
  **Upgrading:** login is now on even when `web.login` is missing from `config.json` — after updating, restart tj-web and create the
  password on the machine first (other devices get 401 until then).
- **Reverse proxy / tunnel:** put an HTTP-aware HTTPS proxy (e.g. a Cloudflare tunnel) in front of `http://127.0.0.1:8023`, keep the `Host`
  header, add `X-Forwarded-For` and `X-Forwarded-Proto: https`, and list the domain in `web.allowed_hosts` (`web.public_url` = optional
  `https://` link for Telegram alerts). nginx: `proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;` — or set `"web": {"behind_proxy": true}` to treat every request as proxied (create the first
  password in a terminal on this computer with `python3 tools/reset_password.py --set` — without `--set` it only deletes the password and sessions). With login off, every request carrying proxy headers is refused (403). Proxied requests always need a
  session, can't create the first password or use the internal token, count toward the global login limit, and get `Secure` cookies, HSTS
  and `private, no-store` caching. Never use raw TCP forwarders (`ssh -R`, `socat`, `tailscale serve --tcp`, `ngrok tcp`) — they look like
  direct local access. `web.login.secure_cookie: true` forces the `Secure` flag; the login page warns on plain `http://` outside loopback/Tailscale.
  The internal token (`state/auth_internal_token`, regenerated on every tj-web start) is for same-machine units only — pass it as a header file,
  e.g. `curl -H @<(printf 'X-TJ-Internal: %s\n' "$(cat state/auth_internal_token)") http://127.0.0.1:8023/api/state`.
- **Security:** binds to 127.0.0.1 by default (optional Tailscale IP; public IPs and 0.0.0.0 are refused); password login is on
  by default, but still never expose the port directly to the internet; every POST needs a same-origin `Origin` header and a CSRF token; secrets stay in `.env`
  (mode 600) — except the unverified broker adapters, whose secrets live in `config.json`, so `config.json` is kept at mode 600 as well (setup.sh and tj-web tighten it).
  Fonts (IBM Plex, SIL OFL 1.1) are served from the repository (`web/v2/fonts/`, no external request); coin logos are not fetched at all (letter icons only — no request to jsDelivr or any CDN;
  the old `web.token_logos` setting and the per-device switch no longer have any effect);
  Rabby (DeBank data) portfolio lookups are also off by default — `rabby.enabled: true` sends your EVM wallet addresses to DeBank; a Cloudflare proxy may inject its Web Analytics script — disable that in Cloudflare if unwanted.
  Report security problems privately (GitHub › Security › Report a vulnerability — see [SECURITY.md](../SECURITY.md)).
  Advanced environment variables and config keys are listed under [고급 설정](CONFIG.md#고급-설정); release notes are in [CHANGELOG.md](../CHANGELOG.md).
- **AI features** (daily/weekly review, receipt evaluation) are off by default and use your local `claude` CLI when enabled (log in as the same OS user that runs the bot: run `claude` → `/login`; on a headless server use `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`, or `ANTHROPIC_API_KEY`; check with `claude -p "ok"`; "organization has disabled Claude subscription access" means your org admin turned Claude Code off — ask them, log in with a personal account, or use an API key). Only an
  allow-list of environment variables is passed to it (PATH, HOME, locale, `HTTP(S)_PROXY`/`NO_PROXY`/`ALL_PROXY`, corporate CA variables
  `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE`/`SSL_CERT_DIR`, and Claude login/gateway/Bedrock/Vertex variables) — never exchange keys or `.env` values.
  Receipt buy/sell evaluation is off by default; enable it by setting `review.sell_eval_daily_max` / `review.buy_eval_daily_max` to 1 or more
  (max calls per day). `review.coach_role` and `review.known_patterns` tailor the daily/weekly review to your style.
  `review.chart_prewarm_per_day` (default 0 = off) lets `tj-review` pre-fetch receipt chart candles in the background (no model calls; DEX candles first, before the free GeckoTerminal 180-day window closes).
- **Known limitations (this release):** until every wallet on a chain finishes its backfill (the chain's first balance reconciliation), today's holdings and
  total use the actual current balance, but cost, PnL and past curves still miss holdings from before the backfill window — sold coins may show unknown cost,
  past curves may look low and the status panel may briefly show a negative-holding warning marked "첫 백필 중" (first backfill, orange); it fixes itself (shorter backfill = sooner).
  That interim current balance is re-read hourly — a withdrawal landing while BNB Chain/Solana balances are being read, or an exchange-to-own-wallet transfer still
  in transit to a wallet that also held coins from before the window, can make that older holding look briefly smaller until the next read or arrival.
  Impersonation/spam rows can remain inside a coin card's history (they are hidden from the history list and excluded from holdings and totals); a KRW
  exchange other than Upbit/Bithumb added after the backfill finished may not be applied to the past curve (correct from that day — add exchange keys at
  install time to avoid it); bot-like addresses sending hundreds of log-less BNB transfers per hour fall behind on BNB Chain (only a few are recovered per
  cycle, newest first); on public-node-only chains such as Base, internal-transfer traces that time out or hit 429 fill in later (the trade is recorded first,
  internal ETH is re-traced with backoff up to 6 hours apart for 30 days; deferred lookups are saved before recording and survive restarts — no action needed; a free Chainnodes key or a QuickNode key (paid plan or 1-month trial) speeds up Base tracing
  and falls through to the next node when it is rate-limited or lacks old history); an Alchemy-only install backfills old
  Arbitrum/Etherscan-chain history slowly over public nodes (add the free Etherscan and Ankr keys), and removing the Etherscan key later re-scans the last
  few hours on public nodes; a few late-indexed internal transfers outside Etherscan's first backfill window may not be re-checked automatically (rare — check
  the balance reconciliation in the status panel); the chain chips in the add-wallet form do not yet explain how each chain is collected (see
  `docs/COLLECTION_LIMITS.md`); a "dashboard not responding" warning can flash for a few seconds right after install or restart (it clears once the first
  build finishes). Exchange debt is recorded at each daily close since 2026-10-10 (3) — recomputing an earlier day uses today's debt (a loan repaid since then
  makes that day look higher), and updating from an older release shows a one-time drop by the borrowed amount; partial Upbit fills are treated as happening at the balance
  snapshot time (the API gives no fill time) and are skipped while the Upbit balance is over 10 minutes old or right after an order completes; contract-sent BNB
  whose sending transaction cannot be identified enters as an opening balance (cost unknown) at that block time, smart-contract wallets are not balance-watched,
  and BNB missed before 2026-10-10 (3) is searched only for confirmed shortfalls of $500/2% or more within 30 days; recomputing a closed day after a late
  transaction may value coins that had no price in that day's snapshot at today's price, and days frozen before the update are not back-filled.
  Upbit open orders still carry no fill time, so an order open for several days can be off by its fill on an older day computed for the first time (e.g. a fresh
  install's long-range curve), today's value can differ by the fill while the Upbit snapshot is over 10 minutes old (never frozen into the close), a first buy of a
  coin with no price looks like a loss today and a sell larger than the booked balance looks like a gain that day. A BNB Chain balance-watch gap waits while your own
  sends in it are not yet in the ledger (log line "미해결 구간 N"); without an archive key a gap over 256 blocks becomes an opening balance at its end block; an
  archive-only setup (no public node) reads 6 wallets per run, so detection can lag by hours with many wallets. A CCA bid sent through a router/helper contract or before
  the collection window does not get its refund cost linked (old rule), and stablecoin refunds use the refund-time KRW rate. Without a keyed node (free Ankr key),
  Base catch-up after a long stop or a fresh install is still slow (balance/nonce bisection is over half of each step); two days of catch-up for a few active wallets may
  use about half of one day's Ankr share once, counted as real-time use, which can shrink that day's backfill burst. The breakdown detail lists up to 400 coins per day for market moves
  (the rest as one "N more" row, totals exact) and transfers per coin per day (net), not per transaction.
  Three or more same-coin Upbit orders that only partly offset each other can move that share of KRW to the next day (consistent, only the day differs); days frozen
  before the 2026-10-11 (2) update stay as they were. A log-less internal BNB credit from someone else in the same block can be attached to your contract call (amount
  right, per-transaction attribution only); deposits arriving faster than the per-run call cap close the overflow as an opening balance (amount kept). When the archive
  key is at rest and public nodes have no old state, only the EVM back-fill lane waits until UTC midnight (latest collection continues). Moving the collection start
  earlier still needs one rebuild; late in-window old transactions on Solana or on discovery-anchored cells still go through a rebuild. A disk filling up after a rebuild
  has started, or a non-English OS error text, is not treated as a disk cause (normal backoff). CCA payment-coin disposals are dated at the bid's exit; manually
  linked participation payments are now disposals too, dated when the first token arrives (KRW rate at send time). HyperEVM relies on Etherscan alone (waits during outages) and HyperCore/HyperEVM moves are not paired with
  Hyperliquid transfers (totals right, no cost carry-over).
  Tron, Sui, TON and Bitcoin hold their reconciliation while anything is unknown, retry undelivered transactions every 6 hours and show a held reconciliation in the
  status panel after 6 hours (TON now skips jettons the provider marks invalid; unknown-decimals spam on Tron/Sui still holds — see `docs/COLLECTION_LIMITS.md`); register a Bitcoin wallet as a single address
  or one HD wallet from the start (switching a recorded address to an HD wallet or back counts the same BTC twice). Same-block transaction order applies to
  transactions collected after this update (stored ones replay in their old order). A Bithumb limit order left open after a partial fill and then cancelled can
  show a larger holding until the next reconciliation (about 20 minutes by default). Restoring a ledger backup taken before new coins appeared with
  `tools/ledger_restore.py` can attach a manual per-coin cost to another coin — re-check manual costs after a restore.
  Toncoin held on an exchange that renamed it to GRAM can show a TON removal and a GRAM inflow with unknown cost (same coin — enter the cost yourself).
  Two same-second stablecoin-only trades in one block (sell a stablecoin, then buy it back) may replay in hash order rather than execution order, moving that
  sale's realized PnL to the next sale's day (final total unchanged); reopening a receipt drawer may not reload an AI evaluation or error that finished meanwhile
  (reload the page); the "fill all" confirmation counts only the manual share (automatic days in the same range are written too, so the real count and Claude
  usage can be higher).
  Not fixed yet: TON wallets already affected by the first-reconciliation race in the previous release, Solana same-slot order, Upbit/Bithumb stop orders filled within one cycle, a Bybit 403 rate limit treated as a
  6-hour key denial, internal outflows of contract wallets (7702/Safe) in third-party transactions on RPC chains (`chains.<chain>.rpc_trace: "all"`), no address or
  history in the new-chain venue drawer, restoring an old backup onto a replaced inbox (restore with the original inbox), Solana token accounts opened and closed
  within one cycle and the last epoch reward of a closed stake account, the first-backfill marker never set with `backfill_full_history: true` (past days stay unfrozen); by policy, airdropped NFTs
  with a floor price count toward the optional NFT total, and old long-range curve days with only daily candles use the 09:00 KST (UTC daily open) price.
- **Tests:** `python3 tests/run_all.py` — standard library only, synthetic data, no network, including real HTTP login checks (401 without a cookie,
  421 for a foreign Host, 403 without CSRF, lockout after repeated failures). `.github/workflows/tests.yml` runs `py_compile` on every file and the
  same command on Python 3.9, 3.11 and 3.13.
- **License:** [MIT](../LICENSE). Provided as is; PnL and tax figures are an aid, not advice.
