import os
import subprocess

_TIMEOUT = 120


def _git(root, *args, binary=False):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, timeout=_TIMEOUT, env=env,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def toplevel(root):
    out = _git(root, "rev-parse", "--show-toplevel")
    return os.path.realpath(out.strip()) if out else None


def commit_of(root, ref):
    if not ref or ref.startswith("-"):
        return None
    out = _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return out.strip() if out else None


def last_tag(root):
    out = _git(root, "describe", "--tags", "--abbrev=0", "HEAD")
    return (out.strip() or None) if out else None


def last_commit_of(root, relpath):
    out = _git(root, "log", "-1", "--format=%H", "HEAD", "--", relpath)
    return (out.strip() or None) if out else None


def is_shallow(root):
    out = _git(root, "rev-parse", "--is-shallow-repository")
    return bool(out) and out.strip() == "true"


def merge_base(root, a, b):
    out = _git(root, "merge-base", a, b)
    return out.strip() if out else None


def revs_touching(root, base, head, relpath):
    out = _git(root, "log", "--full-history", "--format=%H", "%s..%s" % (base, head), "--", relpath.replace(os.sep, "/"))
    return [x for x in out.split("\n") if x] if out else []


def show(root, commit, relpath):
    out = _git(root, "show", "%s:%s" % (commit, relpath.replace(os.sep, "/")), binary=True)
    return out.decode("utf-8", "replace") if out is not None else None


def tree_paths(root, commit, prefix):
    out = _git(root, "ls-tree", "-r", "--name-only", commit, "--", prefix)
    return [x for x in out.split("\n") if x] if out else []


def cat_files(root, commit, paths):
    if not paths:
        return {}
    req = "".join("%s:%s\n" % (commit, p) for p in paths).encode("utf-8")
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(["git", "-C", root, "cat-file", "--batch"], input=req, capture_output=True,
                           timeout=_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    out, data, pos = {}, p.stdout, 0
    for path in paths:
        nl = data.find(b"\n", pos)
        if nl < 0:
            return None
        head = data[pos:nl].split()
        pos = nl + 1
        if len(head) < 3 or head[1] != b"blob":
            continue
        size = int(head[2])
        out[path] = data[pos:pos + size].decode("utf-8", "replace")
        pos += size + 1
    return out
