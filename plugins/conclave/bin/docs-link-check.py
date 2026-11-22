#!/usr/bin/env python3
"""Broken Markdown links in, and to, the files given. Lists every broken link that sits
in one of the given files, or that sits in any Markdown file git lists and points at one
of them. Changes nothing and never reads standard input.

    docs-link-check.py <file>...

  Each <file> is a path relative to the current directory, or absolute, inside the
  repository. A path that is no longer on disk is a file, or a directory, that was
  moved or deleted: links to it, to anything under it, and to a directory that held
  it, are reported. Files only: no directory on disk, pattern or option (name a file
  that starts with `-` as `./-name`).

  Prints `<file>:<line>: <kind>: <target>` on stdout, sorted by file then line, paths
  relative to the repository root, where <kind> is `missing file`, `missing anchor`,
  `ignored by git` or `outside the repository`; then a count on stderr. Control
  characters in a path or target are printed as `\\xNN` or `\\uNNNN` escapes.

  Exit 0 when nothing is broken, 1 when a link is broken, 2 on misuse (no file, a
  directory, a path outside the repository or a symbolic link leaving it, an option,
  not inside a git repository) or when git fails, with nothing on stdout. Exit 3 when
  a file cannot be read: a `cannot read <file>` line goes to stderr, the run goes on,
  and every broken link found is still printed, but the check is incomplete.

  Links inside fenced code blocks, code spans and HTML comments are not read. A target
  whose real path, symbolic links followed, leaves the repository is outside it. Files
  inside a submodule or a nested repository count as present when they are on disk,
  and their headings are checked like any other. Links into a submodule that is not
  checked out (an empty directory) cannot be checked: they are not reported, and the
  submodule is named on stderr.

Runs from anywhere inside the repository. Python standard library and git only.
"""

from __future__ import annotations

import bisect
import html
import io
import os
import posixpath
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import NoReturn
from urllib.parse import unquote

PROG = "docs-link-check.py"
MARKDOWN_SUFFIXES = (".md", ".markdown")

MISSING_FILE = "missing file"
MISSING_ANCHOR = "missing anchor"
IGNORED = "ignored by git"
OUTSIDE = "outside the repository"

# Exit code of a run that could not read every file it had to.
INCOMPLETE = 3

# Browsers scroll to the top of the page for `#top` when no element carries that id.
TOP_FRAGMENT = "top"

# Block structure. A container prefix (blockquote markers, indentation, one list marker)
# is allowed before a fence so fences nested in lists and quotes are recognised.
FENCE_OPEN = re.compile(r"^(?:[ \t]*>)*[ \t]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)?(`{3,}|~{3,})(.*)$")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
BACKTICKS = re.compile(r"`+")
# A heading may sit in a block quote or a list item, nested to any depth. Its container
# prefix is skipped one marker at a time: a `>` with one optional space, or a list item
# marker followed by the one to four spaces (or a tab) that place the item's content;
# five spaces after the marker start an indented code block, not a heading.
CONTAINER_MARKER = re.compile(r"[ \t]*(?:>[ ]?|(?:[-+*]|\d{1,9}[.)])(?:[ ]{1,4}(?![ ])|\t))")
# Matched where the container prefix ends. The text runs to the end of the line; its
# closing `#` sequence is stripped by atx_text, since matching that sequence in the
# pattern backtracks on long blank runs.
ATX_HEADING = re.compile(r"[ ]{0,3}(#{1,6})(?:[ \t]+(.*))?$")
SETEXT_UNDERLINE = re.compile(r"^[ ]{0,3}(=+|-+)[ \t]*$")

