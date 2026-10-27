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

// The fake agent: answers each call by its label, with knobs per scenario.
function fakeAgent(sc, calls) {
  const st = { chal: {}, probes: 0, qa: 0 }
  return async (prompt, opts = {}) => {
    calls.push({ label: opts.label || '', type: (opts.agentType || 'plain').replace('conclave:', ''), model: opts.model || 'inherit' })
    const l = opts.label || ''
    const comps = sc.exec.components || ['backend']
    if (!opts.schema) return 'guidance'
    if (l === 'profile') return { profile: template }
    if (l === 'pm') return { summary: 's', goals: ['g'], acceptance: ['a'], components: comps, security_sensitive: false, needs_decision: sc.pmDecides ? [{ question: 'q', options: ['a', 'b'], recommendation: 'a' }] : [], assumptions: [] }
    if (l === 'architect') return { summary: 'p', components: comps, briefs: comps.map((c) => ({ component: c, brief: `brief ${c}` })), contracts: comps.length > 1 ? [{ between: ['backend', 'frontend'], text: 'GET /x' }] : [], expected_failures: ['a | b | c'], specialists: [], dev_specialities: ['data', 'concurrency'], needs_decision: [], security_sensitive: false, touches_infra: false }
    if (l.startsWith('design:') && l !== 'design:judge') return { approach: 'a', steps: ['s'], files: ['f'], risks: [], expected_tests: [], unsure: [] }
    if (l.startsWith('critique:')) return { verdict: sc.undecidable ? 'adopt_mine' : (l.endsWith('A') ? 'adopt_mine' : 'adopt_theirs'), objections: [], plan: 'plan A' }
    if (l === 'design:judge') return { winner: sc.undecidable ? 'undecidable' : 'A', plan: 'p', reasoning: 'r', decision_needed: 'which storage?' }
    if (l.startsWith('contract:try')) return { cases: ['c'], tests_added: ['t1'], test_files: ['backend/tests/test_c.py'], contract_tests: [{ file: 'backend/tests/test_c.py', name: 't1', criterion: 'a', behaviour: 'failure', expected_failure: 'assert 400' }], could_not_reproduce: false, bugs: [], untestable: [], checks_passed: false }
    if (l.startsWith('contract:audit')) return { valid: true, per_test: [{ file: 'backend/tests/test_c.py', name: 't1', fails_as_declared: true, actual_failure: 'assert 400', can_fail: true, note: '' }], other_tests_pass: true, runs: [] }
    if (l === 'contract:freeze' || l === 'probes:refreeze') return { runs: [{ command: 'freeze', exit_code: 0, output_tail: 'abc  backend/tests/test_c.py' }], all_passed: true }
    if (l.startsWith('verify:') && /verify:(build|challenge|fix|tests)/.test(l)) {
      const scopeFail = sc.scopeFails && l === 'verify:build'
      const frozenFail = sc.frozenFails && l === 'verify:build'
      return { runs: [{ command: 'scope', exit_code: scopeFail ? 1 : 0, output_tail: scopeFail ? 'out of scope: docs/x.md\nout of scope: frontend/y.ts' : '' }, { command: 'frozen', exit_code: frozenFail ? 1 : 0, output_tail: '' }], all_passed: !scopeFail && !frozenFail }
    }
    if (l.startsWith('xcheck')) return { mismatches: [] }
    if (l.startsWith('challenge')) { const c = l.split(' ')[0]; st.chal[c] = (st.chal[c] || 0) + 1; return st.chal[c] === 1 ? { challenges: [{ file: 'backend/x.py', severity: 'high', summary: 'c1', why_it_matters: 'w', demand: 'd' }] } : { challenges: [], escalations: [] } }
    if (l.startsWith('review:')) return l.includes('correctness') && (l.endsWith('r1') || !/ r\d$/.test(l)) && !sc.cleanReview ? { findings: [{ file: 'backend/x.py', line: 1, severity: 'high', summary: 'bug', failure_scenario: 'f' }] } : { findings: [] }
    if (l.startsWith('verify')) return { refuted: Boolean(sc.refuteAll), reason: 'r' }
    if (l.startsWith('recheck')) return { fixed: !sc.notFixed, reason: 'ok' }
    if (l === 'probes' || l === 'probes:again') {
      st.probes++
      if (sc.probeEscalate) return { probes: [], tree_restored: true, verdict: 'escalate', rejection: 'test t1 is wrong', runs: [] }
      return { probes: [{ file: 'backend/tests/test_c.py', name: 't1', mutation: 'invert guard', test_failed: st.probes > 1 }], tree_restored: true, verdict: st.probes > 1 ? 'pass' : 'reject', rejection: st.probes > 1 ? '' : 'survived', runs: [] }
    }
    if (l === 'probes:repair') return { cases: [], tests_added: ['t1'], test_files: ['backend/tests/test_c.py'], bugs: [], checks_passed: true }
    if (l === 'test-engineer') return { cases: ['c'], tests_added: ['t2'], test_files: ['backend/tests/test_d.py'], bugs: [], untestable: [], checks_passed: true }
    if (l === 'docs') return { summary: 'd', files_changed: ['docs/a.md'] }
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
  const result = await load(file)({ profile: sc.profile, exec: sc.exec }, fakeAgent(sc, calls), parallel, async () => [], (t) => phases.push(t), () => {}, { total: null })
  return { result, calls, phases: [...new Set(phases)], types: calls.map((c) => c.type) }
}

const T2 = { tier: 2, task: 'small', brief: 'Goal', components: ['backend'], rounds: 1, lenses: ['correctness', 'security', 'stack'], skip: ['pm', 'architect', 'consult', 'crosscheck', 'docs'], plugin_root: '/plug' }
const T3 = { tier: 3, task: 'feature', components: ['backend', 'frontend'], rounds: 2, lenses: ['correctness', 'security', 'stack', 'conventions', 'ux'], refute_votes_high: 3, plugin_root: '/plug' }

const cases = [
  ['dev-team T2 accepted', 'dev-team', { profile: profileWith({}), exec: T2 }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.result.ready_to_commit, true)
    notIncludes(r.types, 'pm'); notIncludes(r.phases, 'Plan'); includes(r.types, 'verifier')
    includes(r.result.commit_plan.map((s) => s.title), 'feat(backend): x')
  }],
  ['dev-team T3 with every option', 'dev-team', { profile: profileWith({ mutation_probes: true }), exec: { ...T3, contract: true, design: 'duel' } }, (r) => {
    eq(r.result.status, 'accepted')
    for (const p of ['Plan', 'Design', 'Contract', 'Build', 'Cross-check', 'Challenge', 'Review', 'Verify', 'Fix', 'Probes', 'Tests', 'Docs', 'QA']) includes(r.phases, p)
    eq(r.result.design.winner, 'A'); eq(r.result.probes.verdict, 'pass')
    eq(r.result.commit_plan[0].title.startsWith('test: add contract tests'), true)
    includes(r.types, 'test-auditor')
  }],
  ['dev-team no profile reads it', 'dev-team', { exec: T2 }, (r) => { eq(r.phases[0], 'Profile'); eq(r.result.status, 'accepted') }],
  ['dev-team pm decisions stop', 'dev-team', { profile: profileWith({}), exec: T3, pmDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.result.phase, 'Plan'); eq(r.calls.length, 1)
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
  ['review clean', 'review', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness', 'security', 'stack'], components: ['backend'], plugin_root: '/plug' }, cleanReview: true }, (r) => {
    eq(r.result.status, 'accepted'); notIncludes(r.types, 'refuter')
  }],
  ['review with a confirmed finding', 'review', { profile: profileWith({}), exec: { base: 'origin/main', lenses: ['correctness'], components: ['backend'], plugin_root: '/plug' } }, (r) => {
    eq(r.result.status, 'not-ready'); eq(r.result.confirmed.length, 1); includes(r.types, 'refuter')
  }],
  ['plan accepted', 'plan', { profile: profileWith({}), exec: { task: 'x', components: ['backend'], plugin_root: '/plug' } }, (r) => {
    eq(r.result.status, 'accepted'); eq(r.types.join(','), 'pm,architect')
  }],
  ['plan stops on decisions', 'plan', { profile: profileWith({}), exec: { task: 'x', components: ['backend'], plugin_root: '/plug' }, pmDecides: true }, (r) => {
    eq(r.result.status, 'needs-human'); eq(r.types.join(','), 'pm')
  }],
]

function eq(a, b) { if (a !== b) throw new Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`) }
function includes(list, x) { if (!list.includes(x)) throw new Error(`expected ${JSON.stringify(list)} to include ${JSON.stringify(x)}`) }
function notIncludes(list, x) { if (list.includes(x)) throw new Error(`expected ${JSON.stringify(list)} not to include ${JSON.stringify(x)}`) }

let failed = 0
for (const [name, script, sc, check] of cases) {
  try {
    check(await runScenario(wf(script), sc))
    console.log(`ok   ${name}`)
  } catch (e) {
    failed++
    console.log(`FAIL ${name}: ${e.message}`)
  }
}
console.log(`${cases.length - failed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
