#!/usr/bin/env python3
"""Offline tests for plugins/conclave/bin/docs-link-check.py.

    python3 -I tests/test_docs_links.py

Each case builds a throwaway git repository in a temporary directory, writes its
Markdown there and runs the script as a subprocess, so no broken link lives in this
repository. Git reads no global or system configuration. Exit 1 when a case fails.

The --web cases use no outside network: they request an HTTP server on the loopback
address inside this process. The script refuses loopback addresses, so those cases
load it as a module and replace its is_public (and, for host names, its lookup);
the script as shipped is run to prove the same addresses are never requested.
"""

import contextlib
import hashlib
import importlib.util
import io
import ipaddress
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "conclave"
SCRIPT = PLUGIN / "bin" / "docs-link-check.py"
FAILS = []
SKIPS = []
PASSES = 0
TIMEOUT = 30


def environment(ceiling):
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(ceiling),
    }


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, env=environment(root.parent), check=True, capture_output=True)


def make_repo(tmp, files, ignore=None):
    """A git repository at tmp/repo holding files (text or bytes), nothing committed."""
    root = tmp / "repo"
    root.mkdir()
    git(root, "init", "-q")
    if ignore is not None:
        (root / ".gitignore").write_text(ignore, encoding="utf-8")
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def run(root, *args, cwd=None, ceiling=None, direct=False, extra=None, timeout=TIMEOUT):
    command = [str(SCRIPT)] if direct else [sys.executable, "-I", str(SCRIPT)]
    try:
        done = subprocess.run(
            [*command, *args],
            cwd=cwd or root,
            env={**environment(ceiling or root.parent), **(extra or {})},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    return done.returncode, done.stdout, done.stderr


def record(label, ok, detail):
    global PASSES
    if ok:
        PASSES += 1
    else:
        FAILS.append(f"{label}: {detail}")


def skip(label, reason):
    SKIPS.append(f"{label}: {reason}")


def running_as_root():
    """chmod 0 does not stop root from reading a file, so an unreadable file cannot be made."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def expect(label, result, code, lines=()):
    """Exit code and stdout lines exactly; no traceback on stderr."""
    rc, out, err = result
    got = out.splitlines()
    ok = rc == code and got == list(lines) and "Traceback" not in err
    record(label, ok, f"expected exit {code} and {list(lines)!r}, got exit {rc} and {got!r}; stderr={err.strip()[-300:]!r}")


def misuse(label, result):
    rc, out, err = result
    ok = rc == 2 and out == "" and "docs-link-check.py <file>..." in err and "Traceback" not in err
    record(label, ok, f"expected usage and exit 2, got exit {rc}; stdout={out!r} stderr={err.strip()[-300:]!r}")


# ---- cases


def test_missing_file(tmp):
    root = make_repo(tmp, {"a.md": "# A\n\nSee [gone](gone.md).\n"})
    expect("missing file", run(root, "a.md"), 1, ["a.md:3: missing file: gone.md"])


def test_missing_anchor_other_file(tmp):
    root = make_repo(tmp, {"a.md": "[a](other.md#nope)\n[b](other.md#here)\n", "other.md": "# Here\n"})
    expect("missing anchor in another file", run(root, "a.md"), 1, ["a.md:1: missing anchor: other.md#nope"])


def test_missing_anchor_same_file(tmp):
    root = make_repo(tmp, {"a.md": "# Top part\n\n[a](#nope)\n[b](#top-part)\n"})
    expect("missing anchor in the same file", run(root, "a.md"), 1, ["a.md:3: missing anchor: #nope"])


def test_clean(tmp):
    root = make_repo(
        tmp,
        {
            "a.md": "# A\n\n[b](b.md) [s](docs/) [c](docs/c.md#c-title) [self](#a) [root](/)\n",
            "b.md": "b\n",
            "docs/c.md": "# C title\n\n[back](../a.md)\n",
        },
    )
    rc, out, err = run(root, "a.md", "b.md", "docs/c.md")
    expect("clean tree", (rc, out, err), 0, [])
    record("clean tree: count on stderr", "0 broken links" in err, f"stderr={err!r}")


def test_count_on_stderr(tmp):
    root = make_repo(tmp, {"a.md": "[x](x.md) [y](y.md)\n"})
    rc, out, err = run(root, "a.md")
    record("count of broken links on stderr", rc == 1 and len(out.splitlines()) == 2 and "2 broken links" in err, f"rc={rc} err={err!r}")


def test_ignored_target(tmp):
    root = make_repo(
        tmp,
        {"a.md": "[plan](plans/p.md)\n[dir](plans/)\n", "plans/p.md": "# P\n"},
        ignore="plans/\n",
    )
    expect(
        "ignored target",
        run(root, "a.md"),
        1,
        ["a.md:1: ignored by git: plans/p.md", "a.md:2: ignored by git: plans/"],
    )


def test_outside_never_opened(tmp):
    # A FIFO outside the repository: opening it for reading blocks until the timeout.
    os.mkfifo(tmp / "pipe.md")
    root = make_repo(
        tmp,
        {"a.md": "[a](../pipe.md#x)\n[b](sub/../../pipe.md)\n[c](/../pipe.md#y)\n"},
    )
    expect(
        "outside the repository, never opened",
        run(root, "a.md"),
        1,
        [
            "a.md:1: outside the repository: ../pipe.md#x",
            "a.md:2: outside the repository: sub/../../pipe.md",
            "a.md:3: outside the repository: /../pipe.md#y",
        ],
    )


def test_symlink_leaving_repository(tmp):
    (tmp / "elsewhere.md").write_text("# Elsewhere\n", encoding="utf-8")
    root = make_repo(tmp, {"a.md": "[a](link.md#nope)\n"})
    (root / "link.md").symlink_to(tmp / "elsewhere.md")
    expect(
        "a Markdown target whose link leaves the repository is not read for anchors",
        run(root, "a.md"),
        1,
        ["a.md:1: outside the repository: link.md#nope"],
    )


def test_code_fence_and_span(tmp):
    text = (
        "```sh\n[a](gone1.md)\n```\n"
        "~~~~\n[b](gone2.md)\n```\n[c](gone3.md)\n~~~~\n"
        "- item\n\n  ```\n  [d](gone4.md)\n  ```\n"
        "> ```\n> [e](gone5.md)\n> ```\n"
        "Inline `[f](gone6.md)` and ``a ` [g](gone7.md)`` here.\n"
        "Span across `lines [h](gone8.md)\nstill code` end.\n"
        "- ```\n  [i](gone10.md)\n  ```\n"
        "[after](gone9.md)\n"
    )
    root = make_repo(tmp, {"a.md": text})
    expect("code fences and code spans", run(root, "a.md"), 1, ["a.md:23: missing file: gone9.md"])


def test_unclosed_backticks_are_text(tmp):
    root = make_repo(tmp, {"a.md": "A lone ` backtick then [x](gone.md).\n"})
    expect("an unclosed backtick does not hide a link", run(root, "a.md"), 1, ["a.md:1: missing file: gone.md"])


def test_schemes_not_checked(tmp):
    text = (
        "[w](https://example.invalid/x.md) [m](mailto:someone@example.invalid) "
        "[p](//host.invalid/x) [f](ftp://h.invalid/y) [r](<https://example.invalid/a b>)\n"
        "[ref]: https://example.invalid/ref\n"
    )
    root = make_repo(tmp, {"a.md": text})
    expect("schemes and // are not checked", run(root, "a.md"), 0, [])


def test_image_and_reference_definition(tmp):
    text = (
        "![alt](img/gone.png)\n"
        "![ok](img/here.png)\n"
        "[![badge](img/badge.png)](gone-target.md)\n"
        "[r]: gone-ref.md\n"
        "[s]: <gone ref.md> \"Title\"\n"
        "[^1]: a footnote, not-a-link.md\n"
        "[t]: img/here.png 'fine'\n"
    )
    root = make_repo(tmp, {"a.md": text, "img/here.png": b"\x89PNG"})
    expect(
        "images and reference definitions",
        run(root, "a.md"),
        1,
        [
            "a.md:1: missing file: img/gone.png",
            "a.md:3: missing file: gone-target.md",
            "a.md:3: missing file: img/badge.png",
            "a.md:4: missing file: gone-ref.md",
            "a.md:5: missing file: gone ref.md",
        ],
    )


def test_root_relative(tmp):
    root = make_repo(tmp, {"docs/a.md": "[ok](/b.md)\n[bad](/docs/b.md)\n", "b.md": "b\n"})
    expect("root-relative targets", run(root, "docs/a.md"), 1, ["docs/a.md:2: missing file: /docs/b.md"])


def test_title_angle_percent_query(tmp):
    text = (
        '[a](b.md "A title")\n'
        "[b](b.md 'single')\n"
        "[c](b.md (paren))\n"
        "[d](<my file.md>)\n"
        "[e](my%20file.md)\n"
        "[f](b.md?v=1)\n"
        "[g](<gone file.md> 'x')\n"
        "[h](gone%20two.md \"t\")\n"
        "[i](dir/file(1).md)\n"
        "[j](b.md\n'title on the next line')\n"
    )
    root = make_repo(tmp, {"a.md": text, "b.md": "b\n", "my file.md": "m\n", "dir/file(1).md": "p\n"})
    expect(
        "titles, angle brackets, percent-encoding, query, parentheses",
        run(root, "a.md"),
        1,
        ["a.md:7: missing file: gone file.md", "a.md:8: missing file: gone%20two.md"],
    )


def test_not_a_link(tmp):
    text = "[a] (gone1.md)\n[b](my gone2.md)\n\\[c\\](gone3.md)\n[d]: prose with words.md\n"
    root = make_repo(tmp, {"a.md": text})
    expect("text that is not a link is not checked", run(root, "a.md"), 0, [])


def test_anchor_rule(tmp):
    target = (
        "# Diátaxis\n"
        "## Setup\n"
        "## Setup\n"
        "## What's new? (v2)\n"
        "## The `foo_bar` *option* and __bold__\n"
        "## [Linked](x.md) heading ##\n"
        "Setext Title\n"
        "============\n"
        "Second setext\n"
        "---\n"
        '<a id="Custom-Id"></a>\n'
        "<span name='named'></span>\n"
        "```\n## Fenced Heading\n<a id=\"fenced-id\"></a>\n```\n"
        "Text with `<a id=\"span-id\">` in code.\n"
    )
    links = (
        "[1](b.md#diátaxis)\n"
        "[2](b.md#di%C3%A1taxis)\n"
        "[3](b.md#setup)\n"
        "[4](b.md#setup-1)\n"
        "[5](b.md#SETUP)\n"
        "[6](b.md#whats-new-v2)\n"
        "[7](b.md#the-foo_bar-option-and-bold)\n"
        "[8](b.md#linked-heading)\n"
        "[9](b.md#setext-title)\n"
        "[10](b.md#second-setext)\n"
        "[11](b.md#custom-id)\n"
        "[12](b.md#named)\n"
        "[13](b.md#setup-2)\n"
        "[14](b.md#fenced-heading)\n"
        "[15](b.md#fenced-id)\n"
        "[16](b.md#span-id)\n"
        "[17](b.md#diataxis)\n"
        "[18](b.md#top)\n"
    )
    root = make_repo(tmp, {"a.md": links, "b.md": target})
    expect(
        "GitHub anchor rule",
        run(root, "a.md"),
        1,
        [
            "a.md:13: missing anchor: b.md#setup-2",
            "a.md:14: missing anchor: b.md#fenced-heading",
            "a.md:15: missing anchor: b.md#fenced-id",
            "a.md:16: missing anchor: b.md#span-id",
            "a.md:17: missing anchor: b.md#diataxis",
        ],
    )


def test_fragment_on_non_markdown(tmp):
    root = make_repo(tmp, {"a.md": "[a](run.py#L10)\n[b](gone.py#L1)\n", "run.py": "print()\n"})
    expect("fragment on a non-Markdown file", run(root, "a.md"), 1, ["a.md:2: missing file: gone.py#L1"])


def test_deleted_tracked_file(tmp):
    root = make_repo(tmp, {"a.md": "[b](b.md)\n", "b.md": "b\n"})
    git(root, "add", "a.md", "b.md")
    (root / "b.md").unlink()
    expect("a tracked file deleted from disk", run(root, "a.md"), 1, ["a.md:1: missing file: b.md"])


def test_bad_bytes(tmp):
    root = make_repo(tmp, {"a.md": b"# T\xff\xfe\n\n[x](gone.md) \xc3( [ok](#t)\n"})
    expect("a file that is not valid UTF-8", run(root, "a.md"), 1, ["a.md:3: missing file: gone.md"])


def test_unrelated_link(tmp):
    root = make_repo(tmp, {"a.md": "[b](b.md)\n", "b.md": "b\n", "c.md": "[n](nowhere.md)\n[o](../../x.md)\n"})
    expect("a broken link elsewhere, to another target, is not reported", run(root, "a.md"), 0, [])


def test_wide_targets(tmp):
    root = make_repo(tmp, {"a.md": "[ok](b.md#real)\n[bad](b.md#fake)\n", "b.md": "## Real\n"})
    expect("a link to a file that was not given is verified", run(root, "a.md"), 1, ["a.md:2: missing anchor: b.md#fake"])


def test_renamed_heading(tmp):
    root = make_repo(
        tmp,
        {"a.md": "Intro\n\n[x](b.md#old)\n[y](b.md#new)\n", "b.md": "## New\n", "c.md": "[z](a.md#gone)\n"},
    )
    expect("a link to a renamed heading of a given file", run(root, "b.md"), 1, ["a.md:3: missing anchor: b.md#old"])


def test_moved_file(tmp):
    root = make_repo(tmp, {"a.md": "[old](old.md)\n", "docs/x.md": "\n[up](../old.md#part)\n", "new.md": "n\n"})
    expect(
        "a link to a given file no longer on disk",
        run(root, str(root / "old.md"), "new.md"),
        1,
        ["a.md:1: missing file: old.md", "docs/x.md:2: missing file: ../old.md#part"],
    )


def test_deleted_image(tmp):
    root = make_repo(tmp, {"a.md": "![x](img/x.png)\n[ref]: img/x.png\n"})
    expect(
        "a link to a given image no longer on disk",
        run(root, "img/x.png"),
        1,
        ["a.md:1: missing file: img/x.png", "a.md:2: missing file: img/x.png"],
    )


def test_both_ends_given(tmp):
    root = make_repo(tmp, {"a.md": "[old](old.md)\n"})
    expect("a link between two given files is reported once", run(root, "a.md", "old.md"), 1, ["a.md:1: missing file: old.md"])


def test_ignored_reader(tmp):
    root = make_repo(tmp, {"a.md": "a\n", "notes/n.md": "[old](../old.md)\n"}, ignore="notes/\n")
    expect("an ignored Markdown file is not read for links to a given file", run(root, "old.md"), 0, [])


def test_ignored_file_named(tmp):
    root = make_repo(
        tmp,
        {"notes/n.md": "## Here\n\n[g](gone.md)\n[h](#here)\n[s](n.md#here)\n[a](../a.md)\n", "a.md": "a\n"},
        ignore="notes/\n",
    )
    expect("a given ignored Markdown file is checked", run(root, "notes/n.md"), 1, ["notes/n.md:3: missing file: gone.md"])


def test_non_markdown_argument(tmp):
    root = make_repo(tmp, {"a.md": "[x](src/x.py)\n", "src/x.py": "# [a](gone.md)\n"})
    expect("a non-Markdown file given has no links read", run(root, "a.md", "src/x.py"), 0, [])


def test_paths_from_subdirectory(tmp):
    root = make_repo(tmp, {"docs/a.md": "[g](gone.md)\n", "b.md": "[d](docs/a.md#nope)\n"})
    expect(
        "arguments relative to the current directory, output relative to the root",
        run(root, "a.md", cwd=root / "docs"),
        1,
        ["b.md:1: missing anchor: docs/a.md#nope", "docs/a.md:1: missing file: gone.md"],
    )


def test_sorted_by_file_then_line(tmp):
    root = make_repo(tmp, {"b.md": "\n\n[z](z.md)\n[y](y.md)\n", "a.md": "\n[x](x.md)\n", "a/c.md": "[w](w.md)\n"})
    expect(
        "output sorted by file then line",
        run(root, "b.md", "a.md", "a/c.md"),
        1,
        ["a.md:2: missing file: x.md", "a/c.md:1: missing file: w.md", "b.md:3: missing file: z.md", "b.md:4: missing file: y.md"],
    )


def test_misuse(tmp):
    root = make_repo(tmp, {"a.md": "a\n", "docs/b.md": "b\n"})
    (tmp / "outside.md").write_text("o\n", encoding="utf-8")
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    misuse("no argument", run(root))
    misuse("a directory argument", run(root, "docs"))
    misuse("a directory argument with a trailing slash", run(root, "docs/"))
    misuse("the repository root as argument", run(root, "."))
    misuse("a path outside the repository", run(root, str(tmp / "outside.md")))
    misuse("a relative path leaving the repository", run(root, "../outside.md"))
    misuse("an unknown flag", run(root, "--nope", "a.md"))
    misuse("a dash for standard input", run(root, "-"))
    misuse("a run outside a git repository", run(root, str(tmp / "outside.md"), cwd=elsewhere, ceiling=tmp))


def test_stdin_never_read(tmp):
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n"})
    # Standard input is a pipe nobody writes to or closes: reading it would block.
    for label, args in (("no argument", []), ("a file", ["a.md"])):
        with subprocess.Popen(
            [sys.executable, "-I", str(SCRIPT), *args],
            cwd=root,
            env=environment(tmp),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as process:
            try:
                rc = process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                rc = -1
            process.stdin.close()
        record(f"standard input never read ({label})", rc == (1 if args else 2), f"rc={rc}")


def snapshot(root):
    """Every path under the working tree with its content hash, .git excluded."""
    state = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = Path(directory) / name
            state[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def status(root):
    done = subprocess.run(
        ["git", "status", "--porcelain", "--ignored"], cwd=root, env=environment(root.parent), capture_output=True, text=True, check=True
    )
    return done.stdout


def test_read_only(tmp):
    root = make_repo(
        tmp,
        {"a.md": "[g](gone.md)\n[o](old.md)\n", "b.md": "[a](a.md#x)\n", "notes/n.md": "[a](../a.md)\n"},
        ignore="notes/\n",
    )
    git(root, "add", "a.md")
    before_status, before_tree = status(root), snapshot(root)
    index = (root / ".git" / "index").read_bytes()
    git_dir = sorted(str(p.relative_to(root)) for p in (root / ".git").rglob("*"))
    rc, _, _ = run(root, "a.md", "old.md", "notes/n.md")
    record("read-only: the run found the broken links", rc == 1, f"rc={rc}")
    record("read-only: index untouched", (root / ".git" / "index").read_bytes() == index, "index changed")
    record("read-only: nothing added under .git", sorted(str(p.relative_to(root)) for p in (root / ".git").rglob("*")) == git_dir, ".git changed")
    record("read-only: working tree untouched", snapshot(root) == before_tree, "working tree changed")
    record("read-only: git status unchanged", status(root) == before_status, "git status changed")


def test_executable(tmp):
    record("the script is executable", os.access(SCRIPT, os.X_OK), f"{SCRIPT.name} lacks the executable bit")
    record(
        "the script starts with the python3 shebang",
        SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"),
        "unexpected first line",
    )
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n"})
    expect("run by path through its shebang", run(root, "a.md", direct=True), 1, ["a.md:1: missing file: gone.md"])


def test_submodule_target(tmp):
    # A gitlink (submodule) at vendor/sub, its checkout on disk. Files inside it are not
    # ignored by git: every clone that initialises the submodule has them.
    root = make_repo(tmp, {"a.md": "[s](vendor/sub/README.md)\n[t](vendor/sub/README.md#s)\n"})
    sub = root / "vendor" / "sub"
    sub.mkdir(parents=True)
    git(sub, "init", "-q")
    (sub / "README.md").write_text("# S\n", encoding="utf-8")
    git(root, "update-index", "--add", "--cacheinfo", "160000,1234567890123456789012345678901234567890,vendor/sub")
    expect("a link into a submodule is not reported as ignored by git", run(root, "a.md"), 0, [])


def test_symlink_leaving_repository_without_fragment(tmp):
    (tmp / "elsewhere.md").write_text("# Elsewhere\n", encoding="utf-8")
    root = make_repo(tmp, {"a.md": "[a](link.md)\n[b](link.md#elsewhere)\n"})
    (root / "link.md").symlink_to(tmp / "elsewhere.md")
    expect(
        "a symlink leaving the repository is outside with or without a fragment",
        run(root, "a.md"),
        1,
        ["a.md:1: outside the repository: link.md", "a.md:2: outside the repository: link.md#elsewhere"],
    )


def test_not_a_link_markup(tmp):
    text = (
        "Escaped opening \\[c](gone1.md) is text.\n"
        "No opening bracket f(x)](gone2.md) is text.\n"
        "<!-- [old](gone3.md) -->\n"
        "[real](gone4.md)\n"
    )
    root = make_repo(tmp, {"a.md": text})
    expect(
        "an escaped `[`, a `](` with no `[`, and an HTML comment hold no link",
        run(root, "a.md"),
        1,
        ["a.md:4: missing file: gone4.md"],
    )


def test_closed_stdout(tmp):
    root = make_repo(tmp, {"a.md": "".join(f"[x](gone{i}.md)\n" for i in range(5000))})
    with subprocess.Popen(
        [sys.executable, "-I", str(SCRIPT), "a.md"],
        cwd=root,
        env=environment(tmp),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        process.stdout.readline()
        process.stdout.close()
        try:
            err = process.stderr.read().decode("utf-8", "replace")
            rc = process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            err, rc = "timed out", -1
    record(
        "a reader closing stdout early (| head) gives no traceback and a contract exit code",
        rc == 1 and "Traceback" not in err and "BrokenPipeError" not in err,
        f"rc={rc} stderr={err.strip()[-300:]!r}",
    )


def test_unreadable_unrelated_file(tmp):
    label = "an unreadable file that was not given does not discard the report on the given file"
    if running_as_root():
        skip(label, "running as root")
        return
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n", "c.md": "[x](y.md)\n"})
    (root / "c.md").chmod(0)
    try:
        rc, out, err = run(root, "a.md")
    finally:
        (root / "c.md").chmod(0o644)
    record(
        label,
        rc == 3 and out.splitlines() == ["a.md:1: missing file: gone.md"] and "c.md" in err and "Traceback" not in err,
        f"rc={rc} stdout={out!r} stderr={err.strip()[-300:]!r}",
    )


def test_submodule_missing_and_anchor(tmp):
    root = make_repo(tmp, {"a.md": "[g](vendor/sub/GONE.md)\n[h](vendor/sub/README.md#nope)\n[n](nested/doc.md#n)\n"})
    sub = root / "vendor" / "sub"
    sub.mkdir(parents=True)
    git(sub, "init", "-q")
    (sub / "README.md").write_text("# S\n", encoding="utf-8")
    git(root, "update-index", "--add", "--cacheinfo", "160000,1234567890123456789012345678901234567890,vendor/sub")
    nested = root / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    (nested / "doc.md").write_text("# N\n", encoding="utf-8")
    expect(
        "a file absent from a submodule is missing; its headings are checked; a nested repository counts",
        run(root, "a.md"),
        1,
        ["a.md:1: missing file: vendor/sub/GONE.md", "a.md:2: missing anchor: vendor/sub/README.md#nope"],
    )


def test_symlinked_directory(tmp):
    root = make_repo(tmp, {"a.md": "[b](alias/b.md#b)\n[c](alias/c.md)\n", "real/b.md": "# B\n"})
    (root / "alias").symlink_to("real")
    expect("a file under a listed symlinked directory is present", run(root, "a.md"), 1, ["a.md:2: missing file: alias/c.md"])


def test_dangling_symlink_target(tmp):
    root = make_repo(tmp, {"a.md": "[d](dangling.md)\n"})
    (root / "dangling.md").symlink_to("nowhere.md")
    expect("a symlink to nothing is a missing file, not ignored by git", run(root, "a.md"), 1, ["a.md:1: missing file: dangling.md"])


def test_link_opener_and_comments(tmp):
    text = (
        "Escaped backslash \\\\[a](gone1.md) is a link.\n"
        "[across\nlines](gone2.md) is a link.\n"
        "[para\n\nbreak](gone3.md) is not.\n"
        "[nested [brackets] text](gone4.md) is a link.\n"
        "<!--\n[c](gone5.md)\n\n[d](gone6.md)\n-->\n"
        "<!--> [e](gone7.md)\n"
        "Code `<!--` then [f](gone8.md) then --> end.\n"
        "Unclosed <!-- then [g](gone9.md)\n"
    )
    root = make_repo(tmp, {"a.md": text})
    expect(
        "the opening bracket rules and HTML comments",
        run(root, "a.md"),
        1,
        [
            "a.md:1: missing file: gone1.md",
            "a.md:3: missing file: gone2.md",
            "a.md:7: missing file: gone4.md",
            "a.md:13: missing file: gone7.md",
            "a.md:14: missing file: gone8.md",
            "a.md:15: missing file: gone9.md",
        ],
    )


def test_comment_hides_anchor(tmp):
    target = "# Shown\n<!--\n## Hidden\n<a id=\"gone-id\"></a>\n-->\n"
    links = "[a](b.md#shown)\n[b](b.md#hidden)\n[c](b.md#gone-id)\n"
    root = make_repo(tmp, {"a.md": links, "b.md": target})
    expect(
        "headings and ids inside an HTML comment are not anchors",
        run(root, "a.md"),
        1,
        ["a.md:2: missing anchor: b.md#hidden", "a.md:3: missing anchor: b.md#gone-id"],
    )


def test_unreadable_given_file(tmp):
    label = "an unreadable given file: exit 3, named on stderr, the other given file still reported"
    if running_as_root():
        skip(label, "running as root")
        return
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n", "b.md": "[h](gone2.md)\n"})
    (root / "a.md").chmod(0)
    try:
        rc, out, err = run(root, "a.md", "b.md")
    finally:
        (root / "a.md").chmod(0o644)
    record(
        label,
        rc == 3 and out.splitlines() == ["b.md:1: missing file: gone2.md"] and "cannot read a.md" in err and "Traceback" not in err,
        f"rc={rc} stdout={out!r} stderr={err.strip()[-300:]!r}",
    )


def test_moved_directory(tmp):
    # guides/x.md was moved to how-to/x.md, and guides/ went with it; keep/ still holds y.md.
    links = "[a](guides/x.md#setup)\n[b](guides/)\n[c](guides)\n[d](keep/)\n[e](how-to/x.md#setup)\n"
    root = make_repo(tmp, {"a.md": links, "how-to/x.md": "## Setup\n", "keep/y.md": "y\n"})
    broken = ["a.md:1: missing file: guides/x.md#setup", "a.md:2: missing file: guides/", "a.md:3: missing file: guides"]
    expect("a moved directory, passed as its files' old and new paths", run(root, "guides/x.md", "how-to/x.md"), 1, broken)
    expect("a moved directory, passed by its old path", run(root, "guides"), 1, broken)
    expect("a moved directory, passed by its old path with a slash", run(root, "guides/"), 1, broken)
    expect("a gone file whose directory still holds files", run(root, "keep/x.md"), 0, [])


def test_linear_time(tmp):
    # Each shape made the parser rescan the text from every position; the files are not
    # given, so they are read only to look for links to a.md.
    paragraph = "".join(f"Call f(a)](b{i}) here and [ok](a.md)\n" for i in range(4000))
    headings = (
        "# " + "_a " * 20000 + "\n"
        "# " + "![x" * 20000 + "\n"
        "# " + "[x" * 20000 + "\n"
        "# " + " ".join("`" * n for n in range(1, 400)) + "\n"
        "> " * 20000 + "x\n"
        "- > 1. " * 20000 + "x\n"
        "-" + " " * 80000 + "x\n"
        "# a" + " " * 80000 + "b\n"
        "# a" + " \t" * 40000 + "#b\n"
    )
    files = {
        "a.md": "# A\n[h](headings.md#nope)\n",
        "headings.md": headings,
        "brackets.md": "](" * 40000 + "\n",
        "paragraph.md": paragraph,
        "spans.md": "`a` " * 40000 + "\n",
        "runs.md": " ".join("`" * n for n in range(1, 400)) + "\n",
        "comments.md": "<!-- " * 40000 + "\n",
        "openers.md": "[" * 40000 + "](a.md)\n",
        "destinations.md": "[x](a" * 16000 + "\n",
        "nested.md": "[x](a(" * 16000 + "\n",
        "titles.md": '[x](a "' * 8000 + "\n",
        "angles.md": "[x](<a" * 8000 + "\n",
    }
    root = make_repo(tmp, files)
    expect(
        "pathological Markdown files are parsed in linear time",
        run(root, "a.md", timeout=15),
        1,
        ["a.md:2: missing anchor: headings.md#nope"],
    )


def test_control_characters(tmp):
    root = make_repo(tmp, {"a.md": "[a](<x\x1b]0;t\x07\x1b[31mred.md>)\n[b](<l\u2028ine.md>)\n"})
    rc, out, err = run(root, "a.md")
    expect(
        "control characters in a target are escaped",
        (rc, out, err),
        1,
        ["a.md:1: missing file: x\\x1b]0;t\\x07\\x1b[31mred.md", "a.md:2: missing file: l\\u2028ine.md"],
    )
    record("no raw control character on stdout", "\x1b" not in out and "\x07" not in out, f"stdout={out!r}")


def test_control_characters_in_file_name(tmp):
    name = "evil\nb.md:9: missing file: forged.md"
    root = make_repo(tmp, {name: "[g](gone.md)\n"})
    expect(
        "a line break in a file name cannot forge an output line",
        run(root, name),
        1,
        ["evil\\x0ab.md:9: missing file: forged.md:1: missing file: gone.md"],
    )
    rc, _, err = run(root, "--\x1b[2K")
    record("an option with control characters is escaped in the usage error", rc == 2 and "\x1b" not in err, f"rc={rc} stderr={err[:200]!r}")


def test_git_failure_reported(tmp):
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n"})
    missing = str(tmp / "no-such-git-dir")
    rc, out, err = run(root, "a.md", extra={"GIT_DIR": missing})
    record(
        "git's reason for not finding the repository is shown with the usage",
        rc == 2 and out == "" and missing in err and "git: " in err and "docs-link-check.py <file>..." in err,
        f"rc={rc} stdout={out!r} stderr={err[:400]!r}",
    )
    git(root, "add", "a.md")
    (root / ".git" / "index").write_bytes(b"not an index")
    rc, out, err = run(root, "a.md")
    record(
        "a failing git ls-files is reported with git's words and without usage",
        rc == 2 and out == "" and "git ls-files failed" in err and "git: " in err and "<file>..." not in err,
        f"rc={rc} stdout={out!r} stderr={err[:400]!r}",
    )


def test_given_symlink_leaving_repository(tmp):
    (tmp / "out.md").write_text("[x](nowhere.md)\n", encoding="utf-8")
    root = make_repo(tmp, {"a.md": "a\n"})
    (root / "given.md").symlink_to(tmp / "out.md")
    misuse("a given file that is a symbolic link leaving the repository", run(root, "given.md"))


def test_slug_collisions(tmp):
    root = make_repo(
        tmp,
        {"a.md": "[1](b.md#a)\n[2](b.md#a-1)\n[3](b.md#a-1-1)\n[4](b.md#a-2)\n", "b.md": "# A\n## a\n## a-1\n"},
    )
    expect("a heading whose slug is a generated suffix takes the next free one", run(root, "a.md"), 1, ["a.md:4: missing anchor: b.md#a-2"])


def test_uninitialised_submodule(tmp):
    root = make_repo(tmp, {"a.md": "[s](vendor/sub/README.md)\n[t](vendor/sub/README.md#s)\n[u](vendor/sub)\n"})
    (root / "vendor" / "sub").mkdir(parents=True)
    git(root, "update-index", "--add", "--cacheinfo", "160000,1234567890123456789012345678901234567890,vendor/sub")
    rc, out, err = run(root, "a.md")
    expect("links into a submodule that is not checked out are not reported", (rc, out, err), 0, [])
    record("the submodule that is not checked out is named on stderr", "not checked out" in err and "vendor/sub" in err, f"stderr={err!r}")


# ---- cases added by the test engineer


def test_markdown_suffix(tmp):
    root = make_repo(
        tmp,
        {
            "a.md": "[g](guide.markdown#real)\n[h](guide.markdown#nope)\n",
            "guide.markdown": "## Real\n",
            "notes.markdown": "[o](old.md)\n",
        },
    )
    expect(
        "a .markdown file is read for anchors and for links to a given file",
        run(root, "a.md", "old.md"),
        1,
        ["a.md:2: missing anchor: guide.markdown#nope", "notes.markdown:1: missing file: old.md"],
    )


def test_third_repeated_heading(tmp):
    root = make_repo(tmp, {"a.md": "[a](b.md#setup-2)\n[b](b.md#setup-3)\n", "b.md": "## Setup\n## Setup\n## Setup\n"})
    expect("the third heading of the same text gets -2, not -3", run(root, "a.md"), 1, ["a.md:2: missing anchor: b.md#setup-3"])


def test_anchor_keeps_each_space(tmp):
    # "C++ & Rust": punctuation dropped, the two spaces left each become a hyphen.
    root = make_repo(tmp, {"a.md": "[a](b.md#c--rust)\n[b](b.md#c-rust)\n", "b.md": "## C++ & Rust\n"})
    expect("dropped punctuation leaves its spaces, each one a hyphen", run(root, "a.md"), 1, ["a.md:2: missing anchor: b.md#c-rust"])


def test_non_ascii_anchor_case(tmp):
    root = make_repo(
        tmp,
        {"a.md": "[a](b.md#été-日本語)\n[b](b.md#ÉTÉ-日本語)\n[c](b.md#ete-日本語)\n", "b.md": "## Été 日本語\n"},
    )
    expect(
        "non-ASCII letters kept and lowercased, the fragment compared with case ignored",
        run(root, "a.md"),
        1,
        ["a.md:3: missing anchor: b.md#ete-日本語"],
    )


def test_not_headings(tmp):
    target = "#NoSpace\n####### Seven\n~~~\n## Tilde Fenced\n~~~\n## Real\n"
    links = "[a](b.md#nospace)\n[b](b.md#seven)\n[c](b.md#tilde-fenced)\n[d](b.md#real)\n"
    root = make_repo(tmp, {"a.md": links, "b.md": target})
    expect(
        "no space after #, seven #, and a heading in a tilde fence give no anchor",
        run(root, "a.md"),
        1,
        ["a.md:1: missing anchor: b.md#nospace", "a.md:2: missing anchor: b.md#seven", "a.md:3: missing anchor: b.md#tilde-fenced"],
    )


def test_heading_in_list_item(tmp):
    # GitHub renders a heading inside a list item or a block quote as a heading with an anchor.
    root = make_repo(
        tmp,
        {"a.md": "[a](b.md#item-heading)\n[b](b.md#quoted-heading)\n", "b.md": "- ## Item heading\n\n> ## Quoted heading\n"},
    )
    expect("a heading inside a list item or a block quote has an anchor", run(root, "a.md"), 0, [])


def test_heading_container_markers(tmp):
    target = (
        "1. ## Step one\n\n2) # Step two\n\n* - > ### Nested deep\n\n+    # Four spaces\n\n"
        "-     # Indented code\n\n-# Not a marker\n\n1.# Glued\n"
    )
    links = (
        "[a](b.md#step-one)\n[b](b.md#step-two)\n[c](b.md#nested-deep)\n[d](b.md#four-spaces)\n"
        "[e](b.md#indented-code)\n[f](b.md#not-a-marker)\n[g](b.md#glued)\n"
    )
    root = make_repo(tmp, {"a.md": links, "b.md": target})
    expect(
        "ordered and nested list items and quotes hold headings; five spaces or no space after the marker do not",
        run(root, "a.md"),
        1,
        [
            "a.md:5: missing anchor: b.md#indented-code",
            "a.md:6: missing anchor: b.md#not-a-marker",
            "a.md:7: missing anchor: b.md#glued",
        ],
    )


def test_crlf_and_bom(tmp):
    text = "﻿# Title\r\n\r\n```\r\n[a](gone1.md)\r\n```\r\n[b](#title)\r\n[c](gone2.md)\r\n"
    root = make_repo(tmp, {"a.md": text.encode("utf-8")})
    expect(
        "CRLF line endings and a byte order mark: fences close, the first heading counts",
        run(root, "a.md"),
        1,
        ["a.md:7: missing file: gone2.md"],
    )


def test_percent_encoded_outside_never_opened(tmp):
    os.mkfifo(tmp / "pipe.md")
    root = make_repo(tmp, {"a.md": "[a](%2E%2E/pipe.md#x)\n[b](..%2Fpipe.md)\n"})
    expect(
        "a percent-encoded path leaving the repository is outside and never opened",
        run(root, "a.md"),
        1,
        ["a.md:1: outside the repository: %2E%2E/pipe.md#x", "a.md:2: outside the repository: ..%2Fpipe.md"],
    )


def test_self_link_reported_once(tmp):
    root = make_repo(tmp, {"a.md": "# A\n[x](#nope)\n[y](a.md#nope)\n[z](./a.md#nope)\n"})
    lines = ["a.md:2: missing anchor: #nope", "a.md:3: missing anchor: a.md#nope", "a.md:4: missing anchor: ./a.md#nope"]
    expect("a given file linking to itself: each link reported once", run(root, "a.md"), 1, lines)
    expect("the same file given twice: each link reported once", run(root, "a.md", "a.md"), 1, lines)
    expect(
        "the same file given by relative, absolute and dotted paths: each link reported once",
        run(root, "a.md", str(root / "a.md"), "docs/../a.md", "./a.md"),
        1,
        lines,
    )


def test_empty_fragment_and_same_file(tmp):
    root = make_repo(tmp, {"a.md": "[a](#)\n[b](b.md#)\n[c](a.md)\n[d](?x=1)\n[e](a.md?x=1#)\n", "b.md": "b\n"})
    expect("an empty fragment and a link to the same file resolve", run(root, "a.md"), 0, [])


def test_empty_directory_target(tmp):
    root = make_repo(tmp, {"a.md": "[e](empty/)\n[f](gone-dir/)\n"})
    (root / "empty").mkdir()
    expect(
        "an empty directory on disk is not listed by git; an absent one is missing",
        run(root, "a.md"),
        1,
        ["a.md:1: ignored by git: empty/", "a.md:2: missing file: gone-dir/"],
    )


def test_given_ignored_target(tmp):
    root = make_repo(tmp, {"a.md": "[n](notes/n.md)\n", "notes/n.md": "n\n"}, ignore="notes/\n")
    expect(
        "a link to a given file that git ignores is reported from a file that was not given",
        run(root, "notes/n.md"),
        1,
        ["a.md:1: ignored by git: notes/n.md"],
    )


def test_given_target_by_other_spellings(tmp):
    root = make_repo(
        tmp,
        {
            "a.md": "[x](./old.md)\n[y](docs/../old.md#p)\n[z](/old.md)\n",
            "docs/d.md": "[u](../old.md)\n[v](../b.md#gone)\n",
            "b.md": "## Here\n",
        },
    )
    expect(
        "links to a given path written as ./, .., or from the root, from files that were not given",
        run(root, "old.md", "b.md"),
        1,
        [
            "a.md:1: missing file: ./old.md",
            "a.md:2: missing file: docs/../old.md#p",
            "a.md:3: missing file: /old.md",
            "docs/d.md:1: missing file: ../old.md",
            "docs/d.md:2: missing anchor: ../b.md#gone",
        ],
    )


def test_reference_definitions_in_code_and_indented(tmp):
    text = "```\n[r]: gone1.md\n```\n   [s]: gone2.md\n`[t]: gone3.md`\n"
    root = make_repo(tmp, {"a.md": text})
    expect(
        "a reference definition in a fence is skipped, one indented by three spaces is checked",
        run(root, "a.md"),
        1,
        ["a.md:4: missing file: gone2.md"],
    )


def test_misuse_more(tmp):
    root = make_repo(tmp, {"a.md": "a\n"})
    misuse("an unknown flag after a file", run(root, "a.md", "--nope"))
    misuse("a path outside the repository that is not on disk", run(root, "../gone.md"))
    misuse("an absolute path outside the repository that is not on disk", run(root, str(tmp / "gone.md")))
    misuse("a directory among files", run(root, "a.md", "."))
    misuse("the .git directory", run(root, ".git"))


def test_misuse_writes_nothing(tmp):
    root = make_repo(tmp, {"a.md": "[g](gone.md)\n", "docs/b.md": "b\n"})
    before_status, before_tree = status(root), snapshot(root)
    for args in ([], ["docs"], ["--nope"], ["../x.md"]):
        run(root, *args)
    record("misuse changes nothing: working tree", snapshot(root) == before_tree, "working tree changed")
    record("misuse changes nothing: git status", status(root) == before_status, "git status changed")


# ---- --web: a loopback server inside this process, never the outside network


class Recorder:
    """Every GET the loopback server received, and the most served at once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []
        self.in_flight = 0
        self.peak = 0

    def add(self, path, headers):
        with self.lock:
            self.requests.append((path, headers))

    def paths(self):
        with self.lock:
            return [path for path, _ in self.requests]

    def enter(self):
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)

    def leave(self):
        with self.lock:
            self.in_flight -= 1


