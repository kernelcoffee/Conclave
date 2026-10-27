// Conclave review workflow: lenses over the working-tree diff, then a refuter per finding.
// No fixing; the result is a list of confirmed and refuted findings.
//
//   Workflow({ name: "conclave:review",
//              args: { profile: <.claude/conclave.json as an object>,
//                      exec: { base, lenses, components, refute_votes_high, plugin_root, task? } } })
//
// Lenses: correctness, security, conventions, stack (one reviewer-stack per distinct stack
// among the components), ux (only when a touched component has ui: true).

export const meta = {
  name: 'review',
  description: 'Review the working-tree diff with the Conclave lenses and refute every finding; changes nothing',
  whenToUse: 'Launched by /conclave:review, or directly with args.profile and args.exec, to check a diff before committing.',
  phases: [
    { title: 'Profile', detail: 'read .claude/conclave.json when it was not passed in' },
    { title: 'Review', detail: 'one reviewer per lens' },
    { title: 'Verify', detail: 'refuters per finding' },
  ],
}

// ---- args ------------------------------------------------------------------
const opt = (typeof args === 'object' && args) || {}
const exec = opt.exec || {}
const lenses = exec.lenses || ['correctness', 'security', 'stack']
const votesHigh = exec.refute_votes_high || 1
const pluginRoot = exec.plugin_root || ''
const task = exec.task || 'Review the uncommitted working-tree changes.'
const agentCount = { n: 0, byModel: {} }

// ---- schemas ---------------------------------------------------------------
const finding = {
  type: 'object',
  properties: {
    file: { type: 'string' }, line: { type: 'integer' },
    severity: { type: 'string', enum: ['high', 'medium', 'low'] },
    summary: { type: 'string' }, failure_scenario: { type: 'string' }, suggested_fix: { type: 'string' },
  },
  required: ['file', 'severity', 'summary', 'failure_scenario'],
}
const PROFILE = { type: 'object', properties: { profile: { type: 'object' }, error: { type: 'string' } }, required: ['profile'] }
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: finding } }, required: ['findings'] }
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['refuted', 'reason'] }