# Links. Inline links and images are found at their `](`, then their opening `[` is
# looked for in the same paragraph; reference definitions are whole lines. A label
# starting with `^` is a footnote, not a link.
INLINE_OPEN = re.compile(r"\]\(")
BRACKET = re.compile(r"\\[\s\S]|[\[\]]")
INLINE_SPECIAL = re.compile(r"\\[\s\S]?|<!--|`+")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
REFERENCE_DEFINITION = re.compile(
    r"^(?:[ \t]*>)*[ ]{0,3}\[(?!\^)(?:[^\[\]\\\n]|\\.){1,999}\]:[ \t]*"
    r"(?:<(?P<angle>[^<>\n]*)>|(?P<bare>[^\s<]\S*))"
    r"""(?:[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*$""",
    re.MULTILINE,
)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
ESCAPED_PUNCTUATION = re.compile(r"\\([!-/:-@\[-`{-~])")
TITLE_CLOSERS = {'"': '"', "'": "'", "(": ")"}
BACKSLASH_RUN = re.compile(r"\\+")
DESTINATION_SPACE = re.compile(r"[\x00-\x20]")
ANGLE_STOP = re.compile(r"[<>\n]")
PARENTHESIS = re.compile(r"[()]")

# Inline markup removed from a heading before its anchor is computed. Images and links
# are `[label]` then `(destination)` or `[reference]`, each part ending at its first
# closing character; underscore emphasis is a run of one to three `_` that opens before
# a non-space and closes, on the same line, at the next run of the same length after a
# non-space. Each is matched by a lookup in precomputed positions, never by a regex that
# rescans the rest of the heading from every opener.
HEADING_IMAGE_OPEN = re.compile(r"!\[")
HEADING_LINK_OPEN = re.compile(r"\[")
CLOSING_BRACKET = re.compile(r"\]")
CLOSING_PARENTHESIS = re.compile(r"\)")
LINE_BREAK = re.compile(r"\n")
HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
EMPHASIS_OPEN = re.compile(r"(?<![\w\\])(_{1,3})(?![\s_])")
EMPHASIS_CLOSE = {size: re.compile(rf"(?<![\s\\])(?=_{{{size}}}(?!\w))") for size in (1, 2, 3)}
ANCHOR_ATTRIBUTE = re.compile(r"""(?:^|\s)(?:id|name)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
OPEN_TAG = re.compile(r"<[A-Za-z][^<>]*>")

# Characters never printed as they are: C0 and C1 controls, DEL, line and paragraph
# separators, bidirectional overrides and isolates, and lone surrogates (bytes of a
# file name that is not UTF-8).
UNPRINTABLE_CHARACTER = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
SURROGATE_ESCAPES = range(0xDC80, 0xDD00)


def printable(text: str) -> str:
    """The text with every control, line-separating or bidirectional character escaped.

    Paths and link targets come from the repository's files; printed raw, an escape
    sequence would reach the terminal and a line break would forge an output line.
    """
    return UNPRINTABLE_CHARACTER.sub(escape_character, text)


def escape_character(match: re.Match[str]) -> str:
    code = ord(match.group(0))
    if code in SURROGATE_ESCAPES:
        return f"\\x{code - 0xDC00:02x}"
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def complain(reason: str) -> None:
    print(f"{PROG}: {printable(reason)}", file=sys.stderr)


def usage(reason: str) -> NoReturn:
    complain(reason)
    print(__doc__, end="", file=sys.stderr)
    sys.exit(2)


def relay(done: subprocess.CompletedProcess[bytes]) -> None:
    """Pass on what git printed on stderr, one line at a time."""
    for line in os.fsdecode(done.stderr).splitlines():
        if line.strip():
            complain(f"git: {line.rstrip()}")


def fail(reason: str, done: subprocess.CompletedProcess[bytes] | None = None) -> NoReturn:
    """End the run with exit 2 for a failure that is not misuse, with git's own words."""
    complain(reason)
    if done is not None:
        relay(done)
    sys.exit(2)


def git(cwd: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run git with an argument list; it never prompts, waits for input or takes a lock."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        fail("git not found")


def repository_root(cwd: str) -> str:
    """The repository root; failing to find one is misuse (a run outside a repository).

    git does not tell "outside a repository" apart from a repository it refuses (a
    safe.directory refusal, a bad GIT_DIR) other than in translated prose, so its own
    message is printed before the usage.
    """
    done = git(cwd, "rev-parse", "--show-toplevel")
    top = os.fsdecode(done.stdout.rstrip(b"\n"))
    if done.returncode != 0 or not top:
        relay(done)
        usage("cannot find the repository root: not inside a git repository, or git refused it")
    return os.path.realpath(top)


def given_path(argument: str, cwd: str, root: str) -> str:
    """The repository-relative path of one argument; misuse ends the run."""
    absolute = os.path.abspath(os.path.join(cwd, argument))
    parent, name = os.path.split(absolute)
    real = os.path.join(os.path.realpath(parent), name)
    relative = os.path.relpath(real, root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        usage(f"not inside the repository: {argument}")
    if os.path.isdir(real):
        usage(f"a directory, not a file: {argument}")
    if not inside(root, relative):
        usage(f"a symbolic link leaving the repository: {argument}")
    return relative.replace(os.sep, "/")


def known_files(root: str) -> set[str]:
    """Paths git lists (tracked, or untracked and not ignored) that are on disk.

    A submodule, or an untracked nested repository (listed with a trailing ``/``), is
    one entry for the whole directory.
    """
    done = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if done.returncode != 0:
        fail("git ls-files failed", done)
    listed = {os.fsdecode(entry).rstrip("/") for entry in done.stdout.split(b"\0") if entry}
    return {path for path in listed if path and os.path.exists(os.path.join(root, path))}


def directories_of(paths: set[str]) -> set[str]:
    """Every directory holding one of the paths, the repository root as ``""``."""
    found = {""}
    for path in paths:
        parent = posixpath.dirname(path)
        while parent and parent not in found:
            found.add(parent)
            parent = posixpath.dirname(parent)
    return found


def is_markdown(path: str) -> bool:
    return path.lower().endswith(MARKDOWN_SUFFIXES)


def inside(root: str, path: str) -> bool:
    """Whether the path, symbolic links followed, stays inside the repository."""
    real = os.path.realpath(os.path.join(root, path))
    return real == root or real.startswith(root + os.sep)


# ---- Markdown structure


def mask_fences(lines: list[str]) -> list[str]:
    """The lines with every fenced code block, fences included, blanked."""
    masked: list[str] = []
    closer: re.Pattern[str] | None = None
    for line in lines:
        if closer is not None:
            if closer.match(line):
                closer = None
            masked.append("")
            continue
        opened = FENCE_OPEN.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            fence = opened.group(1)
            closer = re.compile(rf"^(?:[ \t]*>)*[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$")
            masked.append("")
            continue
        masked.append(line)
    return masked


@dataclass(frozen=True)
class Region:
    """An inline code span or an HTML comment: text that holds no link."""

    start: int
    end: int
    code: bool
    # The number of backticks on each side of a code span.
    ticks: int = 0


def blank_line_starts(text: str) -> list[int]:
    """Where each blank line, the end of a paragraph, starts."""
    return [match.start() for match in BLANK_LINE.finditer(text)]


class InlineScanner:
    """Finds code spans and HTML comments in one pass; every lookup is a bisect.

    Each file git lists is read on every run, so no step may rescan the text from the
    current position: a file full of unclosed backticks or comments stays linear.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.blank_starts = blank_line_starts(text)
        self.last_close = text.rfind(COMMENT_CLOSE)
        self.runs: dict[int, list[int]] = {}
        for run in BACKTICKS.finditer(text):
            self.runs.setdefault(len(run.group(0)), []).append(run.start())

    def paragraph_end(self, position: int) -> int:
        index = bisect.bisect_left(self.blank_starts, position)
        return self.blank_starts[index] if index < len(self.blank_starts) else len(self.text)

    def comment_end(self, start: int) -> int | None:
        """The end of the HTML comment opening at start, or None when it is not closed."""
        body = start + len(COMMENT_OPEN)
        for empty in (">", "->"):
            if self.text.startswith(empty, body):
                return body + len(empty)
        if self.last_close < body:
            return None
        return self.text.find(COMMENT_CLOSE, body) + len(COMMENT_CLOSE)

    def code_span_end(self, start: int, run_end: int) -> int | None:
        """The end of the code span opened by the backticks from start to run_end, or None.

        It closes at the next run of exactly as many backticks in the same paragraph.
        """
        length = run_end - start
        starts = self.runs.get(length, [])
        index = bisect.bisect_left(starts, run_end)
        if index == len(starts) or starts[index] >= self.paragraph_end(run_end):
            return None
        return starts[index] + length

    def regions(self) -> list[Region]:
        """Code spans and HTML comments, left to right; whichever opens first wins."""
        text = self.text
        regions: list[Region] = []
        i = 0
        while (special := INLINE_SPECIAL.search(text, i)) is not None:
            i = special.start()
            token = special.group(0)
            if token[0] == "\\":
                i += 2
                continue
            if token == COMMENT_OPEN:
                end = self.comment_end(i)
                if end is None:
                    i += len(COMMENT_OPEN)
                    continue
                regions.append(Region(i, end, code=False))
                i = end
                continue
            run_end = special.end()
            end = self.code_span_end(i, run_end)
            if end is None:
                i = run_end
                continue
            regions.append(Region(i, end, code=True, ticks=run_end - i))
            i = end
        return regions


def inline_regions(text: str) -> list[Region]:
    return InlineScanner(text).regions()


def blank_regions(text: str, regions: list[Region], fill: str) -> str:
    """The text with each region's characters replaced by fill, line breaks kept."""
    parts: list[str] = []
    position = 0
    for region in regions:
        parts.append(text[position : region.start])
        parts.append("".join(char if char == "\n" else fill for char in text[region.start : region.end]))
        position = region.end
    parts.append(text[position:])
    return "".join(parts)


def bracket_closers(text: str) -> set[int]:
    """Every unescaped `]` that closes an unescaped `[` of the same paragraph.

    One pass with a stack of open brackets, emptied at each blank line.
    """
    blank_starts = blank_line_starts(text)
    next_blank = 0
    openers: list[int] = []
    closers: set[int] = set()
    for bracket in BRACKET.finditer(text):
        position = bracket.start()
        token = bracket.group(0)
        if token[0] == "\\":
            continue
        while next_blank < len(blank_starts) and blank_starts[next_blank] <= position:
            openers.clear()
            next_blank += 1
        if token == "[":
            openers.append(position)
        elif openers:
            openers.pop()
            closers.add(position)
    return closers


def skip_space(text: str, i: int) -> int:
    """Past spaces and tabs, and at most one line break."""
    newline_seen = False
    while i < len(text) and text[i] in " \t\n":
        if text[i] == "\n":
            if newline_seen:
                break
            newline_seen = True
        i += 1
    return i


class DestinationScanner:
    """Reads inline link destinations and titles; every stop is a lookup.

    Where a destination or a title ends depends only on the next unescaped character of
    a few kinds, and for a bare destination on the parenthesis depth, so those positions
    are indexed once per file instead of scanned again from every `](`. A scan always
    starts after a character that is not a backslash, so which characters a backslash
    escapes is the same for every scan.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        escaped = {run.end() for run in BACKSLASH_RUN.finditer(text) if len(run.group(0)) % 2}

        def unescaped(pattern: re.Pattern[str]) -> list[int]:
            return [position for position in positions(pattern, text) if position not in escaped]

        self.spaces = unescaped(DESTINATION_SPACE)
        self.angle_stops = unescaped(ANGLE_STOP)
        self.title_closers = {opener: unescaped(re.compile(re.escape(closer))) for opener, closer in TITLE_CLOSERS.items()}
        # The parenthesis depth before each unescaped parenthesis, counted from the start
        # of the text, and the closing ones by the depth they close from.
        self.parentheses: list[int] = []
        self.depths: list[int] = []
        self.closing_at: dict[int, list[int]] = {}
        depth = 0
        for position in unescaped(PARENTHESIS):
            self.parentheses.append(position)
            self.depths.append(depth)
            if text[position] == "(":
                depth += 1
            else:
                self.closing_at.setdefault(depth, []).append(position)
                depth -= 1
        self.final_depth = depth

    def depth_before(self, position: int) -> int:
        index = bisect.bisect_left(self.parentheses, position)
        return self.depths[index] if index < len(self.depths) else self.final_depth

    def title_end(self, start: int) -> int | None:
        """Past a link title starting at start, or None when it is not closed."""
        close = first_from(self.title_closers[self.text[start]], start + 1)
        return None if close is None else close + 1

    def bare_end(self, start: int) -> int | None:
        """Where a destination without angle brackets ends: the first unescaped space or
        control character, or the `)` that would close one more parenthesis than it
        opened; None when its parentheses do not balance."""
        length = len(self.text)
        level = self.depth_before(start)
        space = first_from(self.spaces, start)
        close = first_from(self.closing_at.get(level, []), start)
        end = min(length if space is None else space, length if close is None else close)
        if end < length and self.text[end] == ")":
            return end
        return end if self.depth_before(end) == level else None

    def destination(self, start: int) -> tuple[int, str] | None:
        """The offset and raw destination of the inline link whose `(` ends at start."""
        text = self.text
        length = len(text)
        i = skip_space(text, start)
        if i < length and text[i] == "<":
            j = first_from(self.angle_stops, i + 1)
            if j is None or text[j] != ">":
                return None
            offset, raw, after = i + 1, text[i + 1 : j], j + 1
        else:
            j = self.bare_end(i)
            if j is None:
                return None
            offset, raw, after = i, text[i:j], j
        k = skip_space(text, after)
        if k < length and k > after and text[k] in TITLE_CLOSERS:
            end = self.title_end(k)
            if end is None:
                return None
            k = skip_space(text, end)
        if k < length and text[k] == ")":
            return offset, raw
        return None


def link_targets(text: str) -> list[tuple[int, str]]:
    """(line, raw target) of every inline link, image and reference definition."""
    unfenced = "\n".join(mask_fences(text.split("\n")))
    masked = blank_regions(unfenced, inline_regions(unfenced), " ")
    line_starts = [0] + [m.end() for m in re.finditer("\n", masked)]
    closers = bracket_closers(masked)
    destinations = DestinationScanner(masked)
    found: list[tuple[int, str]] = []
    for opening in INLINE_OPEN.finditer(masked):
        if opening.start() not in closers:
            continue
        destination = destinations.destination(opening.end())
        if destination is not None:
            found.append(destination)
    for definition in REFERENCE_DEFINITION.finditer(masked):
        group = "angle" if definition.group("angle") is not None else "bare"
        found.append((definition.start(group), definition.group(group)))
    return [(bisect.bisect_right(line_starts, offset), raw) for offset, raw in found]


# ---- Anchors


def positions(pattern: re.Pattern[str], text: str) -> list[int]:
    return [match.start() for match in pattern.finditer(text)]


def first_from(found: list[int], start: int) -> int | None:
    """The first of the sorted positions at or after start, or None."""
    index = bisect.bisect_left(found, start)
    return found[index] if index < len(found) else None


def strip_bracketed(text: str, opener: re.Pattern[str], keep_label: bool) -> str:
    """The text with each `<opener>label](destination)` or `<opener>label][reference]`
    replaced by its label, or removed."""
    brackets = positions(CLOSING_BRACKET, text)
    parentheses = positions(CLOSING_PARENTHESIS, text)
    parts: list[str] = []
    position = search = 0
    while (start := opener.search(text, search)) is not None:
        label_end = first_from(brackets, start.end())
        if label_end is None:
            break
        follower = text[label_end + 1 : label_end + 2]
        closers = parentheses if follower == "(" else brackets if follower == "[" else []
        end = first_from(closers, label_end + 2)
        if end is None:
            search = start.start() + 1
            continue
        parts.append(text[position : start.start()])
        if keep_label:
            parts.append(text[start.end() : label_end])
        position = search = end + 1
    parts.append(text[position:])
    return "".join(parts)


def strip_underscore_emphasis(text: str) -> str:
    """The text with each `_x_`, `__x__` or `___x___` replaced by what it emphasises."""
    closers = {size: positions(pattern, text) for size, pattern in EMPHASIS_CLOSE.items()}
    line_breaks = positions(LINE_BREAK, text)
    parts: list[str] = []
    position = search = 0
    while (opening := EMPHASIS_OPEN.search(text, search)) is not None:
        size = len(opening.group(1))
        body = opening.end()
        close = first_from(closers[size], body + 1)
        line_end = first_from(line_breaks, body)
        if close is None or (line_end is not None and line_end < close):
            search = opening.start() + 1
            continue
        parts.append(text[position : opening.start()])
        parts.append(text[body:close])
        position = search = close + size
    parts.append(text[position:])
    return "".join(parts)


def strip_markup(text: str) -> str:
    text = strip_bracketed(text, HEADING_IMAGE_OPEN, keep_label=False)
    text = strip_bracketed(text, HEADING_LINK_OPEN, keep_label=True)
    text = HTML_TAG.sub("", text)
    text = strip_underscore_emphasis(text)
    text = ESCAPED_PUNCTUATION.sub(r"\1", text)
    return html.unescape(text)


def plain_heading(text: str) -> str:
    """The text a reader sees in a heading: code kept, other inline markup removed."""
    parts: list[str] = []
    position = 0
    for span in InlineScanner(text).regions():
        if not span.code:
            continue
        parts.append(strip_markup(text[position : span.start]))
        code = text[span.start + span.ticks : span.end - span.ticks]
        if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip():
            code = code[1:-1]
        parts.append(code)
        position = span.end
    parts.append(strip_markup(text[position:]))
    return "".join(parts)


def keeps(char: str) -> bool:
    """Characters GitHub keeps in an anchor: letters, marks, digits, connectors, - and space."""
    if char in " -":
        return True
    category = unicodedata.category(char)
    return category[0] in "LM" or category in ("Nd", "Nl", "Pc")


def slug(heading: str) -> str:
    lowered = plain_heading(heading).lower()
    return "".join(char for char in lowered if keeps(char)).replace(" ", "-")


def atx_text(rest: str) -> str:
    """An ATX heading's text without trailing blanks and its closing `#` sequence.

    The closing sequence counts only when a space or tab precedes it, or when it is the
    whole text: `# foo #` is `foo`, `# foo#` is `foo#`, `# #` is empty.
    """
    text = rest.rstrip(" \t")
    without_closing = text.rstrip("#")
    if len(without_closing) < len(text) and (not without_closing or without_closing[-1] in " \t"):
        return without_closing.rstrip(" \t")
    return text


def content_start(line: str) -> int:
    """Where a line's content starts once its block-quote and list item markers are skipped."""
    position = 0
    while marker := CONTAINER_MARKER.match(line, position):
        position = marker.end()
    return position


def heading_texts(lines: list[str]) -> list[str]:
    """ATX and setext heading texts, in order, from lines whose fences are blanked."""
    headings: list[str] = []
    paragraph: list[str] = []
    for line in lines:
        if not line.strip():
            paragraph = []
            continue
        atx = ATX_HEADING.match(line, content_start(line))
        if atx:
            headings.append(atx_text(atx.group(2) or ""))
            paragraph = []
            continue
        underline = SETEXT_UNDERLINE.match(line)
        if underline and paragraph:
            headings.append("\n".join(part.strip() for part in paragraph))
            paragraph = []
            continue
        if underline and underline.group(1)[0] == "-":
            continue
        paragraph.append(line)
    return headings


def anchors_of(text: str) -> set[str]:
    unfenced = "\n".join(mask_fences(text.split("\n")))
    regions = inline_regions(unfenced)
    comments = [region for region in regions if not region.code]
    anchors: set[str] = set()
    # GitHub's slugger: a repeat takes the next free `-<n>`, counted per base slug and
    # skipping every slug already emitted, so `A`, `a`, `a-1` give `a`, `a-1`, `a-1-1`.
    occurrences: dict[str, int] = {}
    for heading in heading_texts(blank_regions(unfenced, comments, "").split("\n")):
        base = slug(heading)
        candidate = base
        while candidate in occurrences:
            occurrences[base] += 1
            candidate = f"{base}-{occurrences[base]}"
        occurrences[candidate] = 0
        anchors.add(candidate)
    for tag in OPEN_TAG.finditer(blank_regions(unfenced, regions, " ")):
        for attribute in ANCHOR_ATTRIBUTE.finditer(tag.group(0)):
            value = attribute.group(1) if attribute.group(1) is not None else attribute.group(2)
            anchors.add(value.lower())
    return anchors


# ---- Checking


@dataclass
class Repository:
    root: str
    known: set[str]
    given: set[str]
    directories: set[str] = field(init=False)
    checkouts: set[str] = field(init=False)
    not_checked_out: set[str] = field(init=False)
    gone: set[str] = field(init=False)
    gone_parents: set[str] = field(init=False)
    unchecked: set[str] = field(default_factory=set)
    texts: dict[str, str] = field(default_factory=dict)
    anchors: dict[str, set[str]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.directories = directories_of(self.known)
        # A known path that is a directory is a submodule, a nested repository or a
        # symbolic link to a directory: git lists none of the files inside it. An empty
        # one that is not a link is a submodule nobody checked out: what it holds is
        # unknown here.
        self.checkouts = {path for path in self.known if os.path.isdir(os.path.join(self.root, path))}
        self.not_checked_out = {
            path
            for path in self.checkouts
            if not os.path.islink(os.path.join(self.root, path)) and not os.listdir(os.path.join(self.root, path))
        }
        # A given path no longer on disk was moved or deleted, maybe with the directory
        # that held it, or it was a directory itself.
        self.gone = {path for path in self.given if not os.path.lexists(os.path.join(self.root, path))}
        self.gone_parents = directories_of(self.gone) - {""}

    def concerns(self, target: str) -> bool:
        """Whether a link to target is a link to a given path, or to what was under or above a gone one."""
        if target in self.given or target in self.gone_parents:
            return True
        parent = posixpath.dirname(target)
        while parent:
            if parent in self.gone:
                return True
            parent = posixpath.dirname(parent)
        return False

    def text(self, path: str) -> str | None:
        """The file's text, or None when it cannot be read (recorded in failures)."""
        if path in self.failures:
            return None
        if path not in self.texts:
            try:
                with open(os.path.join(self.root, path), encoding="utf-8-sig", errors="replace") as handle:
                    self.texts[path] = handle.read()
            except OSError as error:
                self.failures[path] = error.strerror or type(error).__name__
                return None
        return self.texts[path]

    def anchors_in(self, path: str) -> set[str] | None:
        if path not in self.anchors:
            text = self.text(path)
            if text is None:
                return None
            self.anchors[path] = anchors_of(text)
        return self.anchors[path]

    def listed(self, target: str) -> bool:
        """Whether git lists the target, a directory holding what it lists, or a path in a checkout."""
        if target in self.known or target in self.directories:
            return True
        parent = posixpath.dirname(target)
        while parent:
            if parent in self.not_checked_out:
                self.unchecked.add(parent)
                return True
            if parent in self.checkouts:
                return os.path.exists(os.path.join(self.root, target))
            parent = posixpath.dirname(parent)
        return False

    def readers(self) -> list[str]:
        """Markdown files to read for links: the ones git lists, and the given ones."""
        candidates = {path for path in self.known | self.given if is_markdown(path)}
        return sorted(
            path
            for path in candidates
            if os.path.isfile(os.path.join(self.root, path)) and inside(self.root, path)
        )

    def status(self, source: str, target: str, fragment: str) -> str | None:
        """The kind of breakage of a link to target (``source`` for a same-file link)."""
        path = os.path.join(self.root, target)
        if target != source and not self.listed(target):
            return IGNORED if os.path.exists(path) else MISSING_FILE
        if not inside(self.root, target):
            return OUTSIDE
        if not fragment or not is_markdown(target) or not os.path.isfile(path):
            return None
        wanted = fragment.lower()
        if wanted == TOP_FRAGMENT:
            return None
        anchors = self.anchors_in(target)
        if anchors is None or wanted in anchors:
            return None
        return MISSING_ANCHOR


def split_target(raw: str) -> tuple[str, str] | None:
    """The decoded path and fragment of a link target, or None when it is not checked."""
    target = ESCAPED_PUNCTUATION.sub(r"\1", raw)
    if target.startswith("//") or SCHEME.match(target):
        return None
    path, _, fragment = target.partition("#")
    path = path.partition("?")[0]
    return unquote(path, errors="replace"), unquote(fragment, errors="replace")


def resolve(source: str, path: str) -> str | None:
    """The repository-relative path a link points at, or None when it leaves the repository."""
    if not path:
        return source
    joined = path.lstrip("/") if path.startswith("/") else posixpath.join(posixpath.dirname(source), path)
    normal = posixpath.normpath(joined) if joined else "."
    if normal == ".." or normal.startswith("../"):
        return None
    return "" if normal == "." else normal


def broken_links(repository: Repository) -> set[tuple[str, int, str, str]]:
    found: set[tuple[str, int, str, str]] = set()
    for source in repository.readers():
        source_given = source in repository.given
        text = repository.text(source)
        if text is None:
            continue
        for line, raw in link_targets(text):
            parts = split_target(raw)
            if parts is None:
                continue
            path, fragment = parts
            target = resolve(source, path)
            if target is None:
                if source_given:
                    found.add((source, line, OUTSIDE, raw))
                continue
            if not source_given and not repository.concerns(target):
                continue
            kind = repository.status(source, target, fragment)
            if kind is not None:
                found.add((source, line, kind, raw))
    return found


def main(arguments: list[str]) -> int:
    if not arguments:
        usage("no file given")
    for argument in arguments:
        if argument.startswith("-"):
            usage(f"unknown option: {argument}")
    cwd = os.getcwd()
    root = repository_root(cwd)
    given = {given_path(argument, cwd, root) for argument in arguments}
    repository = Repository(root=root, known=known_files(root), given=given)
    found = broken_links(repository)
    report(found)
    for path in sorted(repository.unchecked):
        complain(f"not checked out, links into it not checked: {path}")
    for path, reason in sorted(repository.failures.items()):
        complain(f"cannot read {path}: {reason}")
    complain(f"{len(found)} broken link{'' if len(found) == 1 else 's'}")
    if repository.failures:
        return INCOMPLETE
    return 1 if found else 0


def report(found: set[tuple[str, int, str, str]]) -> None:
    """Print the broken links; a reader that stops early (`| head`) is not an error."""
    try:
        for source, line, kind, raw in sorted(found):
            print(f"{printable(source)}:{line}: {kind}: {printable(raw)}")
        sys.stdout.flush()
    except BrokenPipeError:
        # Point stdout at the null device so the flush at exit does not fail again.
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, sys.stdout.fileno())
        os.close(null)


if __name__ == "__main__":
    # A character the terminal's encoding lacks is printed as an escape, never an error.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    sys.exit(main(sys.argv[1:]))
