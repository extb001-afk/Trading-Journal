# API 키 받는 법

tj-bot 은 **무료 키와 공개 노드만으로** 돌아가게 짜여 있어요. 꼭 넣을 키는 넷 — Solana 지갑이 있으면 **Helius**, EVM 지갑이 있으면 **Etherscan**·**Alchemy**·**Ankr**(모두 무료 · EVM 키 셋은 없어도 돌지만 경고가 떠요).
나머지 키는 더 빨리·더 넓게 받게 해 줄 뿐이고, 탐색기·시세·노드 키는 공표 한도의 80% 를 기준으로 몫을 정해 천천히 부릅니다.
모든 키는 저장할 때 읽기 전용 1콜로 연결을 확인해요 — 서비스가 키를 거부하면(401·403) 저장하지 않고, 연결이 안 되면(시간 초과 등) 저장한 뒤 경고만 띄워요.
키는 웹 **설정 › 연결·키** 에 붙여 넣으면 `.env`(권한 600)에 저장되고, 화면에는 •••• 로만 보입니다(거래소 공개 API 키만 끝 4자리).
키 값은 로그·상태 파일·화면 응답·`config.json` 어디에도 남기지 않습니다 — 코인게코·오픈시·거래소 키는 요청 헤더로 보내고(거래소는 서명), Helius·Etherscan 키와 노드 키(Alchemy·Ankr·NodeReal·QuickNode)는
서비스가 정한 대로 요청 주소(쿼리 `api-key`·`apikey` · 경로) 안에 넣되 그 주소는 메모리에서만 만들고 오류·로그·상태 패널에는 호스트 이름만 남깁니다(텔레그램 봇 토큰도 같은 방식).

| 키(`.env` 이름) | 꼭 필요? | 무료? | 어디에 쓰나 | 없으면 |
|---|---|---|---|---|
| `TJ_HELIUS_KEY` | Solana 지갑이 있으면 **필수** | 무료 플랜 | Solana 지갑 옛 기록·토큰·NFT 수집, 새 거래 확인의 백업 | Solana 지갑을 못 받아요 |
| `TJ_ETHERSCAN_KEY` | EVM 지갑이 있으면 **필수**(경고만 · 막지는 않음) | 무료 | Ethereum·Arbitrum·Polygon 거래를 빠르고 빠짐없이 · NFT 자동 발견(블록스카웃이 없는 체인) | 공개 노드(RPC)로 받아요 — 최신 거래는 바로, 옛 기록은 천천히 |
| `TJ_ALCHEMY_KEY` | EVM 지갑이 있으면 **필수**(경고만 · 막지는 않음) | 무료(월 3,000만 CU) | 지갑이 주고받은 토큰 전부 + 지금 잔고 찾기(오래 들고만 있던 옛 보유 토큰을 빠뜨리지 않게) | 수집은 돌지만 옛 보유 토큰 찾기가 약해져요(탐색기 한 곳만) |
| `TJ_ANKR_KEY` | EVM 지갑이 있으면 **필수**(경고만 · 막지는 않음) | 무료 Freemium | 오래 안 쓴 지갑에 들어온 토큰 10분마다 확인 · BNB Chain·Base 옛 기록(아카이브) 가속 · BNB Chain 에 남이 그냥 보낸 BNB 찾기(옛 블록 잔고) · 토큰 찾기 보조(Advanced API) | 무료 공개 노드로만 — 늦을 수 있어요(1시간 확인이 받쳐 줌) |
| `TJ_COINGECKO_KEY` | 선택 | Demo 무료 · Pro 유료 | 코인게코 시세 · DEX 토큰 시세 · 원가·차트 시세 · NFT 바닥가 | 전부 무키(공용 무료 한도)로 — 느리고 막히기 쉬워요 |
| `TJ_OPENSEA_KEY` | 선택 | 무료 신청 | EVM NFT 바닥가 최우선 출처 | 코인게코 NFT 로 |
| `TJ_NODEREAL_KEY` · `TJ_QUICKNODE_BSC_KEY` · `TJ_QUICKNODE_BASE_KEY` | 선택 | NodeReal 무료 키 · QuickNode 유료 | BNB Chain·Base 옛 기록(아카이브) 노드 — 무료 키는 월 한도의 80%(백필 때 실시간 몫을 남기고 하루 몫의 최대 10배까지 당겨 씀 · 최근 31일 합 80% 안), 유료는 사용 비율(기본 10%) 안에서만 | 공개 노드로 — BNB Chain 은 공개 노드 보관 기간까지만 |
| 거래소 키(업비트·빗썸·바이낸스·바이빗·OKX·쿠코인·게이트) | 선택 | 무료 | 그 거래소 잔고·체결·입출금 | 그 거래소는 안 받아요 |
| `TJ_TG_TOKEN` · `TJ_TG_CHAT` | 선택 | 무료 | 텔레그램 알림 | 알림 없이 화면만 |

