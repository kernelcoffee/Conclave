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
- the lead, the continue skill and the plan skill name the analysis step, its confirmed
  mark, `state.analysis` and the analysis stage verbatim; the lead and the plan skill no
  longer write the retired fixed T3 line, the two `skipped` marks or
  `design_study.current_state`; the lead puts the analysis checkpoint before the approval
  gate;
- the ANALYSIS return shape names the same fields in both workflow scripts and in the
  architect's "What you return", with the same four required, and DESIGN_STUDY no longer
  carries `current_state`; the check is first run on known-bad variants as well;
- the replaced step wording (`analysis confirmed by the user`, the n/a mark) appears in no
  file that describes the step; the Proposed model placeholder points at the Current state
  diagram under Analysis; the template and the lead name the same Status values;
- plan documents stay local by default: the schema declares `docs.commit_plans` as a boolean
  with default `false` and a description, the lead names `commit_plans`, and no statement that
  made a plan a committed file remains in the lead, the plan template, the init skill or the
  schema; the check is first run on known-bad variants as well;
- lead.md step 2 adds both ignore lines, ignores only plan-named files in a plans directory
  that tracks other documents, gives the one-time notice, never untracks, and keeps
  `.gitignore` in `exec.lead_files` while it differs from the base; its Commit proposal puts
  the lead's own files in a slice of their own and the plan document in none by default;
- the lead lets a request in the task commit the plan without changing the profile and sets
  Status `done` in the local document; /conclave:plan step 3 names both ignore lines;
  /conclave:continue needs the plan document on this machine and ties a run from another
  machine to committed plans; /conclave:init says plans are not committed by default and does
  not ask about the opt-in; the profile template leaves `docs.commit_plans` out; the check is
  first run on known-bad variants as well;
- the schema declares `docs.diataxis` as a boolean with a description and no default, and the
  profile template leaves it out; the writing pack has a `## Diátaxis` section naming the four
  directories, keeps "Document kinds" and the Mermaid patterns, and limits the keep-the-structure
  rule to projects that do not use Diátaxis; the docs-writer and the lead name `docs.diataxis`
  without naming the directories, the docs-writer points to the pack and reports unfixable links
  under `gaps`, the lead asks with AskUserQuestion, never when the key is present, and names
  `exec.lead_files`; /conclave:init asks the question and reports it open on an existing profile;
  the check is first run on known-bad variants as well;
- a profile validates with `docs.diataxis` true or false and not with any other type; the pack
  gives each kind its reader, contents and omissions, tells the kinds apart, creates a missing
  directory with an index file, leaves a pointer, moves nothing else, fixes links inside
  `docs.paths` and lists the others with file and line, and makes misfiled text an audit
  finding; the docs-writer keeps its voice rule, says Diátaxis does not apply when the key is
  `false` or absent, and carries the link rule and the audit finding; the lead and init
  recommend yes with each option's consequence, the lead at T1 or above and saying what it
  wrote; neither agent restates a rule only the pack states; the check is first run on
  known-bad variants as well;
- the link check script `bin/docs-link-check.py` exists, is executable on disk and, once
  tracked, in git; the docs-writer has Bash and a `## Checking links` section, after "Where
  the text goes", that runs the command by its bare name on every file it created, edited,
  moved or deleted (old paths included), says it reports links in those files and links to
  them, repairs links in files under `docs.paths` and runs it again, lists under `gaps` the
  links in files it may not edit and those it cannot repair, keeps to files, passes a moved
  or deleted directory as the files it held, says what each exit code means and that a
  failed run is not a pass, handles the lines printed with exit code 3 and lists each file
  the command could not read under `gaps` (a correction in audit mode), repairs an `ignored by git` or `outside the repository` link only
  by pointing it at a tracked file, runs it in audit mode and maps each line onto a
  correction, and falls back by hand when the command is not found, the auditor reporting
  corrections since it has no `gaps`; the check is first run on known-bad variants as well;
- lead.md states its standing rules once, in one `## Rules` section before `## Before
  anything`: twelve numbered items with the expected bold titles in order, and no retired
  passage that stated rules elsewhere; each rule, the T2 checkpoint stop, the preflight's
  branch bullet, the approval gate, the Commit proposal with its separate push question and
  the plan template's Unknowns placeholder carry what the acceptance names, and neither the
  rules nor the Commit proposal name a hosting service; the first column of the README's
  `## Rules` table holds the same titles in the same order; the checks are first run on
  known-bad variants as well;
- around those rules: the line that says how to read their order opens the section, no sentence
  of a rule is restated word for word below it, every guardrail a rule or the README's
  "Enforced by" column cites is a rule of guard.py, the README row of a rule names each
  guardrail the rule cites and no row leaves "Enforced by" empty, and the continue skill's T2
  resume prints each Unknown with what would settle it and the recommendation; the checks are
  first run on known-bad variants as well;
- with --base: if anything under plugins/ changed since <ref>, the version changed too,
  because installs from git are cached by version and `claude plugin update` does
  nothing for an unchanged version.
Exit 1 on any failure.
"""
import json
import os
import re
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

# The prompts route on the literal text of the template and of the run state:
# /conclave:continue resumes at the analysis checkpoint by finding the step
# `analysis checkpoint` unticked and the run JSON at `stage_done: "analysis"`, the lead and
# /conclave:plan both mark the step with the same confirmed outcome, and all three copy the
# Analysis section into `state.analysis` before the plan stage. /conclave:plan saves its run at
# `stage_done: "plan-team"` with a state that holds the plan, and the lead and /conclave:continue
# route an approved plan-only run from that value through the dev-team plan stage (design duel
# and consults) to the build. A rename in one file and not the others breaks resume silently, so the literals are checked across the files. Since
# the architect writes the Analysis at T3 and in plan-only runs, the fixed T3 line, the two
# `skipped` marks and the design study's old `current_state` are no longer written: the two
# files that write the document must not carry them (continue still reads older documents).
errors_before_literals = len(errors)
step_text = ANALYSIS_STEP.removeprefix("- [ ] ")
confirmed_mark = f"{step_text}: confirmed by the user"
analysis_stage_done = 'stage_done: "analysis"'
plan_team_stage_done = 'stage_done: "plan-team"'
retired_literals = [
    "(no separate analysis at this tier: see the briefs)",
    f"{step_text}: skipped, no separate analysis at T3",
    f"{step_text}: skipped, plan-only run",
    "design_study.current_state",
]
lead_text = (PLUGIN / "agents" / "lead.md").read_text()
for rel, needles in {
    "agents/lead.md": [f"`{step_text}`", confirmed_mark, "**The analysis checkpoint.**", "`state.analysis`",
                       plan_team_stage_done],
    "skills/continue/SKILL.md": [f"`{step_text}`", "state.analysis", analysis_stage_done, "`plan-team`"],
    "skills/plan/SKILL.md": ["The analysis checkpoint", confirmed_mark, "state.analysis", analysis_stage_done,
                             plan_team_stage_done],
}.items():
    text = (PLUGIN / rel).read_text()
    for needle in needles:
        if needle not in text:
            fail(f"{rel}: does not name {needle!r}, which the template and the other prompts use")
for rel in ["agents/lead.md", "skills/plan/SKILL.md"]:
    text = (PLUGIN / rel).read_text()
    for stale in retired_literals:
        if stale in text:
            fail(f"{rel}: still writes the retired literal {stale!r}; "
                 "the architect's analysis stage fills the Analysis now")
if "**The analysis checkpoint.**" in lead_text and "**The approval gate.**" in lead_text:
    if lead_text.index("**The analysis checkpoint.**") > lead_text.index("**The approval gate.**"):
        fail("agents/lead.md: the analysis checkpoint paragraph comes after the approval gate")
if len(errors) == errors_before_literals:
    ok("lead, continue and plan name the analysis step, its confirmed mark, state.analysis and the analysis and plan-team stages; "
       "no retired T3 literal is written; the checkpoint precedes the approval gate")

# ANALYSIS is a return shape shared by the two planning scripts (the schema of the call
# labelled `analysis`) and the architect's "What you return". Nothing executes a prompt, so
# a field renamed on one side would leave a subsection of every T3 Analysis silently empty.
# The scripts keep a fixed source layout for this check: a line `const ANALYSIS = {`, the
# block ending at the first later line that is exactly `}`, each field as `<name>:`, and the
# last `required: [...]` in the block as the top-level list. DESIGN_STUDY lost
# `current_state` to the analysis and must not regain it.
ANALYSIS_FIELDS = ["request", "current_state", "constraints", "unknowns", "components", "diagrams"]
ANALYSIS_REQUIRED = ANALYSIS_FIELDS[:4]
DESIGN_STUDY_FIELDS = ["problems", "proposed_model", "alternatives", "decisions", "migration", "risks"]
ANALYSIS_LINE = "- In an analysis:"
DESIGN_STUDY_LINE = "- In a design study:"
SHAPE_SCRIPTS = ["dev-team.js", "plan-team.js"]


def js_block(text, opener):
    """The lines from `opener` (a whole line) to the first later line that is exactly `}`."""
    lines = [line.rstrip() for line in text.splitlines()]
    if opener not in lines:
        return None
    start = lines.index(opener)
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == "}"), None)
    return None if end is None else lines[start:end + 1]


def analysis_block_problems(name, block):
    """Every way one script's ANALYSIS block departs from the shared field list."""
    body = "\n".join(block)
    problems = [f"{name}: ANALYSIS does not declare `{field}:`"
                for field in ANALYSIS_FIELDS if not re.search(rf"(?<!\w){field}:", body)]
    lists = re.findall(r"required:\s*\[([^\]]*)\]", body)
    if not lists:
        problems.append(f"{name}: ANALYSIS has no `required: [...]` list")
    else:
        required = re.findall(r"'([^']*)'", lists[-1])
        if sorted(required) != sorted(ANALYSIS_REQUIRED):
            problems.append(f"{name}: ANALYSIS requires {required}, expected exactly {ANALYSIS_REQUIRED}")
    return problems


def return_shape_problems(scripts, architect):
    """Every way the scripts and architect.md disagree on ANALYSIS and DESIGN_STUDY.

    `scripts` maps a script name to its source; `architect` is the text of architect.md.
    """
    problems = []
    valid_blocks = {}
    for name, text in scripts.items():
        block = js_block(text, "const ANALYSIS = {")
        if block is None:
            problems.append(f"{name}: no `const ANALYSIS = {{` block closed by a line `}}`")
        else:
            found = analysis_block_problems(name, block)
            problems.extend(found)
            if not found:
                valid_blocks[name] = block
        study = js_block(text, "const DESIGN_STUDY = {")
        if study is None:
            problems.append(f"{name}: no `const DESIGN_STUDY = {{` block closed by a line `}}`")
        elif "current_state" in "\n".join(study):
            problems.append(f"{name}: DESIGN_STUDY still declares `current_state`, which moved to ANALYSIS")
    if len(valid_blocks) == len(scripts) and len({tuple(b) for b in valid_blocks.values()}) > 1:
        problems.append(f"the ANALYSIS blocks of {', '.join(scripts)} are not identical")

    lines = [line.rstrip() for line in architect.splitlines()]
    returns = section(lines, "## What you return")
    if returns is None:
        problems.append("architect.md: no `## What you return` section")
        return problems
    analysis_line = next((line for line in returns if line.startswith(ANALYSIS_LINE)), None)
    if analysis_line is None:
        problems.append(f"architect.md: no line starting `{ANALYSIS_LINE}` under `## What you return`")
    else:
        problems.extend(f"architect.md: the analysis return line does not name `{field}`"
                        for field in ANALYSIS_FIELDS if f"`{field}`" not in analysis_line)
    study_line = next((line for line in returns if line.startswith(DESIGN_STUDY_LINE)), None)
    if study_line is None:
        problems.append(f"architect.md: no line starting `{DESIGN_STUDY_LINE}` under `## What you return`")
    else:
        if "current_state" in study_line:
            problems.append("architect.md: the design study return line still names `current_state`")
        problems.extend(f"architect.md: the design study return line does not name `{field}`"
                        for field in DESIGN_STUDY_FIELDS if f"`{field}`" not in study_line)
    return problems


GOOD_ANALYSIS_BLOCK = """const ANALYSIS = {
  type: 'object',
  properties: {
    request: { type: 'string' }, current_state: { type: 'string' },
    constraints: strList, unknowns: strList, components: strList,
    diagrams: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, kind: { type: 'string' }, mermaid: { type: 'string' } }, required: ['title', 'mermaid'] } },
  },
  required: ['request', 'current_state', 'constraints', 'unknowns'],
}"""
# `current_state` after the DESIGN_STUDY block (inside ANALYSIS, and in a later line) proves
# the study check reads only its own block.
GOOD_SCRIPT = "\n".join([
    "const DESIGN_STUDY = {", "  properties: { problems: strList, proposed_model: { type: 'string' } },",
    "  required: ['problems', 'proposed_model'],", "}", GOOD_ANALYSIS_BLOCK,
    "const note = 'analysis.current_state reaches the prompt'"])
# A stale design-study line outside `## What you return` proves the line check reads only
# that section.
GOOD_ARCHITECT = "\n".join([
    "## Design study", "- In a design study: `current_state`", "## What you return", "- `summary`: x",
    f"{ANALYSIS_LINE} " + ", ".join(f"`{f}`" for f in ANALYSIS_FIELDS) + " as described above.",
    f"{DESIGN_STUDY_LINE} " + ", ".join(f"`{f}`" for f in DESIGN_STUDY_FIELDS) + " as described above.",
    "", "Your final message is data for the orchestrator."])


def shape_case(dev=GOOD_SCRIPT, plan=GOOD_SCRIPT, architect=GOOD_ARCHITECT):
    return {"dev-team.js": dev, "plan-team.js": plan}, architect


BAD_SHAPES = {
    "a field renamed in dev-team.js": (
        shape_case(dev=GOOD_SCRIPT.replace("unknowns: strList", "open_questions: strList")),
        "dev-team.js: ANALYSIS does not declare `unknowns:`"),
    "a field renamed in plan-team.js": (
        shape_case(plan=GOOD_SCRIPT.replace("request: {", "ask: {")),
        "plan-team.js: ANALYSIS does not declare `request:`"),
    "a field renamed in architect.md": (
        shape_case(architect=GOOD_ARCHITECT.replace("`constraints`", "`limits`")),
        "analysis return line does not name `constraints`"),
    "a fifth name in required": (
        shape_case(dev=GOOD_SCRIPT.replace("'unknowns'],", "'unknowns', 'components'],")),
        "dev-team.js: ANALYSIS requires"),
    "a name missing from required": (
        shape_case(plan=GOOD_SCRIPT.replace("'constraints', 'unknowns'],", "'constraints'],")),
        "plan-team.js: ANALYSIS requires"),
    "no required list in ANALYSIS": (
        shape_case(dev=GOOD_SCRIPT.replace("  required: ['request', 'current_state', 'constraints', 'unknowns'],\n", "")
                   .replace(", required: ['title', 'mermaid']", "")),
        "has no `required: [...]` list"),
    "the ANALYSIS block missing": (
        shape_case(plan=GOOD_SCRIPT.replace("const ANALYSIS = {", "const READING = {")),
        "plan-team.js: no `const ANALYSIS = {` block"),
    "the ANALYSIS blocks differ": (
        shape_case(plan=GOOD_SCRIPT.replace("kind: { type: 'string' }", "kind: strList")),
        "are not identical"),
    "`current_state` left in DESIGN_STUDY": (
        shape_case(dev=GOOD_SCRIPT.replace("properties: { problems:",
                                           "properties: { current_state: { type: 'string' }, problems:")),
        "dev-team.js: DESIGN_STUDY still declares `current_state`"),
    "the DESIGN_STUDY block missing": (
        shape_case(dev=GOOD_SCRIPT.replace("const DESIGN_STUDY = {", "const STUDY = {")),
        "dev-team.js: no `const DESIGN_STUDY = {` block"),
    "the analysis return line missing": (
        shape_case(architect="\n".join(line for line in GOOD_ARCHITECT.splitlines()
                                       if not line.startswith(ANALYSIS_LINE))),
        f"no line starting `{ANALYSIS_LINE}`"),
    "`current_state` left in the design study return line": (
        shape_case(architect=GOOD_ARCHITECT.replace(f"{DESIGN_STUDY_LINE} `problems`",
                                                    f"{DESIGN_STUDY_LINE} `current_state`, `problems`")),
        "design study return line still names `current_state`"),
    "a field dropped from the design study return line": (
        shape_case(architect=GOOD_ARCHITECT.replace("`migration`, ", "")),
        "design study return line does not name `migration`"),
}

errors_before_shapes = len(errors)
if return_shape_problems(*shape_case()):
    fail(f"return shape check rejects a valid layout: {return_shape_problems(*shape_case())}")
for case, ((scripts, architect), expected) in BAD_SHAPES.items():
    got = return_shape_problems(scripts, architect)
    if len(got) != 1 or expected not in got[0]:
        fail(f"return shape check on {case}: expected one problem containing {expected!r}, got {got}")
real_scripts = {name: (PLUGIN / "workflows" / name).read_text() for name in SHAPE_SCRIPTS}
for problem in return_shape_problems(real_scripts, (PLUGIN / "agents" / "architect.md").read_text()):
    fail(problem)
if len(errors) == errors_before_shapes:
    ok(f"ANALYSIS names the same {len(ANALYSIS_FIELDS)} fields in both scripts and architect.md, DESIGN_STUDY has no "
       f"current_state ({len(BAD_SHAPES)} bad layouts rejected)")

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

