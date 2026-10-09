# 변경 내역 (Changelog)

판마다 더해진 것과 바뀐 동작이에요. 지금 쓰는 법은 [README.md](README.md), 화면 사진은 README 의 '화면 미리보기'에 있어요.
업데이트는 README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`) 하세요.

## 2026-10-09 밤 — 외부 수정 검증 반영

**원장 손상 대기·버전 표시 · 복구 도구 · 최초 인식 시가 안전장치 · 수수료·브릿지 규약 · 재생 순서 · 선물·청산 감시 · 곡선 마감가 · 새 LP 바로 평가 · 웹 느린 연결 방어 · 화면 ·
분류 보류 거래 · 미검증 DEX 가격·환율 시각 · 대표 심볼 '확인 필요'·정품 등록 · 원가 넘기기 · 거래소 서버 시각·쿠코인 HF · 체인 수집기 · 대시보드 LP 카드**

지난 판(2026-10-09 오후)을 다시 검증한 외부 검토를 하나씩 재현해 보고 진짜인 것을 고친 판이에요 — 1차 = 새 지적과 '먼저 고칠 것', 2차 = 지난 지적 중 아직 '안 고쳐짐'·'일부'였던 것(숫자가 틀리는 것부터).
사진은 지난 판 그대로예요(대시보드 LP 카드 위치는 사진과 달라요).

> **업데이트** — README [업데이트](README.md#업데이트) 순서대로(멈추기 → 백업 확인 → `git pull` → `bash tools/setup.sh` → `pm2 start ecosystem.config.js`). 재구축은 필요 없어요.
> 이 판부터 설정 맨 아래에 버전(`VERSION`)이 보이고, 원장에 **데이터 개정 번호**(`meta` 의 `data_rev`)를 적어요 — 이 판 = 데이터 개정 1(선물 정산 재배치를 적용할 때 기록).
> 이 번호를 모르는 예전 판 코드는 그 칸을 무시하므로, 이 판에서 되돌릴 때는 코드만 되돌리면 돼요. 최초 인식 시가 안전장치·수수료 규약·원가 넘기기 정리로 실현손익·명세 숫자가 조금 바뀔 수 있어요.
> 수집기 쪽 고침(BSC 매도 대금 · 빗썸 과거 지정가 체결 시각)은 새로 받는 거래부터예요. 이미 원장에 있는 분류 보류 거래의 잔고 변화는 재구축([백필 · 재구축](README.md#백필--재구축--재백필)) 때 들어가요.

**1차 — 새 지적 · 먼저 고칠 것**

- **원장 지키기·상태** — 깨진 원장은 띄우지 않고 '원장 손상 — 복구 필요'로 기다려요(띄우기 전 가벼운 검사 · 작은 원장은 `quick_check` 까지 · 큰 원장은 tj-core 가 곧바로 죽으면 그때 ·
  손상 오류가 난 기록은 격리하지 않고 멈춤). 원장 없음·손상·감시 유닛 꺼짐을 화면 위 배너로 알려요(tj-alert 없이도). pm2 없이 돌려도 멈춘 유닛·처음부터 실패하는 수집기·빈 시세를 알아채요
  (각 유닛이 `state/runner_<유닛>.json` 에 30초마다 기록). 디스크 부족으로 백업을 건너뛴 채 30시간이면 빨강 + 텔레그램 · 버전 표시(`VERSION` · `/api/health`)·데이터 개정 번호.
- **복구 도구** — `tools/ledger_restore.py` 가 EVM 기준 블록을 실제 원장(들어온 시각)에서 찾고, 기준이 없는 RPC 커서는 블록 시간으로 넉넉히 되감아 미리보기에 ★ 로 알려요 ·
  RPC 로 받은 체인은 백업 뒤 방출했던 거래를 해시로 다시 받아 로그 없는 송금도 채워요 · 원장 밖 사본 되돌리기(`ledger_restore.py files` · 깨진 사본이 하나라도 있으면 전체 거부) ·
  미리보기에 백업 뒤 생긴 판정 수 · 되돌리기 전 원장은 최근 2개만 보존(`--keep-pre`) · 깨진·0바이트 백업은 '열기 실패' · 저장소에 없는 도구를 가리키던 안내 고침.
  서버 밖 백업은 scp 제한 시간·보낼 도구(rsync/scp)와 받는 쪽 rsync 확인 · 압축만 하고 암호화하지 않는다는 안내 · 처음 접속 때 호스트 키 자동 수락을 문서에.
- **최초 인식 시가 안전장치** — 보냈다 같은 주소에서 돌아온 코인은 보낼 때 원가를 이어받고, 확인 안 된 컨트랙트 토큰과 실제 매도가의 10배 넘는 시세는 매기지 않으며(원가 미확인 + 검토),
  한 번 매긴 값은 고정해요(`state/first_seen_px.json` · 원장 밖 백업에도 포함 · 시세를 기다리는 동안 '시세 대기'). 받은 날 판 몫은 판 값이 원가 · 시세 없는 가스는 검토 행 ·
  폰 카드·보유 줄 '추정' 표시와 처음 한 번 안내 · 이름은 '최초 인식 시가' 하나로.
- **수수료 원가 규약** — 가스 반영을 꺼도 수수료로 쓴 코인(가스·거래소 출금 수수료)의 시가 − 원가 차익은 실현에 반영해요(스위치는 비용만 정함 · 끄면 출금 수수료도 가스·수수료 탭에 따로).
  브릿지 수수료도 같은 규약(떼인 코인의 처분 손익은 늘 실현 · 시가 비용은 켬일 때만 · 끄면 가스·수수료 탭 출발 체인 줄에). 가스 규칙 '시가 미상'에 출금·브릿지 수수료가 음수로 섞이던 것,
  자금 흐름 지도의 출금·브릿지 수수료 중복, 환율 기록 없는 시각의 수수료 처분 행에 생기던 가짜 원화 환차를 고쳤어요 · 스테이블 '추정' 표기는 거래소·지갑 이동 뒤에도 붙어요(숫자 무변) ·
  명세 안내 '가스·수수료 탭 전체'에 거래소 출금 수수료도 들어가요.
- **재생 순서·브릿지·스왑** — 같은 블록은 원본의 tx 순번·로그 번호로, 같은 초 묶음은 아무도 모자라지 않는 순서로 재생해요 · 브릿지 도착이 출발보다 10분까지 먼저 찍혀도 짝 ·
  컨트랙트가 다른 비슷한 수량 후보가 둘이면 짝을 보류(검토) · 시세 없는 다리가 여러 개인 스왑은 원가를 시세 비례(없으면 균등 · 추정)로 나눔 · 브릿지 예치 증서는 낸 토큰 원가를 이어받음(화면 계산만 · 원장 무변).
- **선물·청산 감시** — 선물 정산 자산(BNB 수수료·코인 마진)은 그 자산으로 기장하고 화면은 달러 환산 · 선물 정산 재배치: 되돌리면 `--apply` 전까지 자동 적용 안 함 · 적용 전 원장 백업 ·
  준비된 거래소부터(대기 거래소는 상태 패널 '선물 재배치 대기') · 대기 시작 시각은 재시작해도 이어받음. 잔고 대사 표본에서 바이낸스 선물 지갑 몫을 빼고, 표본이 1시간 연속 다르면 반영(상태 패널).
  청산 감시: 한 번이라도 읽은 거래소는 권한 오류도 10분 뒤 주황 · 1시간 넘게 못 보면 한 번 알림 · 5~30분 간격 재시도 · 1단계 위험 구간도 다시 알림 · 재진입 알림은 최소 15분 간격 ·
  목표가·손절은 낡거나 멈춘 가격으로 판정하지 않음('감시 불가'). 1회 도구(`exf_fut_place.py` · `latefix_move.py`)의 `-h` 는 사용법만 보이고, 적용은 유닛이 멈췄는지 확인해요.
- **곡선** — 옛 마감 변환은 빗썸 원화만 더함 · LP 없는 현금도 처음 관측 전은 0 · 장기 곡선은 첫 기록 날부터 · 그날 마감가는 그 시각까지의 정보만(보간·미래 종가 금지 · 받아 둔 지난날은 그대로).
- **LP** — 방금 예치한 LP 포지션을 바로 평가해요(정기 갱신을 기다리는 동안 20초마다 '원장에 있고 평가가 없는' 열린 포지션만 · 종전엔 다음 갱신까지 총자산이 원금만큼 줄어 보였어요).
- **웹 서버** — 느린 연결 방어: 요청 줄 + 헤더는 10초 안에 · 루프백이 아닌 주소는 IP당 동시 연결 32(`web.max_conn_per_ip`) · 대기열 128 · 로그인 전 요청 본문도 크기에 맞춘 제한 시간 ·
  데모 서버도 같은 상한. `.env` 가 BOM 으로 시작해도 첫 키를 읽고, `/api/day_events` 를 조건 없이 부르면 최신순 5,000건 페이지로 줘요.
- **화면** — 첫 설치 카드는 Solana 지갑이 있을 때만 Helius 를 요구 · 카드 닫기·설정에서 다시 보기 · 마법사 단계 새로고침 유지 · 폰 양도차익 명세 큰 금액 겹침·잘림 없음 ·
  대시보드 배경 갱신이 글자 선택을 지우지 않음 · 명세 카드에 '스테이블 환차손익' 카드(식이 맞게) · '스테이블 환차는 명세에만(실현손익엔 없음)' 문구 · 머리 상태 칩 짧게 · 시트 안 Tab 순환 ·
  펼친 사이클 금액 표기 통일.
**2차 — 지난 지적 중 '안 고쳐짐'·'일부'였던 것**

- **분류 보류 거래** — 분류 보류(UNKNOWN) 거래도 지갑 잔고 변화를 기록해요(시세 없이 원가만 넘김 — 손익 없음 · 내 지갑끼리는 위치 이동) · '분류 보류' 검토를 원장에서 늘 읽어 지난 기록도 보여요 ·
  일별 순유입에선 입출금이 아니라 매매로 봐요.
- **가격·환율** — 풀 유동성을 모르는 DEX 가격은 '미검증'으로 총자산·알림에서 빼요(지금 쓸 가격이 OKX DEX 값과 10% 안일 때만 인정 · 유동성 값이 낡아도 마지막 값이 얇으면 계속 제외) ·
  원화 환율을 받은 시각과 함께 두고 1시간 넘게 못 받으면 그날 마감을 미뤄요(그날은 그 시각 1분봉 환율로 닫힘 · 고정 대체값은 마감·곡선에 저장 안 함).
- **대표 심볼 '확인 필요' · 정품 등록** — USDT·WBTC 같은 대표 심볼인데 정품 목록에 없는 컨트랙트를 심볼만으로 숨기지 않아요 — 유동성 있는 시세·거래소 출금 도착이면 정품,
  아니면 '값 없는 토큰'에 **확인 필요** 배지(확인 전 평가 0 · 총자산·기록·알림 밖). 배지의 [정품으로 등록] = 사용자 정품 목록(`state/genuine_tokens.json` · 원장 밖 백업에 포함) —
  등록한 대표 스테이블은 액면 $1, 남이 보낸 토큰의 '에어드랍 의심' 격리도 풀어요(고플러스 스캠 확증은 그대로). 알림의 사칭 판정도 같은 유동성 기준이고, 내가 서명해 보낸 거래는 사칭으로 지우지 않아요.
- **Katana vbUSDC** — Vault Bridge USDC 를 계약 주소 기준 검증 스테이블(액면 $1 · USDC 묶음)로 — 원가 기록 없이 받은 vbUSDC 와 그것으로 산 코인의 원가가 추정 시가 대신 액면,
  처분은 명세 스테이블 원화 환차 표로(같은 이름의 다른 계약·다른 체인은 그대로).
- **원가 넘기기** — 시세 없는 다리 여러 개 스왑에서 같이 받은 시세 있는 코인·스테이블 잔돈은 그 시각 시가만 원가로(나머지는 시세 없는 코인에) · 한쪽만 시세 있는 스왑의 시세 없는 다리 여럿도
  시가 있는 쪽 합을 나눠 원가·정산액으로('추정' 표시 · 시세를 쓰는 쪽 = 네이티브·거래소 자산·정품 계약만) · 경제 가치 없는 동반 토큰(BNB Chain 스테이킹의 govBNB 같은 투표권 토큰 —
  `seed/zero_value_companions.json` · 이 설치 덧붙임 = `state/seed_local/zero_value_companions.json`)은 원가 나눔 가중 0, 스왑 가스도 실제 증서 쪽에 ·
  브릿지 예치 증서와 같이 받은 가스 환불 잔돈이 증서 원가 승계를 막지 않아요(화면 계산만 · 원장 무변).
- **거래소 수집** — 바이비트 붙은 심볼을 거래소 공개 종목 목록(하루 1회)으로 나누고, 대금 통화를 모르면 유령 코인 대신 체결 보류 · 새 설치·첫 연결 때 바이낸스·바이비트·쿠코인·OKX 옛 출금에도 수수료 반영 ·
  대사가 토큰 자릿수 18 을 지어내지 않음 · OKX 명목가를 모르면 '—'. 서명 시각을 거래소 서버 시각에 맞춰요(1시간마다 · 시각 오류 때 다시 재고 1번 재시도) · 쿠코인 고빈도(HF) 계정 체결 수집
  (일시 실패한 구간은 다음 주기에 이어 받음) · 바이낸스 선물 수익이 같은 ms 에 1,000줄 넘어도 페이지를 넘겨요 · 빗썸·업비트 과거 창 지정가 주문을 마지막 체결 시각으로 · OKX·쿠코인·게이트 마진 체결은 수집하지 않음을 문서에.
- **체인 수집기** — BSC·추적 없는 RPC 체인의 '내 토큰 → 네이티브' 매도에 받은 네이티브를 기록해요(랩드 풀기 로그 · 방금 거래는 잔고로 확인 — 같은 블록 승인·매도 여럿·옛 구간 합계) ·
  이더스캔 색인 전 직접 풀기의 ETH 수령(소각 Transfer 를 남기는 랩드 구현 포함) · 블록스카웃 delegatecall 줄 제외 · owner 없는 옛 솔라나 응답의 연관 토큰 계정 소유자 계산.
- **미추적 체인 · 지갑 격리** — 미추적 체인 점검이 정식 스테이블(balanceOf)까지 봐서 토큰만 받은 지갑도 찾아요(실제로 추적에 합류한 쌍만 빼고 · 설정에서 끈 체인의 발견은 경고·알림 없이 상세에 '끈 체인 N건') ·
  이더스캔 체인에서 한 지갑 목록 조회가 30분 넘게 실패하면 그 지갑만 보류하고 나머지는 계속 수집해요(회복 때 겹친 거래는 레그 합집합으로 보강).
- **대시보드 LP 카드** — LP 포지션이 큰 표 대신 레버리지 · 대출 바로 아래 카드로 와요(가치 큰 순 앞 2개 + 'N개 더' · 줄을 누르면 제자리 펼침 · 종료된 포지션 링크 · 폰은 목록 줄) ·
  레버리지 · 대출도 앞 2줄 + 'N개 더'.

**함께**

- **문서·저장소** — README [업데이트](README.md#업데이트)·[멈추기 · 지우기](README.md#멈추기--지우기) 절 · pm2 없이 쓸 때 로그는 덧붙이기(`>>`) · `alert_bot` 권장 · Ctrl+C 안내 ·
  [SECURITY.md](SECURITY.md) 에 예외 3가지(증권사 비밀값은 `config.json` · 서버 밖 백업 · AI 요약) · 수집 기록 보존은 기본 8일 · 스트림당 512MiB 상한(보장 기간 아님) ·
  `.gitignore` 에 압축 백업·편집기 사본·키 파일 · 1회 도구 `tools/upbit_trades_fill.py`(업비트 옛 주문의 실제 체결 시각 채우기)·`tools/repair_wrap_legs.py`(직접 감싸기·풀기의 빠진 레그 복구) 공개.
- **시험** — 공개 시험 추가: 원장 손상·데이터 개정·pm2 없는 상태 점검·화면 배너 · 실제 core 로 복구 · 최초 인식 시가 안전장치 · 수수료 비용 끔·브릿지 스왑·출금 수수료 흐름 · 선물 자산·재배치 되돌리기·
  대사 표본·청산 감시 재시도·낡은 가격 · 곡선 시작일 · 느린 연결·로그인 전 본문 · 새 LP 바로 평가 · 1회 도구 인자 · (2차) 분류 보류 거래 · 미검증 DEX 가격·환율 시각 · 대표 심볼 확인·정품 등록 ·
  vbUSDC · 원가 넘기기 n:m · 바이비트 심볼 나누기·첫 연결 출금 수수료·자릿수 · 거래소 서버 시각·쿠코인 HF · LP 카드 — 전체 2,700건 넘게(파일 77개).

**English** — Fixes from an external re-verification of the previous release (night of 2026-10-09). A corrupt ledger is no longer started: units wait with
"ledger corrupt — restore needed" (a light check before start, `quick_check` on small ledgers), and a missing/corrupt ledger or a stopped monitor unit shows as a banner
even without tj-alert; stalled units are detected without pm2 too. The version (`VERSION`) is shown at the bottom of Settings and the ledger now records a data revision
(`meta.data_rev`, revision 1 = futures settlement re-placement); older code ignores it, so rolling back from this release needs the code only. The restore tool finds EVM base
blocks from the real ledger, rewinds RPC cursors by block time when there is no base (marked ★), re-fetches log-less native transfers by hash and can restore off-ledger copies
(`ledger_restore.py files`). First-seen price safeguards: coins coming back from the same address inherit their cost, unverified tokens and prices over 10× the actual sale price
are not used, and assigned values are fixed. Fee-cost rule: the price-minus-cost gain on coins spent as fees (gas, withdrawal and bridge fees) is realized even with gas costs off.
Replay order inside a block follows tx index and log index; bridge matching tolerates arrivals up to 10 minutes early and holds ambiguous candidates. Futures settlements are booked in
their own asset (BNB fees, coin margin); an undone re-placement is not re-applied until `--apply`. Liquidation watch alerts when a venue it has read before is unreadable, repeats
in stage 1 and does not judge targets/stops on stale prices. Day-close prices use only information up to that time. New LP positions are valued right away. The web server limits slow
connections (headers within 10 s, 32 concurrent connections per non-loopback IP). README gains "update" and "stop · uninstall" sections; SECURITY.md lists the three exceptions to
"secrets only in `.env`". Second round (earlier findings still open): unclassified (UNKNOWN) transactions now record wallet balance changes; DEX prices with unknown pool liquidity
count only when they match OKX DEX within 10%, and the day close waits when the KRW rate is over an hour old; major symbols (USDT, WBTC …) on unlisted contracts are no longer hidden
by symbol alone but shown as "needs check" (valued 0 until confirmed; a user genuine list in `state/genuine_tokens.json`); Katana vbUSDC is a verified stablecoin by contract;
cost carry-over for multi-leg swaps without prices (zero-value companion tokens such as govBNB in `seed/zero_value_companions.json`); Bybit symbols split by the public instrument list,
withdrawal fees on first connect, request timestamps synced to exchange server time, KuCoin HF fills; BSC token-to-BNB sales record the BNB received; tracked-chain sweeps see
stablecoin balances and one failing wallet no longer blocks the rest; the dashboard LP table became a card under leverage/loans. Collector-side fixes apply to newly fetched
transactions. Screenshots unchanged (the LP card position differs from them).

**알려진 한계(다음 판에)**

- 코인으로 정산된 선물 손익(바이낸스 BNB 수수료·OKX 코인 마진 등)의 화면 달러 환산은 지금 시세 기준이라, 지난 정산 금액이 시세에 따라 조금씩 움직여 보여요 — 원장은 코인 수량 그대로라 실현손익·명세 숫자와는 무관 · 다음 판에 정산 시각 시세로.
- 외부 RPC·탐색기 응답 본문에 크기 상한이 없어요(비정상적으로 큰 응답 방어 — 다음 판에).

## 2026-10-09 오후 — 외부 전면검토 반영

**선물 정산 = 정산 시각 · 스테이블 원화 환차 · 최초 인식 시가 · 수수료 원가 · 곡선 재설계 · 서버 밖 둘째 백업 · 청산 감시 · 화면·접근성**

직전 공개판 전체를 다시 본 외부 검토(71건)를 하나씩 재현해 보고 진짜인 것을 고친 판이에요. 사진은 지난 판 그대로예요.

> **업데이트 뒤 숫자가 바뀔 수 있어요** — `pm2 restart ecosystem.config.js` 로 모든 유닛을 다시 켜세요. 원가를 모르던 수량에 '최초 인식 시가'(기본 켬)가 붙고,
> 수수료 원가 규약·스테이블 원화 환차가 실현손익·양도차익 명세에 들어가요(추정한 행은 '추정' 표시). tj-core 는 첫 거래소 대사 때 지난 선물 정산을 정산 시각으로 한 번 다시 놓고,
> 30일·장기 곡선은 새 규칙으로 한 번 다시 계산돼요(재구축은 필요 없어요).

- **선물 정산 = 정산 시각** — 거래소 잔고에 합쳐진 선물 지갑(바이낸스·바이빗·OKX)의 실현 손익·수수료·펀딩을 대사하는 날이 아니라 **정산 시각**에 총자산으로 기장해요(지난날로 소급하지 않음).
  업데이트 뒤 첫 대사 때 지난 대사가 다른 날로 보낸 선물 정산을 한 번 다시 놓아요 — 근거(감사 기록·선물 정산 파일)가 모자란 통화는 옛 배치 그대로 두고,
  `tools/exf_fut_place.py` 로 계획 미리보기·되돌리기를 할 수 있어요. 선물 정산 파일이 잔고를 못 덮으면 그 거래소 대사를 미루고(상한 3시간 · 1시간 넘게 미루면 상태 패널 '주의'),
  늦게 찾은 옛 체결의 상쇄는 그 체결 직후에 둬요. 대사 되돌림은 부채 이자를 지우지 않고, 재구축은 선물 정산 금액·시각을 그대로 이어 가요. '선물 미반영' 줄은 아직 대사 전인 정산만이에요.
- **해외 거래소 잔고 대사** — 잔고 응답의 금액 칸이 빠졌거나 목록이 불완전하면 조회 실패로 보고 보류 · 잔고 표본 두 번이 일치할 때만 대사 · 마진 체결·간편전환 일시 실패와 진행 중 출금 동안엔 대사를 미뤄요 ·
  바이낸스 담보대출 담보가 Earn 과 두 번 세이던 것 고침 · 바이낸스를 새로 연결하면 모든 심볼 체결 확인을 마친 뒤 첫 대사.
- **양도차익 명세 — 스테이블 원화 환차** — 스테이블코인을 원화로 산 몫은 산 때 원화를 취득가로 써서 환차손익을 별도 표로 보여 줘요. 원화 기록이 없는 몫(액면 입금·기초 잔고)은 처분 시각 환율(환차 0)이고,
  거래소↔지갑·해외 거래소로 옮겨도 원화 원가 몫과 액면 몫을 따로 이어 가요(수수료로 쓴 몫·오프체인 왕복 포함). 처분 행을 누르면 **환차 상세**(용도 · 처분 환율 · 평균 취득 환율 · 주요 매수 상위 3 · 계산식)가 열려요.
  선물 손익·기타 소득(스테이킹·유동성 보상)도 별도 표 · 추정 행 배지 · 시행일 문구는 날짜 기준 · 원가 방식 설명 · 선물 승률은 '정산 건 기준'으로 표기.
- **최초 인식 시가(기본 켬)** — 원가를 모르는 수량(기초 잔고·원가 없는 입금·에어드랍)의 원가를 그 수량이 장부에 처음 생긴 날 시가로 추정해요. 명세·카드·실현손익 머리에 '추정'으로 표시하고,
  스테이블은 원화 취득가를 그때 환율로, 직접 지정한 원가가 먼저예요. 옛날 날(원장 시작일까지) 시세는 남는 API 사용량으로 천천히 받아 채우고(진행률 = 설정 › 원가 계산),
  '이 중 추정' 실현은 수수료·가스 뒤 금액이에요. 가치를 모르는 스왑으로 이어받은 수량은 스왑 날 시가로 다시 매기지 않아요. 끄기 = **설정 › 원가 계산**.
- **수수료 원가 규약** — 가스·체결 수수료로 낸 코인·거래소 출금 수수료 = 그때 시가만큼 비용 + 원가를 아는 몫의 처분 손익(업비트·게이트·빗썸 출금 수수료 몫의 원가가 사라지던 것 고침 · 명세에도 한 줄씩) ·
  양쪽 시세가 없는 스왑은 원가를 그대로 이어받음 · 브릿지 거래에서 받은 토큰 반영 · 평균가 대체는 그 사이클의 평단만.
- **재생 순서·브릿지 짝** — 같은 초의 매수·매도는 블록 번호·체결 시각(ms)·보유로 순서를 정하고, 브릿지 도착은 id 로 이어진 짝을 먼저 확정한 뒤 수량 98~102%·분할 묶음·같은 컨트랙트 우선·스팸 제외로 짝지어요 ·
  늦게 기록된 거래소 출금도 같은 txid 도착에 원가를 넘겨요(화면 계산만 · 원장 무변).
- **곡선 재설계** — 원장 밖 금액(업비트·빗썸 원화, 업비트 미매칭 코인, LP, Rabby 몫)을 구성요소별 규칙 하나로 계산해 30일 곡선과 장기 곡선이 같은 값을 써요.
  일별 마감 때 구성요소를 따로 기록하고(원화는 원 단위·환율·잔고 시각과 함께), 빗썸 원화도 지난날마다 거래 기록으로 되감은 그날 잔고를 써요(종전 = 지금 잔고를 모든 지난날에).
  한 번 정한 지난날 값은 다시 매기지 않고(옛 계산 동결값만 한 번 규칙대로 다시), 장기 곡선 30일 창 밖 날에도 그날 Rabby 몫이 들어가며, 업비트 미매칭 코인이 원장에 편입돼도 두 번 세지 않아요.
  장기 곡선 순유입에 빗썸 원화 입출금도 넣고, 기록과 실제 잔고가 크게 어긋난 구간은 가까운 실측값을 써요. 누락 레그 재기장·원장 복구 뒤에는 곡선을 다시 계산해요.
- **서버 밖 둘째 백업 · 복구** — 원장 파일이 없는데 예전 원장 흔적(백업·수집 기록)이 있으면 빈 원장을 만들지 않고 기다리며 복구를 안내해요(상태 패널 '원장 파일 없음 — 복구 필요').
  원장 교체는 원자적으로, 수집기 기록(`state/inbox/`)은 읽은 뒤에도 8일 남겨요. 새 도구 `tools/ledger_restore.py`(백업 목록·검사·되돌리기·그 사이 수집분 다시 받기)와
  `tools/offsite_backup.py`(압축 원장 사본을 다른 컴퓨터로 · sha256 확인 · 밖으로 ssh 를 못 나가면 outbox 모드 · 기본 꺼짐) — README [백업 · 복구](README.md#백업--복구).
  정기 백업이 3일 넘게 없으면 상태 패널 빨강 + 텔레그램.
- **청산 감시** — 거래소 조회가 막혀도 마지막 값으로 위험 알림을 보내고, '청산 감시가 <곳>을 못 보고 있어요' 알림·상태 패널 빨강 · 청산가 도달은 늘 한 번 더 ·
  위험 구간이면 1시간마다 다시(`alerts.liq_repeat_min` · 0 = 끔) · 벗어났다 다시 들어오면 다시 알림 · OKX 선물 명목가에 계약 단가 반영 · BTC 비교선이 일별 가격을 제대로 찾음.
- **수집기** — 이더스캔 경로의 직접 감싸기·풀기(WETH·WPOL 등)를 전환으로 기록 · 프록시 내부 호출(delegatecall 등)을 값 이동으로 두 번 세지 않음 ·
  솔라나 옛 응답의 소유자 없는 토큰 줄을 버리지 않음 · 주요 L2·솔라나 정품 브리지 토큰이 '가짜'로 숨겨지던 것 고침 · NFT 1155 중복 줄 개수 ·
  BNB Chain·추적 노드 없는 체인의 수집 한계를 문서에.
- **상태 패널 — 재계산 대기** — 잔고 불일치·원장 음수의 '재계산 대기' 칸에 그 체인 과거 기록 넓히기의 진행률·남은 시간과 '끝나면 원장 자동 재계산으로 사라져요'를 보여 줘요.
  넓히기가 끝날 때까지는 '주의'(주황)이고, 끝났는데도 3일 넘게 남으면 오류(빨강)·알림. 탐색기 ↔ RPC 로 경로가 바뀐 체인의 옛 진행 표식과 하루 넘게 갱신 없는 표식은 '진행 중'으로 보지 않아요.
- **화면·접근성** — 금액 칸 말줄임 없앰(축약·줄바꿈) · 명세 카드 '양도차익(명세 기준)'과 머리 차이 줄 · 첫 설치 안내 카드·수집 전 문구 · 자동 갱신이 입력 중인 글자를 지우지 않음 ·
  설정 마법사 초점·오류 문구 · 숫자만 쳐도 원화 금액 검색 · 접근성(h1·표 머리·토스트·확인 창 초점·차트 점) · 라이트 테마 대비 · 로그인 화면 글꼴·시스템 테마 · 해요체·용어 통일.
- **운영·보안** — `.env` 읽기 규칙 하나로(`export` · `=` 앞뒤 공백 · 같은 따옴표 한 겹) · 연결 수·차트 캐시 상한 · 입력 검사 · 지갑이 아닌 주소(토큰 민트 등) 등록 거부 ·
  손상된 설정 파일은 덮어쓰기 전에 보존 · 격리 재처리 요청은 앞 요청과 합침 · 배경 스레드가 손상된 상태 파일에 조용히 죽지 않음 · 쉬운 오류 문구 · 폴더 권한·인코딩 점검.
- **문서·저장소** — README '백업 · 복구' · 첫 비밀번호의 설정 코드(`cat state/auth_setup_code`) 안내 · 재백필 때 `state/` 는 설치 폴더 밖으로 ·
  [SECURITY.md](SECURITY.md)(보안 문제는 비공개 보고로) · `.gitignore` 에 설치 폴더 안 사본(`state*/`·`config*.json`·`env*.txt`) · CI 는 브라우저 스크립트 문법(`node --check`)도 확인 ·
  수집 한계 문서에 바이낸스 소액 전환(Dust)·바이빗 선물 수수료·펀딩·BNB Chain 내부 이동·추적 노드 없는 체인.
- **시험** — 공개 시험 추가: 선물 정산(재배치·근거 검사·늦은 체결) · 스테이블 환차 · 최초 인식 시가·옛날 시세 · 수수료 원가 · 재생 순서·브릿지 짝 · 곡선 구성요소 · 원장 복구 · 서버 밖 백업 ·
  청산 감시 · 재계산 대기 · `.env` 읽기 — 전체 1,900건 넘게(파일 45개).

**English** — External full-review fixes (afternoon of 2026-10-09; 71 findings on the previous public release reproduced and fixed where real).
Futures settlements merged into exchange balances (Binance/Bybit/OKX) are booked at settlement time instead of the reconciliation day; after updating, tj-core re-places
earlier settlements once (`tools/exf_fut_place.py` previews/undoes it; currencies without enough evidence keep the old placement). Exchange balance reconciliation waits on
incomplete responses, needs two matching samples, and no longer double-counts Binance loan collateral. Capital-gains statement: stablecoin KRW FX gains/losses (KRW cost only
for the part bought with KRW, carried across exchange/wallet moves), a per-row FX detail popup, and separate futures and other-income tables. Unknown-cost amounts are now
valued at the price on the day they first appeared in the ledger ("first-seen price", on by default, marked as estimated; Settings › 원가 계산). One fee-cost rule for gas,
trading-fee coins and withdrawal fees. Same-second replay order and bridge matching are deterministic. Curves: off-ledger amounts (Upbit/Bithumb KRW, unmatched Upbit coins,
LP, Rabby) use one per-component rule shared by the 30-day and long-range curves, Bithumb KRW is rewound per day, and fixed past values are not re-priced.
Backup: a ledger-restore tool (`tools/ledger_restore.py`) and an optional off-site backup (`tools/offsite_backup.py`, push or outbox, sha256-verified); tj-core no longer
creates an empty ledger when an old one is missing. Liquidation watch alerts when it cannot see a venue and repeats in the danger zone. Collectors: direct wrap/unwrap
on the Etherscan path is booked as a conversion. Status panel shows history-extension
progress for "waiting for recalculation". UI/accessibility fixes, `.env` parsing unified, SECURITY.md. Screenshots unchanged. Numbers may change after updating —
restart all units with `pm2 restart ecosystem.config.js`.

## 2026-10-09 새벽 — 3차 검수 반영 · 실현 표기

**그날 카드 '총 실현' = 현물 실현 + 선물 실현 · 그날의 기록 시간순 · 진입 시각 추정 · 검색 돋보기**

- **그날 카드 실현 표기** — 위 칸 이름을 '총 실현'(현물 + 선물)으로, '왜 움직였나'의 실현 줄을 '현물 실현'(LP 수수료·스테이킹 보상 포함) · '선물 실현' 두 줄로 나눴어요.
  두 줄 합 = 위 칸(원화 모드면 칸과 같은 체결·정산 시각 원화 — 종가 환율로 다시 곱한 차이는 '환율' 줄로). 선물 정산 이익이 그날 총자산 변화에 아직 안 든 몫은
  '선물 미반영' 줄로 보여 줄 합 = 전일 대비를 지켜요(선물 지갑은 거래소 잔고 대사로만 원장에 들어와요). 작은 금액이어도 실현 두 줄은 '나머지'로 접지 않아요.
  대시보드 '오늘 무엇이 움직였나'·'M월 한눈에'·곡선 툴팁·자동 요약도 같은 줄이에요(요약의 '큰 요인'에서는 서로 지워지는 선물 짝을 빼요).
- **그날의 기록 시간순** — 선물 정산 묶음 줄이 맨 위 고정이 아니라 그 거래소 그날 마지막 정산 시각 자리에 와요.
- **선물 영수증 — 진입 시각 추정** — 빠진 청산 뒤 같은 가격으로 다시 진입해도 옛 진입 시각을 물려받지 않아요: 그 종목 체결이 7일 넘게 없다가 다시 진입했고
  청산이 그 재진입분만으로 덮이며 잔량이 청산의 2배 이상이면 재진입부터 다시 세우고 '진입 시각 추정'을 붙여요(같은 포지션의 뒤 분할 청산에도).
- **선물 영수증 — 바이빗 펀딩** — 진입 시각을 몰라도 정산 차이가 펀딩 한 번 상한(명목가 3%) 안이면 거래소 가격을 보이고 '펀딩 포함 가능'을 붙여요.
- **화면** — 검색 돋보기가 모든 폭에서 보여요(941~1002px 은 머리 줄이 두 줄).

**English** — Day card: the top tile is now "total realized" (spot + futures) and the breakdown shows "spot realized" and "futures realized" rows that add up to it
(KRW at fill/settlement time; the closing-rate difference goes to the FX row). Futures profit not yet in that day's total assets is shown as "futures not yet reflected"
so the rows still sum to the day's change. Day records list futures settlements in time order. Futures receipts: a same-price re-entry after a missing close no longer
inherits an old entry time (7-day idle rule, marked "estimated"); Bybit settlements without a known entry show the exchange price when within one funding cap.
The search button shows at every width.

## 2026-10-09 — 수정 재검증 반영

**선물 영수증 진입 시각 보호 · 화면(글꼴 자체 제공·폰 일별 배치·원화 목표가) · 운영 안전장치 · 공개 시험 확대 · MIT**

- **선물 영수증 — 진입 시각 보호** — 강제청산·ADL 이 기록에서 빠져도 뒤 거래가 옛 진입 시각을 물려받지 않아요. OKX 한 방향(net) 모드의 강제청산(102·103·106·107)·ADL(125~128)·블록 체결(204·205)을
  청산·체결 행으로 받고, 청산의 진입가가 쌓아 온 진입 체결 평균과 0.2% 넘게 다르면 뒤쪽 진입 묶음으로 다시 세워요(맞는 묶음이 없으면 '진입 시각 모름').
  부분 청산은 진입 묶음 수량도 같이 줄이고, 다시 세우기 작업량에는 상한이 있어요. 바이빗 청산 기록(주문 단위 합산)은 이 평균 검사에서 빠져요.
  업데이트 뒤 OKX 는 최근 3개월을 한 번 더 받아요(한 주기 20쪽까지 · 받은 만큼 저장하고 이어 받음).
- **선물 영수증 — 바이빗 펀딩** — 바이빗 정산 손익에 보유 중 펀딩이 섞여 거래소 가격까지 버리던 것 → 진입 시각을 알고 펀딩 시각을 지났고 차이가 명목가 × 3% × 지난 펀딩 수 안이면 가격을 보여 주고 펀딩 몫(fundIncl)은 따로.
- **선물 영수증 — 거래소 줄로 열기** — 일별 기록의 거래소 줄로 열면 '가격 n/m건' 배지·종목 칩(그 거래소 종목만)·칩 아래 네 칸·청산 목록·펀딩도 그 거래소 기준(서버 `coins[].exStats`) · 「전체 보기」로 전 거래소.
- **선물 영수증 — 폰 머리** — 순위('그날 실현 기여 n위')는 둘째 줄 보조 글, 평균 보유는 한 줄.
- **화면 — 글꼴 자체 제공** — IBM Plex Sans KR·Mono 를 `web/v2/fonts/` 에서 제공(unicode-range 조각 woff2 · 첫 화면은 쓰는 글자 조각만 받음 · SIL OFL 1.1) — Google Fonts 요청 없음 · CSP 에서 구글 주소 뺌.
- **화면 — 폰 일별 기록** — 잔디 → 달력 → 그날 카드 → 그날의 기록 순서(날짜를 누르면 그날 카드로 부드럽게 이동). 데스크톱 배치는 그대로.
- **화면 — 목표가·손절선 원화/달러** — '지금 팔면?'·매매일지 계획 시트의 목표가·손절선을 ₩/$ 칩으로 입력(다른 통화 환산값 표시 · 저장·감시·알림은 달러).
  원화 입력은 지금 환율로 바꿔 저장하고, 손대지 않은 기존 값은 원래 달러 그대로예요. 실제 환율을 못 받았을 때는 달러로만 입력해요. 감시 카드·보유 펼침 줄도 원화 화면이면 ≈₩ 로 보여요.
- **화면 — 대시보드 오른쪽 열** — 자체 스크롤을 없애 페이지를 내리면 끝까지 보여요(열 전체가 화면에 들어갈 때만 따라 내려옴).
- **화면 — 습관·머리 줄·그날 카드** — 비교할 시간대가 하나뿐이거나 비율이 같으면 '가장 잘/안 맞는 때' 대신 중립 안내 · 641~1100px 머리 줄에 검색 돋보기 ·
  남은 시간 표시 3곳 한국 시간 · 그날 카드 큰 숫자를 눌러 전체 금액(숨김·랜덤값 유지) · 자동 매칭 칩 글은 서버가 따로 보냄 · 덮여 안 쓰이던 서랍 CSS 정리.
- **운영** — 설정에서 지운 지갑 이름도 재시작 없이 반영 · 화면 계산 자식의 정상 대기(시간 제한 있는 대기)를 교착으로 오판하지 않음 ·
  바이빗 진입 체결·청산 손익 과거 채움이 만료·무효 커서에서 멈추지 않음(레이트 한도 retCode 10006 은 커서 유지) · SQLite 메모리 통계 끄기를 파이썬 쪽에서 확인해 '끔/못 끔/확인 불가'로 기록 ·
  유닛 러너 메모리 상한(tj-web 기본 3GB · `TJ_RUNNER_MAX_MB_<유닛>` · 0 = 끔) · tools 원장 경로의 `# ? %` 처리 · 옛 화면 경로(/classic·/futures)는 파일이 없으면 새 화면으로 ·
  이더스캔 'unsupported chainid' 도 미지원으로 처리.
