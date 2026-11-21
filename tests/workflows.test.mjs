// Control-flow tests for the workflow scripts, with a scripted fake agent().
//
//   node tests/workflows.test.mjs
//
// Each scenario runs a workflow script against a profile and an exec plan; the fake agent
// answers by label. The assertions check where the run ends (status, phase), which phases
// ran, and which roles were spawned. No model is called.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const wf = (name) => path.join(root, 'plugins/conclave/workflows', `${name}.js`)
const template = JSON.parse(fs.readFileSync(path.join(root, 'plugins/conclave/templates/conclave.json'), 'utf8'))
const profileWith = (gates) => ({ ...template, gates: { ...template.gates, ...gates } })

// Loads a workflow script as an async function of the workflow globals. `meta` must be a
// literal, and top-level `return` is allowed by the runtime, so the body is wrapped.
function load(file) {
  const src = fs.readFileSync(file, 'utf8')
  if (!/^export const meta = \{/m.test(src)) throw new Error(`${file}: must start with export const meta`)
  const body = src.replace(/^export const meta/m, 'const meta')
  // eslint-disable-next-line no-new-func
  return new Function('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', `return (async () => {\n${body}\n})()`)
}

// A verifier that runs scope-check.sh as bin/scope-check.sh would: the allowed paths are the
// quoted arguments of the command in the prompt, `changed` is what git would list.
function scopeCheck(prompt, changed) {
  const line = prompt.split('\n').find((x) => x.includes('scope-check.sh')) || ''
  const allowed = [...line.matchAll(/'([^']*)'/g)].map((m) => m[1])
  const globRe = (g) => new RegExp('^' + g.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*\//g, '(.*/)?').replace(/\*\*/g, '.*').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]') + '$')
  const inScope = (f) => allowed.some((p) => p.endsWith('/') ? f.startsWith(p) : /[*?]/.test(p) ? globRe(p).test(f) : f === p)
  const out = changed.filter((f) => !inScope(f))
  return { runs: [{ command: line, exit_code: out.length ? 1 : 0, output_tail: out.map((f) => `out of scope: ${f}`).join('\n') }], all_passed: !out.length }
}

// The fake agent: answers each call by its label, with knobs per scenario.
function fakeAgent(sc, calls) {
  const st = { chal: {}, probes: 0, qa: 0 }
  return async (prompt, opts = {}) => {
    calls.push({ label: opts.label || '', type: (opts.agentType || 'plain').replace('conclave:', ''), model: opts.model || 'inherit', effort: opts.effort, schema: opts.schema, prompt })
    const l = opts.label || ''
    const comps = (sc.exec && sc.exec.components) || ['backend']
    if (!opts.schema) return 'guidance'
    if (l === 'profile') return { profile: template }
    if (l === 'analysis') return sc.noAnalysis ? null : { request: 'do x', current_state: sc.analysisState || 'read today: a.js calls b.js', constraints: ['c1 (docs/x.md)'], unknowns: [], components: comps, ...(sc.analysisDiagram ? { diagrams: [{ title: 'today flow', kind: 'flowchart', mermaid: 'flowchart LR\n  A["a.js"] --> B["b.js"]' }] } : {}) }
    if (l === 'design-study') return { problems: ['p'], proposed_model: 'model M', alternatives: [{ name: 'A', summary: 's', pros: ['x'], cons: ['y'] }], decisions: sc.designDecides && !(sc.exec && sc.exec.proceed) ? [{ question: 'storage?', options: [{ label: 'sqlite', consequence: 'c1' }, { label: 'files', consequence: 'c2' }], recommendation: 'sqlite' }] : [], migration: 'none', risks: [] }
    if (l === 'pm') return { summary: 's', goals: ['g'], acceptance: ['a'], components: comps, security_sensitive: false, needs_decision: sc.pmDecides ? [{ question: 'q', options: ['a', 'b'], recommendation: 'a' }] : [], assumptions: [] }
    if (l === 'architect') return { summary: 'p', components: comps, briefs: comps.map((c) => ({ component: c, brief: `brief ${c}` })), contracts: comps.length > 1 ? [{ between: ['backend', 'frontend'], text: 'GET /x' }] : [], expected_failures: ['a | b | c'], specialists: [], dev_specialities: ['data', 'concurrency'], needs_decision: sc.archDecides && !(sc.exec && sc.exec.proceed) ? [{ question: 'which index?', options: ['a', 'b'], recommendation: 'a' }] : [], security_sensitive: false, touches_infra: false }
    if (l.startsWith('design:') && l !== 'design:judge') return { approach: 'a', steps: ['s'], files: ['f'], risks: [], expected_tests: [], unsure: [] }
    if (l.startsWith('critique:')) return { verdict: sc.undecidable ? 'adopt_mine' : (l.endsWith('A') ? 'adopt_mine' : 'adopt_theirs'), objections: [], plan: 'plan A' }
    if (l === 'design:judge') return { winner: sc.undecidable ? 'undecidable' : 'A', plan: 'p', reasoning: 'r', decision_needed: 'which storage?' }
    if (l.startsWith('contract:try')) return { cases: ['c'], tests_added: ['t1'], test_files: ['backend/tests/test_c.py'], contract_tests: [{ file: 'backend/tests/test_c.py', name: 't1', criterion: 'a', behaviour: 'failure', expected_failure: 'assert 400' }], could_not_reproduce: false, bugs: [], untestable: [], checks_passed: false }
    if (l.startsWith('contract:audit')) return { valid: true, per_test: [{ file: 'backend/tests/test_c.py', name: 't1', fails_as_declared: true, actual_failure: 'assert 400', can_fail: true, note: '' }], other_tests_pass: true, runs: [] }
    if (l === 'contract:freeze' || l === 'probes:refreeze') return { runs: [{ command: 'freeze', exit_code: 0, output_tail: 'abc  backend/tests/test_c.py' }], all_passed: true }
    if (sc.changed && opts.agentType === 'conclave:verifier') return scopeCheck(prompt, sc.changed)
    if (l.startsWith('verify:') && /verify:(build|challenge|fix|tests)/.test(l)) {
      const scopeFail = sc.scopeFails && l === 'verify:build'
      const frozenFail = sc.frozenFails && l === 'verify:build'
      return { runs: [{ command: 'scope', exit_code: scopeFail ? 1 : 0, output_tail: scopeFail ? 'out of scope: docs/x.md\nout of scope: frontend/y.ts' : '' }, { command: 'frozen', exit_code: frozenFail ? 1 : 0, output_tail: '' }], all_passed: !scopeFail && !frozenFail }
    }
    if (l.startsWith('xcheck')) return { mismatches: [] }
    if (l.startsWith('challenge')) { const c = l.split(' ')[0]; st.chal[c] = (st.chal[c] || 0) + 1; return st.chal[c] === 1 ? { challenges: [{ file: 'backend/x.py', severity: 'high', summary: 'c1', why_it_matters: 'w', demand: 'd' }] } : { challenges: [], escalations: [] } }
    if (l.startsWith('review:') && sc.reviews) return { findings: sc.reviews(l) }
    if (l.startsWith('review:')) return l.includes('correctness') && (l.endsWith('r1') || !/ r\d$/.test(l)) && !sc.cleanReview ? { findings: [{ file: 'backend/x.py', line: 1, severity: 'high', summary: 'bug', failure_scenario: 'f' }] } : { findings: [] }
    if (l.startsWith('verify')) return { refuted: Boolean(sc.refuteAll), reason: 'r' }
    if (l.startsWith('recheck')) return { fixed: !sc.notFixed, reason: 'ok' }
    if (l === 'probes' || l === 'probes:again') {
      st.probes++
      if (sc.probeEscalate) return { probes: [], tree_restored: true, verdict: 'escalate', rejection: 'test t1 is wrong', runs: [] }
      return { probes: [{ file: 'backend/tests/test_c.py', name: 't1', mutation: 'invert guard', test_failed: st.probes > 1 }], tree_restored: true, verdict: st.probes > 1 ? 'pass' : 'reject', rejection: st.probes > 1 ? '' : 'survived', runs: [] }
    }
    if (l === 'probes:repair') return { cases: [], tests_added: ['t1'], test_files: ['backend/tests/test_c.py'], bugs: [], checks_passed: true }
    if (l === 'test-engineer') return { cases: ['c'], tests_added: ['t2'], test_files: ['backend/tests/test_d.py'], bugs: sc.teBugs ? [{ file: 'backend/x.py', line: 3, summary: 'te bug', failure_scenario: 'f' }] : [], untestable: [], checks_passed: true }
    if (l === 'docs') return { summary: 'd', files_changed: ['docs/a.md'] }
    if (l === 'docs:audit' && sc.auditNothing) return null
    if (l === 'docs:audit' && sc.auditEmpty) return { corrections: [] }
    if (l === 'docs:audit') return { corrections: [{ file: 'docs/a.md', quoted: 'x', true_statement: 'y', evidence: 'z' }] }
    if (l === 'docs:fix' || l.endsWith(':docs')) return { summary: 'fixed', files_changed: ['docs/a.md'] }
    if (l.startsWith('qa')) { st.qa++; return { all_green: !(sc.qaRed && st.qa === 1), suites: [{ name: 'tests', passed: !(sc.qaRed && st.qa === 1) }], code_fixes_needed: sc.qaRed && st.qa === 1 ? ['fix y'] : [] } }
    return { summary: 'dev', files_changed: ['backend/x.py'], checks_passed: true, rebuttals: [], commit_plan: [{ title: 'feat(backend): x', files: ['backend/x.py'], rationale: 'r' }] }
  }
}

async function runScenario(file, sc) {
  const calls = []
  const phases = []
  const parallel = async (thunks) => Promise.all(thunks.map(async (f) => { try { return await f() } catch (e) { return null } }))
  const result = await load(file)(sc.rawArgs !== undefined ? sc.rawArgs : { profile: sc.profile, exec: sc.exec }, fakeAgent(sc, calls), parallel, async () => [], (t) => phases.push(t), () => {}, { total: null })
  return { result, calls, phases: [...new Set(phases)], types: calls.map((c) => c.type), labels: calls.map((c) => c.label) }
}
const promptOf = (r, label) => (r.calls.find((c) => c.label === label) || {}).prompt || ''
const schemaOf = (r, label) => (r.calls.find((c) => c.label === label) || {}).schema

const T2 = { tier: 2, task: 'small', brief: 'Goal', components: ['backend'], rounds: 1, lenses: ['correctness', 'security', 'stack'], skip: ['pm', 'architect', 'consult', 'crosscheck', 'docs'], plugin_root: '/plug' }
const T3 = { tier: 3, task: 'feature', components: ['backend', 'frontend'], rounds: 2, lenses: ['correctness', 'security', 'stack', 'conventions', 'ux'], refute_votes_high: 3, plugin_root: '/plug' }
// An analysis as the lead passes it back in state after the checkpoint.
const A = { request: 'do x', current_state: 'today: a.js calls b.js', constraints: ['c1 (docs/x.md)'], unknowns: [] }
const PT = { task: 'x', components: ['backend'], plugin_root: '/plug' }
// A state as the build stage leaves it, for launching the review stage directly.
const reviewState = (components, extra) => ({
  components, plan: { summary: 'x', components, contracts: [], expected_failures: [], specialists: [] },
  briefs: Object.fromEntries(components.map((c) => [c, 'b'])),
  reports: Object.fromEntries(components.map((c) => [c, { summary: 'dev', files_changed: [], checks_passed: true }])),
  reviewClean: false, ...extra,
})
// Findings a review launch left open, with the verdict and recheck fields of that launch.
const OPEN = [
  { file: 'backend/a.py', line: 4, severity: 'medium', summary: 'open one', failure_scenario: 'f1', lens: 'correctness', refuted: false, verdict_reason: 'OLD-VERDICT-1', fixed: false, recheck_reason: 'OLD-RECHECK-1' },
  { file: 'backend/b.py', line: 9, severity: 'low', summary: 'open two', failure_scenario: 'f2', lens: 'security', refuted: false, verdict_reason: 'OLD-VERDICT-2', fixed: false, recheck_reason: 'OLD-RECHECK-2' },
]
// Refuter calls (not the verifier's scope checks), by label; their prompts.
const refuterLabels = (r) => r.calls.filter((c) => c.type === 'refuter' && c.label.startsWith('verify:')).map((c) => c.label)
const refuterPrompts = (r) => r.calls.filter((c) => c.type === 'refuter' && c.label.startsWith('verify:')).map((c) => c.prompt)
const recheckLabels = (r) => r.labels.filter((l) => l.startsWith('recheck:'))
const fixFindings = (r) => (r.result.state.history.find((h) => h.phase === 'fix r1') || {}).findings || []
const occurrences = (text, needle) => text.split(needle).length - 1
// Lenses that answer by label; the others return nothing.
const byLens = (table) => (label) => { const k = Object.keys(table).find((x) => label.startsWith(`review:${x}`)); return k ? table[k] : [] }
const T2R = (over) => ({ ...T2, stage: 'review', ...over })
const sharedBlock = (script) => {
  const src = fs.readFileSync(path.join(root, 'plugins/conclave/workflows', `${script}.js`), 'utf8')
  const start = src.indexOf('// ---- findings: path reduction and merge')
  const end = src.indexOf('// ---- end of the shared findings block ----')
  if (start < 0 || end < start) throw new Error(`${script}: shared findings block not found`)
  return src.slice(start, end)
}
// A profile whose component paths are short enough to occur twice in an absolute path.
const SHORT = { ...template, components: [{ ...template.components[0], paths: ['src/'], tests: ['tests/'] }, { ...template.components[1], paths: ['web/src/'], tests: ['web/tests/'] }] }
const LEAD = ['.gitignore', 'docs/plans/']
const CHANGED = ['backend/x.py', '.gitignore', 'docs/plans/p.md']

const cases = [
  ['dev-team T2 accepted', 'dev-team', { profile: profileWith({}), exec: T2 }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.result.ready_to_commit, true)
    notIncludes(r.types, 'pm'); notIncludes(r.phases, 'Plan'); includes(r.types, 'verifier')
    includes(r.result.commit_plan.map((s) => s.title), 'feat(backend): x')
  }],
  ['dev-team T3 with every option', 'dev-team', { profile: profileWith({ mutation_probes: true }), exec: { ...T3, contract: true, design: 'duel' } }, (r) => {
    eq(r.result.status, 'accepted')
    for (const p of ['Analysis', 'Plan', 'Design', 'Contract', 'Build', 'Cross-check', 'Challenge', 'Review', 'Verify', 'Fix', 'Probes', 'Tests', 'Docs', 'QA']) includes(r.phases, p)
    eq(r.result.design.winner, 'A'); eq(r.result.probes.verdict, 'pass')
    eq(r.result.commit_plan[0].title.startsWith('test: add contract tests'), true)
    includes(r.types, 'test-auditor')
  }],
  ['dev-team no profile reads it', 'dev-team', { exec: T2 }, (r) => { eq(r.phases[0], 'Profile'); eq(r.result.status, 'accepted') }],
  // Changed expectation (0.4.6): a T3 plan now starts with the architect's analysis.
  ['dev-team pm decisions stop', 'dev-team', { profile: profileWith({}), exec: T3, pmDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Plan'); eq(r.calls.length, 2); eq(r.labels.join(','), 'analysis,pm')
  }],
  ['dev-team frozen test modified stops', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], contract: true }, frozenFails: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Build')
  }],
  ['dev-team probe escalation stops', 'dev-team', { profile: profileWith({ mutation_probes: true }), exec: { ...T3, components: ['backend'], contract: true }, probeEscalate: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Probes')
  }],
  ['dev-team undecidable duel stops', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], design: 'duel' }, undecidable: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Design'); eq(r.result.decision_request.question, 'which storage?')
  }],
  ['dev-team out-of-scope edits go back to owners', 'dev-team', { profile: profileWith({}), exec: { ...T2, skip: ['pm', 'architect'] }, scopeFails: true }, (r) => {
    eq(r.result.status, 'accepted'); includes(r.calls.map((c) => c.label), 'verify:build-scope:docs')
  }],
  ['dev-team unresolved findings stop', 'dev-team', { profile: profileWith({}), exec: T2, notFixed: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Review')
  }],
  ['dev-team red QA gets one repair round', 'dev-team', { profile: profileWith({}), exec: T2, qaRed: true, cleanReview: true }, (r) => {
    eq(r.result.status, 'accepted'); includes(r.calls.map((c) => c.label), 'qa-fix:backend'); includes(r.calls.map((c) => c.label), 'qa rerun')
  }],
  // Changed expectation (0.4.6): the plan launch with no state runs the analysis first, no stop before the pm.
  ['staged: plan then build then review then finish, state chained', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan' } }, async (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.stage, 'plan'); eq(r.result.next_stage, 'build')
    eq(r.labels.join(','), 'analysis,pm,architect,consult:ux'); eq(r.result.state.analysis.current_state, 'read today: a.js calls b.js')
    eq(Object.keys(r.result.state.briefs).sort().join(','), 'backend,frontend')
    const sc = { profile: profileWith({}), exec: { ...T3, stage: 'build', state: { ...r.result.state, briefs: { ...r.result.state.briefs, backend: 'edited by the user' } } } }
    const b = await runScenario(wf('dev-team'), sc)
    eq(b.result.status, 'stage-done'); eq(b.result.stage, 'build'); eq(b.result.next_stage, 'review')
    notIncludes(b.types, 'pm'); includes(b.types, 'dev'); includes(b.types, 'challenger'); notIncludes(b.types, 'reviewer-correctness')
    eq(b.result.state.briefs.backend.startsWith('edited by the user'), true)
    eq(b.result.state.agents.n, r.result.state.agents.n + b.calls.length)
    const v = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'review', state: b.result.state } })
    eq(v.result.status, 'stage-done'); eq(v.result.stage, 'review'); eq(v.result.next_stage, 'finish')
    notIncludes(v.types, 'dev'.repeat(0) + 'challenger'); includes(v.types, 'reviewer-correctness'); includes(v.types, 'refuter'); eq(v.result.state.reviewClean, true)
    const f = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'finish', state: v.result.state } })
    eq(f.result.status, 'accepted'); eq(f.result.next_stage, null); includes(f.types, 'test-engineer'); includes(f.types, 'qa'); includes(f.types, 'docs-writer')
    eq(f.result.commit_plan.length > 0, true); eq(f.result.agents.n, v.result.state.agents.n + f.calls.length)
  }],
  ['staged: T2 build with a lead brief and no plan stage', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build' } }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'review'); notIncludes(r.types, 'pm'); eq(r.result.state.briefs.backend, 'Goal')
  }],
  ['staged: build without a plan stops', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'build' } }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.calls.length, 0)
  }],
  ['staged: finish refuses an unclean review', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'finish', state: { components: ['backend'], plan: { summary: 'x', contracts: [], expected_failures: [], specialists: [] }, briefs: { backend: 'b' }, reports: { backend: { files_changed: [] } }, reviewClean: false, unresolved: [{ file: 'x' }] } } }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.calls.length, 0)
  }],
  // Changed expectation (0.4.6): the first launch is analysis then pm; the resume does not re-read.
  ['staged: needs-human in plan carries state and resumes', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan' }, pmDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.stage, 'plan'); eq(r.result.state.plan, null)
    eq(r.labels.join(','), 'analysis,pm'); eq(r.result.state.analysis.request, 'do x')
    const again = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: r.result.state, decisions: 'use a', proceed: true }, pmDecides: true })
    eq(again.result.status, 'stage-done'); notIncludes(again.labels, 'analysis')
    eq(again.result.state.agents.n, 5) // analysis, pm twice, architect, ux consultant
  }],
  ['review clean', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security', 'stack'], components: ['backend'], plugin_root: '/plug' }, cleanReview: true }, (r) => {
    eq(r.result.status, 'accepted'); notIncludes(r.types, 'refuter')
  }],
  ['review with a confirmed finding', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness'], components: ['backend'], plugin_root: '/plug' } }, (r) => {
    eq(r.result.status, 'not-ready'); eq(r.result.confirmed.length, 1); includes(r.types, 'refuter')
  }],
  // Changed expectation (0.4.6): plan-team reads the current state before the pm.
  ['string launch: plan-team', 'plan-team', { rawArgs: 'add a thing', exec: {} }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.phases[0], 'Profile'); eq(r.labels.join(','), 'profile,analysis,pm,architect')
    eq(r.types.join(','), 'plain,architect,pm,architect'); eq(r.result.analysis.request, 'do x')
  }],
  ['string launch: review-team', 'review-team', { rawArgs: 'look at it', exec: {}, cleanReview: true }, (r) => { eq(r.result.status, 'accepted'); eq(r.phases[0], 'Profile') }],
  ['string launch: dev-team', 'dev-team', { rawArgs: 'build a thing', exec: {} }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.phases[0], 'Profile'); includes(r.types, 'pm'); includes(r.types, 'dev')
    eq(r.labels.slice(0, 3).join(','), 'profile,analysis,pm'); eq(r.result.analysis.request, 'do x'); eq(r.result.state.analysis.request, 'do x')
  }],
  ['object launch unchanged: empty object throws on missing task', 'dev-team', { rawArgs: {}, exec: {} }, (r) => { throw new Error('should have thrown') }],
  // Changed expectation (0.4.6): launched after the analysis checkpoint (state carries the
  // analysis), so the only call is the design study; the resume re-runs the study, not the analysis.
  ['design mode: plan-team stops on design decisions then resumes', 'plan-team', { profile: profileWith({}), exec: { task: 'redesign x', components: ['backend'], mode: 'design', plugin_root: '/plug', state: { analysis: A } }, designDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.decision_request.question, 'Design decisions'); eq(r.labels.join(','), 'design-study')
    eq(r.result.decision_request.context.decisions[0].options[0].consequence, 'c1')
    deepEq(r.result.analysis, A); deepEq(r.result.state.analysis, A); eq(r.result.design_study.proposed_model, 'model M')
    const again = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { task: 'redesign x', components: ['backend'], mode: 'design', plugin_root: '/plug', state: r.result.state, decisions: 'sqlite', proceed: true }, designDecides: true })
    eq(again.result.status, 'accepted'); eq(again.labels.join(','), 'design-study,pm,architect'); eq(again.result.design_study.proposed_model, 'model M')
    deepEq(again.result.state.analysis, A)
  }],
  // Changed expectation (0.4.6): launched with state.analysis; the resume runs neither the analysis nor the study.
  ['design mode: dev-team plan stage stops, resumes from state without re-running the study', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state: { analysis: A } }, designDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.labels.join(','), 'design-study'); eq(r.result.state.design_study.proposed_model, 'model M')
    eq(r.result.decision_request.question, 'Design decisions')
    eq(Object.keys(r.result.decision_request.context).sort().join(','), 'alternatives,decisions,proposed_model')
    deepEq(r.result.state.analysis, A)
    const p = promptOf(r, 'design-study')
    contains(p, A.current_state); matches(p, /Build on the analysis above/); matches(p, /under risks/)
    const again = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state: r.result.state, decisions: 'sqlite', proceed: true }, designDecides: true })
    eq(again.result.status, 'stage-done'); eq(again.labels.join(','), 'pm,architect,consult:ux'); eq(again.result.state.design_study.proposed_model, 'model M')
  }],
  ['design mode: dev-team with no state reads, then studies, then stops', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design' }, designDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.labels.join(','), 'analysis,design-study'); eq(r.result.decision_request.question, 'Design decisions')
    eq(r.result.state.analysis.request, 'do x')
  }],
  // Changed expectation (0.4.6): plan-team with no state reads the current state first.
  ['plan accepted', 'plan-team', { profile: profileWith({}), exec: PT }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.labels.join(','), 'analysis,pm,architect'); eq(r.result.analysis.request, 'do x')
    eq(r.result.stage, 'plan'); eq(r.result.next_stage, null); eq(r.result.state.analysis.request, 'do x'); eq(r.result.agents.n, 3)
  }],
  ['plan stops on decisions', 'plan-team', { profile: profileWith({}), exec: PT, pmDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.labels.join(','), 'analysis,pm'); eq(r.result.state.analysis.request, 'do x')
  }],

  // ---- dev-team: the analysis stage ----------------------------------------------------
  ['analysis stage: one architect call, stage-done, next plan', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis' } }, (r) => {
    eq(r.calls.length, 1); eq(r.calls[0].type, 'architect'); eq(r.calls[0].label, 'analysis'); eq(r.calls[0].model, 'inherit'); eq(r.calls[0].effort, 'high')
    eq(r.result.status, 'stage-done'); eq(r.result.stage, 'analysis'); eq(r.result.next_stage, 'plan'); eq(r.result.ready_to_commit, false)
    deepEq(r.result.state.analysis, { request: 'do x', current_state: 'read today: a.js calls b.js', constraints: ['c1 (docs/x.md)'], unknowns: [], components: ['backend', 'frontend'] })
    eq(r.result.state.spec, null); eq(r.result.state.plan, null); eq(r.result.state.agents.n, 1); includes(r.phases, 'Analysis')
    const p = r.calls[0].prompt
    contains(p, 'Task:\nfeature'); contains(p, `Project: ${template.name}.`); contains(p, 'Do not edit files')
    contains(p, 'ANALYSIS.'); lacks(p, 'Your previous analysis')
  }],
  ['analysis stage: exec.models override for architect and planners', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', models: { architect: 'x' } } }, async (r) => {
    eq(r.calls[0].model, 'x')
    const p = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'analysis', models: { planners: 'y' } } })
    eq(p.calls[0].model, 'y'); eq(p.calls[0].label, 'analysis')
  }],
  ['analysis stage: nothing returned stops with no analysis', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis' }, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.stage, 'analysis'); eq(r.result.phase, 'Analysis')
    matches(r.result.decision_request.question, /no analysis/); notIncludes(r.labels, 'pm'); eq(r.result.state.analysis, null)
  }],
  ['analysis stage: nothing returned on a revision keeps the previous reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: A }, decisions: 'b.js is not called' }, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); deepEq(r.result.state.analysis, A)
  }],
  ['analysis stage: a correction revises the previous reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: A }, decisions: 'b.js is called through c.js' }, analysisState: 'revised: a.js calls c.js' }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'plan')
    const p = r.calls[0].prompt
    contains(p, 'Your previous analysis:'); contains(p, A.current_state); contains(p, 'b.js is called through c.js')
    eq(r.result.state.analysis.current_state, 'revised: a.js calls c.js')
  }],
  ['analysis stage: no correction is a fresh reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: A } }, analysisState: 'fresh reading' }, (r) => {
    eq(r.labels.join(','), 'analysis'); lacks(r.calls[0].prompt, 'Your previous analysis'); lacks(r.calls[0].prompt, A.current_state)
    eq(r.result.state.analysis.current_state, 'fresh reading')
  }],
  ['analysis stage: other state keys come back unchanged', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { design_study: { proposed_model: 'M0', migration: 'none' }, spec: { summary: 'S0' }, agents: { n: 3 } } } }, (r) => {
    deepEq(r.result.state.design_study, { proposed_model: 'M0', migration: 'none' }); deepEq(r.result.state.spec, { summary: 'S0' }); eq(r.result.state.agents.n, 4)
  }],
  ['analysis stage: skip analysis does not suppress the explicit stage', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', skip: ['analysis'] } }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done')
  }],

  // ---- dev-team: the plan stage with and without an analysis ------------------------------
  ['plan stage with state.analysis: no re-read, prompts carry it', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: A, agents: { n: 1 } } } }, (r) => {
    eq(r.labels.join(','), 'pm,architect,consult:ux'); eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'build')
    deepEq(r.result.state.analysis, A)
    contains(promptOf(r, 'pm'), A.current_state); contains(promptOf(r, 'architect'), A.current_state)
    contains(promptOf(r, 'pm'), 'Analysis (the reading of the code this task rests on; work from it):')
    eq(r.result.state.agents.n, 1 + r.calls.length)
  }],
  ['plan stage, skip analysis: pm and architect without a reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', skip: ['analysis'] } }, (r) => {
    notIncludes(r.labels, 'analysis'); eq(r.labels.slice(0, 2).join(','), 'pm,architect'); eq(r.result.state.analysis, null)
    lacks(promptOf(r, 'pm'), 'Analysis (the reading')
  }],
  ['plan stage, skip architect: the analysis still runs before the pm', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', skip: ['architect'] } }, (r) => {
    eq(r.labels.slice(0, 2).join(','), 'analysis,pm'); eq(r.result.status, 'stage-done')
  }],
  ['plan stage, 0.4.5 state with design_study and spec but no analysis: analysis first', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state: { design_study: { problems: [], proposed_model: 'M0', alternatives: [], decisions: [], migration: 'none', risks: [] }, spec: { summary: 'S0' } } } }, (r) => {
    eq(r.labels.join(','), 'analysis,pm,architect,consult:ux'); eq(r.result.status, 'stage-done')
  }],
  ['plan stage, implicit analysis returns nothing: stop before the pm', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan' }, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); eq(r.result.stage, 'plan'); notIncludes(r.labels, 'pm')
    matches(r.result.decision_request.question, /no analysis/)
  }],
  ['plan stage, restored design_study with current_state: field ignored, study not re-run', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state: { analysis: A, design_study: { current_state: 'old reading', problems: [], proposed_model: 'M0', alternatives: [], decisions: [], migration: 'none', risks: [] } } } }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.labels.join(','), 'pm,architect,consult:ux'); eq(r.result.state.design_study.proposed_model, 'M0')
    // The old unconfirmed reading must not reach the planning architect next to the analysis.
    const arch = promptOf(r, 'architect')
    contains(arch, 'Design study:'); contains(arch, 'M0'); lacks(arch, 'old reading'); lacks(arch, '"current_state"')
  }],
  ['analysis stage with a lead brief: no plan, no briefs in the state', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'analysis' } }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'plan')
    eq(r.result.state.plan, null); deepEq(r.result.state.briefs, {})
  }],
  ['analysis diagrams and components reach the design study, pm and architect', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', proceed: true }, analysisDiagram: true }, (r) => {
    eq(r.labels.slice(0, 3).join(','), 'analysis,design-study,pm')
    for (const label of ['design-study', 'pm', 'architect']) {
      const p = promptOf(r, label)
      contains(p, 'Diagrams:\ntoday flow (flowchart):\n```mermaid\nflowchart LR\n  A["a.js"] --> B["b.js"]\n```')
      contains(p, 'Components:\n- backend\n- frontend')
    }
  }],
  ['analysis revision shows the previous diagrams and components', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: { ...A, components: ['backend'], diagrams: [{ title: 'old flow', mermaid: 'sequenceDiagram\n  a->>b: call' }] } }, decisions: 'b.js is called through c.js' } }, (r) => {
    const p = r.calls[0].prompt
    contains(p, 'Your previous analysis:'); contains(p, 'old flow:\n```mermaid\nsequenceDiagram\n  a->>b: call\n```'); contains(p, 'Components:\n- backend')
  }],
  ['analysis diagrams rewritten by the lead: odd shapes do not throw', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: { ...A, components: 'backend', diagrams: ['flowchart LR\n  X --> Y', { title: 't' }] } } } }, async (r) => {
    eq(r.result.status, 'stage-done'); const pm = promptOf(r, 'pm')
    contains(pm, 'Components:\nbackend'); contains(pm, 'Diagrams:\nflowchart LR\n  X --> Y\n\nt:\n```mermaid\n(none)\n```')
    const s = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: { ...A, diagrams: 'flowchart TD\n  P --> Q' } } } })
    eq(s.result.status, 'stage-done'); contains(promptOf(s, 'pm'), 'Diagrams:\nflowchart TD\n  P --> Q')
    lacks(promptOf(s, 'pm'), 'Components:')
  }],
  ['plan stage, analysis rewritten by the lead: lists as strings, Mermaid, plain string, empty object', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: { request: 'do x', current_state: 'flow:\n```mermaid\nflowchart LR\n  A["a.js"] --> B["b.js (x: y)"]\n```', constraints: 'c1; c2', unknowns: 'none open' } } } }, async (r) => {
    eq(r.result.status, 'stage-done'); notIncludes(r.labels, 'analysis')
    const pm = promptOf(r, 'pm')
    contains(pm, '```mermaid\nflowchart LR\n  A["a.js"] --> B["b.js (x: y)"]\n```'); contains(pm, 'c1; c2'); contains(pm, 'none open')
    const s = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: 'the whole reading as one string' } } })
    eq(s.result.status, 'stage-done'); notIncludes(s.labels, 'analysis'); contains(promptOf(s, 'pm'), 'the whole reading as one string')
    const e = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: {} } } })
    eq(e.result.status, 'stage-done'); notIncludes(e.labels, 'analysis')
  }],
  ['plan stage, pm decisions with an analysis: stop keeps it, resume does not re-read', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: A } }, pmDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.stage, 'plan'); deepEq(r.result.state.analysis, A); eq(r.result.state.plan, null)
    const again = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: r.result.state, decisions: 'use a', proceed: true }, pmDecides: true })
    eq(again.result.status, 'stage-done'); notIncludes(again.labels, 'analysis')
  }],
  ['plan stage after the analysis stage still stops on design, pm and architect decisions', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis' } }, async (r) => {
    const state = r.result.state
    const d = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state }, designDecides: true })
    eq(d.result.status, 'needs-human'); eq(d.result.decision_request.question, 'Design decisions'); eq(d.labels.join(','), 'design-study')
    const p = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state }, pmDecides: true })
    eq(p.result.status, 'needs-human'); eq(p.labels.join(','), 'pm')
    const a = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state }, archDecides: true })
    eq(a.result.status, 'needs-human'); eq(a.labels.join(','), 'pm,architect'); matches(a.result.decision_request.question, /from the architect/)
    deepEq(a.result.state.analysis, state.analysis)
  }],
  ['stage all, T3, no state: analysis before the pm, accepted', 'dev-team', { profile: profileWith({}), exec: T3 }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.labels.slice(0, 2).join(','), 'analysis,pm')
    eq(r.result.analysis.request, 'do x'); eq(r.result.state.analysis.request, 'do x')
  }],
  ['T2 lead brief, stage all and stage build: no analysis, no pm', 'dev-team', { profile: profileWith({}), exec: T2 }, async (r) => {
    eq(r.result.status, 'accepted'); notIncludes(r.labels, 'analysis'); notIncludes(r.labels, 'pm'); eq(r.result.analysis, null)
    const b = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'build' } })
    eq(b.result.status, 'stage-done'); notIncludes(b.labels, 'analysis'); notIncludes(b.labels, 'pm')
  }],
  ['stage all with a plan in state: no analysis', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], state: { components: ['backend'], plan: { summary: 'x', components: ['backend'], contracts: [], expected_failures: [], specialists: [] }, briefs: { backend: 'b' } } }, cleanReview: true }, (r) => {
    notIncludes(r.labels, 'analysis'); notIncludes(r.labels, 'pm'); eq(r.result.status, 'accepted')
  }],
  ['build, review and finish carry the analysis unchanged', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: { analysis: A } } }, async (r) => {
    const b = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'build', state: r.result.state } })
    notIncludes(b.labels, 'analysis'); deepEq(b.result.state.analysis, A)
    const v = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'review', state: b.result.state } })
    notIncludes(v.labels, 'analysis'); deepEq(v.result.state.analysis, A)
    const f = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'finish', state: v.result.state } })
    notIncludes(f.labels, 'analysis'); deepEq(f.result.state.analysis, A); deepEq(f.result.analysis, A)
  }],
  ['build at T3 with no plan in state: no analysis spent', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'build' } }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.calls.length, 0)
  }],

  // ---- shape: the analysis and design-study schemas of both scripts -----------------------
  ['shape: ANALYSIS and DESIGN_STUDY schemas in both scripts', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design' } }, async (r) => {
    const p = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, mode: 'design' } })
    for (const run of [r, p]) {
      const a = schemaOf(run, 'analysis')
      eq([...a.required].join(','), 'request,current_state,constraints,unknowns')
      eq(Object.keys(a.properties).sort().join(','), 'components,constraints,current_state,diagrams,request,unknowns')
      eq([...a.properties.diagrams.items.required].join(','), 'title,mermaid')
      const d = schemaOf(run, 'design-study')
      notIncludes(Object.keys(d.properties), 'current_state'); notIncludes(d.required, 'current_state')
      eq([...d.required].sort().join(','), 'alternatives,decisions,migration,problems,proposed_model,risks')
    }
    deepEq(schemaOf(r, 'analysis'), schemaOf(p, 'analysis')); deepEq(schemaOf(r, 'design-study'), schemaOf(p, 'design-study'))
  }],

  // ---- plan-team: stage, state and the analysis ------------------------------------------
  ['plan-team stage analysis: one call, stage-done', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis' } }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.calls[0].type, 'architect'); eq(r.calls[0].effort, 'high')
    eq(r.result.status, 'stage-done'); eq(r.result.stage, 'analysis'); eq(r.result.next_stage, 'plan')
    eq(r.result.spec, null); eq(r.result.plan, null); eq(r.result.design_study, null); eq(r.result.stopped_for_decisions, false)
    eq(r.result.agents.n, 1); deepEq(r.result.state.analysis, r.result.analysis); eq(r.result.analysis.request, 'do x')
    deepEq(Object.keys(r.result.state).sort(), ['agents', 'analysis'])
    contains(r.calls[0].prompt, 'Do not edit files'); contains(r.calls[0].prompt, 'ANALYSIS.')
  }],
  ['plan-team stage analysis: a correction revises the reading', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis', state: { analysis: A, agents: { n: 1 } }, decisions: 'b.js is called through c.js' }, analysisState: 'revised' }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.labels.join(','), 'analysis')
    const p = r.calls[0].prompt
    contains(p, 'Your previous analysis:'); contains(p, A.current_state); contains(p, 'b.js is called through c.js')
    eq(r.result.analysis.current_state, 'revised'); eq(r.result.agents.n, 2)
  }],
  ['plan-team stage analysis: nothing returned stops, no throw, no pm', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis' }, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); matches(r.result.decision_request.question, /no analysis/)
    eq(r.result.stopped_for_decisions, false); notIncludes(r.labels, 'pm'); eq(r.result.state.analysis, null)
  }],
  ['plan-team plan launch, implicit analysis returns nothing: stop before the pm', 'plan-team', { profile: profileWith({}), exec: PT, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); notIncludes(r.labels, 'pm')
  }],
  ['plan-team plan launch with exec.state.analysis: pm, architect, prompts carry it', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'plan', state: { analysis: A, agents: { n: 1 } } } }, async (r) => {
    eq(r.labels.join(','), 'pm,architect'); eq(r.result.status, 'accepted'); deepEq(r.result.analysis, A); deepEq(r.result.state.analysis, A)
    contains(promptOf(r, 'pm'), A.current_state); contains(promptOf(r, 'architect'), A.current_state)
    eq(r.result.agents.n, 3); eq(r.result.agents.this_stage, 2); eq(r.result.state.agents.n, 3)
    const absent = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, state: { analysis: A } } })
    eq(absent.labels.join(','), 'pm,architect'); eq(absent.result.status, 'accepted')
  }],
  ['plan-team plan launch, analysis rewritten by the lead: raw strings reach the prompts', 'plan-team', { profile: profileWith({}), exec: { ...PT, state: { analysis: 'the whole reading as one string' } } }, async (r) => {
    eq(r.result.status, 'accepted'); eq(r.labels.join(','), 'pm,architect'); contains(promptOf(r, 'pm'), 'the whole reading as one string'); lacks(promptOf(r, 'pm'), '"the whole reading')
    const l = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, state: { analysis: { request: 'do x', current_state: 'flow:\n```mermaid\nflowchart LR\n  A --> B\n```', constraints: 'c1; c2', unknowns: 'none open' } } } })
    eq(l.result.status, 'accepted'); contains(promptOf(l, 'architect'), '```mermaid\nflowchart LR\n  A --> B\n```'); contains(promptOf(l, 'pm'), 'c1; c2')
  }],
  ['plan-team: analysis diagrams and components reach the pm and the architect', 'plan-team', { profile: profileWith({}), exec: { ...PT, components: ['backend'] }, analysisDiagram: true }, (r) => {
    eq(r.labels.join(','), 'analysis,pm,architect')
    for (const label of ['pm', 'architect']) {
      const p = promptOf(r, label)
      contains(p, 'Diagrams:\ntoday flow (flowchart):\n```mermaid\nflowchart LR\n  A["a.js"] --> B["b.js"]\n```'); contains(p, 'Components:\n- backend')
    }
  }],
  ['plan-team: every needs-human carries state.analysis', 'plan-team', { profile: profileWith({}), exec: { ...PT, state: { analysis: A } }, pmDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); deepEq(r.result.state.analysis, A); deepEq(r.result.analysis, A); eq(r.result.stage, 'plan'); eq(r.result.next_stage, null)
    const a = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, state: { analysis: A } }, archDecides: true })
    eq(a.result.status, 'needs-human'); deepEq(a.result.state.analysis, A); eq(a.labels.join(','), 'pm,architect')
  }],
  ['plan-team stage analysis state feeds dev-team stage plan without a re-read', 'plan-team', { profile: profileWith({}), exec: { task: 'feature', components: ['backend', 'frontend'], plugin_root: '/plug', stage: 'analysis' } }, async (r) => {
    const d = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', state: r.result.state } })
    eq(d.result.status, 'stage-done'); notIncludes(d.labels, 'analysis'); deepEq(d.result.state.analysis, r.result.analysis)
    eq(d.result.state.agents.n, 1 + d.calls.length)
  }],

  // ---- challenger (workflows, round 1) ----------------------------------------------------
  // The lead re-triages with analysis.components between the analysis stage and the plan
  // stage, then launches plan with the saved state and the re-triaged exec.components. The
  // plan stage must work on the re-triaged components, not on the guess frozen into the
  // analysis stage's state.
  ['challenger: re-triaged exec.components after the analysis stage reach the plan stage', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], stage: 'analysis' } }, async (r) => {
    eq(r.result.status, 'stage-done')
    const p = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, components: ['backend', 'frontend'], stage: 'plan', state: r.result.state } })
    contains(promptOf(p, 'pm'), '"name": "frontend"')
    const s = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, components: ['backend', 'frontend'], stage: 'plan', skip: ['pm', 'architect'], state: r.result.state } })
    eq(Object.keys(s.result.state.briefs).sort().join(','), 'backend,frontend')
  }],
  // Contract 6: plan-team restores only analysis and agents; a dev-team-shaped state with a
  // study, a spec and a plan must not short-circuit the study, the pm or the architect.
  ['challenger: plan-team ignores design_study, spec and plan in exec.state', 'plan-team', { profile: profileWith({}), exec: { ...PT, mode: 'design', state: { analysis: A, design_study: { problems: [], proposed_model: 'STALE', alternatives: [], decisions: [], migration: 'none', risks: [] }, spec: { summary: 'STALE' }, plan: { summary: 'STALE' }, agents: { n: 2 } } } }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.labels.join(','), 'design-study,pm,architect')
    eq(r.result.design_study.proposed_model, 'model M'); eq(r.result.spec.summary, 's')
    deepEq(Object.keys(r.result.state).sort(), ['agents', 'analysis']); eq(r.result.agents.n, 5)
    lacks(promptOf(r, 'pm'), 'STALE')
  }],
  // With skip: ["analysis"] in design mode nobody reads the current state any more: the old
  // study asked for "how it works today (with file references)", the reduced one only asks
  // for a proposal. Without an analysis the study must still be told to read the code first.
  ['challenger: design study without an analysis is still told to read the code', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', skip: ['analysis'] }, designDecides: true }, (r) => {
    eq(r.labels.join(','), 'design-study')
    matches(promptOf(r, 'design-study'), /read the code|file reference/i)
  }],
  // Response to the challenger: the components precedence and the study clause, each way.
  ['analysis launched without components: an empty state.components does not hide the re-triage', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: undefined, stage: 'analysis' } }, async (r) => {
    eq(r.result.status, 'stage-done'); deepEq(r.result.state.components, [])
    const s = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, components: ['frontend'], stage: 'plan', skip: ['pm', 'architect'], state: r.result.state } })
    eq(s.result.status, 'stage-done'); deepEq(s.result.state.components, ['frontend']); eq(Object.keys(s.result.state.briefs).join(','), 'frontend')
  }],
  ['plan launch without exec.components keeps the components of the state', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], stage: 'analysis' } }, async (r) => {
    const s = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, components: undefined, stage: 'plan', skip: ['pm', 'architect'], state: r.result.state } })
    eq(s.result.status, 'stage-done'); deepEq(s.result.state.components, ['backend'])
  }],
  ['once a plan exists its components win over exec.components', 'dev-team', { profile: profileWith({}), exec: { ...T3, components: ['backend'], stage: 'plan' } }, async (r) => {
    eq(r.result.status, 'stage-done'); deepEq(r.result.state.components, ['backend'])
    const b = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, components: ['backend', 'frontend'], stage: 'build', state: r.result.state } })
    deepEq(b.result.components, ['backend']); includes(b.labels, 'build:backend'); notIncludes(b.labels, 'build:frontend')
  }],
  ['design study with an analysis is told to build on it, not to re-read the code', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', state: { analysis: A } }, designDecides: true }, (r) => {
    const p = promptOf(r, 'design-study')
    contains(p, 'Build on the analysis above'); lacks(p, 'No analysis precedes this study')
  }],
  ['design study clauses are the same text in both scripts', 'plan-team', { profile: profileWith({}), exec: { ...PT, mode: 'design' }, designDecides: true }, async (r) => {
    const lineOf = (script) => fs.readFileSync(path.join(root, 'plugins/conclave/workflows', `${script}.js`), 'utf8').split('\n').find((l) => l.includes('Build on the analysis above'))
    eq(lineOf('plan-team'), lineOf('dev-team')); contains(lineOf('dev-team'), 'No analysis precedes this study: read the code this change touches first')
    contains(promptOf(r, 'design-study'), 'Build on the analysis above')
  }],

  // ---- test engineer (round 2): return keys, boundaries and plan-team parity -----------------
  ['te: dev-team analysis stage returns the contract keys, counts one agent', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis' } }, (r) => {
    for (const k of ['status', 'stage', 'next_stage', 'state', 'summary', 'agents', 'ready_to_commit']) includes(Object.keys(r.result), k)
    eq(r.result.agents.n, 1); eq(r.result.agents.this_stage, 1); eq(r.result.summary.agents_used, 1)
    eq(r.result.state.design_study, null); eq(r.result.state.design, null)
  }],
  ['te: dev-team analysis stage failure keeps the restored state and stays at analysis', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: A, spec: { summary: 'S0' }, agents: { n: 3 } }, decisions: 'b.js is not called' }, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.stage, 'analysis'); eq(r.result.next_stage, 'plan'); eq(r.result.ready_to_commit, false)
    matches(r.result.decision_request.question, /no analysis/); eq(r.labels.join(','), 'analysis')
    deepEq(r.result.state.analysis, A); deepEq(r.result.state.spec, { summary: 'S0' })
  }],
  ['te: dev-team analysis stage in design mode runs no design study', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', mode: 'design', design: 'duel', contract: true }, designDecides: true }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'plan')
    eq(r.result.state.design_study, null); eq(r.result.state.plan, null)
  }],
  ['te: dev-team analysis stage keeps a restored plan, briefs and components', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { components: ['backend'], plan: { summary: 'P0', components: ['backend'], contracts: [], expected_failures: [], specialists: [] }, briefs: { backend: 'B0' } } } }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done')
    eq(r.result.state.plan.summary, 'P0'); deepEq(r.result.state.briefs, { backend: 'B0' }); deepEq(r.result.state.components, ['backend'])
    eq(r.result.state.analysis.request, 'do x')
  }],
  ['te: dev-team analysis stage with a correction but no previous reading is a fresh reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', decisions: 'b.js is not called' } }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); lacks(r.calls[0].prompt, 'Your previous analysis')
    eq(r.result.state.analysis.request, 'do x')
  }],
  ['te: dev-team analysis revision prompt keeps the context block and the instruction', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', state: { analysis: A }, decisions: 'b.js is called through c.js' } }, (r) => {
    const p = r.calls[0].prompt
    contains(p, `Project: ${template.name}.`); contains(p, 'Task:\nfeature'); contains(p, 'ANALYSIS.'); contains(p, 'Do not edit files')
    // The previous reading and the correction come before the instruction that asks for the whole reading again.
    eq(p.indexOf('Your previous analysis:') < p.indexOf('ANALYSIS.'), true); eq(p.indexOf('b.js is called through c.js') < p.indexOf('ANALYSIS.'), true)
  }],
  ['te: dev-team exec.proceed is not read by the analysis: explicit stage and implicit run both still read', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'analysis', proceed: true } }, async (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'plan')
    const p = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T3, stage: 'plan', proceed: true } })
    eq(p.labels.slice(0, 2).join(','), 'analysis,pm'); eq(p.result.status, 'stage-done')
  }],
  ['te: dev-team unknown stage value runs all stages with the analysis first', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'Analysis' } }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.labels.slice(0, 2).join(','), 'analysis,pm'); eq(r.result.analysis.request, 'do x')
  }],
  ['te: dev-team implicit analysis failure in an all-stages launch stops before the pm', 'dev-team', { profile: profileWith({}), exec: T3, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); eq(r.result.stage, 'all'); eq(r.labels.join(','), 'analysis')
    eq(r.result.state.analysis, null); eq(r.result.state.plan, null)
  }],
  ['te: dev-team T2 lead brief, stage plan: no analysis, no pm', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'plan' } }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.next_stage, 'build'); notIncludes(r.labels, 'analysis'); notIncludes(r.labels, 'pm')
    eq(r.result.state.analysis, null); eq(r.result.state.briefs.backend, 'Goal')
  }],
  ['te: dev-team design mode, no analysis in state but proceed: the study gets the fresh reading', 'dev-team', { profile: profileWith({}), exec: { ...T3, stage: 'plan', mode: 'design', proceed: true }, designDecides: true }, (r) => {
    eq(r.labels.slice(0, 3).join(','), 'analysis,design-study,pm'); eq(r.result.status, 'stage-done')
    const p = promptOf(r, 'design-study')
    contains(p, 'DESIGN STUDY.'); contains(p, 'read today: a.js calls b.js'); contains(p, 'Build on the analysis above')
    eq(p.indexOf('read today: a.js calls b.js') < p.indexOf('DESIGN STUDY.'), true)
  }],

  ['te: plan-team stage analysis returns exactly the contract keys', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis' } }, (r) => {
    deepEq(Object.keys(r.result).sort(), ['agents', 'analysis', 'design_study', 'next_stage', 'plan', 'spec', 'stage', 'state', 'status', 'stopped_for_decisions', 'task'])
    eq(r.result.task, 'x'); eq(r.result.agents.this_stage, 1); eq(typeof r.result.agents.byModel, 'object'); deepEq(r.result.state.agents, r.result.agents)
  }],
  ['te: plan-team analysis prompt carries the context block and the component choice', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis' } }, (r) => {
    const p = r.calls[0].prompt
    contains(p, `Project: ${template.name}.`); contains(p, 'x'); contains(p, 'ANALYSIS.'); contains(p, 'Do not edit files')
    for (const c of template.components) contains(p, c.name)
    lacks(p, 'Your previous analysis')
  }],
  ['te: plan-team stage analysis without a correction is a fresh reading that replaces the state', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis', state: { analysis: A, agents: { n: 2 } } }, analysisState: 'fresh' }, (r) => {
    eq(r.labels.join(','), 'analysis'); lacks(r.calls[0].prompt, 'Your previous analysis'); lacks(r.calls[0].prompt, A.current_state)
    eq(r.result.analysis.current_state, 'fresh'); eq(r.result.state.analysis.current_state, 'fresh'); eq(r.result.agents.n, 3)
  }],
  ['te: plan-team stage analysis in design mode runs no study', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis', mode: 'design' }, designDecides: true }, (r) => {
    eq(r.labels.join(','), 'analysis'); eq(r.result.status, 'stage-done'); eq(r.result.design_study, null)
  }],
  ['te: plan-team analysis call takes the planners policy and exec.models overrides', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'analysis' } }, async (r) => {
    eq(r.calls[0].model, 'inherit'); eq(r.calls[0].effort, 'high')
    const a = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, stage: 'analysis', models: { architect: 'x' } } })
    eq(a.calls[0].label, 'analysis'); eq(a.calls[0].model, 'x')
    const p = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, stage: 'analysis', models: { planners: 'y' } } })
    eq(p.calls[0].model, 'y')
  }],
  ['te: plan-team explicit stage plan, or any other stage value, analyses first and returns stage plan', 'plan-team', { profile: profileWith({}), exec: { ...PT, stage: 'plan' } }, async (r) => {
    eq(r.labels.join(','), 'analysis,pm,architect'); eq(r.result.status, 'accepted'); eq(r.result.stage, 'plan'); eq(r.result.next_stage, null)
    const o = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, stage: 'build' } })
    eq(o.labels.join(','), 'analysis,pm,architect'); eq(o.result.status, 'accepted'); eq(o.result.stage, 'plan')
  }],
  ['te: plan-team exec.state that is not an object is ignored and the analysis runs', 'plan-team', { profile: profileWith({}), exec: { ...PT, state: 'garbage' } }, (r) => {
    eq(r.labels.join(','), 'analysis,pm,architect'); eq(r.result.status, 'accepted'); eq(r.result.agents.n, 3)
  }],
  ['te: plan-team design mode with no state reads, then studies on the reading, then stops', 'plan-team', { profile: profileWith({}), exec: { ...PT, mode: 'design' }, designDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.labels.join(','), 'analysis,design-study'); eq(r.result.decision_request.question, 'Design decisions')
    eq(r.result.state.analysis.request, 'do x'); eq(r.result.analysis.request, 'do x'); eq(r.result.stage, 'plan'); eq(r.result.next_stage, null)
    eq(Object.keys(r.result.decision_request.context).sort().join(','), 'alternatives,decisions,proposed_model')
    const p = promptOf(r, 'design-study')
    contains(p, 'DESIGN STUDY.'); contains(p, 'read today: a.js calls b.js'); contains(p, 'Build on the analysis above'); matches(p, /under risks/)
    eq(r.result.state.agents.n, 2)
  }],
  ['te: plan-team needs-human returns count agents across launches', 'plan-team', { profile: profileWith({}), exec: { ...PT, state: { analysis: A, agents: { n: 4 } } }, pmDecides: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.agents.n, 5); eq(r.result.agents.this_stage, 1); eq(r.result.state.agents.n, 5)
    const again = await runScenario(wf('plan-team'), { profile: profileWith({}), exec: { ...PT, state: r.result.state, decisions: 'use a', proceed: true }, pmDecides: true })
    eq(again.result.status, 'accepted'); eq(again.labels.join(','), 'pm,architect'); eq(again.result.agents.n, 7); deepEq(again.result.analysis, A)
  }],
  ['te: plan-team string launch whose analysis returns nothing stops, no throw', 'plan-team', { rawArgs: 'add a thing', exec: {}, noAnalysis: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Analysis'); eq(r.labels.join(','), 'profile,analysis')
    eq(r.result.stopped_for_decisions, false); eq(r.result.spec, null); eq(r.result.plan, null)
  }],

  // ---- review cost: resume, routing, merge, docs audit, lead files ------------------------
  ['[resume] a relaunched review judges the findings left open, without their old verdicts', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend'], { unresolved: OPEN }) }), reviews: () => [] }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.state.reviewClean, true); deepEq(r.result.state.unresolved, [])
    eq(refuterLabels(r).sort().join(','), 'verify:a.py,verify:b.py')
    for (const p of refuterPrompts(r)) { lacks(p, 'OLD-'); lacks(p, '"recheck_reason"'); lacks(p, '"fixed"') }
    contains(refuterPrompts(r).join('\n'), 'open one'); contains(refuterPrompts(r).join('\n'), 'open two')
    const fix = promptOf(r, 'fix r1:backend')
    contains(fix, 'open one'); contains(fix, 'open two'); lacks(fix, 'OLD-'); lacks(fix, '"recheck_reason"')
    eq(recheckLabels(r).length, 2)
  }],
  ['[resume] a finding left open and reported again at the same file and line is judged once', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend'], { unresolved: OPEN }) }), reviews: byLens({ correctness: [{ file: 'backend/a.py', line: 4, severity: 'medium', summary: 'reported again in other words', failure_scenario: 'g' }] }) }, (r) => {
    eq(r.result.status, 'stage-done')
    eq(refuterLabels(r).sort().join(','), 'verify:a.py,verify:b.py'); eq(recheckLabels(r).length, 2)
    const a = fixFindings(r).find((f) => f.file === 'backend/a.py')
    eq(a.summary, 'open one'); deepEq(a.also_reported, [{ lens: 'correctness', severity: 'medium', summary: 'reported again in other words', failure_scenario: 'g' }])
    eq(fixFindings(r).length, 2); eq(occurrences(promptOf(r, 'fix r1:backend'), '"failure_scenario": "g"'), 1)
  }],
  ['[resume] a review launch with no open findings and silent reviewers ends clean with no refuter', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend'], { unresolved: [] }) }), reviews: () => [] }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.state.reviewClean, true); notIncludes(r.types, 'refuter')
  }],
  ['[routing] an absolute path under a frontend path is fixed by frontend, whatever the order of exec.components', 'dev-team', { profile: profileWith({}), exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: '/home/dev/work/shop/frontend/src/App.tsx', line: 12, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) }, async (r) => {
    includes(r.labels, 'fix r1:frontend'); notIncludes(r.labels, 'fix r1:backend')
    const o = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ components: ['frontend', 'backend'], state: reviewState(['frontend', 'backend']) }), reviews: byLens({ correctness: [{ file: '/home/dev/work/shop/frontend/src/App.tsx', line: 12, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) })
    includes(o.labels, 'fix r1:frontend'); notIncludes(o.labels, 'fix r1:backend')
    const d = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: '/home/dev/work/shop/docs/design.md', line: 3, severity: 'low', summary: 's', failure_scenario: 'f' }] }) })
    includes(d.labels, 'fix r1:docs'); notIncludes(d.labels, 'fix r1:backend')
  }],
  ['[routing] the longest matching path wins; a path matching nothing goes to the first of exec.components', 'dev-team', { profile: SHORT, exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: '/home/dev/src/shop/web/src/a.ts', line: 2, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) }, async (r) => {
    includes(r.labels, 'fix r1:frontend'); notIncludes(r.labels, 'fix r1:backend')
    const short = await runScenario(wf('dev-team'), { profile: SHORT, exec: T2R({ components: ['frontend', 'backend'], state: reviewState(['frontend', 'backend']) }), reviews: byLens({ correctness: [{ file: '/home/dev/src/shop/src/b.py', line: 2, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) })
    includes(short.labels, 'fix r1:backend'); notIncludes(short.labels, 'fix r1:frontend')
    const none = (order) => runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ components: order, state: reviewState(order) }), reviews: byLens({ correctness: [{ file: '/opt/elsewhere/z.py', line: 1, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) })
    const fb = await none(['frontend', 'backend']); includes(fb.labels, 'fix r1:frontend'); notIncludes(fb.labels, 'fix r1:backend')
    const bf = await none(['backend', 'frontend']); includes(bf.labels, 'fix r1:backend'); notIncludes(bf.labels, 'fix r1:frontend')
  }],
  ['[merge] two lenses on one file and line: one refutation, one fix item, one recheck, both summaries, highest severity', 'dev-team', { profile: profileWith({}), exec: T2R({ refute_votes_high: 3, state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'medium', summary: 'missing guard on the empty list', failure_scenario: 'f1' }], security: [{ file: 'backend/x.py', line: 7, severity: 'high', summary: 'unvalidated input reaches the query', failure_scenario: 'f2' }] }) }, async (r) => {
    eq(r.result.status, 'stage-done')
    eq(refuterLabels(r).join(','), 'verify:x.py v1,verify:x.py v2,verify:x.py v3')
    for (const p of refuterPrompts(r)) { contains(p, 'missing guard on the empty list'); contains(p, 'unvalidated input reaches the query') }
    const fix = promptOf(r, 'fix r1:backend')
    contains(fix, 'missing guard on the empty list'); contains(fix, 'unvalidated input reaches the query'); contains(fix, 'f1'); contains(fix, 'f2')
    eq(recheckLabels(r).join(','), 'recheck:x.py')
    const [f] = fixFindings(r)
    // The most severe copy leads, so the scenario the refuters and the recheck judge first is the one its severity comes from.
    eq(fixFindings(r).length, 1); eq(f.severity, 'high'); eq(f.lens, 'correctness, security'); eq(f.summary, 'unvalidated input reaches the query'); eq(f.failure_scenario, 'f2')
    deepEq(f.also_reported, [{ lens: 'correctness', severity: 'medium', summary: 'missing guard on the empty list', failure_scenario: 'f1' }])
    const low = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ refute_votes_high: 3, state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'medium', summary: 'a', failure_scenario: 'f1' }], 'stack:python': [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'b', failure_scenario: 'f2' }] }) })
    eq(refuterLabels(low).join(','), 'verify:x.py'); eq(fixFindings(low)[0].severity, 'medium'); eq(fixFindings(low)[0].lens, 'correctness, python')
    const single = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'medium', summary: 'a', failure_scenario: 'f1' }] }) })
    eq(Object.keys(fixFindings(single)[0]).includes('also_reported'), false)
  }],
  ['[merge] absolute and relative spellings merge; two lines stay apart; no-line findings keep the old rule', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'medium', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/home/dev/shop/backend/x.py', line: 7, severity: 'medium', summary: 'b', failure_scenario: 'f2' }] }) }, async (r) => {
    eq(refuterLabels(r).join(','), 'verify:x.py'); eq(fixFindings(r).length, 1); eq(fixFindings(r)[0].file, 'backend/x.py')
    const go = (table) => runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens(table) })
    const lines = await go({ correctness: [{ file: 'backend/x.py', line: 10, severity: 'medium', summary: 'a', failure_scenario: 'f' }], security: [{ file: 'backend/x.py', line: 11, severity: 'medium', summary: 'a', failure_scenario: 'f' }] })
    eq(refuterLabels(lines).length, 2); eq(fixFindings(lines).length, 2); eq(recheckLabels(lines).length, 2)
    const prefix = 'the handler never closes the session when'
    const same = await go({ correctness: [{ file: 'backend/x.py', severity: 'medium', summary: `${prefix} the request fails`, failure_scenario: 'f' }], security: [{ file: 'backend/x.py', severity: 'medium', summary: `${prefix} the client hangs up`, failure_scenario: 'f' }] })
    eq(refuterLabels(same).length, 1); eq(fixFindings(same)[0].summary, `${prefix} the request fails`)
    deepEq(fixFindings(same)[0].also_reported, [{ lens: 'security', severity: 'medium', summary: `${prefix} the client hangs up`, failure_scenario: 'f' }])
    const differ = await go({ correctness: [{ file: 'backend/x.py', severity: 'medium', summary: 'one thing', failure_scenario: 'f' }], security: [{ file: 'backend/x.py', severity: 'medium', summary: 'another thing', failure_scenario: 'f' }] })
    eq(refuterLabels(differ).length, 2)
    const spelled = await go({ correctness: [{ file: 'backend/x.py', severity: 'medium', summary: 'one thing', failure_scenario: 'f' }], security: [{ file: '/home/dev/shop/backend/x.py', severity: 'medium', summary: 'one thing', failure_scenario: 'f' }] })
    eq(refuterLabels(spelled).length, 2)
    // A short component path that also occurs in the directories above the repository.
    const twice = await runScenario(wf('dev-team'), { profile: SHORT, exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'src/b.py', line: 2, severity: 'medium', summary: 'a', failure_scenario: 'f' }], security: [{ file: '/home/dev/src/shop/src/b.py', line: 2, severity: 'medium', summary: 'b', failure_scenario: 'f' }] }) })
    eq(refuterLabels(twice).length, 1); eq(fixFindings(twice)[0].lens, 'correctness, security')
  }],
  ['[merge] review-team: each confirmed and each refuted finding once, with its lenses', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security'], components: ['backend'], plugin_root: '/plug' }, reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/home/dev/shop/backend/x.py', line: 7, severity: 'medium', summary: 'b', failure_scenario: 'f2' }] }) }, async (r) => {
    eq(r.result.status, 'not-ready'); eq(r.result.confirmed.length, 1); eq(r.result.refuted.length, 0); eq(refuterLabels(r).length, 1)
    const [c] = r.result.confirmed
    eq(c.lens, 'correctness, security'); eq(c.severity, 'medium'); eq(c.summary, 'b'); eq(c.file, 'backend/x.py'); deepEq(c.also_reported, [{ lens: 'correctness', severity: 'low', summary: 'a', failure_scenario: 'f1' }])
    const ref = await runScenario(wf('review-team'), { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security'], components: ['backend'], plugin_root: '/plug' }, refuteAll: true, reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'a', failure_scenario: 'f1' }], security: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'b', failure_scenario: 'f2' }] }) })
    eq(ref.result.status, 'accepted'); eq(ref.result.refuted.length, 1); eq(ref.result.confirmed.length, 0); eq(ref.result.refuted[0].lens, 'correctness, security')
  }],
  ['[merge] the path reduction and merge code is the same text in both scripts', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness'], components: ['backend'], plugin_root: '/plug' }, cleanReview: true }, () => {
    const d = sharedBlock('dev-team')
    eq(sharedBlock('review-team'), d); contains(d, 'const repoPath ='); contains(d, 'const mergeFindings =')
  }],
  ['[docs] an audit that returns nothing is reported as not audited, and QA still runs', 'dev-team', { profile: profileWith({}), exec: { ...T2, skip: ['pm', 'architect', 'consult', 'crosscheck'] }, cleanReview: true, auditNothing: true }, (r) => {
    eq(r.result.status, 'accepted'); includes(r.labels, 'docs:audit'); includes(r.labels, 'qa'); notIncludes(r.labels, 'docs:fix')
    eq(r.result.docs.audited, false); eq(r.result.summary.docs_audited, false); eq(r.result.state.docs.audited, false)
    const slice = r.result.commit_plan.find((s) => s.title.startsWith('docs:'))
    eq(slice.rationale, 'docs writer, not audited')
  }],
  ['[docs] an audit that returns a list, empty or not, is reported as audited', 'dev-team', { profile: profileWith({}), exec: { ...T2, skip: ['pm', 'architect', 'consult', 'crosscheck'] }, cleanReview: true, auditEmpty: true }, async (r) => {
    eq(r.result.status, 'accepted'); notIncludes(r.labels, 'docs:fix')
    eq(r.result.docs.audited, true); eq(r.result.summary.docs_audited, true)
    eq(r.result.commit_plan.find((s) => s.title.startsWith('docs:')).rationale, 'docs writer, audited')
    const fixed = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, skip: ['pm', 'architect', 'consult', 'crosscheck'] }, cleanReview: true })
    includes(fixed.labels, 'docs:fix'); eq(fixed.result.docs.audited, true); eq(fixed.result.summary.docs_audited, true)
    eq(fixed.result.commit_plan.find((s) => s.title.startsWith('docs:')).rationale, 'docs writer, audited')
  }],
  ['[scope] exec.lead_files are allowed in the build, review and finish stages and named to QA', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: LEAD }, changed: CHANGED }, async (r) => {
    eq(r.result.status, 'stage-done'); eq(r.labels.some((l) => l.includes('-scope')), false)
    contains(promptOf(r, 'verify:build'), "'.gitignore' 'docs/plans/'")
    const v = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'review', lead_files: LEAD, state: r.result.state }, changed: CHANGED })
    eq(v.result.status, 'stage-done'); includes(v.labels, 'verify:fix r1'); eq(v.labels.some((l) => l.includes('-scope')), false)
    const f = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'finish', lead_files: LEAD, state: v.result.state }, changed: CHANGED, teBugs: true })
    eq(f.result.status, 'accepted'); includes(f.labels, 'verify:tests'); eq(f.labels.some((l) => l.includes('-scope')), false)
    const qa = promptOf(f, 'qa')
    matches(qa, /Allowed paths for the scope gate: .*\.gitignore docs\/plans\//); contains(qa, 'the lead changed .gitignore docs/plans/ itself')
  }],
  ['[scope] without exec.lead_files the same files are out of scope in every stage', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build' }, changed: CHANGED }, async (r) => {
    includes(r.labels, 'verify:build-scope:backend'); includes(r.labels, 'verify:build-scope:docs')
    contains(promptOf(r, 'verify:build-scope:backend'), 'edited outside the allowed paths: .gitignore')
    const v = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'review', state: r.result.state }, changed: CHANGED })
    includes(v.labels, 'verify:fix r1-scope:backend')
    const f = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'finish', state: v.result.state }, changed: CHANGED, teBugs: true })
    includes(f.labels, 'verify:tests-scope:backend'); lacks(promptOf(f, 'qa'), '.gitignore'); lacks(promptOf(f, 'qa'), 'the lead changed')
  }],
  ['[scope] a file outside every allowed path and not in exec.lead_files is still sent back', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: LEAD }, changed: [...CHANGED, 'Makefile'] }, (r) => {
    includes(r.labels, 'verify:build-scope:backend'); notIncludes(r.labels, 'verify:build-scope:docs')
    const p = promptOf(r, 'verify:build-scope:backend')
    contains(p, 'edited outside the allowed paths: Makefile'); lacks(p, 'outside the allowed paths: .gitignore')
  }],
  // Challenger: the refuter's rule is "the finding stands only if the failure scenario is
  // reachable", and the recheck asks whether "the failure scenario is no longer reachable".
  // A merged finding takes the highest severity, so it must also show the scenario that
  // severity belongs to; otherwise a high copy is judged and rechecked on a lower copy's scenario.
  ['[merge] a merged finding shows the refuter, the fix and the recheck the scenario of every copy', 'dev-team', { profile: profileWith({}), exec: T2R({ refute_votes_high: 3, state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'naming is unclear', failure_scenario: 'LOW-SCENARIO a reader misreads the name' }], security: [{ file: 'backend/x.py', line: 7, severity: 'high', summary: 'unvalidated input reaches the query', failure_scenario: 'HIGH-SCENARIO a crafted id drops the table', suggested_fix: 'HIGH-FIX bind the parameter' }] }) }, (r) => {
    eq(refuterLabels(r).join(','), 'verify:x.py v1,verify:x.py v2,verify:x.py v3')
    for (const p of refuterPrompts(r)) contains(p, 'HIGH-SCENARIO a crafted id drops the table')
    contains(promptOf(r, 'fix r1:backend'), 'HIGH-SCENARIO a crafted id drops the table')
    contains(promptOf(r, 'fix r1:backend'), 'HIGH-FIX bind the parameter')
    const recheck = r.calls.find((c) => c.label.startsWith('recheck:'))
    contains(recheck.prompt, 'HIGH-SCENARIO a crafted id drops the table')
  }],
  // Challenger: a lead that writes one file as a string must not have that file sent to a dev
  // as "edited outside the allowed paths ... Revert it": either it is taken as one path, or
  // the run stops before any dev is told to revert it.
  ['[scope] exec.lead_files written as one string never sends the lead\'s file to a dev to revert', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: '.gitignore' }, changed: ['backend/x.py', '.gitignore'] }, (r) => {
    eq(r.labels.some((l) => l.includes('-scope')), false)
  }],
  ['[scope] exec.lead_files as one string is one allowed path; a value that is not a path or a list of paths stops the launch', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: '.gitignore' }, changed: ['backend/x.py', '.gitignore', 'Makefile'] }, async (r) => {
    eq(r.result.status, 'stage-done'); contains(promptOf(r, 'verify:build'), "'.gitignore'")
    const p = promptOf(r, 'verify:build-scope:backend')
    contains(p, 'edited outside the allowed paths: Makefile'); lacks(p, 'outside the allowed paths: .gitignore')
    for (const bad of [42, { path: '.gitignore' }, ['.gitignore', 7]]) {
      const err = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: bad }, changed: ['backend/x.py'] }).then(() => null, (e) => e)
      if (!err) throw new Error(`expected exec.lead_files ${JSON.stringify(bad)} to stop the launch`)
      matches(err.message, /exec\.lead_files must be a path or a list of paths/)
    }
  }],
  ['[merge] the most severe copy leads wherever it was reported, and every other copy keeps its scenario and fix', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'a', failure_scenario: 'fa', suggested_fix: 'FIX-A' }], security: [{ file: '/home/dev/shop/backend/x.py', line: 7, severity: 'high', summary: 'b', failure_scenario: 'fb' }], 'stack:python': [{ file: 'backend/x.py', line: 7, severity: 'high', summary: 'c', failure_scenario: 'fc' }] }) }, (r) => {
    const [f] = fixFindings(r)
    eq(fixFindings(r).length, 1); eq(f.summary, 'b'); eq(f.severity, 'high'); eq(f.file, 'backend/x.py'); eq(f.lens, 'correctness, security, python')
    deepEq(f.also_reported, [
      { lens: 'correctness', severity: 'low', summary: 'a', failure_scenario: 'fa', suggested_fix: 'FIX-A' },
      { lens: 'python', severity: 'high', summary: 'c', failure_scenario: 'fc' },
    ])
    contains(promptOf(r, 'fix r1:backend'), 'FIX-A')
  }],
  // Reviewer: an exact file path in the profile (Dockerfile, README.md) is also the name of a
  // file inside a component; it must not take a component's file away from its dev.
  ['[routing] a component\'s Dockerfile or README.md goes to the component; the root ones go to devops and docs', 'dev-team', { profile: profileWith({}), exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: '/srv/shop/backend/Dockerfile', line: 3, severity: 'medium', summary: 's', failure_scenario: 'f' }], security: [{ file: '/srv/shop/frontend/README.md', line: 5, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) }, async (r) => {
    includes(r.labels, 'fix r1:backend'); includes(r.labels, 'fix r1:frontend'); notIncludes(r.labels, 'fix r1:devops'); notIncludes(r.labels, 'fix r1:docs')
    contains(promptOf(r, 'fix r1:backend'), '/srv/shop/backend/Dockerfile'); contains(promptOf(r, 'fix r1:frontend'), '/srv/shop/frontend/README.md')
    const root = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: '/srv/shop/Dockerfile', line: 3, severity: 'medium', summary: 's', failure_scenario: 'f' }], security: [{ file: '/srv/shop/README.md', line: 5, severity: 'medium', summary: 's', failure_scenario: 'f' }] }) })
    includes(root.labels, 'fix r1:devops'); includes(root.labels, 'fix r1:docs'); notIncludes(root.labels, 'fix r1:backend'); notIncludes(root.labels, 'fix r1:frontend')
  }],
  ['[merge] the root Dockerfile and a component\'s Dockerfile at the same line are two findings', 'dev-team', { profile: profileWith({}), exec: T2R({ components: ['backend', 'frontend'], state: reviewState(['backend', 'frontend']) }), reviews: byLens({ correctness: [{ file: 'Dockerfile', line: 3, severity: 'medium', summary: 'root image runs as root', failure_scenario: 'f1' }], security: [{ file: '/srv/shop/backend/Dockerfile', line: 3, severity: 'medium', summary: 'backend image pins no digest', failure_scenario: 'f2' }] }) }, (r) => {
    eq(refuterLabels(r).length, 2); eq(fixFindings(r).length, 2); eq(recheckLabels(r).length, 2)
    eq(fixFindings(r).some((f) => 'also_reported' in f), false)
    contains(promptOf(r, 'fix r1:devops'), 'root image runs as root'); lacks(promptOf(r, 'fix r1:devops'), 'backend image pins no digest')
    contains(promptOf(r, 'fix r1:backend'), 'backend image pins no digest'); lacks(promptOf(r, 'fix r1:backend'), 'root image runs as root')
  }],
  // Reviewer: where the cut is a guess, the merged finding must still name a file a reviewer
  // wrote, so the refuter, the fix and the recheck read the right one.
  ['[merge] a merged finding names a file a reviewer wrote: the relative spelling, else the leading copy\'s own', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: '/srv/shop/backend/backend/settings.py', line: 10, severity: 'medium', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/srv/shop/backend/backend/settings.py', line: 10, severity: 'high', summary: 'b', failure_scenario: 'f2' }] }) }, async (r) => {
    eq(refuterLabels(r).length, 1); eq(fixFindings(r).length, 1); includes(r.labels, 'fix r1:backend')
    const [f] = fixFindings(r)
    eq(f.file, '/srv/shop/backend/backend/settings.py'); eq(f.summary, 'b')
    deepEq(f.also_reported, [{ lens: 'correctness', severity: 'medium', summary: 'a', failure_scenario: 'f1' }])
    for (const p of refuterPrompts(r)) lacks(p, '"file": "backend/settings.py"')
    const mixed = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/srv/shop/backend/x.py', line: 7, severity: 'high', summary: 'b', failure_scenario: 'f2' }] }) })
    const [m] = fixFindings(mixed)
    eq(m.file, 'backend/x.py'); eq(m.summary, 'b')
    deepEq(m.also_reported, [{ lens: 'correctness', severity: 'low', summary: 'a', failure_scenario: 'f1' }])
    const led = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'high', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/srv/shop/backend/x.py', line: 7, severity: 'low', summary: 'b', failure_scenario: 'f2' }] }) })
    deepEq(fixFindings(led)[0].also_reported, [{ lens: 'security', severity: 'low', summary: 'b', failure_scenario: 'f2', file: '/srv/shop/backend/x.py' }])
  }],
  ['[merge] review-team routes nothing but shows the same merged file and locations', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security'], components: ['backend', 'frontend'], plugin_root: '/plug' }, reviews: byLens({ correctness: [{ file: 'Dockerfile', line: 3, severity: 'medium', summary: 'a', failure_scenario: 'f1' }, { file: '/srv/shop/backend/backend/settings.py', line: 10, severity: 'low', summary: 'c', failure_scenario: 'f3' }], security: [{ file: '/srv/shop/backend/Dockerfile', line: 3, severity: 'medium', summary: 'b', failure_scenario: 'f2' }, { file: '/srv/shop/backend/backend/settings.py', line: 10, severity: 'medium', summary: 'd', failure_scenario: 'f4' }] }) }, (r) => {
    eq(r.result.confirmed.length, 3); eq(refuterLabels(r).length, 3)
    deepEq(r.result.confirmed.map((c) => c.file).sort(), ['/srv/shop/backend/Dockerfile', '/srv/shop/backend/backend/settings.py', 'Dockerfile'])
    eq(r.result.confirmed.find((c) => c.summary === 'd').lens, 'correctness, security')
  }],

  // ---- test engineer: review cost, gaps the dev scenarios leave open -----------------------
  // The state a review stop actually leaves (fixed: false, recheck_reason) is the state the
  // lead relaunches with; the open findings must be judged again from it, without those fields.
  ['te: [resume] a review stopped with open findings, relaunched with its own state, judges them again', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/a.py', line: 4, severity: 'medium', summary: 'still open after the fix', failure_scenario: 'f1' }] }), notFixed: true }, async (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.state.unresolved.length, 1); eq(r.result.state.unresolved[0].fixed, false)
    const again = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: r.result.state }), reviews: () => [] })
    eq(again.result.status, 'stage-done'); eq(again.result.state.reviewClean, true); deepEq(again.result.state.unresolved, [])
    eq(refuterLabels(again).join(','), 'verify:a.py')
    const p = refuterPrompts(again)[0]
    contains(p, 'still open after the fix'); lacks(p, '"fixed"'); lacks(p, '"recheck_reason"'); lacks(p, '"verdict_reason"'); lacks(p, '"refuted"')
    includes(again.labels, 'fix r1:backend'); eq(recheckLabels(again).join(','), 'recheck:a.py')
  }],
  ['te: [resume] escalations and open findings are both judged in round 1, and one at the same line is judged once', 'dev-team', { profile: profileWith({}), exec: T2R({ refute_votes_high: 3, state: reviewState(['backend'], { unresolved: OPEN, escalated: [{ file: 'backend/a.py', line: 4, severity: 'high', summary: 'challenger escalation', failure_scenario: 'esc', lens: 'backend-challenge' }, { file: 'backend/c.py', line: 2, severity: 'medium', summary: 'other escalation', failure_scenario: 'esc2', lens: 'backend-challenge' }] }) }), reviews: () => [] }, (r) => {
    eq(r.result.status, 'stage-done'); deepEq(r.result.state.escalated, [])
    // a.py:4 is one defect (escalation high + open medium): three votes; b.py and c.py one each.
    eq(refuterLabels(r).sort().join(','), 'verify:a.py v1,verify:a.py v2,verify:a.py v3,verify:b.py,verify:c.py')
    const a = fixFindings(r).find((f) => f.file === 'backend/a.py')
    eq(fixFindings(r).length, 3); eq(a.severity, 'high'); eq(a.summary, 'challenger escalation'); eq(a.lens.split(', ').sort().join(', '), 'backend-challenge, correctness')
    deepEq(a.also_reported, [{ lens: 'correctness', severity: 'medium', summary: 'open one', failure_scenario: 'f1' }])
    eq(recheckLabels(r).length, 3)
  }],
  ['te: [resume] open findings the refuters now reject leave the review clean with no fix', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend'], { unresolved: OPEN }) }), reviews: () => [], refuteAll: true }, (r) => {
    eq(r.result.status, 'stage-done'); eq(r.result.state.reviewClean, true); deepEq(r.result.state.unresolved, [])
    eq(refuterLabels(r).length, 2); eq(r.labels.some((l) => l.startsWith('fix r')), false); eq(recheckLabels(r).length, 0)
  }],
  // An open finding that was already a merge keeps its lenses once and every copy when a lens
  // it already names reports it again.
  ['te: [resume] a merged open finding reported again keeps each lens once and every copy', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend'], { unresolved: [{ file: 'backend/x.py', line: 7, severity: 'medium', summary: 'first', failure_scenario: 'f1', lens: 'correctness, security', also_reported: [{ lens: 'security', severity: 'low', summary: 'second', failure_scenario: 'f2' }], refuted: false, verdict_reason: 'OLD-V', fixed: false, recheck_reason: 'OLD-R' }] }) }), reviews: byLens({ security: [{ file: '/srv/shop/backend/x.py', line: 7, severity: 'low', summary: 'third', failure_scenario: 'f3' }] }) }, (r) => {
    eq(refuterLabels(r).join(','), 'verify:x.py')
    const [f] = fixFindings(r)
    eq(fixFindings(r).length, 1); eq(f.lens, 'correctness, security'); eq(f.file, 'backend/x.py'); eq(f.summary, 'first')
    deepEq(f.also_reported, [{ lens: 'security', severity: 'low', summary: 'second', failure_scenario: 'f2' }, { lens: 'security', severity: 'low', summary: 'third', failure_scenario: 'f3', file: '/srv/shop/backend/x.py' }])
    lacks(promptOf(r, 'fix r1:backend'), 'OLD-')
  }],
  // Line 0 is "no line": the old rule (file and first 40 characters of the summary) applies.
  ['te: [merge] line 0 is treated as no line', 'dev-team', { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 0, severity: 'medium', summary: 'one thing', failure_scenario: 'f' }], security: [{ file: 'backend/x.py', line: 0, severity: 'medium', summary: 'another thing', failure_scenario: 'f' }] }) }, async (r) => {
    eq(refuterLabels(r).length, 2); eq(fixFindings(r).length, 2)
    const same = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: T2R({ state: reviewState(['backend']) }), reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 0, severity: 'medium', summary: 'one thing', failure_scenario: 'f' }], security: [{ file: 'backend/x.py', severity: 'medium', summary: 'one thing', failure_scenario: 'g' }] }) })
    eq(refuterLabels(same).length, 1); eq(fixFindings(same)[0].lens, 'correctness, security')
  }],
  ['te: [merge] review-team gives a merged finding with a high copy refute_votes_high votes', 'review-team', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security'], components: ['backend'], refute_votes_high: 3, plugin_root: '/plug' }, reviews: byLens({ correctness: [{ file: 'backend/x.py', line: 7, severity: 'low', summary: 'a', failure_scenario: 'f1' }], security: [{ file: '/srv/shop/backend/x.py', line: 7, severity: 'high', summary: 'b', failure_scenario: 'f2' }] }) }, (r) => {
    eq(refuterLabels(r).join(','), 'verify:x.py v1,verify:x.py v2,verify:x.py v3')
    for (const p of refuterPrompts(r)) { contains(p, 'f1'); contains(p, 'f2') }
    eq(r.result.confirmed.length, 1); eq(r.result.confirmed[0].severity, 'high'); eq(r.result.confirmed[0].file, 'backend/x.py')
  }],
  // exec.lead_files is passed on every launch and never saved in state: a later launch without
  // it treats the same files as out of scope again.
  ['te: [scope] exec.lead_files is not saved in state: a later launch without it sends the files back', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: LEAD }, changed: CHANGED }, async (r) => {
    eq(r.result.status, 'stage-done'); eq(JSON.stringify(r.result.state).includes('lead_files'), false); eq(JSON.stringify(r.result.state).includes('.gitignore'), false)
    const v = await runScenario(wf('dev-team'), { profile: profileWith({}), exec: { ...T2, stage: 'review', state: r.result.state }, changed: CHANGED })
    includes(v.labels, 'verify:fix r1-scope:backend'); contains(promptOf(v, 'verify:fix r1-scope:backend'), 'edited outside the allowed paths: .gitignore')
  }],
  ['te: [scope] an empty exec.lead_files list behaves as if absent', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'build', lead_files: [] }, changed: CHANGED }, (r) => {
    eq(r.result.status, 'stage-done'); includes(r.labels, 'verify:build-scope:backend')
    contains(promptOf(r, 'verify:build-scope:backend'), 'edited outside the allowed paths: .gitignore')
  }],
  // No audit was due (docs skipped): docs_audited is neither true nor false.
  ['te: [docs] with no docs pass, the summary does not claim an audit either way', 'dev-team', { profile: profileWith({}), exec: T2, cleanReview: true }, (r) => {
    eq(r.result.status, 'accepted'); notIncludes(r.labels, 'docs:audit'); eq(r.result.summary.docs_audited, null)
    eq(r.result.commit_plan.some((s) => s.title.startsWith('docs:')), false)
  }],
  // A finish relaunch after an unaudited docs pass keeps reporting it as not audited.
  ['te: [docs] not audited survives in state for the lead to see', 'dev-team', { profile: profileWith({}), exec: { ...T2, stage: 'finish', skip: ['pm', 'architect', 'consult', 'crosscheck'], state: reviewState(['backend'], { reviewClean: true }) }, auditNothing: true }, (r) => {
    eq(r.result.status, 'accepted'); includes(r.labels, 'qa'); eq(r.result.state.docs.audited, false); eq(r.result.summary.docs_audited, false)
    eq(r.result.commit_plan.find((s) => s.title.startsWith('docs:')).rationale, 'docs writer, not audited')
  }],
]

