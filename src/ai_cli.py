from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time

import logs

__all__ = ["CLAUDE_BINS", "REVIEW_MODEL", "CLI_START_GAP_S", "GS", "claude_bin", "CLI_ENV_KEEP", "CLI_ENV_AUTH", "invoke", "cli_error_text", "cli_blocked"]

CLAUDE_BINS = ("claude", os.path.expanduser("~/.local/bin/claude"),
               "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
REVIEW_MODEL = "claude-sonnet-5-5"
CLI_START_GAP_S = 3.0
_CLI_PACE = threading.Lock()
_CLI_LAST = [0.0]
GS = threading.local()


def claude_bin():
    for b in CLAUDE_BINS:
        try:
            subprocess.run([b, "--version"], capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
            _cli_probe(b)
            return b
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _parse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        rv = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return rv if isinstance(rv, dict) else None


CLI_ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
                "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy",
                "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "XDG_CONFIG_HOME")
CLI_ENV_AUTH = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR",
                "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                "CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS")


def _cli_env(src=None) -> dict:
    src = os.environ if src is None else src
    return {k: v for k, v in src.items()
            if k in CLI_ENV_KEEP or k in CLI_ENV_AUTH or k == "LC_ALL" or k.startswith("LC_")}


_CLI_FLAGS = {}


def _cli_probe(b) -> list:
    if b not in _CLI_FLAGS:
        try:
            h = subprocess.run([b, "--help"], capture_output=True, text=True, timeout=20, env=_cli_env(), stdin=subprocess.DEVNULL).stdout or ""
        except Exception:   # noqa: BLE001 [fallback]
            h = ""
        _CLI_FLAGS[b] = ["--no-session-persistence"] if "--no-session-persistence" in h else []
    return _CLI_FLAGS[b]


def _cli_extra(b) -> list:
    return list(_CLI_FLAGS.get(b) or [])


def _cli_cwd():
    import tempfile
    base = os.path.join(tempfile.gettempdir(), f"tj-review-cli-{os.getuid()}")
    try:
        os.makedirs(base, mode=0o700, exist_ok=True)
        st = os.lstat(base)
        import stat as _st9
        if _st9.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not os.listdir(base):
            if st.st_mode & 0o077:
                os.chmod(base, 0o700)
            return base, False
    except OSError:
        pass
    return tempfile.mkdtemp(prefix="tj-review-cli-"), True


def invoke(b: str, stdin_text: str, label: str) -> dict | None:
    with _CLI_PACE:
        wait = _CLI_LAST[0] + CLI_START_GAP_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _CLI_LAST[0] = time.time()
    GS.calls = getattr(GS, "calls", 0) + 1
    work_dir, rm_dir = _cli_cwd()
    try:
        out = subprocess.run(
            [b, "-p", "--strict-mcp-config", "--model", REVIEW_MODEL, "--tools", ""] + _cli_extra(b),
            input=stdin_text,
            capture_output=True, text=True, timeout=600, cwd=work_dir, env=dict(_cli_env(), CLAUDE_CODE_SAFE_MODE="1"))
    finally:
        if rm_dir:
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)
    if out.returncode != 0:
        raw = (out.stderr or "").strip() or (out.stdout or "").strip()
        why = logs.redact_secret_text(raw.splitlines()[0] if raw else "")[:300]
        GS.last_err = why
        logging.getLogger("tj-review").warning("리뷰 CLI 실패(%s, rc=%s): %s", label, out.returncode, why[:200])
        return None
    GS.last_err = None
    rv = _parse((out.stdout or "").strip())
    if rv is None:
        logging.getLogger("tj-review").warning("리뷰 응답 파싱 실패(%s): %s", label, (out.stdout or "").strip()[:200])
    return rv


_MSG_ACCESS = "Claude 접근이 막혀 있어요 — 서버에 로그인된 계정의 조직 설정에서 Claude Code 사용이 꺼져 있어요(관리자 설정 또는 서버에서 claude 다시 로그인)"
_MSG_LIMIT = "Claude 사용 한도에 걸렸어요 — 잠시 뒤 다시 평가하세요"


def cli_blocked(text: str) -> bool:
    return text in (_MSG_ACCESS, _MSG_LIMIT)


def cli_error_text(default: str) -> str:
    w = str(getattr(GS, "last_err", None) or "")
    lw = w.lower()
    if not w:
        return default
    if "disabled claude subscription access" in lw or ("organization" in lw and "disabled" in lw):
        return _MSG_ACCESS
    if "not logged in" in lw or "/login" in lw or "invalid api key" in lw or "authentication" in lw or "oauth" in lw:
        return "Claude 로그인이 필요해요 — 서버에서 claude 로그인(또는 API 키)을 확인하세요"
    if "usage limit" in lw or "rate limit" in lw or "limit reached" in lw or "overloaded" in lw:
        return _MSG_LIMIT
    return default + " — " + logs.redact_secret_text(w)[:120]