SLOW_ANSWER = 1.0
ENDLESS_BODY = 3.0


def make_handler(recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def answer(self, code, location=None):
            self.send_response(code)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            recorder.add(self.path, dict(self.headers.items()))
            path, _, query = self.path.partition("?")
            parts = path.strip("/").split("/")
            if path == "/ok":
                self.answer(200)
            elif parts[0] == "status" and len(parts) == 2 and parts[1].isdigit():
                self.answer(int(parts[1]))
            elif parts[0] == "hop" and len(parts) == 2 and parts[1].isdigit():
                left = int(parts[1])
                if left:
                    self.answer(302, f"/hop/{left - 1}")
                else:
                    self.answer(200)
            elif path == "/loop":
                self.answer(301, "/loop")
            elif path == "/to":
                self.answer(302, unquote(query))
            elif path == "/nolocation":
                self.answer(302)
            elif path == "/pause":
                recorder.enter()
                time.sleep(0.2)
                recorder.leave()
                self.answer(200)
            elif path == "/slow":
                time.sleep(SLOW_ANSWER)
                self.answer(200)
            elif parts[0] == "redirect" and len(parts) == 2 and parts[1].isdigit():
                self.answer(int(parts[1]), "/ok")
            elif parts[0] == "endless" and len(parts) == 2 and parts[1].isdigit():
                # A head, then a body that keeps coming for ENDLESS_BODY seconds.
                self.send_response(int(parts[1]))
                self.send_header("Content-Length", str(10**9))
                self.end_headers()
                end = time.monotonic() + ENDLESS_BODY
                while time.monotonic() < end:
                    self.wfile.write(b"x" * 1024)
                    self.wfile.flush()
                    time.sleep(0.01)
            else:
                self.answer(404)

    return Handler


class QuietServer(ThreadingHTTPServer):
    """A client that hangs up early (a timeout, a TLS hello) is expected; any other error is printed."""

    def handle_error(self, request, client_address):
        if not isinstance(sys.exception(), (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


@contextlib.contextmanager
def serving():
    """A loopback HTTP server: its base address and the recorder of what it was asked."""
    recorder = Recorder()
    server = QuietServer(("127.0.0.1", 0), make_handler(recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", recorder
    finally:
        server.shutdown()
        server.server_close()


def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def load_script():
    """A fresh copy of the script as a module, so a replaced function never leaks into the next case."""
    spec = importlib.util.spec_from_file_location("docs_link_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LOOPBACK = ipaddress.ip_address("127.0.0.1")


def open_loopback(module):
    """Let the module request 127.0.0.1, where the test server listens; every other address as shipped."""
    shipped = module.is_public
    module.is_public = lambda address: address == LOOPBACK or shipped(address)
    return module


def open_loopback_once(module):
    """Let the module request 127.0.0.1 once, for the first hop; every later address as shipped."""
    shipped = module.is_public
    granted = []

    def judge(address):
        if address == LOOPBACK and not granted:
            granted.append(address)
            return True
        return shipped(address)

    module.is_public = judge
    return module


def fake_names(module, names):
    """Replace the module's lookup for the names given (None: does not resolve); the calls it gets."""
    shipped = module.lookup
    calls = []

    def lookup(host, port):
        calls.append(host)
        if host not in names:
            return shipped(host, port)
        if names[host] is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6, (address, port, 0, 0)) if ":" in address else (socket.AF_INET, (address, port))
            for address in names[host]
        ]

    module.lookup = lookup
    return calls


def run_inside(module, root, *args):
    """Run the module's main in root, as the script would run; git reads no global configuration."""
    git_environment = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": str(root.parent)}
    saved_environment = {key: os.environ.get(key) for key in git_environment}
    saved_cwd = os.getcwd()
    out, err = io.StringIO(), io.StringIO()
    os.chdir(root)
    os.environ.update(git_environment)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = module.main(list(args))
            except SystemExit as stop:
                code = stop.code
    finally:
        os.chdir(saved_cwd)
        for key, value in saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return code, out.getvalue(), err.getvalue()


def unverified(err):
    return [line for line in err.splitlines() if line.startswith("could not verify ")]


def expect_web(label, result, code, lines=(), not_verified=()):
    """Exit code, stdout lines and `could not verify` lines exactly; no traceback."""
    rc, out, err = result
    ok = rc == code and out.splitlines() == list(lines) and unverified(err) == list(not_verified) and "Traceback" not in err
    record(
        label,
        ok,
        f"expected exit {code}, {list(lines)!r} and {list(not_verified)!r}; got exit {rc}, {out.splitlines()!r}; stderr={err.strip()[-600:]!r}",
    )


def links(*targets):
    return "".join(f"[l{i}]({target})\n" for i, target in enumerate(targets, 1))


def test_web_offline_by_default(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(f"{base}/ok", f"{base}/status/404", "https://example.invalid/x")})
        module = open_loopback(load_script())
        lookups = fake_names(module, {})
        result = run_inside(module, root, "a.md")
        record(
            "without --web: output and exit code of the offline check",
            result == (0, "", "docs-link-check.py: 0 broken links\n"),
            f"got {result!r}",
        )
        record("without --web: no lookup and no request", lookups == [] and recorder.paths() == [], f"{lookups!r} {recorder.paths()!r}")
        shipped = run(root, "a.md")
        record("without --web, as shipped: same output", shipped == (0, "", "docs-link-check.py: 0 broken links\n"), f"got {shipped!r}")
        record("without --web, as shipped: no request", recorder.paths() == [], f"{recorder.paths()!r}")


def test_web_dead(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(f"{base}/status/404", f"{base}/status/410", f"<{base}/gone\x1b[31m>")})
        expect_web(
            "--web: 404 and 410 are dead links, control characters escaped",
            run_inside(open_loopback(load_script()), root, "--web", "a.md"),
            1,
            [f"a.md:1: dead link: {base}/status/404", f"a.md:2: dead link: {base}/status/410", f"a.md:3: dead link: {base}/gone\\x1b[31m"],
        )
        record("--web: each dead address requested", len(recorder.paths()) == 3, f"{recorder.paths()!r}")


def test_web_live_and_redirects_within_limit(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(f"{base}/ok", f"{base}/hop/3", f"{base}/hop/5", f"{base}/status/204")})
        expect_web("--web: 2xx, directly or after up to five redirects, is fine", run_inside(open_loopback(load_script()), root, "a.md", "--web"), 0)
        record("--web: the whole redirect chain was followed", recorder.paths().count("/hop/0") == 2, f"{recorder.paths()!r}")


def test_web_too_many_redirects(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(f"{base}/hop/6", f"{base}/loop")})
        expect_web(
            "--web: six redirects or a loop: too many redirects, exit code unchanged",
            run_inside(open_loopback(load_script()), root, "--web", "a.md"),
            0,
            not_verified=[f"could not verify a.md:1: {base}/hop/6: too many redirects", f"could not verify a.md:2: {base}/loop: too many redirects"],
        )
        paths = recorder.paths()
        record(
            "--web: a first request and five redirects, no more",
            "/hop/0" not in paths and paths.count("/hop/1") == 1 and paths.count("/loop") == 6,
            f"{paths!r}",
        )


