#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import _harness as T  # noqa: E402

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

chk = T.chk
TOOLS = os.path.join(T.ROOT, "tools", "refactor")
if not os.path.isfile(os.path.join(TOOLS, "cfg_keys.py")):
    _pub = os.path.realpath(T.HERE) == os.path.realpath(os.path.join(T.ROOT, "tests"))
    chk(_pub, "공개판 배치 — 비공개 도구(tools/refactor/cfg_keys.py) 없음 · 건너뜀" if _pub else "저장소 배치인데 비공개 도구 없음(건너뛰지 않고 실패)")
    T.finish()
sys.path.insert(0, TOOLS)
import cfg_keys as C  # noqa: E402

FILES = {
    "src/paths.py": 'CONFIG_PATH = "config.json"\n',
    "src/config.py": (
        "import json\nimport paths\n\n\n"
        "def load_config():\n    with open(paths.CONFIG_PATH) as f:\n        return json.load(f)\n\n\n"
        "def _poll_cfg(cfg, sect):\n    return ((cfg or {}).get(sect) or {}).get('poll_sec')\n\n\n"
        "def exf_poll(cfg):\n    return _poll_cfg(cfg, 'exf')\n\n\n"
        "def upbit_poll(cfg):\n    return _poll_cfg(cfg, 'upbit')\n"),
    "src/settings_store.py": (
        "import json\nimport paths\n\n\n"
        "def read_config_raw():\n    with open(paths.CONFIG_PATH, 'rb') as f:\n        raw = f.read()\n    return json.loads(raw.decode('utf-8'))\n"),
    "src/statefile.py": "def read_json(p, d=None):\n    return d\n",
    "src/watcher.py": (
        "import config\nimport helper\nfrom mixin import ReadMixin\n\n\n"
        "class Watcher(ReadMixin):\n    def __init__(self, cfg, n):\n        self.cfg = cfg\n        self.n = n\n\n"
        "    def step(self):\n        web = self.cfg.get('web') or {}\n        return web.get('port'), self.cfg['chains']\n\n\n"
        "def main(sink):\n    cfg = config.load_config()\n    w = Watcher(cfg, 3)\n    sink.push(cfg)\n    helper.use(cfg)\n    helper.cb(lambda: cfg)\n"
        "    for k, v in cfg.items():\n        pass\n    return config.exf_poll(cfg), w\n"),
    "src/mixin.py": "class ReadMixin:\n    def mix(self):\n        return self.cfg.get('backup', {}).get('keep_db')\n",
    "src/helper.py": (
        "import paths\nimport statefile\n\n\n"
        "def use(c):\n    return c.get('wallets')\n\n\n"
        "def cb(fn):\n    return fn\n\n\n"
        "def direct():\n    raw = statefile.read_json(paths.CONFIG_PATH, {}) or {}\n    return raw.get('review')\n\n\n"
        "def quotes():\n    cfg = {'quotes': 1}\n    return cfg.get('quotes')\n\n\n"
        "def lost(conf):\n    return conf.get('wallets')\n"),
    "src/svc.py": (
        "import settings_store as ss\n\n\n"
        "class Core:\n    def __init__(self):\n        self.cfg = ss.read_config_raw()\n        self.port = Port(self)\n\n\n"
        "class Port:\n    def __init__(self, core):\n        self.core = core\n\n"
        "    cfg = property(lambda self: self.core.cfg)\n\n"
        "    def use(self):\n        return self.cfg.get('health')\n"),
    "src/web.py": (
        "import svc\n\nB: svc.Core = None\n\n\n"
        "def read():\n    return B.cfg.get('exf')\n\n\n"
        "def main():\n    global B\n    B = svc.Core()\n"),
}


def build(extra=None):
    root = tempfile.mkdtemp(prefix="tj_cfg_keys_", dir=T.TMP)
    files = dict(FILES)
    files.update(extra or {})
    for rel, text in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(root, "config.example.json"), "w", encoding="utf-8") as fh:
        json.dump({"web": {}, "chains": {}, "brokers_note": ""}, fh)
    return root


