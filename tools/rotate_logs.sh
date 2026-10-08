#!/bin/bash
set -uo pipefail
MAX_MB=10; KEEP_MB=2; DRY=0; DIR="$HOME/.pm2/logs"
usage() {
  cat <<'USAGE'
사용법: bash tools/rotate_logs.sh [--max-mb 10] [--keep-mb 2] [--dry-run] [로그 디렉터리(기본 ~/.pm2/logs)]
  크기 상한(--max-mb)을 넘은 tj-*.log 만: 끝 --keep-mb 를 <이름>.1 로 보존(직전 .1 은 덮음) → 원본을 0 바이트로 자른다(복사-자르기).
  --dry-run = 무엇을 자를지만 보여 줌 · 리눅스·맥 둘 다 · 크론 예: 0 * * * * bash <설치 폴더>/tools/rotate_logs.sh
  pm2-logrotate 를 쓰는 설치는 이 도구가 필요 없다(둘 중 하나만).
USAGE
}
while [ $# -gt 0 ]; do
  case "$1" in
    --max-mb) [ $# -ge 2 ] || { usage; exit 2; }; MAX_MB=$2; shift 2;;
    --keep-mb) [ $# -ge 2 ] || { usage; exit 2; }; KEEP_MB=$2; shift 2;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage; exit 0;;
    -*) echo "모르는 옵션: $1"; usage; exit 2;;
    *) DIR=$1; shift;;
  esac
done
case "$MAX_MB" in ''|*[!0-9]*) echo "--max-mb 는 숫자만(MB 정수)"; exit 2;; esac
case "$KEEP_MB" in ''|*[!0-9]*) echo "--keep-mb 는 숫자만(MB 정수)"; exit 2;; esac
[ "$KEEP_MB" -lt "$MAX_MB" ] || { echo "--keep-mb 는 --max-mb 보다 작아야"; exit 2; }
[ -d "$DIR" ] || { echo "디렉터리 없음: $DIR"; exit 2; }
max=$((MAX_MB * 1024 * 1024)); keep=$((KEEP_MB * 1024 * 1024)); n=0; freed=0
for f in "$DIR"/tj-*.log; do
  [ -f "$f" ] || continue
  sz=$(wc -c < "$f" 2>/dev/null | tr -d '[:space:]')
  case "$sz" in ''|*[!0-9]*) echo "크기 못 읽음: $f (건너뜀)"; continue;; esac
  [ "$sz" -gt "$max" ] || continue
  n=$((n + 1)); freed=$((freed + sz - keep))
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] $(basename "$f") $((sz / 1048576))MB → 끝 ${KEEP_MB}MB 를 $(basename "$f").1 로 보존 후 0 으로 자름"
    continue
  fi
  tail -c "$keep" "$f" > "$f.1.tmp" && mv -f "$f.1.tmp" "$f.1" && : > "$f" \
    && echo "잘랐음: $(basename "$f") $((sz / 1048576))MB → 보존 $(basename "$f").1(${KEEP_MB}MB)" \
    || echo "실패: $f (원본 유지)"
done
echo "대상 ${n}개 · 확보 약 $((freed / 1048576))MB$([ "$DRY" = 1 ] && echo ' (dry-run — 변경 없음)')"