- **상태 패널** — '원장 음수 보유'가 과거 기록을 넓히는 도중 늦게 들어온 옛 거래 때문이면 '재계산 대기' 설명을 붙여요(경고는 그대로 — 재계산 뒤에도 남으면 빠진 입금 점검).
  EVM 수집기가 재시작돼도 진행 중인 과거 기록 넓히기를 원장 자동 재계산이 '끝남'으로 착각하지 않아요.
- **시험** — 공개 시험 추가: 선물 영수증(누적 포지션·분할·반전·강제청산 누락·펀딩) · 빌드 분리(교착 판정·폴백) · 노드 키(무료 80%·유료 비율·키를 설정 파일에 안 씀) ·
  화면 스냅숏(버전 키·델타·저장·복원) · 체인 끄기(추천 기준·잠금·자동 끄기 스위치·시세 장애·자동 체인 30일 유예) — 전체 1,300건 넘게.
- **문서·라이선스** — 재구축 때 원장 임시 사본이 `state/` 밖(홈 폴더 · 원장 3배+2GB · `backfill.rebuild_dir` 로 변경)에 생긴다는 안내 · 고급 설정에 `TJ_TENSOR_KEY`·`health.t.build_p95_warn_s`·러너 메모리 상한 ·
  라이선스 = MIT(`LICENSE`).

