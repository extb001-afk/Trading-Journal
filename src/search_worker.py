import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import search_index


def main():
    out_f = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s [tj-web 검색 일꾼] %(message)s", stream=sys.stderr)
    common.add_secret_filter()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("req")
            body = search_index.search(str(req.get("q") or "")[:search_index.Q_MAX], kinds=req.get("kinds") or None,
                                       limit=req.get("limit") or None, after=req.get("after") or None,
                                       before=req.get("before") or None, offset=req.get("offset") or None)
            out = {"ok": True, "body": body}
        except Exception as e:
            out = {"ok": False, "err": type(e).__name__}
        try:
            line9 = json.dumps(out, default=str)
        except Exception as e:
            line9 = json.dumps({"ok": False, "err": type(e).__name__})
        out_f.write(line9 + "\n")
        out_f.flush()


if __name__ == "__main__":
    main()
