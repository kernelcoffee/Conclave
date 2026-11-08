#!/usr/bin/env python3
"""Conclave guardrails: ground rules the harness enforces on every tool call.

Modes (first argument):
  pre   PreToolUse   deny a call that breaks a rule (exit 2, reason on stderr), or ask
                     the user first (one permissionDecision ask, only when nothing denied)
  post  PostToolUse  redact secret-looking values from a tool result
  stop  Stop / SubagentStop  refuse a final message that contains a secret

Rules (names used in the deny reason and in CONCLAVE_ALLOW):
  read-secret-file     Read, Grep, Glob, Bash and Edit/Write on secret files (a heredoc
                       body that only cat or tee show or write, or that git commit/tag/notes
                       -F - or gh --body-file - read as a message, is text, not filenames,
                       unless it is unquoted and has a `$` or backtick for bash to expand;
                       a `-m` or `--body` value from `"$(cat <<'EOF' ...)"` is text too)
  write-secret         a secret literal in the text of a file tool or a Bash command: a
                       quoted value after a credential key, or a bare one unless it is an
                       expression (a call, a member path, an index, an environment lookup
                       or a template placeholder; in a config file only the last two) or,
                       in the code of a source file (not its strings or comments), a plain
                       identifier; or a known-prefix token anywhere. Never a key name alone
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
  no-secret-in-output  a final message that contains a secret literal or known-prefix token
  commit-approval      git commit/push/tag and gh pr/release from the main session always
                       ask the user first (a permission prompt); allow it with
                       CONCLAVE_ALLOW=commit-approval when the user said so
  pii                  personal or identifiable information (email addresses, phone
                       numbers, home-directory paths, the local git identity, card,
                       IBAN or national id numbers) in written files, heredoc text,
                       staged changes, commit or PR text, or data sent out; in the author,
                       maintainer, contributor and owner fields of plugin.json,
                       marketplace.json, package.json, pyproject.toml and Cargo.toml an
                       email or the git identity is a public contact. A hit asks the user
                       from the main session (permissionDecision ask) and denies from a
                       subagent (agent_id set), which cannot carry the prompt;
                       CONCLAVE_ALLOW=pii skips both

Overrides come from the environment Claude Code was started with, never from the command
line (an inline CONCLAVE_* assignment is itself denied):
  CONCLAVE_ALLOW=rule,rule       skip these rules ("all" skips everything)
  CONCLAVE_ALLOWED_HOSTS=a.com,b.org   extra hosts data may be sent to
  CONCLAVE_PII_ALLOW=you@your.org,Your Name      values the pii rule accepts (a public contact)

A deny or ask reason never contains the matched value. This is a tripwire against mistakes, not a
security boundary: a command can always be written in a way the parser does not see.
"""

import bisect
import fnmatch
import json
import math
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from functools import cached_property
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

# The key words of a credential assignment; a text without one cannot match it.
CREDENTIAL_KEYS = (
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret"
    r"|auth[_-]?token|secret[_-]?key|encryption[_-]?key|signing[_-]?key"
)
CREDENTIAL_KEY = re.compile(rf"(?i)\b(?:{CREDENTIAL_KEYS})\b")

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
        # key and separator on one line (`=`, `:`, `:=` or `=>`, never `==` or `:==`); the
        # value on that line, or as the first word of a later line after blank lines when
        # it is quoted or a single word (no `:`, `=` only as base64 padding) that no
        # separator follows. credential_literal takes a value on a later line only in the
        # forms each text kind allows (loose_value).
        "credential assignment",
        re.compile(
            rf"(?i)\b(?P<key>{CREDENTIAL_KEYS})\b"
            r"[ \t]*(?P<sep>:=|=>|[:=])(?![=>])[ \t]*"
            r"(?:(?:\r?\n[ \t]*)*?\r?\n[ \t]*(?=['\"`]|[^\s'\"`,;:=]{8,}={0,3}(?!\S)(?![ \t]*[:=])))?"
            r"['\"`]?(?P<value>[^\s'\"`,;]{8,})"
        ),
    ),
]
GENERIC = {"connection string with password", "basic auth in URL", "bearer token", "credential assignment"}
PLACEHOLDER = re.compile(
    r"^(?:\$|\{\{|<|%|\*{3,}|x{4,}|your|my|the|change|example|placeholder|dummy|fake|test|sample|todo|tbd|none|null|nil|redacted|secret|password|token|key|value|string|path|file|user|admin|hunter2|\.\.\.|-+$|_+$|0+$|1+$|abc|123)",
    re.I,
)

MAX_SCAN_BYTES = 1_000_000

# ---- personal and identifiable information ------------------------------------------
PII_ALLOW = {v.strip().lower() for v in os.environ.get("CONCLAVE_PII_ALLOW", "").split(",") if v.strip()}
# Files whose job is to name people; the pii rule does not apply to them.
PII_EXEMPT_FILES = ["LICENSE*", "LICENCE*", "COPYING*", "AUTHORS*", "CONTRIBUTORS*", "MAINTAINERS*", "CODEOWNERS", ".mailmap", "NOTICE*"]
EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")
SAFE_EMAIL_DOMAINS = re.compile(r"(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost|local|users\.noreply\.github\.com|noreply\.github\.com)$", re.I)
SAFE_EMAIL_LOCAL = re.compile(r"^(?:no-?reply|donotreply|do-not-reply|noreply\+.*|git|nobody|root|postmaster|security|support|admin|info|hello|contact|webmaster|user|someone|test|foo|bar|me|you|name|email|first\.last)$", re.I)
PHONE = re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){2,4}(?!\w)")
HOME_PATH = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\{1,2}Users\\{1,2})([A-Za-z0-9._-]+)")
SAFE_HOME_USERS = {"user", "username", "me", "you", "name", "runner", "ubuntu", "vscode", "node", "app", "dev", "developer", "example", "your-name", "yourname", "<user>", "$user", "public", "default", "shared"}
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
US_SSN = re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)")
FR_NIR = re.compile(r"(?<!\d)[12] ?\d{2} ?(?:0[1-9]|1[0-2]) ?(?:\d{2}|2[AB]) ?\d{3} ?\d{3} ?\d{2}(?!\d)")


def luhn_ok(digits):
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def iban_ok(raw):
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in moved)
    return int(num) % 97 == 1


_LOCAL_IDENTITY = None


def local_identity(cwd):
    """The machine's own identity: git user.name/email, the login name, the home path."""
    global _LOCAL_IDENTITY
    if _LOCAL_IDENTITY is None:
        ident = set()
        for key in ("user.email", "user.name"):
            rc, out = git(["config", "--get", key], cwd or os.getcwd())
            v = out.strip()
            if rc == 0 and v and (key == "user.email" or len(v.split()) >= 2):
                ident.add(v)
        login = os.environ.get("USER") or os.environ.get("LOGNAME") or HOME.name
        if login and login.lower() not in SAFE_HOME_USERS and len(login) >= 3:
            ident.add(str(HOME))
        _LOCAL_IDENTITY = {v for v in ident if v.lower() not in PII_ALLOW}
    return _LOCAL_IDENTITY


def pii_exempt(path):
    name = Path(str(path)).name if path else ""
    return bool(name) and any(fnmatch.fnmatch(name.upper(), g.upper()) for g in PII_EXEMPT_FILES)