**English** — Re-verification fixes (2026-10-09). Futures receipts: a missing liquidation/ADL no longer makes later trades inherit an old entry time (OKX one-way liquidation 102·103·106·107,
ADL 125–128 and block trades are now rows; a close whose entry price differs from the running entry average by more than 0.2% re-anchors to the matching recent entries, otherwise
"entry time unknown"; partial closes shrink entry lots; bounded work). Bybit closes that include funding keep the exchange price (funding shown separately). Opening a receipt from an
exchange row scopes the badge, coin chips, tiles and close list to that exchange ("show all" for every exchange). UI: IBM Plex fonts are served from the repo (no Google Fonts),
phone daily view puts the calendar first, target/stop inputs accept KRW or USD (stored in USD; USD only when no live FX rate), the dashboard right column no longer scrolls on its own,
habits only name a "best time" when there is something to compare. Ops: cleared wallet names apply without restart, the build child no longer mistakes timed waits for a deadlock,
Bybit cursors recover from expired/invalid cursors (rate limit 10006 keeps the cursor), SQLite memory-stats off is verified, a runner memory cap (tj-web 3 GB by default), negative
ledger holdings caused by a running history extension are explained, and restarting the EVM collector no longer lets the ledger rebuild mid-extension. More public tests (1,300+). License: MIT.