ROOT1 = build()
snap = C.snapshot(ROOT1)
top, sub, unres, vk = snap["top"], snap["sub"], snap["unresolved"], snap["varkey"]

chk(snap["converged"], "고정점 수렴")
chk("web" in top and "web.port" in sub, "생성자 인자 → self.cfg → 블록 하위 키(web.port)", (top, sub))
chk("chains" in top, "self.cfg['chains'] = 최상위 키")
chk("backup" in top and "backup.keep_db" in sub, "믹스인 묶음의 self.cfg(다른 모듈 바탕 클래스) · 꼬리 .get 사슬 하위 키")
chk("wallets" in top and "watcher" not in top["wallets"] and "helper" in top["wallets"], "다른 모듈 함수 인자로 넘김(import 별칭) → 받는 쪽 읽기")
chk("review" in top, "CONFIG_PATH 를 read_json 으로 직접 읽음 = 원천")
chk("health" in top and "svc" in top["health"], "property 포트(self.core.cfg) · read_config_raw(rb · decode · loads)")
chk("exf" in top and "web" in top["exf"], "주석 달린 전역 + 함수 안 global 대입 → B.cfg 읽기")
chk("quotes" not in top, "이름만 cfg(원천이 설정 아님) = 셈 밖")
vkey = [k for k in vk if k.startswith("config:_poll_cfg|varkey|")]
chk(len(vkey) == 1 and vk[vkey[0]] == ["exf", "upbit"], "변수 키 = 부르는 곳 글자(exf·upbit)", vk)
chk("upbit" not in top, "변수 키 글자는 최상위 키 목록에 넣지 않음(표로만)")
chk(any(u.startswith("helper:lost|guard|") for u in unres), "받는 쪽 못 정한 설정 꼴 이름의 최상위 키 읽기 = guard", unres)
chk(any(u.startswith("watcher:main|whole|<top>.items()") for u in unres), "통째 소비(.items) = whole")
chk(any(u.startswith("watcher:main|passout|<top> → sink.push()") for u in unres), "받는 함수를 못 푸는 곳으로 넘김 = passout", unres)

base = {k: snap[k] for k in ("top", "sub", "varkey", "unresolved")}
fail, gone = C.compare(base, snap)
chk(not fail and not gone, "같은 트리 대조 = 실패 0 · 정보 0", (fail, gone))
ROOT2 = build({"src/helper.py": FILES["src/helper.py"] + "\n\ndef more():\n    c = __import__('config').load_config()\n"
                                                         "    return c.get('newkey'), c.get('web', {}).get('bind')\n"})
s2 = C.snapshot(ROOT2)
fail, gone = C.compare(base, s2)
chk(any("새 최상위 키 읽기 'newkey'" in f for f in fail), "새 최상위 키 = 실패", fail)
chk(any("새 하위 키 읽기 'web.bind'" in f for f in fail), "새 하위 키 = 실패", fail)
ROOT3 = build({"src/config.py": FILES["src/config.py"] + "\n\ndef ex_poll(cfg):\n    return _poll_cfg(cfg, 'bithumb')\n"})
fail, gone = C.compare(base, C.snapshot(ROOT3))
chk(any("새 글자 bithumb" in f for f in fail), "변수 키 자리의 새 글자 = 실패", fail)
ROOT4 = build({"src/helper.py": FILES["src/helper.py"] + "\n\ndef lost2(cfg9):\n    return cfg9['chains']\n"})
fail, gone = C.compare(base, C.snapshot(ROOT4))
chk(any("새 미해결 자리 helper:lost2|guard|" in f for f in fail), "새 미해결 자리(guard) = 실패", fail)
ROOT5 = build({"src/mixin.py": "class ReadMixin:\n    def mix(self):\n        return None\n"})
fail, gone = C.compare(base, C.snapshot(ROOT5))
chk(not fail and any("backup" in g for g in gone), "사라진 키 = 실패 아님(정보)", (fail, gone))
EXTRA6 = ("\n\ndef spread():\n    data = {**config.load_config()}\n    return data.get('spreadkey')\n\n\n"
          "def star_in(*parts):\n    return parts[0].get('starkey')\n\n\n"
          "def kw_in(**kw):\n    return kw['d'].get('kwkey')\n\n\n"
          "def calls():\n    star_in(config.load_config())\n    kw_in(d=config.load_config())\n")