# Package manifests name their authors on purpose. In these fields an email address or the
# local git identity is a public contact; every other kind of pii still counts there, and
# the rest of the manifest is scanned as usual.
JSON_CONTACT_KEYS = {"author", "authors", "maintainers", "contributors", "owner"}
# Where each JSON manifest names its contacts, by path from the root ("[]" is an array
# item): the keys of the top-level object, and in marketplace.json each plugin's author.
JSON_CONTACT_PLACES = {
    "plugin.json": {(): JSON_CONTACT_KEYS},
    "package.json": {(): JSON_CONTACT_KEYS},
    "marketplace.json": {(): JSON_CONTACT_KEYS, ("plugins", "[]"): {"author"}},
}
JSON_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]')
# TOML manifests name their contacts in `authors = [...]` or `maintainers = [...]`, one line
# or several, under these tables only; a quoted `]` does not end the array. Anything the
# pattern cannot read is left to the normal scan.
TOML_CONTACT_TABLES = {"pyproject.toml": {"project", "tool.poetry"}, "Cargo.toml": {"package", "workspace.package"}}
TOML_CONTACT = re.compile(
    r"""(?m)^[ \t]*(?:authors|maintainers)[ \t]*=[ \t]*(\[(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*'|[^\]"'])*\])"""
)
TOML_TABLE = re.compile(r"(?m)^[ \t]*(\[\[?)[ \t]*([^\[\]\n]*?)[ \t]*\]")
# Strings and comments, so that a line inside a multi-line string is not read as a key.
TOML_INERT = re.compile(r'"""(?:[^\\]|\\.)*?"""|\'\'\'.*?\'\'\'|"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'|#[^\n]*', re.S)
CONTACT_MANIFESTS = JSON_CONTACT_PLACES.keys() | TOML_CONTACT_TABLES.keys()


class _JsonLevel:
    """An object or array met while walking a JSON manifest's tokens."""

    def __init__(self, bracket, in_contact, contact_keys, path):
        self.bracket = bracket
        self.in_contact = in_contact  # the whole container is a contact value
        self.contact_keys = contact_keys  # keys of this object that hold a contact
        self.path = path
        self.key = None
        self.expect_key = bracket == "{"


def json_contact_spans(text, places):
    """Spans of the string values under the contact keys at the given places of a JSON document."""
    try:
        json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return []
    spans = []
    stack = []
    for m in JSON_TOKEN.finditer(text):
        tok = m.group(0)
        top = stack[-1] if stack else None
        in_contact = top is not None and (
            top.in_contact or (top.bracket == "{" and not top.expect_key and top.key in top.contact_keys)
        )
        if tok in ("{", "["):
            path = () if top is None else (*top.path, top.key if top.bracket == "{" else "[]")
            keys = places.get(path, set()) if tok == "{" and not in_contact else set()
            stack.append(_JsonLevel(tok, in_contact, keys, path))
        elif tok in ("}", "]"):
            stack.pop()
        elif tok == ":":
            top.expect_key = False
        elif tok == ",":
            top.expect_key = top.bracket == "{"
        elif top is not None and top.expect_key:
            top.key = json.loads(tok)
        elif in_contact:
            spans.append(m.span())
    return spans


def toml_contact_spans(text, tables):
    """Spans of the `authors` and `maintainers` arrays of the given tables of a TOML document."""
    inert = [m.span() for m in TOML_INERT.finditer(text)]
    multiline = [(s, e) for s, e in inert if text.startswith(('"""', "'''"), s)]

    def is_inert(pos):
        return any(s <= pos < e for s, e in inert)

    headers = []
    for m in TOML_TABLE.finditer(text):
        if not is_inert(m.start(1)):
            name = re.sub(r"[ \t]*\.[ \t]*", ".", m.group(2))
            headers.append((m.start(), name if m.group(1) == "[" else None))
    spans = []
    for m in TOML_CONTACT.finditer(text):
        start, end = m.span(1)
        if any(s < end and start < e for s, e in multiline):  # the array is not inside a string
            continue
        table = next((name for pos, name in reversed(headers) if pos < m.start()), None)
        if table in tables:
            spans.append((start, end))
    return spans


def public_contact_spans(path, text):
    """Character spans of a manifest's author and maintainer fields; empty for other files."""
    name = Path(str(path)).name if path else ""
    if not text:
        return []
    if name in JSON_CONTACT_PLACES:
        return json_contact_spans(text, JSON_CONTACT_PLACES[name])
    if name in TOML_CONTACT_TABLES:
        return toml_contact_spans(text, TOML_CONTACT_TABLES[name])
    return []


def find_file_pii(path, text, cwd=None):
    """find_pii for the content of a file: exempt files skip it, manifest contact fields are public."""
    if pii_exempt(path):
        return []
    return find_pii(text, cwd, public_contact_spans(path, text))


def find_pii(text, cwd=None, public=()):
    """Return [(kind, line)] for personal or identifiable values in text. Never the value.

    `public` holds character spans of public-contact fields: an email address or the local
    git name or email inside one is not reported; any other kind is.
    """
    hits = []
    if not text:
        return hits

    def add(kind, pos, contact=False):
        if contact and any(start <= pos < end for start, end in public):
            return
        hits.append((kind, text.count("\n", 0, pos) + 1))

    for m in EMAIL.finditer(text):
        local, domain = m.group(1), m.group(2)
        token_start = max(text.rfind(c, 0, m.start()) for c in " \t\n'\"`<>()[]") + 1
        between = text[token_start : m.start()]
        scheme_end = between.find("://")
        if scheme_end >= 0 and not re.search(r"[/?#]", between[scheme_end + 3 :]):
            continue  # userinfo in a URL (scheme://user:pass@host), not an address; a query is not
        if m.group(0).lower() in PII_ALLOW or SAFE_EMAIL_DOMAINS.search(domain) or SAFE_EMAIL_LOCAL.match(local):
            continue
        if domain.lower() in ("anthropic.com",) and local.lower().startswith("noreply"):
            continue
        add("email address", m.start(), contact=True)
    for m in PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 15 and m.group(0).strip().lower() not in PII_ALLOW:
            add("phone number", m.start())
    for m in HOME_PATH.finditer(text):
        user = m.group(1).lower()
        if user in SAFE_HOME_USERS or user.startswith(("$", "<", "{", "%")) or f"/home/{user}" in PII_ALLOW:
            continue
        add("home-directory path naming a user", m.start())
    for m in CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and len(set(digits)) > 3 and luhn_ok(digits):
            add("payment card number", m.start())
    for m in IBAN.finditer(text):
        try:
            if iban_ok(m.group(0)):
                add("IBAN", m.start())
        except ValueError:
            continue
    for m in US_SSN.finditer(text):
        add("national id number", m.start())
    for m in FR_NIR.finditer(text):
        if len(re.sub(r"\D", "", m.group(0))) >= 13:
            add("national id number", m.start())
    for value in local_identity(cwd):
        # every occurrence: one inside a public-contact field must not hide one outside it.
        # The home path is never a contact, whatever field it sits in.
        idx = text.find(value)
        while idx >= 0:
            add("the local user's identity (git name or email, home path)", idx, contact=value != str(HOME))
            idx = text.find(value, idx + 1)
    return hits


PII_PLACEHOLDER = "a placeholder (user@example.com, /home/user, ~/...) or a relative path"


def pii_detail(where: str, hits: list[tuple[str, int]]) -> str:
    """One finding of the pii rule: the place and the kinds, never a value."""
    kinds = ", ".join(sorted({k for k, _ in hits}))
    first = min(line for _, line in hits)
    return f"{where} contains personal or identifiable information ({kinds}; first at line {first})."


def listing(entries: list[str], cap: int = 5) -> str:
    """Up to cap distinct entries, sorted, and how many more there are."""
    items = sorted(set(entries))
    more = f" and {len(items) - cap} more" if len(items) > cap else ""
    return ", ".join(items[:cap]) + more


def is_subagent(data: dict) -> bool:
    """True for a call from a subagent. agent_id is set only there; agent_type alone is also
    sent from the main thread of a session started with an agent (`--agent`, or a plugin's
    settings.json), so it does not tell the two apart."""
    return bool(data.get("agent_id"))


def report_pii(data: dict, finding: str) -> None:
    """pii asks the user from the main session and denies from a subagent, which cannot carry
    the prompt to the user. The ask is only collected here: mode_pre emits it at the end, so
    any rule that denies the same call wins."""
    if is_subagent(data):
        deny(
            "pii",
            f"{finding} A subagent cannot confirm this: replace it with {PII_PLACEHOLDER}, or stop and hand it "
            "back so the main session makes the change and the user is asked.",
        )
        return
    if skipped("pii", finding):
        return
    PENDING_PII.append(finding)


# Asks, collected during the checks and emitted as one "ask" only if no rule denied:
# commit-approval actions and pii findings from the main session.
PENDING_ASK: list[str] = []
PENDING_PII: list[str] = []
TEMP_PREFIXES = ["/tmp", "/var/tmp", "/dev/shm"]


# ---- helpers -----------------------------------------------------------------
def skipped(rule: str, detail: str) -> bool:
    """True when CONCLAVE_ALLOW skips rule; says so on stderr with the detail."""
    if rule in ALLOW or "all" in ALLOW:
        print(f"Conclave guardrail [{rule}] skipped by CONCLAVE_ALLOW: {detail}", file=sys.stderr)
        return True
    return False


def deny(rule, detail):
    if skipped(rule, detail):
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


# The credential assignment pattern fires on a literal only, never on a key name alone. A
# value in quotes is a literal. A bare value that passes looks_real is a literal unless
#   (a) it is an expression by its syntax: a call `name(...)`, a member path `a.b.c`, an
#       index `a[...]`, an environment lookup or a template placeholder; outside source
#       text a name in a call or member path that looks random is not code (random_name);
#   (b) it is a plain identifier and the text is source code.
# What a text is (TextKind) comes from where it comes from, never from its shape: the file a
# tool writes or a command shows, the place of a command word, a message channel. Source
# text takes (a) and (b), config text only the lookups and placeholders of (a), every other
# kind all of (a) and nothing else. In source text a key inside a string or a comment is
# data (source_inert_spans).
CONFIG_SUFFIXES = {
    ".env", ".ini", ".cfg", ".conf", ".cnf", ".properties", ".toml", ".tfvars", ".yaml", ".yml", ".json",
    ".jsonc", ".sh", ".bash", ".zsh", ".ksh", ".ps1", ".psm1", ".bat", ".cmd", ".mk", ".dockerfile",
    ".containerfile", ".service", ".socket", ".timer",
}
CONFIG_NAMES = {
    ".env", ".envrc", ".npmrc", ".pypirc", ".netrc", ".pgpass", ".yarnrc", ".gemrc", "environ",
    ".bashrc", ".zshrc", ".profile", ".bash_profile", "dockerfile", "containerfile", "makefile", "gnumakefile",
}
CONFIG_NAME_PREFIXES = (".env.", "dockerfile.", "containerfile.")
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".pyw", ".ipynb", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".vue",
    ".svelte", ".java", ".kt", ".kts", ".scala", ".groovy", ".gradle", ".go", ".rs", ".c", ".h", ".cc",
    ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".m", ".mm", ".swift", ".cs", ".fs", ".vb", ".rb", ".php",
    ".pl", ".pm", ".lua", ".r", ".jl", ".dart", ".ex", ".exs", ".erl", ".hrl", ".clj", ".cljs", ".hs",
    ".ml", ".mli", ".elm", ".zig", ".nim", ".sol", ".qml",
}
# A template or copy of a file is read as the file: app.ini.example, settings.py.in.
TEMPLATE_SUFFIXES = {".example", ".sample", ".template", ".tmpl", ".tpl", ".dist", ".default", ".in", ".orig", ".bak"}
# The interpreter a `#!` line names, behind `env` and its options when it is env.
SHEBANG = re.compile(r"#![ \t]*(?:\S*/)?(?:env[ \t]+(?:-\S*[ \t]+)*)?(?P<prog>[^\s/]+)")
SHEBANG_SOURCE = re.compile(
    r"(?:python|pypy|node|nodejs|deno|bun|ts-node|tsx|ruby|perl|php|lua|luajit|rscript|julia|groovy|"
    r"kotlin|scala|swift|elixir|escript|dart)[\d.]*",
    re.I,
)
# Template placeholders looks_real does not already skip: `%{name}`, a format or interpolation
# field `{name}` or `#{name}`, tox `{env:NAME}`, Concourse `((name))`, Maven `@name@`.
PLACEHOLDER_FORM = re.compile(r"%\{[^{}\s]+\}|#?\{[A-Za-z_][^{}\s]*\}|\(\([\w.:-]+\)\)|@[A-Za-z_][\w.-]*@", re.A)
# An identifier, and the link to the next one in a member path: `.`, `?.`, `!.`, `!!.`, `->`,
# `::`, with `#` for a JavaScript private field. `$` is a name character in JavaScript and PHP.
NAME = re.compile(r"[A-Za-z_$][\w$]*", re.A)
MEMBER_LINK = re.compile(r"(?:\.|\?\.|!!?\.|->|::)#?(?P<name>[A-Za-z_$][\w$]*)", re.A)
# The parts of a name: a word (`Client`, `client`), an acronym, digits, punctuation. A name
# of 12 or more characters with one or two letter parts in a fifth of it or more is
# random, not a word chain: `Hq7Lm2Pz9Rt4Kw8Vb`, base64, but not `oauth2ClientSecretV3`.
NAME_PART = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+|[^A-Za-z\d]+", re.A)
RANDOM_NAME_MIN = 12
BRACKETS = {"(": ")", "[": "]", "{": "}"}
# What may end an expression: a non-null mark, then closers of the call it is an argument of.
EXPRESSION_TAIL = re.compile(r"[!?]{0,2}[)\]};]*")
# (b): a plain identifier, in source text also a type name with generic arguments, an array or
# nullable mark, a union, a reference, and the closers of a call it is an argument of.
# Possessive quantifiers keep the match linear on a long value.
TYPE_NAME = r"[A-Za-z_]\w*+(?:<[\w<>\[\].:?]*+)?[!?]?"
SOURCE_NAME = re.compile(rf"[&*]{{0,2}}{TYPE_NAME}(?:\|{TYPE_NAME})*+[)\]}}>]*+", re.A)
# A single English word: what starts a sentence on the line after `password:`, not a value.
PROSE_WORD = re.compile(r"[A-Z]?[a-z]+(?:-[A-Za-z]?[a-z]+)*[.!?]?|[A-Z]+")
# What may follow a value alone on a later line: a comment.
VALUE_LINE_TAIL = re.compile(r"[ \t]*(?:[ \t]#[^\n]*)?\r?")
# A fenced block in prose, the kind its info string names (fence_kind), and an inline code span.
FENCE = re.compile(r"(?m)^[ \t]{0,3}(?P<mark>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)$")
FENCE_LANG = re.compile(r"[\w+-]+")
CODE_RUN = re.compile(r"`+|\n")
# A diff file header (`--- a/app.ini` then `+++ b/app.py`, or `+++` alone), a run of removed
# lines, and the first line after the header that is not part of a hunk (`diff --git`,
# `commit`, a blank line); a head or tail header (`==> app.py <==`); a grep location
# (`src/app.py:3:`, `src/app.py-3-`, `src/app.py:`).
DIFF_HEADER = re.compile(r"(?m)^(?:--- (?:a/)?(?P<old>\S+)[^\n]*\n)?\+\+\+ (?:b/)?(?P<path>\S+)[^\n]*$")
REMOVED_RUN = re.compile(r"(?m)(?:^-[^\n]*(?:\n|\Z))+")
HUNK_END = re.compile(r"(?m)^(?![ +\-@\\])")
HEAD_HEADER = re.compile(r"(?m)^==> (?P<path>[^\n]+?) <==[ \t]*$")
GREP_LOCATION = re.compile(r"(?m)^(?P<path>[^\s:]+?(?=:\d+[:-])|[^\s:]+?\.\w+(?=:|-\d+-))", re.A)
# What may open a string or a comment in source text (source_inert_spans): a triple quote
# (Python, Kotlin, Scala, Swift, C# raw), a Rust raw string `r#"`, a C# verbatim `@"`, a
# backtick (JavaScript template, Go raw string), a quote, `//`, `/*`, `<!--`, `#`, `--`, `;`,
# a backslash that escapes the next character, and a newline.
SOURCE_EVENT = re.compile(r"\"\"\"|'''|(?<![\w$])b?r#+\"|(?<![\w$])\$?@\$?\"|[`\"'#;\n\\]|//|/\*|<!--|--", re.A)
STRING_PREFIX_CHARS = "rRbBuUfF"
STRING_CLOSE = {
    '"': re.compile(r'\\.|"|\n', re.S),
    "'": re.compile(r"\\.|'|\n", re.S),
    "`": re.compile(r"\\.|`", re.S),
    '"""': re.compile(r'\\.|"""', re.S),
    "'''": re.compile(r"\\.|'''", re.S),
}
VERBATIM_CLOSE = re.compile(r'""|"')
INDENT = re.compile(r"[ \t]*")