## 2026-10-08 저녁 — 외부 검토 반영

**선물 영수증 가격·진입 시각 · 화면 다듬기 · 상태 전송 304 · 운영 안전장치**

- **선물 영수증 — 바이낸스·OKX 가격** — 바이낸스는 정산(초 단위 시각)과 체결(ms)을 초 단위로 짝지어 청산 가격이 붙고, OKX 한 방향(net) 모드 계정도 가격 행이 생겨요
  (업데이트 뒤 OKX 는 최근 3개월을 한 번 더 받아요).
- **선물 영수증 — 진입 시각** — 같은 종목 체결을 시간순으로 쌓아 포지션이 0 이 된 뒤 첫 진입을 진입 시각으로 봐요(분할 청산도 맞게). 한 방향 모드의 반전(보유보다 많이 청산)과
  손익 0 청산은 가격이 맞아떨어질 때만 나눠 보여 주고(헤지 모드는 포지션 방향으로 바로), 아니면 종전 표시예요.
- **선물 영수증 — 바이빗 진입 체결** — 바이빗 정산(closed-pnl)에는 청산만 있어 진입 시각이 늘 비었어요. 이제 체결 내역(`/v5/execution/list`)에서 진입을 받아요
  (평소 수집 주기마다 1번 · 처음 한 번은 첫 바이빗 정산 30일 전까지 · 공표 한도의 0.1% 미만). 진입 시각이 하나도 없으면 '평균 보유' 칸은 숨겨요.