ROOT6 = build({"src/helper.py": FILES["src/helper.py"].replace("import paths\n", "import config\nimport paths\n", 1) + EXTRA6})
s6 = C.snapshot(ROOT6)
fail, gone = C.compare(base, s6)
chk(any("'spreadkey'" in f for f in fail), "{**설정} 펼친 복사 뒤 새 키 읽기 = 실패(자료 흐름)", fail)
chk(any("helper:calls|passout|<top> → star_in()" in f for f in fail) and any("helper:calls|passout|<top> → kw_in()" in f for f in fail),
    "*args·**kw 로 받는 함수에 넘김(매개변수에 못 묶음) = passout 새 자리 = 실패", fail)
EXTRA8 = ("\n\ndef take(d):\n    return d.get('port')\n\n\n"
          "def two():\n    c = config.load_config()\n    return take(c['web']), take(c['backup'])\n\n\n"
          "def dflt(cache):\n    data = cache.get('cur', config.load_config())\n    return data.get('dfltkey')\n\n\n"
          "def ored():\n    data = config.load_config() | {}\n    return data.get('orkey')\n\n\n"
          "def rd(c, key='oldk', *, k2='o2'):\n    return c.get(key), c.get(k2)\n\n\n"
          "def callrd():\n    return rd(config.load_config()), rd(config.load_config(), k2='o3')\n\n\n"
          "def use(read):\n    return read()\n\n\n"
          "def lam():\n    data = config.load_config()\n    use(lambda: data)\n\n\n"
          "def outer():\n    data = config.load_config()\n\n    def inner():\n        return data.get('innerkey')\n    return inner()\n")
ROOT8 = build({"src/helper.py": FILES["src/helper.py"].replace("import paths\n", "import config\nimport paths\n", 1) + EXTRA8})
s8 = C.snapshot(ROOT8)
u8 = s8["unresolved"]
chk(any(u.startswith("helper:take|conflict|d{") and "blk:backup" in u and "blk:web" in u for u in u8),
    "한 매개변수에 서로 다른 블록(web·backup) = conflict 미해결 자리(새 것 = 실패)", [u for u in u8 if "conflict" in u])
chk("dfltkey" in s8["top"], "x.get(k, 설정) 기본값으로 흐른 설정의 읽기", sorted(s8["top"]))
chk("orkey" in s8["top"], "설정 | {} 섞은 복사의 읽기")
chk("innerkey" in s8["top"], "안쪽 함수가 둘레 함수의 설정 이름(닫힘)을 읽음")
vk8 = s8["varkey"]
chk(vk8.get("helper:rd|varkey|<top>[key]") == ["oldk"] and vk8.get("helper:rd|varkey|<top>[k2]") == ["o2", "o3"],
    "변수 키 = 기본값 글자 + 키워드 전용 인자 글자", vk8)
