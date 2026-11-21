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
- with --base: if anything under plugins/ changed since <ref>, the version changed too,
  because installs from git are cached by version and `claude plugin update` does
  nothing for an unchanged version.
Exit 1 on any failure.
"""
import json
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