---

## Helius — `TJ_HELIUS_KEY` (Solana)

1. https://dashboard.helius.dev 에 가입(무료 플랜).
2. **API Keys** 에서 키를 복사.
3. **설정 › 연결·키 › 탐색기 키 › Helius** 에 붙여 넣고 저장.

- 쓰는 곳: Solana 지갑의 거래·잔고·토큰, Solana NFT 자동 발견.
- **새 거래 확인은 무료 공개 노드(publicnode)가 먼저** 하고, 응답이 없거나 이상하면 같은 요청을 Helius 로 다시 보내요. 공개 노드는 최근 약 18시간만 보관해서,
  마지막 확인이 12시간보다 오래된 주소와 처음 넣은 지갑은 Helius 로 확인하고, Helius 가 주기적으로 공개 노드 결과를 대조합니다.
- **처음 넣은 지갑·오래 꺼졌다 켠 설치는 최근 하루 거래를 먼저**(주소마다 가장 새 100건까지) 받아 보여 주고, 옛 기록은 사이클마다 60초씩 끊어 뒤에서 이어 받아요
  (옛 기록이 실패하거나 몫이 모자라도 최신 확인은 안 막혀요 · 끄기 = `sol.live_first_hours: 0` · 끊어 받기 끄기 = `sol.old_slice_sec: 0`).
- **하루 몫** = 월 크레딧(무료 100만 · 유료면 `config.json` 의 `sol.helius_monthly_credits`)의 80% ÷ 30(무료 기준 약 2만 6천).
  새 거래 확인 몫(실제 사용량 × 1.25 · 하루 몫의 3~10% — 상한 `sol.helius_head_min_pct`)을 먼저 떼어 두고 나머지는 옛 기록에 써요. 무료 플랜이면 아래
  '따라잡기 버스트'처럼 옛 기록에 하루 몫의 **10배(열흘치)까지** 앞당겨 씁니다(최근 31일 합 ≤ 월 80% · 끄기 = `sol.helius_burst: false` ·
  새로 받은 키라면 **설정 › 연결·키 › 탐색기 키 › Helius** 의 '새로 받은 키' 칩을 켜세요 — `state/settings.json` 의 `node_plans.helius.fresh_since` · 키를 바꿔 저장하면 꺼져요).
- 옛 기록 몫을 다 쓰면 옛 구간만 다음 날(UTC 0시 = 한국 오전 9시) 이어 받고, 새 거래 확인은 공개 노드로 계속해요(옛 기록 = Solana 공식 공개 노드 · 공표 한도의 80% 안).
  공개 노드를 끄려면 `sol.head_rpc`·`sol.archive_rpc` 를 `""` 로(그러면 Helius 만 쓰고, 하루 몫이 다 차면 그날 끝까지 쉼).

## Etherscan — `TJ_ETHERSCAN_KEY` (EVM 지갑이 있으면 필수 · 무료 — EVM 가속)

1. https://etherscan.io/myapikey 에 가입 → **Add** 로 키 만들기(무료).
2. **설정 › 연결·키 › 탐색기 키 › Etherscan** 에 저장.