- **선물 영수증 — 차트·금액** — 차트는 고른 거래소의 봉과 점만 그려요(칩 이름 '봉' → '거래소') · 한 주문이 여러 체결로 나뉘어도 ▲ 하나(수량 합·평균가·'한 주문 n체결') ·
  그날 거래소가 2곳 이상일 때 거래소 줄로 열면 큰 숫자·세 칸이 그 거래소 금액(아래에 '그날 선물 전체' 줄) · 원화 보기는 실현·수수료·펀딩을 정산마다 원화로 바꾼 합 · 거래 줄 손익·수수료는 축약 없는 정확값.
- **선물 영수증 — 그 밖** — 종목 칩은 넓은 화면에서 줄바꿈(잘림 없음)·폰에서는 가로로 넘기고 더 있는 쪽 가장자리를 흐리게 · 한자 등 영문 아닌 글자가 든 종목도 이름·가격 그대로 ·
  크게 움직인 거래(숏 100 → 50 등)도 가격 표시(진입·청산가가 10배 넘게 다를 때만 의심) · 가격 없는 청산의 이유를 '체결 보강 중(남은 n구간)'·'체결 기록에서 못 찾음'·'거래소 값끼리 안 맞음'으로.
- **화면 — 머리 줄·서랍** — 폭 641~약 950px(넓은 글꼴이면 더 넓어도)에서 탭이 잘리거나 상태 칩이 찌그러지던 것 → 탭을 둘째 줄로 접어요 ·
  서랍을 그리다 오류가 나면 설정을 초기화하지 않고 서랍 안에 오류와 닫기만 · 자동 갱신 때 열린 서랍의 가로 스크롤·초점 그대로 · 알림(토스트)이 검색 창 위에도 보여요.