def test_web_could_not_verify(tmp):
    with serving() as (base, recorder):
        closed = closed_port()
        https = base.replace("http://", "https://")
        targets = [
            f"{base}/status/401",
            f"{base}/status/403",
            f"{base}/status/429",
            f"{base}/status/418",
            f"{base}/status/500",
            f"{base}/status/503",
            f"{base}/nolocation",
            f"{base}/to?ftp://127.0.0.1/x",
            f"{base}/to?file:///etc/passwd",
            f"http://127.0.0.1:{closed}/ok",
            f"{https}/ok",
            f"{base}/ok",
        ]
        root = make_repo(tmp, {"a.md": links(*targets)})
        reasons = [
            "HTTP 401",
            "HTTP 403",
            "HTTP 429",
            "HTTP 418",
            "HTTP 500",
            "HTTP 503",
            "redirect without a location",
            "redirect to another scheme",
            "redirect to another scheme",
            "connection refused",
            "TLS failure",
        ]
        expect_web(
            "--web: refusals, other 4xx, 5xx, refused connection, TLS failure, other schemes: could not verify, exit unchanged",
            run_inside(open_loopback(load_script()), root, "--web", "a.md"),
            0,
            not_verified=[f"could not verify a.md:{i}: {target}: {reason}" for i, (target, reason) in enumerate(zip(targets, reasons), 1)],
        )
        record("--web: a redirect to another scheme is not followed", "/x" not in recorder.paths(), f"{recorder.paths()!r}")


