#!/usr/bin/env python3
"""Conclave guardrails: ground rules the harness enforces on every tool call.

Modes (first argument):
  pre   PreToolUse   deny a call that breaks a rule (exit 2, reason on stderr)
  post  PostToolUse  redact secret-looking values from a tool result
  stop  Stop / SubagentStop  refuse a final message that contains a secret

Rules (names used in the deny reason and in CONCLAVE_ALLOW):
  read-secret-file     Read, Grep, Glob, Bash and Edit/Write on secret files
  write-secret         secret-looking content in Write/Edit/Bash
  commit-secret        git add/commit of a secret file or secret content
  send-data-out        request bodies, uploads or literal credentials to hosts outside
                       the allowlist (localhost and private ranges, CONCLAVE_ALLOWED_HOSTS)
  subagent-no-git      git commit/push/tag and gh pr merge from a subagent
  protect-history      push to the default branch, force push, branch deletion,
                       reset --hard, rewriting pushed history, clean -f, stash drop
  destructive-command  rm -r outside the project or on the project root, sudo,
                       global installs, global git config, home config edits, pipe to shell
  stay-in-project      Write/Edit or a writing Bash command outside the project directory
                       (temp dirs, the scratchpad and ~/.claude are allowed)
  no-secret-in-output  a final message that contains a secret-looking value

Overrides come from the environment Claude Code was started with, never from the command
line (an inline CONCLAVE_* assignment is itself denied):
  CONCLAVE_ALLOW=rule,rule       skip these rules ("all" skips everything)
  CONCLAVE_ALLOWED_HOSTS=a.com,b.org   extra hosts data may be sent to

A deny reason never contains the matched value. This is a tripwire against mistakes, not a
security boundary: a command can always be written in a way the parser does not see.
"""

import fnmatch
import json
import math
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# ---- configuration -----------------------------------------------------------
ALLOW = {r.strip() for r in os.environ.get("CONCLAVE_ALLOW", "").split(",") if r.strip()}
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("CONCLAVE_ALLOWED_HOSTS", "").split(",") if h.strip()}
HOME = Path.home()

SECRET_FILE_GLOBS = [
    ".env",
    ".env.*",
    ".envrc",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.ppk",
    "credentials",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "service-account*.json",
    "*.tfvars",
    "*.tfstate",
    "*.tfstate.*",
    "secrets.*",
    "secret.*",
    "*.secret",
    "*.secrets",
    ".netrc",
    "_netrc",
    ".pgpass",
    ".my.cnf",
    ".git-credentials",
    ".htpasswd",
    "secring.gpg",
    "private-key*",
    "*.private",
    "token",
    "token.*",
    "*.token",
    "kubeconfig",
]
SECRET_FILE_EXCEPTIONS = [".env.sample", ".env.example", ".env.template", ".env.dist", ".env.schema", "*.pub"]
# Directories under $HOME whose files are credentials or machine configuration.
PROTECTED_HOME_DIRS = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".azure",
    ".config/gh",
    ".config/gcloud",
    ".config/hub",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".bashrc",
    ".zshrc",
    ".profile",
    ".bash_profile",
]
SYSTEM_DIRS = [
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/boot",
    "/var",
    "/opt",
    "/root",
    "/dev",
    "/proc",
    "/sys",
]

