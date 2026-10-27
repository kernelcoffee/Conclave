// Conclave dev-team workflow: the adversarial pipeline, shaped by the lead's exec plan.
//
//   Workflow({ name: "conclave:dev-team",
//              args: { profile: <.claude/conclave.json as an object>, exec: <exec plan> } })
//
// The lead (agents/lead.md) builds `exec`; see docs/design.md for its fields. This script
// never decides tier, rounds, lenses or models on its own. It logs the agent budget it is
// about to spend, then runs:
//
//   Plan        pm (spec, acceptance, open decisions; stops the run on decisions), then
//               architect (per-component briefs, contracts, failure matrix, specialists).
//               Skipped when exec.brief is given (T2) or exec.skip names them.
//   Design      exec.design === "duel": two devs with different specialities propose and
//               critique; the architect judges when they disagree
//   Consult     ad-hoc consultants from the architect, plus ux for ui components,
//               reviewer-security when the plan is security sensitive, devops for infra
//   Contract    exec.contract: the test engineer writes failing tests with declared
//               expected failures before any code; the test auditor validates them; the
//               verifier freezes them by checksum
//   Build       one dev per touched component, in parallel; the verifier checks scope
//               and frozen tests afterwards
//   Cross-check each side of a contract pair verifies the other side against the contract
//   Challenge   per component: challenger attacks, dev answers, up to exec.rounds
//   Review      exec.lenses (correctness, security, stack per distinct stack, conventions, ux)
//               plus the architect's ad-hoc reviewers
//   Verify      refuters per finding (1 vote; exec.refute_votes_high for high severity);
//               after the last fix round, one re-check per fixed finding
//   Fix         confirmed findings routed to the owning dev, docs-writer or devops; then
//               the verifier checks scope and frozen tests again
//   Probes      profile.gates.mutation_probes: the test auditor sabotages the code once
//               per test and requires the test to fail; QA repairs weak tests
//   Tests       test-engineer writes black-box tests from the failure matrix
//   Docs        docs-writer aligns the docs the profile names; a second docs-writer call
//               audits every claim; corrections are applied
//   QA          checks, builds, e2e, coverage gate, shortcut audit, scope, frozen, flakes;
//               one repair round
//
// Any phase can stop with { status: "needs-human", decision_request } for the lead to
// resolve. Resume after the pm stops: exec.decisions (free text) and exec.proceed = true.

export const meta = {
  name: 'dev-team',
  description: 'Build with per-component devs and challengers, review with lenses, refute, fix, black-box test, docs and QA, at the tier the lead chose; optional test-first contract, mutation probes and design duel',
  whenToUse: 'Launched by the conclave lead for T2 and T3 tasks. Needs args.profile and args.exec.',
  phases: [
    { title: 'Profile', detail: 'read .claude/conclave.json when it was not passed in' },
    { title: 'Plan', detail: 'pm spec, then architect briefs, contracts and failure matrix' },
    { title: 'Design', detail: 'design duel: two devs propose and critique, the architect judges' },
    { title: 'Consult', detail: 'specialists advise the devs before the build' },
    { title: 'Contract', detail: 'test-first: failing tests with declared failures, audited and frozen' },
    { title: 'Build', detail: 'one dev per component, in parallel; scope and freeze verified' },
    { title: 'Cross-check', detail: 'contract pairs verify each other' },
    { title: 'Challenge', detail: 'same-stack challenger vs dev, up to N rounds' },
    { title: 'Review', detail: 'lenses chosen by the lead' },
    { title: 'Verify', detail: 'refuters per finding; re-check after the last fix' },
    { title: 'Fix', detail: 'owning role fixes confirmed findings; scope and freeze verified' },
    { title: 'Probes', detail: 'mutation probes per test; QA repairs weak tests' },
    { title: 'Tests', detail: 'black-box test engineer from the failure matrix' },
    { title: 'Docs', detail: 'docs writer, then a docs audit' },
    { title: 'QA', detail: 'checks, build, e2e, coverage, audit, scope, frozen, flakes' },
  ],
}

// ---- args ------------------------------------------------------------------
const opt = (typeof args === 'object' && args) || {}
const exec = opt.exec || {}
if (!exec.task) throw new Error('args.exec.task is required (the lead builds exec; see docs/design.md)')
const task = exec.task
const tier = exec.tier || 2
const maxRounds = exec.rounds || (tier >= 3 ? 2 : 1)
const skip = new Set(exec.skip || [])
const lenses = exec.lenses || ['correctness', 'security', 'stack']
const votesHigh = exec.refute_votes_high || 1
const pluginRoot = exec.plugin_root || ''
const bin = pluginRoot ? `${pluginRoot}/bin` : '<conclave plugin>/bin'
const contractMode = Boolean(exec.contract) && !skip.has('tests')
const duel = exec.design === 'duel' && !skip.has('architect')
const agentCount = { n: 0, byModel: {} }

