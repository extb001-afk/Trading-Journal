#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

chk = T.chk

CHILD = r"""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
for name in json.loads(sys.argv[2]):
    sys.modules[name] = None
import calcguard
mod = __import__(sys.argv[3])
attrs = {}
for a in json.loads(sys.argv[4]):
    v = getattr(mod, a)
    attrs[a] = v if v is None or isinstance(v, (dict, tuple, list, str, int)) else type(v).__name__
snap = calcguard.snapshot()
print(json.dumps({"attrs": attrs, "n": {k: (snap.get(k) or {}).get("n", 0) for k in json.loads(sys.argv[5])},
                  "types": {k: (snap.get(k) or {}).get("types", {}) for k in json.loads(sys.argv[5])}}, default=list))
"""

IMPORT_ERRS = {"ImportError", "ModuleNotFoundError"}
CASES = [
    (["pricing"], "candles", {}, ["candles:<module>[pricing_tables]"]),
    (["fut_rcpt"], "view_detail", {"fut_rcpt": None}, ["view_detail:<module>[fut_rcpt]"]),
    (["perp_dex"], "view_fut", {"perp_dex": None, "PERP_NAMES": {}}, ["view_fut:<module>[perp_dex]"]),
    (["review_prompt"], "view_review", {"REVIEW_LEN_KEYS": [], "review_len_key": None, "REVIEW_PV": None, "REVIEW_WPV": None},
     ["view_review:<module>[len_keys]", "view_review:<module>[prompt_version]", "view_review:<module>[weekly_version]"]),
    (["review_progress"], "view_review", {"review_progress": None}, ["view_review:<module>[review_progress]"]),
]


def run(block, target, names, sites, strict):
    env = {k: v for k, v in os.environ.items() if k != "TJ_STRICT"}
    if strict:
        env["TJ_STRICT"] = "1"
    return subprocess.run([sys.executable, "-c", CHILD, T.SRC, json.dumps(block), target, json.dumps(sorted(names)), json.dumps(sites)],
                          capture_output=True, text=True, env=env, timeout=120, check=False)


seen = set()
for block, target, want, sites in CASES:
    r = run(block, target, want, sites, False)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = None
    chk(r.returncode == 0 and out is not None, "%s: %s 없음 = import 성공(예외 0)" % (target, "·".join(block)), (r.returncode, r.stderr[-600:]))
    if out is None:
        continue
    chk(out["attrs"] == want, "%s: %s 없음 = 대체 값 그대로" % (target, "·".join(block)), out["attrs"])
    chk(all(out["n"][s] == 1 for s in sites) and all(set(out["types"][s]) <= IMPORT_ERRS and out["types"][s] for s in sites),
        "%s: calcguard 기록 자리마다 1(ImportError) — %s" % (target, ", ".join(sites)), out)
    seen.update(sites)
    rs = run(block, target, want, sites, True)
    chk(rs.returncode != 0 and any(x + ":" in rs.stderr for x in IMPORT_ERRS), "%s: 엄격 모드 = ImportError 다시 던짐(import 실패)" % target, (rs.returncode, rs.stderr[-300:]))

r0 = run([], "view_review", {"REVIEW_PV": None}, ["view_review:<module>[prompt_version]"], False)
try:
    base = json.loads(r0.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    base = None
chk(base is not None and base["n"]["view_review:<module>[prompt_version]"] == 0 and base["attrs"]["REVIEW_PV"] is not None,
    "막지 않으면 기록 0 · 진짜 값(대조군)", (r0.returncode, r0.stderr[-300:], base))
chk(len(seen) == 7, "모듈 수준 선택 import 7자리 전부 시험", sorted(seen))
T.finish()
