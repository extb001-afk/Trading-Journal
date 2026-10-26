# tj-bot security (English)

← [README.md](../README.md) · Korean original: [SECURITY_DATA.md](SECURITY_DATA.md) — keep this file in step with it (structure checked by `tests/test_docs_en.py`). Commands, paths and settings keys are as in the original; other linked documents are in Korean.

Anchor map (Korean → English): [보안 · 데이터](SECURITY_DATA.md#보안--데이터) → [Security · data](#security--data)

## Security · data

- **It only reads.** It never asks for private keys or seed phrases, and with exchange and brokerage keys it calls only balance and history lookup APIs (there is no order or withdrawal code).
- **The web UI binds to 127.0.0.1 by default** and is locked with password login (on by default — PBKDF2-SHA256 hash, HttpOnly·SameSite=Strict session cookie, attempt limits).
  Every response carries frame-blocking and nosniff headers, and server error pages do not include internal paths or values. Every write request (POST) checks same origin (Origin) + CSRF token,
  and the key-entry API accepts only local/tailnet access (or a logged-in reverse proxy). The Host of every request is checked (DNS rebinding protection).
  When login is off, every request with reverse-proxy or tunnel headers is refused.
  **Private IP (RFC 1918 · 10.x, 172.16–31.x and other router-internal addresses) or tailnet binding = login required + HTTPS proxy recommended** — when login is off, tj-web refuses to start (because anyone on the same network would see all your assets ·
  it opens only if you explicitly set `web.login.allow_lan_without_password: true` · not recommended). A private IP is plain HTTP, so the password and cookie travel unencrypted; use an HTTPS reverse proxy —
  with `web.behind_proxy: true` the login cookie always gets `Secure` (the only exception is an explicit `web.login.secure_cookie: false` · error in the startup log).
- Secrets (explorer, exchange and Telegram keys) are stored in `.env` (600) and shown on screen only as •••• (only exchange public API keys show their last 4 characters).
  Exception: for brokerage connections (unverified · off by default), `app_secret`, `secret_key`, `client_secret`, `refresh_token` etc. go into the `brokers` field of `config.json` —
  so `config.json` is also kept readable only by you (600): `tools/setup.sh` sets it to 600 when it creates it and when run again, and tj-web also narrows it at startup if it is wider than 600 (only when the file is yours).
  If you copied the files in yourself, run `chmod 600 config.json .env` once. `.env`, `config.json` and `state/` are in `.gitignore` — never commit them.
- Outgoing requests are lookups only: block explorers and RPC (your addresses), exchange APIs, prices (GeckoTerminal, DexScreener, exchange public prices, public stock/gold prices),
  scam checks (GoPlus — candidate token addresses only), wallet portfolio enrichment (Rabby public API — **off by default** · when turned on with `rabby.enabled: true`, your EVM wallet addresses valued at $1,000 or more go outside (DeBank data), threshold `rabby.min_wallet_usd`),
  bridge explorers (arrival checks), FX rates, Telegram sending, NFT floor prices (CoinGecko, Magic Eden, OpenSea — collection addresses only), Hyperliquid public lookups (your addresses),
  checking your public IP (api.ipify.org — only when you press the exchange IP allow-list guide button on the settings screen).
  The ledger contents themselves are not sent. Exception: when off-server backup (`backup.offsite` — off by default) is on, a compressed copy of the ledger is sent over ssh to **a computer you specify**.
  Exception: when the AI features (off by default) are on, that day's summary and receipt summaries are sent to the `claude` CLI on your computer.
- **External addresses the browser (screen) calls directly** — the above are what the server calls; the browser that opens the screen also makes requests directly to the following (those services can see the client IP):
  - **Fonts** (IBM Plex Sans KR, IBM Plex Mono) — now served from the repository (no external request): tj-web serves the glyph slices (woff2) in `web/v2/fonts/` itself,
    and the browser fetches only the slices for the characters shown on screen. License = SIL Open Font License 1.1 (`web/v2/fonts/OFL.txt`).
  - **Coin logos** — not fetched (letter icons only · 0 external requests). In earlier releases, turning them on sent logo requests to jsDelivr (`cdn.jsdelivr.net`), and from the **chain, contract address and symbol** in the logo URLs
    that service could guess the list of tokens you hold — logo fetching itself has been removed (`web.token_logos` and the device setting have no effect even if their values remain).
  - **If you put a proxy or tunnel such as Cloudflare in front**, depending on its settings a **Web Analytics** script (`static.cloudflareinsights.com`) may be inserted into the page —
    it is inserted by the proxy, not by tj-bot; if you do not want it, turn off Web Analytics (automatic injection) for that site in the Cloudflare dashboard.
- AI reviews and evaluations use the `claude` CLI on your computer, and only allow-listed environment variables are passed to it (PATH, HOME, locale, proxy `HTTP(S)_PROXY`, `NO_PROXY`, `ALL_PROXY`,
  corporate certificates `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, and Claude login, gateway, Bedrock and Vertex variables). Exchange keys and `.env` values are not passed.
  AI sell and buy evaluations are off by default — turn them on by setting `review.sell_eval_daily_max` and `review.buy_eval_daily_max` in `config.json` to 1 or more (maximum calls per day).
- When the login screen appears (logout, expiry, or log out on all devices from another device), the screen snapshots left in that browser (IndexedDB, version key) are deleted.
- **When copies of the ledger appear outside `state/`** — during an automatic rebuild (after an extended backfill, etc.), a temporary copy of about 3x the ledger + 2 GB (`~/tj_shadow_extrebuild_<time>/`, mode 700) and
  a diagnostic report (`~/tj_shadow_extrebuild_<time>.report.json`, latest 3) appear in the **home folder**; the copy is deleted when the rebuild ends. If the computer is shared with other users or the home folder is small,
  move them with `"backfill": {"rebuild_dir": "/my/disk/path"}` in `config.json` ([backfill · rebuild](OPERATIONS.md#백필--재구축--재백필)).
- **If you find a security problem**, report it through the repository's **Security › Report a vulnerability** (private report) instead of a public issue. Include only how to reproduce it — no real keys, addresses or balances.