# /conclave:plan records the triage tier in the run JSON, so a plan-only run is often at T1
# or T2. /conclave:continue picks the first `planning` bullet that matches; if the T2 bullet
# comes first and does not exclude plan-only runs, a paused plan-only run at T2 is resumed by
# the lead writing the specs itself (no pm, no architect, no plan-team) and the build then
# finds no `plan` in state. The plan-only route must win over the T2 route: either the T2
# bullet excludes plan-only runs, or the plan-only bullet comes first. A missing bullet is a
# failure too, so that dropping one does not pass for a correct order.
continue_lines = (PLUGIN / "skills" / "continue" / "SKILL.md").read_text().splitlines()
planning_bullets = [line.strip() for line in continue_lines if line.startswith("   - ")]
t2_bullet = next((i for i, line in enumerate(planning_bullets) if line.startswith("- At T2")), None)
plan_only_bullet = next((i for i, line in enumerate(planning_bullets)
                         if "plan-only run" in line and line.startswith("- At T3")), None)
if t2_bullet is None or plan_only_bullet is None:
    fail("skills/continue/SKILL.md: step 2 lost its `- At T2` or its `- At T3 or in a plan-only run` bullet")
elif t2_bullet < plan_only_bullet and not any(
        word in planning_bullets[t2_bullet] for word in ("plan-only", "plan_only")):
    fail("skills/continue/SKILL.md: the T2 `planning` bullet comes before the plan-only bullet and does not "
         "exclude plan-only runs, so a plan-only run triaged T2 is resumed as a lead-written T2 plan "
         "instead of through plan-team")
else:
    ok("continue routes a plan-only run through plan-team at every tier")

# `exec.proceed` lets every open design-study, pm and architect decision of the relaunched
# stage through without a stop. A needs-human stop that only reports an empty answer (an
# empty analysis inside a plan launch, an empty pm) must therefore be relaunched without it,
# or the plan that follows is written on decisions nobody asked the user. The lead and
# /conclave:plan each state the rule in their needs-human step: `exec.proceed: true` tied to
# `decisions` or `needs_decision` in the context, and the other stops relaunched without it.
def proceed_rule_problems(rel, text, prefix):
    step = next((line for line in text.splitlines() if line.lstrip().startswith(prefix)), None)
    if step is None:
        return [f"{rel}: no needs-human step starting {prefix!r}"]
    missing = [needle for needle in ("`exec.proceed: true`", "`needs_decision`", "without `exec.proceed`")
               if needle not in step]
    if missing:
        return [f"{rel}: the needs-human step does not tie `exec.proceed` to answered decisions "
                f"(missing {', '.join(missing)}), so an empty answer would be relaunched with every open decision let through"]
    return []


errors_before_proceed = len(errors)
unconditional = "- `needs-human`: relaunch the same stage with `exec.decisions` set to the answers, `exec.proceed: true` and the saved `state`."
conditional = ("- `needs-human`: when the context carries `decisions` or `needs_decision`, `exec.proceed: true`; "
               "any other stop is relaunched without `exec.proceed`.")
if not proceed_rule_problems("self-test", unconditional, "- `needs-human`:") \
        or not proceed_rule_problems("self-test", "", "- `needs-human`:") \
        or proceed_rule_problems("self-test", conditional, "- `needs-human`:"):
    fail("proceed_rule_problems self-test: the check does not tell an unconditional `exec.proceed` from a conditional one")
for problem in (proceed_rule_problems("agents/lead.md", lead_text, "- `needs-human`:")
                + proceed_rule_problems("skills/plan/SKILL.md", (PLUGIN / "skills" / "plan" / "SKILL.md").read_text(),
                                        "6. `needs-human`")):
    fail(problem)

# An approved plan-only run whose dev-team plan stage stopped still reads
# `stage_done: "plan-team"`; continue must not ask for the approval again, so the mapping of
# that value depends on Status.
plan_team_mapping = next((line for line in continue_lines if "`plan-team` (" in line), None)
if plan_team_mapping is None or "`approved`" not in plan_team_mapping.split("`plan-team` (", 1)[1].split("`plan` → ", 1)[0]:
    fail("skills/continue/SKILL.md: the `plan-team` mapping of step 2 does not say what an `approved` document "
         "resumes at, so an approved plan-only run is asked for approval again")
if len(errors) == errors_before_proceed:
    ok("lead and plan tie exec.proceed to answered decisions; continue maps plan-team by Status")


# A correction of the analysis travels in `exec.decisions` on the `analysis` relaunch. The
# plan stage reads `exec.decisions` as the user's answers to its own questions and tells the
# design study and the pm to leave their decisions empty, so a correction left in the exec of
# the `plan` launch that follows the checkpoint would quietly thin out the decisions the user
# is asked. Every place that launches `plan` after the checkpoint drops both fields.
def plan_launch_problems(rel, text, prefix):
    line = next((line for line in text.splitlines() if line.lstrip().startswith(prefix)), None)
    if line is None:
        return [f"{rel}: no line starting {prefix!r} that launches `plan` after the analysis checkpoint"]
    missing = [needle for needle in ("without `exec.proceed`", "without `exec.decisions`") if needle not in line]
    if missing:
        return [f"{rel}: the `plan` launch after the analysis checkpoint does not say {' and '.join(missing)}, "
                "so a correction of the analysis reaches the pm and the design study as answers to their questions"]
    return []


errors_before_plan_launch = len(errors)
carried = "- At T3 ... launch `plan`, without `exec.proceed`."
dropped = "- At T3 ... launch `plan` without `exec.proceed` and without `exec.decisions`."
if not plan_launch_problems("self-test", carried, "- At T3") \
        or not plan_launch_problems("self-test", "", "- At T3") \
        or plan_launch_problems("self-test", dropped, "- At T3"):
    fail("plan_launch_problems self-test: the check does not tell a `plan` launch that drops `exec.decisions` "
         "from one that carries it")
continue_text = "\n".join(continue_lines)
for problem in (plan_launch_problems("agents/lead.md", lead_text, "- At T3 the architect writes the Analysis")
                + plan_launch_problems("agents/lead.md", lead_text, "- **T3.**")
                + plan_launch_problems("skills/plan/SKILL.md", (PLUGIN / "skills" / "plan" / "SKILL.md").read_text(),
                                       "5. On confirmation")
                + plan_launch_problems("skills/continue/SKILL.md", continue_text,
                                       "- At T3 or in a plan-only run, when the step is ticked")):
    fail(problem)

# dev-team builds a T2 plan from `exec.brief` only while the state holds no plan; after the
# build, review and finish read `state.briefs`. Continue must send an edited T2 brief into
# `exec.brief` only while there is no plan in the saved state, or the edit never reaches them.
brief_step = next((line for line in continue_lines if line.startswith("3. Re-read the Briefs")), None)
if brief_step is None or "`exec.brief`" not in brief_step or "holds no `plan`" not in brief_step:
    fail("skills/continue/SKILL.md: step 3 does not limit `exec.brief` to a T2 whose saved state holds no `plan`, "
         "so an edited brief after the build never reaches review or finish")
if len(errors) == errors_before_plan_launch:
    ok("the plan launch after the analysis checkpoint drops exec.decisions and exec.proceed; "
       "continue sends a T2 brief to exec.brief only before a plan exists")


# A plan document is the working paper of one task: by default the lead keeps it out of every
# commit and adds the plans directory to .gitignore; `docs.commit_plans: true` opts back in.
# The lead reads the setting by name, so the schema must declare it as an off-by-default
# boolean and lead.md must name it; and none of the statements that made a plan a committed
# file may come back in the files that tell the lead, the template or the profile what to do.
SCHEMA_REL = "schemas/conclave.schema.json"
LEAD_REL = "agents/lead.md"
PLAN_COMMIT_FILES = [LEAD_REL, "templates/plan.md", "skills/init/SKILL.md", SCHEMA_REL]
PLAN_COMMIT_RETIRED = [
    "committed record",
    "it is a committed file",
    "the plan document is in the first",
    "committed with the change",
    "where per-task plan documents are committed",
]


