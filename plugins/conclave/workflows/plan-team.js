// Conclave plan workflow: architect analysis of the current state, then pm spec, then
// architect briefs, contracts and failure matrix. Writes nothing; stops when the pm or the
// architect has decisions only the user can make.
//
//   Workflow({ name: "conclave:plan-team",
//              args: { profile: <.claude/conclave.json as an object>,
//                      exec: { task, components?, base?, plugin_root, stage?, state?,
//                              mode?, decisions?, proceed? } } })
//
// exec.stage "analysis" runs only the analysis (a revision of exec.state.analysis when
// exec.decisions carries the user's correction) and returns stage-done with state for the
// plan launch. Any other stage is the plan: it runs the analysis first when
// exec.state.analysis is absent. Only analysis and agents are restored from exec.state.

export const meta = {
  name: 'plan-team',
  description: 'Analyse a task with the Conclave architect, spec it with the pm, then plan it with the architect; no code is written',
  whenToUse: 'Launched by /conclave:plan, or directly with args.profile and args.exec, before a large change; exec.stage "analysis" runs the analysis alone.',
  phases: [
    { title: 'Profile', detail: 'read .claude/conclave.json when it was not passed in' },
    { title: 'Analysis', detail: 'architect reads the current state before anyone specifies' },
    { title: 'Plan', detail: 'pm spec, then architect briefs, contracts and failure matrix' },
  ],
}

// ---- args ------------------------------------------------------------------
// A bare string (the raw workflow launcher passes the typed text) is the task; the
// Profile phase then loads .claude/conclave.json. The object form is { profile, exec }.
const opt = typeof args === 'string' ? { exec: { task: args } } : ((typeof args === 'object' && args) || {})
const exec = opt.exec || {}
if (!exec.task) throw new Error('a task is required: pass a string, or { profile, exec: { task } }')
const task = exec.task
const pluginRoot = exec.plugin_root || ''
const agentCount = { n: 0, byModel: {} }
const stage = exec.stage === 'analysis' ? 'analysis' : 'plan'
const prev = (exec.state && typeof exec.state === 'object') ? exec.state : {}
const agentsBefore = (prev.agents && prev.agents.n) || 0
let analysis = prev.analysis || null
const agentsTotal = () => ({ n: agentsBefore + agentCount.n, byModel: agentCount.byModel, this_stage: agentCount.n })
const snapshot = () => ({ analysis, agents: agentsTotal() })

// ---- schemas ---------------------------------------------------------------
const strList = { type: 'array', items: { type: 'string' } }
const decisionOption = { anyOf: [{ type: 'string' }, { type: 'object', properties: { label: { type: 'string' }, consequence: { type: 'string' } }, required: ['label', 'consequence'] }] }
const DECISION = { type: 'object', properties: { question: { type: 'string' }, options: { type: 'array', items: decisionOption }, recommendation: { type: 'string' } }, required: ['question', 'options', 'recommendation'] }
const decisionList = { type: 'array', items: DECISION }
const DESIGN_STUDY = {
  type: 'object',
  properties: {
    problems: strList, proposed_model: { type: 'string' },
    alternatives: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, summary: { type: 'string' }, pros: strList, cons: strList }, required: ['name', 'summary', 'pros', 'cons'] } },
    decisions: decisionList, migration: { type: 'string' }, risks: strList,
    diagrams: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, kind: { type: 'string' }, mermaid: { type: 'string' } }, required: ['title', 'mermaid'] } },
  },
  required: ['problems', 'proposed_model', 'alternatives', 'decisions', 'migration', 'risks'],
}
const ANALYSIS = {
  type: 'object',
  properties: {
    request: { type: 'string' }, current_state: { type: 'string' },
    constraints: strList, unknowns: strList, components: strList,
    diagrams: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, kind: { type: 'string' }, mermaid: { type: 'string' } }, required: ['title', 'mermaid'] } },
  },
  required: ['request', 'current_state', 'constraints', 'unknowns'],
}
const PROFILE = { type: 'object', properties: { profile: { type: 'object' }, error: { type: 'string' } }, required: ['profile'] }
const SPEC = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    goals: strList, non_goals: strList,
    acceptance: strList,
    components: strList,
    security_sensitive: { type: 'boolean' },
    needs_decision: decisionList,
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
    files: strList, risks: strList, assumptions: strList,
    diagrams: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, kind: { type: 'string' }, mermaid: { type: 'string' } }, required: ['title', 'mermaid'] } },
    security_sensitive: { type: 'boolean' },
    touches_infra: { type: 'boolean' },
    dev_specialities: strList,
    needs_decision: decisionList,
  },
  required: ['summary', 'components', 'briefs', 'contracts', 'expected_failures', 'specialists', 'needs_decision'],
}