// ---- schemas ---------------------------------------------------------------
const strList = { type: 'array', items: { type: 'string' } }
const finding = {
  type: 'object',
  properties: {
    file: { type: 'string' }, line: { type: 'integer' },
    severity: { type: 'string', enum: ['high', 'medium', 'low'] },
    summary: { type: 'string' }, failure_scenario: { type: 'string' }, suggested_fix: { type: 'string' },
  },
  required: ['file', 'severity', 'summary', 'failure_scenario'],
}
const RUN = { type: 'object', properties: { command: { type: 'string' }, exit_code: { type: 'integer' }, output_tail: { type: 'string' } }, required: ['command', 'exit_code', 'output_tail'] }
const runList = { type: 'array', items: RUN }
const PROFILE = { type: 'object', properties: { profile: { type: 'object' }, error: { type: 'string' } }, required: ['profile'] }
const SPEC = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    goals: strList, non_goals: strList,
    acceptance: strList,
    components: strList,
    security_sensitive: { type: 'boolean' },
    needs_decision: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, options: strList, recommendation: { type: 'string' } }, required: ['question', 'options', 'recommendation'] } },
    assumptions: strList,
  },
  required: ['summary', 'goals', 'acceptance', 'components', 'security_sensitive', 'needs_decision'],
}
const PLAN = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    components: strList,
    briefs: { type: 'array', items: { type: 'object', properties: { component: { type: 'string' }, brief: { type: 'string' } }, required: ['component', 'brief'] } },
    contracts: { type: 'array', items: { type: 'object', properties: { between: strList, text: { type: 'string' } }, required: ['between', 'text'] } },
    expected_failures: strList,
    specialists: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, role: { type: 'string', enum: ['consultant', 'reviewer'] }, brief: { type: 'string' } }, required: ['name', 'role', 'brief'] } },
    dev_specialities: strList,
    files: strList, risks: strList, assumptions: strList,
    security_sensitive: { type: 'boolean' },
    touches_infra: { type: 'boolean' },
    needs_decision: strList,
  },
  required: ['summary', 'components', 'briefs', 'contracts', 'expected_failures', 'specialists', 'needs_decision'],
}
const DESIGN = { type: 'object', properties: { approach: { type: 'string' }, steps: strList, files: strList, risks: strList, expected_tests: strList, unsure: strList }, required: ['approach', 'steps', 'files', 'risks', 'expected_tests', 'unsure'] }
const CRITIQUE = { type: 'object', properties: { verdict: { type: 'string', enum: ['adopt_mine', 'adopt_theirs', 'merge'] }, objections: { type: 'array', items: { type: 'object', properties: { claim: { type: 'string' }, breaks_with: { type: 'string' } }, required: ['claim', 'breaks_with'] } }, plan: { type: 'string' } }, required: ['verdict', 'objections', 'plan'] }
const JUDGEMENT_DESIGN = { type: 'object', properties: { winner: { type: 'string', enum: ['A', 'B', 'undecidable'] }, plan: { type: 'string' }, reasoning: { type: 'string' }, decision_needed: { type: 'string' } }, required: ['winner', 'plan', 'reasoning', 'decision_needed'] }
const commitSlice = { type: 'object', properties: { title: { type: 'string' }, files: strList, rationale: { type: 'string' } }, required: ['title', 'files', 'rationale'] }
const DEV = {
  type: 'object',
  properties: { summary: { type: 'string' }, files_changed: strList, tests_added: strList, checks_passed: { type: 'boolean' }, deviations: strList, handoff: strList, rebuttals: strList, commit_plan: { type: 'array', items: commitSlice } },
  required: ['summary', 'files_changed', 'checks_passed'],
}
const CROSSCHECK = {
  type: 'object',
  properties: { mismatches: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, summary: { type: 'string' }, failure_scenario: { type: 'string' } }, required: ['file', 'summary', 'failure_scenario'] } } },
  required: ['mismatches'],
}
const CHALLENGE = {
  type: 'object',
  properties: {
    challenges: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, severity: { type: 'string', enum: ['high', 'medium', 'low'] }, summary: { type: 'string' }, why_it_matters: { type: 'string' }, demand: { type: 'string' }, proof_test: { type: 'string' } }, required: ['file', 'severity', 'summary', 'why_it_matters', 'demand'] } },
    escalations: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, summary: { type: 'string' }, rebuttal: { type: 'string' }, why_rejected: { type: 'string' } }, required: ['summary', 'rebuttal', 'why_rejected'] } },
    accepted: strList, tests_added: strList,
  },
  required: ['challenges'],
}
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: finding } }, required: ['findings'] }
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }
const RECHECK = { type: 'object', properties: { fixed: { type: 'boolean' }, reason: { type: 'string' } }, required: ['fixed', 'reason'] }
const contractTest = { type: 'object', properties: { file: { type: 'string' }, name: { type: 'string' }, criterion: { type: 'string' }, behaviour: { type: 'string', enum: ['success', 'failure', 'boundary'] }, expected_failure: { type: 'string' } }, required: ['file', 'name', 'criterion', 'behaviour', 'expected_failure'] }
const TESTS = {
  type: 'object',
  properties: {
    cases: strList, tests_added: strList, test_files: strList,
    contract_tests: { type: 'array', items: contractTest },
    could_not_reproduce: { type: 'boolean' },
    bugs: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, summary: { type: 'string' }, failure_scenario: { type: 'string' } }, required: ['file', 'summary', 'failure_scenario'] } },
    untestable: strList, checks_passed: { type: 'boolean' },
  },
  required: ['cases', 'tests_added', 'bugs', 'checks_passed'],
}
const RED_AUDIT = { type: 'object', properties: { valid: { type: 'boolean' }, per_test: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, name: { type: 'string' }, fails_as_declared: { type: 'boolean' }, actual_failure: { type: 'string' }, can_fail: { type: 'boolean' }, note: { type: 'string' } }, required: ['file', 'name', 'fails_as_declared', 'actual_failure', 'can_fail', 'note'] } }, other_tests_pass: { type: 'boolean' }, runs: runList }, required: ['valid', 'per_test', 'other_tests_pass', 'runs'] }
const PROBES = { type: 'object', properties: { probes: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, name: { type: 'string' }, mutation: { type: 'string' }, test_failed: { type: 'boolean' } }, required: ['file', 'name', 'mutation', 'test_failed'] } }, tree_restored: { type: 'boolean' }, verdict: { type: 'string', enum: ['pass', 'reject', 'escalate'] }, rejection: { type: 'string' }, runs: runList }, required: ['probes', 'tree_restored', 'verdict', 'rejection', 'runs'] }
const VERIFY = { type: 'object', properties: { runs: runList, all_passed: { type: 'boolean' } }, required: ['runs', 'all_passed'] }
const DOCS = { type: 'object', properties: { summary: { type: 'string' }, files_changed: strList, gaps: strList }, required: ['summary', 'files_changed'] }
const DOC_AUDIT = { type: 'object', properties: { corrections: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, quoted: { type: 'string' }, true_statement: { type: 'string' }, evidence: { type: 'string' } }, required: ['file', 'quoted', 'true_statement', 'evidence'] } } }, required: ['corrections'] }
const QA = {
  type: 'object',
  properties: {
    all_green: { type: 'boolean' },
    suites: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, passed: { type: 'boolean' }, detail: { type: 'string' } }, required: ['name', 'passed'] } },
    coverage: { type: 'string' }, audit: { type: 'string' }, flaky: strList, code_fixes_needed: strList,
  },
  required: ['all_green', 'suites'],
}

// ---- models and effort -----------------------------------------------------
const GROUP = {
  pm: 'planners', architect: 'planners',
  dev: 'workers', challenger: 'workers', 'test-engineer': 'workers', devops: 'workers',
  'reviewer-correctness': 'reviewers', 'reviewer-security': 'reviewers', 'reviewer-stack': 'reviewers', ux: 'reviewers', 'test-auditor': 'reviewers',
  'reviewer-conventions': 'mechanical', qa: 'mechanical', 'docs-writer': 'mechanical', profile: 'mechanical', verifier: 'mechanical',
  refuter: 'refuter', adhoc: 'reviewers',
}
const DEFAULT_MODEL = { planners: 'inherit', workers: 'opus', reviewers: 'opus', mechanical: 'sonnet', refuter: 'opus' }
const DEFAULT_EFFORT = { planners: 'high', workers: 'high', reviewers: 'high', mechanical: 'medium', refuter: 'high' }
const LOW_EFFORT = new Set(['qa', 'profile', 'verifier'])
let profile = opt.profile || null
const pick = (table, role) => {
  const g = GROUP[role] || 'workers'
  const sources = [exec.models || {}, (profile && profile.models) || {}]
  for (const s of sources) { if (s[role]) return s[role]; if (s[g]) return s[g] }
  return table[g]
}
const modelFor = (role) => { const m = pick(DEFAULT_MODEL, role); return m === 'inherit' ? undefined : m }
const effortFor = (role) => {
  const e = (exec.effort || {})[role] || (exec.effort || {})[GROUP[role]]
  if (e) return e
  return LOW_EFFORT.has(role) ? 'low' : DEFAULT_EFFORT[GROUP[role] || 'workers']
}

