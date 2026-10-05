#!/usr/bin/env python3
import getpass
import json
import os
import sys

USAGE = ("사용법: python3 tools/reset_password.py [-y]   비밀번호·로그인 세션 지우기 → 이 컴퓨터에서 /login 으로 새로 만들기\n"
         "       python3 tools/reset_password.py --set   새 비밀번호를 터미널에서 바로 입력(모든 기기 로그아웃)")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import common
import login_auth


def _port():
    try:
        with open(common.CONFIG_PATH, encoding="utf-8") as f:
            return int(((json.load(f).get("web") or {}).get("port")) or 8023)
    except (OSError, ValueError, TypeError):
        return 8023


def _rm(p):
    try:
        os.unlink(p)
        return True
    except FileNotFoundError:
        return False


def main(argv):
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        return 0
    bad = [a for a in argv if a not in ("-y", "--yes", "--set")]
    if bad:
        print("알 수 없는 옵션: " + " ".join(bad) + "  (-h 도움말)")
        return 2
    if not os.path.isdir(common.STATE_DIR):
        print(f"state 폴더가 없어요: {common.STATE_DIR} — 설치 폴더에서 실행하거나 TJ_BASE 를 지정하세요")
        return 2
    if "--set" in argv:
        if not sys.stdin.isatty():
            print("--set 은 터미널에서 직접 입력해야 해요(파이프·스크립트 입력 거부)")
            return 2
        pw = getpass.getpass("새 비밀번호(10자 이상): ")
        prob = login_auth.password_problem(pw)
        if prob:
            print("쓸 수 없는 비밀번호: " + prob)
            return 1
        if getpass.getpass("한 번 더: ") != pw:
            print("두 번 입력한 비밀번호가 달라요 — 바꾸지 않았어요")
            return 1
        login_auth.set_password(pw)
        _rm(login_auth.SESS_PATH)
        print("새 비밀번호를 저장했어요 · 모든 기기 로그아웃 — 브라우저에서 다시 로그인하세요")
        return 0
    have = [p for p in (login_auth.AUTH_PATH, login_auth.SESS_PATH) if os.path.exists(p)]
    if not have:
        print("지울 것이 없어요(비밀번호·세션 파일 없음)")
        return 0
    if not ({"-y", "--yes"} & set(argv)):
        if not sys.stdin.isatty():
            print("확인 없이 지우려면 -y 를 붙이세요")
            return 2
        ans = input("웹 로그인 비밀번호와 모든 로그인 세션을 지울까요? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("취소했어요")
            return 1
    for p in have:
        _rm(p)
    print("지웠어요: " + ", ".join(os.path.relpath(p, common.BASE_DIR) for p in have))
    print(f"이제 이 컴퓨터에서 http://127.0.0.1:{_port()}/login 을 열어 새 비밀번호를 만드세요"
          " (web.login 이 켜져 있는 동안은 그 전까지 화면이 열리지 않아요)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
