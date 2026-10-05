#!/bin/bash
set -uo pipefail
MAX_MB=10; KEEP_MB=2; DRY=0; DIR="$HOME/.pm2/logs"
while [ $# -gt 0 ]; do
  case "$1" in
    --max-mb) MAX_MB=$2; shift 2;;
    --keep-mb) KEEP_MB=$2; shift 2;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n 2,9p "$0"; exit 0;;
    *) DIR=$1; shift;;
  esac
done
case "$MAX_MB$KEEP_MB" in *[!0-9]*) echo "숫자만(MB 정수)"; exit 2;; esac
[ "$KEEP_MB" -lt "$MAX_MB" ] || { echo "--keep-mb 는 --max-mb 보다 작아야"; exit 2; }
[ -d "$DIR" ] || { echo "디렉터리 없음: $DIR"; exit 2; }
max=$((MAX_MB * 1024 * 1024)); keep=$((KEEP_MB * 1024 * 1024)); n=0; freed=0
for f in "$DIR"/tj-*.log; do
  [ -f "$f" ] || continue
  sz=$(stat -f %z "$f" 2>/dev/null || stat -c %s "$f")
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