def test_web_timeout(tmp):
    with serving() as (base, _):
        root = make_repo(tmp, {"a.md": links(f"{base}/slow", f"{base}/ok")})
        module = open_loopback(load_script())
        module.TIMEOUT = 0.2
        started = time.monotonic()
        result = run_inside(module, root, "--web", "a.md")
        elapsed = time.monotonic() - started
        expect_web("--web: an answer later than the timeout", result, 0, not_verified=[f"could not verify a.md:1: {base}/slow: timed out"])
        record("--web: the run does not wait for the slow answer", elapsed < SLOW_ANSWER, f"took {elapsed:.2f}s")


def test_web_unknown_host(tmp):
    with serving() as (base, _):
        root = make_repo(tmp, {"a.md": links("http://gone.invalid/page", f"{base}/ok"), "b.md": links("http://gone.invalid/page")})
        module = open_loopback(load_script())
        fake_names(module, {"gone.invalid": None})
        expect_web(
            "--web: a host that does not resolve is dead when another address answered",
            run_inside(module, root, "--web", "a.md"),
            1,
            ["a.md:1: dead link: http://gone.invalid/page"],
        )
        module = open_loopback(load_script())
        fake_names(module, {"gone.invalid": None})
        rc, out, err = run_inside(module, root, "--web", "b.md")
        expect_web(
            "--web: a host that does not resolve, nothing answered: not dead, exit 3",
            (rc, out, err),
            3,
            not_verified=["could not verify b.md:1: http://gone.invalid/page: host not found"],
        )
        record("--web: stderr says the web could not be reached", "the web could not be reached" in err, f"stderr={err!r}")
        closed = closed_port()
        root_c = tmp / "c"
        root_c.mkdir()
        git(root_c, "init", "-q")
        (root_c / "c.md").write_text(links(f"http://127.0.0.1:{closed}/a"), encoding="utf-8")
        rc, out, err = run_inside(open_loopback(load_script()), root_c, "--web", "c.md")
        record(
            "--web: every connection refused: the web could not be reached, exit 3",
            rc == 3 and out == "" and "the web could not be reached" in err,
            f"rc={rc} stdout={out!r} stderr={err!r}",
        )


