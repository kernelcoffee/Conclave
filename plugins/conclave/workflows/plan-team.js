// Conclave plan workflow: pm spec, then architect briefs, contracts and failure matrix.
// Writes nothing; stops when the pm or the architect has decisions only the user can make.
//
//   Workflow({ name: "conclave:plan-team",
//              args: { profile: <.claude/conclave.json as an object>,
//                      exec: { task, components?, base?, plugin_root, decisions?, proceed? } } })

export const meta = {
  name: 'plan-team',
  description: 'Spec a task with the Conclave pm, then plan it with the architect; no code is written',
  whenToUse: 'Launched by /conclave:plan, or directly with args.profile and args.exec, before a large change.',
  phases: [
    { title: 'Profile', detail: 'read .claude/conclave.json when it was not passed in' },
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

// ---- schemas ---------------------------------------------------------------
const strList = { type: 'array', items: { type: 'string' } }
const decisionOption = { anyOf: [{ type: 'string' }, { type: 'object', properties: { label: { type: 'string' }, consequence: { type: 'string' } }, required: ['label', 'consequence'] }] }
const DECISION = { type: 'object', properties: { question: { type: 'string' }, options: { type: 'array', items: decisionOption }, recommendation: { type: 'string' } }, required: ['question', 'options', 'recommendation'] }
const decisionList = { type: 'array', items: DECISION }
const DESIGN_STUDY = {
  type: 'object',
  properties: {
    current_state: { type: 'string' }, problems: strList, proposed_model: { type: 'string' },
    alternatives: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, summary: { type: 'string' }, pros: strList, cons: strList }, required: ['name', 'summary', 'pros', 'cons'] } },
    decisions: decisionList, migration: { type: 'string' }, risks: strList,
    diagrams: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, kind: { type: 'string' }, mermaid: { type: 'string' } }, required: ['title', 'mermaid'] } },
  },
  required: ['current_state', 'problems', 'proposed_model', 'alternatives', 'decisions', 'migration', 'risks'],
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

// ---- Design study (exec.mode === 'design') -----------------------------------
let designStudy = null
const designStudyPrompt = () =>
  `${context(components)}\n\n` +
  (exec.decisions ? `The user answered your earlier design questions; honour them and leave decisions empty unless something new comes up:\n${exec.decisions}\n\n` : '') +
  `DESIGN STUDY. Before anyone specifies or plans, establish the shape of the change: how it works today (with file references), the problems, the model you recommend, the alternatives you considered with their pros and cons, the decisions only the user can make (each option with its consequence, your recommendation first), how existing data and settings migrate, the risks, and one or two Mermaid diagrams (flowchart or sequenceDiagram, real module and endpoint names, at most twelve nodes) that show the current and the proposed model when more than two parts or a flow are involved. Argue the recommendation from the goal of the task, not from implementation convenience. Do not edit files.`
if (exec.mode === 'design') {
  phase('Plan')
  designStudy = await run('architect', designStudyPrompt(), { phase: 'Plan', schema: DESIGN_STUDY, label: 'design-study' })
  if (!designStudy) throw new Error('architect returned no design study')
  if (designStudy.decisions.length && !exec.proceed) {
    log(`design study has ${designStudy.decisions.length} open decision(s); stopping before the pm`)
    return { status: 'needs-human', phase: 'Plan', decision_request: { question: 'Design decisions', context: { decisions: designStudy.decisions, proposed_model: designStudy.proposed_model, alternatives: designStudy.alternatives } }, stopped_for_decisions: true, task, design_study: designStudy, spec: null, plan: null, agents: agentCount }
  }
}
const modelText = () => (designStudy ? `Chosen model (from the design study; spec against it, do not reopen it):\n${designStudy.proposed_model}\n\nMigration:\n${designStudy.migration}\n\n` : '')

// ---- Plan ------------------------------------------------------------------
phase('Plan')
const spec = await run('pm',
  `${context(components)}\n\n${modelText()}` +
  (exec.decisions ? `The user answered your earlier questions; honour them and leave needs_decision empty unless something new comes up:\n${exec.decisions}\n\n` : '') +
  `Write the product spec for this task: goals, non-goals, acceptance criteria the test engineer can turn into cases, the components touched (choose from: ${allNames}), whether the change is security sensitive, and the decisions only the user can make. Do not edit files.`,
  { phase: 'Plan', schema: SPEC, label: 'pm' })
if (!spec) throw new Error('pm returned nothing')
if (spec.needs_decision.length && !exec.proceed) {
  log(`pm has ${spec.needs_decision.length} open decision(s); stopping before the architect`)
  return { status: 'needs-human', phase: 'Plan', decision_request: { question: 'Decisions only the user can make', context: { needs_decision: spec.needs_decision } }, stopped_for_decisions: true, task, design_study: designStudy, spec, plan: null, agents: agentCount }
}
if (spec.components && spec.components.length) components = spec.components.filter((c) => byName[c])

const plan = await run('architect',
  `${context(components)}\n\n${modelText()}Product spec from the pm:\n${show(spec)}\n\n` +
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
  return { status: 'needs-human', phase: 'Plan', decision_request: { question: 'Decisions only the user can make', context: { needs_decision: plan.needs_decision } }, stopped_for_decisions: true, task, components: plan.components, design_study: designStudy, spec, plan, agents: agentCount }
}
return { status: 'accepted', task, components: plan.components, design_study: designStudy, spec, plan, stopped_for_decisions: false, agents: agentCount }