- 쓰는 곳: Ethereum·Arbitrum·Polygon 거래를 빠르고 빠짐없이 받기(키 하나로 여러 체인), 블록스카웃이 없는 체인의 NFT 자동 발견. 무료 키는 Base 를 지원하지 않아요(Base 는 공개 RPC 로 받음).
- **필수지만 막지는 않아요** — EVM 지갑이 있는데 키가 없으면 설정 마법사·키 카드('EVM 필수')·상태 패널에 '이더스캔 키가 필요해요(무료)'가 떠요(텔레그램으로는 안 감).
  키가 없으면 공개 노드(RPC)로 받아 **최신 거래는 바로 보이고 옛 기록은 뒤에서 천천히** 채워요(기록이 사라지지는 않아요 · 새로 받는 체인은 블록스카웃을 수집 첫 경로로 쓰지 않아요).
- **하루 몫** = 공표 무료 한도(하루 10만 회)의 80%(8만 회) · 초당 요청은 공표 3회보다 낮은 2회. 옛 기록을 채우는 동안은 오늘 남은 시간의 새 거래 확인 몫
  (실제 사용량 × 1.25 · 하루 몫의 3~70%)만 먼저 떼어 두고 나머지를 옛 기록에 몰아 써요 — 옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 씁니다.
- 하루 몫을 다 쓰거나 키가 거부되면 그 체인은 공개 RPC 로 이어 받아요(예전부터 블록스카웃으로 받던 설치는 종전처럼 블록스카웃이 살아 있으면 거기로). 이더스캔이 살아나면 알아서 돌아옵니다.

## Alchemy — `TJ_ALCHEMY_KEY` (EVM 지갑 토큰·잔고 찾기 — EVM 지갑이 있으면 필수)

**받는 법**

1. https://dashboard.alchemy.com/signup 에 가입(무료 — 카드 없이).
2. **Create new app** → 네트워크는 전부 켜 둡니다(기본값 — 꺼진 네트워크는 그 체인 조회가 막혀요) → **API Key** 복사.
3. **설정 › 연결·키 › 탐색기 키 › Alchemy** 에 키만 붙여 넣고(주소 `https://…/v2/` 뒤의 값) **연결 테스트**(Ethereum·Base 최신 블록 1번씩) → **저장**.
   재시작 없이 바로 씁니다.

**어디에 쓰나**

- **지갑이 한 번이라도 주고받은 토큰 전부 + 지금 잔고 찾기**(`alchemy_getTokenBalances`) — 오래 들고만 있던 토큰처럼 최근 거래 기록에 안 보이는 보유를 빠뜨리지 않게 합니다.
  Base·Ethereum·Arbitrum·Optimism·Polygon 등 Alchemy 가 지원하는 EVM 체인. 무료 탐색기 색인이 막힌 체인(예: Base)에서 특히 필요해요.
- **감시·옛 기록(백필)은 늘 무료 노드가 먼저입니다.** Alchemy 는 무료 경로가 없거나 너무 느린 곳의 보조로만 씁니다
  (무료 등급의 `eth_getLogs` 는 요청당 10블록이라 큰 백필에는 쓰지 않아요).
- 처음 한 번은 등록 지갑 × 체인을 전부 확인하고, 그 뒤에는 무료 신호(무료 노드의 nonce·잔고·새 거래)로 움직임이 보인 (지갑, 체인)만 다시 묻습니다 —
  안 쓰는 지갑은 0콜.

**얼마나 쓰나**

- 무료 = 월 3,000만 CU · 초당 300 CU(15 요청). 봇은 **월 한도의 80%** 를 31일로 나눈 하루 몫(약 77만 CU)까지만 쓰고, 다 쓰면 그날(UTC)은 멈췄다가
  다음 날 이어서 합니다. 초당도 80% 아래(초당 2요청 · 모든 프로세스 합산).
