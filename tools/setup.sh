#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -h|--help)
    cat <<'USAGE'
tj-bot 첫 설치 도우미 — 아무것도 설치하지 않습니다(확인·안내만). 여러 번 실행해도 안전합니다.
  bash tools/setup.sh          점검 + config.json·.env·state/ 준비 + 다음 단계 안내
  bash tools/setup.sh --demo   합성 데이터로 화면만 구경(저장 안 함 · 포트 TJ_PORT=8024 bash tools/setup.sh --demo)
USAGE
    exit 0;;
  ""|--demo) ;;
  *) echo "모르는 옵션: $1 (bash tools/setup.sh --help)"; exit 2;;
esac
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

echo "tj-bot 설치 점검 ($ROOT)"

PY="${TJ_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || die "python3 가 없습니다 — https://www.python.org/downloads/ 에서 3.9 이상을 설치하세요"
"$PY" - <<'EOF' || die "Python 3.9 이상이 필요합니다"
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
EOF
ok "$("$PY" --version 2>&1)"
"$PY" -c "import sqlite3, ssl; assert sqlite3.sqlite_version_info >= (3, 24)" 2>/dev/null \
  || die "sqlite3(3.24+)·ssl 모듈이 있는 파이썬이 필요합니다"
ok "sqlite3·ssl 확인"

if [[ "${1:-}" == "--demo" ]]; then
  echo
  echo "데모 모드 — 합성 데이터(실제 지갑·거래 아님), 설정 저장 안 함. 끄려면 Ctrl+C"
  echo "  → http://127.0.0.1:${TJ_PORT:-8023}/"
  exec env TJ_DEMO=1 "$PY" src/web.py
fi

if [[ -f config.json ]]; then
  if chmod 600 config.json 2>/dev/null; then
    ok "config.json 있음 (유지 · 권한 600)"
  else
    warn "config.json 권한을 600 으로 바꾸지 못했어요 — 파일 소유자를 확인하고 'chmod 600 config.json' 을 직접 하세요"
  fi
else
  cp config.example.json config.json
  chmod 600 config.json
  ok "config.json 생성 (config.example.json 복사 — 지갑은 웹 화면에서 추가)"
fi
if [[ -f .env ]]; then
  chmod 600 .env
  ok ".env 있음 (권한 600 으로 맞춤)"
else
  umask 077
  cp .env.example .env
  chmod 600 .env
  ok ".env 생성 (권한 600 — 키는 웹 화면에서 입력)"
fi
mkdir -p state && chmod 700 state
ok "state/ 준비 (원장·캐시가 여기 쌓입니다)"

"$PY" -m py_compile src/*.py && ok "파이썬 소스 컴파일 확인"
PORT="$("$PY" -c 'import json,sys
try:
    p = int((json.load(open("config.json")).get("web") or {}).get("port") or 8023)
except Exception:
    p = 8023
print(p if 0 < p < 65536 else 8023)' 2>/dev/null || echo 8023)"

echo
if command -v pm2 >/dev/null 2>&1; then
  ok "pm2 $(pm2 --version 2>/dev/null | tail -1)"
  cat <<EOF

다음 단계:
  pm2 start ecosystem.config.js     # 전체 시작 (지갑 없으면 수집기는 조용히 대기)
  pm2 save                          # 재부팅 후에도 자동 시작하려면 + 'pm2 startup' 안내를 따르세요
  open http://127.0.0.1:${PORT}/       # 첫 화면에서 설정 마법사가 열립니다 (리눅스는 브라우저로 직접)
  cat state/auth_setup_code         # 첫 비밀번호 화면이 묻는 설정 코드 (tj-web 이 처음 켜질 때 만듦 · 쓰고 나면 지워짐)
EOF
else
  warn "pm2 가 없습니다 — Node.js 설치 후 'npm install -g pm2' (권장)"
  cat <<EOF

pm2 없이 바로 써 보려면 (터미널 6개, 각각 켜 두기):
  $PY src/unit_runner.py web
  $PY src/unit_runner.py core
  $PY src/unit_runner.py evm
  $PY src/unit_runner.py sol
  $PY src/unit_runner.py bsc
  $PY src/alert_bot.py              # 상태 점검·원장 경고(텔레그램 연결 전에도 화면 상태 패널을 채움 — 권장)
  # (선택) 거래소: $PY src/upbit_link.py  ·  $PY src/ex_foreign.py
그리고 http://127.0.0.1:${PORT}/ 을 여세요. 첫 비밀번호 화면의 설정 코드 = cat state/auth_setup_code
멈추기: 각 터미널에서 Ctrl+C(유닛 러너는 자기가 띄운 프로세스를 정상 종료한 뒤 끝나요).
로그는 각 터미널에 나옵니다. 파일로 남기려면 ★덧붙이기(>>)로★ — 예: $PY src/unit_runner.py web >> ~/tj-logs/tj-web.log 2>&1
  ('>' 로 열면 자르기 뒤에도 그 프로세스가 옛 위치에 이어 써서 크기가 안 줄어요 · 자르기: bash tools/rotate_logs.sh ~/tj-logs)
EOF
fi