# (name, compiled regex). Specific token formats first; the generic assignment rule is
# filtered by length, entropy and placeholder words to keep test fixtures out.
SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Slack webhook", re.compile(r"https://hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]+")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe key", re.compile(r"\b[sr]k_live_[0-9a-zA-Z]{24,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
    ("Twilio key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("PyPI token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}")),
    ("Discord token", re.compile(r"\b[MN][A-Za-z0-9_-]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("Telegram bot token", re.compile(r"\b[0-9]{8,10}:AA[A-Za-z0-9_-]{33}\b")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "connection string with password",
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql|oracle)://[^:/\s'\"]+:(?P<value>[^@/\s'\"]{4,})@"
        ),
    ),
    ("basic auth in URL", re.compile(r"(?i)\bhttps?://[^:/\s'\"@]+:(?P<value>[^@/\s'\"]{4,})@[^\s'\"]+")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+(?P<value>[A-Za-z0-9._~+/=-]{20,})")),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token|secret[_-]?key|encryption[_-]?key|signing[_-]?key)\b\s*[:=]\s*['\"]?(?P<value>[^\s'\"`,;]{8,})"
        ),
    ),
]
GENERIC = {"connection string with password", "basic auth in URL", "bearer token", "credential assignment"}
PLACEHOLDER = re.compile(
    r"^(?:\$|\{\{|<|%|\*{3,}|x{4,}|your|my|the|change|example|placeholder|dummy|fake|test|sample|todo|tbd|none|null|nil|redacted|secret|password|token|key|value|string|path|file|user|admin|hunter2|\.\.\.|-+$|_+$|0+$|1+$|abc|123)",
    re.I,
)

MAX_SCAN_BYTES = 1_000_000
TEMP_PREFIXES = ["/tmp", "/var/tmp", "/dev/shm"]


# ---- helpers -----------------------------------------------------------------
def deny(rule, detail):
    if rule in ALLOW or "all" in ALLOW:
        print(f"Conclave guardrail [{rule}] skipped by CONCLAVE_ALLOW: {detail}", file=sys.stderr)
        return
    print(
        f"Conclave guardrail [{rule}]: {detail} Do not work around this; if the action is right, tell the user and let them do it.",
        file=sys.stderr,
    )
    sys.exit(2)


def entropy(s):
    if not s:
        return 0.0
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_real(value):
    """Filter for the generic patterns: long enough, varied enough, not a placeholder."""
    v = value.strip("'\"` ")
    if len(v) < 12 or PLACEHOLDER.match(v):
        return False
    if v.startswith(("$", "${", "{{", "<", "%(", "os.environ", "process.env", "getenv", "env.")):
        return False
    if entropy(v) < 3.0:
        return False
    classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    return classes >= 2


def find_secrets(text):
    """Return [(pattern name, line number)] for secret-looking values in text."""
    hits = []
    if not text:
        return hits
    for name, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            if name in GENERIC:
                value = m.group("value") if "value" in rx.groupindex else m.group(0)
                if not looks_real(value):
                    continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append((name, line))
    return hits


def redact(text):
    """Replace secret-looking values in text; returns (new_text, count)."""
    count = 0

    def sub(name, rx):
        nonlocal text

        def repl(m):
            nonlocal count
            if name in GENERIC:
                value = m.group("value") if "value" in rx.groupindex else m.group(0)
                if not looks_real(value):
                    return m.group(0)
                count += 1
                start, end = m.span("value") if "value" in rx.groupindex else m.span(0)
                whole = m.group(0)
                return whole[: start - m.start()] + f"[REDACTED {name}]" + whole[end - m.start() :]
            count += 1
            return f"[REDACTED {name}]"

        text = rx.sub(repl, text)

    for name, rx in SECRET_PATTERNS:
        sub(name, rx)
    return text, count


def is_secret_file(path):
    name = Path(str(path)).name
    if not name:
        return False
    if under_protected_home(path):
        return True
    if any(fnmatch.fnmatch(name, g) for g in SECRET_FILE_EXCEPTIONS):
        return False
    return any(fnmatch.fnmatchcase(name.lower(), g.lower()) for g in SECRET_FILE_GLOBS)


def resolve(path, cwd):
    p = Path(os.path.expanduser(str(path)))
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p


def under(path, root):
    try:
        Path(path).relative_to(root)
        return True
    except ValueError:
        return False


def under_protected_home(path):
    p = Path(os.path.expanduser(str(path)))
    if not p.is_absolute():
        return False
    for d in PROTECTED_HOME_DIRS:
        if under(p, HOME / d) or p == HOME / d:
            return True
    return False