- **따라잡기 버스트(무료 키만 · Alchemy·Ankr·NodeReal·Helius 공통)**: 실시간(감시·새 거래 확인)으로는 한도를 다 안 쓰니, 백필·첫 전수처럼 밀린 일을
  따라잡을 때 남는 몫을 **하루 몫의 10배(열흘치)까지** 앞당겨 씁니다. 실시간이 실제로 쓰는 양(지난 7일 장부 실측 · 오늘 쓰는 속도)× 1.5 를
  오늘 남은 시간과 앞으로 30일 날마다 먼저 남겨 두고, 그 나머지만 백필에 씁니다 — 실시간이 늘면 그 자리에서 백필 몫이 줄어 물러나요.
  실시간 호출은 백필이 하루 몫을 넘겨 써도 막히지 않아요(그날 실시간 몫 = 하루 몫). **최근 31일 합은 늘 월 한도의 80% 안**(서비스의 한 달 주기를
  몰라도 넘지 않게)이라, 크게 몰아 쓴 날이 31일 창에 남아 있는 동안은 백필이 거의 쉬고 실시간만 돌아요.
  유료 키는 버스트 없이 고른 사용 비율 그대로예요. 설정 칸에 '버스트 중'이 보이면 오늘 평소 몫을 넘겨 쓰는 중이라는 뜻이고, '실시간 하루 약 · 오늘 백필 상한'이 함께 보여요.
  사용 기록이 없는 지난날(이 기능이 생기기 전 · 기록을 시작하기 전)은 평소 몫을 다 썼다고 보수적으로 셉니다 — 그래서 업데이트 뒤 한 달쯤은 버스트가 거의 없어요.
  키를 새로 받아 처음 넣었다면 그 칸의 **새로 받은 키(지난 사용 없음)** 를 켜세요 — 그 전 날들을 0 으로 보고 바로 버스트를 씁니다(자동으로 켜지지 않아요 ·
  키를 다른 값으로 바꿔 저장하면 꺼져요). 다른 곳에서 쓰던 키라면 켜지 마세요. 설정 파일 칸 = `state/settings.json` 의 `node_plans.<서비스>.fresh_since`(`YYYY-MM-DD`, UTC).
- 단가는 Alchemy 공식 CU 표 그대로 셉니다 — `alchemy_getTokenBalances` 20 · `eth_getBalance` 20 · `eth_call` 26 · `eth_getLogs` 60 · `alchemy_getAssetTransfers` 120 · 그 밖 26.
- 오늘 쓴 양 / 하루 몫은 설정 › 연결·키 › Alchemy 칸에 보입니다. 유료 요금제라면 같은 칸에서 **유료 키** 를 고르고 월 한도·사용 비율(10·25·50·80%)을 넣으세요.

**없으면**: 수집·감시는 그대로 돌지만 옛 보유 토큰 찾기가 약해집니다(탐색기 한 곳만 — 그 탐색기가 막힌 체인은 오래 들고만 있던 토큰을 놓칠 수 있어요).
설정 화면·상태 패널에 경고가 뜹니다.

## Ankr — `TJ_ANKR_KEY` (EVM 지갑이 있으면 필수 · 무료 Freemium)

1. https://www.ankr.com/rpc/ 에 가입(무료 Freemium) → **Projects** 에서 API 키.
2. **설정 › 연결·키 › 탐색기 키 › Ankr** 에 키만 붙여 넣고(`rpc.ankr.com/…/` 뒤의 값) 저장 — 저장할 때 Ethereum 최신 블록 1콜로 연결을 확인하고(키 거부 401·403·404 = 저장 안 함 ·
   연결 실패 = 저장 + 경고), BSC·EVM 수집기가 자동으로 다시 시작해요.
- 왜 필수: 오래 안 쓴 지갑에 들어온 토큰을 10분마다 빠르게 확인합니다(Alchemy 무료 키는 한 번에 10블록만 훑어 이 일에 못 써요). 없으면 무료 공개 노드로만 확인해 늦거나
  공개 노드가 막힐 때 빠질 수 있어요(1시간마다 탐색기 확인이 받쳐 줘요). 설정 화면·상태 패널에 경고가 뜨지만 수집은 그대로 돌아요.

