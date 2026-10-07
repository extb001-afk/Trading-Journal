#!/usr/bin/env python3
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import ops_requests


def main():
    if "--cancel" in sys.argv:
        print("승인 취소" if ops_requests.cancel_approve() else "승인 없음")
        return 0
    g = ops_requests.gate_record()
    if not g:
        print("게이트 기록 없음(아직 자동 재계산이 돌지 않았음)")
    else:
        print("마지막 게이트:", time.strftime("%Y-%m-%d %H:%M", time.localtime(g.get("ts") or 0)), "· 통과" if g.get("ok") else "· 보류",
              "(승인으로 통과)" if g.get("approved") else "")
        print("재계산 사유:", g.get("why") or "?")
        for m in g.get("months") or []:
            print(f"  {m['month']}: 실현 ${m['before']:,.2f} → ${m['after']:,.2f} ({m['diff']:+,.2f})")
        if (g.get("n_months") or 0) > len(g.get("months") or []):
            print(f"  … 외 {g['n_months'] - len(g['months'])}달")
        for o in g.get("open_cost") or []:
            print(f"  안 판 포지션 {o.get('sym') or '그룹 ' + str(o.get('group'))}: 원가 ${o['before']:,.2f} → ${o['after']:,.2f} ({o['diff']:+,.2f})")
        u = g.get("unv") or {}
        if u:
            print(f"  원가미상 매도: ${u.get('before', 0):,.2f}({u.get('rows_before')}건) → ${u.get('after', 0):,.2f}({u.get('rows_after')}건)")
        if g.get("approve_note"):
            print("  승인 상태:", g["approve_note"])
        rs = g.get("report_sha")
        print("보고서:", (f"{rs} ({'보존본 있음' if ops_requests.find_rejected(rs) else '보존본 없음'})" if rs else "없음"))
    if "--yes" in sys.argv:
        pend = ops_requests.pending_gate()
        ok, msg = ops_requests.approve((pend or {}).get("report_sha") or "", "tools/rebuild_approve.py")
        print(msg)
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