def is_temp(path, data):
    p = Path(path)
    for t in TEMP_PREFIXES:
        if under(p, t):
            return True
    for key in ("scratchpad_dir",):
        if data.get(key) and under(p, Path(data[key]).resolve()):
            return True
    for env in ("TMPDIR", "TMP", "TEMP"):
        if os.environ.get(env) and under(p, Path(os.environ[env]).resolve()):
            return True
    if under(p, HOME / ".claude"):
        return True
    return False


def project_dir(data):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    return Path(root).resolve()


def inside_project(path, data):
    p = resolve(path, data.get("cwd") or os.getcwd())
    return under(p, project_dir(data)) or is_temp(p, data)


def git(args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def default_branch(cwd):
    rc, out = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    for cand in ("main", "master"):
        if git(["show-ref", "--verify", "--quiet", f"refs/heads/{cand}"], cwd)[0] == 0:
            return cand
    return "main"


def current_branch(cwd):
    rc, out = git(["symbolic-ref", "--short", "HEAD"], cwd)
    return out.strip() if rc == 0 else ""


def head_is_pushed(cwd):
    rc, up = git(["rev-parse", "--abbrev-ref", "@{upstream}"], cwd)
    if rc != 0 or not up.strip():
        return False
    return git(["merge-base", "--is-ancestor", "HEAD", up.strip()], cwd)[0] == 0


# ---- command parsing -----------------------------------------------------------
OPERATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", ";;"}
WRAPPERS = {"sudo", "env", "nice", "time", "nohup", "command", "exec", "stdbuf", "ionice", "doas", "timeout"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}


def tokenize(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return cmd.split()


def segments(cmd, depth=0):
    """Split a shell command line into simple commands; expand sh -c and pipes-into-shell."""
    out = []
    cur = []
    prev_op = ""
    for tok in tokenize(cmd):
        if tok in OPERATORS:
            if cur:
                out.append((prev_op, cur))
            cur = []
            prev_op = tok
            continue
        cur.append(tok)
    if cur:
        out.append((prev_op, cur))
    expanded = []
    for op, toks in out:
        toks = strip_wrappers(toks)
        expanded.append((op, toks))
        if depth < 3 and toks and Path(toks[0]).name in SHELLS | {"eval"}:
            for i, t in enumerate(toks[1:], 1):
                if t == "-c" and i + 1 < len(toks):
                    expanded.extend(segments(toks[i + 1], depth + 1))
                    break
                if toks[0] == "eval":
                    expanded.extend(segments(" ".join(toks[1:]), depth + 1))
                    break
    return expanded


def strip_wrappers(toks):
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            if t.startswith("CONCLAVE_"):
                deny(
                    "destructive-command",
                    "an inline CONCLAVE_* assignment is not an override; overrides come from the environment Claude Code was started with.",
                )
            i += 1
            continue
        if Path(t).name in WRAPPERS:
            i += 1
            # skip wrapper options such as `timeout 30` or `sudo -u user`
            while i < len(toks) and (
                toks[i].startswith("-") or (Path(t).name == "timeout" and re.match(r"^\d", toks[i]))
            ):
                i += 1
            continue
        break
    return toks[i:]


def git_parts(toks):
    """For a git command: (subcommand, args after it) with global options removed."""
    if not toks or Path(toks[0]).name != "git":
        return None, []
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, toks[i + 1 :]
    return None, []


# ---- rules: Bash -----------------------------------------------------------------
DATA_FLAGS = {
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--data-ascii",
    "-F",
    "--form",
    "--form-string",
    "-T",
    "--upload-file",
    "--json",
    "--post-data",
    "--post-file",
    "--body-data",
    "--body-file",
}
HTTP_TOOLS = {"curl", "wget", "http", "https", "httpie", "xh", "aria2c"}
TRANSFER_TOOLS = {"scp", "sftp", "rsync", "ftp", "nc", "ncat", "netcat", "socat", "telnet"}
LOCAL_HOST = re.compile(
    r"^(?:localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|::1|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|[^.]+\.local|[^.]+\.localhost|host\.docker\.internal)$",
    re.I,
)


def host_of(url):
    m = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^/@\s]*@)?([^/:?#\s]+)", url, re.I)
    return m.group(1).lower() if m else ""


def host_allowed(host):
    if not host or LOCAL_HOST.match(host):
        return True
    return host in EXTRA_HOSTS or any(host.endswith("." + h) for h in EXTRA_HOSTS)


def check_outbound(op, toks):
    if not toks:
        return
    head = Path(toks[0]).name
    if head in HTTP_TOOLS:
        urls = [
            t
            for t in toks[1:]
            if re.match(r"^(?:https?|ftp)://", t, re.I) or re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:[/:]|$)", t, re.I)
        ]
        hosts = [host_of(u) for u in urls]
        sends = any(
            t in DATA_FLAGS
            or t.startswith(tuple(f + "=" for f in DATA_FLAGS))
            or re.match(r"^-[A-Za-z]*[dFT][A-Za-z]*$", t)
            for t in toks[1:]
        )
        method = next(
            (
                toks[i + 1].upper()
                for i, t in enumerate(toks)
                if t in ("-X", "--request", "--method") and i + 1 < len(toks)
            ),
            "",
        )
        sends = sends or method in ("POST", "PUT", "PATCH") or op == "|" or any(t.startswith("@") for t in toks[1:])
        literal_credential = any(find_secrets(t) for t in toks[1:])
        if literal_credential:
            deny(
                "send-data-out",
                f"`{head}` carries a literal credential-looking value in its arguments; use an environment variable the user set, and only toward an allowed host.",
            )
        if sends and not all(host_allowed(h) for h in hosts):
            bad = ", ".join(h for h in hosts if not host_allowed(h)) or "an unknown host"
            deny(
                "send-data-out",
                f"`{head}` would send data to {bad}. Only localhost, private ranges and CONCLAVE_ALLOWED_HOSTS may receive request bodies or uploads.",
            )
    if head in TRANSFER_TOOLS:
        targets = [t for t in toks[1:] if not t.startswith("-")]
        hosts = []
        for t in targets:
            m = re.match(r"^(?:[^@\s:]+@)?([^:/\s]+):", t)
            if m:
                hosts.append(m.group(1).lower())
        if head in ("nc", "ncat", "netcat", "socat", "telnet"):
            hosts.extend(
                t.lower() for t in targets if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$|^\d+\.\d+\.\d+\.\d+$", t, re.I)
            )
        if any(not host_allowed(h) for h in hosts):
            deny(
                "send-data-out",
                f"`{head}` would transfer data to {', '.join(h for h in hosts if not host_allowed(h))}, which is not an allowed host.",
            )


def check_git(data, toks):
    sub, args = git_parts(toks)
    if not sub:
        return
    cwd = data.get("cwd") or os.getcwd()
    in_sub = bool(data.get("agent_id"))
    flags = [a for a in args if a.startswith("-")]
    positional = [a for a in args if not a.startswith("-")]

    if sub in ("commit", "push", "tag") and in_sub:
        deny(
            "subagent-no-git",
            f"`git {sub}` from a subagent ({data.get('agent_type') or 'unknown role'}). Only the main session commits, after the user approves.",
        )
    if sub == "config" and any(f in ("--global", "--system") for f in flags):
        deny(
            "destructive-command",
            "`git config --global/--system` changes the user's identity or tooling for every repository. Use repo-local config.",
        )
    if sub == "commit":
        if "--amend" in flags and head_is_pushed(cwd):
            deny("protect-history", "`git commit --amend` would rewrite a commit that is already on the remote.")
        scan_staged(
            cwd,
            include_unstaged=any(f in ("-a", "--all") for f in flags)
            or any(re.match(r"^-[a-zA-Z]*a", f) for f in flags),
        )
    elif sub == "add":
        scan_add(cwd, args)
    elif sub == "push":
        check_push(cwd, flags, positional)
    elif sub == "reset" and any(f in ("--hard", "--merge") for f in flags):
        deny("protect-history", "`git reset --hard` discards uncommitted work. Use `git stash` or a specific path.")
    elif sub in ("rebase", "filter-branch", "filter-repo", "replace") and head_is_pushed(cwd):
        deny("protect-history", f"`git {sub}` would rewrite history that is already on the remote.")
    elif sub == "branch" and any(f in ("-D", "--delete", "-d") and True for f in flags):
        force = any(f in ("-D", "--force", "-f") or re.match(r"^-[a-zA-Z]*D", f) for f in flags)
        targets = positional
        if force or any(t == default_branch(cwd) for t in targets):
            deny(
                "protect-history",
                "force-deleting a branch (or deleting the default branch) loses commits. Use `git branch -d` on a merged branch, or let the user do it.",
            )
    elif sub == "branch" and any(f in ("-f", "--force", "-M") for f in flags):
        deny("protect-history", "`git branch -f/-M` moves or renames a branch in place; let the user do it.")
    elif sub in ("checkout", "restore", "switch"):
        wholesale = any(p in (".", ":/", "./", "*") for p in positional) and not (sub == "checkout" and "-b" in flags)
        if sub == "checkout" and positional and positional[0] == ".":
            wholesale = True
        if wholesale and not any(f in ("--staged", "-S") for f in flags):
            deny(
                "destructive-command",
                f"`git {sub}` on the whole tree discards every uncommitted change. Name the file, or let the user do it.",
            )
    elif sub == "clean" and any(f in ("-f", "--force") or re.match(r"^-[a-zA-Z]*f", f) for f in flags):
        deny(
            "destructive-command",
            "`git clean -f` deletes untracked files for good. Run it with `-n` to list them and let the user decide.",
        )
    elif sub == "stash" and positional and positional[0] in ("drop", "clear"):
        deny("destructive-command", f"`git stash {positional[0]}` discards saved work.")
    elif sub == "update-ref" and any(f in ("-d", "--delete") for f in flags):
        deny("protect-history", "`git update-ref -d` deletes a ref.")
    elif sub == "reflog" and positional and positional[0] in ("expire", "delete"):
        deny("protect-history", "pruning the reflog removes the safety net for recovering commits.")
    elif sub == "gc" and any(f.startswith("--prune") for f in flags):
        deny("protect-history", "`git gc --prune` removes unreachable commits for good.")


def check_push(cwd, flags, positional):
    if any(
        f in ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--all", "--prune")
        or re.match(r"^-[a-zA-Z]*f", f)
        or f.startswith("--force-with-lease=")
        for f in flags
    ):
        deny(
            "protect-history",
            "force, mirror, all-branches or pruning pushes rewrite or delete remote history. Push the branch plainly, or let the user do it.",
        )
    if any(f in ("--delete", "-d") for f in flags) or any(p.startswith(":") for p in positional[1:]):
        deny("protect-history", "deleting a remote branch; let the user do it.")
    if any(p.startswith("+") for p in positional[1:]):
        deny("protect-history", "a `+refspec` is a force push.")
    default = default_branch(cwd)
    targets = []
    if len(positional) >= 2:
        for spec in positional[1:]:
            dst = spec.split(":", 1)[1] if ":" in spec else spec
            targets.append(dst.rsplit("/", 1)[-1])
    else:
        cur = current_branch(cwd)
        if cur:
            targets.append(cur)
    if default in targets:
        deny(
            "protect-history",
            f"pushing to the default branch `{default}`. Push a feature branch and open a pull request, or let the user push.",
        )


def scan_staged(cwd, include_unstaged=False):
    rc, names = git(["diff", "--cached", "--name-only"], cwd)
    if rc != 0:
        return
    listed = names.split()
    if include_unstaged:
        listed += git(["diff", "--name-only"], cwd)[1].split()
    for n in listed:
        if is_secret_file(n):
            deny("commit-secret", f"`{n}` is a secret file; unstage it (`git reset -- {n}`) and add it to .gitignore.")
    rc, diff = git(["diff", "--cached", "-U0"] + (["HEAD"] if include_unstaged else []), cwd)
    if rc != 0:
        return
    added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    current = ""
    report = []
    for l in diff.splitlines():
        if l.startswith("+++ "):
            current = l[4:].replace("b/", "", 1)
        elif l.startswith("+") and not l.startswith("+++"):
            for name, _ in find_secrets(l[1:]):
                report.append(f"{current} ({name})")
    if report:
        deny(
            "commit-secret",
            f"the staged changes contain secret-looking values: {', '.join(sorted(set(report))[:5])}. Move them to an ignored file or an environment variable.",
        )


def scan_add(cwd, args):
    paths = [a for a in args if not a.startswith("-")]
    everything = any(a in ("-A", "--all", "-u", "--update") for a in args) or any(p in (".", ":/", "./") for p in paths)
    candidates = []
    if everything or not paths:
        rc, out = git(["status", "--porcelain", "--untracked-files=all"], cwd)
        if rc == 0:
            candidates = [l[3:].split(" -> ")[-1] for l in out.splitlines() if l.strip()]
    else:
        for p in paths:
            rc, out = git(["ls-files", "-o", "-m", "--exclude-standard", "--", p], cwd)
            candidates.extend(out.split() if rc == 0 else [p])
    for c in candidates:
        if is_secret_file(c):
            deny("commit-secret", f"`{c}` is a secret file; do not stage it, add it to .gitignore.")
    for c in candidates:
        full = Path(cwd) / c
        try:
            if full.is_file() and full.stat().st_size <= MAX_SCAN_BYTES:
                text = full.read_text(errors="ignore")
                hits = find_secrets(text)
                if hits:
                    deny(
                        "commit-secret",
                        f"`{c}` contains a secret-looking value ({hits[0][0]}, line {hits[0][1]}); do not stage it.",
                    )
        except OSError:
            continue


RM_LIKE = {"rm", "shred", "unlink", "rmdir"}
GLOBAL_INSTALLS = [
    (
        ("npm",),
        lambda a: (
            ("-g" in a or "--global" in a) and any(x in a for x in ("install", "i", "add", "uninstall", "rm", "link"))
        ),
    ),
    (("yarn",), lambda a: a[:1] == ["global"]),
    (("pnpm",), lambda a: "-g" in a or "--global" in a),
    (
        ("pip", "pip3"),
        lambda a: a[:1] == ["install"] and ("--user" in a or not any(k in " ".join(a) for k in ("--target", "-t "))),
    ),
    (("cargo",), lambda a: a[:1] == ["install"]),
    (("gem",), lambda a: a[:1] == ["install"] and "--user-install" not in a),
    (("go",), lambda a: a[:1] == ["install"]),
    (
        ("brew", "apt", "apt-get", "dnf", "yum", "pacman", "zypper", "snap", "flatpak", "port", "choco", "winget"),
        lambda a: True,
    ),
]


def check_destructive(data, op, toks, raw=""):
    if not toks:
        return
    head = Path(toks[0]).name
    cwd = data.get("cwd") or os.getcwd()
    project = project_dir(data)
    env_hint = "activate" in raw or "venv" in raw or "VIRTUAL_ENV" in raw
    if head in ("sudo", "doas", "su"):
        deny("destructive-command", "`sudo` is never run by the team; tell the user what needs root.")
    if head in RM_LIKE:
        flags = [t for t in toks[1:] if t.startswith("-")]
        recursive = (
            any(f in ("-r", "-R", "--recursive") or re.match(r"^-[a-zA-Z]*[rR]", f) for f in flags) or head == "shred"
        )
        for t in toks[1:]:
            if t.startswith("-"):
                continue
            p = resolve(t, cwd)
            if str(p) in ("/", str(HOME)) or p == project or (project / ".git") == p or under(p, project / ".git"):
                deny(
                    "destructive-command",
                    f"`{head}` on `{t}` would remove the project, its history or the home directory.",
                )
            if not (under(p, project) or is_temp(p, data)):
                deny("destructive-command", f"`{head}` on `{t}` is outside the project directory.")
            if recursive and under_protected_home(p):
                deny("destructive-command", f"`{head} -r` on a protected home path.")
    if head in ("chmod", "chown", "chgrp"):
        if any(t in ("-R", "--recursive") or re.match(r"^-[a-zA-Z]*R", t) for t in toks[1:]) and any(
            resolve(t, cwd) in (Path("/"), HOME, project)
            or not (under(resolve(t, cwd), project) or is_temp(resolve(t, cwd), data))
            for t in toks[1:]
            if not t.startswith("-") and not re.match(r"^[0-7]{3,4}$|^[ugoa]*[+-=]", t)
        ):
            deny("destructive-command", f"recursive `{head}` outside the project or on its root.")
        if "777" in toks:
            deny("destructive-command", "mode 777 makes files writable by everyone.")
    if head in ("mkfs", "fdisk", "parted", "dd") or any(t.startswith("of=/dev/") for t in toks):
        deny("destructive-command", f"`{head}` touches devices or partitions.")
    if head in ("crontab",) and "-r" in toks:
        deny("destructive-command", "`crontab -r` removes every scheduled job.")
    if op == "|" and head in SHELLS:
        deny(
            "destructive-command",
            "piping downloaded or generated text into a shell runs it unread. Save it to a file in the project, read it, then run it.",
        )
    args = toks[1:]
    for names, pred in GLOBAL_INSTALLS:
        if head in names:
            # python -m pip install → treat like pip
            if pred(args):
                if head in ("pip", "pip3") and (env_hint or "/bin/pip" in toks[0]):
                    break
                deny(
                    "destructive-command",
                    f"`{head} {' '.join(args[:2])}` installs outside the project. Use the project's environment (venv, node_modules, a pinned tool in the build) or ask the user to install it.",
                )
    if head == "python" or head == "python3":
        if (
            args[:2] == ["-m", "pip"]
            and args[2:3] == ["install"]
            and not env_hint
            and "/bin/python" not in toks[0]
            and "--target" not in args
            and "-t" not in args
        ):
            deny("destructive-command", "`python -m pip install` outside a virtual environment installs globally.")


WRITE_VERBS = {"tee", "cp", "mv", "install", "mkdir", "touch", "ln", "truncate", "dd", "rsync"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}


def check_scope_bash(data, toks, raw):
    cwd = data.get("cwd") or os.getcwd()
    if not toks:
        return
    head = Path(toks[0]).name
    targets = []
    # redirections: shlex with punctuation_chars splits '>' as its own token
    for i, t in enumerate(toks):
        if t in REDIRECTS or t == ">" or t == ">>":
            if i + 1 < len(toks):
                targets.append(toks[i + 1])
    if head in WRITE_VERBS:
        positional = [t for t in toks[1:] if not t.startswith("-")]
        if head in ("cp", "mv", "install", "ln", "rsync") and len(positional) >= 2:
            targets.append(positional[-1])
        elif head in ("tee", "mkdir", "touch", "truncate"):
            targets.extend(positional)
    if head == "sed" and any(t == "-i" or t.startswith("-i") for t in toks[1:]):
        targets.extend(t for t in toks[1:] if not t.startswith("-") and "/" in t)
    for t in targets:
        if t.startswith("/dev/"):
            continue
        if under_protected_home(t):
            deny(
                "destructive-command",
                f"writing to `{t}`, a credential or machine-configuration path in the home directory.",
            )
        p = resolve(t, cwd)
        if any(under(p, s) for s in SYSTEM_DIRS):
            deny("destructive-command", f"writing to `{t}` under a system directory.")
        if not inside_project(t, data):
            deny(
                "stay-in-project",
                f"writing to `{t}`, outside the project directory. Only the project, temp dirs and the scratchpad are writable.",
            )


def check_secret_tokens(toks):
    for t in toks:
        if "/" in t or t.startswith(".") or t.lower() in ("credentials", "token", "kubeconfig"):
            if is_secret_file(t):
                deny(
                    "read-secret-file",
                    f"`{Path(t).name}` is a secret file; its contents never enter the context. Use the sample or ask the user for the variable name.",
                )


def check_bash(data):
    cmd = data["tool_input"].get("command") or ""
    if not cmd.strip():
        return
    for name, line in find_secrets(cmd):
        deny(
            "write-secret",
            f"the command contains a secret-looking value ({name}). Reference the secret through an environment variable the user set instead.",
        )
    for op, toks in segments(cmd):
        check_secret_tokens(toks)
        check_outbound(op, toks)
        check_git(data, toks)
        check_destructive(data, op, toks, cmd)
        check_scope_bash(data, toks, cmd)


# ---- rules: file tools -------------------------------------------------------------
def check_read(data):
    path = data["tool_input"].get("file_path") or data["tool_input"].get("path") or ""
    if path and is_secret_file(path):
        deny(
            "read-secret-file",
            f"`{Path(path).name}` is a secret file; its contents never enter the context. Use the sample file or ask the user for the variable name.",
        )


def check_write(data):
    inp = data["tool_input"]
    path = inp.get("file_path") or ""
    content = inp.get("content") if "content" in inp else inp.get("new_string", "")
    if path:
        if is_secret_file(path):
            deny(
                "read-secret-file",
                f"`{Path(path).name}` is a secret file; the team does not create or edit credentials. Write a `.sample` and tell the user which variables to set.",
            )
        if under_protected_home(path):
            deny(
                "destructive-command", f"`{path}` is a credential or machine-configuration path in the home directory."
            )
        p = resolve(path, data.get("cwd") or os.getcwd())
        if any(under(p, s) for s in SYSTEM_DIRS):
            deny("destructive-command", f"`{path}` is under a system directory.")
        if not inside_project(path, data):
            deny(
                "stay-in-project",
                f"`{path}` is outside the project directory. Only the project, temp dirs and the scratchpad are writable.",
            )
    hits = find_secrets(content or "")
    if hits:
        name, line = hits[0]
        deny(
            "write-secret",
            f"the content contains a secret-looking value ({name}, line {line} of the new text). Keep secrets in an ignored file or an environment variable and reference them by name.",
        )


def check_webfetch(data):
    url = data["tool_input"].get("url") or ""
    if find_secrets(url):
        deny("send-data-out", "the URL carries a credential-looking value.")


# ---- modes -------------------------------------------------------------------------
def mode_pre(data):
    tool = data.get("tool_name", "")
    if tool == "Bash":
        check_bash(data)
    elif tool in ("Read", "Grep", "Glob", "NotebookRead"):
        check_read(data)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        check_write(data)
    elif tool == "WebFetch":
        check_webfetch(data)


def redact_any(obj):
    total = 0
    if isinstance(obj, str):
        new, n = redact(obj)
        return new, n
    if isinstance(obj, list):
        out = []
        for item in obj:
            new, n = redact_any(item)
            out.append(new)
            total += n
        return out, total
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            new, n = redact_any(v)
            out[k] = new
            total += n
        return out, total
    return obj, 0


def mode_post(data):
    resp = data.get("tool_response")
    if resp is None:
        return
    new, n = redact_any(resp)
    if n:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "updatedToolOutput": new,
                        "additionalContext": f"Conclave guardrail redacted {n} secret-looking value(s) from this tool result. Do not try to recover or reconstruct them.",
                    }
                }
            )
        )


def mode_stop(data):
    if data.get("stop_hook_active"):
        return
    text = data.get("last_assistant_message") or ""
    hits = find_secrets(text)
    if hits:
        names = ", ".join(sorted({h[0] for h in hits}))
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": f"Conclave guardrail [no-secret-in-output]: the final message contains what looks like a secret ({names}). Rewrite it without the value: say where the secret lives and how to set it, never what it is. Then stop.",
                }
            )
        )


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Conclave guardrail: could not read hook input ({e}); allowing.", file=sys.stderr)
        return
    if "no-guard" in ALLOW or "all" in ALLOW:
        return
    if mode == "pre":
        mode_pre(data)
    elif mode == "post":
        mode_post(data)
    elif mode == "stop":
        mode_stop(data)


if __name__ == "__main__":
    main()