class TextKind(StrEnum):
    """Where a scanned text comes from, which decides how a bare credential value is read."""

    SOURCE = "source"  # a code file: (a) and (b)
    CONFIG = "config"  # env, ini, toml, yaml, json, properties, shell, Dockerfile: lookups and placeholders
    FREE = "free"  # prose, a document, a final message, tool output: (a)
    DATA = "data"  # a Bash command, its words and arguments: (a)
    OUTBOUND = "outbound"  # a URL or a request argument that leaves the machine: (a)


# Kinds where a value on a later line than its key may be a first word followed by more
# text, or sit at the start of the line (loose_value).
LOOSE_LINE_KINDS = {TextKind.FREE, TextKind.CONFIG}
# The kind of a fenced block by its label: source for a programming language, config, data
# for a shell, free for prose, a diff and any label not listed (fence_kind).
FENCE_KINDS = {
    **dict.fromkeys(
        ("python", "py", "python3", "py3", "ipython", "pycon", "javascript", "js", "jsx", "mjs", "cjs", "typescript",
         "ts", "tsx", "rust", "rs", "go", "golang", "java", "kotlin", "kt", "kts", "swift", "c", "h", "cpp", "c++",
         "cc", "cxx", "hpp", "objc", "objective-c", "objectivec", "cs", "csharp", "fsharp", "fs", "vb", "vbnet",
         "rb", "ruby", "php", "lua", "scala", "dart", "elixir", "ex", "exs", "erlang", "erl", "haskell", "hs",
         "sql", "perl", "pl", "r", "julia", "jl", "clojure", "clj", "cljs", "groovy", "gradle", "ocaml", "ml",
         "elm", "zig", "nim", "solidity", "sol", "vue", "svelte", "qml"),
        TextKind.SOURCE,
    ),
    **dict.fromkeys(
        ("yaml", "yml", "json", "jsonc", "json5", "ini", "cfg", "conf", "cnf", "properties", "toml", "env", "dotenv",
         "dockerfile", "docker", "makefile", "make", "systemd", "hcl", "tf", "terraform", "tfvars", "nginx",
         "apache", "apacheconf", "ssh-config", "sshconfig", "gitconfig", "xml", "csv", "tsv", "http"),
        TextKind.CONFIG,
    ),
    **dict.fromkeys(
        ("sh", "bash", "zsh", "ksh", "shell", "console", "shell-session", "powershell", "ps1", "bat", "cmd"),
        TextKind.DATA,
    ),
    **dict.fromkeys(
        ("text", "txt", "plain", "plaintext", "markdown", "md", "log", "output", "none", "diff", "patch", "udiff"),
        TextKind.FREE,
    ),
}

Region = tuple[int, int, TextKind]
Layout = Callable[[str], list[Region]]


def path_kind(path: str | os.PathLike[str]) -> TextKind | None:
    """The kind the name of a file gives its content, or None when the name does not say."""
    name = Path(str(path)).name.lower()
    while Path(name).suffix in TEMPLATE_SUFFIXES:
        name = Path(name).stem
    suffix = Path(name).suffix
    if (
        suffix in CONFIG_SUFFIXES
        or name in CONFIG_NAMES
        or name.startswith(CONFIG_NAME_PREFIXES)
        or ".env." in name
    ):
        return TextKind.CONFIG
    return TextKind.SOURCE if suffix in SOURCE_SUFFIXES else None


def shebang_kind(first_line: str) -> TextKind | None:
    """The kind a `#!` line gives a script: source for a language interpreter, config for a
    shell, None otherwise."""
    m = SHEBANG.match(first_line)
    if m is None:
        return None
    prog = m.group("prog")
    if prog in SHELLS:
        return TextKind.CONFIG
    return TextKind.SOURCE if SHEBANG_SOURCE.fullmatch(prog) else None


def text_kind(path: str | os.PathLike[str], text: str = "") -> TextKind:
    """The kind of text, the content of the file at path: by its name, else by its `#!` line,
    else free text."""
    return path_kind(path) or shebang_kind(text.split("\n", 1)[0]) or TextKind.FREE


def closing(value: str, i: int) -> int | None:
    """The offset of the bracket that closes the one at i; None when value ends first (the
    pattern cut it at a space, a quote or a comma) or -1 when a bracket closes out of turn."""
    stack = []
    for k in range(i, len(value)):
        c = value[k]
        if c in BRACKETS:
            stack.append(BRACKETS[c])
        elif c in ")]}":
            if c != stack.pop():
                return -1
            if not stack:
                return k
    return None


def random_name(name: str) -> bool:
    """True when a name looks random rather than a chain of words: 12 or more characters,
    a fifth of them or more in parts of one or two letters (NAME_PART)."""
    if len(name) < RANDOM_NAME_MIN:
        return False
    short = sum(1 for part in NAME_PART.findall(name) if part[0].isalpha() and len(part) <= 2)
    return short * 5 >= len(name)


def code_expression(value: str, names_checked: bool = False) -> bool:
    """(a) on a bare value: a call, a member path or an index. A reference or dereference
    mark may come first (&cfg.token), a non-null mark and the closers of an enclosing call
    last. With names_checked, a name of the path that looks random (random_name) makes it
    a dotted token, not code. Placeholders are tested by credential_literal."""
    v = value.lstrip("&*")
    if len(value) - len(v) > 2:
        return False
    m = NAME.match(v)
    if m is None or (names_checked and random_name(m.group())):
        return False
    i, shaped = m.end(), False
    while i < len(v):
        link = MEMBER_LINK.match(v, i)
        if link:
            if names_checked and random_name(link.group("name")):
                return False
            i, shaped = link.end(), True
            continue
        j = i + (v[i] == "!")  # a macro call: env!(...)
        if j < len(v) and v[j] in "([":
            end = closing(v, j)
            if end is None:
                return True  # the value stops inside the arguments
            if end < 0:
                return False
            i, shaped = end + 1, True
            continue
        break
    return shaped and EXPRESSION_TAIL.fullmatch(v, i) is not None


def code_spans(text: str, start: int, end: int) -> list[Region]:
    """The inline code spans between start and end: a run of backticks to the next run of the
    same length on its line."""
    spans: list[Region] = []
    opened: re.Match[str] | None = None
    for run in CODE_RUN.finditer(text, start, end):
        if run.group() == "\n":
            opened = None
        elif opened is None:
            opened = run
        elif len(run.group()) == len(opened.group()):
            spans.append((opened.end(), run.start(), TextKind.SOURCE))
            opened = None
    return spans


def fence_kind(info: str) -> TextKind:
    """The kind of a fenced block by its info string: source with no label, else the kind
    FENCE_KINDS gives its first word, free text for a label it does not list."""
    if not info:
        return TextKind.SOURCE
    lang = FENCE_LANG.match(info)
    return FENCE_KINDS.get(lang.group().lower(), TextKind.FREE) if lang else TextKind.FREE