def plan_commit_problems(texts):
    """Every way the files in PLAN_COMMIT_FILES (relative path -> text) undo local plans."""
    problems = []
    try:
        docs = json.loads(texts[SCHEMA_REL])["properties"]["docs"]["properties"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return [f"{SCHEMA_REL}: cannot read `properties.docs.properties` ({e!r})"]
    setting = docs.get("commit_plans")
    if not isinstance(setting, dict):
        problems.append(f"{SCHEMA_REL}: `docs` does not declare `commit_plans`, the opt-in for committing plans")
    elif setting.get("type") != "boolean" or setting.get("default") is not False:
        problems.append(f"{SCHEMA_REL}: `docs.commit_plans` must be a boolean with default `false`, "
                        f"found type {setting.get('type')!r} and default {setting.get('default')!r}")
    elif not str(setting.get("description", "")).strip():
        problems.append(f"{SCHEMA_REL}: `docs.commit_plans` has no description")
    if "commit_plans" not in texts[LEAD_REL]:
        problems.append(f"{LEAD_REL}: does not name `commit_plans`, so the lead never reads the opt-in")
    for rel in PLAN_COMMIT_FILES:
        lowered = texts[rel].lower()
        for stale in PLAN_COMMIT_RETIRED:
            if stale in lowered:
                problems.append(f"{rel}: still says {stale!r}; plan documents are not committed by default")
    return problems


GOOD_PLAN_SCHEMA = json.dumps({"properties": {"docs": {"properties": {
    "plans": {"type": "string", "description": "Directory for per-task plan documents; ignored by git."},
    "commit_plans": {"type": "boolean", "default": False, "description": "Commit plan documents."},
}}}})
GOOD_PLAN_TEXTS = {
    LEAD_REL: "The plan document is not committed unless `profile.docs.commit_plans` is `true`.",
    "templates/plan.md": "(build-safe slices in order; the plan document is in none of them)",
    "skills/init/SKILL.md": "Propose `docs.plans`; plan documents are not committed by default.",
    SCHEMA_REL: GOOD_PLAN_SCHEMA,
}


def plan_case(rel, text):
    return {**GOOD_PLAN_TEXTS, rel: text}


def schema_case(**commit_plans):
    schema = json.loads(GOOD_PLAN_SCHEMA)
    setting = schema["properties"]["docs"]["properties"]
    if commit_plans:
        setting["commit_plans"] = commit_plans
    else:
        del setting["commit_plans"]
    return plan_case(SCHEMA_REL, json.dumps(schema))


BAD_PLAN_COMMITS = {
    "`commit_plans` missing": (schema_case(), "does not declare `commit_plans`"),
    "`commit_plans` not a boolean": (
        schema_case(type="string", default="false", description="x"), "must be a boolean with default `false`"),
    "`commit_plans` on by default": (
        schema_case(type="boolean", default=True, description="x"), "must be a boolean with default `false`"),
    "`commit_plans` without a default": (
        schema_case(type="boolean", description="x"), "must be a boolean with default `false`"),
    "`commit_plans` without a description": (schema_case(type="boolean", default=False), "has no description"),
    "lead.md no longer names `commit_plans`": (
        plan_case(LEAD_REL, "The plan document is not committed."), f"{LEAD_REL}: does not name `commit_plans`"),
    "the committed record back in lead.md": (
        plan_case(LEAD_REL, GOOD_PLAN_TEXTS[LEAD_REL] + " The plan document is the Committed record."),
        f"{LEAD_REL}: still says 'committed record'"),
    "the committed file back in lead.md": (
        plan_case(LEAD_REL, GOOD_PLAN_TEXTS[LEAD_REL] + " It is a committed file."),
        f"{LEAD_REL}: still says 'it is a committed file'"),
    "the first slice back in the plan template": (
        plan_case("templates/plan.md", "(build-safe slices in order; the plan document is in the first)"),
        "templates/plan.md: still says 'the plan document is in the first'"),
    "committed plans back in the init skill": (
        plan_case("skills/init/SKILL.md", "Propose `docs.plans` (where per-task plan documents are committed)."),
        "skills/init/SKILL.md: still says 'where per-task plan documents are committed'"),
    "committed with the change back in the schema": (
        plan_case(SCHEMA_REL, GOOD_PLAN_SCHEMA.replace("ignored by git.", "committed with the change.")),
        f"{SCHEMA_REL}: still says 'committed with the change'"),
}

errors_before_plan_commit = len(errors)
if plan_commit_problems(GOOD_PLAN_TEXTS):
    fail(f"plan commit check rejects valid files: {plan_commit_problems(GOOD_PLAN_TEXTS)}")
for case, (texts, expected) in BAD_PLAN_COMMITS.items():
    got = plan_commit_problems(texts)
    if len(got) != 1 or expected not in got[0]:
        fail(f"plan commit check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in plan_commit_problems({rel: (PLUGIN / rel).read_text() for rel in PLAN_COMMIT_FILES}):
    fail(problem)
if len(errors) == errors_before_plan_commit:
    ok(f"plan documents stay local by default: the schema declares docs.commit_plans off, lead.md names it, "
       f"no retired statement remains ({len(BAD_PLAN_COMMITS)} bad variants rejected)")


# The default rests on rules only lead.md carries: step 2 of the plan document section adds the
# ignore lines (the directory with one trailing slash, so the plan-named pattern after it never
# reads `//`, which git does not match), asks the user instead of guessing when the plans directory
# tracks other documents, checks the new lines with `git check-ignore`, gives the one-time notice
# only where it adds the line, and keeps `.gitignore` in `exec.lead_files` only while its diff
# against the base is the lead's own added lines (scope-check.sh compares the tree with the base,
# so a line committed by an earlier task would otherwise be sent to a dev to revert, while any
# other edit must still reach the scope gate). The Commit proposal must stage the lead's own
# uncommitted files in a slice of their own, since no workflow slice carries them, put a committed
# plan in that slice, and keep the plan document out of every slice by default.
LEAD_STEP_2 = re.compile(r"^2\. Create `\.claude/conclave/runs/.*$(?:\n {3}.*$)*", re.M)
LEAD_COMMIT = re.compile(r"^## Commit proposal\n(.*?)(?=^## |\Z)", re.S | re.M)
LEAD_IGNORE_RULES = [
    (LEAD_STEP_2, "`.claude/conclave/`", "no longer ignores the run JSON directory"),
    (LEAD_STEP_2, "unless plans are committed, the plans directory", "no longer ignores the plans directory"),
    (LEAD_STEP_2, "one trailing slash", "no longer says how the plans directory line ends"),
    (LEAD_STEP_2, "git ls-files", "no longer checks what is tracked in the plans directory before ignoring it"),
    (LEAD_STEP_2, "- **Tier:**", "no longer tells a tracked plan document from another date-named document"),
    (LEAD_STEP_2, "AskUserQuestion", "no longer asks the user when the plans directory tracks other documents"),
    (LEAD_STEP_2, "<plans directory without its trailing slash>/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md",
     "no longer offers a plan-named pattern git can match"),
    (LEAD_STEP_2, "keeps the old behaviour", "no longer gives the notice to a project that already tracks plans"),
    (LEAD_STEP_2, "in the message where you add", "no longer limits the notice to the message that adds the line"),
    (LEAD_STEP_2, "Never untrack", "no longer forbids untracking files in the plans directory"),
    (LEAD_STEP_2, "git check-ignore", "no longer checks that the new lines ignore the run JSON and the plan"),
    (LEAD_STEP_2, "git diff <profile.base> -- .gitignore",
     "no longer reads the diff of `.gitignore` against the base before naming it in `exec.lead_files`"),
    (LEAD_STEP_2, "removes none", "no longer leaves `.gitignore` out of `exec.lead_files` when other lines changed"),
    (LEAD_COMMIT, "`.gitignore`", "the Commit proposal no longer commits the `.gitignore` lines the lead added"),
    (LEAD_COMMIT, "first slice of its own", "the Commit proposal no longer gives the lead's own files a slice"),
    (LEAD_COMMIT, "git status --porcelain",
     "the Commit proposal no longer limits the lead's slice to files with uncommitted changes"),
    (LEAD_COMMIT, "the slice of your own files",
     "the Commit proposal no longer says which first slice a committed plan goes into"),
    (LEAD_COMMIT, "By default the plan document is in no slice",
     "the Commit proposal no longer keeps the plan document out of every slice by default"),
]
# A placeholder for a directory that ends in a slash, followed by another slash, gives `//`.
LEAD_IGNORE_FORBIDDEN = [
    (LEAD_STEP_2, "<plans directory>/", "writes the plan-named pattern after a directory that ends in a slash"),
    (LEAD_STEP_2, "//", "writes an ignore line with `//`, which git never matches"),
]


def lead_ignore_problems(lead_text):
    """Every rule of LEAD_IGNORE_RULES that lead_text no longer carries, and every forbidden form it
    carries, naming lead.md."""
    problems = []
    for section, needle, why in LEAD_IGNORE_RULES:
        found = section.search(lead_text)
        if not found:
            problems.append(f"{LEAD_REL}: {why} (section {section.pattern!r} not found)")
        elif needle not in found.group(0):
            problems.append(f"{LEAD_REL}: {why} (missing {needle!r})")
    for section, needle, why in LEAD_IGNORE_FORBIDDEN:
        found = section.search(lead_text)
        if found and needle in found.group(0):
            problems.append(f"{LEAD_REL}: {why} (found {needle!r})")
    return problems


GOOD_LEAD_IGNORE = (
    "2. Create `.claude/conclave/runs/<slug>.json`. Local working state:\n"
    "   - The ignore file lists `.claude/conclave/` and, unless plans are committed, the plans directory, with "
    "one trailing slash.\n"
    "   - Run git ls-files first; a plan document carries the - **Tier:** line; otherwise ask with "
    "AskUserQuestion, offering "
    "`<plans directory without its trailing slash>/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md`.\n"
    "   - Say once, in the message where you add the line, that `docs.commit_plans: true` keeps the old behaviour. "
    "Never untrack them.\n"
    "   - Confirm with git check-ignore.\n"
    "   - Name it in `exec.lead_files` while `git diff <profile.base> -- .gitignore` adds only these lines "
    "and removes none.\n"
    "3. Presentation.\n"
    "## Commit proposal\n"
    "Lead files (`.gitignore`) that git status --porcelain shows go into a first slice of its own; a committed "
    "plan goes into the slice of your own files. By default the plan document is in no slice.\n"
    "## Rules\n"
)
BAD_LEAD_IGNORE = {
    f"lead.md without {needle!r}": (GOOD_LEAD_IGNORE.replace(needle, "", 1), why)
    for _, needle, why in LEAD_IGNORE_RULES
}
BAD_LEAD_IGNORE["lead.md with a pattern after `<plans directory>/`"] = (
    GOOD_LEAD_IGNORE.replace("Confirm with", "Or `<plans directory>/*.md`. Confirm with", 1),
    "after a directory that ends in a slash")
BAD_LEAD_IGNORE["lead.md with a `//` ignore line"] = (
    GOOD_LEAD_IGNORE.replace("Confirm with", "Default `docs/plans//[0-9]*.md`. Confirm with", 1), "`//`")
BAD_LEAD_IGNORE["lead.md without step 2"] = (
    GOOD_LEAD_IGNORE.replace("2. Create", "Create", 1), "(section")
BAD_LEAD_IGNORE["lead.md without a Commit proposal"] = (
    GOOD_LEAD_IGNORE.replace("## Commit proposal", "## Commits", 1), "(section")
BAD_LEAD_IGNORE["lead.md with step 2's sub-bullets moved out of it"] = (
    GOOD_LEAD_IGNORE.replace("state:\n   - The", "state:\n\nThe", 1), "(missing")

errors_before_lead_ignore = len(errors)
if lead_ignore_problems(GOOD_LEAD_IGNORE):
    fail(f"lead ignore check rejects a valid lead.md: {lead_ignore_problems(GOOD_LEAD_IGNORE)}")
for case, (text, expected) in BAD_LEAD_IGNORE.items():
    got = lead_ignore_problems(text)
    if case.endswith(("step 2", "Commit proposal", "moved out of it")):
        # Losing a whole section, or the sub-bullets of step 2, drops every rule it carries.
        if len(got) < 2 or not all(expected in p and p.startswith(f"{LEAD_REL}:") for p in got):
            fail(f"lead ignore check on {case}: expected several problems containing {expected!r}, got {got}")
    elif len(got) != 1 or expected not in got[0] or not got[0].startswith(f"{LEAD_REL}:"):
        fail(f"lead ignore check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in lead_ignore_problems((PLUGIN / LEAD_REL).read_text()):
    fail(problem)
if len(errors) == errors_before_lead_ignore:
    ok(f"lead.md ignores the plans directory with a pattern git matches, asks before ignoring other documents, "
       f"warns once, keeps only its own .gitignore lines in lead_files and commits them "
       f"({len(BAD_LEAD_IGNORE)} bad variants rejected)")

# The rest of the local-plan default lives in prose the lead and the skills follow, outside the
# two lead.md sections checked above: the plan-document paragraph says a request in the task opts
# that task in without touching the profile; the Commit proposal sets Status `done` in the local
# document by default; /conclave:plan step 3 names both ignore lines; /conclave:continue no longer
# promises a restart "from another machine" when plans are not committed; /conclave:init says plans
# are not committed by default and does not ask about the opt-in; and the profile template leaves
# `docs.commit_plans` out, so a project created from it keeps its plans local.
LOCAL_PLAN_FILES = [LEAD_REL, "skills/plan/SKILL.md", "skills/continue/SKILL.md", "skills/init/SKILL.md",
                    "templates/conclave.json"]
LEAD_PLAN_PARAGRAPH = "Every task at T1 and above is written down"
PLAN_STEP_3 = "3. Create the plan document"
CONTINUE_NO_RUN = "   - A slug with no run JSON"
INIT_DOCS = "- **Docs.**"


def anchored_line(text, prefix):
    """The first line of text that starts with prefix, or None."""
    return next((line for line in text.splitlines() if line.startswith(prefix)), None)


def local_plan_prompt_problems(texts):
    """Every way lead.md, the plan, continue and init skills and the profile template (relative path ->
    text) drop a rule of the local-plan default, one message each, naming the file."""
    problems = []

    paragraph = anchored_line(texts[LEAD_REL], LEAD_PLAN_PARAGRAPH)
    if paragraph is None:
        problems.append(f"{LEAD_REL}: no plan-document paragraph starting {LEAD_PLAN_PARAGRAPH!r}")
    else:
        for needle, why in [("asks in the task", "no longer lets a request in the task commit the plan"),
                            ("do not change the profile", "no longer keeps a request in the task out of the profile")]:
            if needle not in paragraph:
                problems.append(f"{LEAD_REL}: the plan-document paragraph {why} (missing {needle!r})")

    commit = LEAD_COMMIT.search(texts[LEAD_REL])
    done_local = "Status `done` in the local document"
    if commit is None:
        problems.append(f"{LEAD_REL}: no `## Commit proposal` section")
    elif done_local not in commit.group(1):
        problems.append(f"{LEAD_REL}: the Commit proposal no longer sets Status `done` in the uncommitted plan "
                        f"document after the last commit (missing {done_local!r})")

    step_3 = anchored_line(texts["skills/plan/SKILL.md"], PLAN_STEP_3)
    if step_3 is None:
        problems.append(f"skills/plan/SKILL.md: no step starting {PLAN_STEP_3!r}")
    else:
        for needle in ("`.claude/conclave/`", "unless plans are committed, the plans directory"):
            if needle not in step_3:
                problems.append(f"skills/plan/SKILL.md: step 3 does not name both ignore lines (missing {needle!r})")

    restart = anchored_line(texts["skills/continue/SKILL.md"], CONTINUE_NO_RUN)
    if restart is None:
        problems.append(f"skills/continue/SKILL.md: no bullet starting {CONTINUE_NO_RUN.strip()!r}")
    else:
        if "present on this machine" not in restart:
            problems.append("skills/continue/SKILL.md: the restart from a plan document does not say the document "
                            "must be present on this machine")
        # Each sentence that mentions another machine must tie it to committed plans.
        for sentence in re.split(r"(?<=[.;])\s+", restart):
            if "another machine" in sentence and "commit" not in sentence:
                problems.append("skills/continue/SKILL.md: the restart from a plan document still covers a run from "
                                "another machine without tying it to a project that commits its plans")

    docs_line = anchored_line(texts["skills/init/SKILL.md"], INIT_DOCS)
    if docs_line is None:
        problems.append(f"skills/init/SKILL.md: no bullet starting {INIT_DOCS!r}")
    else:
        for needle, why in [("`docs.plans`", "no longer proposes `docs.plans`"),
                            ("not committed by default", "no longer says plan documents are not committed by default"),
                            ("do not ask", "no longer says not to ask about `docs.commit_plans`")]:
            if needle not in docs_line:
                problems.append(f"skills/init/SKILL.md: the Docs bullet {why} (missing {needle!r})")

    try:
        template_docs = json.loads(texts["templates/conclave.json"]).get("docs", {})
    except (json.JSONDecodeError, AttributeError) as e:
        problems.append(f"templates/conclave.json: cannot read `docs` ({e!r})")
    else:
        if "commit_plans" in template_docs:
            problems.append("templates/conclave.json: sets `docs.commit_plans`; the opt-in is left out of new profiles")
    return problems


GOOD_LOCAL_PLAN = {
    LEAD_REL: (
        f"{LEAD_PLAN_PARAGRAPH}. Not committed unless `profile.docs.commit_plans` is `true` or the user asks in the "
        "task. A request holds for that task; do not change the profile unless asked.\n"
        "## Commit proposal\nBy default the plan document is in no slice; set Status `done` in the local document.\n"
        "## Rules\n"),
    "skills/plan/SKILL.md": (
        f"{PLAN_STEP_3} as lead.md says (`.claude/conclave/` and, unless plans are committed, the plans directory).\n"),
    "skills/continue/SKILL.md": (
        "1. Pick the run.\n"
        f"{CONTINUE_NO_RUN} but a plan document: the state is lost (the JSON was deleted, or, in a project that "
        "commits its plans, the run came from another machine). The document must be present on this machine; "
        "a run from another machine needs its document committed or copied.\n"),
    "skills/init/SKILL.md": (
        f"{INIT_DOCS} Propose `docs.plans`; plan documents are not committed by default. Leave `docs.commit_plans` "
        "out and do not ask about it.\n"),
    "templates/conclave.json": json.dumps({"docs": {"plans": "docs/plans/"}}),
}


def local_plan_case(rel, old, new):
    assert old in GOOD_LOCAL_PLAN[rel], (rel, old)
    return {**GOOD_LOCAL_PLAN, rel: GOOD_LOCAL_PLAN[rel].replace(old, new, 1)}


BAD_LOCAL_PLAN = {
    "lead.md without the request in the task": (
        local_plan_case(LEAD_REL, "or the user asks in the task", ""), "missing 'asks in the task'"),
    "lead.md changing the profile on a request": (
        local_plan_case(LEAD_REL, "do not change the profile unless asked", "save it in the profile"),
        "missing 'do not change the profile'"),
    "lead.md without the plan-document paragraph": (
        local_plan_case(LEAD_REL, LEAD_PLAN_PARAGRAPH, "Each task is written down"), "no plan-document paragraph"),
    "lead.md without Status done in the local document": (
        local_plan_case(LEAD_REL, "set Status `done` in the local document", "leave Status alone"),
        "no longer sets Status `done`"),
    "lead.md without a Commit proposal": (
        local_plan_case(LEAD_REL, "## Commit proposal", "## Commits"), "no `## Commit proposal`"),
    "plan step 3 with only the run JSON line": (
        local_plan_case("skills/plan/SKILL.md", " and, unless plans are committed, the plans directory", ""),
        "missing 'unless plans are committed, the plans directory'"),
    "plan step 3 without the run JSON line": (
        local_plan_case("skills/plan/SKILL.md", "`.claude/conclave/` and", ""), "missing '`.claude/conclave/`'"),
    "plan without step 3": (
        local_plan_case("skills/plan/SKILL.md", PLAN_STEP_3, "Create the plan document"), "no step starting"),
    "continue without this machine": (
        local_plan_case("skills/continue/SKILL.md", "must be present on this machine", "is read"),
        "must be present on this machine"),
    "continue with the old another-machine wording": (
        local_plan_case("skills/continue/SKILL.md", "the JSON was deleted, or, in a project that commits its plans, "
                        "the run came from another machine", "the JSON was deleted or the run came from another machine"),
        "without tying it to a project that commits its plans"),
    "continue without the restart bullet": (
        local_plan_case("skills/continue/SKILL.md", CONTINUE_NO_RUN, "   - No run JSON"), "no bullet starting"),
    "init without not committed by default": (
        local_plan_case("skills/init/SKILL.md", "plan documents are not committed by default", "plans are committed"),
        "missing 'not committed by default'"),
    "init asking about commit_plans": (
        local_plan_case("skills/init/SKILL.md", "out and do not ask about it", "and ask the user whether to set it"),
        "missing 'do not ask'"),
    "init without docs.plans": (
        local_plan_case("skills/init/SKILL.md", "Propose `docs.plans`", "Propose a plans directory"),
        "missing '`docs.plans`'"),
    "the profile template sets commit_plans": (
        local_plan_case("templates/conclave.json", '"docs/plans/"}', '"docs/plans/", "commit_plans": true}'),
        "templates/conclave.json: sets `docs.commit_plans`"),
}

errors_before_local_plan = len(errors)
if local_plan_prompt_problems(GOOD_LOCAL_PLAN):
    fail(f"local plan check rejects valid files: {local_plan_prompt_problems(GOOD_LOCAL_PLAN)}")
for case, (texts, expected) in BAD_LOCAL_PLAN.items():
    got = local_plan_prompt_problems(texts)
    if len(got) != 1 or expected not in got[0]:
        fail(f"local plan check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in local_plan_prompt_problems({rel: (PLUGIN / rel).read_text() for rel in LOCAL_PLAN_FILES}):
    fail(problem)
if len(errors) == errors_before_local_plan:
    ok(f"lead, plan, continue, init and the profile template keep plans local by default "
       f"({len(BAD_LOCAL_PLAN)} bad variants rejected)")

# The ignore lines are prose the lead copies into a project's .gitignore, so what they match is
# git's business, not the prompt's: every default plans line lead.md step 2 writes (a backticked
# `docs/plans/...`) is put in a scratch repository's .gitignore on its own, and git must ignore a
# plan document of the template's name under it; a plan-named pattern must leave a non-plan file
# such as `docs/plans/README.md` alone, and `.claude/conclave/` must ignore the run JSON.
PLAN_DOC_PATH = "docs/plans/2026-11-21-plan-documents-stay-local.md"
NON_PLAN_PATH = "docs/plans/README.md"
RUN_JSON_PATH = ".claude/conclave/runs/plan-documents-stay-local.json"


def ignore_line_problems(step_2):
    """Every default ignore line in step_2 that git does not apply as lead.md describes it."""
    import tempfile

    problems = []
    lines = sorted(set(re.findall(r"`(docs/plans/[^`]*)`", step_2)))
    if not lines:
        return [f"{LEAD_REL}: step 2 names no default plans line (`docs/plans/...`)"]
    if "`.claude/conclave/`" not in step_2:
        problems.append(f"{LEAD_REL}: step 2 does not name the `.claude/conclave/` line")
    with tempfile.TemporaryDirectory() as repo:
        init = subprocess.run(["git", "init", "-q", repo], capture_output=True, text=True)
        if init.returncode != 0:
            return [f"cannot create a scratch git repository: {init.stderr.strip()}"]

        def ignored(pattern, path):
            Path(repo, ".gitignore").write_text(pattern + "\n")
            return subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=repo).returncode == 0

        if not ignored(".claude/conclave/", RUN_JSON_PATH):
            problems.append(f"git does not ignore {RUN_JSON_PATH} with `.claude/conclave/`")
        for line in lines:
            if not ignored(line, PLAN_DOC_PATH):
                problems.append(f"{LEAD_REL}: git does not ignore {PLAN_DOC_PATH} with the line `{line}`")
            if line != "docs/plans/" and ignored(line, NON_PLAN_PATH):
                problems.append(f"{LEAD_REL}: the plan-named line `{line}` also ignores {NON_PLAN_PATH}")
    return problems


GOOD_STEP_2 = ("2. Create `.claude/conclave/runs/<slug>.json`; ignore `.claude/conclave/` and `docs/plans/`, or "
               "`docs/plans/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md`.")
BAD_STEP_2 = {
    "a `//` plan-named line": (
        GOOD_STEP_2.replace("`docs/plans/[0-9]", "`docs/plans//[0-9]"), "git does not ignore"),
    "a plan-named line that matches every file": (
        GOOD_STEP_2.replace("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md", "*"), "also ignores"),
    "a plans line without a slash before the file": (
        GOOD_STEP_2.replace("`docs/plans/[0-9]", "`docs/plans/x[0-9]"), "git does not ignore"),
    "no default plans line": (GOOD_STEP_2.replace("`docs/plans/", "`plans/"), "names no default plans line"),
    "no run JSON line": (GOOD_STEP_2.replace("ignore `.claude/conclave/` and", "ignore"), "`.claude/conclave/` line"),
}

errors_before_ignore_lines = len(errors)
if ignore_line_problems(GOOD_STEP_2):
    fail(f"ignore line check rejects valid lines: {ignore_line_problems(GOOD_STEP_2)}")
for case, (text, expected) in BAD_STEP_2.items():
    got = ignore_line_problems(text)
    if len(got) != 1 or expected not in got[0]:
        fail(f"ignore line check on {case}: expected one problem containing {expected!r}, got {got}")
real_step_2 = LEAD_STEP_2.search((PLUGIN / LEAD_REL).read_text())
for problem in ignore_line_problems(real_step_2.group(0) if real_step_2 else ""):
    fail(problem)
if len(errors) == errors_before_ignore_lines:
    ok(f"git applies the default ignore lines of lead.md step 2 as described ({len(BAD_STEP_2)} bad variants rejected)")


# A project records whether its documentation follows Diátaxis in `docs.diataxis`: a boolean the
# user sets, with no default, because an absent key is what tells the lead and /conclave:init that
# the question is still open; the profile template must not answer it for the user. The rules live
# in the writing pack's `## Diátaxis` section with the four directory names; the docs-writer and
# the lead name the key and point at that section without restating the rules (the directory names
# stay out of both agents). The section that moves is the smallest one holding the edit, and the
# README's entry-point sections never move, so a one-line edit cannot carry a chapter or hollow the
# README. The lead asks with AskUserQuestion only when `docs.paths` is non-empty, never when the key
# is present, and adds `docs/` to `docs.paths` on a yes when no entry ends with `/` (else the pack's
# `docs/` fallback is outside the writer's reach). A directory entry is one that ends with `/`, as
# the scope gate reads it: a bare `docs` matches only a file of that name, so the four directories
# under it would be out of scope. The lead names the profile in `exec.lead_files` while its
# difference from `profile.base` is only the lines it wrote with the user's agreement, not only in
# the task that asked: the scope gate compares the tree with the base, commits included, so a later
# task on the branch would otherwise send the committed answer to a dev to revert; any other change
# (a subagent's edit) keeps the profile out so the gate still catches it. An untracked profile, which
# `git diff` does not show, is proposed for a commit first. /conclave:init asks when it composes a
# profile, keeps the answer on `--force`, and reports the open question on an existing one. Nothing
# executes these prompts, so the wording is guarded.
WRITING_REL = "skills/writing-docs/SKILL.md"
DOCS_WRITER_REL = "agents/docs-writer.md"
INIT_REL = "skills/init/SKILL.md"
TEMPLATE_REL = "templates/conclave.json"
DIATAXIS_FILES = [SCHEMA_REL, TEMPLATE_REL, WRITING_REL, DOCS_WRITER_REL, LEAD_REL, INIT_REL]
DIATAXIS_KEY = "`docs.diataxis`"
DIATAXIS_HEADING = "## Diátaxis"
DIATAXIS_DIRS = ["`tutorials/`", "`how-to/`", "`reference/`", "`explanation/`"]
DIATAXIS_FALLBACK = "`docs/`"
# The instruction itself: the option texts name `docs/` too, as a consequence, without writing it.
DIATAXIS_ADD = f"add {DIATAXIS_FALLBACK}"
# A directory entry of `docs.paths` is one that ends with `/`, as the scope gate reads it. The
# instructions, not the option texts that also say it, carry these needles.
PACK_DIRECTORY_ENTRY = "the first entry that ends with `/`"
DIRECTORY_ENTRY = "no entry of `docs.paths` ends with `/`"
WRITING_KEPT_HEADINGS = ["## Document kinds", "## Mermaid patterns"]
WRITING_KEPT_TEXT = ["The plan document (`templates/plan.md`)"]
PACK_RULES = [
    ("deepest heading", "does not define the section that moves as the smallest one holding the edit"),
    ("entry-point sections", "does not keep the README's entry-point sections in place"),
    (PACK_DIRECTORY_ENTRY, "does not define a directory entry of `docs.paths` as one that ends with `/`"),
]
# Wording that counts a `docs.paths` entry without a trailing `/` as a directory, which the scope
# gate compares as a single file.
BARE_DIRECTORY = "directory in the tree"

LEAD_RULES = [
    ("Never ask when the key is present", "no longer says it never asks again"),
    ("non-empty `docs.paths`", "is no longer limited to a non-empty `docs.paths`"),
    (DIATAXIS_ADD, f"no longer adds {DIATAXIS_FALLBACK} to `docs.paths` on a yes"),
    (DIRECTORY_ENTRY, "no longer adds `docs/` only when no entry of `docs.paths` ends with `/`"),
]
# Once the profile is named in `exec.lead_files`, the scope gate lets every edit to it through.
LEAD_FILES_RULES = [
    ("profile.base", "does not keep the profile in `exec.lead_files` while it differs from `profile.base`; a "
                     "later task on the branch sends the answer to a dev to revert"),
    ("changes nothing but lines you wrote", "names the profile in `exec.lead_files` whatever its diff holds, so a "
                                            "subagent's edit to it passes the scope gate"),
    ("untracked", "does not handle an untracked profile, which `git diff` does not show"),
]

BLOCK_START = re.compile(r"^(#|- |\||\d+\. |\*\*)")


def blocks(text):
    """The paragraphs, list items, headings and table rows of a Markdown text, each with its
    continuation lines joined by spaces, so a rule wrapped over several lines reads as one."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            found.append("")
        elif not found or not found[-1] or BLOCK_START.match(stripped):
            found.append(stripped)
        else:
            found[-1] += " " + stripped
    return [block for block in found if block]


def block_with(text, *needles):
    """The first block of text that contains every needle, or None."""
    return next((b for b in blocks(text) if all(n in b for n in needles)), None)


def diataxis_problems(texts):
    """Every way the files in DIATAXIS_FILES (relative path -> text) drop the Diátaxis setting, one
    message each, naming the file."""
    problems = []
    try:
        docs = json.loads(texts[SCHEMA_REL])["properties"]["docs"]["properties"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return [f"{SCHEMA_REL}: cannot read `properties.docs.properties` ({e!r})"]
    setting = docs.get("diataxis")
    if not isinstance(setting, dict):
        problems.append(f"{SCHEMA_REL}: `docs` does not declare `diataxis`, the project's Diátaxis answer")
    elif setting.get("type") != "boolean":
        problems.append(f"{SCHEMA_REL}: `docs.diataxis` must be a boolean, found type {setting.get('type')!r}")
    elif "default" in setting:
        problems.append(f"{SCHEMA_REL}: `docs.diataxis` has a default ({setting['default']!r}); an absent key must "
                        "mean the user has not been asked")
    elif not str(setting.get("description", "")).strip():
        problems.append(f"{SCHEMA_REL}: `docs.diataxis` has no description")

    try:
        template_docs = json.loads(texts[TEMPLATE_REL]).get("docs", {})
    except (json.JSONDecodeError, AttributeError) as e:
        problems.append(f"{TEMPLATE_REL}: cannot read `docs` ({e!r})")
    else:
        if "diataxis" in template_docs:
            problems.append(f"{TEMPLATE_REL}: sets `docs.diataxis`; the answer is the user's, asked for each project")

    writing_lines = [line.rstrip() for line in texts[WRITING_REL].splitlines()]
    pack = section(writing_lines, DIATAXIS_HEADING)
    if pack is None:
        problems.append(f"{WRITING_REL}: no `{DIATAXIS_HEADING}` section")
    else:
        pack_text = " ".join(line.strip() for line in pack)
        missing = [d for d in DIATAXIS_DIRS if d not in pack_text]
        if missing:
            problems.append(f"{WRITING_REL}: the `{DIATAXIS_HEADING}` section does not name {', '.join(missing)}")
        for needle, why in PACK_RULES:
            if needle not in pack_text:
                problems.append(f"{WRITING_REL}: the `{DIATAXIS_HEADING}` section {why} (missing {needle!r})")
        if BARE_DIRECTORY in pack_text:
            problems.append(f"{WRITING_REL}: the `{DIATAXIS_HEADING}` section counts a `docs.paths` entry without a "
                            "trailing `/` as a directory; the scope gate reads it as a single file")
    lost = ([h for h in WRITING_KEPT_HEADINGS if h not in writing_lines]
            + [t for t in WRITING_KEPT_TEXT if t not in texts[WRITING_REL]])
    if lost:
        problems.append(f"{WRITING_REL}: lost {', '.join(f'`{h}`' for h in lost)}")
    if block_with(texts[WRITING_REL], "existing structure", "does not use Diátaxis") is None:
        problems.append(f"{WRITING_REL}: the rule to keep the existing structure is not limited to a project that "
                        "does not use Diátaxis")

    writer_rule = block_with(texts[DOCS_WRITER_REL], DIATAXIS_KEY, "`conclave:writing-docs`", "`gaps`")
    if DIATAXIS_KEY not in texts[DOCS_WRITER_REL]:
        problems.append(f"{DOCS_WRITER_REL}: does not name {DIATAXIS_KEY}")
    elif writer_rule is None:
        problems.append(f"{DOCS_WRITER_REL}: no paragraph that names {DIATAXIS_KEY}, points to "
                        "`conclave:writing-docs` and lists unfixable links under `gaps`")

    lead_rule = block_with(texts[LEAD_REL], DIATAXIS_KEY, "AskUserQuestion")
    if DIATAXIS_KEY not in texts[LEAD_REL]:
        problems.append(f"{LEAD_REL}: does not name {DIATAXIS_KEY}")
    elif lead_rule is None:
        problems.append(f"{LEAD_REL}: no paragraph that names {DIATAXIS_KEY} and asks the question with "
                        "AskUserQuestion")
    else:
        for needle, why in LEAD_RULES:
            if needle not in lead_rule:
                problems.append(f"{LEAD_REL}: the Diátaxis question {why} (missing {needle!r})")
        if "`exec.lead_files`" not in lead_rule:
            problems.append(f"{LEAD_REL}: the Diátaxis question no longer names the profile in `exec.lead_files`")
        else:
            for needle, why in LEAD_FILES_RULES:
                if needle not in lead_rule:
                    problems.append(f"{LEAD_REL}: the Diátaxis question {why} (missing {needle!r})")
        if "of this task" in lead_rule:
            problems.append(f"{LEAD_REL}: the Diátaxis question limits `exec.lead_files` to the task that asked "
                            "(\"of this task\")")

    for rel in (DOCS_WRITER_REL, LEAD_REL):
        restated = [d for d in DIATAXIS_DIRS if d in texts[rel]]
        if restated:
            problems.append(f"{rel}: names {', '.join(restated)}; the framework's rules belong in {WRITING_REL}")

    init_ask = block_with(texts[INIT_REL], DIATAXIS_KEY, "AskUserQuestion")
    if init_ask is None:
        problems.append(f"{INIT_REL}: does not ask the Diátaxis question with AskUserQuestion and write "
                        f"{DIATAXIS_KEY} when it composes a profile")
    else:
        if DIATAXIS_ADD not in init_ask:
            problems.append(f"{INIT_REL}: no longer adds {DIATAXIS_FALLBACK} to `docs.paths` on a yes")
        if DIRECTORY_ENTRY not in init_ask:
            problems.append(f"{INIT_REL}: no longer adds {DIATAXIS_FALLBACK} only when no entry of `docs.paths` ends "
                            "with `/`")
        if "`--force`" not in init_ask or "carry" not in init_ask:
            problems.append(f"{INIT_REL}: does not carry an existing {DIATAXIS_KEY} over on `--force`")
    if block_with(texts[INIT_REL], DIATAXIS_KEY, "still open") is None:
        problems.append(f"{INIT_REL}: does not report the Diátaxis question as still open on an existing profile "
                        f"without {DIATAXIS_KEY}")
    return problems


GOOD_DIATAXIS = {
    SCHEMA_REL: json.dumps({"properties": {"docs": {"properties": {
        "diataxis": {"type": "boolean", "description": "Whether the documentation follows Diátaxis."}}}}}),
    TEMPLATE_REL: json.dumps({"docs": {"paths": ["docs/"]}}),
    WRITING_REL: (
        "## Structure\n"
        "- In a project that does not use Diátaxis, and in sections a change does not touch,\n"
        "  keep the document's existing structure.\n"
        "## Mermaid patterns\n"
        "## Document kinds\n"
        "The plan document (`templates/plan.md`) is an analysis.\n"
        f"{DIATAXIS_HEADING}\n"
        "| Tutorial | `tutorials/` |\n| How-to | `how-to/` |\n| Reference | `reference/` |\n"
        "| Explanation | `explanation/` |\n"
        "Under the first entry that ends with `/`.\n"
        "3. Move the smallest section: from the deepest heading above the edit.\n"
        "4. Never move the README's entry-point sections.\n"),
    DOCS_WRITER_REL: (
        "## Where the text goes\n\n"
        f"When {DIATAXIS_KEY} is `true`, follow the \"Diátaxis\" section of `conclave:writing-docs`;\n"
        "list links you may not fix under `gaps`.\n"),
    LEAD_REL: (
        f"4. When the profile has a non-empty `docs.paths` and no {DIATAXIS_KEY}, ask with AskUserQuestion; on a "
        f"yes, when no entry of `docs.paths` ends with `/`, add "
        f"{DIATAXIS_FALLBACK}. Never ask when the key is present. Name the "
        "profile in `exec.lead_files` while `git diff <profile.base>` changes nothing but lines you wrote; propose "
        "committing an untracked profile.\n"),
    INIT_REL: (
        f"3. When the profile has no {DIATAXIS_KEY}, say the question is still open.\n\n"
        f"Ask with AskUserQuestion and write {DIATAXIS_KEY}; on a yes, when no entry of `docs.paths` ends with "
        f"`/`, add {DIATAXIS_FALLBACK}. With `--force`, "
        "carry the old value over.\n"),
}


def diataxis_case(rel, *pairs):
    """GOOD_DIATAXIS with each (old, new) pair of `pairs`, given flat, replaced once in rel."""
    text = GOOD_DIATAXIS[rel]
    for old, new in zip(pairs[::2], pairs[1::2]):
        assert old in text, (rel, old)
        text = text.replace(old, new, 1)
    return {**GOOD_DIATAXIS, rel: text}


def diataxis_schema_case(**setting):
    schema = json.loads(GOOD_DIATAXIS[SCHEMA_REL])
    properties = schema["properties"]["docs"]["properties"]
    if setting:
        properties["diataxis"] = setting
    else:
        del properties["diataxis"]
    return {**GOOD_DIATAXIS, SCHEMA_REL: json.dumps(schema)}


BAD_DIATAXIS = {
    "`diataxis` missing from the schema": (diataxis_schema_case(), "does not declare `diataxis`"),
    "`diataxis` not a boolean": (
        diataxis_schema_case(type="string", description="x"), "`docs.diataxis` must be a boolean"),
    "`diataxis` with a default": (
        diataxis_schema_case(type="boolean", default=True, description="x"), "`docs.diataxis` has a default"),
    "`diataxis` with a false default": (
        diataxis_schema_case(type="boolean", default=False, description="x"), "`docs.diataxis` has a default"),
    "`diataxis` without a description": (diataxis_schema_case(type="boolean"), "`docs.diataxis` has no description"),
    "the profile template answers the question": (
        diataxis_case(TEMPLATE_REL, '["docs/"]}', '["docs/"], "diataxis": true}'),
        f"{TEMPLATE_REL}: sets `docs.diataxis`"),
    "the pack without its Diátaxis section": (
        diataxis_case(WRITING_REL, DIATAXIS_HEADING + "\n", "## Kinds\n"), f"{WRITING_REL}: no `{DIATAXIS_HEADING}`"),
    "the pack without `how-to/`": (
        diataxis_case(WRITING_REL, "`how-to/`", "`guides/`"), "does not name `how-to/`"),
    "the pack without `explanation/`": (
        diataxis_case(WRITING_REL, "`explanation/`", "`background/`"), "does not name `explanation/`"),
    # The directory names count only inside the section: one moved above it is missing from it.
    "a directory named only outside the Diátaxis section": (
        diataxis_case(WRITING_REL, "`tutorials/`", "`lessons/`", "## Mermaid patterns\n",
                      "## Mermaid patterns\nSee `tutorials/`.\n"),
        "does not name `tutorials/`"),
    "the pack without its Document kinds": (
        diataxis_case(WRITING_REL, "## Document kinds\n", ""), "lost `## Document kinds`"),
    "the pack without its Mermaid patterns": (
        diataxis_case(WRITING_REL, "## Mermaid patterns\n", ""), "lost `## Mermaid patterns`"),
    "the pack without its plan-document paragraph": (
        diataxis_case(WRITING_REL, "The plan document (`templates/plan.md`)", "Plans"),
        "lost `The plan document (`templates/plan.md`)`"),
    # A one-line edit inside a large chapter must not carry the whole chapter.
    "the pack moving a whole chapter": (
        diataxis_case(WRITING_REL, "the smallest section: from the deepest heading above the edit",
                      "the whole section"),
        "smallest one holding the edit"),
    "the pack moving the README's entry point": (
        diataxis_case(WRITING_REL, "4. Never move the README's entry-point sections.\n", ""),
        "entry-point sections in place"),
    # The scope gate prefix-matches only an entry ending with `/`: the directories under a bare
    # `docs` entry are out of scope and sent to a dev to revert.
    "the pack without its directory-entry rule": (
        diataxis_case(WRITING_REL, PACK_DIRECTORY_ENTRY, "the first directory"), "one that ends with `/`"),
    "the pack counting a bare entry as a directory": (
        diataxis_case(WRITING_REL, PACK_DIRECTORY_ENTRY, PACK_DIRECTORY_ENTRY + " or names a directory in the tree"),
        "counts a `docs.paths` entry without a trailing `/`"),
    "the keep-the-structure rule left unscoped": (
        diataxis_case(WRITING_REL, "In a project that does not use Diátaxis, and in sections a change does not touch,",
                      "Always"), "not limited to a project that does not use Diátaxis"),
    "docs-writer.md without the key": (
        diataxis_case(DOCS_WRITER_REL, DIATAXIS_KEY, "the setting"), f"{DOCS_WRITER_REL}: does not name"),
    "docs-writer.md without the pack section": (
        diataxis_case(DOCS_WRITER_REL, "`conclave:writing-docs`", "your judgement"),
        "points to `conclave:writing-docs`"),
    "docs-writer.md without the link report": (
        diataxis_case(DOCS_WRITER_REL, "under `gaps`", "nowhere"), "lists unfixable links under `gaps`"),
    "docs-writer.md restating a directory": (
        diataxis_case(DOCS_WRITER_REL, "list links", "put guides in `how-to/`; list links"),
        f"{DOCS_WRITER_REL}: names `how-to/`"),
    "lead.md without the key": (diataxis_case(LEAD_REL, DIATAXIS_KEY, "the setting"), f"{LEAD_REL}: does not name"),
    "lead.md without the question": (
        diataxis_case(LEAD_REL, "ask with AskUserQuestion", "set it to true"),
        "asks the question with AskUserQuestion"),
    "lead.md asking again when the key is present": (
        diataxis_case(LEAD_REL, " Never ask when the key is present.", ""), "no longer says it never asks again"),
    "lead.md without the profile in lead_files": (
        diataxis_case(LEAD_REL, " Name the profile in `exec.lead_files` while `git diff <profile.base>` changes "
                                "nothing but lines you wrote; propose committing an untracked profile.", ""),
        "no longer names the profile"),
    # Without a content condition every profile edit, a subagent's included, passes the scope gate.
    "lead.md naming the profile in lead_files whatever its diff holds": (
        diataxis_case(LEAD_REL, "changes nothing but lines you wrote", "shows a change"),
        "whatever its diff holds"),
    "lead.md without the untracked profile": (
        diataxis_case(LEAD_REL, "; propose committing an untracked profile.", "."), "an untracked profile"),
    # The scope gate compares with profile.base, commits included: the answer an earlier task on the
    # branch committed must stay allowed, or the next task sends it to a dev to revert.
    "lead.md keeping the profile in lead_files apart from the base diff": (
        diataxis_case(LEAD_REL, "<profile.base>", "<HEAD>"), "while it differs from `profile.base`"),
    "lead.md keeping the profile in lead_files for the asking task only": (
        diataxis_case(LEAD_REL, "lines you wrote;", "lines you wrote, of this task;"),
        "limits `exec.lead_files` to the task that asked"),
    "lead.md asking with an empty docs.paths": (
        diataxis_case(LEAD_REL, "a non-empty `docs.paths`", "`docs.paths`"), "limited to a non-empty `docs.paths`"),
    "lead.md without the docs/ fallback": (
        diataxis_case(LEAD_REL, f", add {DIATAXIS_FALLBACK}", ""), f"no longer adds {DIATAXIS_FALLBACK} to"),
    "lead.md adding docs/ beside a bare directory entry": (
        diataxis_case(LEAD_REL, DIRECTORY_ENTRY, "no entry is a directory"),
        "only when no entry of `docs.paths` ends with `/`"),
    "lead.md restating a directory": (
        diataxis_case(LEAD_REL, "ask with", "ask, naming `reference/`, with"), f"{LEAD_REL}: names `reference/`"),
    "init without the question": (
        diataxis_case(INIT_REL, "Ask with AskUserQuestion", "Set it"), f"{INIT_REL}: does not ask"),
    "init without the open question": (
        diataxis_case(INIT_REL, "is still open", "is answered"), f"{INIT_REL}: does not report"),
    "init without the docs/ fallback": (
        diataxis_case(INIT_REL, DIATAXIS_ADD, "write it"),
        f"{INIT_REL}: no longer adds {DIATAXIS_FALLBACK} to"),
    "init adding docs/ beside a bare directory entry": (
        diataxis_case(INIT_REL, DIRECTORY_ENTRY, "no entry is a directory"),
        f"{INIT_REL}: no longer adds {DIATAXIS_FALLBACK} only when"),
    "init asking again on --force": (
        diataxis_case(INIT_REL, "carry the old value over", "ask again"), "over on `--force`"),
}

errors_before_diataxis = len(errors)
if diataxis_problems(GOOD_DIATAXIS):
    fail(f"diataxis check rejects valid files: {diataxis_problems(GOOD_DIATAXIS)}")
for case, (texts, expected) in BAD_DIATAXIS.items():
    got = diataxis_problems(texts)
    if len(got) != 1 or expected not in got[0]:
        fail(f"diataxis check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in diataxis_problems({rel: (PLUGIN / rel).read_text() for rel in DIATAXIS_FILES}):
    fail(problem)
if len(errors) == errors_before_diataxis:
    ok(f"docs.diataxis is a boolean without a default, the pack has its Diátaxis section, the docs-writer, the lead "
       f"and init name the key without restating the rules ({len(BAD_DIATAXIS)} bad variants rejected)")


# The schema is what /conclave:init validates a profile against: an answered question (`true` or
# `false`) must validate, an answer of any other type must not, and an unanswered one (the template)
# already validates above.
errors_before_diataxis_schema = len(errors)
try:
    import jsonschema

    for answer in (True, False):
        profile = json.loads(json.dumps(template))
        profile.setdefault("docs", {})["diataxis"] = answer
        try:
            jsonschema.validate(profile, schema)
        except jsonschema.ValidationError as e:
            fail(f"{SCHEMA_REL}: a profile answering `docs.diataxis: {json.dumps(answer)}` does not validate: "
                 f"{e.message}")
    for answer in ("yes", "true", 1, None, ["docs/"]):
        profile = json.loads(json.dumps(template))
        profile.setdefault("docs", {})["diataxis"] = answer
        try:
            jsonschema.validate(profile, schema)
        except jsonschema.ValidationError:
            continue
        fail(f"{SCHEMA_REL}: a profile with `docs.diataxis: {json.dumps(answer)}` validates; only a boolean answers "
             "the question")
except ImportError:
    pass  # reported once above
if len(errors) == errors_before_diataxis_schema:
    ok("a profile validates with `docs.diataxis` true or false and is rejected with any other type")


# The rest of what the acceptance criteria ask of the Diátaxis wording, past the guard above: the
# pack gives each kind what its reader needs, what it contains and what it leaves out, says how to
# tell the kinds apart, creates a missing directory with an index file, leaves a pointer where a
# section moved from, moves nothing else, fixes links inside `docs.paths` and lists the others with
# file and line, and makes misfiled text an audit finding. The docs-writer keeps "match the voice
# and density" for a project without Diátaxis, says its Diátaxis section does not apply when the
# key is `false` or absent, carries the link rule and the audit finding, and moves nothing else. The
# lead and init offer yes as the recommended answer with each option's consequence; the lead asks at
# T1 or above and says what it wrote. Neither agent restates a rule that only the pack states.
REACH_FILES = [WRITING_REL, DOCS_WRITER_REL, LEAD_REL, INIT_REL]
REACH_PACK = [
    ("| Tutorial |", "does not describe the tutorial kind"),
    ("| How-to guide |", "does not describe the how-to guide kind"),
    ("| Reference |", "does not describe the reference kind"),
    ("| Explanation |", "does not describe the explanation kind"),
    ("The reader needs", "does not say what the reader of each kind needs"),
    ("The document contains", "does not say what each kind contains"),
    ("It leaves out", "does not say what each kind leaves out"),
    ("learning or working", "does not say how to tell the kinds apart (learning or working)"),
    ("to do something or to know something", "does not say how to tell the kinds apart (do or know)"),
    ("index file", "does not create a missing directory with an index file"),
    ("points to the new place", "does not leave a line pointing to a moved section's new place"),
    ("Move nothing else", "does not forbid moving anything else"),
    ("never in one pass", "does not forbid reorganising the documentation in one pass"),
    ("inside `docs.paths`", "does not update the links to moved text inside `docs.paths`"),
    ("with file and line", "does not list the links outside `docs.paths` with file and line"),
    ("directory of the wrong kind", "does not make text in the directory of the wrong kind an audit finding"),
]
REACH_WRITER = [
    ("`false` or absent", "does not say its Diátaxis instructions do not apply when the key is `false` or absent"),
    ("inside `docs.paths`", "does not update the links to moved text inside `docs.paths`"),
    ("with file and line", "does not list the links it may not fix with file and line"),
    ("never anything else", "does not forbid moving anything the pack does not allow"),
]
WRITER_VOICE = "Match the voice and density of the surrounding text."
REACH_ASK = [
    ("recommended", "does not recommend an answer"),
    ("yes (", "does not give the consequence of yes"),
    ("no (", "does not give the consequence of no"),
]
REACH_LEAD = [
    ("T1 or above", "is not limited to a task at T1 or above"),
    ("Say in one line what you wrote", "does not tell the user what it wrote into the profile"),
]
REACH_INIT = [("`true` or `false`", "does not write the answer as `true` or `false`")]
# Rules only the pack states: an agent that carries one has restated the framework.
PACK_ONLY = ["deepest heading", "entry-point sections", "index file", "Moved to [", "learning or working",
             "It leaves out"]


def diataxis_reach_problems(texts):
    """Every way the files in REACH_FILES (relative path -> text) drop a behaviour the Diátaxis
    acceptance criteria name, one message each, naming the file."""
    problems = []
    pack = section([line.rstrip() for line in texts[WRITING_REL].splitlines()], DIATAXIS_HEADING)
    if pack is None:
        problems.append(f"{WRITING_REL}: no `{DIATAXIS_HEADING}` section")
    else:
        pack_text = " ".join(line.strip() for line in pack)
        for needle, why in REACH_PACK:
            if needle not in pack_text:
                problems.append(f"{WRITING_REL}: the `{DIATAXIS_HEADING}` section {why} (missing {needle!r})")

    writer = texts[DOCS_WRITER_REL]
    writer_lines = [line.rstrip() for line in writer.splitlines()]
    how = section(writer_lines, "## How you write")
    if how is None or WRITER_VOICE not in " ".join(how):
        problems.append(f"{DOCS_WRITER_REL}: \"How you write\" no longer says {WRITER_VOICE!r}")
    writer_rule = block_with(writer, DIATAXIS_KEY, "`conclave:writing-docs`")
    if writer_rule is None:
        problems.append(f"{DOCS_WRITER_REL}: no paragraph that names {DIATAXIS_KEY} and points to "
                        "`conclave:writing-docs`")
    else:
        for needle, why in REACH_WRITER:
            if needle not in writer_rule:
                problems.append(f"{DOCS_WRITER_REL}: the Diátaxis paragraph {why} (missing {needle!r})")
    audit = section(writer_lines, "## As auditor")
    audit_text = " ".join(audit or [])
    if DIATAXIS_KEY not in audit_text or "wrong kind" not in audit_text:
        problems.append(f"{DOCS_WRITER_REL}: \"As auditor\" does not make text in the directory of the wrong kind a "
                        f"finding when {DIATAXIS_KEY} is `true`")

    for rel, extra in ((LEAD_REL, REACH_LEAD), (INIT_REL, REACH_INIT)):
        ask = block_with(texts[rel], DIATAXIS_KEY, "AskUserQuestion")
        if ask is None:
            problems.append(f"{rel}: no paragraph that names {DIATAXIS_KEY} and asks with AskUserQuestion")
            continue
        for needle, why in REACH_ASK + extra:
            if needle not in ask:
                problems.append(f"{rel}: the Diátaxis question {why} (missing {needle!r})")

    for rel in (DOCS_WRITER_REL, LEAD_REL):
        restated = [p for p in PACK_ONLY if p in texts[rel]]
        if restated:
            problems.append(f"{rel}: states {', '.join(repr(p) for p in restated)}, a rule of the pack's "
                            f"`{DIATAXIS_HEADING}` section")
    return problems


GOOD_REACH = {
    WRITING_REL: (
        f"{DIATAXIS_HEADING}\n"
        "| Kind | The reader needs | The document contains | It leaves out | Directory |\n"
        "| Tutorial | x |\n| How-to guide | x |\n| Reference | x |\n| Explanation | x |\n"
        "Ask: is the reader learning or working, and do they need\n"
        "to do something or to know something?\n"
        "Move text as tasks touch it, never in one pass.\n"
        "2. Create a missing directory with a short index file.\n"
        "3. Keep one line that points to the new place.\n"
        "4. Move nothing else.\n"
        "5. Update the links inside `docs.paths`; list the others under `gaps` with file and line.\n"
        "In audit mode, text in the directory of the wrong kind is a finding.\n"
        "## Mermaid patterns\n"),
    DOCS_WRITER_REL: (
        "## How you write\n\n"
        f"{WRITER_VOICE} Name endpoints.\n\n"
        "## Where the text goes\n\n"
        f"When {DIATAXIS_KEY} is `true`, follow the \"Diátaxis\" section of `conclave:writing-docs`, never\n"
        "anything else. Update links inside `docs.paths`; list the others under `gaps` with file and line.\n"
        f"When {DIATAXIS_KEY} is `false` or absent, this section does not apply.\n\n"
        "## As auditor\n\n"
        f"When {DIATAXIS_KEY} is `true`, text in the directory of the wrong kind is a finding.\n\n"
        "## What you return\n"),
    LEAD_REL: (
        f"4. When the profile has no {DIATAXIS_KEY} and the task is at T1 or above, ask with AskUserQuestion.\n"
        "   Options, recommended first: yes (four directories) or no (existing structure). Say in one line\n"
        "   what you wrote.\n"),
    INIT_REL: (
        f"Ask with AskUserQuestion, recommended first: yes (four directories) or no (existing structure).\n"
        f"Write {DIATAXIS_KEY}, `true` or `false`.\n"),
}


def reach_case(rel, old, new):
    text = GOOD_REACH[rel]
    assert old in text, (rel, old)
    return {**GOOD_REACH, rel: text.replace(old, new, 1)}


BAD_REACH = {
    "the pack without the tutorial kind": (
        reach_case(WRITING_REL, "| Tutorial |", "| Lesson |"), "the tutorial kind"),
    "the pack without the explanation kind": (
        reach_case(WRITING_REL, "| Explanation |", "| Background |"), "the explanation kind"),
    "the pack without what the reader needs": (
        reach_case(WRITING_REL, "The reader needs", "Audience"), "what the reader of each kind needs"),
    "the pack without what each kind contains": (
        reach_case(WRITING_REL, "The document contains", "Content"), "what each kind contains"),
    "the pack without what each kind leaves out": (
        reach_case(WRITING_REL, "It leaves out", "Notes"), "what each kind leaves out"),
    "the pack without the learning-or-working test": (
        reach_case(WRITING_REL, "learning or working", "new"), "(learning or working)"),
    "the pack without the do-or-know test": (
        reach_case(WRITING_REL, "to do something or to know something", "help"), "(do or know)"),
    "the pack creating a directory without an index": (
        reach_case(WRITING_REL, "with a short index file", "as needed"), "with an index file"),
    "the pack moving a section without a pointer": (
        reach_case(WRITING_REL, "Keep one line that points to the new place.", "Delete the old text."),
        "pointing to a moved section's new place"),
    "the pack moving more than the edit": (
        reach_case(WRITING_REL, "4. Move nothing else.\n", "4. Move neighbouring sections too.\n"),
        "forbid moving anything else"),
    "the pack reorganising in one pass": (
        reach_case(WRITING_REL, "as tasks touch it, never in one pass", "all at once"), "in one pass"),
    "the pack leaving links inside docs.paths broken": (
        reach_case(WRITING_REL, "Update the links inside `docs.paths`; list", "List"), "inside `docs.paths`"),
    "the pack listing outside links without file and line": (
        reach_case(WRITING_REL, " with file and line.", "."), "with file and line"),
    "the pack without the audit finding": (
        reach_case(WRITING_REL, "In audit mode, text in the directory of the wrong kind is a finding.\n", ""),
        "an audit finding"),
    "docs-writer.md without its voice rule": (
        reach_case(DOCS_WRITER_REL, WRITER_VOICE, "Write freely."), "no longer says"),
    "docs-writer.md applying Diátaxis when the key is false": (
        reach_case(DOCS_WRITER_REL, f"When {DIATAXIS_KEY} is `false` or absent, this section does not apply.\n", ""),
        "`false` or absent"),
    "docs-writer.md leaving links inside docs.paths broken": (
        reach_case(DOCS_WRITER_REL, "Update links inside `docs.paths`; list", "List"), "inside `docs.paths`"),
    "docs-writer.md listing links without file and line": (
        reach_case(DOCS_WRITER_REL, " with file and line.", "."), "with file and line"),
    "docs-writer.md moving more than the pack allows": (
        reach_case(DOCS_WRITER_REL, ", never\nanything else.", "."), "forbid moving anything"),
    "docs-writer.md auditing without the wrong-kind finding": (
        reach_case(DOCS_WRITER_REL, f"When {DIATAXIS_KEY} is `true`, text in the directory of the wrong kind is a "
                                    "finding.\n\n", ""), "\"As auditor\" does not make"),
    "lead.md without a recommended answer": (
        reach_case(LEAD_REL, "recommended first", "in any order"), f"{LEAD_REL}: the Diátaxis question does not "
                                                                   "recommend"),
    "lead.md without the consequence of no": (
        reach_case(LEAD_REL, "no (existing structure)", "no"), f"{LEAD_REL}: the Diátaxis question does not give "
                                                                "the consequence of no"),
    "lead.md asking at T0": (
        reach_case(LEAD_REL, "the task is at T1 or above", "any task"), "T1 or above"),
    "lead.md writing the profile silently": (
        reach_case(LEAD_REL, " Say in one line\n   what you wrote.", ""), "what it wrote into the profile"),
    "lead.md restating a pack rule": (
        reach_case(LEAD_REL, "(four directories)", "(four directories, each with an index file)"),
        f"{LEAD_REL}: states 'index file'"),
    "docs-writer.md restating a pack rule": (
        reach_case(DOCS_WRITER_REL, "Name endpoints.", "Move from the deepest heading."),
        f"{DOCS_WRITER_REL}: states 'deepest heading'"),
    "init without a recommended answer": (
        reach_case(INIT_REL, "recommended first", "in any order"), f"{INIT_REL}: the Diátaxis question does not "
                                                                   "recommend"),
    "init without the consequence of yes": (
        reach_case(INIT_REL, "yes (four directories)", "yes"), f"{INIT_REL}: the Diátaxis question does not give "
                                                                 "the consequence of yes"),
    "init writing something other than a boolean": (
        reach_case(INIT_REL, "`true` or `false`", "\"yes\" or \"no\""), "as `true` or `false`"),
}

errors_before_reach = len(errors)
if diataxis_reach_problems(GOOD_REACH):
    fail(f"diataxis reach check rejects valid files: {diataxis_reach_problems(GOOD_REACH)}")
for case, (texts, expected) in BAD_REACH.items():
    got = diataxis_reach_problems(texts)
    if len(got) != 1 or expected not in got[0]:
        fail(f"diataxis reach check on {case}: expected one problem containing {expected!r}, got {got}")
for problem in diataxis_reach_problems({rel: (PLUGIN / rel).read_text() for rel in REACH_FILES}):
    fail(problem)
if len(errors) == errors_before_reach:
    ok(f"the Diátaxis pack, docs-writer, lead and init carry every behaviour the acceptance names "
       f"({len(BAD_REACH)} bad variants rejected)")


# The docs-writer checks the links of what it wrote with the plugin's own command, called by its
# bare name: the plugin's bin directory is on the agent's PATH, so the script must ship executable
# (on disk and in git's index, where a clone takes its mode from), or the name is not found. Nothing
# executes the prompt, so each behaviour the acceptance names is guarded by its wording, inside the
# docs-writer's `## Checking links` section only, and the agent must keep the Bash tool that runs it.
LINK_CHECK_REL = "bin/docs-link-check.py"
LINK_CHECK_NAME = "docs-link-check.py"
LINK_CHECK_HEADING = "## Checking links"
LINK_CHECK_AFTER = "## Where the text goes"
LINK_CHECK_RULES = [
    (f"`{LINK_CHECK_NAME}`", "does not name the command"),
    ("After writing or moving documentation", "does not run the command after writing or moving documentation"),
    ("before you return", "does not run the command before it returns"),
    ("from the repository root", "does not run the command from the repository root"),
    ("created, edited, moved or deleted in this task",
     "does not run the command on every documentation file it created, edited, moved or deleted"),
    ("edited only to update a link", "does not pass a file it edited only to update a link"),
    ("the old path of a file you moved or deleted", "does not pass the old path of a file it moved or deleted"),
    ("the links in those files", "does not say the command reports the links in the files given"),
    ("the links to those files", "does not say the command reports the links to the files given"),
    ("Repair every reported link that sits in a file under `docs.paths`",
     "does not repair the reported links in files under `docs.paths`"),
    ("run the command again", "does not run the command again after a repair"),
    ("in a file you may not edit", "does not list under `gaps` a link in a file it may not edit"),
    ("cannot repair", "does not list under `gaps` a link it cannot repair"),
    ("under `gaps` with file, line and target", "does not list a link it leaves under `gaps` with file, line and target"),
    ("do not rewrite text to silence", "no longer forbids rewriting text to silence the check"),
    ("takes files only", "no longer keeps the command to files"),
    ("the old and the new path", "does not pass the old and the new path of what it moved under Diátaxis"),
    ("In audit mode, run it", "does not run the command in audit mode"),
    ("report each line it prints as a correction", "does not report a broken link as a correction in audit mode"),
    ("When the command is not found, say so under `gaps`", "does not say what to do when the command is not found"),
    ("check by hand", "does not check the links by hand when the command is not found"),
    # A directory argument is misuse, and the old path of a moved directory names no file the
    # command can match, so a moved or deleted directory is passed as the files it held.
    ("passed as every file it held", "does not pass a moved or deleted directory as the files it held"),
    ("each by its old path and its new path", "does not pass each file of a moved directory by its old and new path"),
    ("never as the directory itself", "does not forbid passing a directory"),
    # Misuse prints usage on stderr and nothing on stdout, which reads as a clean run unless the
    # agent is told what each exit code means.
    ("Exit code 0 means every link resolves", "does not say that exit code 0 is a pass"),
    ("exit code 1 means each printed line needs handling", "does not say that exit code 1 means handling each line"),
    ("Any other exit code", "does not say what any other exit code means"),
    ("is not a pass", "does not say that a failed run is not a pass"),
    ("fix the arguments and run it again", "does not fix its arguments and run again after a failed run"),
    ("handle it as a command that cannot be found", "does not fall back when the command keeps failing"),
    # Exit code 3 prints real broken links and names an unreadable file on stderr; read as "any
    # other exit code", both would be dropped for a check by hand.
    ("Exit code 3 means a file could not be read", "does not say what exit code 3 means"),
    ("handle each printed line as for exit code 1", "does not handle the lines printed with exit code 3"),
    ("each file a `cannot read` line on stderr names under `gaps`",
     "does not list under `gaps` a file the command could not read"),
    ("do not count the run as a pass", "does not say that a run with exit code 3 is not a pass"),
    ("each file a `cannot read` line on stderr names as a correction",
     "does not have the auditor report a file the command could not read as a correction"),
    # These two kinds are not fixed by correcting a path, and the tempting fix is outside `docs.paths`.
    ("`ignored by git` or `outside the repository`", "does not say how to repair a link to an ignored or outside target"),
    ("pointing it at a tracked file that carries the same content",
     "does not repair an ignored or outside target by pointing at a tracked file"),
    ("never change ignore rules", "no longer forbids changing ignore rules to silence an ignored target"),
    # The auditor returns `corrections` only: each printed line maps onto one, and its fallback
    # cannot be `gaps`.
    ("`file` is the linking file", "does not map a printed line onto a correction's `file`"),
    ("`quoted` the link as written with its line", "does not map a printed line onto a correction's `quoted`"),
    ("`true_statement` the target that exists when the diff shows it was renamed or moved",
     "does not map a printed line onto a correction's `true_statement`"),
    ("`evidence` the printed line", "does not map a printed line onto a correction's `evidence`"),
    ("not found or keeps failing in audit mode", "does not say what the auditor does when the command is not found or fails"),
    ("look up by hand", "does not have the auditor check the links by hand without the command"),
    ("report each broken one as a correction", "does not have the auditor report a link it checked by hand as a correction"),
]
# A path to the command ties the prompt to one layout of the plugin; the contract calls it by name.
LINK_CHECK_FORBIDDEN = [(f"/{LINK_CHECK_NAME}", "calls the command by a path instead of its bare name")]


def link_check_script_problems(on_disk, executable, git_mode):
    """Every way the link check script fails to ship runnable; git_mode is its index mode, None
    while it is untracked."""
    rel = f"plugins/conclave/{LINK_CHECK_REL}"
    if not on_disk:
        return [f"{rel}: missing; the docs-writer runs it by name"]
    problems = []
    if not executable:
        problems.append(f"{rel}: not executable on disk, so the docs-writer cannot run it by name")
    if git_mode is not None and git_mode != "100755":
        problems.append(f"{rel}: tracked with mode {git_mode}, not 100755, so a clone cannot run it by name")
    return problems


def link_check_writer_problems(text):
    """Every way docs-writer.md drops a behaviour of the link check, one message each, naming the file."""
    problems = []
    tools = anchored_line(text, "tools:")
    if tools is None or "Bash" not in [t.strip() for t in tools.removeprefix("tools:").split(",")]:
        problems.append(f"{DOCS_WRITER_REL}: the `tools` line does not grant Bash, which runs {LINK_CHECK_NAME}")
    lines = [line.rstrip() for line in text.splitlines()]
    checking = section(lines, LINK_CHECK_HEADING)
    if checking is None:
        problems.append(f"{DOCS_WRITER_REL}: no `{LINK_CHECK_HEADING}` section")
        return problems
    if LINK_CHECK_AFTER not in lines or lines.index(LINK_CHECK_AFTER) > lines.index(LINK_CHECK_HEADING):
        problems.append(f"{DOCS_WRITER_REL}: `{LINK_CHECK_HEADING}` does not come after `{LINK_CHECK_AFTER}`")
    body = " ".join(line.strip() for line in checking)
    for needle, why in LINK_CHECK_RULES:
        if needle not in body:
            problems.append(f"{DOCS_WRITER_REL}: `{LINK_CHECK_HEADING}` {why} (missing {needle!r})")
    for needle, why in LINK_CHECK_FORBIDDEN:
        if needle in body:
            problems.append(f"{DOCS_WRITER_REL}: `{LINK_CHECK_HEADING}` {why} (found {needle!r})")
    return problems


GOOD_LINK_CHECK_WRITER = (
    "---\nname: docs-writer\ntools: Read, Edit, Bash, Skill\n---\n"
    f"{LINK_CHECK_AFTER}\n\nPut the text where it belongs.\n\n"
    f"{LINK_CHECK_HEADING}\n\n"
    f"After writing or moving documentation, and before you return, run `{LINK_CHECK_NAME}` from the repository root "
    "with every file you created, edited, moved or deleted in this task: a file you edited only to update a link, "
    "and the old path of a file you moved or deleted. A directory is passed as every file it held, each by its old "
    "path and its new path, never as the directory itself. It lists the links in those files and the links to those "
    "files. Exit code 0 means every link resolves, exit code 1 means each printed line needs handling. Exit code 3 "
    "means a file could not be read: handle each printed line as for exit code 1, list each file a `cannot read` "
    "line on stderr names under `gaps`, and do not count the run as a pass. Any other "
    "exit code is not a pass: fix the arguments and run it again, then handle it as a command that cannot be found. "
    "Repair every reported link that sits in a file under `docs.paths`, then run the command again. A link reported "
    "as `ignored by git` or `outside the repository` is repaired by pointing it at a tracked file that carries the "
    "same content; never change ignore rules. A link in a file you may not edit, and one you cannot repair, goes "
    "under `gaps` with file, line and target; do not rewrite text to silence the check. It takes files only. Under "
    "Diátaxis pass the old and the new path. When the command is not found, say so under `gaps` and check by hand.\n\n"
    "In audit mode, run it and report each line it prints as a correction: `file` is the linking file, `quoted` the "
    "link as written with its line, `true_statement` the target that exists when the diff shows it was renamed or "
    "moved, `evidence` the printed line. On exit code 3, also report each file a `cannot read` line on stderr "
    "names as a correction. When the command is not found or keeps failing in audit mode, look up by "
    "hand and report each broken one as a correction.\n\n"
    "## As auditor\n\nAudit the docs.\n")


def link_writer_case(old, new):
    """GOOD_LINK_CHECK_WRITER with its one occurrence of old replaced by new."""
    assert GOOD_LINK_CHECK_WRITER.count(old) == 1, old
    return GOOD_LINK_CHECK_WRITER.replace(old, new)


BAD_LINK_CHECK_WRITER = {f"docs-writer.md without {needle!r}": (link_writer_case(needle, ""), f"(missing {needle!r})")
                         for needle, _ in LINK_CHECK_RULES}
BAD_LINK_CHECK_WRITER.update({
    "docs-writer.md without the section": (
        link_writer_case(LINK_CHECK_HEADING, "## Links"), f"no `{LINK_CHECK_HEADING}` section"),
    "docs-writer.md with the section before Where the text goes": (
        link_writer_case(LINK_CHECK_AFTER, "## Placement").replace("## As auditor", LINK_CHECK_AFTER, 1),
        "does not come after"),
    "docs-writer.md calling the command by a path": (
        link_writer_case("In audit mode, run it", f"In audit mode, run it as `${{CLAUDE_PLUGIN_ROOT}}/bin/{LINK_CHECK_NAME}`"),
        "by a path instead of its bare name"),
    "docs-writer.md without Bash": (
        link_writer_case("tools: Read, Edit, Bash, Skill", "tools: Read, Edit, Skill"), "does not grant Bash"),
    # A rule that survives only outside the section does not count.
    "docs-writer.md with the fallback moved to As auditor": (
        link_writer_case("say so under `gaps` and check by hand.", "say so under `gaps`.").replace(
            "Audit the docs.", "Check by hand: check by hand."),
        "(missing 'check by hand')"),
})
BAD_LINK_CHECK_SCRIPT = {
    "the script missing": ((False, False, None), "missing"),
    "the script not executable on disk": ((True, False, None), "not executable on disk"),
    "the script tracked without its executable bit": ((True, True, "100644"), "tracked with mode 100644"),
}

errors_before_link_check = len(errors)
for args in [(True, True, None), (True, True, "100755")]:
    if link_check_script_problems(*args):
        fail(f"link check script check rejects a runnable script {args}: {link_check_script_problems(*args)}")
if link_check_writer_problems(GOOD_LINK_CHECK_WRITER):
    fail(f"link check writer check rejects a valid docs-writer.md: {link_check_writer_problems(GOOD_LINK_CHECK_WRITER)}")
for case, (args, expected) in BAD_LINK_CHECK_SCRIPT.items():
    got = link_check_script_problems(*args)
    if len(got) != 1 or expected not in got[0] or not got[0].startswith(f"plugins/conclave/{LINK_CHECK_REL}:"):
        fail(f"link check script check on {case}: expected one problem containing {expected!r}, got {got}")
for case, (text, expected) in BAD_LINK_CHECK_WRITER.items():
    got = link_check_writer_problems(text)
    if len(got) != 1 or expected not in got[0] or not got[0].startswith(f"{DOCS_WRITER_REL}:"):
        fail(f"link check writer check on {case}: expected one problem containing {expected!r}, got {got}")
link_script = PLUGIN / LINK_CHECK_REL
index_entry = subprocess.run(["git", "ls-files", "--stage", "--", str(link_script.relative_to(ROOT))],
                             cwd=ROOT, capture_output=True, text=True).stdout.split()
for problem in (link_check_script_problems(link_script.is_file(), os.access(link_script, os.X_OK),
                                           index_entry[0] if index_entry else None)
                + link_check_writer_problems((PLUGIN / DOCS_WRITER_REL).read_text())):
    fail(problem)
if len(errors) == errors_before_link_check:
    ok(f"{LINK_CHECK_NAME} ships executable and the docs-writer runs it as the acceptance names "
       f"({len(BAD_LINK_CHECK_SCRIPT) + len(BAD_LINK_CHECK_WRITER)} bad variants rejected)")


# The lead's standing rules are stated once, in a numbered `## Rules` section near the top of
# lead.md, which is the authority; the procedure sections say how to apply them. The titles and
# their order are fixed (the first four always hold, the next seven follow the order in which a
# task meets them, the last is about the lead's own work), the two passages that used to state
# rules elsewhere stay gone, and each rule keeps what the acceptance criteria name. The procedure
# sections that close a gap carry it too: the T2 checkpoint stop prints a recommendation with each
# Unknown, the preflight proposes the branch from `profile.base` and covers another task's branch,
# the approval gate gives the mode advice, and the Commit proposal stages files by name and asks
# about the push in a paragraph of its own, after the commit question, naming no hosting service.
# The README mirrors the list in a table for the user; its first column must hold the same titles
# in the same order. Nothing executes these prompts, so the wording is guarded.
README_REL = "README.md"
PLAN_TEMPLATE_REL = "templates/plan.md"
RULES_HEADING = "## Rules"
RULES_BEFORE = "## Before anything"
RULE_TITLES = ["Plan first", "Functional over technical", "The user's word", "Guardrails", "Small slices",
               "Tier before tokens", "Branch", "Unknowns with a recommendation", "After approval", "Commits",
               "Push and pull request", "Your own work"]
RULE_ITEM = re.compile(r"^(\d+)\. \*\*(.+?)\.\*\* (.*)$")
RETIRED_RULE_PASSAGES = ["Two rules sit above everything else"]
# What each rule must still say, searched in its text after the bold title (A2 to A10).
RULE_NEEDLES = {
    "Plan first": ["approves the plan document", "at any tier above T0", "at any pace"],
    "Functional over technical": ["The functional spec is the authority", "traces to no goal or acceptance criterion",
                                  "candidate for a later task", "do not build it"],
    "The user's word": ["only these", "confirming the Analysis", "approving the plan", "each decision",
                        "the go after a stage at pace `step`", "creating a branch", "creating the commits",
                        "pushing and opening the pull request", "a prompt a guardrail raises", "`commit-approval`",
                        "`pii`", "every question a section below puts to the user", "Never guess an answer",
                        "never reopened"],
    "Guardrails": ["never work around one", "`CONCLAVE_ALLOW`", "rewriting history", "exact commands",
                   "secret or personal value left as a placeholder"],
    "Small slices": ["several independent changes", "separate tasks", "one at a time"],
    "Tier before tokens": ["before spending", "after each stage", "more than half"],
    "Branch": ["`profile.base`", "another task", "the default branch", "user's yes",
               "branch from the current commit or to stay", "follow the answer", "before the first edit at every tier",
               "a dirty tree is settled before any switch"],
    "Unknowns with a recommendation": ["analysis checkpoint", "what would settle it", "recommendation"],
    "After approval": ["approval gate", "accepts edits without asking", "still wait for their word",
                       "a shell command can still raise a permission prompt", "switch back",
                       "Never change the mode or a permission setting yourself"],
    "Commits": ["Never run `git commit` without the user's approval", "`commit-approval`", "by name",
                "never the whole tree", "Subagents never commit", "`subagent-no-git`"],
    "Push and pull request": ["Never run `git push` without the user's approval", "`commit-approval`",
                              "`protect-history`", "After the last commit", "separate question",
                              "push the branch and open the pull request"],
    "Your own work": ["No shortcuts", "the checklist the reviewers apply", "two or three sentences", "with the reason",
                      "fix it as part of the task"],
}
# The line above the first rule that says how to read their order.
READING_ORDER_NEEDLES = ["Rules 1 to 4", "rules 5 to 11", "rule 12"]
# The procedure blocks that close a gap: (name, the start of the block in lead.md, what it must say).
# The branch starts at `profile.base`, a remote-tracking ref by default; without `--no-track` that
# ref becomes the new branch's upstream and a plain push aims at the default branch. The push then
# sets the upstream itself.
PUSH_PARAGRAPH = "After the last commit"
PREFLIGHT_BRANCH = "- **Branch.**"
PREFLIGHT_CLEAN_TREE = "- **Clean tree.**"
APPROVAL_GATE = "**The approval gate.**"
# The dirty tree is settled before the switch, or another task's uncommitted work follows onto the
# new branch; a branch belongs to another task by the Branch line of its plan document (a run JSON
# has no branch of its own); the user may keep stacked work on that branch; T0 and T1 settle the
# branch before their first edit too, and the commit proposal catches a proposal not made yet.
PROCEDURE_NEEDLES = [
    ("the T2 checkpoint stop", "- At T2, stop:", ["what would settle it", "recommendation"]),
    ("the test for another task's branch", "2. Read the task",
     ["belongs to another task", "`- **Branch:**` line of another task's plan document", "`plan_doc`",
      "`git log --oneline <profile.base>..HEAD`"]),
    ("the preflight's clean-tree bullet", PREFLIGHT_CLEAN_TREE,
     ["on the current branch", "before the *Branch* proposal", "before any switch"]),
    ("the preflight's branch bullet", PREFLIGHT_BRANCH,
     ["`profile.base`", "another task", "--no-track -c <prefix><short-topic> <profile.base>`",
      "after the *Clean tree* answer", "`git switch -c <prefix><short-topic>`", "staying on it"]),
    ("the T0 and T1 branch step", "4. Before the first edit",
     ["settle the branch", "another task's branch", "dirty tree first", "say which branch you stay on"]),
    ("the approval gate", APPROVAL_GATE, ["accepts edits without asking", "*The user's word*"]),
    ("the push paragraph of the Commit proposal", PUSH_PARAGRAPH,
     ["separate question", "`git push -u <remote> <branch>`", "no remote", "push alone",
      "switch the permission mode back"]),
]
COMMIT_NEEDLES = ["by name", "never `git add -A`",
                  "On the default branch or on another task's branch, make the proposal of the *Branch* rule first"]
COMMIT_QUESTION = "wait for the user to approve"
TEMPLATE_UNKNOWNS = "- <what is not known"
HOSTING_NAMES = ["github", "gitlab", "bitbucket", "gitea", "`gh`", "`gh ", "`glab", "merge request"]
# A sentence of a rule this long or longer that another rule repeats word for word is a rule stated twice.
REPEATED_SENTENCE_MIN = 25


def rule_items(lead_text):
    """The (number, title, body) of each numbered item in the first `## Rules` section of lead_text,
    with the lines that start an item but do not open with a bold title as (number, None, line)."""
    rules = section([line.rstrip() for line in lead_text.splitlines()], RULES_HEADING)
    items = []
    for block in blocks("\n".join(rules or [])):
        if not re.match(r"^\d+\. ", block):
            continue
        found = RULE_ITEM.match(block)
        items.append((int(found.group(1)), found.group(2), found.group(3)) if found
                     else (int(block.split(".", 1)[0]), None, block))
    return items


def rules_section_problems(lead_text):
    """Every way lead.md breaks the layout of its standing rules, one message each."""
    lines = [line.rstrip() for line in lead_text.splitlines()]
    problems = []
    count = lines.count(RULES_HEADING)
    if count == 0:
        return [f"{LEAD_REL}: no `{RULES_HEADING}` section"]
    if count > 1:
        problems.append(f"{LEAD_REL}: {count} `{RULES_HEADING}` sections; the standing rules are stated once")
    if RULES_BEFORE not in lines:
        problems.append(f"{LEAD_REL}: no `{RULES_BEFORE}` section to place `{RULES_HEADING}` before")
    elif lines.index(RULES_HEADING) > lines.index(RULES_BEFORE):
        problems.append(f"{LEAD_REL}: `{RULES_HEADING}` comes after `{RULES_BEFORE}`; the rules open the prompt")
    items = rule_items(lead_text)
    untitled = [number for number, title, _ in items if title is None]
    if untitled:
        problems.append(f"{LEAD_REL}: rule {', '.join(map(str, untitled))} does not open with a bold title "
                        "(`N. **Title.** text`)")
    numbers = [number for number, _, _ in items]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"{LEAD_REL}: the rules are numbered {numbers}, not 1 to {len(numbers)}")
    titles = [title for _, title, _ in items if title is not None]
    missing = [t for t in RULE_TITLES if t not in titles]
    unexpected = [t for t in titles if t not in RULE_TITLES]
    repeated = sorted({t for t in titles if titles.count(t) > 1})
    if missing or unexpected or repeated:
        parts = [f"{label} {names}" for label, names in
                 (("missing", missing), ("unexpected", unexpected), ("repeated", repeated)) if names]
        problems.append(f"{LEAD_REL}: the `{RULES_HEADING}` titles differ from the expected {len(RULE_TITLES)}: "
                        f"{', '.join(parts)}")
    elif titles != RULE_TITLES:
        problems.append(f"{LEAD_REL}: the `{RULES_HEADING}` titles are out of order: {titles}, expected {RULE_TITLES}")
    for passage in RETIRED_RULE_PASSAGES:
        if passage in lead_text:
            problems.append(f"{LEAD_REL}: still says {passage!r}; the `{RULES_HEADING}` list states every rule")
    return problems


def rule_content_problems(texts):
    """Every needle of RULE_NEEDLES, READING_ORDER_NEEDLES, PROCEDURE_NEEDLES, COMMIT_NEEDLES and the
    template placeholder that the files (relative path -> text) no longer carry, a sentence two rules
    both say, every hosting service the rules or the procedure blocks this task changed name, and a
    push asked in the commit question, one message each."""
    lead_text = texts[LEAD_REL]
    problems = []
    bodies = {title: body for _, title, body in rule_items(lead_text) if title is not None}
    for title, needles in RULE_NEEDLES.items():
        if title not in bodies:
            continue
        for needle in needles:
            if needle not in bodies[title]:
                problems.append(f"{LEAD_REL}: the rule *{title}* no longer says {needle!r}")
    said_by = {}
    for title, body in bodies.items():
        for sentence in re.split(r"(?<=[.;:])\s+", body):
            sentence = sentence.strip()
            if len(sentence) < REPEATED_SENTENCE_MIN:
                continue
            first = said_by.setdefault(sentence, title)
            if first != title:
                problems.append(f"{LEAD_REL}: *{first}* and *{title}* both say {sentence!r}; state a rule once")

    rules = "\n".join(section([line.rstrip() for line in lead_text.splitlines()], RULES_HEADING) or [])
    reading = next((b for b in blocks(rules) if not re.match(r"^\d+\. ", b)), "")
    for needle in READING_ORDER_NEEDLES:
        if needle not in reading:
            problems.append(f"{LEAD_REL}: the line above the first rule no longer says {needle!r} "
                            "(how to read the order)")

    commit = LEAD_COMMIT.search(lead_text)
    commit_blocks = blocks(commit.group(1)) if commit else []
    lead_blocks = blocks(lead_text)
    for name, start, needles in PROCEDURE_NEEDLES:
        pool = commit_blocks if start == PUSH_PARAGRAPH else lead_blocks
        block = next((b for b in pool if b.startswith(start)), None)
        if block is None:
            why = (", so the push has no question of its own after the commit question"
                   if start == PUSH_PARAGRAPH else "")
            problems.append(f"{LEAD_REL}: no block starting {start!r} ({name}){why}")
            continue
        for needle in needles:
            if needle not in block:
                problems.append(f"{LEAD_REL}: {name} no longer says {needle!r}")
    starts = [next((i for i, b in enumerate(lead_blocks) if b.startswith(start)), None)
              for start in (PREFLIGHT_CLEAN_TREE, PREFLIGHT_BRANCH)]
    if None not in starts and starts[0] > starts[1]:
        problems.append(f"{LEAD_REL}: the preflight asks about the branch before the dirty tree; settle the tree "
                        "before any switch")
    if commit is None:
        problems.append(f"{LEAD_REL}: no `## Commit proposal` section")
    else:
        for needle in COMMIT_NEEDLES:
            if needle not in commit.group(1):
                problems.append(f"{LEAD_REL}: the Commit proposal no longer says {needle!r}")
        question = next((b for b in commit_blocks if COMMIT_QUESTION in b), None)
        if question is None:
            problems.append(f"{LEAD_REL}: the Commit proposal no longer says {COMMIT_QUESTION!r}")
        elif re.search(r"\bpush", question, re.I):
            problems.append(f"{LEAD_REL}: the Commit proposal asks about the push in the commit question; "
                            "the push is a separate question after the last commit")

    changed = [("the `## Rules` section", rules), ("the Commit proposal", commit.group(1) if commit else "")]
    changed += [(name, next((b for b in lead_blocks if b.startswith(start)), ""))
                for name, start, _ in PROCEDURE_NEEDLES if start in (PREFLIGHT_BRANCH, APPROVAL_GATE)]
    for where, text in changed:
        named = [n for n in HOSTING_NAMES if n in text.lower()]
        if named:
            problems.append(f"{LEAD_REL}: {where} names a hosting service or its tool ({', '.join(named)})")

    placeholder = anchored_line(texts[PLAN_TEMPLATE_REL], TEMPLATE_UNKNOWNS)
    if placeholder is None:
        problems.append(f"{PLAN_TEMPLATE_REL}: no Unknowns placeholder starting {TEMPLATE_UNKNOWNS!r}")
    elif "recommendation" not in placeholder:
        problems.append(f"{PLAN_TEMPLATE_REL}: the Unknowns placeholder no longer names the lead's 'recommendation'")
    return problems


def readme_rule_rows(readme_text):
    """The first cell of each data row of the table under `## Rules` in readme_text; None when the
    section or its table is missing."""
    rules = section([line.rstrip() for line in readme_text.splitlines()], RULES_HEADING)
    rows = [line for line in rules or [] if line.startswith("|")]
    separator = next((i for i, row in enumerate(rows) if re.fullmatch(r"\|[\s:|-]+\|", row)), None)
    if separator is None:
        return None
    return [row.split("|")[1].strip() for row in rows[separator + 1:]]


def rules_mirror_problems(lead_text, readme_text):
    """Every way the README's `## Rules` table differs from the titles of lead.md, one message each."""
    rows = readme_rule_rows(readme_text)
    if rows is None:
        return [f"{README_REL}: no table under `{RULES_HEADING}` to mirror the rules of {LEAD_REL}"]
    titles = [title for _, title, _ in rule_items(lead_text) if title is not None]
    problems = [f"{README_REL}: the `{RULES_HEADING}` table has no row for {t!r}, a rule of {LEAD_REL}"
                for t in titles if t not in rows]
    problems += [f"{README_REL}: the `{RULES_HEADING}` table has a row {r!r} that {LEAD_REL} lacks"
                 for r in rows if r not in titles]
    if not problems and rows != titles:
        problems.append(f"{README_REL}: the `{RULES_HEADING}` rows {rows} differ in order or count from the rules "
                        f"of {LEAD_REL} {titles}")
    return problems


GOOD_RULE_BODIES = {
    "Plan first": "Nothing is built before the user approves the plan document, at any tier above T0 and at any pace.",
    "Functional over technical": (
        "The functional spec is the authority. Whatever traces to no goal or acceptance criterion is logged as a "
        "candidate for a later task; do not build it."),
    "The user's word": (
        "Wait for the user's word on only these: confirming the Analysis, approving the plan, each decision, the go "
        "after a stage at pace `step`, creating a branch, creating the commits, pushing and opening the pull "
        "request, and a prompt a guardrail raises (`commit-approval`, `pii`). A decision is every question a "
        "section below puts to the user. Never guess an answer; a decision is never reopened."),
    "Guardrails": (
        "A denial: never work around one; the user sets `CONCLAVE_ALLOW`. When one blocks rewriting history, give "
        "the exact commands, any secret or personal value left as a placeholder."),
    "Small slices": "A request with several independent changes is proposed as separate tasks, run one at a time.",
    "Tier before tokens": "Say the tier before spending and the count after each stage; explain more than half over.",
    "Branch": (
        "Not on the default branch: propose one from `profile.base` on the user's yes. On another task's, offer to "
        "branch from the current commit or to stay, and follow the answer; before the first edit at every tier, and "
        "a dirty tree is settled before any switch."),
    "Unknowns with a recommendation": (
        "At the analysis checkpoint, each Unknown with what would settle it and your recommendation."),
    "After approval": (
        "At the approval gate, say the mode that accepts edits without asking and what will still wait for their "
        "word; say that a shell command can still raise a permission prompt; switch back at the end. Never change "
        "the mode or a permission setting yourself."),
    "Commits": (
        "Never run `git commit` without the user's approval; `commit-approval` asks. Stage by name, never the "
        "whole tree. Subagents never commit; `subagent-no-git`."),
    "Push and pull request": (
        "Never run `git push` without the user's approval; `commit-approval` asks and `protect-history` guards the "
        "default branch. After the last commit, a separate question: push the branch and open the pull request."),
    "Your own work": (
        "No shortcuts; the checklist the reviewers apply applies to you. Reports in two or three sentences, a "
        "wrong finding with the reason, and fix it as part of the task when the profile is wrong."),
}
GOOD_RULES_PIECES = {
    "opening": "You lead a team.\n\n",
    "rules": RULES_HEADING + "\n\nRules 1 to 4 always hold, rules 5 to 11 follow the task, rule 12 is yours.\n\n",
    "before": (f"{RULES_BEFORE}\n\n1. Read the profile.\n2. Read the task. A branch belongs to another task when "
               "the `- **Branch:**` line of another task's plan document names it (via `plan_doc`) or by "
               "`git log --oneline <profile.base>..HEAD`.\n\n"),
    "preflight": ("## Preflight\n\n- **Clean tree.** Ask about a dirty tree, committing on the current branch, "
                  "before the *Branch* proposal, acting before any switch.\n"
                  "- **Branch.** Apply *Branch* after the *Clean tree* answer: from `profile.base`, also on another "
                  "task, propose `git switch --no-track -c <prefix><short-topic> <profile.base>`, or "
                  "`git switch -c <prefix><short-topic>` or staying on it.\n\n"),
    "solo": ("## T0 and T1\n\n4. Before the first edit, settle the branch: on another task's branch, the dirty tree "
             "first; else say which branch you stay on.\n\n"),
    "checkpoint": "## The plan document\n\n- At T2, stop: the Unknowns, each with what would settle it and your "
                  "recommendation.\n\n",
    "gate": "**The approval gate.** Say they can switch to the mode that accepts edits without asking, and list the "
            "items of *The user's word* still ahead.\n\n",
    "commit": ("## Commit proposal\n\nOn the default branch or on another task's branch, make the proposal of the "
               "*Branch* rule first. Stage each file by name, never `git add -A`. Show the messages and wait for the "
               "user to approve.\n\n"),
    "push": f"{PUSH_PARAGRAPH}, ask as a separate question, `git push -u <remote> <branch>`; skip it with no remote, "
            "offer the push alone without a tool, then remind them to switch the permission mode back.\n",
}
GOOD_TEMPLATE_UNKNOWNS = f"### Unknowns\n\n{TEMPLATE_UNKNOWNS}, what would settle it, and the lead's recommendation>\n"


def standing_lead(bodies=None, titles=None, **pieces):
    """A lead.md built from the good pieces, with bodies, titles (the order of the list) and named
    pieces replaced."""
    bodies = {**GOOD_RULE_BODIES, **(bodies or {})}
    parts = {**GOOD_RULES_PIECES, **pieces}
    rules = "".join(f"{n}. **{t}.** {bodies.get(t, 'Text.')}\n" for n, t in enumerate(titles or RULE_TITLES, 1))
    return (parts["opening"] + parts["rules"] + rules + "\n" + parts["before"] + parts["preflight"]
            + parts["checkpoint"] + parts["gate"] + parts["solo"] + parts["commit"] + parts["push"])


def standing_readme(rows=None):
    lines = ["# Conclave", "", RULES_HEADING, "", "| Rule | What it means | Enforced by |", "|---|---|---|"]
    lines += [f"| {row} | text | the lead |" for row in (RULE_TITLES if rows is None else rows)]
    return "\n".join(lines + ["", "## Tiers", ""])


def piece_without(name, needle):
    assert needle in GOOD_RULES_PIECES[name], (name, needle)
    return {name: GOOD_RULES_PIECES[name].replace(needle, "")}


GOOD_STANDING = standing_lead()
SWAPPED = RULE_TITLES[:4] + [RULE_TITLES[5], RULE_TITLES[4]] + RULE_TITLES[6:]
BAD_RULES_SECTION = {
    "a title removed": (standing_lead(titles=[t for t in RULE_TITLES if t != "Small slices"]), "'Small slices'"),
    "a title renamed": (
        standing_lead(titles=[("Approval" if t == "After approval" else t) for t in RULE_TITLES]),
        "missing ['After approval'], unexpected ['Approval']"),
    "a title repeated": (standing_lead(titles=RULE_TITLES + ["Commits"]), "repeated ['Commits']"),
    "two titles swapped": (standing_lead(titles=SWAPPED), "out of order"),
    "a second `## Rules` section at the end": (GOOD_STANDING + f"\n{RULES_HEADING}\n\n- Say the tier.\n",
                                               "2 `## Rules` sections"),
    "the section placed after `## Before anything`": (
        standing_lead(opening=GOOD_RULES_PIECES["opening"] + GOOD_RULES_PIECES["before"], before=""),
        "comes after `## Before anything`"),
    "no `## Rules` section": (GOOD_STANDING.replace(RULES_HEADING, "## Principles"), "no `## Rules` section"),
    # An item without a bold title has no title either, so the title it held is missing too.
    "a rule without a bold title": (GOOD_STANDING.replace("5. **Small slices.**", "5. Small slices:"),
                                    ["rule 5 does not open with a bold title", "missing ['Small slices']"]),
    "the rules misnumbered": (GOOD_STANDING.replace("7. **Branch.**", "8. **Branch.**"), "numbered"),
    "the two-rules paragraph still present": (
        GOOD_STANDING.replace("You lead a team.", "You lead a team. Two rules sit above everything else."),
        "still says 'Two rules sit above everything else'"),
}
BAD_RULE_CONTENT = {
    f"*{title}* without {needle!r}": (
        {LEAD_REL: standing_lead(bodies={title: GOOD_RULE_BODIES[title].replace(needle, "")}),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        f"the rule *{title}* no longer says {needle!r}")
    for title, needles in RULE_NEEDLES.items() for needle in needles
}
for name, start, needles in PROCEDURE_NEEDLES:
    piece = next(key for key, text in GOOD_RULES_PIECES.items() if start in text)
    for needle in needles:
        BAD_RULE_CONTENT[f"{name} without {needle!r}"] = (
            {LEAD_REL: standing_lead(**piece_without(piece, needle)), PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
            f"{name} no longer says {needle!r}")
for needle in READING_ORDER_NEEDLES:
    BAD_RULE_CONTENT[f"the reading-order line without {needle!r}"] = (
        {LEAD_REL: standing_lead(**piece_without("rules", needle)), PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        f"the line above the first rule no longer says {needle!r}")
for needle in COMMIT_NEEDLES:
    BAD_RULE_CONTENT[f"the Commit proposal without {needle!r}"] = (
        {LEAD_REL: standing_lead(**piece_without("commit", needle)), PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        f"the Commit proposal no longer says {needle!r}")
BAD_RULE_CONTENT.update({
    "the push asked in the commit question": (
        {LEAD_REL: standing_lead(commit=GOOD_RULES_PIECES["commit"].replace(
            "to approve.", "to approve the commits and the push."), push=""),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "commit question"),
    "the push paragraph merged into the commit question": (
        {LEAD_REL: standing_lead(commit=GOOD_RULES_PIECES["commit"].rstrip("\n") + " "),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "commit question"),
    "a hosting service named in the rules": (
        {LEAD_REL: standing_lead(bodies={"Push and pull request": GOOD_RULE_BODIES["Push and pull request"]
                                         + " Open it on GitHub."}),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "the `## Rules` section names a hosting service or its tool (github)"),
    "a hosting service named in the preflight's branch bullet": (
        {LEAD_REL: standing_lead(preflight=GOOD_RULES_PIECES["preflight"].replace("also on", "on GitLab, also on")),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "the preflight's branch bullet names a hosting service or its tool (gitlab)"),
    "the branch asked before the dirty tree": (
        {LEAD_REL: standing_lead(preflight="\n".join(
            [GOOD_RULES_PIECES["preflight"].splitlines()[i] for i in (0, 1, 3, 2)]) + "\n\n"),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "asks about the branch before the dirty tree"),
    "a hosting service named in the approval gate": (
        {LEAD_REL: standing_lead(gate=GOOD_RULES_PIECES["gate"].replace("still ahead.", "still ahead on Bitbucket.")),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "the approval gate names a hosting service or its tool (bitbucket)"),
    "a sentence two rules both say": (
        {LEAD_REL: standing_lead(bodies={
            title: GOOD_RULE_BODIES[title] + " `protect-history` blocks a push to the default branch."
            for title in ("Branch", "Push and pull request")}),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "*Branch* and *Push and pull request* both say '`protect-history` blocks a push to the default branch.'"),
    "a hosting tool named in the Commit proposal": (
        {LEAD_REL: standing_lead(push=GOOD_RULES_PIECES["push"].replace("without a tool", "without `gh pr create`")),
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS},
        "the Commit proposal names a hosting service or its tool (`gh )"),
    "the template placeholder without the recommendation": (
        {LEAD_REL: GOOD_STANDING,
         PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS.replace(", and the lead's recommendation", "")},
        "no longer names the lead's 'recommendation'"),
    "the template without the Unknowns placeholder": (
        {LEAD_REL: GOOD_STANDING, PLAN_TEMPLATE_REL: "### Unknowns\n\n- (none)\n"}, "no Unknowns placeholder"),
})
LEAD_WITHOUT_SLICES = standing_lead(titles=[t for t in RULE_TITLES if t != "Small slices"])
BAD_RULES_MIRROR = {
    "a row missing from the README": (
        (GOOD_STANDING, standing_readme([t for t in RULE_TITLES if t != "Branch"])), "no row for 'Branch'"),
    "an extra row in the README": (
        (GOOD_STANDING, standing_readme(RULE_TITLES + ["Be kind"])), "a row 'Be kind' that agents/lead.md lacks"),
    "the README rows in another order": ((GOOD_STANDING, standing_readme(SWAPPED)), "differ in order"),
    "a README row repeated": ((GOOD_STANDING, standing_readme(RULE_TITLES + ["Commits"])), "differ in order or count"),
    "a rule missing from lead.md": (
        (LEAD_WITHOUT_SLICES, standing_readme()), "a row 'Small slices' that agents/lead.md lacks"),
    "a rule only in lead.md": (
        (standing_lead(titles=RULE_TITLES + ["Be kind"]), standing_readme()), "no row for 'Be kind'"),
    "no table in the README": ((GOOD_STANDING, f"# Conclave\n\n{RULES_HEADING}\n\nSee lead.md.\n"), "no table"),
}

errors_before_rules = len(errors)
GOOD_RULE_TEXTS = {LEAD_REL: GOOD_STANDING, PLAN_TEMPLATE_REL: GOOD_TEMPLATE_UNKNOWNS}
for problem in (rules_section_problems(GOOD_STANDING) + rule_content_problems(GOOD_RULE_TEXTS)
                + rules_mirror_problems(GOOD_STANDING, standing_readme())):
    fail(f"standing rules check rejects valid files: {problem}")
for case, (text, expected) in BAD_RULES_SECTION.items():
    got = rules_section_problems(text)
    expected = [expected] if isinstance(expected, str) else expected
    if len(got) != len(expected) or not all(e in p for e, p in zip(expected, got)):
        fail(f"rules section check on {case}: expected problems containing {expected!r} in that order, got {got}")
for case, (texts, expected) in BAD_RULE_CONTENT.items():
    got = rule_content_problems(texts)
    # Merging the push into the commit question both loses its paragraph and puts it in the question.
    if case.startswith("the push"):
        if not got or not all(expected in p for p in got):
            fail(f"rule content check on {case}: expected problems containing {expected!r}, got {got}")
    elif len(got) != 1 or expected not in got[0]:
        fail(f"rule content check on {case}: expected one problem containing {expected!r}, got {got}")
for case, ((lead, readme), expected) in BAD_RULES_MIRROR.items():
    got = rules_mirror_problems(lead, readme)
    if len(got) != 1 or expected not in got[0]:
        fail(f"rules mirror check on {case}: expected one problem containing {expected!r}, got {got}")
real_lead = (PLUGIN / LEAD_REL).read_text()
for problem in (rules_section_problems(real_lead)
                + rule_content_problems({LEAD_REL: real_lead,
                                         PLAN_TEMPLATE_REL: (PLUGIN / PLAN_TEMPLATE_REL).read_text()})
                + rules_mirror_problems(real_lead, (ROOT / README_REL).read_text())):
    fail(problem)
if len(errors) == errors_before_rules:
    ok(f"lead.md states its {len(RULE_TITLES)} standing rules once, before `{RULES_BEFORE}`, with what the acceptance "
       f"names, and the README's table mirrors them "
       f"({len(BAD_RULES_SECTION) + len(BAD_RULE_CONTENT) + len(BAD_RULES_MIRROR)} bad variants rejected)")


# Around the standing rules: the line that says how to read their order opens the section, above
# the first rule; a sentence of a rule is not restated word for word in a procedure section (the
# list is the only statement, the sections below say how); every guardrail a rule or the README's
# "Enforced by" column cites is a rule guard.py has, under its existing name, and the README row of
# a rule names every guardrail the rule in lead.md cites, so the user sees who enforces it; and the
# continue skill, which restates what the T2 checkpoint stop prints on a resume, prints the
# recommendation with each Unknown too.
GUARD_REL = "hooks/guard.py"
GUARD_RULES_START = "Rules (names used in the deny reason"
GUARD_RULE_LINE = re.compile(r"^  ([a-z]+(?:-[a-z]+)*) {2,}\S", re.M)
CITED_GUARD_RULE = re.compile(r"`([a-z]+(?:-[a-z]+)+|pii)`")
ENFORCED_BY = "Enforced by"
RESTATED_MIN = 40
CONTINUE_REL = "skills/continue/SKILL.md"
CONTINUE_T2_RESUME = "   - At T2 outside a plan-only run"
CONTINUE_T2_NEEDLES = ["Unknowns", "what would settle it", "recommendation"]


def guard_rule_names(guard_text):
    """The rule names listed in guard.py's docstring, under its Rules heading."""
    docstring = guard_text.split('"""')[1] if guard_text.count('"""') >= 2 else ""
    rules = docstring.split(GUARD_RULES_START, 1)[1] if GUARD_RULES_START in docstring else ""
    return set(GUARD_RULE_LINE.findall(rules.split("\nOverrides", 1)[0]))


def rules_reading_line_problems(lead_text):
    """A problem when the `## Rules` section does not open with the line that says how to read the
    order, above the first rule."""
    rules = section([line.rstrip() for line in lead_text.splitlines()], RULES_HEADING)
    first = next(iter(blocks("\n".join(rules or []))), "")
    if re.match(r"^\d+\. ", first) or not all(n in first for n in READING_ORDER_NEEDLES):
        return [f"{LEAD_REL}: the `{RULES_HEADING}` section does not open with the line that says how to read "
                "the order of the rules, above the first rule"]
    return []


def rules_restated_problems(lead_text):
    """Every sentence of a rule that lead.md repeats word for word outside the `## Rules` section."""
    lines = [line.rstrip() for line in lead_text.splitlines()]
    rules = section(lines, RULES_HEADING)
    if rules is None:
        return []
    start = lines.index(RULES_HEADING)
    outside = " ".join(blocks("\n".join(lines[:start] + lines[start + 1 + len(rules):])))
    problems = []
    for _, title, body in rule_items(lead_text):
        if title is None:
            continue
        for sentence in re.split(r"(?<=[.;:])\s+", body):
            sentence = sentence.strip().rstrip(".;:")
            if len(sentence) >= RESTATED_MIN and sentence in outside:
                problems.append(f"{LEAD_REL}: the rule *{title}* is restated outside `{RULES_HEADING}`: "
                                f"{sentence!r}; a procedure section says how, the list states the rule once")
    return problems


def readme_rule_table(readme_text):
    """(header cells, data rows as cell lists) of the table under `## Rules` in readme_text; None
    when the section or its table is missing."""
    rules = section([line.rstrip() for line in readme_text.splitlines()], RULES_HEADING)
    rows = [line for line in rules or [] if line.startswith("|")]
    separator = next((i for i, row in enumerate(rows) if re.fullmatch(r"\|[\s:|-]+\|", row)), None)
    if separator is None or separator == 0:
        return None
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    return cells[separator - 1], cells[separator + 1:]


def rules_enforcement_problems(lead_text, readme_text, guard_names):
    """Every guardrail name a rule of lead.md or the README's "Enforced by" column cites that guard.py
    lacks, every README row whose "Enforced by" cell is empty, and every guardrail a rule of lead.md
    cites that its README row does not name, one message each."""
    table = readme_rule_table(readme_text)
    if table is None:
        return [f"{README_REL}: no table under `{RULES_HEADING}`"]
    header, rows = table
    if ENFORCED_BY not in header:
        return [f"{README_REL}: the `{RULES_HEADING}` table has no {ENFORCED_BY!r} column"]
    column = header.index(ENFORCED_BY)
    enforced = {row[0]: (row[column] if len(row) > column else "") for row in rows}
    problems = []
    for title, cell in enforced.items():
        if not cell:
            problems.append(f"{README_REL}: the `{RULES_HEADING}` row {title!r} says nothing under {ENFORCED_BY!r}")
        for name in CITED_GUARD_RULE.findall(cell):
            if name not in guard_names:
                problems.append(f"{README_REL}: the `{RULES_HEADING}` row {title!r} cites `{name}`, "
                                f"which is no rule of {GUARD_REL}")
    for _, title, body in rule_items(lead_text):
        if title is None:
            continue
        for name in CITED_GUARD_RULE.findall(body):
            if name not in guard_names:
                problems.append(f"{LEAD_REL}: the rule *{title}* cites `{name}`, which is no rule of {GUARD_REL}")
            elif title in enforced and f"`{name}`" not in enforced[title]:
                problems.append(f"{README_REL}: the `{RULES_HEADING}` row {title!r} does not name `{name}`, "
                                f"which the rule in {LEAD_REL} cites")
    return problems


def continue_checkpoint_problems(continue_text):
    """A problem when the continue skill's T2 resume at the analysis checkpoint no longer prints the
    Unknowns each with what would settle it and the recommendation."""
    line = anchored_line(continue_text, CONTINUE_T2_RESUME)
    if line is None:
        return [f"{CONTINUE_REL}: no line starting {CONTINUE_T2_RESUME.strip()!r} (the T2 resume at the "
                "analysis checkpoint)"]
    return [f"{CONTINUE_REL}: the T2 resume at the analysis checkpoint no longer says {needle!r}"
            for needle in CONTINUE_T2_NEEDLES if needle not in line]


GOOD_GUARD = ('"""Guardrails.\n\nModes (first argument):\n  pre   PreToolUse   deny\n\n'
              f"{GUARD_RULES_START} and in CONCLAVE_ALLOW):\n"
              "  subagent-no-git      git commit from a subagent\n"
              "                       continued text\n"
              "  protect-history      push to the default branch\n"
              "  commit-approval      ask first\n"
              "  pii                  personal data\n\n"
              'Overrides come from the environment:\n  CONCLAVE_ALLOW=rule,rule   skip\n"""\n')
GOOD_GUARD_NAMES = guard_rule_names(GOOD_GUARD)
ENFORCED_CELLS = {"The user's word": "the lead; `commit-approval` and `pii` raise the prompts",
                  "Commits": "`commit-approval`, `subagent-no-git`",
                  "Push and pull request": "`commit-approval`, `protect-history`"}


def enforced_readme(cells=None, header="| Rule | What it means | Enforced by |"):
    cells = {**ENFORCED_CELLS, **(cells or {})}
    lines = ["# Conclave", "", RULES_HEADING, "", header, "|---|---|---|"]
    lines += [f"| {title} | text | {cells.get(title, 'the lead')} |" for title in RULE_TITLES]
    return "\n".join(lines + ["", "## Tiers", ""])


GOOD_CONTINUE = (f"{CONTINUE_T2_RESUME}, when the step is unticked: show its summary and Unknowns, each with what "
                 "would settle it and your recommendation, and wait.\n")
GOOD_ENFORCED = enforced_readme()
BAD_RULES_AROUND = {
    "the reading-order line placed after the rules": (
        "reading", standing_lead(rules=RULES_HEADING + "\n\n", before=GOOD_RULES_PIECES["rules"].split("\n\n", 1)[1]
                                 + GOOD_RULES_PIECES["before"]),
        "does not open with the line that says how to read"),
    "a rule restated in a procedure section": (
        "restated", standing_lead(gate=GOOD_RULES_PIECES["gate"] + "Stage each file by name. Never run `git push` "
                                  "without the user's approval.\n\n"),
        "the rule *Push and pull request* is restated outside `## Rules`"),
    "a rule citing a guardrail guard.py lacks": (
        "enforcement", standing_lead(bodies={"Commits": GOOD_RULE_BODIES["Commits"].replace(
            "`subagent-no-git`", "`subagent-no-commit`")}),
        "the rule *Commits* cites `subagent-no-commit`, which is no rule of hooks/guard.py"),
    "a README row citing a guardrail guard.py lacks": (
        "enforcement-readme", enforced_readme({"Branch": "the lead; `protect-branch`"}),
        "the `## Rules` row 'Branch' cites `protect-branch`, which is no rule"),
    "a README row with an empty Enforced by cell": (
        "enforcement-readme", enforced_readme({"Small slices": ""}),
        "the `## Rules` row 'Small slices' says nothing under 'Enforced by'"),
    "a README row that drops a guardrail the rule cites": (
        "enforcement-readme", enforced_readme({"Commits": "`commit-approval`"}),
        "the `## Rules` row 'Commits' does not name `subagent-no-git`"),
    "the README table without an Enforced by column": (
        "enforcement-readme", enforced_readme(header="| Rule | What it means | Who |"),
        "has no 'Enforced by' column"),
    "the continue skill's T2 resume without the recommendation": (
        "continue", GOOD_CONTINUE.replace(" and your recommendation", ""),
        "no longer says 'recommendation'"),
    "the continue skill's T2 resume without what would settle it": (
        "continue", GOOD_CONTINUE.replace(" what would settle it and", ""),
        "no longer says 'what would settle it'"),
}


def rules_around_problems(kind, text):
    if kind == "reading":
        return rules_reading_line_problems(text)
    if kind == "restated":
        return rules_restated_problems(text)
    if kind == "enforcement":
        return rules_enforcement_problems(text, GOOD_ENFORCED, GOOD_GUARD_NAMES)
    if kind == "enforcement-readme":
        return rules_enforcement_problems(GOOD_STANDING, text, GOOD_GUARD_NAMES)
    return continue_checkpoint_problems(text)


errors_before_around = len(errors)
if GOOD_GUARD_NAMES != {"subagent-no-git", "protect-history", "commit-approval", "pii"}:
    fail(f"guard rule names read from a known docstring: {sorted(GOOD_GUARD_NAMES)}")
for problem in (rules_reading_line_problems(GOOD_STANDING) + rules_restated_problems(GOOD_STANDING)
                + rules_enforcement_problems(GOOD_STANDING, GOOD_ENFORCED, GOOD_GUARD_NAMES)
                + continue_checkpoint_problems(GOOD_CONTINUE)):
    fail(f"standing rules surroundings check rejects valid files: {problem}")
for case, (kind, text, expected) in BAD_RULES_AROUND.items():
    got = rules_around_problems(kind, text)
    if len(got) != 1 or expected not in got[0]:
        fail(f"standing rules surroundings check on {case}: expected one problem containing {expected!r}, got {got}")
real_guard_names = guard_rule_names((PLUGIN / GUARD_REL).read_text())
if not {"commit-approval", "subagent-no-git", "protect-history", "pii"} <= real_guard_names:
    fail(f"{GUARD_REL}: the rule names read from its docstring miss one the rules cite: {sorted(real_guard_names)}")
real_readme = (ROOT / README_REL).read_text()
for problem in (rules_reading_line_problems(real_lead) + rules_restated_problems(real_lead)
                + rules_enforcement_problems(real_lead, real_readme, real_guard_names)
                + continue_checkpoint_problems((PLUGIN / CONTINUE_REL).read_text())):
    fail(problem)
if len(errors) == errors_before_around:
    ok(f"the rules open with how to read their order, are not restated below, cite only guardrails "
       f"{GUARD_REL} has and the README names, and the continue skill prints the recommendation "
       f"({len(BAD_RULES_AROUND)} bad variants rejected)")


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
