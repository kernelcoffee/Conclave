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