// ---- helpers ---------------------------------------------------------------
const show = (obj) => JSON.stringify(obj, null, 2)
const count = (model) => { agentCount.n += 1; const k = model || 'inherit'; agentCount.byModel[k] = (agentCount.byModel[k] || 0) + 1 }
// Runs a Conclave role. Custom agent types load at session start; when the type is not
// registered (plugin just installed, or exec.briefs_from_files), a default agent reads
// the brief from the plugin's agents dir and acts as that role.
async function run(role, prompt, opts) {
  const model = modelFor(role)
  const options = { effort: effortFor(role), ...(model ? { model } : {}), ...opts }
  count(options.model)
  if (role === 'profile') return agent(prompt, options) // not a role file; a plain default agent
  const fromBrief = () => {
    if (!pluginRoot) throw new Error(`agent type conclave:${role} is not registered and exec.plugin_root is not set`)
    return agent(`First read the file ${pluginRoot}/agents/${role}.md and act exactly as the agent it describes, obeying every rule in it (including which files you may edit). Then do the task below.\n\n---\n\n${prompt}`, options)
  }
  if (exec.briefs_from_files) return fromBrief()
  try {
    return await agent(prompt, { agentType: `conclave:${role}`, ...options })
  } catch (e) {
    if (!String(e && e.message).includes('not found')) throw e
    log(`agent type conclave:${role} not registered in this session (run /reload-plugins or restart); running from its brief file`)
    return fromBrief()
  }
}
const runAdhoc = (spec, prompt, opts) => { const model = modelFor('adhoc'); count(model); return agent(`${spec.brief}\n\n---\n\n${prompt}`, { effort: effortFor('adhoc'), ...(model ? { model } : {}), ...opts }) }
const dedupe = (items) => {
  const seen = new Set()
  return items.filter((f) => {
    const key = `${f.file}:${f.line || 0}:${(f.summary || '').slice(0, 40)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
const globToRe = (g) => new RegExp('^' + g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*\//g, '(.*/)?').replace(/\*\*/g, '.*').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]') + '$')
const matches = (file, pattern) => pattern.endsWith('/') ? file.startsWith(pattern) : (pattern.includes('*') || pattern.includes('?')) ? globToRe(pattern).test(file) : file === pattern
const failedRuns = (runs) => (runs || []).filter((r) => r.exit_code !== 0).map((r) => `$ ${r.command}\n(exit ${r.exit_code})\n${r.output_tail}`).join('\n\n')
const uniq = (list) => [...new Set(list)]
const shellQuote = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`

// ---- Profile ---------------------------------------------------------------
if (!profile) {
  phase('Profile')
  const r = await run('profile', 'Read the file .claude/conclave.json in the current project and return it unchanged as the `profile` field. If it does not exist or is not valid JSON, return an empty object as `profile` and say why in `error`. Do nothing else.', { phase: 'Profile', schema: PROFILE, label: 'profile' })
  if (!r || !r.profile || !r.profile.components) throw new Error(`no profile: ${(r && r.error) || 'run /conclave:init first'}`)
  profile = r.profile
}
const base = exec.base || profile.base || 'origin/main'
const gates = profile.gates || {}
const byName = {}
for (const c of profile.components || []) byName[c.name] = c
const ownerOf = (file) => {
  if (file) {
    for (const c of profile.components || []) if ((c.paths || []).some((p) => matches(file, p))) return `dev:${c.name}`
    if (((profile.docs || {}).paths || []).some((p) => matches(file, p))) return 'docs-writer'
    if (((profile.devops || {}).paths || []).some((p) => matches(file, p))) return 'devops'
  }
  return `dev:${(exec.components || [])[0] || (profile.components[0] || {}).name}`
}

// ---- state and the uniform stop ---------------------------------------------
let components = exec.components || []
let plan = null
let spec = null
const briefs = {}
const reports = {}
const history = []
let contract = { tests: [], files: [], checksums: '' }
const stop = (phaseName, question, context) => ({
  status: 'needs-human', phase: phaseName, decision_request: { question, context },
  task, tier, components, spec, plan: plan && { summary: plan.summary, contracts: plan.contracts, expected_failures: plan.expected_failures },
  reports, contract, history, agents: agentCount, ready_to_commit: false,
})

// ---- context block ---------------------------------------------------------
const contractsText = () => (plan && plan.contracts && plan.contracts.length)
  ? plan.contracts.map((c) => `Between ${c.between.join(' and ')}:\n${c.text}`).join('\n\n')
  : '(none)'
const failuresText = () => ((plan && plan.expected_failures) || []).length ? '- ' + plan.expected_failures.join('\n- ') : '(none given)'
const frozenText = () => contract.files.length ? `\n\nFrozen contract tests (checksummed; you may not edit them):\n- ${contract.files.join('\n- ')}` : ''
const packsFor = (names) => uniq(names.flatMap((n) => (byName[n] || {}).stacks || [])).map((s) => `conclave:stack-${s}`)
const context = (names) => {
  const comps = (names || []).map((n) => byName[n]).filter(Boolean)
  return `Project: ${profile.name}. ${profile.summary || ''}\nBase ref: ${base}\n` +
    `Stakes (severity high means): ${profile.stakes || 'breaks behaviour or loses data'}\n` +
    `Threat model: ${(profile.security || {}).threat_model || '(none stated)'}\n\n` +
    `Task:\n${task}\n\n` +
    (comps.length ? `Component(s) you work on:\n${show(comps)}\n\nStack packs: load each with the Skill tool before you start: ${packsFor(names).join(', ') || '(none)'}\n\n` : '') +
    `Contract(s):\n${contractsText()}\n\nExpected failures:\n${failuresText()}${frozenText()}`
}
const allowedPaths = (names, extra) => uniq([
  ...names.flatMap((n) => [...((byName[n] || {}).paths || []), ...((byName[n] || {}).tests || [])]),
  ...(extra || []),
])

// ---- verifier: scope and frozen ---------------------------------------------
// One cheap mechanical check after writes. Out-of-scope files go back to the owning dev;
// an edited frozen test stops the run.
const verifyTree = async (names, extra, phaseName, label) => {
  const cmds = [`${bin}/scope-check.sh ${base} ${allowedPaths(names, extra).map(shellQuote).join(' ')}`]
  if (contract.checksums) cmds.push(`${bin}/freeze.sh verify <<'EOF'\n${contract.checksums}\nEOF`)
  const v = await run('verifier',
    `Run these commands from the repository root, in order, and report each verbatim with its exit code. Do not change anything.\n\n${cmds.map((c, i) => `${i + 1}. ${c}`).join('\n')}`,
    { phase: phaseName, schema: VERIFY, label })
  if (!v) return { ok: true, out_of_scope: [], frozen_ok: true }
  const scopeRun = v.runs[0]
  const frozenRun = v.runs[1]
  const outOfScope = scopeRun && scopeRun.exit_code !== 0 ? (scopeRun.output_tail.match(/out of scope: (.+)/g) || []).map((l) => l.replace('out of scope: ', '').trim()) : []
  const frozenOk = !frozenRun || frozenRun.exit_code === 0
  if (!frozenOk) log(`${label}: a frozen contract test was modified`)
  if (outOfScope.length) log(`${label}: ${outOfScope.length} file(s) outside the allowed paths`)
  return { ok: v.all_passed, out_of_scope: outOfScope, frozen_ok: frozenOk, runs: v.runs }
}

// ---- Plan ------------------------------------------------------------------
if (exec.brief) {
  for (const c of components) briefs[c] = exec.brief
  plan = { summary: 'lead-written brief', components, briefs: components.map((c) => ({ component: c, brief: exec.brief })), contracts: [], expected_failures: exec.expected_failures || [], specialists: [], needs_decision: [], security_sensitive: Boolean(exec.security_sensitive), touches_infra: false, dev_specialities: exec.dev_specialities || [] }
  log(`T${tier}: planning skipped, the lead wrote the brief for ${components.join(', ')}`)
} else {
  phase('Plan')
  if (!skip.has('pm')) {
    spec = await run('pm',
      `${context(components)}\n\n` +
      (exec.decisions ? `The user answered your earlier questions; honour them and leave needs_decision empty unless something new comes up:\n${exec.decisions}\n\n` : '') +
      `Write the product spec for this task: goals, non-goals, acceptance criteria the test engineer can turn into cases, the components touched (choose from: ${(profile.components || []).map((c) => c.name).join(', ')}), whether the change is security sensitive, and the decisions only the user can make. Do not edit files.`,
      { phase: 'Plan', schema: SPEC, label: 'pm' })
    if (!spec) return stop('Plan', 'The pm returned nothing; relaunch or write the brief yourself.', {})
    if (spec.needs_decision.length && !exec.proceed) {
      log(`pm has ${spec.needs_decision.length} open decision(s); stopping before the build`)
      return { ...stop('Plan', 'Decisions only the user can make, from the pm.', { needs_decision: spec.needs_decision }), stopped_for_decisions: true }
    }
    if (spec.components && spec.components.length) components = spec.components.filter((c) => byName[c])
  }
  if (!skip.has('architect')) {
    plan = await run('architect',
      `${context(components)}\n\n` +
      (spec ? `Product spec from the pm:\n${show(spec)}\n\n` : '') +
      (exec.decisions ? `User decisions:\n${exec.decisions}\n\n` : '') +
      `Contract pairs the profile declares: ${show(profile.contracts || [])}. Components available: ${(profile.components || []).map((c) => c.name).join(', ')}.\n` +
      `Plan the change: one brief per touched component, a contract for every declared pair whose both sides change, the expected-failure matrix, ad-hoc specialists if the fixed team lacks the knowledge, risks and assumptions.` +
      (duel ? ` A design duel follows: name two dev_specialities chosen for what this task could get wrong.` : '') +
      ` Work on the current branch (uncommitted work is context, not something to undo). Do not edit files.`,
      { phase: 'Plan', schema: PLAN, label: 'architect' })
    if (!plan) return stop('Plan', 'The architect returned nothing; relaunch or write the briefs yourself.', { spec })
    if (plan.needs_decision.length && !exec.proceed) {
      log(`architect has ${plan.needs_decision.length} open decision(s); stopping before the build`)
      return { ...stop('Plan', 'Decisions only the user can make, from the architect.', { needs_decision: plan.needs_decision }), stopped_for_decisions: true }
    }
    components = plan.components.filter((c) => byName[c])
    for (const b of plan.briefs) briefs[b.component] = b.brief
  } else {
    for (const c of components) briefs[c] = `${task}\n\n${spec ? `Spec:\n${show(spec)}` : ''}`
    plan = { summary: 'architect skipped', components, briefs: [], contracts: [], expected_failures: [], specialists: [], needs_decision: [], security_sensitive: Boolean(spec && spec.security_sensitive), touches_infra: false, dev_specialities: [] }
  }
}
if (!components.length) return stop('Plan', 'No component to build; check exec.components against profile.components.', { components: exec.components })
for (const c of components) if (!briefs[c]) briefs[c] = task

// ---- Design duel -----------------------------------------------------------
let duelResult = null
if (duel) {
  phase('Design')
  const specs = (plan.dev_specialities && plan.dev_specialities.length >= 2) ? plan.dev_specialities.slice(0, 2) : (exec.dev_specialities && exec.dev_specialities.length >= 2 ? exec.dev_specialities.slice(0, 2) : ['correctness and data integrity', 'concurrency, lifetime and failure paths'])
  const tag = (i) => (i === 0 ? 'A' : 'B')
  const designs = await parallel(specs.map((s, i) => () =>
    run('dev', `${context(components)}\n\nBriefs:\n${show(briefs)}\n\nYou are developer ${tag(i)}; your speciality: ${s}. Produce your DESIGN for this task from your speciality's point of view: the smallest correct change. Read the code first. Do not write code.`,
      { phase: 'Design', schema: DESIGN, label: `design:${tag(i)}` })))
  if (!designs[0] || !designs[1]) return stop('Design', 'A developer returned no design.', { designs })
  const showD = (d) => `Approach: ${d.approach}\nSteps:\n${d.steps.map((s) => '  - ' + s).join('\n')}\nFiles: ${d.files.join(', ')}\nRisks:\n${d.risks.map((s) => '  - ' + s).join('\n')}\nExpected tests:\n${d.expected_tests.map((s) => '  - ' + s).join('\n')}\nUnsure about:\n${d.unsure.map((s) => '  - ' + s).join('\n')}`
  const critiques = await parallel([0, 1].map((i) => () =>
    run('dev', `${context(components)}\n\nYou are developer ${tag(i)}; your speciality: ${specs[i]}.\nYOUR design:\n${showD(designs[i])}\n\nThe OTHER developer's design (speciality: ${specs[1 - i]}):\n${showD(designs[1 - i])}\n\nCRITIQUE the other design from your speciality, then state the plan you would implement now.`,
      { phase: 'Design', schema: CRITIQUE, label: `critique:${tag(i)}` })))
  if (!critiques[0] || !critiques[1]) return stop('Design', 'A developer returned no critique.', { designs, critiques })
  const agreeA = critiques[0].verdict === 'adopt_mine' && critiques[1].verdict === 'adopt_theirs'
  const agreeB = critiques[0].verdict === 'adopt_theirs' && critiques[1].verdict === 'adopt_mine'
  if (agreeA || agreeB) {
    duelResult = { winner: agreeA ? 'A' : 'B', plan: critiques[agreeA ? 0 : 1].plan, reasoning: 'both developers agree', specialities: specs }
    log(`design duel: both developers agree on developer ${duelResult.winner}'s plan`)
  } else {
    const judged = await run('architect',
      `${context(components)}\n\nYou are the JUDGE of a design duel. Read the code where a decision hinges on it.\n\n` +
      `Developer A (speciality: ${specs[0]}) proposed:\n${showD(designs[0])}\nAfter reading B's design, A said (${critiques[0].verdict}) with objections:\n${critiques[0].objections.map((o) => `  - ${o.claim} (breaks with: ${o.breaks_with})`).join('\n') || '  (none)'}\nA would now implement: ${critiques[0].plan}\n\n` +
      `Developer B (speciality: ${specs[1]}) proposed:\n${showD(designs[1])}\nAfter reading A's design, B said (${critiques[1].verdict}) with objections:\n${critiques[1].objections.map((o) => `  - ${o.claim} (breaks with: ${o.breaks_with})`).join('\n') || '  (none)'}\nB would now implement: ${critiques[1].plan}\n\n` +
      `Decide which plan to implement (you may merge). If the evidence does not allow a decision, answer "undecidable" and state the exact question the user must answer.`,
      { phase: 'Design', schema: JUDGEMENT_DESIGN, label: 'design:judge' })
    if (!judged) return stop('Design', 'The design judge returned nothing.', { designs, critiques })
    if (judged.winner === 'undecidable') return stop('Design', judged.decision_needed, { designs, critiques, judge_reasoning: judged.reasoning })
    duelResult = { winner: judged.winner, plan: judged.plan, reasoning: judged.reasoning, specialities: specs }
    log(`design duel: the judge chose developer ${judged.winner}'s plan`)
  }
  for (const c of components) briefs[c] = `${briefs[c]}\n\n## Implementation plan chosen by the design duel\n${duelResult.plan}`
}

// ---- budget line -----------------------------------------------------------
const stackSet = uniq(components.flatMap((c) => byName[c].stacks || []))
const uiTouched = components.some((c) => byName[c].ui)
const lensRoles = []
for (const l of lenses) {
  if (l === 'stack') for (const s of stackSet) lensRoles.push({ role: 'reviewer-stack', stack: s })
  else if (l === 'ux') { if (uiTouched) lensRoles.push({ role: 'ux' }) }
  else lensRoles.push({ role: `reviewer-${l}` })
}
const adhocReviewers = (plan.specialists || []).filter((s) => s.role === 'reviewer')
const consultants = (plan.specialists || []).filter((s) => s.role === 'consultant')
log(`T${tier} · ${components.join(', ')} · stacks ${stackSet.join(', ')} · ${maxRounds} round(s) · lenses ${lensRoles.map((l) => l.stack ? `stack:${l.stack}` : l.role.replace('reviewer-', '')).join(', ')}${adhocReviewers.length ? ` +${adhocReviewers.length} ad-hoc` : ''} · ${votesHigh} vote(s) on high${contractMode ? ' · contract' : ''}${gates.mutation_probes ? ' · probes' : ''}${duel ? ' · duel' : ''}`)

// ---- Consult ---------------------------------------------------------------
const consultPrompt = (who) => `${context(components)}\n\nBriefs the devs will receive:\n${show(briefs)}\n\nWrite the guidance the devs need from your specialty (${who}) for this task: constraints, pitfalls, exact formats, references. Do not edit files. Your final message is the guidance text.`
const consultRuns = []
if (!skip.has('consult')) {
  for (const s of consultants) consultRuns.push(() => runAdhoc(s, consultPrompt(s.name), { phase: 'Consult', label: `consult:${s.name}` }).then((t) => t && `## Guidance from ${s.name}\n${t}`))
  if (uiTouched && lenses.includes('ux')) consultRuns.push(() => run('ux', consultPrompt('UX'), { phase: 'Consult', label: 'consult:ux' }).then((t) => t && `## UX guidance\n${t}`))
  if (plan.security_sensitive) consultRuns.push(() => run('reviewer-security', consultPrompt('security'), { phase: 'Consult', label: 'consult:security' }).then((t) => t && `## Security guidance\n${t}`))
  if (plan.touches_infra) consultRuns.push(() => run('devops', consultPrompt('CI, packaging and deployment'), { phase: 'Consult', label: 'consult:devops' }).then((t) => t && `## DevOps guidance\n${t}`))
}
if (consultRuns.length) {
  phase('Consult')
  const notes = (await parallel(consultRuns)).filter(Boolean)
  for (const c of components) briefs[c] = `${briefs[c]}\n\n${notes.join('\n\n')}`
  log(`${notes.length} consultant note(s) appended to the briefs`)
}

// ---- Contract (test-first) ---------------------------------------------------
const freeze = async (files, phaseName, label) => {
  const v = await run('verifier',
    `Run this command from the repository root and report its complete stdout verbatim (not only the tail) with its exit code. Do not change anything.\n\n1. ${bin}/freeze.sh freeze ${files.map(shellQuote).join(' ')}`,
    { phase: phaseName, schema: VERIFY, label })
  if (!v || !v.all_passed || !v.runs[0] || !v.runs[0].output_tail.trim()) return null
  return v.runs[0].output_tail.trim()
}
const contractList = () => contract.tests.map((t) => `  ${t.file}::${t.name} [${t.behaviour}, ${t.criterion}] expected failure: ${t.expected_failure}`).join('\n')
if (contractMode) {
  phase('Contract')
  let feedback = ''
  let valid = false
  let tests = null
  for (let attempt = 1; attempt <= 2 && !valid; attempt++) {
    tests = await run('test-engineer',
      `${context(components)}\n\nBriefs the devs will receive (so your tests target the behaviour, not the plan's internals):\n${show(briefs)}\n\n` +
      `CONTRACT MODE: no implementation exists yet. Write the contract tests from the acceptance criteria and the expected failures: for each behaviour the success path, each failure path and the boundary. Declare the exact expected failure of every test on the current code. Touch only the components' tests paths. Run them to see them fail as declared.` +
      (feedback ? `\n\nYour previous attempt was rejected by the test auditor:\n${feedback}` : ''),
      { phase: 'Contract', schema: TESTS, label: `contract:try${attempt}` })
    if (!tests) return stop('Contract', 'The test engineer returned nothing in contract mode.', {})
    if (tests.could_not_reproduce || !(tests.contract_tests || []).length) return stop('Contract', 'The test engineer could not write an honest failing test: the behaviour may already hold, the defect may not exist as described, or a seam is missing.', { untestable: tests.untestable, cases: tests.cases })
    const audit = await run('test-auditor',
      `${context(components)}\n\nRED AUDIT. The test engineer claims these tests fail on the current code exactly as declared:\n${tests.contract_tests.map((t) => `  ${t.file}::${t.name} [${t.behaviour}, ${t.criterion}] expected failure: ${t.expected_failure}`).join('\n')}\nTest files: ${(tests.test_files || []).join(' ')}\n\n` +
      `Run the components' checks (or their test runner for just these tests, then the whole suite). For each test say whether it fails exactly as declared (same test, same assertion, same message or values), what the actual failure was, and whether it can fail at all. Then read every test for tautologies, happy-path-only coverage where the criterion names a failure path, and implementation-detail pinning. "valid" is true only if every test fails as declared, none is a tautology, and every other test passes. Do not edit anything.`,
      { phase: 'Contract', schema: RED_AUDIT, label: `contract:audit${attempt}` })
    if (!audit) return stop('Contract', 'The test auditor returned nothing.', { tests })
    valid = audit.valid && audit.other_tests_pass && audit.per_test.every((t) => t.fails_as_declared && t.can_fail)
    if (!valid) {
      feedback = audit.per_test.filter((t) => !t.fails_as_declared || !t.can_fail).map((t) => `- ${t.file}::${t.name}: declared failure not observed or test cannot fail. Actual: ${t.actual_failure}. ${t.note}`).join('\n') + (failedRuns(audit.runs) ? `\n\nOutput:\n${failedRuns(audit.runs)}` : '')
      log(`contract: the test auditor rejected the tests on attempt ${attempt}`)
    }
  }
  if (!valid) return stop('Contract', 'The test engineer and the test auditor could not converge on contract tests that fail exactly as declared. Decide whether the tests or the declared failures are wrong, or whether the behaviour already holds.', { last_feedback: feedback, tests })
  const sums = await freeze(tests.test_files || [], 'Contract', 'contract:freeze')
  if (!sums) return stop('Contract', 'Could not freeze the contract tests (freeze.sh failed or printed nothing).', { test_files: tests.test_files })
  contract = { tests: tests.contract_tests, files: tests.test_files || [], checksums: sums }
  log(`contract frozen: ${contract.tests.length} test(s) in ${contract.files.length} file(s)`)
}

// ---- Build -----------------------------------------------------------------
phase('Build')
const built = await parallel(components.map((c) => () =>
  run('dev', `${context([c])}\n\nYou are the dev for component "${c}". Your brief:\n${briefs[c]}`, { phase: 'Build', schema: DEV, label: `build:${c}` })
    .then((r) => ({ component: c, report: r }))))
for (const b of built.filter(Boolean)) reports[b.component] = b.report
for (const c of components) if (!reports[c]) return stop('Build', `The dev for ${c} returned nothing.`, { reports })
history.push({ phase: 'build', reports: { ...reports } })

const devFix = async (c, prompt, label, phaseName) => {
  const r = await run('dev', prompt, { phase: phaseName, schema: DEV, label })
  if (r) reports[c] = r
  return r
}
const fixPrompt = (c, items, what) =>
  `${context([c])}\n\nYou are the dev for component "${c}". Your brief:\n${briefs[c]}\n\nYour last report:\n${show(reports[c])}\n\n` +
  `${what}. Fix each one properly (no shortcuts), re-run the component's checks, and report again in the same shape. ` +
  `If one is wrong, say why under rebuttals; never silently skip one.\n\n${show(items)}`
let docsTouched = false
let devopsTouched = false
const routeFixes = async (items, what, phaseName, labelPrefix) => {
  const byOwner = {}
  for (const f of items) (byOwner[ownerOf(f.file)] ||= []).push(f)
  await parallel(Object.entries(byOwner).map(([owner, list]) => () => {
    if (owner === 'docs-writer') { docsTouched = true; return run('docs-writer', `${context(components)}\n\nDocs you own: ${show(profile.docs || {})}.\n\n${what}; fix them in the docs.\n\n${show(list)}`, { phase: phaseName, schema: DOCS, label: `${labelPrefix}:docs` }) }
    if (owner === 'devops') { devopsTouched = true; return run('devops', `${context(components)}\n\nDevops block: ${show(profile.devops || {})}.\n\n${what}; fix them.\n\n${show(list)}`, { phase: phaseName, schema: DEV, label: `${labelPrefix}:devops` }) }
    const c = owner.slice(4)
    if (!byName[c]) return null
    return devFix(c, fixPrompt(c, list, what), `${labelPrefix}:${c}`, phaseName)
  }))
}
const extraAllowed = () => [...(docsTouched ? ((profile.docs || {}).paths || []) : []), ...(devopsTouched ? ((profile.devops || {}).paths || []) : [])]
// Scope and frozen check after writes; out-of-scope files go back to their owner once.
const guardTree = async (phaseName, label) => {
  const v = await verifyTree(components, extraAllowed(), phaseName, label)
  if (!v.frozen_ok) return stop(phaseName, 'A frozen contract test was modified after the freeze. Inspect git diff on the contract test files and decide whether to restore them or to re-freeze.', { contract, runs: v.runs })
  if (v.out_of_scope.length) {
    await routeFixes(v.out_of_scope.map((f) => ({ file: f, severity: 'medium', summary: `edited outside the allowed paths: ${f}`, failure_scenario: 'The verifier found this file changed although it is outside the paths your role owns. Revert it unless the brief requires it; if it does, say so under deviations.' })), 'The verifier found files changed outside your allowed paths', phaseName, `${label}-scope`)
  }
  return null
}
{ const s = await guardTree('Build', 'verify:build'); if (s) return s }

// ---- Cross-check -----------------------------------------------------------
const pairs = (plan.contracts || []).filter((k) => k.between.length === 2 && k.between.every((n) => components.includes(n)))
if (pairs.length && !skip.has('crosscheck')) {
  phase('Cross-check')
  const checks = (await parallel(pairs.flatMap((k) => {
    const [a, b] = k.between
    return [[a, b], [b, a]].map(([me, other]) => () =>
      run('dev',
        `${context([me, other])}\n\nYou are the dev for "${me}". The "${other}" dev reports:\n${show(reports[other])}\n\n` +
        `Verify the "${other}" side of the working tree against the contract between you: paths, methods, request and response shapes, status codes, error details, messages. ` +
        `Read the code, not the report. Do not edit anything. Report every mismatch with file, line, summary and the failure it causes.`,
        { phase: 'Cross-check', schema: CROSSCHECK, label: `xcheck:${me}→${other}` })
        .then((r) => (r ? r.mismatches.map((m) => ({ ...m, severity: 'medium', found_by: `${me}-dev` })) : [])))
  }))).filter(Boolean).flat()
  log(`cross-check: ${checks.length} contract mismatch(es)`)
  if (checks.length) await routeFixes(checks, 'The other side\'s dev found these contract mismatches on your side', 'Cross-check', 'xfix')
}

// ---- Challenge -------------------------------------------------------------
const escalated = []
if (!skip.has('challenge')) {
  phase('Challenge')
  await parallel(components.map((c) => async () => {
    let round = 1
    let result = await run('challenger',
      `${context([c])}\n\nYou challenge the dev of component "${c}". The dev's brief:\n${briefs[c]}\n\nThe dev's report:\n${show(reports[c])}\n\n` +
      `Round 1: challenge this component's side of the working tree (git diff ${base}, git status, read the code).`,
      { phase: 'Challenge', schema: CHALLENGE, label: `challenge:${c} r1` })
    while (result && result.challenges.length && round <= maxRounds) {
      log(`${c}: ${result.challenges.length} challenge(s) in round ${round}`)
      const answered = await devFix(c, fixPrompt(c, result.challenges, 'Your challenger raised these'), `answer:${c} r${round}`, 'Challenge')
      if (!answered) break
      if (round === maxRounds) {
        for (const r of answered.rebuttals || []) escalated.push({ file: 'rebuttal', severity: 'medium', summary: r, failure_scenario: `Dev rebuttal not re-examined by the challenger (rounds exhausted): ${r}`, lens: `${c}-challenge` })
        break
      }
      round += 1
      result = await run('challenger',
        `${context([c])}\n\nYour previous challenges:\n${show(result.challenges)}\n\nThe dev's response:\n${show(answered)}\n\n` +
        `Round ${round}: re-examine the working tree. Accept settled challenges, escalate rejected rebuttals, and only raise new challenges the fix created.`,
        { phase: 'Challenge', schema: CHALLENGE, label: `challenge:${c} r${round}` })
      if (result) for (const e of result.escalations || []) escalated.push({ file: e.file || 'rebuttal', line: e.line, severity: 'medium', summary: e.summary, failure_scenario: `${e.why_rejected} (dev rebuttal: ${e.rebuttal})`, lens: `${c}-challenge` })
    }
  }))
  log(`challenge phase done: ${escalated.length} escalation(s) carried into review`)
  history.push({ phase: 'challenge', reports: { ...reports }, escalations: escalated })
  { const s = await guardTree('Challenge', 'verify:challenge'); if (s) return s }
}

// ---- Review / Verify / Fix rounds -----------------------------------------
const allReports = () => `Dev reports:\n${show(reports)}`
const reviewPrompt = (extra) =>
  `${context(components)}\n\n${allReports()}\n\n${extra || ''}Review the uncommitted working-tree changes: run \`git diff ${base}\` and \`git status\`, and read any untracked files the reports list.`
const refutePrompt = (f) =>
  `A reviewer (${f.lens} lens) reported this finding on the uncommitted working-tree changes:\n${show(f)}\n\n${context(components)}\n\n` +
  `Try to refute it. Read the code at that location and the callers. The finding stands only if the failure scenario is reachable in practice through this change. ` +
  `Set refuted=true if it cannot happen, is already handled, or is outside what the task changed. Default to refuted=true if unsure. Do not edit files.`

let reviewClean = false
let lastConfirmed = []
let carried = escalated
for (let round = 1; round <= maxRounds; round++) {
  phase('Review')
  const raw = (await parallel([
    ...lensRoles.map((l) => () =>
      run(l.role, reviewPrompt(l.stack ? `Your lens is the ${l.stack} stack: load conclave:stack-${l.stack} with the Skill tool first and apply its review checklist. ` : ''), { phase: 'Review', schema: FINDINGS, label: `review:${l.stack ? `stack:${l.stack}` : l.role.replace('reviewer-', '')} r${round}` })
        .then((res) => (res ? res.findings.map((f) => ({ ...f, lens: l.stack || l.role.replace('reviewer-', '') })) : []))),
    ...adhocReviewers.map((spec) => () =>
      runAdhoc(spec, `${reviewPrompt()}\n\nReport findings only with a concrete failure scenario; an empty list is valid.`, { phase: 'Review', schema: FINDINGS, label: `review:${spec.name} r${round}` })
        .then((res) => (res ? res.findings.map((f) => ({ ...f, lens: spec.name })) : []))),
  ])).filter(Boolean).flat()
  const fresh = dedupe([...carried, ...raw])
  carried = []
  log(`review round ${round}: ${raw.length} finding(s), ${fresh.length} after dedup with escalations`)
  if (!fresh.length) { reviewClean = true; lastConfirmed = []; break }

  phase('Verify')
  const judged = (await parallel(fresh.map((f) => async () => {
    const votes = f.severity === 'high' ? votesHigh : 1
    const verdicts = (await parallel(Array.from({ length: votes }, (_, i) => () =>
      run('refuter', refutePrompt(f), { phase: 'Verify', schema: VERDICT, label: `verify:${(f.file || '').split('/').pop()}${votes > 1 ? ` v${i + 1}` : ''}`, ...(votes > 1 && tier >= 3 && i === 0 ? { model: modelFor('pm') } : {}) })))).filter(Boolean)
    const refutedCount = verdicts.filter((v) => v.refuted).length
    const refuted = verdicts.length ? refutedCount * 2 > verdicts.length || (votes === 1 && refutedCount === 1) : true
    return { ...f, refuted, verdict_reason: verdicts.map((v) => v.reason).join(' | ') || 'refuter failed' }
  }))).filter(Boolean)
  lastConfirmed = judged.filter((f) => !f.refuted)
  log(`review round ${round}: ${lastConfirmed.length}/${fresh.length} finding(s) survived refutation`)
  if (!lastConfirmed.length) { reviewClean = true; break }

  phase('Fix')
  await routeFixes(lastConfirmed, 'Independent review confirmed these findings', 'Fix', `fix r${round}`)
  history.push({ phase: `fix r${round}`, reports: { ...reports }, findings: lastConfirmed })
  { const s = await guardTree('Fix', `verify:fix r${round}`); if (s) return s }
  if (round === maxRounds) {
    // No full review round left: re-check each fixed finding with one refuter instead.
    phase('Verify')
    const rechecked = (await parallel(lastConfirmed.map((f) => () =>
      run('refuter',
        `This finding was confirmed by review and the owning role reports it fixed:\n${show(f)}\n\nCurrent reports:\n${allReports()}\n\n${context(components)}\n\n` +
        `Read the code at that location now (git diff ${base}). Set fixed=true only if the failure scenario is no longer reachable and the fix is complete and not a shortcut (no suppression, no weakened test, no swallowed error). Do not edit files.`,
        { phase: 'Verify', schema: RECHECK, label: `recheck:${(f.file || '').split('/').pop()}` })
        .then((v) => ({ ...f, fixed: v ? v.fixed : false, recheck_reason: v ? v.reason : 'recheck failed' }))))).filter(Boolean)
    const unresolved = rechecked.filter((f) => !f.fixed)
    log(`re-check after the last fix round: ${rechecked.length - unresolved.length}/${rechecked.length} fixed`)
    if (!unresolved.length) { reviewClean = true; lastConfirmed = [] } else lastConfirmed = unresolved
  }
}
if (!reviewClean) return stop('Review', 'Review rounds exhausted with confirmed findings still open. Decide: another round, a narrower task, or accept with the findings documented.', { unresolved_findings: lastConfirmed })

// ---- Probes (mutation) -----------------------------------------------------
let probes = null
if (gates.mutation_probes && !skip.has('tests')) {
  const targets = contract.tests.length
    ? contract.tests.map((t) => ({ file: t.file, name: t.name }))
    : components.flatMap((c) => (reports[c].tests_added || []).map((n) => ({ file: '(see the dev report)', name: n })))
  if (!targets.length) log('mutation probes: no tests to probe')
  else {
    phase('Probes')
    const probePrompt = (list, extra) =>
      `${context(components)}\n\n${allReports()}\n\nMUTATION PROBES. Tests to probe:\n${list.map((t) => `  ${t.file}::${t.name}`).join('\n')}\n\n` +
      `For each test, apply ONE targeted sabotage to the implementation that should make that test fail (invert the guard, drop the rollback, skip the lock, return early), rebuild if needed, run the test, record whether it failed. Then restore the file exactly (git checkout -- for tracked files; a saved copy for untracked files) and prove it with sha256sum before == after. Work sequentially. ${extra || ''}` +
      `verdict "pass" if every probe failed its test and the tree is restored; "reject" with the reason otherwise; "escalate" if you believe a test itself is wrong.`
    probes = await run('test-auditor', probePrompt(targets), { phase: 'Probes', schema: PROBES, label: 'probes' })
    if (!probes) return stop('Probes', 'The test auditor returned nothing from the mutation probes; inspect git status before continuing.', {})
    if (!probes.tree_restored) return stop('Probes', 'The test auditor could not prove it restored the working tree after the mutation probes. Inspect git status and git diff before continuing.', { runs: probes.runs })
    if (probes.verdict === 'escalate') return stop('Probes', `The test auditor believes a test is wrong: ${probes.rejection}`, { probes: probes.probes })
    const survivors = probes.probes.filter((p) => !p.test_failed)
    if (probes.verdict === 'reject' || survivors.length) {
      log(`mutation probes: ${survivors.length} surviving probe(s); the test engineer repairs the tests`)
      const repair = await run('test-engineer',
        `${context(components)}\n\nREPAIR MODE. The implementation passed review and must not be modified. The test auditor found tests that passed while the implementation was sabotaged; strengthen each so the SAME sabotage makes it fail, keep its name, never weaken an assertion. Report every file touched.\n\n` +
        `Surviving probes:\n${survivors.map((p) => `- ${p.file}::${p.name} survived: ${p.mutation}`).join('\n') || '(none listed)'}\n\nAuditor's rejection: ${probes.rejection}`,
        { phase: 'Probes', schema: TESTS, label: 'probes:repair' })
      if (!repair) return stop('Probes', 'The test engineer returned nothing from the repair.', { survivors })
      const again = await run('test-auditor', probePrompt(survivors.map((p) => ({ file: p.file, name: p.name })), `Re-apply exactly these sabotages: ${survivors.map((p) => `${p.file}::${p.name}: ${p.mutation}`).join('; ')}. `), { phase: 'Probes', schema: PROBES, label: 'probes:again' })
      if (!again || !again.tree_restored) return stop('Probes', 'The test auditor could not prove it restored the working tree after the repair probes.', { runs: again ? again.runs : [] })
      if (again.verdict !== 'pass') return stop('Probes', `The test engineer could not repair the tests to the auditor's satisfaction: ${again.rejection}`, { probes: again.probes })
      probes = { ...probes, verdict: 'pass', probes: [...probes.probes.filter((p) => p.test_failed), ...again.probes], repaired_files: repair.test_files || [] }
      if (contract.checksums && (repair.test_files || []).length) {
        const sums = await freeze(uniq([...contract.files, ...repair.test_files]), 'Probes', 'probes:refreeze')
        if (!sums) return stop('Probes', 'Could not re-freeze the contract tests after the repair.', {})
        contract = { ...contract, files: uniq([...contract.files, ...repair.test_files]), checksums: sums }
      }
    }
  }
}

// ---- Tests (black-box) -----------------------------------------------------
let tests = null
if (!skip.has('tests')) {
  phase('Tests')
  tests = await run('test-engineer',
    `${context(components)}\n\n${allReports()}\n\nBriefs:\n${show(briefs)}\n\n` +
    (contract.tests.length ? `Contract tests already exist and are frozen (do not edit them):\n${contractList()}\n\nCover what they do not: ` : '') +
    `Derive the case list from the task, the contracts and the expected failures BEFORE reading the implementation, then cover every gap. Compare against ${base}.`,
    { phase: 'Tests', schema: TESTS, label: 'test-engineer' })
  if (tests && tests.bugs.length) {
    log(`test engineer proved ${tests.bugs.length} bug(s); routing to the devs`)
    await routeFixes(tests.bugs.map((b) => ({ ...b, severity: 'high' })), 'The test engineer wrote tests that fail and believes these are defects. Make the tests pass by fixing the code; never weaken a test', 'Tests', 'bugfix')
    { const s = await guardTree('Tests', 'verify:tests'); if (s) return s }
  }
}

// ---- Docs ------------------------------------------------------------------
let docs = null
let docCorrections = []
if (!skip.has('docs') && ((profile.docs || {}).paths || []).length) {
  phase('Docs')
  docsTouched = true
  docs = await run('docs-writer', `Bring the documentation in line with this change. Docs you own: ${show(profile.docs)}.\n\n${context(components)}\n\n${allReports()}`, { phase: 'Docs', schema: DOCS, label: 'docs' })
  if (docs && docs.files_changed.length) {
    const audit = await run('docs-writer',
      `AUDIT MODE. Another writer updated these documentation files for the change in the working tree: ${docs.files_changed.join(' ')}. Docs block: ${show(profile.docs)}.\n\n${context(components)}\n\n` +
      `Read git diff ${base} for both the code and the documentation. Check every claim in the changed documentation and in the comments of the changed source files against the code, with file and line. Report concrete corrections only; an empty list is a valid answer. Do not edit anything.`,
      { phase: 'Docs', schema: DOC_AUDIT, label: 'docs:audit' })
    docCorrections = audit ? audit.corrections : []
    if (docCorrections.length) {
      log(`docs audit: ${docCorrections.length} correction(s)`)
      const fixed = await run('docs-writer',
        `An auditor checked your documentation against the code and reports these corrections. Apply each one you can verify in the code; for any you believe is wrong, leave the text and say why under gaps. Docs you own: ${show(profile.docs)}.\n\n${context(components)}\n\n${docCorrections.map((c) => `- ${c.file}: "${c.quoted}" → ${c.true_statement} (evidence: ${c.evidence})`).join('\n')}`,
        { phase: 'Docs', schema: DOCS, label: 'docs:fix' })
      if (fixed) docs = { ...fixed, corrections_applied: docCorrections.length }
    }
  }
}

// ---- QA --------------------------------------------------------------------
let qa = null
if (!skip.has('qa')) {
  phase('QA')
  const qaPrompt = () =>
    `Verify this change end to end. Base ref: ${base}. Gates: ${show(gates)}. Plugin bin dir with diff-coverage.sh, shortcut-audit.sh, scope-check.sh and freeze.sh: ${bin}.\n` +
    `Allowed paths for the scope gate: ${allowedPaths(components, extraAllowed()).join(' ')}.\n` +
    (contract.checksums ? `Frozen checksums for the frozen gate (feed to freeze.sh verify on stdin):\n${contract.checksums}\n` : '') +
    `\n${context(components)}\n\n${allReports()}`
  qa = await run('qa', qaPrompt(), { phase: 'QA', schema: QA, label: 'qa' })
  if (qa && !qa.all_green) {
    const red = qa.suites.filter((s) => !s.passed).map((s) => s.name)
    log(`QA red (${red.join(', ') || 'gates'}); one repair round`)
    const items = [
      ...(qa.code_fixes_needed || []).map((c) => ({ file: 'see detail', severity: 'high', summary: c, failure_scenario: c })),
      ...(qa.flaky || []).map((t) => ({ file: 'see detail', severity: 'medium', summary: `flaky: ${t}`, failure_scenario: `failed at least once in ${gates.flake_runs || 3} runs` })),
    ]
    await parallel(components.map((c) => () =>
      devFix(c, fixPrompt(c, items, `QA is red. Fix what is yours in component "${c}" (application code or a wrong test, never a weakened test); uncovered lines need tests`) + `\n\nQA report:\n${show(qa)}`, `qa-fix:${c}`, 'QA')))
    qa = await run('qa', qaPrompt(), { phase: 'QA', schema: QA, label: 'qa rerun' })
  }
}

log(`agents used: ${agentCount.n} (${Object.entries(agentCount.byModel).map(([m, n]) => `${m}×${n}`).join(', ')})`)
const ready = Boolean(reviewClean && (skip.has('qa') || (qa && qa.all_green)))
const commitPlan = []
if (contract.files.length) commitPlan.push({ title: 'test: add contract tests (red before the implementation)', files: contract.files, rationale: 'the frozen contract; red at this commit' })
for (const c of components) for (const s of (reports[c].commit_plan || [])) commitPlan.push({ ...s, component: c })
if (tests && (tests.tests_added || []).length) commitPlan.push({ title: 'test: black-box tests from the failure matrix', files: tests.test_files || [], rationale: 'test engineer additions' })
if (docs && docs.files_changed.length) commitPlan.push({ title: 'docs: align documentation with the change', files: docs.files_changed, rationale: 'docs writer, audited' })
return {
  status: ready ? 'accepted' : 'not-ready',
  task, tier, components,
  spec,
  plan: { summary: plan.summary, contracts: plan.contracts, expected_failures: plan.expected_failures, specialists: plan.specialists, risks: plan.risks, assumptions: plan.assumptions },
  design: duelResult,
  contract: contract.tests.length ? { tests: contract.tests, files: contract.files } : null,
  review_clean: reviewClean,
  unresolved_findings: reviewClean ? [] : lastConfirmed,
  probes: probes && { verdict: probes.verdict, probes: probes.probes },
  tests, docs, qa, history,
  commit_plan: commitPlan,
  agents: agentCount,
  ready_to_commit: ready,
}
