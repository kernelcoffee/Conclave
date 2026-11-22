#!/usr/bin/env python3
"""Offline tests for plugins/conclave/bin/docs-link-check.py.

    python3 -I tests/test_docs_links.py

Each case builds a throwaway git repository in a temporary directory, writes its
Markdown there and runs the script as a subprocess, so no broken link lives in this
repository. Git reads no global or system configuration. Exit 1 when a case fails.
"""

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "plugins" / "conclave" / "bin" / "docs-link-check.py"
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
