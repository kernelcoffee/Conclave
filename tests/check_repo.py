#!/usr/bin/env python3
"""Repository consistency checks.

    python3 -I tests/check_repo.py [--base <git-ref>]

- every JSON file parses;
- the profile template validates against the profile schema (needs `jsonschema`);
- every stack listed in the schema enum has a skills/stack-<name>/SKILL.md, and back;
- plugin.json and marketplace.json carry the same version;
- the plan template opens with the Analysis (Request, Current state, Constraints,
  Unknowns) before the Functional spec, keeps no Current state in the Technical spec, and
  starts Steps with the analysis step, before `plan`; the check is first run on known-bad
  variants so a check that rejects nothing fails too;
- the lead, the continue skill and the plan skill name the analysis step, the fixed T3
  line and the step's outcome marks verbatim, and the lead puts the analysis checkpoint
  before the approval gate;
- the replaced step wording (`analysis confirmed by the user`, the n/a mark) appears in no
  file that describes the step; the Proposed model placeholder points at the Current state
  diagram under Analysis; the template and the lead name the same Status values;
- with --base: if anything under plugins/ changed since <ref>, the version changed too,
  because installs from git are cached by version and `claude plugin update` does
  nothing for an unchanged version.
Exit 1 on any failure.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "conclave"
errors = []


def fail(msg):
    errors.append(msg)
    print(f"FAIL {msg}")


def ok(msg):
    print(f"ok   {msg}")


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        fail(f"{path.relative_to(ROOT)}: {e}")
        return None


tracked = subprocess.run(["git", "ls-files", "*.json"], cwd=ROOT, capture_output=True, text=True).stdout.split()
for f in tracked:
    load(ROOT / f)
ok(f"{len(tracked)} JSON files parse") if not errors else None

schema = load(PLUGIN / "schemas" / "conclave.schema.json")
template = load(PLUGIN / "templates" / "conclave.json")
try:
    import jsonschema

    jsonschema.validate(template, schema)
    ok("template validates against the schema")
except ImportError:
    fail("jsonschema is not installed (pip install jsonschema)")
except jsonschema.ValidationError as e:
    fail(f"template does not validate: {e.message} at {list(e.absolute_path)}")

enum = set(schema["properties"]["components"]["items"]["properties"]["stacks"]["items"]["enum"])
packs = {p.parent.name.removeprefix("stack-") for p in (PLUGIN / "skills").glob("stack-*/SKILL.md")}
if enum == packs:
    ok(f"stack enum matches the {len(packs)} stack packs")
else:
    fail(f"stack enum and packs differ: only in enum {sorted(enum - packs)}, only as packs {sorted(packs - enum)}")

plugin_v = load(PLUGIN / ".claude-plugin" / "plugin.json")["version"]
market = load(ROOT / ".claude-plugin" / "marketplace.json")
market_v = next(p.get("version") for p in market["plugins"] if p["name"] == "conclave")
if plugin_v == market_v:
    ok(f"version {plugin_v} in plugin.json and marketplace.json")
else:
    fail(f"version mismatch: plugin.json {plugin_v}, marketplace.json {market_v}")

ANALYSIS_SUBSECTIONS = ["### Request", "### Current state", "### Constraints", "### Unknowns"]
ANALYSIS_STEP = "- [ ] analysis checkpoint"
PLAN_STEP_PREFIX = "- [ ] plan"


def section(lines, heading):
    """The lines under a `## ` heading, up to the next `## ` heading; None when absent."""
    if heading not in lines:
        return None
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def plan_template_problems(text):
    """Every way the plan template breaks the Analysis layout, one message each."""
    lines = [line.rstrip() for line in text.splitlines()]
    problems = []

    if "## Analysis" not in lines:
        problems.append("no `## Analysis` section")
    elif "## Functional spec" not in lines:
        problems.append("no `## Functional spec` section")
    elif lines.index("## Analysis") > lines.index("## Functional spec"):
        problems.append("`## Analysis` comes after `## Functional spec`")

    analysis = section(lines, "## Analysis")
    if analysis is not None:
        found = [line for line in analysis if line in ANALYSIS_SUBSECTIONS]
        missing = [s for s in ANALYSIS_SUBSECTIONS if s not in found]
        if missing:
            problems.append(f"`## Analysis` lacks {', '.join(f'`{s}`' for s in missing)}")
        elif found != ANALYSIS_SUBSECTIONS:
            problems.append(f"`## Analysis` subsections out of order: {found}, expected {ANALYSIS_SUBSECTIONS}")

    if "## Technical spec" not in lines:
        problems.append("no `## Technical spec` section")
    elif "### Current state" in lines[lines.index("## Technical spec"):]:
        problems.append("`### Current state` still appears after `## Technical spec`")

    steps = section(lines, "## Steps")
    if steps is None:
        problems.append("no `## Steps` section")
    else:
        steps = [line for line in steps if line.strip()]
        plan_at = next((i for i, line in enumerate(steps) if line.startswith(PLAN_STEP_PREFIX)), None)
        if ANALYSIS_STEP not in steps:
            problems.append(f"Steps lacks `{ANALYSIS_STEP}`")
        elif plan_at is None:
            problems.append(f"Steps lacks the `{PLAN_STEP_PREFIX}` step")
        elif steps.index(ANALYSIS_STEP) > plan_at:
            problems.append(f"`{ANALYSIS_STEP}` comes after the `{PLAN_STEP_PREFIX}` step")
        elif steps[0] != ANALYSIS_STEP:
            problems.append(f"Steps does not start with `{ANALYSIS_STEP}`, it starts with `{steps[0]}`")
    return problems


GOOD_PLAN = "\n".join(["# t", "## Analysis", *ANALYSIS_SUBSECTIONS, "## Functional spec", "## Technical spec",
                       "### Proposed model", "## Steps", ANALYSIS_STEP, f"{PLAN_STEP_PREFIX} (<n> agents)"])
BAD_PLANS = {
    "`## Analysis` missing": (GOOD_PLAN.replace("## Analysis\n", ""), "no `## Analysis`"),
    "`## Analysis` after `## Functional spec`": (
        GOOD_PLAN.replace("## Functional spec\n", "").replace("# t\n", "# t\n## Functional spec\n"),
        "comes after `## Functional spec`"),
    "a subsection missing": (GOOD_PLAN.replace("### Constraints\n", ""), "lacks `### Constraints`"),
    "subsections out of order": (
        GOOD_PLAN.replace("### Request", "@").replace("### Unknowns", "### Request").replace("@", "### Unknowns"),
        "out of order"),
    "`### Current state` under `## Technical spec`": (
        GOOD_PLAN.replace("### Proposed model", "### Current state\n### Proposed model"),
        "still appears after `## Technical spec`"),
    "analysis step missing": (GOOD_PLAN.replace(ANALYSIS_STEP + "\n", ""), f"lacks `{ANALYSIS_STEP}`"),
    "analysis step after plan": (
        GOOD_PLAN.replace(ANALYSIS_STEP + "\n", "") + "\n" + ANALYSIS_STEP, "comes after the `- [ ] plan` step"),
    "analysis step not first": (
        GOOD_PLAN.replace(ANALYSIS_STEP + "\n", "- [ ] spec\n" + ANALYSIS_STEP + "\n"),
        "does not start with"),
    # A subsection that exists but sits outside the Analysis (here under the Functional
    # spec) does not count: the check reads only the lines up to the next `## ` heading.
    "a subsection moved out of the Analysis": (
        GOOD_PLAN.replace("### Request\n", "").replace("## Functional spec\n", "## Functional spec\n### Request\n"),
        "lacks `### Request`"),
}

errors_before_template = len(errors)
if plan_template_problems(GOOD_PLAN):
    fail(f"plan template check rejects a valid layout: {plan_template_problems(GOOD_PLAN)}")
for case, (text, expected) in BAD_PLANS.items():
    got = plan_template_problems(text)
    if len(got) != 1 or expected not in got[0]:
        fail(f"plan template check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in plan_template_problems((PLUGIN / "templates" / "plan.md").read_text()):
    fail(f"templates/plan.md: {problem}")
if len(errors) == errors_before_template:
    ok(f"plan template opens with the Analysis and starts Steps with its step ({len(BAD_PLANS)} bad layouts rejected)")

# The prompts route on the literal text of the template: /conclave:continue resumes at the
# analysis checkpoint by finding the step `analysis checkpoint` unticked, the
# lead and /conclave:plan both write the same fixed T3 line, and /conclave:plan marks the
# step as skipped for a plan-only run so continue sends its document to the approval gate. A
# rename in one file and not the others breaks resume silently, so the literals are
# checked across the files.
errors_before_literals = len(errors)
step_text = ANALYSIS_STEP.removeprefix("- [ ] ")
t3_line = "(no separate analysis at this tier: see the briefs)"
confirmed_mark = f"{step_text}: confirmed by the user"
t3_mark = f"{step_text}: skipped, no separate analysis at T3"
plan_only_mark = f"{step_text}: skipped, plan-only run"
lead_text = (PLUGIN / "agents" / "lead.md").read_text()
for rel, needles in {
    "agents/lead.md": [f"`{step_text}`", t3_line, confirmed_mark, t3_mark, plan_only_mark, "**The analysis checkpoint.**"],
    "skills/continue/SKILL.md": [f"`{step_text}`", plan_only_mark],
    "skills/plan/SKILL.md": [t3_line, plan_only_mark, "The analysis checkpoint"],
}.items():
    text = (PLUGIN / rel).read_text()
    for needle in needles:
        if needle not in text:
            fail(f"{rel}: does not name {needle!r}, which the template and the other prompts use")
if "**The analysis checkpoint.**" in lead_text and "**The approval gate.**" in lead_text:
    if lead_text.index("**The analysis checkpoint.**") > lead_text.index("**The approval gate.**"):
        fail("agents/lead.md: the analysis checkpoint paragraph comes after the approval gate")
if len(errors) == errors_before_literals:
    ok("lead, continue and plan name the analysis step, the T3 line and the outcome marks verbatim; the checkpoint precedes the approval gate")

# The step was first named `analysis confirmed by the user` and marked `(n/a: ...)` when
# skipped; the user replaced both with the outcome after a colon, so a skipped checkpoint
# never reads as confirmed. Neither wording may come back in a file that describes the step.
errors_before_old_wording = len(errors)
old_step = "analysis " + "confirmed by the user"
old_mark = "(" + "n/a"
for path in [PLUGIN / "templates" / "plan.md", PLUGIN / "agents" / "lead.md",
             PLUGIN / "skills" / "plan" / "SKILL.md", PLUGIN / "skills" / "continue" / "SKILL.md",
             PLUGIN / "skills" / "writing-docs" / "SKILL.md", ROOT / "docs" / "design.md", ROOT / "README.md"]:
    text = path.read_text()
    for old in (old_step, old_mark):
        if old in text:
            fail(f"{path.relative_to(ROOT)}: still uses the replaced wording {old!r}; "
                 f"write `{ANALYSIS_STEP.removeprefix('- [ ] ')}: <outcome>` instead")
if len(errors) == errors_before_old_wording:
    ok("no file uses the replaced analysis step wording or its n/a mark")

# Current state moved from the Technical spec into the Analysis; the Proposed model
# placeholder must still point at its diagram there, or the two diagrams stop being drawn
# side by side.
plan_lines = [line.rstrip() for line in (PLUGIN / "templates" / "plan.md").read_text().splitlines()]
technical = section(plan_lines, "## Technical spec") or []
if "### Proposed model" not in technical:
    fail("templates/plan.md: no `### Proposed model` under `## Technical spec`")
else:
    start = technical.index("### Proposed model") + 1
    end = next((i for i in range(start, len(technical)) if technical[i].startswith("### ")), len(technical))
    proposed = " ".join(technical[start:end])
    if "Current state" not in proposed or "Analysis" not in proposed:
        fail("templates/plan.md: the Proposed model placeholder no longer points at the Current state diagram under Analysis")
    else:
        ok("the Proposed model placeholder points at the Current state diagram under Analysis")

# No Status value is added by the analysis checkpoint: the template's Status list and the
# order the lead moves Status through must name the same values.
status_line = next((line for line in plan_lines if line.startswith("- **Status:** <")), None)
lead_status = lead_text.split("move Status along (", 1)
if status_line is None or len(lead_status) != 2:
    fail("cannot find the Status list in templates/plan.md or the Status order in agents/lead.md")
else:
    template_status = {s.strip() for s in status_line.split("<", 1)[1].rstrip(">").split("|")}
    lead_values = set(lead_status[1].split(")", 1)[0].split("`")[1::2])
    if template_status == lead_values:
        ok(f"templates/plan.md and agents/lead.md name the same {len(template_status)} Status values")
    else:
        fail(f"Status values differ: only in templates/plan.md {sorted(template_status - lead_values)}, "
             f"only in agents/lead.md {sorted(lead_values - template_status)}")

if "--base" in sys.argv:
    base = sys.argv[sys.argv.index("--base") + 1]
    changed = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD", "--", "plugins/"], cwd=ROOT, capture_output=True, text=True)
    if changed.returncode != 0:
        fail(f"cannot diff against {base}: {changed.stderr.strip()}")
    elif changed.stdout.strip():
        old = subprocess.run(["git", "show", f"{base}:plugins/conclave/.claude-plugin/plugin.json"], cwd=ROOT, capture_output=True, text=True)
        old_v = json.loads(old.stdout)["version"] if old.returncode == 0 else None
        if old_v == plugin_v:
            fail(f"plugins/ changed since {base} but the version is still {plugin_v}; bump it in plugin.json and marketplace.json")
        else:
            ok(f"plugins/ changed and the version moved {old_v} -> {plugin_v}")
    else:
        ok(f"plugins/ unchanged since {base}")

sys.exit(1 if errors else 0)