def test_web_local_addresses_as_shipped(tmp):
    with serving() as (base, recorder):
        port = base.rsplit(":", 1)[1]
        targets = [
            f"http://127.0.0.1:{port}/ok",
            f"http://localhost:{port}/ok",
            f"http://[::1]:{port}/ok",
            f"http://2130706433:{port}/ok",
            f"http://0x7f.1:{port}/ok",
            f"http://[::ffff:127.0.0.1]:{port}/ok",
            f"http://0.0.0.0:{port}/ok",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://100.64.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://2852039166/latest/meta-data/",
            "http://[fe80::1]/",
            "http://[fd00::1]/",
            "http://224.0.0.1/",
            "http://240.0.0.1/",
        ]
        root = make_repo(tmp, {"a.md": links(*targets)})
        expect_web(
            "--web as shipped: loopback, private, shared, link-local, metadata, multicast and reserved addresses refused",
            run(root, "--web", "a.md"),
            0,
            not_verified=[f"could not verify a.md:{i}: {target}: local or private address" for i, target in enumerate(targets, 1)],
        )
        record("--web as shipped: the loopback server got no request", recorder.paths() == [], f"{recorder.paths()!r}")


def test_web_local_names(tmp):
    with serving() as (base, recorder):
        port = base.rsplit(":", 1)[1]
        names = {
            "intranet.test": ["10.0.0.1"],
            "router.test": ["192.168.1.1"],
            "metadata.test": ["169.254.169.254"],
            "mixed.test": ["127.0.0.1", "10.0.0.1"],
            "mapped.test": ["::ffff:127.0.0.2"],
        }
        targets = [f"http://{name}:{port}/ok" for name in names]
        root = make_repo(tmp, {"a.md": links(*targets)})
        module = open_loopback(load_script())
        fake_names(module, names)
        expect_web(
            "--web: a name that resolves to a non-public address, or to one among others, is refused",
            run_inside(module, root, "--web", "a.md"),
            0,
            not_verified=[f"could not verify a.md:{i}: {target}: local or private address" for i, target in enumerate(targets, 1)],
        )
        record("--web: no request for a name that resolves to a non-public address", recorder.paths() == [], f"{recorder.paths()!r}")