function contains(text, needle) { if (!String(text).includes(needle)) throw new Error(`expected the text to contain ${JSON.stringify(needle)}`) }
function lacks(text, needle) { if (String(text).includes(needle)) throw new Error(`expected the text not to contain ${JSON.stringify(needle)}`) }
function matches(text, re) { if (!re.test(String(text))) throw new Error(`expected ${JSON.stringify(text)} to match ${re}`) }
// Deep equality with object keys compared in sorted order.
const canon = (v) => Array.isArray(v) ? v.map(canon) : (v && typeof v === 'object') ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, canon(v[k])])) : v
function deepEq(a, b) { const x = JSON.stringify(canon(a)); const y = JSON.stringify(canon(b)); if (x !== y) throw new Error(`expected ${y}, got ${x}`) }
function eq(a, b) { if (a !== b) throw new Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`) }
function includes(list, x) { if (!list.includes(x)) throw new Error(`expected ${JSON.stringify(list)} to include ${JSON.stringify(x)}`) }
function notIncludes(list, x) { if (list.includes(x)) throw new Error(`expected ${JSON.stringify(list)} not to include ${JSON.stringify(x)}`) }

let failed = 0
for (const [name, script, sc, check] of cases) {
  try {
    let r
    try { r = await runScenario(wf(script), sc) } catch (e) {
      if (name.includes('throws') && /task is required/.test(e.message)) { console.log(`ok   ${name}`); continue }
      throw e
    }
    await check(r)
    console.log(`ok   ${name}`)
  } catch (e) {
    failed++
    console.log(`FAIL ${name}: ${e.message}`)
  }
}
console.log(`${cases.length - failed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
