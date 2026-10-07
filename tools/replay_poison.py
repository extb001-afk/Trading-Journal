#!/usr/bin/env python3
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import ops_requests


def main():
    a = sys.argv[1:]
    ents = ops_requests.poison_entries(limit=10 ** 6)
    if not ents:
        print("격리 레코드 없음(state/poison.jsonl)")
        return 0
    for e in ents:
        print(f"{e['id']}  {time.strftime('%m-%d %H:%M', time.localtime(e['ts'] or 0))}  {e['kind']:12s}  {e['ref'][:18]:18s}  {e['err'][:60]}"
              f"  → {'재처리 성공' if e['state'] == '성공' else ('재처리 실패: ' + e['rerr'][:40]) if e['state'] == '실패' else '대기'}")
    if "--apply" in a:
        ids = [a[i + 1] for i, x in enumerate(a) if x == "--id" and i + 1 < len(a)]
        if "--all" not in a and not ids:
            raise SystemExit("--all 또는 --id <id> 를 주세요")
        ok, msg = ops_requests.poison_request(ids=ids, all_="--all" in a, by="tools/replay_poison.py")
        print(msg + (" (결과: 이 도구를 다시 실행)" if ok else ""))
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