- **화면 — 시간·표·접근성** — 섞여 있던 시각 표시를 브라우저 시간대와 상관없이 한국 시간으로 · 1101~1279px 에서 30일 목록 표가 칸을 넘던 것·배지 두 줄 고침 ·
  다크 테마 흐린 글자 대비 4.5:1 이상 · 폰 보관처 서랍 터치 영역 44px · 랜덤값 워터마크를 작고 옅게.
- **화면 — 문구·빈 칸** — 히트맵 제목 '좋았던 날과 아쉬웠던 날' · 자금 흐름 지도 각주는 한 줄 + '자세히' · '오늘 무엇이 움직였나' 카드 높이 = 내용 ·
  평가 기록 없는 기타 자산은 전체 폭 · 긴 키 이름의 설명은 둘째 줄로 · 매매 습관에서 비교할 시간대가 하나뿐이면 '아직 부족해요'.
- **설정 화면 오류 문장** — '체인 목록을 읽지 못했어요: FileNotFoundError' 처럼 파이썬 예외 이름이 그대로 보이던 것을 원인과 할 일 문장으로 바꿨어요(종류는 tj-web 로그에만).
- **미매칭 수량** — 수량을 모르는 줄이 '0 DEGEN 보유'로 보이던 것을 수량 없이 'DEGEN 보유'로.
- **보낸 내역 빈 화면 문구** — 무엇을 기다리는지(첫 수집·화면 계산)와 오래 이어지면 확인할 곳(설정 › 상태 패널)을 적었어요.
- **상태 전송 줄임** — `/api/state` 는 요청의 `If-None-Match` 가 지금 버전과 같으면 304 를 돌려줘요(약한 ETag 비교 — `W/` 있든 없든).
  화면을 다시 열 때는 기기에 저장된 버전을 서버가 24시간(최대 6개) 기억해 차이(델타)만 보내요(종전 = 몇십 분 지나면 통째로).
- **빌드 경고** — 상태 패널 '웹 빌드 느림'(p95)에서 원장 재구축 중·교체 직후 빌드는 표본에서 빼요 · tj-web 줄에 빌드 방식 칩('빌드 별도 프로세스'·'빌드 웹 안 · 쉼 N분') ·
  경고 문턱 기본값 = 별도 프로세스 60초 · 웹 안 10초(`config.json` 의 `health.t.build_p95_warn_s` 를 적으면 그 값).
- **빌드 자식 교착** — fork 순간 다른 스레드가 SQLite 전역 잠금(메모리 통계)을 쥐고 있으면 자식이 영영 기다리던 것 → tj-web 이 SQLite 를 쓰기 전에 그 통계를 꺼서(리눅스 ·
  빌드 자식을 쓸 때만) 원인을 없애고, 그래도 걸리면 3초 만에 알아채고 다시 fork(3번까지 · 그래도 안 되면 웹 안에서) ·
  멈춤 판정 = CPU 와 디스크 읽기가 180초 동안 그대로일 때(종전 CPU 90초) · 자식이 실패하면 오류 내용(비밀값 가림)을 로그에 남겨요.
- **운영** — 지갑 이름·퍼프 덱스 주소를 바꿔도 화면 서버를 다시 켜지 않아요 · 화면 계산 전용 코어는 코어 4개 이상에서만(2~3개는 자식 프로세스만) ·
  `TJ_BUILD_PROC`(`auto`·`off`·`fork`)를 `.env`·`config.json` 의 `build_proc` 로도 · 리눅스 `tools/rotate_logs.sh` 크기 계산 고침(로그 정리는 pm2-logrotate 와 둘 중 하나만) ·
  `ecosystem.config.js` 재시작 간격 = 점점 늘림(2초부터) · 빠른 실패 상한 50 → 1000번.
- **체인 자동 끄기 안전장치** — 지난 7일 시세가 있던 코인이 지금만 시세가 없으면(시세 장애) 그 체인은 '값 모름'으로 두고 자동으로 끄지 않아요 ·
  자동으로 켠 체인은 켠 뒤 30일 동안 끄기 추천·자동 끄기에서 빠져요 · **설정 › 지갑 · 주소 › 체인별 조회**에 '추천 체인 자동으로 끄기' 스위치(기본 켬 · 재시작 없음).
- **계산·수집** — 업비트 거래 시작 전 가격: 입금 증명이 있어도 그 토큰 DEX 시세가 아직 없으면 같은 심볼 거래소 값은 2곳 이상이 서로 2배 안으로 맞을 때만(아니면 DEX 시세가 올 때까지 0) ·
  자금 흐름 추적에서 이더스캔이 그 체인을 요금제 미지원으로 답하면 7일 동안 노드로 읽고, 이어 읽을 때 겹친 이동은 한 번만 셉니다.
- **보안·연결** — 원장 경로에 `#`·`?`·`%` 가 있어도 열려요(SQLite 주소 인용) · QuickNode Base 키는 `base-mainnet` 엔드포인트만 받고 연결 시험은 먼저 체인 번호(`eth_chainId`)를 확인 ·
  비밀번호를 바꾸면 CSRF 토큰도 새로 만들어요(열려 있던 다른 탭은 새로고침).
- **config.json 도 본인만 읽게(0600)** — 증권사 연결(미검증 · 기본 꺼짐)의 비밀값(`app_secret`·`refresh_token` 등)이 `config.json` 의 `brokers` 칸에 들어가므로,
  `tools/setup.sh` 가 다시 실행될 때와 tj-web 이 켜질 때 `config.json` 권한이 600 보다 넓으면(그리고 내 파일이면) 600 으로 좁혀요. 설정 저장도 600 으로 써요.
- **데모(`bash tools/setup.sh --demo`)** — 선물 영수증(거래소 2곳 · 분할 청산 · 반전 체결 · 펀딩 — 합성 봉 차트), 설정 › 체인별 조회·확인 주기·수집 한계,
  보낸 내역, 보유 코인 '오늘 변동'·'7일 추이', '오늘 무엇이 움직였나', 코인마다 다른 가격 이력(타임머신)을 합성 데이터로 보여 줘요.
- **시험·CI** — GitHub Actions 가 Python 3.9 · 3.11 · 3.13 에서 전체 파일 문법 검사(`py_compile`)와 시험을 돌리고, HTTP 로그인 시험(쿠키 없이 401 · 다른 Host 421 ·
  CSRF 없이 403 · 연속 실패 잠금 429)을 더했어요.