def markdown_layout(text: str) -> list[Region]:
    """A final message: a fenced block has the kind of its label (fence_kind), a fence left
    open is free text to the end, an inline code span is source, the rest is free text."""
    fences: list[Region] = []
    opened: tuple[str, int, int, TextKind] | None = None
    for f in FENCE.finditer(text):
        mark, info = f.group("mark"), f.group("info").strip()
        if opened is None:
            opened = (mark[0], len(mark), f.end(), fence_kind(info))
        elif mark[0] == opened[0] and len(mark) >= opened[1] and not info:
            fences.append((opened[2], f.start(), opened[3]))
            opened = None
    if opened is not None:
        fences.append((opened[2], len(text), TextKind.FREE))
    regions: list[Region] = []
    pos = 0
    for fence in fences:
        regions += code_spans(text, pos, fence[0])
        regions.append(fence)
        pos = fence[1]
    return regions + code_spans(text, pos, len(text))


def diff_layout(text: str) -> list[Region]:
    """Diff or patch output: the hunk lines under a `+++` header have the kind of the file it
    names, its removed (`-`) lines the kind of the file the `---` line before it names; any
    other line (the next file's `diff --git`, a commit header in git log -p) ends them."""
    headers = list(DIFF_HEADER.finditer(text))
    regions: list[Region] = []
    for k, h in enumerate(headers):
        limit = headers[k + 1].start() if k + 1 < len(headers) else len(text)
        hunk_end = HUNK_END.search(text, h.end() + 1, limit)
        stop = hunk_end.start() if hunk_end else limit
        new = text_kind(h.group("path"))
        old = text_kind(h.group("old")) if h.group("old") else new
        pos = h.end()
        if old is not new:
            for run in REMOVED_RUN.finditer(text, pos, stop):
                if run.start() > pos:
                    regions.append((pos, run.start(), new))
                regions.append((run.start(), run.end(), old))
                pos = run.end()
        if pos < stop:
            regions.append((pos, stop, new))
    return regions


def head_layout(text: str) -> list[Region]:
    """head or tail output over several files: the lines under `==> f <==` have f's kind."""
    headers = list(HEAD_HEADER.finditer(text))
    return [
        (h.end(), headers[k + 1].start() if k + 1 < len(headers) else len(text), text_kind(h.group("path")))
        for k, h in enumerate(headers)
    ]


def grep_layout(text: str) -> list[Region]:
    """grep output: a line whose location names a file has that file's kind after it."""
    regions: list[Region] = []
    for loc in GREP_LOCATION.finditer(text):
        end = text.find("\n", loc.end())
        regions.append((loc.end(), len(text) if end < 0 else end, text_kind(loc.group("path"))))
    return regions


def opens_string(text: str, line: int, i: int) -> bool:
    """True when the quote at i opens a string: it starts its line or follows a character
    that is not part of a word, or a string prefix (f'', rb""). An apostrophe inside a
    word (don't) opens nothing."""
    j = i - 1
    while j >= line and i - j <= 2 and text[j] in STRING_PREFIX_CHARS:
        j -= 1
    return j < line or not (text[j].isalnum() or text[j] == "_")


def string_end(text: str, opener: str, start: int, end: int) -> tuple[int, int]:
    """(end of the content, end of the closing quote) of the string whose opener ends at
    start: a backslash escapes the next character; a one-quote string left open ends with
    its line, any other with the text."""
    close = STRING_CLOSE[opener]
    k = start
    while (c := close.search(text, k, end)) is not None:
        if c.group()[0] == "\\":
            k = c.end()
        elif c.group() == "\n":
            return c.start(), c.start()
        else:
            return c.start(), c.end()
    return end, end


def inert_end(text: str, e: re.Match[str], line: int, indent_end: int, end: int) -> tuple[int, int] | None:
    """(end of the content, where code resumes) of the string or comment SOURCE_EVENT found
    at e, on the line that starts at line and whose indentation ends at indent_end; None
    when e opens neither. A comment runs to the end of its line, a block comment to its
    closer; one left open, like a multi-line string, runs to the end of the text."""
    tok, i, after = e.group(), e.start(), e.end()
    nxt = text[after : min(after + 1, end)]
    if tok in ('"', "'"):
        return string_end(text, tok, after, end) if opens_string(text, line, i) else None
    if tok in STRING_CLOSE:
        return string_end(text, tok, after, end)
    if tok.endswith('"'):
        if "#" in tok:  # Rust r#"..."#: no escapes, closed by a quote and as many #
            closer = '"' + "#" * tok.count("#")
            k = text.find(closer, after, end)
            return (end, end) if k < 0 else (k, k + len(closer))
        k = after  # C# @"...": no escapes, "" is a quote
        while (c := VERBATIM_CLOSE.search(text, k, end)) is not None:
            if c.group() == '"':
                return c.start(), c.end()
            k = c.end()
        return end, end
    if tok in ("/*", "<!--"):
        closer = "*/" if tok == "/*" else "-->"
        k = text.find(closer, after, end)
        return (end, end) if k < 0 else (k, k + len(closer))
    blank_after = nxt in ("", "\n", "\r", " ", "\t")
    comment = (
        tok == "//"
        or (tok == "#" and (blank_after or nxt in ("#", ":") or (i == line and text.startswith("!/", after, end))))
        or (tok == "--" and (i == line or text[i - 1] in " \t") and (blank_after or text.startswith("[[", after, end)))
        or (tok == ";" and i == indent_end and (blank_after or nxt == ";"))
    )
    if not comment:
        return None
    k = text.find("\n", after, end)
    return (end, end) if k < 0 else (k, k)


def source_inert_spans(text: str, start: int, end: int) -> tuple[list[int], list[int]]:
    """The (starts, ends) of the contents of the strings and comments of the source text
    text[start:end], in one pass: quoted strings, triple-quoted strings (Python, Kotlin,
    Scala, Swift, C# raw), backtick strings (JavaScript and TypeScript templates, Go raw
    strings), Rust raw strings, C# verbatim strings; `//`, `#`, `--` and `;` line comments
    and `/* */` and `<!-- -->` block comments. Only a `#` before a blank, `#`, `:` or a
    shebang path, a `--` between blanks and a `;` that starts its line open a comment, so
    a JavaScript private field, a decrement or a statement end does not."""
    starts: list[int] = []
    ends: list[int] = []
    line = pos = start
    indent_end = INDENT.match(text, line, end).end()
    while (e := SOURCE_EVENT.search(text, pos, end)) is not None:
        tok = e.group()
        if tok == "\n" or (tok == "\\" and text.startswith("\n", e.end(), end)):
            line = pos = text.index("\n", e.start()) + 1
            indent_end = INDENT.match(text, line, end).end()
            continue
        if tok == "\\":
            pos = e.end() + 1
            continue
        span = inert_end(text, e, line, indent_end, end)
        if span is None:
            pos = e.end()
            continue
        starts.append(e.end())
        ends.append(span[0])
        pos = span[1]
        newline = text.rfind("\n", e.end(), pos)
        if newline >= 0:
            line = newline + 1
            indent_end = INDENT.match(text, line, end).end()
    return starts, ends


class Scan:
    """One text being scanned for secrets: its kind, and the regions (fenced blocks, code
    spans, the files a diff, head or grep shows) a layout gives a kind of their own. Lines,
    regions and the strings and comments of source text are read once, when a match first
    needs them."""

    def __init__(self, text: str, kind: TextKind, layout: Layout | None = None) -> None:
        self.text = text
        self.kind = kind
        self.layout = layout
        self._inert: dict[tuple[int, int], tuple[list[int], list[int]]] = {}

    @cached_property
    def newlines(self) -> list[int]:
        return [m.start() for m in re.finditer("\n", self.text)]

    @cached_property
    def regions(self) -> tuple[list[int], list[Region]]:
        regions = self.layout(self.text) if self.layout else []
        return [r[0] for r in regions], regions

    def line_start(self, pos: int) -> int:
        i = bisect.bisect_left(self.newlines, pos)
        return self.newlines[i - 1] + 1 if i else 0

    def line_end(self, pos: int) -> int:
        i = bisect.bisect_left(self.newlines, pos)
        return self.newlines[i] if i < len(self.newlines) else len(self.text)

    def kind_at(self, pos: int) -> TextKind:
        starts, regions = self.regions
        i = bisect.bisect_right(starts, pos) - 1
        return regions[i][2] if i >= 0 and pos < regions[i][1] else self.kind

    def segment(self, pos: int) -> tuple[int, int]:
        """The region holding pos, or the stretch between two regions."""
        starts, regions = self.regions
        i = bisect.bisect_right(starts, pos) - 1
        if i >= 0 and pos < regions[i][1]:
            return regions[i][0], regions[i][1]
        return (regions[i][1] if i >= 0 else 0), (starts[i + 1] if i + 1 < len(starts) else len(self.text))

    def inert(self, pos: int) -> bool:
        """True when pos sits inside a string or a comment of the source text around it."""
        seg = self.segment(pos)
        if seg not in self._inert:
            self._inert[seg] = source_inert_spans(self.text, *seg)
        starts, ends = self._inert[seg]
        i = bisect.bisect_right(starts, pos) - 1
        return i >= 0 and pos < ends[i]

    def kind_of_key(self, pos: int) -> TextKind:
        """The kind of the text at a key; in source text, data inside a string or a comment
        (a connection string, a pasted fixture, a docstring, a note)."""
        kind = self.kind_at(pos)
        return TextKind.DATA if kind is TextKind.SOURCE and self.inert(pos) else kind


def loose_value(m: re.Match[str], scan: Scan) -> bool:
    """True when the value of a credential assignment match sits on a later line than its key
    and that line is not indented, or holds more than the value and a comment: a form only
    free and config text take (LOOSE_LINE_KINDS)."""
    text, start = scan.text, m.start("value")
    if text.find("\n", m.end("sep"), start) < 0:
        return False
    line = scan.line_start(start)
    quoted = start > line and text[start - 1] in "'\"`"
    alone = quoted or VALUE_LINE_TAIL.fullmatch(text, m.end("value"), scan.line_end(start)) is not None
    return not (text[line] in " \t" and alone)