def test_web_redirect_to_local(tmp):
    with serving() as (base, recorder):
        port = base.rsplit(":", 1)[1]
        for destination in (
            f"http://127.0.0.1:{port}/secret",
            f"http://localhost:{port}/secret",
            f"http://2130706433:{port}/secret",
            f"http://[::ffff:127.0.0.1]:{port}/secret",
            "http://10.0.0.1/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.test/latest/meta-data/",
        ):
            with tempfile.TemporaryDirectory(dir=tmp) as each:
                root = make_repo(Path(each), {"a.md": links(f"{base}/to?{destination}")})
                module = open_loopback_once(load_script())
                fake_names(module, {"metadata.test": ["169.254.169.254"]})
                expect_web(
                    f"--web: a redirect to {destination} is refused",
                    run_inside(module, root, "--web", "a.md"),
                    0,
                    not_verified=[f"could not verify a.md:1: {base}/to?{destination}: local or private address"],
                )
        paths = recorder.paths()
        record("--web: the local address behind a redirect is never requested", all(path.startswith("/to?") for path in paths) and len(paths) == 7, f"{paths!r}")


def test_web_credentials(tmp):
    with serving() as (base, recorder):
        host = base.removeprefix("http://")
        targets = [f"http://user:secret@{host}/ok", f"http://user@{host}/ok", f"http://:secret@{host}/ok", f"{base}/to?http://u:secret@{host}/ok"]
        root = make_repo(tmp, {"a.md": links(*targets)})
        rc, out, err = run_inside(open_loopback(load_script()), root, "--web", "a.md")
        expect_web(
            "--web: an address with a user name or password is never requested",
            (rc, out, err),
            0,
            not_verified=[
                f"could not verify a.md:1: http://***@{host}/ok: carries credentials",
                f"could not verify a.md:2: http://***@{host}/ok: carries credentials",
                f"could not verify a.md:3: http://***@{host}/ok: carries credentials",
                f"could not verify a.md:4: {base}/to?http://u:secret@{host}/ok: carries credentials",
            ],
        )
        record("--web: only the redirect was requested", [path.split("?")[0] for path in recorder.paths()] == ["/to"], f"{recorder.paths()!r}")
        record(
            "--web: the password of an address is never printed",
            "secret" not in out and all("secret" not in line for line in unverified(err)[:3]),
            f"stdout={out!r} stderr={err!r}",
        )


def test_web_request_hygiene(tmp):
    with serving() as (base, recorder):
        port = base.rsplit(":", 1)[1]
        root = make_repo(tmp, {"a.md": links(f"<http://site.test:{port}/ok?q=a b>")})
        module = open_loopback(load_script())
        calls = fake_names(module, {"site.test": ["127.0.0.1"]})
        expect_web("--web: a name resolved once and connected to by the vetted address", run_inside(module, root, "--web", "a.md"), 0)
        record("--web: one lookup, no second resolution for the connection", calls == ["site.test"], f"{calls!r}")
        requests = recorder.requests
        record("--web: one request", len(requests) == 1, f"{requests!r}")
        if len(requests) == 1:
            path, headers = requests[0]
            names = {name.lower() for name in headers}
            record("--web: the path is sent percent-encoded", path == "/ok?q=a%20b", f"path={path!r}")
            record("--web: the Host header names the host as written", headers.get("Host") == f"site.test:{port}", f"{headers!r}")
            record("--web: a plain User-Agent naming the script", headers.get("User-Agent") == "docs-link-check.py", f"{headers!r}")
            record(
                "--web: no cookie, authorization or body",
                not names & {"cookie", "authorization", "proxy-authorization", "content-length", "transfer-encoding"},
                f"{headers!r}",
            )


def test_web_same_address_twice(tmp):
    with serving() as (base, recorder):
        root = make_repo(
            tmp,
            {"a.md": links(f"{base}/status/404", f"{base}/status/404#part"), "b.md": f"\n[r]: {base}/status/404#other\n"},
        )
        expect_web(
            "--web: an address linked from several places: every place reported",
            run_inside(open_loopback(load_script()), root, "--web", "a.md", "b.md"),
            1,
            [f"a.md:1: dead link: {base}/status/404", f"a.md:2: dead link: {base}/status/404#part", f"b.md:2: dead link: {base}/status/404#other"],
        )
        record("--web: one request per distinct address, the fragment not sent", recorder.paths() == ["/status/404"], f"{recorder.paths()!r}")


def test_web_other_targets_not_requested(tmp):
    with serving() as (base, recorder):
        host = base.removeprefix("http://")
        root = make_repo(
            tmp,
            {
                "a.md": links("b.md", f"ftp://{host}/x", f"//{host}/y", "mailto:someone@example.invalid") + f"`{base}/code` and\n```\n[c]({base}/fenced)\n```\n",
                "b.md": links(f"{base}/from-b"),
            },
        )
        expect_web(
            "--web: other schemes, //host, code and files not given are not requested",
            run_inside(open_loopback(load_script()), root, "--web", "a.md"),
            0,
        )
        record("--web: nothing requested", recorder.paths() == [], f"{recorder.paths()!r}")


def test_web_sorted_with_offline(tmp):
    with serving() as (base, _):
        root = make_repo(
            tmp,
            {
                "b.md": links(f"{base}/status/410", "gone-b.md"),
                "a.md": links("gone-a.md", f"{base}/status/404", f"{base}/ok", "#nope"),
            },
        )
        expect_web(
            "--web: offline and dead lines together, sorted by file then line",
            run_inside(open_loopback(load_script()), root, "--web", "b.md", "a.md"),
            1,
            [
                "a.md:1: missing file: gone-a.md",
                f"a.md:2: dead link: {base}/status/404",
                "a.md:4: missing anchor: #nope",
                f"b.md:1: dead link: {base}/status/410",
                "b.md:2: missing file: gone-b.md",
            ],
        )


def test_web_limit(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(*(f"{base}/ok?n={i}" for i in range(201)))})
        expect_web(
            "--web: at most 200 distinct addresses, the rest limit reached",
            run_inside(open_loopback(load_script()), root, "--web", "a.md"),
            0,
            not_verified=[f"could not verify a.md:201: {base}/ok?n=200: limit reached"],
        )
        record("--web: 200 requests", len(recorder.paths()) == 200, f"{len(recorder.paths())} requests")


def test_web_a_few_at_a_time(tmp):
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(*(f"{base}/pause?n={i}" for i in range(24)))})
        module = open_loopback(load_script())
        expect_web("--web: addresses checked in parallel", run_inside(module, root, "--web", "a.md"), 0)
        record(
            "--web: a few requests at a time, never more than the pool",
            1 < recorder.peak <= module.WORKERS,
            f"peak={recorder.peak} workers={module.WORKERS}",
        )