- **문서** — README 목차, [고급 설정](README.md#고급-설정)(환경변수·설정 키), 브라우저가 직접 부르는 외부 주소(글꼴·로고 · Cloudflare 분석), 자동 재구축 임시 사본 위치.

**English** — External review fixes (evening of 2026-10-08). Futures receipts: Binance closes now get prices (settlements matched to fills by the second) and OKX one-way (net) accounts get
price rows (the last 3 months are fetched once more); entry times follow the running position (partial closes; reversals and zero-PnL closes are
split only when prices reconcile); Bybit entries come from `/v5/execution/list` (one call per collector cycle, once back to 30 days before the first
Bybit settlement). The chart draws only the selected exchange with one ▲ per order; opening from an exchange line shows that exchange's totals;
KRW view sums each settlement; trade lines show exact amounts; symbol chips wrap (desktop) or scroll with faded edges (phone); non-ASCII symbols
and large moves (only a 10x gap is suspect) are kept. Screens: header tabs fold to a second line at 641–~950px, drawer errors stay in the drawer,
refreshes keep scroll and focus, toasts show above search, times follow KST regardless of the browser time zone, the 30-day list fits at 1101–1279px, dark-theme contrast, 44px touch
targets, a lighter watermark and clearer wording. Ops: `/api/state` answers 304 to a matching `If-None-Match` (weak ETag comparison) and reopening
the screen gets a delta (stored base versions kept 24h, up to 6); the build p95 warning skips ledger-rebuild builds, shows the build mode and defaults
to 60s (child process) / 10s (in-process) unless `health.t.build_p95_warn_s` is set; SQLite memory statistics are switched off before fork (Linux, build child on) so a
build child can no longer inherit a held SQLite lock, and a stuck child is still detected in 3s and forked again; chain auto-off skips chains whose prices are only temporarily missing, gives auto-enabled chains 30 days of grace and has an
on/off switch; pre-listing prices without the token's DEX price need 2 exchanges agreeing within 2x; flow tracing falls back to nodes when Etherscan does not support a chain;
SQLite paths are URI-quoted; QuickNode keys are checked (`base-mainnet`, `eth_chainId`); changing the password rotates the CSRF token;
`config.json` is kept at 0600; the demo shows futures receipts, chain settings, outflows and price history; CI runs on Python 3.9/3.11/3.13 with
HTTP login tests.

## 2026-10-08

**선물 영수증 · 화면 계산 분리(리눅스) · 업비트 거래 시작 전 가격 · 디자인 정리**

- **선물 영수증** — 일별 기록의 '그날 실현 기여'·'그날의 기록'에서 선물 정산 줄을 누르면(선물만 있는 날은 '최고의 날' 칩도) 차익 영수증 같은 서랍이 열려요:
  그날 합·거래소·종목 칩, 실제 시세 차트 위의 진입(▲ 롱 · ▼ 숏)·청산(●) 점과 평균 진입가, 청산 목록·수수료·펀딩. 그날 합은 지금 선물 실현과 똑같아요(정산 금액은 거래소 원본 그대로).
  진입·청산 가격은 **바이낸스·바이빗·OKX·Hyperliquid** 만 — 수집기가 정산을 받는 같은 응답에서 가격을 옆 파일 `state/futures_px_<거래소>.json`(표시 전용 · 지워도 다시 생김)에 남기고,
  바이낸스만 선물 체결 내역을 조금 더 불러요(공표 한도 80% 안). 바이낸스·OKX 의 3개월 넘은 날과 그 밖의 퍼프 덱스(dYdX·Lighter·GMX·Jupiter·Pacifica)는 정산 금액만 보여 주고,
  게이트·쿠코인 선물은 종전처럼 받지 않아요. 업데이트 뒤 가격은 수집기 두 주기(약 20~30분) 안에 채워져요.
- **업비트 거래 시작 전 코인도 평가** — 업비트에 들어왔지만 업비트 원화·BTC·USDT 마켓이 아직 없는 코인은 전에는 0원이었어요. 이제
  입출금 txid 로 같은 토큰(같은 체인·컨트랙트)임이 확인되면 그 토큰을 확인한 다른 거래소 시세 → 같은 심볼 다른 거래소 시세(그 토큰 DEX 시세와 2배 넘게 다르면 버림) → 그 토큰 DEX 시세 순으로 평가하고,
  체인 기록 없이 업비트가 직접 넣어 준 코인(업비트 안 스왑·에어드랍)은 같은 심볼 거래소 시세가 2곳 이상에서 서로 2배 안으로 맞을 때만 평가해요(아니면 종전대로 0).
  보유 코인 펼침의 가격 출처에 **'거래 시작 전'**(증명 없이 평가하면 '· N곳 일치')이 붙고, 업비트 거래가 시작되면(마켓 목록 1시간마다 확인) 업비트 시세로 돌아가요.
  지난날 마감 기록은 바꾸지 않고 오늘부터 반영해요.
- **화면 계산은 따로(리눅스)** — 리눅스에서 코어가 2개 이상이면 화면 계산(빌드)을 tj-web 의 자식 프로세스에서 하고, 가장 높은 번호 코어 1개를 그 계산 전용으로 비워 둬요
  (다른 tj 유닛은 나머지 코어). 계산이 도는 동안에도 화면 응답·배경 작업이 느려지지 않아요. 자식이 실패하면(남은 램 1.2GB 미만·멈춤·시간 초과) 그 회차는 종전처럼
  tj-web 안에서 계산하고, 3번 연속 실패하면 1시간 동안 자식을 쓰지 않아요. 맥·코어 1개는 종전 그대로입니다. 끄려면 환경변수 `TJ_BUILD_PROC=off`
  (예: `TJ_BUILD_PROC=off pm2 restart ecosystem.config.js --update-env` — 코어 배분은 유닛이 켜질 때 정해져 전부 다시 켜야 해요).

**English** — Futures receipts: click a futures settlement line in the daily records to open a drawer with that day's total (identical
to realized futures PnL), per-symbol chips, entry ▲▼ / exit ● dots on a real price chart, closes, fees and funding; entry/exit prices come from
Binance, Bybit, OKX and Hyperliquid (stored display-only in `state/futures_px_<exchange>.json`; Binance/OKX days older than 3 months and other perp
DEXes show settlement amounts only). Coins sitting on Upbit before Upbit lists them (no KRW/BTC/USDT market yet) are no longer valued at 0: a token
proven by deposit/withdrawal txid uses the proving exchange, then the same symbol on other exchanges (dropped if 2x off the token's DEX price),
then that DEX price; Upbit-credited coins without a chain record need 2+ exchanges agreeing within 2x. The price source reads '거래 시작 전'
(pre-listing), past closed days are not rewritten, and Upbit's own price takes over once the market opens.

## 2026-10-07

**체인 켜기·끄기 · 보관처 상세 · RPC 대체 · API 하루 몫 · 리눅스 서버 안내**

- **보관처 상세** — 대시보드 '보관처별' 줄을 누르면 오른쪽에서 서랍이 열려요(폰은 아래에서 올라오는 시트). 체인별 비중을 누르면 탐색기, 주소는 바로 복사,
  코인을 누르면 보유표로 가요. 거래소는 체인 대신 '잔고 기준 N분 전'을 보여 주고, 계산이 안 된 칸은 '—' 로 둡니다.
- **매수 점 거슬러 찾기** — 경유 지갑·브릿지를 거쳐 거래소로 들어가 판 코인도 원가를 처음 산 매수(스왑)까지 따라가 영수증 차트에 점을 찍어요.
  매수 시각을 알 수 없는 몫은 시각을 지어내지 않고, 들어온 시각에 **입금 마름모**(원가 단가·원가 규칙)로 따로 표시합니다.
- **보낸 내역 전송 목록** — 한 주소의 전송은 최근 200건을 최신순으로 보여 주고(앞 8줄 + 50건씩 더 보기), 그보다 오래된 것은
  '그 전 N건은 목록에서 생략'으로 알려요. 합계·건수는 늘 전 건 기준입니다.
- **지갑을 넣으면 알아서 수집** — `pm2 start ecosystem.config.js` 로 띄운 설치는 설정에서 지갑을 추가하면 수집기가 스스로 다시 시작해요
  (손으로 `pm2 restart` 할 필요 없음). 다시 시작하기 전까지는 지갑 줄·보낸 내역에 **'곧 자동으로 수집 시작'** 이 보입니다.
- **확인 주기(계단)** — 오래 안 쓴 주소는 덜 자주 확인해요(지금 주기 → 조금 느리게 → 1시간마다 → 6시간마다 → 6개월 넘게 쉬면 하루 1회).
  쉬는 주소는 탐색기를 부르지 않고 공개 RPC 로 잔고·nonce 만 보다가, 바뀌거나 내가 보내면 바로 지금 주기로 돌아와요.
  기록이 하나도 없는 **빈 지갑**은 하루 한 번만 봅니다. 주소별 칩과 '지금 확인' 단추는 **설정 › 지갑 · 주소**에서.
- **옛 기록 먼저, 새 거래 확인은 남겨 둔 몫으로** — 이더스캔 키의 하루 몫(공표 한도의 80%)에서 새 거래 확인 몫(하루의 약 10~70% — 실제 사용량으로 정함)을
  먼저 떼어 두고, 나머지는 옛 기록 채우기가 UTC 0시(한국 오전 9시)부터 바로 몰아서 써요. 그래서 **처음 넣은 지갑은 옛 기록부터 채우고,
  첫날은 새 거래 확인이 평소보다 늦을 수 있어요**(그동안 새 거래 확인은 하루 몫의 약 10% 안에서 고르게). 옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 씁니다.
  하루 총량은 그대로라 한도를 넘지 않고, 오늘 옛 기록 몫을 다 쓴 뒤 넣은 지갑은 주로 다음 오전 9시부터 채워요.
- **체인 끄기** — **설정 › 지갑 · 주소 › 체인별 조회**에서 안 쓰는 체인의 스위치를 끄면 그 체인의 조회·입출금 알림이 멈춰 컴퓨터와 API 한도를 아껴요.
  지금까지 기록은 그대로 남고(잔고는 끈 때 값에서 멈춤), 다시 켜면 끈 날부터 빠진 기간을 이어 받아요.
  그 체인에서 보낸 거래가 지갑마다 10번 이하면 **'끄는 걸 추천해요'** 로 강조하고 끄면 줄어드는 하루 호출 수를 보여 줘요. 다만 모르는 지갑(확인 전·점검 실패)이
  하나라도 있거나, 최근 30일 안에 보낸 거래가 있거나, 옛 기록을 채우는 중이면 추천하지 않아요. 잔고가 $100 넘게 남아 있으면 추천 옆에 같이 적어 둡니다.
  BSC·Solana(따로 도는 수집기)와 일부 체인은 아직 이 스위치로 못 꺼요(줄에 이유 표시).
  **추천 체인은 기본으로 꺼져요** — '끄는 걸 추천해요' 조건에 맞고 그 체인에 든 값(시세 있는 코인 + LP + NFT)이 소액 기준(최대 $100) 이하이면, 기초 잔고 대조가 끝난 뒤
  활동 점검 때 알아서 끄고 텔레그램으로 한 줄 알려요. 손으로 다시 켠 체인은 다시 자동으로 끄지 않고, 꺼 둔 체인에 새 잔고·활동이 생기면 미추적 체인 점검이 알려요.
- **확인 주기가 지갑 수에 맞춰 늘어나요** — 지갑이 많아 이더스캔 하루 몫(공표 한도의 80% — 같은 키를 쓰는 체인 합산)을 넘을 것 같으면 기본 확인 주기를 지갑 수에 맞춰 늘려요(최대 15분 —
  그래도 넘치면 종전처럼 간격을 더 벌려요). 지갑 칩의 **'M분마다'** 와 'Solana 지갑 N개라 M분마다 확인해요' 같은 줄로 보여 주고, 체인별 조회 카드에도 같은 주기가 나와요.
- **Solana 도 하루 몫** — 헬리우스 무료 월 한도(100만 크레딧)의 80% 를 30일로 나눈 하루 몫(약 2만 6천) 안에 들도록 Solana 기본 주기를 맞춰요.
  이더스캔과 같이 새 거래 확인 몫을 먼저 떼어 두고(옛 기록을 채우는 동안은 하루 몫의 10% — `sol.helius_head_min_pct` 로 1~70 사이 조절) 나머지는 UTC 0시부터 옛 기록에 먼저 써요.
  오늘 옛 기록 몫을 다 쓴 뒤 넣은 Solana 지갑은 '옛 기록 차례 대기'로 보이다가 다음 오전 9시에 시작합니다. 옛 기록이 다 채워지면 새 거래 확인이 하루 몫을 그대로 써요.
  유료 플랜이면 `config.json` 의 `sol.helius_monthly_credits` 에 월 크레딧을 적으세요.
- **Solana 새 거래는 공개 노드 먼저** — Solana 새 거래 확인은 무료 공개 노드(publicnode)를 먼저 쓰고, 응답이 없거나 이상하면 같은 요청을 헬리우스로 다시 보내요
  (헬리우스는 옛 기록 채우기와 백업에 씀). 공개 노드는 최근 약 18시간만 보관해서, 마지막 확인이 12시간보다 오래된 주소(수집기를 오래 껐다 켠 경우 등)와
  처음 넣은 지갑은 헬리우스로 확인하고, 헬리우스가 주기적으로 공개 노드 결과를 대조해 빠진 거래가 있으면 다시 받아요.
  헬리우스 하루 몫을 다 쓴 날은 그날 끝(UTC 자정 = 한국 오전 9시)까지 헬리우스를 쉬고 공개 노드로 이어 받아요(새 거래 = publicnode · 옛 기록 = Solana 공식 공개 노드,
  공표 한도의 80% 안 · 새 지갑 첫 백필은 다음 날). 끄려면 `sol.head_rpc`·`sol.archive_rpc` 를 `""` 로 — 그러면 종전처럼 헬리우스만 쓰고, 하루 몫이 다 차면 그날 끝까지 쉬어요.
- **옛 기록 채우는 동안** — 첫 백필·옛 기록 채우기가 남은 주소도 새 거래 확인은 계단 규칙을 따라요. 최근 거래가 보이는 주소는 지금 주기로 계속 확인하고,
  오래 쉰 주소는 새 거래 확인은 쉬면서 옛 기록만 마저 채워요(하루 몫 안에서).
- **빈 지갑은 먼저 가볍게** — nonce·잔고가 0 인 EVM 지갑은 긴 옛 기록 채우기 전에 토큰 이동이 하나라도 있었는지 한 번만 가볍게 물어봐요.
  하나도 없으면 **빈 지갑**으로 두고 활동은 하루 한 번만 확인합니다(토큰 입금만 오면 주 1회 확인 때 기록 — 시각·수량은 그대로).
- **EVM 지갑이면 Etherscan 키 필수** — EVM 지갑을 등록했는데 Etherscan 키가 없으면 설정 마법사(지갑·키·마지막 요약)·키 카드('EVM 필수')·상태 패널에
  '이더스캔 키가 필요해요(무료)'가 떠요. 경고만 하고 막지는 않아요 — 키가 없어도 공개 탐색기·RPC 로 계속 받지만 느리거나, 공개 탐색기가 막힌 체인
  (Arbitrum·Polygon 등)은 늦게 기록될 수 있어요(기록이 사라지지는 않아요). 이 안내는 텔레그램으로 보내지 않습니다.
- **Base 는 공개 RPC 로 직접** — Base 블록스카웃 API 가 막혀 있어(2026-10 기준 403 · 무료 이더스캔 키도 Base 는 지원하지 않음) Base 는 탐색기 없이
  공개 RPC 노드에서 직접 읽어요. 이미 쓰던 설치는 재시작하면 지금까지 받은 위치를 그대로 이어받아 새 거래는 바로 보이고, 아직 못 받은 옛 구간과
  내부 ETH 이동(스왑으로 받은 ETH·브리지 입금 등)은 뒤에서 채워요(지갑·기간에 따라 몇 시간까지). 지갑의 잔고·nonce 를 대조해 로그가 남지 않는 ETH 이동도 찾고,
  옛 구간을 다 채우기 전까지는 새로 넣은 Base 지갑의 기초 잔고 확인이 늦어질 수 있어요. 블록스카웃으로 되돌리려면 `config.json` 의 `chains.base.discovery` 를 `"explorer"` 로.
- **탐색기가 막히면 공개 RPC 로 자동 대체** — 이더스캔·블록스카웃이 막히면(하루 한도를 다 씀·키 거부·연속 실패·403·색인 정지, 또는 하루 몫 때문에
  새 거래 확인이 20분 넘게 밀림) 그 체인만 받던 위치에서 이어 공개 RPC 로 받아요(하루 한도·키 문제일 때 그 체인 블록스카웃이 살아 있으면 종전처럼 블록스카웃 먼저).
  설정은 필요 없어요 — 체인마다 키 없는 공개 노드 목록이 들어 있어요. 탐색기가 살아나면 알아서 돌아가요(블록스카웃은 15분마다·이더스캔은 1시간마다 한 번 시험,
  하루 한도는 쉼이 끝나면 · 깜빡이지 않게 최소 30분은 머묾). 상태 패널과 확인 주기 카드에 '이더스캔 대신 RPC 로 확인 중(이유)'이 한 줄 보이고,
  텔레그램으로는 보내지 않아요. 하루·월 한도가 있는 무료 노드는 공표 한도의 80% 까지만 세어 쓰고, 넘으면 그 노드는 UTC 자정까지 쉬고 다음 노드로 넘어가요.
  끄려면 `config.json` 에 `"rpc_fallback": false`(전체) 또는 `chains.<체인>.rpc_fallback: false`(그 체인만).
- **빗썸 원화 입출금도 일별 기록에** — 은행 ↔ 빗썸 원화 입출금이 그날 기록·그날 카드 '입출금'(순유입)·자산 변동 분해에 들어가요(전에는 업비트만). [README › 일별 기록](README.md#일별-기록--그날-카드--m월-한눈에)
- **미매칭엔 할 일만** — '기초 잔고 대사 완료' 같은 알림이 미매칭 › 기타 보류에 빈 '—' 줄로 쌓이던 것을 뺐어요(미매칭 배지 수도 그만큼 줄어요).

**English** — A holding-place drawer (share of total, coin ring, 30-day in/out, chains, coins), buy dots traced back through
hop wallets and bridges to the original swap (unknown buy times shown as a separate "deposit" diamond, never invented), outflow
transfer lists of the latest 200 with "show more", automatic collector restart after adding a wallet ("곧 자동으로 수집 시작"),
tiered per-address check intervals (idle addresses checked less, empty wallets once a day) and an Etherscan daily budget (80% cap) that
keeps a share for new-transaction checks and spends the rest on old history from 00:00 UTC.
Also new: per-chain on/off switches in Settings › 지갑 · 주소 (a chain is suggested for switching off when every wallet sent 10 or fewer
transactions there and nothing is unknown, recent or still backfilling; switching it back on resumes from the day it was turned off),
base check intervals that grow with the number of wallets so the daily budget holds, a Helius daily budget for Solana (80% of the free
monthly credits spread over 30 days, old history first as well — `sol.helius_head_min_pct`; set `sol.helius_monthly_credits` for paid plans),
new-transaction checks that keep following the tiers while old history is still being filled, and a one-call probe for empty wallets.
Solana new transactions are checked on a free public node (publicnode) first, with Helius as backup and periodic cross-check; when the
Helius daily share is used up, public nodes carry on until the UTC day ends (`sol.head_rpc` / `sol.archive_rpc` = `""` to disable).
Base is now read directly from public RPC nodes (its Blockscout API is blocked; existing installs keep their position and fill older
history in the background), and any EVM chain whose Etherscan/Blockscout is blocked or out of quota switches to public RPC automatically
and back when the explorer recovers (`rpc_fallback: false` to disable). Bithumb KRW bank deposits/withdrawals now show up in the daily
records, net flow and breakdown, and "baseline reconciled" notices no longer fill the unmatched list.
Chains that meet the switch-off suggestion and hold $100 or less (priced coins + LP + NFT) are now switched off automatically after their baseline
reconciliation (one Telegram line; a chain you switch back on stays on). Optional node keys (`TJ_NODEREAL_KEY`, `TJ_ANKR_KEY`,
`TJ_QUICKNODE_BSC_KEY`, `TJ_QUICKNODE_BASE_KEY` — Settings › 연결·키) add archive nodes for BNB Chain/Base history (free keys at 80% of the
monthly quota, paid at a usage share, 10% by default), and the Rabby portfolio check only covers EVM wallets worth $1,000+ (`rabby.min_wallet_usd`).

## 2026-10-05

- **전체 검색**(⌘K · /)과 **내 매매 돌아보기**(타임머신 · 자금 흐름 지도 · 팔기 전 미리보기 · 올해 결산 · 계획 지키기 점수 · 매매 습관 · 하루 실현 잔디 · BTC 비교선 · 안 팔았다면) —
  README [화면 미리보기 › 새로 생긴 것](README.md#새로-생긴-것--내-매매를-다르게-보는-화면).
- **텔레그램 알림 3등급**(즉시 · 하루 요약 · 시스템) — README [텔레그램 알림 설정](README.md#텔레그램-알림-설정).
- 수집기·원장 단단하게, 비공개 원격 접속 흔적 제거, 로그인·프록시 경로 강화(로그인 기본 켜짐 — README '처음 시작하면 이것부터'의 업데이트 안내).
- 첫 공개판.