- 쓰는 곳: BSC·Base 옛 기록(아카이브 — 한 번에 3천 블록), 같은 키로 토큰 찾기 보조(Advanced API — `rpc.ankr.com/multichain`).
  최신 기록은 평소 무료 공개 노드가 먼저입니다 — 봇을 오래 끈 뒤·새로 설치한 뒤 최근 구간을 따라잡는 동안만 Base 등 RPC 체인의 잔고·nonce 확인을 키 노드(Ankr·Alchemy 등)에 먼저 보내요
  (하루 몫 80% 안 · 넘으면 공개 노드로 · 예: 자주 쓰는 지갑 몇 개를 이틀치 따라잡으면 하루 몫의 절반쯤을 한 번). BNB Chain 잔고 감시가 기록으로 설명 안 되는 BNB 증가(남이 그냥 보낸 BNB·컨트랙트가 보내 준 BNB)를 찾으면
  그 구간을 옛 블록 잔고로 반씩 좁혀요(입금 한 건에 수십 콜 · 하루 상한 · 평소 0콜) — 키가 없으면 공개 노드가 보관한 최근 블록만 훑어요([수집 한계](COLLECTION_LIMITS.md)).
- 쉬는 지갑 토큰 받음 확인: 탐색기로 수집하는 체인(Ethereum·Arbitrum·Polygon·Gnosis·Story 등)에서 한동안 안 쓴 지갑·빈 지갑에 토큰이 들어왔는지
  10분마다 한 번 getLogs 로 묶어(지갑 묶음 — 보통 500개씩) 확인하고, 받은 지갑만 바로 탐색기로 기록해요. Ankr 무료 키가 안 여는 체인·키가 없을 때는 무료 공개 노드로
  (Alchemy 는 이 용도에 안 써요 — 무료 getLogs 요청당 10블록 상한). 설정 `addr_tier.inflow_sec`(기본 600초 · 0 = 끔).