// ---- models and effort -----------------------------------------------------
const GROUP = { pm: 'planners', architect: 'planners', profile: 'mechanical' }
const DEFAULT_MODEL = { planners: 'inherit', workers: 'opus', reviewers: 'opus', mechanical: 'sonnet', refuter: 'opus' }
const DEFAULT_EFFORT = { planners: 'high', workers: 'high', reviewers: 'high', mechanical: 'medium', refuter: 'high' }
const LOW_EFFORT = new Set(['profile'])
let profile = opt.profile || null
const pick = (table, role) => {
  const g = GROUP[role] || 'planners'
  const sources = [exec.models || {}, (profile && profile.models) || {}]
  for (const s of sources) { if (s[role]) return s[role]; if (s[g]) return s[g] }
  return table[g]
}
const modelFor = (role) => { const m = pick(DEFAULT_MODEL, role); return m === 'inherit' ? undefined : m }
const effortFor = (role) => {
  const e = (exec.effort || {})[role] || (exec.effort || {})[GROUP[role]]
  if (e) return e
  return LOW_EFFORT.has(role) ? 'low' : DEFAULT_EFFORT[GROUP[role] || 'planners']
}

// ---- helpers ---------------------------------------------------------------
const show = (obj) => JSON.stringify(obj, null, 2)
const count = (model) => { agentCount.n += 1; const k = model || 'inherit'; agentCount.byModel[k] = (agentCount.byModel[k] || 0) + 1 }
// An analysis may come back from the lead rewritten from the plan document: a list as one
// string, a missing field, or the whole reading as one string. Never throw on it, and
// insert strings raw so Mermaid text reaches the prompt verbatim. The optional components
// and diagrams are shown when present, so the reading reaches the next agents whole.
const asText = (v) => (v == null || v === '') ? '(none)' : typeof v === 'string' ? v : Array.isArray(v) ? (v.length ? v.map((x) => `- ${typeof x === 'string' ? x : show(x)}`).join('\n') : '(none)') : show(v)
const present = (v) => v != null && v !== '' && !(Array.isArray(v) && !v.length)
const diagramText = (d) => (d && typeof d === 'object' && !Array.isArray(d))
  ? `${asText(d.title)}${present(d.kind) ? ` (${asText(d.kind)})` : ''}:\n\`\`\`mermaid\n${asText(d.mermaid)}\n\`\`\``
  : asText(d)
const analysisBody = (a) => (a && typeof a === 'object' && !Array.isArray(a))
  ? `Request:\n${asText(a.request)}\n\nCurrent state:\n${asText(a.current_state)}\n\nConstraints:\n${asText(a.constraints)}\n\nUnknowns:\n${asText(a.unknowns)}` +
    (present(a.components) ? `\n\nComponents:\n${asText(a.components)}` : '') +
    (present(a.diagrams) ? `\n\nDiagrams:\n${Array.isArray(a.diagrams) ? a.diagrams.map(diagramText).join('\n\n') : asText(a.diagrams)}` : '')
  : asText(a)