def credential_literal(m: re.Match[str], scan: Scan) -> bool:
    """True when the value of a credential assignment match is a literal: quoted, or bare and
    neither (a) nor (b) for the kind of the text at its key. Never reports the value."""
    text, value, start = scan.text, m.group("value"), m.start("value")
    before = text[start - 1] if start else ""
    kind = scan.kind_of_key(m.start("key"))
    if loose_value(m, scan) and (kind not in LOOSE_LINE_KINDS or PROSE_WORD.fullmatch(value)):
        return False  # the next statement or command in code and in a shell, a sentence in prose
    if before in ("'", '"'):
        return True
    if PLACEHOLDER_FORM.fullmatch(value):
        return False
    if kind is TextKind.CONFIG:
        return True
    if code_expression(value, names_checked=kind is not TextKind.SOURCE):
        return False
    # a backtick opens a template string in code and a code span or substitution elsewhere:
    # only an expression inside it is not a literal
    return before == "`" or kind is not TextKind.SOURCE or SOURCE_NAME.fullmatch(value) is None


def generic_value(name: str, rx: re.Pattern[str], m: re.Match[str], scan: Scan) -> str | None:
    """The value a generic pattern matched, or None when it is not a real-looking literal.
    find_secrets and redact both decide through this one function."""
    value = m.group("value") if "value" in rx.groupindex else m.group(0)
    if not looks_real(value):
        return None
    if name == "credential assignment" and not credential_literal(m, scan):
        return None
    return value


def find_secret_lines(
    text: str, kind: TextKind = TextKind.FREE, layout: Layout | None = None
) -> list[tuple[str, int, int]]:
    """Return [(pattern name, first line, last line)] for secret-looking values in text; kind
    is where the text comes from, layout gives regions of it a kind of their own."""
    hits: list[tuple[str, int, int]] = []
    if not text:
        return hits
    scan = Scan(text, kind, layout)
    for name, rx in SECRET_PATTERNS:
        line, counted = 1, 0
        for m in rx.finditer(text):
            if name in GENERIC and generic_value(name, rx, m, scan) is None:
                continue
            line += text.count("\n", counted, m.start())
            counted = m.start()
            hits.append((name, line, line + text.count("\n", m.start(), m.end())))
    return hits


def find_secrets(text: str, kind: TextKind = TextKind.FREE, layout: Layout | None = None) -> list[tuple[str, int]]:
    """Return [(pattern name, line number)] for secret-looking values in text, as
    find_secret_lines does, with the line each one starts on."""
    return [(name, first) for name, first, _ in find_secret_lines(text, kind, layout)]


def redact(text: str, kind: TextKind = TextKind.FREE, layout: Layout | None = None) -> tuple[str, int]:
    """Replace secret-looking values in text; returns (new_text, count). kind and layout as
    for find_secrets."""
    count = 0

    def sub(name, rx):
        nonlocal text
        scan = Scan(text, kind, layout)

        def repl(m):
            nonlocal count
            if name in GENERIC:
                if generic_value(name, rx, m, scan) is None:
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
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace", timeout=15)
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


def strict_tokens(cmd):
    """Shell words and operators of cmd, or None when its quotes do not balance."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return None


def tokenize(cmd):
    toks = strict_tokens(cmd)
    return cmd.split() if toks is None else toks


# ---- heredocs ----------------------------------------------------------------------
# A heredoc body is text only when the shell reads it as text, so the command is scanned
# the way bash reads it: `<<` counts outside quotes and comments only, and anything the scan
# does not model (backticks, `$[ ]`, `${ }`, `case`, a heredoc inside `( )`, an operator it
# cannot read whole) leaves every body in place. An unquoted body (`<<EOF`) with a `$` or a
# backtick in it is expanded by bash, so it is never text either.
HEREDOC_OP = re.compile(r"""<<(-?)[ \t]*(?:'([^'\n]+)'|"([^"\n]+)"|\\?([A-Za-z_][A-Za-z0-9_.-]*))""")
SHELL_BREAK = " \t\n;&|()<>"
# Commands that show or write their input as it is.
TEXT_SINKS = {"cat", "tee"}
# Subcommands that take a heredoc or an argument as message text and never run it.
GIT_MESSAGE_SUBS = {"commit", "tag", "notes"}
GH_BODY_SUBS = {("pr", "create"), ("pr", "edit"), ("pr", "comment"), ("pr", "review"), ("pr", "merge"),
                ("issue", "create"), ("issue", "edit"), ("issue", "comment"), ("release", "create"),
                ("release", "edit")}
# Options whose `-` value makes git or gh read stdin as the message, and the ones that open an
# editor, which would inherit that stdin.
GIT_STDIN_OPTS = ("-F", "--file")
GH_STDIN_OPTS = ("-F", "--body-file", "--notes-file")
EDITOR_OPTS = {"-e", "--edit", "--editor"}
# git global options that can make git run a configured command (an editor, a hook, a pager).
GIT_CONFIG_OPTS = ("-c", "--config-env", "--exec-path")
# Options whose value is message text, not a file. A short git cluster such as `-am` ends in
# -m after flags that take no value.
GIT_MESSAGE_OPTS = {"-m", "--message"}
GIT_SHORT_MESSAGE = re.compile(r"-[asnvqeziop]*m")
GH_MESSAGE_OPTS = {"-b", "--body", "-t", "--title", "--subject", "-n", "--notes"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Stands for the `$` of the substitution being classified, so its word can be found.
SUBST_MARK = "\x00"


class Frame:
    """A context met while scanning a command: the top level, `$(`, `(` or a double quote."""

    def __init__(self, kind, start):
        self.kind = kind
        self.start = start  # first offset inside the context
        self.end = None  # offset of the closing character
        self.breaks = []  # (start, end) of each statement break: ; ;; && || & newline

    def statement(self, at, length):
        """(start, end) of the statement of this context that holds offset at."""
        start = max((e for s, e in self.breaks if e <= at), default=self.start)
        end = min((s for s, e in self.breaks if s >= at), default=length if self.end is None else self.end)
        return start, end


class Heredoc:
    def __init__(self, frames, op, match):
        self.frames = frames  # contexts holding the operator, from the top level in
        self.op = op  # (start, end) of the operator
        self.strip = bool(match.group(1))
        self.word = match.group(2) or match.group(3) or match.group(4)
        self.unquoted = match.group(4) is not None and "\\" not in match.group(0)
        self.body = (0, 0)  # the body; the terminator line follows it


def _quote_end(cmd, i):
    """Offset after the '...' or $'...' string at i; None when it is not closed."""
    if cmd[i] == "'":
        end = cmd.find("'", i + 1)
        return None if end < 0 else end + 1
    j = i + 2
    while j < len(cmd):
        if cmd[j] == "\\":
            j += 2
        elif cmd[j] == "'":
            return j + 1
        else:
            j += 1
    return None


def _read_bodies(cmd, i, pending, frame, docs):
    """Read the bodies of the pending heredocs after the newline at i.

    Returns the offset of the newline that ends the last terminator, or None when a body
    is not closed the way bash closes it.
    """
    for doc in pending:
        if doc.frames[-1] is not frame:
            return None
        body = k = i + 1
        while True:
            if k > len(cmd):
                return None
            e = cmd.find("\n", k)
            e = len(cmd) if e < 0 else e
            line = cmd[k:e]
            text = line.lstrip("\t") if doc.strip else line
            if text == doc.word:
                break
            # inside $( ), bash also ends the body at a line that only starts with the word
            if len(doc.frames) > 1 and text.startswith(doc.word):
                return None
            # an unquoted body joins a line that ends in a backslash to the next one
            if doc.unquoted and (len(line) - len(line.rstrip("\\"))) % 2:
                return None
            if e == len(cmd):
                return None
            k = e + 1
        doc.body = (body, k)
        docs.append(doc)
        i = e
    pending.clear()
    return i


def scan_heredocs(cmd):
    """(heredocs, cuts) of cmd read as bash reads it; None when it holds what the scan does not model.

    cuts are the comments and heredoc operators: text that is not a shell word.
    """
    n = len(cmd)
    stack = [Frame("top", 0)]
    pending, docs, cuts = [], [], []
    i = 0
    while i < n:
        c, f = cmd[i], stack[-1]
        if c == "\\":
            i += 2
        elif c == "`" or cmd.startswith(("$[", "${"), i):
            return None
        elif f.kind == '"':
            if c == '"':
                f.end = i
                stack.pop()
                i += 1
            elif cmd.startswith("$(", i):
                stack.append(Frame("$(", i + 2))
                i += 2
            else:
                i += 1
        elif c == "'" or cmd.startswith("$'", i):
            i = _quote_end(cmd, i)
            if i is None:
                return None
        elif c == '"':
            stack.append(Frame('"', i + 1))
            i += 1
        elif c == "#" and (i == 0 or cmd[i - 1] in SHELL_BREAK):
            end = cmd.find("\n", i)
            end = n if end < 0 else end
            cuts.append((i, end))
            i = end
        elif cmd.startswith("$(", i):
            stack.append(Frame("$(", i + 2))
            i += 2
        elif c == "(":
            stack.append(Frame("(", i + 1))
            i += 1
        elif c == ")":
            if f.kind == "top":
                return None
            f.end = i
            stack.pop()
            i += 1
        elif cmd.startswith("<<<", i):
            i += 3
        elif cmd.startswith("<<", i):
            m = HEREDOC_OP.match(cmd, i)
            if not m or (m.end() < n and cmd[m.end()] not in SHELL_BREAK):
                return None
            pending.append(Heredoc(tuple(stack), (i, m.end()), m))
            cuts.append((i, m.end()))
            i = m.end()
        elif c == "\n":
            f.breaks.append((i, i + 1))
            i = _read_bodies(cmd, i, pending, f, docs) if pending else i + 1
            if i is None:
                return None
        elif c in ";&|":
            w = 2 if cmd.startswith(("&&", "||", ";;"), i) else 1
            redirect = c == "&" and w == 1 and (cmd[i - 1 : i] in ("<", ">") or cmd[i + 1 : i + 2] == ">")
            if not (c == "|" and w == 1 or redirect):  # a pipe continues the statement
                f.breaks.append((i, i + w))
            i += w
        elif (
            cmd.startswith("case", i)
            and (i == 0 or cmd[i - 1] in SHELL_BREAK)
            and cmd[i + 4 : i + 5] in ("", *SHELL_BREAK)
        ):
            return None  # its `pattern)` closes no `(`
        else:
            i += 1
    if len(stack) != 1 or pending:
        return None
    return docs, cuts


def _words(cmd, frame, at, blanks):
    """Words of the statement of frame that holds offset at, with blanks spaced out; None if unbalanced."""
    start, end = frame.statement(at, len(cmd))
    chars = list(cmd[start:end])
    for s, e in blanks:
        for k in range(max(s, start), min(e, end)):
            chars[k - start] = " "
    return strict_tokens("".join(chars))


def _message_args(toks):
    """Arguments after the subcommand when toks is a git or gh command that takes message text."""
    sub, args = git_parts(toks)
    if sub in GIT_MESSAGE_SUBS:
        return args
    if toks and Path(toks[0]).name == "gh" and len(toks) >= 3 and (toks[1], toks[2]) in GH_BODY_SUBS:
        return toks[3:]
    return None


def _names_stdin(args, opts):
    """True when args give `-` as the value of one of opts: `-F -`, `-F-`, `--file=-`."""
    for k, a in enumerate(args):
        for o in opts:
            attached = o + ("=-" if o.startswith("--") else "-")
            if a == attached or (a == o and args[k + 1 : k + 2] == ["-"]):
                return True
    return False


def _stdin_message(stage, words):
    """True when a git or gh stage reads its stdin as message text and nothing it runs reads it.

    That takes `-F -` (git commit/tag/notes) or `--body-file -` (gh), no editor option, and
    no `-c` or variable assignment that could name an editor or a hook to run instead.
    """
    if any(ASSIGNMENT.match(t) for t in stage[: len(stage) - len(words)]):
        return False
    if any(t in EDITOR_OPTS for t in words):
        return False
    if Path(words[0]).name == "git":
        sub, args = git_parts(words)
        options = words[1 : len(words) - len(args) - 1]
        if sub not in GIT_MESSAGE_SUBS or any(t.startswith(GIT_CONFIG_OPTS) for t in options):
            return False
        return _names_stdin(args, GIT_STDIN_OPTS)
    args = _message_args(words)
    return args is not None and _names_stdin(args, GH_STDIN_OPTS)


def _sink_targets(toks):
    """Files a pipeline of text sinks writes to; None when any stage is something else."""
    if toks is None or any(t in OPERATORS and t not in ("|", "|&") for t in toks):
        return None
    targets, stage = [], []
    for t in [*toks, "|"]:
        if t not in ("|", "|&"):
            stage.append(t)
            continue
        words = strip_wrappers(stage)
        if not words or (Path(words[0]).name not in TEXT_SINKS and not _stdin_message(stage, words)):
            return None
        targets += [words[k + 1] for k in range(len(words) - 1) if words[k] in REDIRECTS]
        if Path(words[0]).name == "tee":
            targets += [
                w for k, w in enumerate(words[1:], 1)
                if not w.startswith("-") and w not in REDIRECTS and words[k - 1] not in REDIRECTS
            ]
        stage = []
    return targets


def _message_option(prefix, prev, git):
    """True when a word that starts with prefix, after the word prev, is a message option's value."""
    if git:
        if prefix.startswith("--message=") or (not prefix.startswith("--") and GIT_SHORT_MESSAGE.match(prefix)):
            return True
        return not prefix.startswith("-") and (prev in GIT_MESSAGE_OPTS or bool(GIT_SHORT_MESSAGE.fullmatch(prev)))
    long_opts = tuple(o + "=" for o in GH_MESSAGE_OPTS if o.startswith("--"))
    short_opts = tuple(o for o in GH_MESSAGE_OPTS if not o.startswith("--"))
    if prefix.startswith(long_opts) or (not prefix.startswith("--") and prefix.startswith(short_opts)):
        return True
    return not prefix.startswith("-") and prev in GH_MESSAGE_OPTS


def _subst_use(cmd, doc, blanks):
    """How a git or gh message command uses the `"$(cat <<EOF ...)"` argument holding doc.

    "message" when it is the value of a message option (`-m`, `--body`), "argument" for any
    other argument after the subcommand (`-F` names a file), None when the command is not a
    git or gh message command or the substitution comes before the subcommand, where it may
    run (`git -c core.editor=...`).
    """
    if SUBST_MARK in cmd:
        return None
    mark = doc.frames[2].start - 2  # the `$` of its `$(`
    toks = _words(cmd[:mark] + SUBST_MARK + cmd[mark + 1 :], doc.frames[0], doc.op[0], blanks)
    if toks is None or any(t in OPERATORS for t in toks):
        return None
    words = strip_wrappers(toks)
    args = _message_args(words)

    def subst(t):
        return "$(" in t or SUBST_MARK in t

    if args is None or sum(map(subst, toks)) != sum(map(subst, args)):
        return None
    at = next((k for k, t in enumerate(args) if SUBST_MARK in t), None)
    if at is None:
        return None
    prefix = args[at].split(SUBST_MARK, 1)[0]
    prev = args[at - 1] if at else ""
    return "message" if _message_option(prefix, prev, Path(words[0]).name == "git") else "argument"


def _substitutions(text):
    """The command text of each `$( )` and backtick substitution in text, outer and inner."""
    found = [m.group(1) for m in re.finditer(r"`([^`]*)`", text)]
    start = text.find("$(")
    while start >= 0:
        depth, k = 1, start + 2
        while k < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[k], 0)
            k += 1
        found.append(text[start + 2 : k - 1 if depth == 0 else k])
        start = text.find("$(", start + 2)
    return found