chk(any(u.startswith("helper:lam|passout|lambda→<top> → use()") for u in u8), "lambda 로 설정을 넘김 = passout", u8)
FILES9 = {
    "src/helper.py": FILES["src/helper.py"].replace("import paths\n", "import config\nimport paths\n", 1) + (
        "\n\nKEYS = ('ka', 'kb')\n\n\n"
        "def pickpart(flag):\n    c = config.load_config()\n    part = c['web'] if flag else c['backup']\n    return part.get('port')\n\n\n"
        "def loopk():\n    c = config.load_config()\n    return [c.get(k) for k in KEYS]\n\n\n"
        "def read_settings(p):\n    import json\n    with open(p) as f:\n        return json.load(f)\n\n\n"
        "def viapath():\n    options = read_settings(paths.CONFIG_PATH)\n    return options.get('pathkey')\n\n\n"
        "def other_file(p2):\n    return read_settings(p2).get('notcfg')\n"),
    "src/cache.py": "from config import load_config\n\nOPTIONS = load_config()\n",
    "src/reg.py": ("import config\n\nCFG_KEY = 'chain_wallets'\n\n\n"
                   "def wallets():\n    return config.load_config().get(CFG_KEY)\n\n\n"
                   "def branchy(flag):\n    c = config.load_config()\n    if flag:\n        data = c['web']\n    else:\n        data = c['backup']\n"
                   "    return data.get('keep_db')\n\n\n"
                   "def dflt2():\n    c = config.load_config()\n    part = c.get('web', c.get('backup'))\n    return part.get('port')\n"),
    "src/user2.py": "import config\nimport reg\n\n\ndef f():\n    return config.load_config()[reg.CFG_KEY]\n",
    "src/user3.py": ("import config\nfrom reg import CFG_KEY\n\nCFG_KEY = 'other_key'\n\n\n"
                     "def g():\n    return config.load_config().get(CFG_KEY)\n"),
    "src/user4.py": "import config\nfrom reg import CFG_KEY\n\n\ndef h():\n    return config.load_config().get(CFG_KEY)\n",
    "src/user5.py": ("import config\nimport reg\nimport types\n\nreg = types.SimpleNamespace(CFG_KEY='new')\n\n\n"
                     "def f5():\n    return config.load_config().get(reg.CFG_KEY)\n"),
    "src/consumer.py": ("import cache\nimport config\nfrom cache import OPTIONS as data\n\n\n"
                        "def a():\n    return data.get('fromkey'), cache.OPTIONS.get('attrkey')\n\n\n"
                        "def b():\n    return config._poll_cfg(config.load_config(), 'newsect')\n"),
}
ROOT9 = build(FILES9)
s9 = C.snapshot(ROOT9)
chk(any(u.startswith("helper:pickpart|conflict|식 ") and "blk:backup" in u for u in s9["unresolved"]),
    "조건식 두 갈래 다른 블록 = conflict(식 글) — 뒤 갈래 읽기를 조용히 놓치지 않음", [u for u in s9["unresolved"] if "conflict" in u])
chk(s9["varkey"].get("helper:loopk|varkey|<top>[k]") == ["ka", "kb"], "모듈 상수 글자 묶음을 도는 변수 키 = 그 글자", s9["varkey"])
chk("pathkey" in s9["top"] and "notcfg" not in s9["top"], "경로를 받아 읽는 도우미(설정 경로로 부른 곳만 설정)", sorted(s9["top"]))
chk("fromkey" in s9["top"] and "attrkey" in s9["top"], "다른 모듈 전역 설정(from import 별칭 · 모듈.이름)", sorted(s9["top"]))
chk(s9["varkey"].get("config:_poll_cfg|varkey|<top>[sect]") == ["exf", "newsect", "upbit"], "변수 키 글자 = 다른 모듈에서 부른 글자까지", s9["varkey"])
chk(s9["varkey"].get("reg:wallets|varkey|<top>[CFG_KEY]") == ["chain_wallets"]
    and s9["varkey"].get("user2:f|varkey|<top>[reg.CFG_KEY]") == ["chain_wallets"], "모듈 상수 글자(CFG_KEY · 모듈.상수) 변수 키 = 그 글자", s9["varkey"])
chk(s9["varkey"].get("user3:g|varkey|<top>[CFG_KEY]") == ["?"] and s9["varkey"].get("user4:h|varkey|<top>[CFG_KEY]") == ["chain_wallets"],
    "from import 한 상수를 그 모듈이 다시 대입하면 못 정함('?') · 한 번만 묶이면 원래 글자", s9["varkey"])
chk(s9["varkey"].get("user5:f5|varkey|<top>[reg.CFG_KEY]") == ["?"]
    and "user5:f5|conflict|모듈 별칭 reg.CFG_KEY{재대입 확인 못 함}" in s9["unresolved"],
    "모듈 별칭(reg)을 다시 대입하면 reg.CFG_KEY 를 옛 글자로 풀지 않음('?' + 닫힌 표 conflict)",
    [s9["varkey"].get("user5:f5|varkey|<top>[reg.CFG_KEY]"), [u for u in s9["unresolved"] if u.startswith("user5")]])