const analysisText = () => (analysis ? `Analysis (the reading of the code this task rests on; work from it):\n${analysisBody(analysis)}\n\n` : '')
async function run(role, prompt, opts) {
  const model = modelFor(role)
  const options = { effort: effortFor(role), ...(model ? { model } : {}), ...opts }
  count(model)
  if (role === 'profile') return agent(prompt, options)
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

// ---- Profile ---------------------------------------------------------------
if (!profile) {
  phase('Profile')
  const r = await run('profile', 'Read the file .claude/conclave.json in the current project and return it unchanged as the `profile` field. If it does not exist or is not valid JSON, return an empty object as `profile` and say why in `error`. Do nothing else.', { phase: 'Profile', schema: PROFILE, label: 'profile' })
  if (!r || !r.profile || !r.profile.components) throw new Error(`no profile: ${(r && r.error) || 'run /conclave:init first'}`)
  profile = r.profile
}
const base = exec.base || profile.base || 'origin/main'
const byName = {}
for (const c of profile.components || []) byName[c.name] = c
let components = (exec.components || []).filter((c) => byName[c])
const allNames = (profile.components || []).map((c) => c.name).join(', ')

// ---- context block ---------------------------------------------------------
const packsFor = (names) => [...new Set(names.flatMap((n) => (byName[n] || {}).stacks || []))].map((s) => `conclave:stack-${s}`)
const context = (names) => {
  const comps = (names || []).map((n) => byName[n]).filter(Boolean)
  return `Project: ${profile.name}. ${profile.summary || ''}\nBase ref: ${base}\n` +
    `Stakes (severity high means): ${profile.stakes || 'breaks behaviour or loses data'}\n` +
    `Threat model: ${(profile.security || {}).threat_model || '(none stated)'}\n\n` +
    `Task:\n${task}\n\n` +
    (comps.length ? `Component(s) likely touched:\n${show(comps)}\n\nStack packs: load each with the Skill tool before you start: ${packsFor(names).join(', ') || '(none)'}\n\n` : `All components:\n${show(profile.components)}\n\n`) +
    `Contract pairs the profile declares: ${show(profile.contracts || [])}`
}

// The design study is never restored from exec.state: it re-runs on a resume.
let designStudy = null

// ---- Analysis: the reading of the current state, before anyone specifies -----------
// exec.stage "analysis" always runs it (a revision when exec.decisions carries the user's
// correction of exec.state.analysis); a plan launch runs it first when no analysis was
// passed in, without a stop before the pm. The checkpoint is the lead's.
const analysisPrompt = (previous) =>
  `${context(components)}\n\n` +
  (previous ? `Your previous analysis:\n${analysisBody(previous)}\n\nThe user corrected it. Re-read the code the correction points to and return the whole analysis again, revised:\n${exec.decisions}\n\n` : '') +
  `ANALYSIS. Before anyone specifies or plans, read the code this task touches and return the reading only: the request restated (what is asked and what is not), how it works today (each claim with a file reference), the constraints that bound a solution (each with where it is written), the unknowns (each with what would settle it; an empty list when nothing is open), the components the reading shows involved (choose from: ${allNames}), and one Mermaid diagram of the current state (flowchart or sequenceDiagram, real module and endpoint names, at most twelve nodes) when more than two parts or a flow are involved. Propose no model, brief or contract. Do not edit files.`
if (stage === 'analysis' || !analysis) {
  phase('Analysis')
  const previous = stage === 'analysis' && exec.decisions ? analysis : null
  const a = await run('architect', analysisPrompt(previous), { phase: 'Analysis', schema: ANALYSIS, label: 'analysis' })
  if (!a) {
    return { status: 'needs-human', stage, next_stage: stage === 'analysis' ? 'plan' : null, phase: 'Analysis', decision_request: { question: 'The architect returned no analysis; relaunch the analysis stage.', context: {} }, stopped_for_decisions: false, task, analysis, design_study: null, spec: null, plan: null, state: snapshot(), agents: agentsTotal() }
  }
  analysis = a
}
if (stage === 'analysis') {
  log(`analysis done; agents used: ${agentCount.n}`)
  return { status: 'stage-done', stage: 'analysis', next_stage: 'plan', task, analysis, design_study: null, spec: null, plan: null, stopped_for_decisions: false, state: snapshot(), agents: agentsTotal() }
}

// ---- Design study (exec.mode === 'design') -----------------------------------
const designStudyPrompt = () =>
  `${context(components)}\n\n${analysisText()}` +
  (exec.decisions ? `The user answered your earlier design questions; honour them and leave decisions empty unless something new comes up:\n${exec.decisions}\n\n` : '') +
  `DESIGN STUDY. Before anyone specifies or plans, propose the shape of the change.` +
  // The no-analysis branch cannot run here (an analysis always precedes the study in this
  // script); it stays byte-identical to dev-team.js, which reaches it through skip
  // ["analysis"]. tests/workflows.test.mjs enforces the identity.
  (analysis ? ' Build on the analysis above: do not restate the current state, and report under risks every place where the code contradicts it.' : ' No analysis precedes this study: read the code this change touches first, and give a file reference for every claim about how it works today.') +
  ` Return the problems, the model you recommend, the alternatives you considered with their pros and cons, the decisions only the user can make (each option with its consequence, your recommendation first), how existing data and settings migrate, the risks, and one Mermaid diagram of the proposed model (flowchart or sequenceDiagram, real module and endpoint names, at most twelve nodes) when more than two parts or a flow are involved. Argue the recommendation from the goal of the task, not from implementation convenience. Do not edit files.`
if (exec.mode === 'design') {
  phase('Plan')
  designStudy = await run('architect', designStudyPrompt(), { phase: 'Plan', schema: DESIGN_STUDY, label: 'design-study' })
  if (!designStudy) throw new Error('architect returned no design study')
  if (designStudy.decisions.length && !exec.proceed) {
    log(`design study has ${designStudy.decisions.length} open decision(s); stopping before the pm`)
    return { status: 'needs-human', stage, next_stage: null, phase: 'Plan', decision_request: { question: 'Design decisions', context: { decisions: designStudy.decisions, proposed_model: designStudy.proposed_model, alternatives: designStudy.alternatives } }, stopped_for_decisions: true, task, analysis, design_study: designStudy, spec: null, plan: null, state: snapshot(), agents: agentsTotal() }
  }
}
const modelText = () => (designStudy ? `Chosen model (from the design study; spec against it, do not reopen it):\n${designStudy.proposed_model}\n\nMigration:\n${designStudy.migration}\n\n` : '')

// ---- Plan ------------------------------------------------------------------
phase('Plan')
const spec = await run('pm',
  `${context(components)}\n\n${analysisText()}${modelText()}` +
  (exec.decisions ? `The user answered your earlier questions; honour them and leave needs_decision empty unless something new comes up:\n${exec.decisions}\n\n` : '') +
  `Write the product spec for this task: goals, non-goals, acceptance criteria the test engineer can turn into cases, the components touched (choose from: ${allNames}), whether the change is security sensitive, and the decisions only the user can make. Do not edit files.`,
  { phase: 'Plan', schema: SPEC, label: 'pm' })
if (!spec) throw new Error('pm returned nothing')
if (spec.needs_decision.length && !exec.proceed) {
  log(`pm has ${spec.needs_decision.length} open decision(s); stopping before the architect`)
  return { status: 'needs-human', stage, next_stage: null, phase: 'Plan', decision_request: { question: 'Decisions only the user can make', context: { needs_decision: spec.needs_decision } }, stopped_for_decisions: true, task, analysis, design_study: designStudy, spec, plan: null, state: snapshot(), agents: agentsTotal() }
}
if (spec.components && spec.components.length) components = spec.components.filter((c) => byName[c])

const plan = await run('architect',
  `${context(components)}\n\n${analysisText()}${modelText()}Product spec from the pm:\n${show(spec)}\n\n` +
  (designStudy ? `Design study:\n${show(designStudy)}\n\n` : '') +
  (exec.decisions ? `User decisions:\n${exec.decisions}\n\n` : '') +
  `Components available: ${allNames}.\n` +
  `Plan the change: one brief per touched component (Goal, Files, Steps, Tests to write, Docs to update, Acceptance), a contract for every declared pair whose both sides change, the expected-failure matrix, ad-hoc specialists if the fixed team lacks the knowledge, risks and assumptions. Work on the current branch (uncommitted work is context, not something to undo). Do not edit files.`,
  { phase: 'Plan', schema: PLAN, label: 'architect' })
if (!plan) throw new Error('architect returned nothing')
const stopped = Boolean(plan.needs_decision.length && !exec.proceed)
if (stopped) log(`architect has ${plan.needs_decision.length} open decision(s)`)

log(`agents used: ${agentCount.n} (${Object.entries(agentCount.byModel).map(([m, n]) => `${m}×${n}`).join(', ')})`)
if (stopped) {
  return { status: 'needs-human', stage, next_stage: null, phase: 'Plan', decision_request: { question: 'Decisions only the user can make', context: { needs_decision: plan.needs_decision } }, stopped_for_decisions: true, task, components: plan.components, analysis, design_study: designStudy, spec, plan, state: snapshot(), agents: agentsTotal() }
}
return { status: 'accepted', stage, next_stage: null, task, components: plan.components, analysis, design_study: designStudy, spec, plan, stopped_for_decisions: false, state: snapshot(), agents: agentsTotal() }
