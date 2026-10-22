import atexit
import os
import shutil
import subprocess
import tempfile

REQUIRE_GPG = os.environ.get("TJ_TEST_REQUIRE_GPG") == "1"
SOCK_MAX = 100
SOCK_NAME = "S.gpg-agent.browser"
DAEMONS = ("gpg-agent", "keyboxd", "dirmngr", "scdaemon")


def gpg_path():
    return shutil.which("gpg")


def skip_or_fail(T, what):
    if REQUIRE_GPG:
        T.chk(False, "gpg 없음 — %s 못 돌림(TJ_TEST_REQUIRE_GPG=1)" % what)
    else:
        print("SKIP gpg 없음 — %s 건너뜀" % what, flush=True)


def short_tmpdir(prefix="tjg"):
    base = tempfile.gettempdir()
    why = None
    if len(os.path.join(base, prefix + "XXXXXXXX", "restore", SOCK_NAME)) > SOCK_MAX:
        why = "기본 임시 폴더 경로가 길어 소켓 한도를 넘음(%d자) — /tmp 아래로" % len(base)
        base = "/tmp"
    elif any(ch.isspace() for ch in base):
        why = "기본 임시 폴더 경로에 공백(데몬 명령 줄 --homedir 판정이 갈림) — /tmp 아래로"
        base = "/tmp"
    d = tempfile.mkdtemp(prefix=prefix, dir=base)
    os.chmod(d, 0o700)
    return d, why


def agents_left(homes):
    homes = [h for h in homes if h]
    if not homes:
        return 0
    try:
        r = subprocess.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return -1
    if r.returncode or not r.stdout.strip():
        return -1
    return len(_agent_pids(r.stdout, homes))


def _agent_pids(ps_out, homes):
    pids, want = [], set(homes)
    for ln in ps_out.splitlines():
        parts = ln.strip().split()
        if len(parts) < 2 or not parts[0].isdigit() or os.path.basename(parts[1]) not in DAEMONS:
            continue
        args = parts[2:]
        hd = {args[i + 1] for i in range(len(args) - 1) if args[i] == "--homedir"} | \
            {a.split("=", 1)[1] for a in args if a.startswith("--homedir=")}
        if hd & want:
            pids.append(int(parts[0]))
    return pids


class Kit:

    def __init__(self):
        self.gpg = gpg_path()
        self.gpgconf = shutil.which("gpgconf")
        self.root, self.why = None, None
        self.restore = self.server = None
        self.fpr = None
        self.version = None
        atexit.register(self.close)

    def run(self, home, args, inp=None, check=True):
        env = dict(os.environ, GNUPGHOME=home, LC_ALL="C")
        r = subprocess.run([self.gpg, "--homedir", home, "--batch", "--no-tty"] + list(args), input=inp,
                           capture_output=True, env=env, timeout=120)
        err = r.stderr.decode("utf-8", "replace")
        if check and r.returncode:
            raise RuntimeError("gpg %s 실패 rc=%d: %s" % (args[:2], r.returncode, err.strip()[-300:]))
        return r.returncode, r.stdout, err

    def _home(self, name):
        h = os.path.join(self.root, name)
        os.makedirs(h, mode=0o700)
        os.chmod(h, 0o700)
        return h

    def make(self):
        if not self.gpg:
            raise RuntimeError("gpg 없음")
        self.root, self.why = short_tmpdir()
        self.restore, self.server = self._home("restore"), self._home("server")
        self.version = self.run(self.restore, ["--version"])[1].decode("utf-8", "replace").splitlines()[0]
        self.run(self.restore, ["--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "tj-test",
                                "future-default", "default", "1d"])
        self.fpr = self.fingerprints(self.restore, secret=True)[0]
        pub = self.run(self.restore, ["--armor", "--export", self.fpr])[1]
        self.run(self.server, ["--import"], inp=pub)
        return self.fpr

    def fingerprints(self, home, secret=False):
        out = self.run(home, ["--with-colons", "--list-secret-keys" if secret else "--list-keys"])[1]
        fprs, want = [], False
        for ln in out.decode("utf-8", "replace").splitlines():
            f = ln.split(":")
            if f[0] in ("pub", "sec"):
                want = True
            elif f[0] == "fpr" and want:
                fprs.append(f[9])
                want = False
        return fprs

    def encrypt(self, src, dst):
        return self.run(self.server, ["--yes", "--trust-model", "always", "--compress-algo", "none", "--recipient", self.fpr,
                                      "--output", dst, "--encrypt", src])[0]

    def decrypt(self, src, dst, home=None):
        return self.run(home or self.restore, ["--yes", "--pinentry-mode", "loopback", "--passphrase", "", "--output", dst,
                                               "--decrypt", src], check=home is None)[0]

    def homes(self):
        return [h for h in (self.restore, self.server) if h]

    def close(self):
        homes = self.homes()
        try:
            for h in homes:
                if self.gpgconf and os.path.isdir(h):
                    try:
                        subprocess.run([self.gpgconf, "--homedir", h, "--kill", "all"], capture_output=True, timeout=30,
                                       env=dict(os.environ, GNUPGHOME=h))
                    except (OSError, subprocess.SubprocessError):
                        pass
            if homes and agents_left(homes) != 0:
                try:
                    out = subprocess.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=20).stdout
                except (OSError, subprocess.SubprocessError):
                    out = ""
                for pid in _agent_pids(out, homes):
                    try:
                        os.kill(pid, 15)
                    except OSError:
                        pass
        finally:
            if self.root:
                shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