chk(any(u.startswith("reg:branchy|conflict|변수 data{") for u in s9["unresolved"]), "if/else 가지마다 다른 블록을 같은 이름에 = conflict",
    [u for u in s9["unresolved"] if "conflict" in u])
chk(any(u.startswith("reg:dflt2|conflict|식 ") for u in s9["unresolved"]), "c.get('web', c.get('backup')) 두 블록 = conflict")
ROOT10 = build(dict(FILES9, **{"src/user6.py": "from builtins import setattr as put\nimport reg\n\nput(reg, 'CFG_KEY', 'new_key')\n"}))
s10 = C.snapshot(ROOT10)
chk(s10["varkey"].get("user2:f|varkey|<top>[reg.CFG_KEY]") == ["?"]
    and any(u.startswith("user2:f|conflict|모듈 별칭 reg.CFG_KEY") for u in s10["unresolved"]),
    "다른 이름으로 들여온 setattr(put(reg, 'CFG_KEY', …))도 바뀔 수 있음으로 봄('?' + 닫힌 표 conflict)",
    [s10["varkey"].get("user2:f|varkey|<top>[reg.CFG_KEY]"), [u for u in s10["unresolved"] if "conflict" in u]])
shutil.rmtree(ROOT10, ignore_errors=True)
ROOT11 = build(dict(FILES9, **{"src/mut.py": "import reg\nreg.CFG_KEY = 'new_key'\n"}))
s11 = C.snapshot(ROOT11)
chk(s11["varkey"].get("user4:h|varkey|<top>[CFG_KEY]") == ["?"] and s11["varkey"].get("reg:wallets|varkey|<top>[CFG_KEY]") == ["?"],
    "다른 모듈이 reg.CFG_KEY = … 로 바꾸면 from import·같은 모듈 상수 글자로도 안 풂('?')",
    [s11["varkey"].get("user4:h|varkey|<top>[CFG_KEY]"), s11["varkey"].get("reg:wallets|varkey|<top>[CFG_KEY]")])
shutil.rmtree(ROOT11, ignore_errors=True)
chain = "".join("\n\ndef a%02d():\n    return a%02d()\n" % (i, i + 1) for i in range(70)) + \
    "\n\ndef a70():\n    return config.load_config()\n\n\ndef deep():\n    return a00().get('deepkey')\n"
ROOT7 = build({"src/helper.py": FILES["src/helper.py"].replace("import paths\n", "import config\nimport paths\n", 1) + chain})
s7 = C.snapshot(ROOT7)
fail, gone = C.compare(base, s7)
chk(not s7["converged"] and any("고정점 미수렴" in f for f in fail), "고정점 상한을 넘는 사슬 = 미수렴 = 대조 실패(거짓 통과 없음)", fail[:3])
for r in (ROOT1, ROOT2, ROOT3, ROOT4, ROOT5, ROOT6, ROOT7, ROOT8, ROOT9):
    shutil.rmtree(r, ignore_errors=True)

BASE_PATH = os.path.join(T.ROOT, C.BASELINE)
chk(os.path.isfile(BASE_PATH), "기준선 파일 있음(%s)" % C.BASELINE)
with open(BASE_PATH, encoding="utf-8") as fh:
    baseline = json.load(fh)
cur = C.snapshot(T.ROOT)
chk(cur["converged"], "지금 트리 고정점 수렴")
fail, gone = C.compare(baseline, cur)
for g in gone[:20]:
    print("정보", g)
chk(not fail, "설정 키 읽기 ⊆ 기준선(새 최상위·하위 키 · 변수 키 글자 · 미해결 자리 0) — 고치는 법: 키를 선언(10-2 뒤 cfg_schema) 하고"
              " 총괄이 cfg_keys.py --write 로 기준선 갱신(사유 커밋)", fail[:40])
print("참고: 최상위 키 %d · 하위 키 %d · 변수 키 자리 %d · 미해결 %d" % (len(cur["top"]), len(cur["sub"]), len(cur["varkey"]),
                                                        len(cur["unresolved"])))
T.finish()