- 무료 = 월 2억 크레딧(노드 요청 200 · Advanced API 요청 700 크레딧). 봇은 80% 아래 하루 몫까지만 쓰고, Advanced API 는 따로 분당 50 한도의 80% 아래로 부릅니다.
- NodeReal(`TJ_NODEREAL_KEY`, https://dashboard.nodereal.io — BSC 옛 기록 · 무료 월 1천만 CU)도 같은 방식이에요(80% 하루 몫).

## CoinGecko — `TJ_COINGECKO_KEY` (데모 또는 프로 — 자동 판별)

**받는 법**

1. https://www.coingecko.com/en/developers/dashboard 에 가입.
2. 무료라면 **Demo** 키를 만들고(가입만 하면 됨), 유료 플랜이 있다면 그 **Pro** 키를 그대로 씁니다.
3. **설정 › 연결·키 › 탐색기 키 › CoinGecko** 에 저장 — 저장·연결 테스트 때 데모인지 프로인지 자동으로 알아냅니다
   (프로는 주소가 `pro-api.coingecko.com` 으로 달라요). 재시작은 필요 없어요.

**어디에 쓰나 — 키 하나를 아래 기능이 같이 씁니다**

| 기능 | 언제 코인게코를 부르나 |
|---|---|
| 지금 시세 | 거래소(바이낸스 → 바이빗)가 값을 못 준 코인만 — 예: 원화 마켓이 없는 업비트·빗썸 코인, Hyperliquid 코인 |
| DEX 토큰 시세 | 온체인 토큰의 DEX 실가(코인게코 온체인 = GeckoTerminal 데이터 · 풀 유동성을 같이 받아 얇은 풀의 튀는 값은 거름) |
| 지난 시세 | 원가(거래소 1분봉이 없는 토큰의 그때 시세), 차트·장기 곡선의 시세 점, DEX 풀 봉 |
| NFT 바닥가 | 오픈시 키가 없거나 실패한 EVM 컬렉션 |

- **시세 순서는 그대로 = 바이낸스 → 바이빗 → 코인게코.** 키를 넣어도 거래소 값이 있는 코인은 코인게코를 부르지 않아요.
- 거래소 값이 있는 코인의 **확인용 조회**(동명 코인 거르기 기준가 등)는 키 몫을 아끼려고 예전처럼 무키로 부릅니다.
- **부족하거나 실패하면 그 콜만 무키로** 다시 부릅니다(예전과 같은 공용 무료 한도). 키 쪽은 잠깐 쉽니다 —
  한도 초과(429)는 1분부터 두 배씩 최대 15분, 키 거절(401·403)은 6시간(설정에서 다시 저장·테스트하면 바로 풀림), 장애는 1분.
  키가 정답으로 '없음'(404)이라고 하면 무키로 다시 묻지 않아요.

**얼마나 쓰나**

- **데모(무료)**: 코인게코 공표 한도(분당 30회 · 월 1만 회)의 80% 아래 — 분당 24회 · 하루 260회.
- **프로(유료)**: 코인게코가 알려 주는 플랜 한도(분당·월)의 **10%** 만 씁니다(기본). 같은 화면의 **사용 비율** 버튼으로 25·50·80% 까지(80% 가 상한).
  한 달 몫은 남은 날에 고르게 나누고, 같은 키를 다른 곳에서도 많이 썼으면 그만큼 줄여 계정 전체가 80% 를 넘지 않게 합니다.
  플랜 한도는 6시간에 한 번 코인게코에 물어 갱신합니다(추적 NFT 가 없어도). 못 읽으면 데모 수준으로 아껴 씁니다.
- 하루 몫은 기능별로 나눕니다 — 지금 시세 50% · NFT 30% · 지난 시세 20% 는 그 기능 몫으로 남겨 두고, 쓰지 않는 기능 몫은 다른 기능이 빌려 씁니다.
  분당 몫의 1/4 은 지금 시세용으로 남기고, 지금 시세는 한 시간에 하루 몫의 1/24 까지만(하루 몫을 한꺼번에 쓰지 않게).
- 웹·수집기 등 여러 프로세스가 같은 예산 기록(`state/nft_budget.json`)을 함께 써서 합계가 한도를 넘지 않습니다.

**없으면**: 코인게코·GeckoTerminal 을 전부 무키(IP 공유 무료 한도)로 부릅니다. 돌아가긴 하지만 느리고, NFT 바닥가는 처음 몇 시간 걸릴 수 있어요.

## OpenSea — `TJ_OPENSEA_KEY` (NFT 바닥가)

1. https://docs.opensea.io/reference/api-keys 에서 무료로 신청.
2. **설정 › 연결·키 › 탐색기 키 › OpenSea** 에 저장.

- 쓰는 곳: EVM NFT 바닥가를 **오픈시에서 먼저** 받아 작은 컬렉션까지 추적합니다. 없거나 실패하면 코인게코 NFT.
- 오픈시 연결은 공개 문서 기준입니다(키 없이 실호출 시험은 못 함).

## 거래소 키

| 거래소 | `.env` 이름 | 어디서 받나 |
|---|---|---|
| 업비트 | `UPBIT_ACCESS` · `UPBIT_SECRET` | 업비트 › 마이페이지 › Open API 관리 |
| 빗썸 | `TJ_BITHUMB_KEY` · `TJ_BITHUMB_SECRET` | 빗썸 › 마이페이지 › API 관리 |
| 바이낸스 | `TJ_BINANCE_KEY` · `TJ_BINANCE_SECRET` | 바이낸스 › API Management |
| 바이빗 | `TJ_BYBIT_KEY` · `TJ_BYBIT_SECRET` | 바이빗 › API |
| OKX | `TJ_OKX_KEY` · `TJ_OKX_SECRET` · `TJ_OKX_PASSPHRASE` | OKX › API keys |
| 쿠코인 | `TJ_KUCOIN_KEY` · `TJ_KUCOIN_SECRET` · `TJ_KUCOIN_PASSPHRASE` | 쿠코인 › API Management |
| 게이트 | `TJ_GATE_KEY` · `TJ_GATE_SECRET` | 게이트 › API Keys |

> **반드시 '조회(읽기)' 권한만 켜고, IP 화이트리스트를 거세요.** 거래·출금·이체 권한은 절대 켜지 마세요.
> 바이낸스·바이빗·OKX 는 저장할 때 권한을 확인해 거래·출금·이체가 켜진 키를 거부하고,
> 권한을 API 로 확인할 수 없는 업비트·빗썸·쿠코인·게이트는 '조회 권한만 켰음' 확인을 눌러야 저장됩니다.
> 그다음 잔고 조회 1콜(읽기 전용)로 키를 확인해, 거래소가 키를 거부하면(401·403 — 틀린 키·IP 화이트리스트 밖) 저장하지 않습니다.

- 쓰는 곳: 그 거래소의 잔고·체결·입출금(무엇을 어디까지 받는지는 [COLLECTION_LIMITS.md](COLLECTION_LIMITS.md)).
- 바이낸스·바이빗·OKX 는 같은 조회 키로 선물 손익과 선물 영수증의 진입·청산 가격도 받습니다(추가 권한 필요 없음 · 바이낸스만 선물 체결 내역을 조금 더 부름 — 공표 한도 80% 안).
- 거래소 공개 시세(달러·원화 시세)는 키 없이 받습니다.

## 텔레그램 — `TJ_TG_TOKEN` · `TJ_TG_CHAT`

1. 텔레그램에서 @BotFather → `/newbot` 으로 봇을 만들고 토큰을 받습니다.
2. **설정 마법사 › 텔레그램** 에 토큰을 넣고 안내를 따르면 채팅 ID 는 마법사가 자동으로 채웁니다.
3. 알림 종류·조용한 시간은 **설정 › 알림 (텔레그램)** 에서 고릅니다.

---

## English

Four free keys are required: `TJ_HELIUS_KEY` when you track a Solana wallet, and `TJ_ETHERSCAN_KEY`, `TJ_ALCHEMY_KEY` and `TJ_ANKR_KEY` when you track an EVM wallet
(for the three EVM keys this is a warning only — collection still runs on public nodes without them: the newest transactions show up right away, old history fills more slowly,
old holdings are harder to find and idle wallets' incoming tokens are checked less often). All other keys are optional. Every key is checked with one read-only call when you save it —
a key the service refuses (401/403) is not saved; a connection failure saves it with a warning.
Paste keys in **Settings › Connections & keys**; they are stored in `.env` (mode 600), shown masked, and never written to `config.json`, state files or
screen responses; URLs in error messages, logs and the status panel are reduced to the host name. Each key is sent the way its service requires: request headers
for exchanges (signed), CoinGecko and OpenSea; the URL key parameter for Helius (`api-key`) and Etherscan (`apikey`); the URL path for the Telegram bot token;
and the endpoint URL for the node keys (`TJ_ALCHEMY_KEY`, `TJ_NODEREAL_KEY`, `TJ_ANKR_KEY`, `TJ_QUICKNODE_BSC_KEY`, `TJ_QUICKNODE_BASE_KEY`). URLs that carry a key
are built in memory only.

- **Helius** (`TJ_HELIUS_KEY`, free plan — https://dashboard.helius.dev): Solana history, tokens and NFT discovery, and backup for new-transaction
  checks (those go to the free publicnode first; Helius cross-checks it). Freshly added wallets get their last day of transactions first (newest 100 per address),
  then old history in 60-second slices per cycle. Daily share = 80% of the monthly credits ÷ 30; a new-transaction share (measured use × 1.25, 3–10% of the day,
  capped by `sol.helius_head_min_pct`) is kept and the rest goes to old history — on the free plan old history may burst up to 10x the daily share
  (rolling 31 days stay under 80%; `sol.helius_burst: false` turns it off).
- **Etherscan** (`TJ_ETHERSCAN_KEY`, free — https://etherscan.io/myapikey): fast and complete Ethereum/Arbitrum/Polygon history (the free key does not
  cover Base, which is read from public RPC); NFT discovery where no Blockscout exists. Daily share = 80% of the published 100k/day, at most 2 requests/s;
  while old history is filling, a new-transaction share (measured use × 1.25, 3–70% of the day) is kept and the rest goes to old history. Without the key,
  or when it is refused or the share runs out, that chain continues on public RPC (installs that already used Blockscout keep it if it is up; a fresh install
  never starts on Blockscout) and returns to Etherscan by itself once Etherscan recovers.
- **Alchemy** (`TJ_ALCHEMY_KEY`, free 30M CU/month — https://dashboard.alchemy.com/signup): finds every token a wallet ever touched plus current
  balances (`alchemy_getTokenBalances`) so long-held tokens are not missed. Watching and backfill stay on free nodes; Alchemy only helps where no free
  path exists. One full pass at first, then only (wallet, chain) pairs that free signals show as changed. Metered with the official CU table under a
  daily share of 80% of the monthly limit (and 80% of the per-second limit); the key is read on every call, so saving it needs no restart.
- **Ankr** (`TJ_ANKR_KEY`, free Freemium — https://www.ankr.com/rpc/ — required for EVM wallets: 10-minute incoming-token checks for idle wallets)
  and **NodeReal** (`TJ_NODEREAL_KEY`): faster BSC/Base archive backfill and old-block balances for the BNB Chain balance watch (finds plain BNB sent to you
  or paid out by contracts — a few dozen calls per deposit, daily cap, zero calls otherwise; without a key only recent blocks are scanned); the
  same Ankr key also backs token discovery (Advanced API, 700 credits per request). Each keyed service has its own daily ledger capped at 80%.
  While an RPC chain such as Base catches up on recent blocks (after a long stop or on a fresh install), balance/nonce checks go to a keyed node first
  (Ankr, Alchemy, …; within the daily share, public nodes when it is used up — e.g. two days of catch-up for a few active wallets may use about half of one day's share once);
  otherwise public nodes come first.
  Ankr also runs the 10-minute "tokens received by resting wallets" check (one batched `eth_getLogs` per chain, recipient topic = your wallets;
  public nodes when the key is missing or the chain is not open on the free plan; never Alchemy — its free getLogs is capped at 10 blocks).
  Config `addr_tier.inflow_sec` (default 600, 0 = off).
- **Catch-up burst** (free keys only — Alchemy, Ankr, NodeReal, Helius): backfill and first full passes may use up to 10x the normal daily share
  (ten days' worth). The real-time load measured in the ledger (busiest of the last 7 days, or today's pace) x 1.5 is reserved first for the rest of
  today and for each of the next 30 days; only the remainder goes to backfill, and it shrinks at once when real-time use grows. Real-time calls are never
  blocked by backfill use. The rolling 31-day total always stays under 80% of the monthly limit. Paid keys never burst. Etherscan (daily limit) keeps
  only today's measured real-time share (x 1.25, at least 3% of the day) while backfilling.
  Past days with no usage record (before this feature recorded them) count as a full normal day, so bursting is rare for about a month after
  upgrading — unless you mark the key "new key (no past use)" in its settings card (`node_plans.<service>.fresh_since` = `YYYY-MM-DD` in
  `state/settings.json`; never set automatically, cleared when a different key value is saved).
- **CoinGecko** (`TJ_COINGECKO_KEY`, free demo or paid pro — https://www.coingecko.com/en/developers/dashboard, plan auto-detected):
  one key shared by CoinGecko USD prices for coins no exchange priced (Binance → Bybit → CoinGecko order unchanged), DEX token prices
  (CoinGecko on-chain / GeckoTerminal data, pool liquidity included for the thin-pool guard), historical prices for cost basis and charts,
  DEX pool candles, and NFT floors. Cross-check lookups for coins an exchange already prices stay keyless. When the key's share runs out or
  the key fails (429 / 401 / 403 / outage), that single call falls back to the old keyless request and the key rests for a while.
  Demo = 24/min, 260/day (below 80% of the published 30/min, 10k/month). Pro = 10% of the plan limits by default (25/50/80% selectable,
  80% hard cap), plan limits refreshed every 6 hours. The daily share is split live prices 50% / NFT 30% / historical 20% (idle shares are
  borrowed), and all processes share one budget file.
- **OpenSea** (`TJ_OPENSEA_KEY`, free application — https://docs.opensea.io/reference/api-keys): first source for EVM NFT floors.
- **Exchanges**: read-only keys with an IP whitelist only; keys with trade/withdraw/transfer permissions are refused where the exchange lets us check.
  Binance, Bybit and OKX keys also feed futures PnL and the futures-receipt entry/exit prices (no extra permission).
- **Telegram** (`TJ_TG_TOKEN`, `TJ_TG_CHAT`): create a bot with @BotFather; the setup wizard fills the chat id.