// ---- models and effort -----------------------------------------------------
const GROUP = {
  'reviewer-correctness': 'reviewers', 'reviewer-security': 'reviewers', 'reviewer-stack': 'reviewers', ux: 'reviewers',
  'reviewer-conventions': 'mechanical', profile: 'mechanical',
  refuter: 'refuter',
}
const DEFAULT_MODEL = { planners: 'inherit', workers: 'opus', reviewers: 'opus', mechanical: 'sonnet', refuter: 'opus' }
const DEFAULT_EFFORT = { planners: 'high', workers: 'high', reviewers: 'high', mechanical: 'medium', refuter: 'high' }
const LOW_EFFORT = new Set(['profile'])
let profile = opt.profile || null
const pick = (table, role) => {
  const g = GROUP[role] || 'reviewers'
  const sources = [exec.models || {}, (profile && profile.models) || {}]
  for (const s of sources) { if (s[role]) return s[role]; if (s[g]) return s[g] }
  return table[g]
}
const modelFor = (role) => { const m = pick(DEFAULT_MODEL, role); return m === 'inherit' ? undefined : m }
const effortFor = (role) => {
  const e = (exec.effort || {})[role] || (exec.effort || {})[GROUP[role]]
  if (e) return e
  return LOW_EFFORT.has(role) ? 'low' : DEFAULT_EFFORT[GROUP[role] || 'reviewers']
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
const dedupe = (items) => {
  const seen = new Set()
  return items.filter((f) => {
    const key = `${f.file}:${f.line || 0}:${(f.summary || '').slice(0, 40)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
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
const components = (exec.components || []).filter((c) => byName[c])
if (!components.length) for (const c of profile.components || []) components.push(c.name)

// ---- context block ---------------------------------------------------------
const packsFor = (names) => [...new Set(names.flatMap((n) => (byName[n] || {}).stacks || []))].map((s) => `conclave:stack-${s}`)
const context = (names) => {
  const comps = (names || []).map((n) => byName[n]).filter(Boolean)
  return `Project: ${profile.name}. ${profile.summary || ''}\nBase ref: ${base}\n` +
    `Stakes (severity high means): ${profile.stakes || 'breaks behaviour or loses data'}\n` +
    `Threat model: ${(profile.security || {}).threat_model || '(none stated)'}\n\n` +
    `Task:\n${task}\n\n` +
    (comps.length ? `Component(s) under review:\n${show(comps)}\n\nStack packs: load each with the Skill tool before you start: ${packsFor(names).join(', ') || '(none)'}\n\n` : '') +
    `Contract(s):\n(none)\n\nExpected failures:\n(none given)`
}

// ---- lenses ----------------------------------------------------------------
const stackSet = [...new Set(components.flatMap((c) => byName[c].stacks || []))]
const uiTouched = components.some((c) => byName[c].ui)
const lensRoles = []
for (const l of lenses) {
  if (l === 'stack') for (const s of stackSet) lensRoles.push({ role: 'reviewer-stack', stack: s })
  else if (l === 'ux') { if (uiTouched) lensRoles.push({ role: 'ux' }) }
  else lensRoles.push({ role: `reviewer-${l}` })
}
log(`review · ${components.join(', ')} · stacks ${stackSet.join(', ') || '(none)'} · lenses ${lensRoles.map((l) => l.stack ? `stack:${l.stack}` : l.role.replace('reviewer-', '')).join(', ')} · ${votesHigh} vote(s) on high`)

// ---- Review ----------------------------------------------------------------
phase('Review')
const reviewPrompt = (extra) =>
  `${context(components)}\n\n${extra || ''}Review the uncommitted working-tree changes: run \`git diff ${base}\` and \`git status\`, and read any untracked files that git status lists. Do not edit files.`
const raw = (await parallel(lensRoles.map((l) => () =>
  run(l.role, reviewPrompt(l.stack ? `Your lens is the ${l.stack} stack: load conclave:stack-${l.stack} with the Skill tool first and apply its review checklist. ` : ''), { phase: 'Review', schema: FINDINGS, label: `review:${l.stack ? `stack:${l.stack}` : l.role.replace('reviewer-', '')}` })
    .then((res) => (res ? res.findings.map((f) => ({ ...f, lens: l.stack || l.role.replace('reviewer-', '') })) : []))))).filter(Boolean).flat()
const fresh = dedupe(raw)
log(`review: ${raw.length} finding(s), ${fresh.length} after dedup`)

// ---- Verify ----------------------------------------------------------------
let confirmed = []
let refuted = []
if (fresh.length) {
  phase('Verify')
  const refutePrompt = (f) =>
    `A reviewer (${f.lens} lens) reported this finding on the uncommitted working-tree changes:\n${show(f)}\n\n${context(components)}\n\n` +
    `Try to refute it. Read the code at that location and the callers. The finding stands only if the failure scenario is reachable in practice through this change. ` +
    `Set refuted=true if it cannot happen, is already handled, or is outside what the change touched. Default to refuted=true if unsure. Do not edit files.`
  const judged = (await parallel(fresh.map((f) => async () => {
    const votes = f.severity === 'high' ? votesHigh : 1
    const verdicts = (await parallel(Array.from({ length: votes }, (_, i) => () =>
      run('refuter', refutePrompt(f), { phase: 'Verify', schema: VERDICT, label: `verify:${(f.file || '').split('/').pop()}${votes > 1 ? ` v${i + 1}` : ''}` })))).filter(Boolean)
    const refutedCount = verdicts.filter((v) => v.refuted).length
    const isRefuted = verdicts.length ? refutedCount * 2 > verdicts.length || (votes === 1 && refutedCount === 1) : true
    return { ...f, refuted: isRefuted, verdict_reason: verdicts.map((v) => v.reason).join(' | ') || 'refuter failed' }
  }))).filter(Boolean)
  confirmed = judged.filter((f) => !f.refuted)
  refuted = judged.filter((f) => f.refuted)
  log(`verify: ${confirmed.length}/${fresh.length} finding(s) survived refutation`)
}

log(`agents used: ${agentCount.n} (${Object.entries(agentCount.byModel).map(([m, n]) => `${m}×${n}`).join(', ')})`)
return { status: confirmed.length ? 'not-ready' : 'accepted', base, components, lenses: lensRoles.map((l) => l.stack ? `stack:${l.stack}` : l.role), confirmed, refuted, agents: agentCount }