def test_web_misuse(tmp):
    root = make_repo(tmp, {"a.md": "a\n"})
    for args in (["--web"], ["--nope", "a.md"], ["--web", "--nope", "a.md"], ["a.md", "--web", "--nope"], ["--Web", "a.md"]):
        rc, out, err = result = run(root, *args)
        misuse(f"misuse: {' '.join(args)}", result)
        record(f"misuse: {' '.join(args)}: the usage describes --web", "docs-link-check.py --web <file>..." in err, f"stderr={err[:300]!r}")


def test_web_not_in_agents_or_skills(tmp):
    named = [
        str(path.relative_to(PLUGIN))
        for directory in ("agents", "skills")
        for path in sorted((PLUGIN / directory).rglob("*"))
        if path.is_file() and "--web" in path.read_text(encoding="utf-8", errors="replace")
    ]
    record("no agent or skill names --web", named == [], f"named in {named!r}")


def test_web_writes_nothing(tmp):
    with serving() as (base, _):
        root = make_repo(tmp, {"a.md": links(f"{base}/ok", f"{base}/status/404", "gone.md")})
        git(root, "add", "a.md")
        before_status, before_tree = status(root), snapshot(root)
        rc_shipped, _, _ = run(root, "--web", "a.md")
        rc_inside, _, _ = run_inside(open_loopback(load_script()), root, "--web", "a.md")
        record("--web writes nothing: the runs found the broken links", rc_shipped == 1 and rc_inside == 1, f"rc={rc_shipped},{rc_inside}")
        record("--web writes nothing: working tree", snapshot(root) == before_tree, "working tree changed")
        record("--web writes nothing: git status", status(root) == before_status, "git status changed")


def test_web_is_public(tmp):
    module = load_script()
    refused = [
        "127.0.0.1", "127.1.2.3", "0.0.0.0", "10.0.0.1", "172.16.0.1", "192.168.1.1", "100.64.0.1", "169.254.169.254",
        "224.0.0.1", "240.0.0.1", "255.255.255.255", "192.0.2.1", "::1", "::", "fe80::1", "fec0::1", "fd00::1", "ff02::1",
        "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "::127.0.0.1", "2002:7f00:1::", "64:ff9b::7f00:1",
    ]
    public = ["8.8.8.8", "93.184.215.14", "2606:4700::1111", "::ffff:8.8.8.8"]
    wrong = [a for a in refused if module.is_public(ipaddress.ip_address(a))] + [a for a in public if not module.is_public(ipaddress.ip_address(a))]
    record("is_public refuses every local, private, shared, reserved or multicast form, and only those", wrong == [], f"wrong for {wrong!r}")


@contextlib.contextmanager
def trickling_tls(seconds, interval=0.1):
    """A loopback server that answers a TLS hello with a record header, then one byte of it per interval."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                continue
            with connection:
                connection.settimeout(1)
                try:
                    connection.recv(4096)
                    connection.sendall(b"\x16\x03\x03\x40\x00")
                    end = time.monotonic() + seconds
                    while time.monotonic() < end and not stop.is_set():
                        connection.sendall(b"\x02")
                        time.sleep(interval)
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        thread.join(timeout=5)
        listener.close()


def test_web_tls_handshake_bounded(tmp):
    """Ten seconds per request: a server that drips its TLS handshake must not hold the run past the timeout."""
    with serving() as (base, _), trickling_tls(3.0) as port:
        target = f"https://127.0.0.1:{port}/ok"
        root = make_repo(tmp, {"a.md": links(target, f"{base}/ok")})
        module = open_loopback(load_script())
        module.TIMEOUT = 0.5
        started = time.monotonic()
        result = run_inside(module, root, "--web", "a.md")
        elapsed = time.monotonic() - started
        record("--web: a trickled TLS handshake is cut at the timeout", elapsed < 2.0, f"took {elapsed:.2f}s with TIMEOUT 0.5; result={result!r}")
        expect_web("--web: a trickled TLS handshake is timed out", result, 0, not_verified=[f"could not verify a.md:1: {target}: timed out"])


def test_web_offline_without_ssl(tmp):
    """Without --web the check is that of 0.4.10, also on a Python built without the ssl module."""
    root = make_repo(tmp, {"a.md": links("gone.md", "https://example.invalid/x")})
    no_ssl = (
        "import runpy, sys\n"
        "sys.modules['ssl'] = None\n"
        "sys.argv = sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", no_ssl, str(SCRIPT), "a.md"],
        cwd=root,
        env=environment(root.parent),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )
    result = (done.returncode, done.stdout, done.stderr)
    record(
        "without --web, no ssl module: output and exit code of the offline check",
        result == (1, "a.md:1: missing file: gone.md\n", "docs-link-check.py: 1 broken link\n"),
        f"got {result!r}",
    )


@contextlib.contextmanager
def without_ssl():
    """Make `import ssl` fail, as on a Python built without it, then put back what was there."""
    saved = sys.modules.get("ssl", "absent")
    sys.modules["ssl"] = None
    try:
        yield
    finally:
        if saved == "absent":
            sys.modules.pop("ssl", None)
        else:
            sys.modules["ssl"] = saved


def test_web_without_ssl(tmp):
    """On a Python without ssl, --web still checks http addresses; an https one is never requested."""
    with serving() as (base, recorder):
        https = base.replace("http://", "https://")
        targets = [f"{https}/ok", f"{base}/status/404", f"{base}/to?{https}/status/404"]
        root = make_repo(tmp, {"a.md": links(*targets)})
        with without_ssl():
            result = run_inside(open_loopback(load_script()), root, "--web", "a.md")
        expect_web(
            "--web without the ssl module: http checked, https not verified",
            result,
            1,
            [f"a.md:2: dead link: {base}/status/404"],
            [f"could not verify a.md:1: {targets[0]}: TLS unavailable", f"could not verify a.md:3: {targets[2]}: TLS unavailable"],
        )
        paths = recorder.paths()
        record("--web without the ssl module: no https hop reaches the server", sorted(paths) == ["/status/404", f"/to?{https}/status/404"], f"{paths!r}")


# ---- --web, QA additions


# Run the script as shipped with an audit hook that reports every socket the interpreter
# is asked to resolve, create or connect: proof by the runtime, not by a replaced function.
AUDITED = (
    "import runpy, sys\n"
    "def hook(event, args):\n"
    "    if event == 'socket.getaddrinfo':\n"
    "        sys.__stderr__.write(f'AUDIT {event} {args[0]!r}\\n')\n"
    "    elif event in ('socket.__new__', 'socket.connect', 'socket.gethostbyname', 'socket.sendto'):\n"
    "        sys.__stderr__.write(f'AUDIT {event}\\n')\n"
    "sys.addaudithook(hook)\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def run_audited(root, *args):
    done = subprocess.run(
        [sys.executable, "-I", "-c", AUDITED, str(SCRIPT), *args],
        cwd=root,
        env=environment(root.parent),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )
    audit = [line for line in done.stderr.splitlines() if line.startswith("AUDIT ")]
    err = "".join(line + "\n" for line in done.stderr.splitlines() if not line.startswith("AUDIT "))
    return (done.returncode, done.stdout, err), audit


def test_web_qa_offline_opens_no_socket(tmp):
    """Without --web, as shipped: not one name lookup, socket or connection, whatever the files link to."""
    root = make_repo(
        tmp,
        {"a.md": links("https://example.invalid/x", "http://127.0.0.1:9/", "gone.md", "http://user:secret@example.invalid/")},
    )
    result, audit = run_audited(root, "a.md")
    record(
        "QA without --web: output of the offline check",
        result == (1, "a.md:3: missing file: gone.md\n", "docs-link-check.py: 1 broken link\n"),
        f"got {result!r}",
    )
    record("QA without --web: no lookup, no socket, no connection", audit == [], f"audit={audit!r}")


def test_web_qa_refused_addresses_open_no_connection(tmp):
    """--web as shipped: local addresses and credentials never reach a connect, and the credential host is never even resolved."""
    root = make_repo(
        tmp,
        {
            "a.md": links(
                "http://127.0.0.1:9/",
                "http://localhost/",
                "http://[::1]/",
                "http://10.0.0.1/",
                "http://192.168.1.1/",
                "http://169.254.169.254/",
                "http://2130706433/",
                "http://0x7f.1/",
                "https://user:secret@example.invalid/",
            )
        },
    )
    (rc, out, err), audit = run_audited(root, "--web", "a.md")
    record(
        "QA --web as shipped: refused addresses: nothing on stdout, nothing dead",
        rc in (0, 3) and out == "" and "Traceback" not in err,
        f"rc={rc} stdout={out!r} stderr={err[-400:]!r}",
    )
    record(
        "QA --web as shipped: no socket created or connected for a refused address",
        not [line for line in audit if not line.startswith("AUDIT socket.getaddrinfo")],
        f"audit={audit!r}",
    )
    record(
        "QA --web as shipped: an address carrying credentials is not even looked up",
        not [line for line in audit if "example.invalid" in line],
        f"audit={audit!r}",
    )
    record("QA --web as shipped: the password is printed nowhere", "secret" not in out + err, f"stdout={out!r} stderr={err!r}")
    record(
        "QA --web as shipped: the credentials line",
        "could not verify a.md:9: https://***@example.invalid/: carries credentials" in unverified(err),
        f"stderr={err!r}",
    )


def test_web_qa_control_characters_on_stderr(tmp):
    """The `could not verify` lines escape control characters, as stdout does: no raw escape reaches the terminal."""
    root = make_repo(tmp, {"a.md": links("<http://10.0.0.1/\x1b[31mred>", "<http://u:p@10.0.0.1/\x07bell>")})
    rc, out, err = run(root, "--web", "a.md")
    expect_web(
        "QA --web: control characters escaped in the could-not-verify lines",
        (rc, out, err),
        0,
        not_verified=[
            "could not verify a.md:1: http://10.0.0.1/\\x1b[31mred: local or private address",
            "could not verify a.md:2: http://***@10.0.0.1/\\x07bell: carries credentials",
        ],
    )
    record("QA --web: no raw control character on stderr", "\x1b" not in err and "\x07" not in err, f"stderr={err!r}")


def test_web_qa_fragment_not_checked(tmp):
    """A live page with a fragment it does not have is fine: the fragment is neither sent nor checked."""
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(f"{base}/ok#no-such-part", f"{base}/ok#", f"{base}/ok#other")})
        expect_web("QA --web: a fragment on a live page is not checked", run_inside(open_loopback(load_script()), root, "--web", "a.md"), 0)
        record("QA --web: one request, without the fragment", recorder.paths() == ["/ok"], f"{recorder.paths()!r}")


def test_web_qa_link_forms(tmp):
    """Images, titles and reference definitions are checked; a link inside an HTML comment or in a non-Markdown file is not."""
    with serving() as (base, recorder):
        root = make_repo(
            tmp,
            {
                "a.md": (
                    f'![i]({base}/status/404 "a title")\n'
                    f"[t]({base}/status/410 'other')\n"
                    f'[r]: {base}/status/404?ref "Title"\n'
                    f"<!-- [c]({base}/status/404?comment) -->\n"
                    f"[![badge]({base}/status/404?badge)]({base}/ok)\n"
                ),
                "notes.txt": links(f"{base}/status/404?txt"),
            },
        )
        expect_web(
            "QA --web: images, titles and reference definitions are checked",
            run_inside(open_loopback(load_script()), root, "--web", "a.md", "notes.txt"),
            1,
            [
                f"a.md:1: dead link: {base}/status/404",
                f"a.md:2: dead link: {base}/status/410",
                f"a.md:3: dead link: {base}/status/404?ref",
                f"a.md:5: dead link: {base}/status/404?badge",
            ],
        )
        paths = recorder.paths()
        record(
            "QA --web: a link in a comment or a non-Markdown file is not requested",
            sorted(paths) == sorted(["/status/404", "/status/410", "/status/404?ref", "/status/404?badge", "/ok"]),
            f"{paths!r}",
        )


def test_web_qa_redirect_codes(tmp):
    """301, 302, 303, 307 and 308 are followed; 300 and 304 are not redirects and are not verified."""
    with serving() as (base, recorder):
        followed = [f"{base}/redirect/{code}" for code in (301, 302, 303, 307, 308)]
        other = [f"{base}/redirect/{code}" for code in (300, 304)]
        root = make_repo(tmp, {"a.md": links(*followed, *other)})
        rc, out, err = run_inside(open_loopback(load_script()), root, "--web", "a.md")
        lines = unverified(err)
        record(
            "QA --web: every redirect code followed to a live page; 300 and 304 not verified",
            rc == 0
            and out == ""
            and len(lines) == 2
            and lines[0].startswith(f"could not verify a.md:6: {other[0]}: ")
            and lines[1].startswith(f"could not verify a.md:7: {other[1]}: "),
            f"rc={rc} stdout={out!r} stderr={err!r}",
        )
        record("QA --web: five redirects followed, 300 and 304 not", recorder.paths().count("/ok") == 5, f"{recorder.paths()!r}")


def test_web_qa_body_never_read(tmp):
    """Status line and headers only: an answer whose body keeps coming does not hold the run."""
    with serving() as (base, _):
        root = make_repo(tmp, {"a.md": links(f"{base}/endless/200", f"{base}/endless/404")})
        started = time.monotonic()
        result = run_inside(open_loopback(load_script()), root, "--web", "a.md")
        elapsed = time.monotonic() - started
        expect_web("QA --web: a page with an endless body is judged by its status", result, 1, [f"a.md:2: dead link: {base}/endless/404"])
        record("QA --web: the body is not read", elapsed < ENDLESS_BODY / 2, f"took {elapsed:.2f}s, the body lasts {ENDLESS_BODY}s")


def test_web_qa_unreachable_keeps_offline_lines(tmp):
    """Web unreachable: the offline lines are still printed, nothing is called dead, exit 3."""
    closed = closed_port()
    root = make_repo(tmp, {"a.md": links("gone.md", f"http://127.0.0.1:{closed}/a", "http://gone.invalid/page")})
    module = open_loopback(load_script())
    fake_names(module, {"gone.invalid": None})
    rc, out, err = run_inside(module, root, "--web", "a.md")
    record(
        "QA --web: web unreachable and a broken file link: the file link printed, nothing dead, exit 3",
        rc == 3 and out.splitlines() == ["a.md:1: missing file: gone.md"] and "the web could not be reached" in err,
        f"rc={rc} stdout={out!r} stderr={err!r}",
    )


def test_web_qa_unknown_host_any_answer(tmp):
    """Any HTTP answer, even an error or a late one, shows the web was reached: the unknown host is dead."""
    with serving() as (base, _):
        root = make_repo(tmp, {"a.md": links("http://gone.invalid/page", f"{base}/status/503"), "b.md": links("http://gone.invalid/b", f"{base}/slow")})
        module = open_loopback(load_script())
        fake_names(module, {"gone.invalid": None})
        expect_web(
            "QA --web: an unknown host is dead when another address answered 503",
            run_inside(module, root, "--web", "a.md"),
            1,
            ["a.md:1: dead link: http://gone.invalid/page"],
            [f"could not verify a.md:2: {base}/status/503: HTTP 503"],
        )
        module = open_loopback(load_script())
        fake_names(module, {"gone.invalid": None})
        expect_web(
            "QA --web: an unknown host is dead when the only answer comes late",
            run_inside(module, root, "--web", "b.md"),
            1,
            ["b.md:1: dead link: http://gone.invalid/b"],
        )


def test_web_qa_limit_counts_distinct_addresses(tmp):
    """200 distinct addresses, some linked twice or with a fragment: all requested, none `limit reached`."""
    with serving() as (base, recorder):
        targets = [f"{base}/ok?n={i}" for i in range(200)] + [f"{base}/ok?n=0#again", f"{base}/ok?n=199"]
        root = make_repo(tmp, {"a.md": links(*targets)})
        expect_web("QA --web: 200 distinct addresses linked 202 times: no limit reached", run_inside(open_loopback(load_script()), root, "--web", "a.md"), 0)
        record("QA --web: 200 distinct addresses, 200 requests", len(recorder.paths()) == 200, f"{len(recorder.paths())} requests")


def test_web_qa_bounds(tmp):
    """Ten seconds per request, and a few requests at a time: not one per address."""
    module = load_script()
    record("QA --web: ten seconds per request", module.TIMEOUT == 10, f"TIMEOUT={module.TIMEOUT!r}")
    with serving() as (base, recorder):
        root = make_repo(tmp, {"a.md": links(*(f"{base}/pause?n={i}" for i in range(24)))})
        expect_web("QA --web: 24 slow addresses", run_inside(open_loopback(load_script()), root, "--web", "a.md"), 0)
        record("QA --web: a few at a time, at most 10", 1 < recorder.peak <= 10, f"peak={recorder.peak}")


def make_certificate(directory, name):
    """A self-signed certificate for name, made by openssl; None when openssl is not there."""
    key, cert = directory / f"{name}.key", directory / f"{name}.pem"
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2",
             "-subj", f"/CN={name}", "-addext", f"subjectAltName=DNS:{name}"],
            check=True,
            capture_output=True,
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return key, cert


@contextlib.contextmanager
def serving_tls(key, cert):
    """The loopback server over TLS; the server names the clients asked for in their hello."""
    import ssl

    recorder = Recorder()
    names = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.sni_callback = lambda _socket, name, _context: names.append(name)
    server = QuietServer(("127.0.0.1", 0), make_handler(recorder))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], recorder, names
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def trusted(cert):
    """OpenSSL's own SSL_CERT_FILE, for one in-process run: the default context trusts cert."""
    saved = os.environ.get("SSL_CERT_FILE")
    os.environ["SSL_CERT_FILE"] = str(cert) if cert else os.devnull
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("SSL_CERT_FILE", None)
        else:
            os.environ["SSL_CERT_FILE"] = saved