def split_heredocs(cmd):
    """Return (cmd without its text heredoc bodies, [(files written, body)], [argument values],
    [substitutions]).

    A body is text when the whole pipeline it feeds shows, writes or takes it as a message:
    cat and tee, or git commit/tag/notes and the gh subcommands that take a body, reading it
    through `-F -` or `--body-file -`. Those bodies are removed, operator and terminator lines
    kept, so a redirect target is still checked. A body inside `"$(cat <<EOF ...)"` is one
    argument: removed when a git or gh message command takes it, and returned to be checked as
    a filename unless it is a message option's value. An unquoted body with a `$` or backtick
    is expanded by bash, so it always stays, and the commands of its substitutions are
    returned to be checked. Every other body stays: it may run.
    """
    scan = scan_heredocs(cmd)
    if scan is None:
        return cmd, [], [], []
    docs, cuts = scan
    if any(f.kind == "(" for d in docs for f in d.frames):
        return cmd, [], [], []
    blanks = cuts + [d.body for d in docs]
    removed, bodies, values, scripts = [], [], [], []
    for d in docs:
        body = cmd[d.body[0] : d.body[1]]
        expands = d.unquoted and ("$" in body or "`" in body)
        if expands:
            scripts += _substitutions(body)
        kinds = [f.kind for f in d.frames]
        if kinds == ["top"]:
            targets = _sink_targets(_words(cmd, d.frames[0], d.op[0], blanks))
            if targets is None:
                continue
            bodies.append((targets, body))
        elif kinds == ["top", '"', "$("] and _words(cmd, d.frames[2], d.op[0], blanks) == ["cat"]:
            use = _subst_use(cmd, d, blanks)
            if use != "message":
                values.append(body.rstrip("\n"))
            if use is None:
                continue
        else:
            continue
        if not expands:
            removed.append(d.body)
    out, pos = [], 0
    for s, e in sorted(removed):
        out.append(cmd[pos:s])
        pos = e
    out.append(cmd[pos:])
    return "".join(out), bodies, values, scripts


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
        if ASSIGNMENT.match(t):
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


def check_outbound(data, op, toks):
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
        if sends:
            phits = find_pii(" ".join(toks[1:]))
            if phits:
                report_pii(data, pii_detail(f"the `{head}` request", phits))
        # each argument leaves the machine as the shell wrote it
        literal_credential = any(find_secrets(t, TextKind.OUTBOUND) for t in toks[1:])
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
    in_sub = is_subagent(data)
    flags = [a for a in args if a.startswith("-")]
    positional = [a for a in args if not a.startswith("-")]

    if sub in ("commit", "push", "tag") and in_sub:
        deny(
            "subagent-no-git",
            f"`git {sub}` from a subagent ({data.get('agent_type') or 'unknown role'}). Only the main session commits, after the user approves.",
        )
    if sub in ("commit", "push", "tag") and not in_sub:
        PENDING_ASK.append(f"git {sub}")
    if sub in ("commit", "tag"):
        msg = " ".join(args)
        hits = find_pii(msg, cwd)
        if hits:
            report_pii(data, pii_detail(f"the `git {sub}` message", hits))
    if sub == "config" and any(f in ("--global", "--system") for f in flags):
        deny(
            "destructive-command",
            "`git config --global/--system` changes the user's identity or tooling for every repository. Use repo-local config.",
        )
    if sub == "commit":
        if "--amend" in flags and head_is_pushed(cwd):
            deny("protect-history", "`git commit --amend` would rewrite a commit that is already on the remote.")
        scan_staged(
            data,
            cwd,
            include_unstaged=any(f in ("-a", "--all") for f in flags)
            or any(re.match(r"^-[a-zA-Z]*a", f) for f in flags),
        )
    elif sub == "add":
        scan_add(data, cwd, args)
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


HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def staged_pii_kinds(cwd, path, lines):
    """pii kinds on the added lines of one staged file; lines are (line number, text).

    A manifest is scanned whole from the index, so its contact fields are known, and only
    hits on added lines count. Any other file, or a manifest git cannot show, is scanned
    line by line.
    """
    if pii_exempt(path):
        return []
    if Path(path).name in CONTACT_MANIFESTS:
        rc, blob = git(["cat-file", "blob", f":{path}"], cwd)
        if rc == 0:
            numbers = {n for n, _ in lines}
            return [kind for kind, n in find_file_pii(path, blob, cwd) if n in numbers]
    return [kind for _, text in lines for kind, _ in find_pii(text, cwd)]


