# tj-bot installation (English)

← [README.md](../README.md) · Korean original: [INSTALL.md](INSTALL.md) — keep this file in step with it (structure checked by `tests/test_docs_en.py`). Commands, paths and settings keys are as in the original; other linked documents are in Korean.

Anchor map (Korean → English): [설치 자세히](INSTALL.md#설치-자세히) → [Installation in detail](#installation-in-detail) · [1) 준비물](INSTALL.md#1-준비물) → [1) Requirements](#1-requirements) · [2) 받기 + 설치 점검](INSTALL.md#2-받기--설치-점검) → [2) Download + install check](#2-download--install-check) · [3) 키 준비](INSTALL.md#3-키-준비--env-와-configjson) → [3) Preparing keys](#3-preparing-keys--env-and-configjson) · [4) 실행 · 설정 마법사](INSTALL.md#4-실행--설정-마법사) → [4) Running · setup wizard](#4-running--setup-wizard) · [5) 첫 실행](INSTALL.md#5-첫-실행--얼마나-걸리고-어디서-보나) → [5) First run](#5-first-run--how-long-it-takes-and-where-to-look) · [6) 화면 열기](INSTALL.md#6-화면-열기--다른-기기에서-보기) → [6) Opening the screen](#6-opening-the-screen--viewing-from-other-devices) · [6-1) 서버에서 늘 켜 두기](INSTALL.md#6-1-서버리눅스에서-늘-켜-두기) → [6-1) Always on a server](#6-1-keeping-it-running-on-a-linux-server) · [7) 문제 해결](INSTALL.md#7-문제-해결--자주-묻는-5가지) → [7) Troubleshooting](#7-troubleshooting--5-common-questions)

## Installation in detail

### 1) Requirements

| Item | Required? | Notes |
|---|---|---|
| macOS or Linux | Required | Windows has not been tested (to use it, run it in Linux under WSL2). A computer or server that can stay on 24 hours a day is best |
| **Python 3.9 or later** | Required | Uses **only the standard library** — there is nothing to `pip install`. A Python that includes sqlite3 3.24+ and the ssl module (the default `python3` on macOS or Ubuntu 22.04+ is fine) |
| Node.js + pm2 | Optional (recommended) | Restarts everything automatically after a reboot or an error. `npm install -g pm2`. Node is needed only if you use pm2 |
| `claude` CLI | Optional | Only when you turn on AI reviews or AI buy/sell evaluations (off by default). Uses the Claude Code CLI already logged in on your computer as is |
| Fixed IP | Recommended when connecting exchanges | Exchange keys get an IP whitelist, so on a laptop whose IP changes often, exchange sync can be refused when you are out |

### 2) Download + install check

```bash
git clone <this repository URL> tj-bot
cd tj-bot
bash tools/setup.sh
```

`tools/setup.sh` **installs nothing.** It checks the Python version, sqlite3 and ssl,
copies `config.example.json` → `config.json` and `.env.example` → `.env` (if they already exist, their contents are left as they are · both files are set to mode 600),
creates `state/` (mode 700) and then tells you the next command to type. It is safe to run several times.
(For development · optional) To let your editor and `mypy` find the `src/` modules, run `bash tools/setup.sh --dev-path` — it writes a one-line `tj.pth` (`<this folder>/src`) into your user site-packages (not needed to run the bot · left as is if it already exists).

### 3) Preparing keys — `.env` and `config.json`

**Usually you do not need to edit the files yourself.** The web setup wizard writes `.env` and `config.json` for you. Just have the keys ready.

| Key (`.env` name) | Required? | Where to get it | When it is needed |
|---|---|---|---|
| `TJ_HELIUS_KEY` | **Required** if you have Solana wallets | https://dashboard.helius.dev (free) | Collecting Solana wallets |
| `TJ_ETHERSCAN_KEY` | **Required** if you have EVM wallets (warning only · does not block) | https://etherscan.io/myapikey (free) | Fetches Ethereum, Arbitrum and Polygon transactions quickly and without gaps (one key for several chains · only 80% of the daily free limit). Without it, transactions come through public nodes (RPC): the newest show up right away, but old history fills in late |
| `TJ_ALCHEMY_KEY` | **Required** if you have EVM wallets (warning only · does not block) | https://dashboard.alchemy.com/signup (free — 30M CU per month) | Finds every token a wallet has ever sent or received, plus current balances, so old holdings are not missed (Base, Ethereum, Arbitrum, etc.) · fills in from its internal-transfer list only when tracing nodes cannot give all internal ETH moves of old Base transactions (older than 30 days, etc.). Watching and old history come from free nodes; this key is used only for finding tokens and balances and for that gap-filling — under 80% of the free limit (daily share). Collection still runs without it, but finding old holdings is weaker (one explorer only) |
| `TJ_ANKR_KEY` | **Required** if you have EVM wallets (warning only · does not block) | https://www.ankr.com/rpc/ (free Freemium) | Quickly checks every 10 minutes for tokens arriving at wallets unused for a long time, fetches BNB Chain and Base old history (archive) quickly, finds BNB someone simply sent you on BNB Chain from old-block balances, and assists token discovery with the same key (Advanced API). Under 80% of the free limit. Collection still runs without it, but only through public nodes, so it can be late |
| `TJ_COINGECKO_KEY` | Optional | https://www.coingecko.com/en/developers/dashboard → a **Demo** key (free) or a paid **Pro** key — detected automatically | One key is shared by CoinGecko prices (coins with no exchange price), DEX token prices, cost basis, charts and NFT floor prices, making them faster. When its share runs short or a call fails, only that call goes keyless. Without it everything uses the shared keyless limit, so it is slow and NFT floor prices can take the first few hours. A Pro key uses only 10% of the plan limit (default · 25, 50 or 80% selectable) |
| `TJ_OPENSEA_KEY` | Optional | https://docs.opensea.io/reference/api-keys (free application) | When set, EVM NFT floor prices come **only from OpenSea**, so even small collections are tracked smoothly (other chains, or no key → CoinGecko) |
| `TJ_NODEREAL_KEY` · `TJ_QUICKNODE_KEY` | Optional | NodeReal (https://dashboard.nodereal.io) dashboard (free keys available) · QuickNode (https://dashboard.quicknode.com — if you have a paid plan or a 1-month free trial key · no permanent free plan · when the trial ends, switch to a paid plan or delete the key · if it keeps being refused, the bot drops it on its own and uses the default nodes) is one multichain endpoint URL (any chain's URL — the bot builds the per-chain URLs · Base internal-transfer traces + old balances with what is left · never used for getLogs) | Archive nodes for BNB Chain and Base old history — when set, BNB Chain is fetched further back than public nodes keep. Without them, public nodes are used. Free keys use 80% of the monthly limit (during backfill they keep the real-time share and burst up to 10x the daily share); paid keys use only their usage share (default 10% · QuickNode 80%) — choose the plan and test the connection in **Settings › Connections · keys** (설정 › 연결·키) |
| `TJ_CHAINNODES_KEY` | Optional | Chainnodes (https://www.chainnodes.org/) free Core plan (12.5M requests per month · 25 per second) API key — 8-4-4-4-12 format (if you paste the Base URL, only the key is saved) | Used first to check internal moves (trace) of Base transactions (not for logs or balances) · order = Chainnodes → QuickNode (if a key is set) → default nodes · transactions older than roughly the last 45 days, and calls while the limit is hit, go to the next node · 80% of the monthly limit — test the connection in **Settings › Connections · keys** (설정 › 연결·키) |
| `TJ_TRONGRID_KEY` | Optional (recommended if you have Tron wallets) | https://www.trongrid.io (free sign-up) | Tron wallet collection and balance reconciliation (TronGrid). With a key, 4 requests per second · within 80% of the daily free limit · sent only in a header. Without it, the shared keyless rate of 0.8 per second — old history is slow (about 1,400 transactions per hour) |
| `TJ_TONCENTER_KEY` | Optional (recommended if you have TON wallets) | https://t.me/tonapibot (free toncenter key) | TON wallet collection and balance reconciliation (toncenter v3). With a key, 8 requests per second (80% of the free 10). Without it, 1 per second |
| `UPBIT_ACCESS` · `UPBIT_SECRET` | Optional | Upbit › My page › Open API management | Upbit deposits/withdrawals, fills and balances |
| `TJ_BITHUMB_KEY` · `TJ_BITHUMB_SECRET` | Optional | Bithumb › My page › API management | Bithumb |
| `TJ_BINANCE_KEY` · `TJ_BINANCE_SECRET` | Optional | Binance › API Management | Binance |
| `TJ_BYBIT_KEY` · `TJ_BYBIT_SECRET` | Optional | Bybit › API | Bybit |
| `TJ_OKX_KEY` · `TJ_OKX_SECRET` · `TJ_OKX_PASSPHRASE` | Optional | OKX › API keys | OKX |
| `TJ_KUCOIN_KEY` · `TJ_KUCOIN_SECRET` · `TJ_KUCOIN_PASSPHRASE` | Optional | KuCoin › API Management | KuCoin |
| `TJ_GATE_KEY` · `TJ_GATE_SECRET` | Optional | Gate › API Keys | Gate |
| `TJ_COINBASE_KEY_NAME` · `TJ_COINBASE_SECRET` | Optional | Coinbase › Settings › API → CDP › Secret API Keys (**ECDSA · View only** — [how to create one](API_KEYS.md#코인베이스-키-cdp-api-키--조회-전용)) | Coinbase |
| `TJ_TG_TOKEN` · `TJ_TG_CHAT` | Optional | Create a bot with Telegram's @BotFather (the wizard fills in the chat ID automatically) | Telegram alerts |

How to get each key, what it is used for and what happens without it are listed in [docs/API_KEYS.md](API_KEYS.md).

> **Turn on only the 'view (read)' permission for exchange keys, and set an IP whitelist.**
> Never turn on trade, withdrawal or transfer permissions. Binance, Bybit and OKX check the permissions when the key is saved and refuse keys with trade, withdrawal or transfer turned on;
> for Upbit, Bithumb, KuCoin and Gate, whose permissions cannot be checked through the API, the key is saved only after you confirm 'I turned on view permission only' ('조회 권한만 켰음').
> Every key is checked with one read-only call when saved — if the service refuses the key (401·403) it is not saved; if the connection fails (timeout, etc.) it is saved and only a warning is shown.
> No private key or seed phrase is needed anywhere — this bot only reads.

No RPC key is needed. `config.example.json` uses only public RPCs and free explorers — the default setup is built to run **on free keys and public nodes alone**,
and paid keys and nodes only make it faster or, as with BNB Chain, let it fetch older history. External APIs are called slowly, with a daily share set from **80% of the published limit**,
and public nodes that publish no limit are held to a low requests-per-second rate by the bot itself. When an explorer is blocked, collection continues over public RPC (`rpc_fallback` — table below · [changelog 2026-10-07](../CHANGELOG.md#2026-10-07)).
For node keys (Alchemy, Ankr, NodeReal, QuickNode), paste just the key (for QuickNode, the multichain endpoint URL) into **Settings › Connections · keys › Explorer keys** (설정 › 연결·키 › 탐색기 키): it is saved only in `.env` and the node URL is built only in memory (no key is written into `config.json`).
Watching and backfill always try free nodes first, and calls that use a key are counted per service in a daily ledger and stop for the day before going over **80% of the published free limit** (if you choose a paid plan: monthly limit × usage share 10·25·50·80%).
When catching up on backlog such as a backfill or the first full scan, free node keys keep only the share real-time actually uses (ledger measurement × 1.5) and draw up to **10x the daily share (ten days' worth)**
(**burst** — the total of the last 31 days always stays within 80% of the monthly limit · real-time calls are never blocked by backfill) · the settings field shows 'burst in progress' (버스트 중) and 'real-time about … per day · today's backfill cap' (실시간 하루 약 · 오늘 백필 상한).
Burst is decided only from what this bot actually used (the daily ledger records), so there is nothing to turn on — past days with no usage record count as 0, and if the per-day records were ever damaged and discarded, the days before that are conservatively counted as having used the normal share ([docs/API_KEYS.md](API_KEYS.md)).
Wallets that have not sent anything for a long time (over 7 days) still get their balance checked every 10 minutes (public node · one batched call) and confirmed through an explorer every hour, and tokens arriving at such wallets are checked separately every 10 minutes (Ankr key → otherwise public-node getLogs · `addr_tier.inflow_sec`) —
incoming deposits are recorded within about an hour at the latest, and while a withdrawal from an exchange to your wallet is 'in transit', that address is checked every 10 minutes (the interval is stretched automatically only when there are so many wallets that the daily limit would be exceeded).
If you have a faster paid RPC, you can add it to the RPC lists `chains.<chain>`, `bsc` and `sol` in `config.json` (do not show URLs with embedded keys to others).
Node keys for BNB Chain and Base old history (NodeReal, Ankr, QuickNode), put in `.env` as in the table above, have their node URLs built only in memory, and no key-embedded URL is written into `config.json`.

→ [Settings keys worth knowing](CONFIG.md#알아-두면-좋은-키)


Telegram alert types and quiet hours are set not in `config.json` but on the screen under **Settings › Alerts (Telegram)** (설정 › 알림 (텔레그램)) (saved in `state/ui_prefs.json`).

### 4) Running · setup wizard

```bash
pm2 start ecosystem.config.js     # start everything — units without wallets or keys wait quietly
pm2 save                          # (optional) auto-start after reboot: also run the command 'pm2 startup' prints
```

Open **http://127.0.0.1:8023/** in a browser and the setup wizard guides you in this order: **wallets → explorer keys → exchanges → Telegram → display** (지갑 → 탐색기 키 → 거래소 → 텔레그램 → 표시).
You can enter [several wallets at once](FEATURES.md#지갑-주소-여러-개-한-번에), and EVM addresses are registered with the chains to track chosen (chips). Exchange keys are tested as soon as they are saved.
To change things later, open the same steps again from the **Settings** (설정) tab on the screen (after a change only the affected unit restarts itself within 30 seconds · wallet names and perp DEX addresses take effect without a restart).

To run without pm2, keep each one running in its own terminal:

```bash
python3 src/unit_runner.py web     # screen (required)
python3 src/unit_runner.py core    # ledger writer (required)
python3 src/unit_runner.py evm     # EVM wallets · sol and bsc work the same way
python3 src/unit_runner.py tron    # when you add Tron wallets · sui, ton and btc work the same way (waits if there is no wallet on that chain)
python3 src/alert_bot.py           # health checks, ledger warnings, Telegram (recommended — when it is off, the top of the screen shows '감시 유닛이 꺼져 있어요' (the monitoring unit is off))
python3 src/upbit_link.py          # (optional) Upbit · src/ex_foreign.py = foreign exchanges
```

To keep logs in files, open them in **append (`>>`)** mode — e.g. `python3 src/unit_runner.py web >> ~/tj-logs/tj-web.log 2>&1`
(if you open them with `>`, the process keeps writing at its old position even after `tools/rotate_logs.sh` truncates the file, so the size does not shrink). To stop = Ctrl+C in each terminal.
Even without pm2, the status panel tells you which unit has stopped from the `state/runner_<unit>.json` (pid, time) each unit leaves.

### 5) First run — how long it takes and where to look

- At first, each wallet is fetched back over the **last 5 months** (backfill). Numbers on the screen keep changing meanwhile.
- Time it takes (based on this repository's measured model `seed/coverage/speed_model.json`, free limits):
  - Etherscan-family chains: a few seconds to a few tens of seconds per wallet · chains without an Etherscan key such as Base and Optimism: fetched over public RPC — **the most recent transactions show up first, within the first cycle (1–2 minutes)**, and the rest of the last 48 hours and older ranges are filled separately behind it, taking hours to days depending on the wallet and node (new transactions still show right away meanwhile · a fresh install does not use Blockscout as its first collection path)
  - BNB Chain: 5 months ≈ 20–25 minutes regardless of the number of wallets (latest blocks from the first cycle · old history in a side lane) · Solana: about 0.4 seconds per transaction (1,000 ≈ 7 minutes — the last day's transactions show first at the first check and old history continues behind)
  - Exchanges: Upbit past fills are fetched one 7-day window per minute, so a few months take tens of minutes — foreign exchanges are similar
  - With many wallets and trades it can take **several hours**. After that only increments are fetched, keeping up within 1 to a few minutes.
  - While old history is being filled, the Etherscan, Helius and node keys **first set aside the share for checking new transactions (actual usage plus a margin)** and put the remaining limit into old history — even on the first day, new transactions usually show within a few minutes.
- Where to look:
  - **Status bar → open status panel** (상태 표시줄 → 상태 패널 열기) at the top of the screen — per-collector 'fetching past records' (과거 기록 수집 중), delays, errors
  - **Settings › Collection limits** (설정 › 수집 한계) — how far each exchange and chain has been fetched and what cannot be fetched (same content as [docs/COLLECTION_LIMITS.md](COLLECTION_LIMITS.md))
  - Logs: `pm2 logs tj-core` · `pm2 logs tj-evm` etc.
- Even before all old history is in (before the first balance reconciliation of that chain or exchange), **today's holdings and total assets show the actual current balance** (venue 'current balance (fetching old records)' (지금 잔고(옛 기록 받는 중)) · for exchanges 'exchange current balance (fetching old records)' (거래소 지금 잔고(옛 기록 받는 중))) — most of it usually within a few minutes of starting; **allow about 30 minutes until every initial balance shows** (newly found tokens need a price first · chains the activity check turns on automatically come in after that check). Cost, PnL and past curves become exact once all old history is in, and progress and time left are shown under the dashboard curve.
- Before the backfill finishes, it is normal to see many 'cost unknown' (원가 미확인) items and balance differences. Handle only what is left after it finishes in the **Unmatched** (미매칭) tab.
- Even with Telegram connected, internal bot news such as syncing and fetching past records is not sent to Telegram (status panel only — a single message when everything has been fetched for the first time). Details: [Telegram alert settings](FEATURES.md#텔레그램-알림-설정).

### 6) Opening the screen · viewing from other devices

- On this computer: **http://127.0.0.1:8023/** (the port is `web.port` in `config.json`)
- **Login (on by default)** — the first time you open http://127.0.0.1:8023/ **on this computer**, it starts with **create a password** (10+ characters).
  It then asks for the **setup code** — the contents of the `state/auth_setup_code` file in the install folder (`cat state/auth_setup_code` · a 0600 file readable only on this computer ·
  deleted once used). This stops someone outside from creating the first password before you behind a proxy that does not add headers.
  After that, it asks for the password on any device. Once logged in, a device stays logged in for 30 days, and it asks again after 7 days without use
  (`web.login.session_days` · `idle_days`).
  - Change password · log out on all devices · log out = **Settings › Login** (설정 › 로그인) on the screen. 5 wrong attempts in 10 minutes lock it for 15 minutes (doubling when repeated, up to 24 hours) — attempts through a proxy or tunnel (when the proxy adds headers such as X-Forwarded-*) are counted separately from direct access on this computer, so wrong attempts from outside do not stop you logging in on this computer (changing it with `reset_password.py --set` also clears the lock).
  - If you forgot the password, on this computer run `python3 tools/reset_password.py` (deletes it; then create a new one at /login) or
    `python3 tools/reset_password.py --set` (type it directly in the terminal). A running tj-web notices immediately.
  - To turn it off = `"web": {"login": {"enabled": false}}` in `config.json` → `pm2 restart tj-web` (turning it on or off and changing durations take effect on restart).
    When it is off, anyone who can reach this address can see the screen. If `bind` is `tailscale` or a private IP and login is off, tj-web **refuses to start**
    (because anyone on the same network would see all your assets — to open it anyway, set `"login": {"enabled": false, "allow_lan_without_password": true}` explicitly · not recommended).
  - Units on the same computer (tj-review) pass automatically with an internal token (`state/auth_internal_token`, created anew each time tj-web starts).
    When querying it yourself, pass the header as a file so the token does not stay on the command line (process list):
    `curl -H @<(printf 'X-TJ-Internal: %s\n' "$(cat state/auth_internal_token)") http://127.0.0.1:8023/api/state`
    (works only for direct loopback GETs; refused when proxy headers are attached).
- **When opening it from outside through an HTTPS reverse proxy or tunnel (e.g. a Cloudflare tunnel)** — login must be on (when it is off, every request with proxy headers gets 403).
  - The proxy must send to `http://127.0.0.1:8023`, pass `Host` through unchanged and add `X-Forwarded-For` (the real client IP at the end) and `X-Forwarded-Proto: https`
    (a Cloudflare tunnel does this by default). Put that domain in `web.allowed_hosts`, and if you want links in alerts, add `"public_url": "https://<domain>"`.
  - Requests through the proxy: login required · no first password, internal token or settings changes · an overall login-attempt cap · `Secure` cookie · HSTS ·
    no caching (`Cache-Control: private, no-store` · `Cloudflare-CDN-Cache-Control: no-store`). Login-attempt limits are based on the last `X-Forwarded-For` value (the real client IP).
  - **nginx example** (a plain `proxy_pass` adds no headers — be sure to include the four lines below):
    ```nginx
    location / {
      proxy_pass http://127.0.0.1:8023;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
    }
    ```
    If your proxy cannot add headers, or you want to be certain, set `"web": {"behind_proxy": true}` in `config.json` — every request is then treated as coming through a proxy
    (the first password then cannot be created on the web screen — type it directly in a terminal on this computer with `python3 tools/reset_password.py --set` (run without arguments, it only deletes) · internal-token queries do not work).
    With `behind_proxy`, the login cookie always gets `Secure` (an HTTPS proxy is assumed — behind an HTTP proxy you must set `"login": {"secure_cookie": false}` explicitly to be able to log in, and tj-web then reports it as an error at startup).
  - **Do not open it through a plain TCP relay such as `ssh -R`, `socat`, `tailscale serve --tcp` or `ngrok tcp`.** They add no headers, so requests look as if they were opened
    directly on this computer (creating the first password, the internal token and the attempt-cap exemption become open to the outside). Use only proxies that understand HTTP (ones that add headers — `tailscale serve` and `funnel` add `Tailscale-*`).
  - If the login screen is opened over `http://` and the address is not this computer or a tailnet address, it shows an 'unencrypted address' (암호화되지 않은 주소) warning (the password and cookie travel as is).
- To view it from your other devices such as a phone, turn on [Tailscale](https://tailscale.com) and set `"web": {"bind": "tailscale"}` in `config.json` →
  `pm2 restart tj-web`. It opens only on your devices inside the tailnet (Tailscale encrypts). Binding to a public IP or 0.0.0.0 is refused in code.
  Writing a private IP (192.168.x etc.) directly is not recommended, because the password and cookie travel over HTTP (no encryption) on the same Wi-Fi (tj-web warns at startup).
- **Changing settings** such as entering keys, wallets and Telegram (**Settings › Connections · keys**, 설정 › 연결·키) works **only on a screen opened directly on this computer (loopback) or over the tailnet** (through a proxy or tunnel
  only when `"web": {"setup_allow_proxy": true}`). Even when bound to a private IP, other devices on the same Wi-Fi cannot change settings
  (`"setup_allow_lan": true` only when really needed — not recommended).

### 6-1) Keeping it running on a (Linux) server

On a laptop, the public IP changes when you take it out, so **exchange queries get blocked** (IP whitelist), and collection stops when you close the lid.
If you want it always on, putting it on one fixed-IP server is easier.

| Item | Recommended |
|---|---|
| Specs | At least 2 cores · 4 GB RAM · 40 GB SSD (tens of wallets) / comfortably 4 cores · 8 GB RAM · 80 GB SSD or more (hundreds of wallets, several chains) |
| Actual usage (reference) | Usually about 1.3–2.5 GB RAM for all units together (the largest is the screen server tj-web) · CPU 10–20% of one core · only the first backfill and rebuilds use one core for a few hours |
| Core allocation (automatic) | With 2+ cores the screen build runs in a tj-web child process; with 4+ cores the highest-numbered core is dedicated to that build (the other units stay on the other cores) — turn off with `TJ_BUILD_PROC=off` ([advanced settings](CONFIG.md#고급-설정)) |
| Operating system | Ubuntu 24.04 LTS (22.04 or later works with its default python3) — no Python packages to install |
| 4 GB RAM server | Create 4 GB of swap (in case screen builds pile up) |
| IP | **Fixed public IP** — put that IP in the whitelist of your exchange API keys |
| Time zone | Set it to `Asia/Seoul` so log times match the screen |
| Disk | The ledger (`state/ledger.db`) and regular backups grow, so keep at least 20 GB free |

Steps:
1. Prepare `git` and `python3` (· optionally `nodejs`/`npm` → `npm install -g pm2`) on the server, and as a regular service user follow [2)–4)](#2-download--install-check) above as is.
2. `pm2 start ecosystem.config.js` → after checking, `pm2 save` → run the command `pm2 startup` prints, and it starts automatically after reboots too.
3. **Keep the screen open only on 127.0.0.1, as by default.** Do not open the port directly to the internet (firewall: SSH only).
   - For a quick look by yourself: on your computer `ssh -L 8023:127.0.0.1:8023 user@server` → http://127.0.0.1:8023/ in your computer's browser (create the first password this way too).
   - From anywhere, e.g. a phone: the **HTTPS reverse proxy or tunnel** in 6) above (Cloudflare tunnel etc. — login required) or Tailscale.
4. Check that you replaced the exchange keys with keys whitelisted for the server IP, and that exchange sync is green in the status panel.
5. Backup: regular ledger backups stay on the same server disk, so turn on the [second backup off the server](OPERATIONS.md#백업--복구) (`tools/offsite_backup.py`), and keep `.env` and `config.json` separately.
6. Log cleanup: with pm2, `pm2 install pm2-logrotate` (recommended); otherwise put `bash tools/rotate_logs.sh` in cron — **use only one of the two** (check first with `--dry-run` · `-h` for usage).

### 7) Troubleshooting — 5 common questions

1. **The screen does not open** — check with `pm2 ls` that `tj-web` is online, and whether `pm2 logs tj-web --lines 50` shows errors
   (if you started it directly without pm2, the output of the terminal where `src/unit_runner.py web` runs).
   If another program is using port 8023, change `web.port` in `config.json` and `pm2 restart tj-web` (the log has one line '포트 … 을(를) 다른 프로그램이 쓰고 있어요' (port … is used by another program)).
   The `TJ_PORT` environment variable is for the demo (`--demo`) only — the normal run port is `web.port` alone, and the daily review, health check and password-reset tools read the same value.
2. **Saving an exchange key is refused / sync has stopped** — keys with trade, withdrawal or transfer permissions turned on are refused (issue a new one with view only).
   Check that the IP whitelist contains this computer's current public IP (if you take a laptop out, its IP changes and the key is refused).
3. **Solana wallets are not picked up** — if `TJ_HELIUS_KEY` is empty, the Solana collector only waits. Enter it in Settings › Connections · keys (설정 › 연결·키).
4. **Many cost-unknown items and balance differences** — normal during the backfill. After it finishes, handle what is left in the **Unmatched** (미매칭) tab with 'apply cost' (원가 적용), 'estimate at the price then' (당시 시세로 추정) or 'treat PnL as 0' (손익 0 처리).
   Cases where an exchange API does not give old records (e.g. OKX fills about 4 months, Bybit 2 years) are listed in [docs/COLLECTION_LIMITS.md](COLLECTION_LIMITS.md).
5. **'Origin check failed' (출처(Origin) 확인 실패) or 'CSRF token mismatch' (CSRF 토큰 불일치) (403)** — write requests are accepted only from the same screen. Refresh the page.
   Changing settings with outside tools such as `curl` is deliberately blocked.

---