def test_web_qa_tls_name_and_certificate(tmp):
    """TLS goes to the vetted address with the host name as server name, and the certificate is checked against that name."""
    made = make_certificate(tmp, "site.test")
    if made is None:
        skip("QA --web: TLS certificate and server name", "openssl is not installed")
        return
    key, cert = made
    with serving_tls(key, cert) as (port, recorder, names):
        root = make_repo(
            tmp,
            {"a.md": links(f"https://site.test:{port}/status/404"), "b.md": links(f"https://other.test:{port}/ok"), "c.md": links(f"https://site.test:{port}/ok")},
        )
        module = open_loopback(load_script())
        calls = fake_names(module, {"site.test": ["127.0.0.1"], "other.test": ["127.0.0.1"]})
        with trusted(cert):
            expect_web("QA --web: a trusted certificate for the name: the answer is judged", run_inside(module, root, "--web", "a.md"), 1, [f"a.md:1: dead link: https://site.test:{port}/status/404"])
        record("QA --web: the server name sent is the host name, not the address", names == ["site.test"], f"names={names!r}")
        record("QA --web: the name resolved once over TLS", calls == ["site.test"], f"calls={calls!r}")
        requests = recorder.requests
        record(
            "QA --web: over TLS, the Host header names the host",
            len(requests) == 1 and requests[0][1].get("Host") == f"site.test:{port}",
            f"{requests!r}",
        )
        module = open_loopback(load_script())
        fake_names(module, {"site.test": ["127.0.0.1"], "other.test": ["127.0.0.1"]})
        with trusted(cert):
            expect_web(
                "QA --web: a certificate for another name is a TLS failure",
                run_inside(module, root, "--web", "b.md"),
                3,  # the only address got no HTTP answer: the check is incomplete
                not_verified=[f"could not verify b.md:1: https://other.test:{port}/ok: TLS failure"],
            )
        module = open_loopback(load_script())
        fake_names(module, {"site.test": ["127.0.0.1"], "other.test": ["127.0.0.1"]})
        with trusted(None):
            expect_web(
                "QA --web: an untrusted certificate is a TLS failure",
                run_inside(module, root, "--web", "c.md"),
                3,  # the only address got no HTTP answer: the check is incomplete
                not_verified=[f"could not verify c.md:1: https://site.test:{port}/ok: TLS failure"],
            )
        record("QA --web: no request reached the server past a refused certificate", len(recorder.requests) == 1, f"{recorder.requests!r}")


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]


def main():
    for test in TESTS:
        with tempfile.TemporaryDirectory(prefix="docs-links-") as tmp:
            test(Path(tmp).resolve())
    print(f"{PASSES} passed, {len(FAILS)} failed, {len(SKIPS)} skipped")
    for skipped in SKIPS:
        print("  SKIP", skipped)
    for failure in FAILS:
        print("  FAIL", failure)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