def git_batch(args: list[str], request: list[str], cwd: str) -> bytes | None:
    """stdout of a git command fed one request per line on stdin; None when it fails."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, input="".join(f"{q}\n" for q in request).encode(), capture_output=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def staged_blobs(cwd: str, paths: list[str]) -> dict[str, str]:
    """The staged content of each of paths, read with one `git cat-file --batch-check` for
    the sizes and one `git cat-file --batch` for the blobs of MAX_SCAN_BYTES or less; a
    path git cannot show, or a larger blob, is left out."""
    names = [p for p in paths if "\n" not in p]
    check = "--batch-check=%(objectname) %(objecttype) %(objectsize)"
    sizes = git_batch(["cat-file", check], [f":{p}" for p in names], cwd)
    lines = sizes.decode(errors="replace").splitlines() if sizes else []
    if len(lines) != len(names):
        return {}  # one answer per request, or the answers cannot be matched to the paths
    oids: dict[str, list[str]] = {}
    for path, line in zip(names, lines, strict=True):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob" and parts[2].isdigit() and int(parts[2]) <= MAX_SCAN_BYTES:
            oids.setdefault(parts[0], []).append(path)
    out = git_batch(["cat-file", "--batch"], list(oids), cwd) if oids else None
    blobs: dict[str, str] = {}
    pos = 0
    while out is not None and pos < len(out):
        newline = out.find(b"\n", pos)
        header = out[pos:newline].split() if newline >= 0 else []
        if len(header) != 3 or not header[2].isdigit():
            break
        size = int(header[2])
        content = out[newline + 1 : newline + 1 + size].decode(errors="replace")
        for path in oids.get(header[0].decode(errors="replace"), []):
            blobs[path] = content
        pos = newline + 1 + size + 1  # the content ends with a newline of its own
    return blobs


def staged_secrets(cwd: str, added: dict[str, list[tuple[int, str]]]) -> list[str]:
    """`path (pattern name)` for each secret-looking value on the added lines of the staged
    files. Only a credential assignment depends on the kind of a file, so a file whose added
    lines hold no credential key word is scanned line by line as free text, and the others
    whole from the index, with the kind their name or `#!` line gives, so that a string, a
    comment or a value on the next line is read in its place; a hit counts when it touches
    an added line. A file the index cannot give is scanned line by line with that kind."""
    keyed = {path for path, lines in added.items() if any(CREDENTIAL_KEY.search(text) for _, text in lines)}
    blobs = staged_blobs(cwd, sorted(keyed)) if keyed else {}
    report = []
    for path, lines in added.items():
        if path not in keyed:
            report += [f"{path} ({name})" for _, text in lines for name, _ in find_secrets(text)]
            continue
        blob = blobs.get(path)
        first = next((text for n, text in lines if n == 1), None)
        if first is None:
            first = blob.split("\n", 1)[0] if blob is not None else ""
        kind = path_kind(path) or shebang_kind(first) or TextKind.FREE
        if blob is None:
            report += [f"{path} ({name})" for _, text in lines for name, _ in find_secrets(text, kind)]
            continue
        numbers = sorted(n for n, _ in lines)
        for name, first_line, last_line in find_secret_lines(blob, kind):
            k = bisect.bisect_left(numbers, first_line)
            if k < len(numbers) and numbers[k] <= last_line:
                report.append(f"{path} ({name})")
    return report


# Diff output in one shape whatever the user's config: no color or external driver, a/ and
# b/ prefixes, raw paths. Run from the top of the work tree, diff.relative hides nothing.
DIFF_FIXED = ["--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/"]


def scan_staged(data, cwd, include_unstaged=False):
    rc, top = git(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0:
        return
    cwd = top.rstrip("\n")
    quote = ["-c", "core.quotePath=false"]
    rc, names = git([*quote, "diff", "--cached", "--name-only", *DIFF_FIXED], cwd)
    if rc != 0:
        return
    listed = names.split()
    if include_unstaged:
        listed += git([*quote, "diff", "--name-only", *DIFF_FIXED], cwd)[1].split()
    for n in listed:
        if is_secret_file(n):
            deny("commit-secret", f"`{n}` is a secret file; unstage it (`git reset -- {n}`) and add it to .gitignore.")
    rc, diff = git([*quote, "diff", "--cached", "-U0", *DIFF_FIXED] + (["HEAD"] if include_unstaged else []), cwd)
    if rc != 0:
        return
    current = ""
    lineno = 0
    in_header = False  # between `diff --git` and the first hunk, `+++ ` names the file
    added = {}  # path -> [(line number in the staged file, text)]
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header = True
        elif in_header and line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@ "):
            in_header = False
            m = HUNK_HEADER.match(line)
            lineno = int(m.group(1)) if m else 0
        elif not in_header and line.startswith("+"):
            added.setdefault(current, []).append((lineno, line[1:]))
            lineno += 1
    report = staged_secrets(cwd, added)
    pii_report = []
    for path, lines in added.items():
        pii_report.extend(f"{path} ({kind})" for kind in staged_pii_kinds(cwd, path, lines))
    if report:
        deny(
            "commit-secret",
            f"the staged changes contain secret-looking values: {', '.join(sorted(set(report))[:5])}. Move them to an ignored file or an environment variable.",
        )
    if pii_report:
        report_pii(data, f"the staged changes contain personal or identifiable information: {listing(pii_report)}.")


def scan_add(data, cwd, args):
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
    texts = []
    for c in candidates:
        full = Path(cwd) / c
        try:
            if full.is_file() and full.stat().st_size <= MAX_SCAN_BYTES:
                texts.append((c, full.read_text(errors="ignore")))
        except OSError:
            continue
    for c, text in texts:
        hits = find_secrets(text, text_kind(c, text))
        if hits:
            deny(
                "commit-secret",
                f"`{c}` contains a secret-looking value ({hits[0][0]}, line {hits[0][1]}); do not stage it.",
            )
    pii_report = [f"{c} ({kind})" for c, text in texts for kind, _ in find_file_pii(c, text, cwd)]
    if pii_report:
        report_pii(data, f"the files to stage contain personal or identifiable information: {listing(pii_report)}.")


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


GH_PUBLISHING = {("pr", "create"), ("pr", "merge"), ("pr", "comment"), ("pr", "review"), ("pr", "edit"),
                 ("issue", "create"), ("issue", "comment"), ("issue", "edit"), ("release", "create"),
                 ("release", "edit"), ("gist", "create"), ("repo", "create")}


def check_gh(data, toks):
    if not toks or Path(toks[0]).name != "gh" or len(toks) < 3:
        return
    pair = (toks[1], toks[2])
    if pair not in GH_PUBLISHING and toks[1] != "api":
        return
    if is_subagent(data):
        deny("subagent-no-git", f"`gh {' '.join(pair)}` from a subagent publishes on the user's behalf; only the main session does, after approval.")
    hits = find_pii(" ".join(toks[3:]), data.get("cwd"))
    if hits:
        report_pii(data, pii_detail(f"the `gh {' '.join(pair)}` text", hits))
    if pair in GH_PUBLISHING:
        PENDING_ASK.append(f"gh {' '.join(pair)}")


ECHOES = {"echo", "printf"}


def echoed_to_config(segs: list[tuple[str, list[str]]]) -> list[str]:
    """The text of each echo or printf whose output a redirect or a following tee writes to
    a config file: the arguments joined as the command prints them."""
    out = []
    for i, (_, toks) in enumerate(segs):
        words = strip_wrappers(toks)
        if not words or Path(words[0]).name not in ECHOES:
            continue
        targets = [words[k + 1] for k in range(len(words) - 1) if words[k] in REDIRECTS]
        if i + 1 < len(segs) and segs[i + 1][0] in ("|", "|&"):
            sink = strip_wrappers(segs[i + 1][1])
            if sink and Path(sink[0]).name == "tee":
                targets += [w for w in sink[1:] if not w.startswith("-") and w not in REDIRECTS]
        if TextKind.CONFIG not in {text_kind(t) for t in targets}:
            continue
        args = [w for k, w in enumerate(words[1:], 1) if w not in REDIRECTS and words[k - 1] not in REDIRECTS]
        while args and args[0].startswith("-"):
            args.pop(0)  # echo -e, -n
        text = " ".join(args).replace("\\n", "\n")
        out.append(text)
    return out


DECLARERS = {"export", "readonly", "declare", "typeset", "local"}


def shell_assignments(cmd: str) -> list[str]:
    """The `NAME=value` words the shell assigns in cmd: the leading assignments of each
    simple command, also after a wrapper such as env, and the arguments of export,
    readonly, declare, typeset and local. The shell reads their values as strings."""
    out: list[str] = []
    start, declaring = True, False
    for tok in tokenize(cmd):
        if tok in OPERATORS:
            start, declaring = True, False
        elif ASSIGNMENT.match(tok) and (start or declaring):
            out.append(tok)
        elif declaring and tok.startswith("-"):
            continue  # declare -x
        elif start and (Path(tok).name in WRAPPERS or tok.startswith("-")):
            continue  # env, sudo -E
        else:
            declaring = start and Path(tok).name in DECLARERS
            start = False
    return out


def check_bash(data):
    cmd = data["tool_input"].get("command") or ""
    if not cmd.strip():
        return
    # Every word reaches a program as written (NAME=value, --flag=value, -e NAME=value, echo
    # arguments) and message text (git -m, -F - heredocs, gh --body and --title) leaves the
    # machine, so the whole command is data: a bare value is a literal unless it is an
    # expression, whatever fence or backticks surround it.
    hits = find_secrets(cmd, TextKind.DATA)
    if hits:
        deny(
            "write-secret",
            f"the command contains a secret-looking value ({hits[0][0]}). Reference the secret through an environment variable the user set instead.",
        )
    # A heredoc body read as text is prose, not filenames; it is still scanned whole for
    # secrets (above) and, when it goes to a file, for pii like the Write tool's content.
    # Commit and PR text from a heredoc is scanned by the git and gh checks below.
    without_bodies, bodies, values, scripts = split_heredocs(cmd)
    for text in (without_bodies, *scripts):
        for _, toks in segments(text):
            check_secret_tokens(toks)
        # the shell reads an assigned value as a string, as a config file does
        if any(find_secrets(word, TextKind.CONFIG) for word in shell_assignments(text)):
            deny(
                "write-secret",
                "the command assigns a secret-looking value to a shell variable. Reference the secret through an environment variable the user set instead.",
            )
    check_secret_tokens(values)
    for targets, body in bodies:
        if TextKind.CONFIG in {text_kind(t, body) for t in targets}:
            for name, line in find_secrets(body, TextKind.CONFIG):
                deny(
                    "write-secret",
                    f"the heredoc text contains a secret-looking value ({name}, line {line}). Keep secrets in an ignored file or an environment variable and reference them by name.",
                )
    for text in echoed_to_config(segments(cmd)):
        for name, _ in find_secrets(text, TextKind.CONFIG):
            deny(
                "write-secret",
                f"the command writes a secret-looking value ({name}) to a config file. Keep secrets in an ignored file or an environment variable and reference them by name.",
            )
    for targets, body in bodies:
        for target in targets:
            phits = find_file_pii(target, body, data.get("cwd"))
            if phits:
                report_pii(data, pii_detail(f"the heredoc text for `{Path(target).name}`", phits))
    for op, toks in segments(cmd):
        check_outbound(data, op, toks)
        check_git(data, toks)
        check_gh(data, toks)
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


def new_text(inp: dict) -> str:
    """The text a file tool writes: Write content, Edit new_string, MultiEdit edits and
    NotebookEdit new_source."""
    parts = [inp.get(k) for k in ("content", "new_string", "new_source")]
    edits = inp.get("edits")
    if isinstance(edits, list):
        parts += [e.get("new_string") for e in edits if isinstance(e, dict)]
    return "\n".join(p for p in parts if isinstance(p, str))


def check_write(data):
    inp = data["tool_input"]
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    content = new_text(inp)
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
    # a markdown cell of a notebook is prose, whatever the notebook's language
    kind = TextKind.FREE if inp.get("cell_type") == "markdown" else text_kind(path, content)
    hits = find_secrets(content, kind)
    if hits:
        name, line = hits[0]
        deny(
            "write-secret",
            f"the content contains a secret-looking value ({name}, line {line} of the new text). Keep secrets in an ignored file or an environment variable and reference them by name.",
        )
    phits = find_file_pii(path, content, data.get("cwd"))
    if phits:
        report_pii(data, pii_detail(f"the new text for `{Path(path).name}`", phits))


def check_webfetch(data):
    url = data["tool_input"].get("url") or ""
    if find_secrets(url, TextKind.OUTBOUND):
        deny("send-data-out", "the URL carries a credential-looking value.")
    hits = find_pii(url, data.get("cwd"))
    if hits:
        report_pii(data, pii_detail("the WebFetch URL", hits))


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
    # Every check has run and none denied: emit the asks, as one object.
    reasons = []
    if PENDING_PII:
        findings = " ".join(dict.fromkeys(PENDING_PII))
        reasons.append(
            f"Conclave rule [pii]: {findings} Confirm only if this is intended; otherwise use "
            f"{PII_PLACEHOLDER}, or add a public contact to CONCLAVE_PII_ALLOW."
        )
    if PENDING_ASK and "commit-approval" not in ALLOW and "all" not in ALLOW:
        actions = ", ".join(dict.fromkeys(PENDING_ASK))
        reasons.append(f"Conclave rule [commit-approval]: {actions} needs your explicit approval.")
    if reasons:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": " ".join(reasons),
            }
        }))


def redact_any(obj, kind: TextKind = TextKind.FREE, layout: Layout | None = None):
    total = 0
    if isinstance(obj, str):
        new, n = redact(obj, kind, layout)
        return new, n
    if isinstance(obj, list):
        out = []
        for item in obj:
            new, n = redact_any(item, kind, layout)
            out.append(new)
            total += n
        return out, total
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            new, n = redact_any(v, kind, layout)
            out[k] = new
            total += n
        return out, total
    return obj, 0


def named_files(words: list[str]) -> list[str]:
    """The file names a command line may show: each word, the path after a `REV:` or an
    `--opt=`, so `git show HEAD:app.ini` and `--file=app.ini` count."""
    names = []
    for w in words:
        if w.startswith("-") and "=" not in w:
            continue
        names += [w, w.rsplit(":", 1)[-1], w.split("=", 1)[-1]]
    return names


def config_or_free(files: list[str]) -> TextKind:
    """Config when one of files is a config file, else free text."""
    return TextKind.CONFIG if any(text_kind(f) is TextKind.CONFIG for f in files) else TextKind.FREE


# Commands whose output is environment variables or stored configuration: the head alone,
# or the head with one of these subcommands.
ENV_DUMP_HEADS = {"set", "export", "declare", "typeset"}
ENV_DUMP_FLAGS = {"-p", "-x", "-px", "-xp"}
ENV_DUMP_SUBCOMMANDS = {
    "heroku": {"config"},
    "docker": {"inspect"},
    "podman": {"inspect"},
    "kubectl": {"describe", "get"},
    "vault": {"kv", "read"},
    "doppler": {"secrets"},
    "systemctl": {"show", "show-environment"},
}
COMPOSE_TOOLS = {"docker", "podman"}
# Commands whose output provably comes from the files they name: cat, head, tail, nl and
# sed -n print them; grep prints a location before each line; diff and git print a `+++`
# header before each file. The options of head, tail and sed that take a value.
SHOW_TOOLS = {"cat", "head", "tail", "sed", "nl"}
VALUE_OPTIONS = {
    "head": {"-n", "-c", "--lines", "--bytes"},
    "tail": {"-n", "-c", "--lines", "--bytes"},
    "sed": {"-e", "-f", "-l", "--expression", "--file", "--line-length"},
}
SED_SCRIPT_OPTIONS = ("-e", "-f", "--expression", "--file")
SED_QUIET = re.compile(r"-[A-Za-z]*n[A-Za-z]*|--quiet|--silent")
GREP_TOOLS = {"grep", "egrep", "fgrep", "rg", "ag", "ack"}
GIT_PATCH_SUBS = {"diff", "show", "log", "format-patch", "stash"}
# What may follow grep or diff in a pipeline and still print its lines as they were.
OUTPUT_FILTERS = {"head", "tail", "sort", "uniq", "grep", "egrep", "fgrep", "rg", "cat", "less", "more"}
PATCH_SUFFIXES = {".diff", ".patch"}


def simple_commands(words: list[str]) -> list[list[str]]:
    """words split at the shell operators."""
    commands: list[list[str]] = [[]]
    for w in words:
        if w in OPERATORS:
            commands.append([])
        else:
            commands[-1].append(w)
    return [c for c in commands if c]


def unwrapped(words: list[str], wrappers: set[str]) -> list[str]:
    """words after the leading assignments, options and wrappers (sudo, nice -n): the
    command and its arguments. Unlike strip_wrappers it never denies."""
    i = 0
    while i < len(words) and (ASSIGNMENT.match(words[i]) or words[i].startswith("-") or Path(words[i]).name in wrappers):
        i += 1
    return words[i:]


def shows_environment(words: list[str]) -> bool:
    """True when a simple command prints environment variables or stored configuration: env
    or printenv run on its own (also as the last word, after ssh, docker exec or kubectl
    exec), set, export, declare, heroku config, docker inspect, docker compose config,
    kubectl describe or get, vault kv or read, doppler secrets, systemctl show."""
    rest = unwrapped(words, WRAPPERS - {"env"})
    if not rest:
        return False
    head = Path(rest[0]).name
    if head in ENV_DUMP_HEADS:
        return all(w in ENV_DUMP_FLAGS for w in rest[1:])  # set, export -p; not set -e
    if "printenv" in rest or Path(rest[-1]).name == "env":
        return True
    sub = next((w for w in rest[1:] if not w.startswith("-")), "")
    if head == "docker-compose" or (head in COMPOSE_TOOLS and sub == "compose"):
        return "config" in rest
    return sub.split(":", 1)[0] in ENV_DUMP_SUBCOMMANDS.get(head, set())


def shown_files(head: str, args: list[str]) -> list[str]:
    """The files cat, head, tail, nl or sed -n print, or [] when the command may print
    something else (sed without -n). A sed script given as the first argument is not one."""
    if head == "sed" and not any(SED_QUIET.fullmatch(a) for a in args):
        return []
    script = head == "sed" and not any(a.startswith(SED_SCRIPT_OPTIONS) for a in args)
    files: list[str] = []
    value = False
    for a in args:
        if value:
            value = False
        elif a.startswith("-") and a != "-":
            value = a in VALUE_OPTIONS.get(head, set())
        elif script:
            script = False
        else:
            files.append(a)
    return files


def output_reading(data: dict) -> tuple[TextKind, Layout | None]:
    """How to read a tool result, from where it comes from: (kind, layout).

    A Read has the kind of its file, a patch file the kinds its `+++` headers name. Grep
    output, and that of a Bash grep, has the kind of the file each location names. diff
    and git diff/show/log output has the kind of the file each `+++` header names. cat,
    head, tail, nl or sed -n of source files alone is source, head or tail of several files
    has the kind each `==> f <==` header names. A command that prints the environment or
    stored configuration (shows_environment), or that names a config file, is config.
    Everything else is free text."""
    inp = data.get("tool_input") or {}
    tool = data.get("tool_name")
    if tool == "Read":
        path = inp.get("file_path") or ""
        if Path(path).suffix.lower() in PATCH_SUFFIXES:
            return TextKind.FREE, diff_layout
        return (text_kind(path) if path else TextKind.FREE), None
    if tool == "Grep":
        return config_or_free([f for f in (inp.get("path"), inp.get("glob")) if isinstance(f, str) and f]), grep_layout
    if tool != "Bash":
        return TextKind.FREE, None
    # read with tokenize, not segments or strip_wrappers: those deny, a PreToolUse step
    words = tokenize(inp.get("command") or "")
    commands = simple_commands(words)
    if any(shows_environment(c) for c in commands):
        return TextKind.CONFIG, None
    kind = config_or_free(named_files(words))
    commands = [c for c in (unwrapped(c, WRAPPERS) for c in commands) if c]
    if not commands:
        return kind, None
    first, rest = commands[0], commands[1:]
    head, sub = Path(first[0]).name, git_parts(first)[0]
    filtered = all(Path(c[0]).name in OUTPUT_FILTERS for c in rest)
    if (head in GREP_TOOLS or sub == "grep") and filtered:
        return kind, grep_layout
    if (head == "diff" or sub in GIT_PATCH_SUBS) and filtered:
        return kind, diff_layout
    files = shown_files(head, first[1:]) if head in SHOW_TOOLS and not rest else []
    if head in ("head", "tail") and len(files) > 1:
        return kind, head_layout
    if files and all(text_kind(f) is TextKind.SOURCE for f in files):
        return TextKind.SOURCE, None
    return kind, None


def mode_post(data):
    resp = data.get("tool_response")
    if resp is None:
        return
    new, n = redact_any(resp, *output_reading(data))
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
    # prose, with its fenced blocks and code spans read as code
    hits = find_secrets(text, TextKind.FREE, markdown_layout)
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
