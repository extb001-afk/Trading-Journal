#!/usr/bin/env bash
set -euo pipefail
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
  ok "config.json 있음 (유지)"
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

"$PY" -m py_compile src/*.py src/brokers/*.py && ok "파이썬 소스 컴파일 확인"

echo
if command -v pm2 >/dev/null 2>&1; then
  ok "pm2 $(pm2 --version 2>/dev/null | tail -1)"
  cat <<EOF

다음 단계:
  pm2 start ecosystem.config.js     # 전체 시작 (지갑 없으면 수집기는 조용히 대기)
  pm2 save                          # 재부팅 후에도 자동 시작하려면 + 'pm2 startup' 안내를 따르세요
  open http://127.0.0.1:8023/       # 첫 화면에서 설정 마법사가 열립니다 (리눅스는 브라우저로 직접)
EOF
else
  warn "pm2 가 없습니다 — Node.js 설치 후 'npm install -g pm2' (권장)"
  cat <<EOF

pm2 없이 바로 써 보려면 (터미널 5개, 각각 켜 두기):
  $PY src/unit_runner.py web
  $PY src/unit_runner.py core
  $PY src/unit_runner.py evm
  $PY src/unit_runner.py sol
  $PY src/unit_runner.py bsc
  # (선택) 거래소: $PY src/upbit_link.py  ·  $PY src/ex_foreign.py  ·  알림: $PY src/alert_bot.py
그리고 http://127.0.0.1:8023/ 을 여세요.
EOF
fi
