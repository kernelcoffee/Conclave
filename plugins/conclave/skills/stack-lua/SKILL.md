---
name: stack-lua
description: Knowledge pack for Lua 5.1 to 5.5 code, including World of Warcraft addons: idioms, review checklist, testing, tooling, pitfalls. Loaded by Conclave devs, challengers, reviewers and the lead.
user-invocable: false
---
# Lua stack pack

Applies to plain Lua scripts and libraries, and to embedded Lua such as World of Warcraft
addons (Lua 5.1 with the WoW API, frames, events and saved variables).

The interpreter version decides what exists; check it before using a feature. 5.1 and
LuaJIT: `setfenv`/`getfenv`, `unpack`, no integers, no `goto`. 5.2: `_ENV` replaces
`setfenv`, `goto`, `table.unpack`. 5.3: integers and bitwise operators, `utf8`. 5.4:
`<const>` and `<close>` locals, generational GC. 5.5: explicit `global` declarations
(once a scope declares globals, undeclared names are an error) and read-only `for` loop
control variables. WoW addons stay on 5.1 whatever the current Lua is.

## Idioms

- Everything is `local` unless it is deliberately exported; one addon table per addon
  (`local ADDON, ns = ...`) holding state and functions, never a scattering of globals.
- Tables reused rather than re-created in hot paths (event handlers, `OnUpdate`), with
  `wipe()` to clear; string concatenation in loops replaced by `table.concat`.
- Event handling: one frame registered for the events it needs, a dispatch table mapping
  event names to handlers, `UnregisterEvent` when the state no longer needs it; `OnUpdate`
  throttled with an accumulator, never running work every frame.
- Saved variables declared in the TOC, initialised with defaults on `ADDON_LOADED` for the
  addon's own name, versioned so migrations can run.
- Secure or protected calls (combat lockdown) respected: `InCombatLockdown()` checked
  before touching protected frames; actions queued for `PLAYER_REGEN_ENABLED`.
- Errors surfaced through `error()` with a level or through the addon's own reporting,
  not swallowed with `pcall` and ignored.
- Metatables for classes kept simple (`setmetatable({}, {__index = Class})`); `self`
  passed with `:`.

## Review checklist

- A global leaked by a missing `local` (luacheck flags it); a global name shadowing a WoW
  API or a library.
- A table allocated per call in an `OnUpdate` or a frequent event handler; string
  concatenation in a loop.
- `OnUpdate` without throttling; an event registered and never unregistered; a handler
  that does work for every unit when it only needed one.
- Protected frame manipulation during combat; `UIParent` taint from unsecure code paths.
- Saved variables accessed before `ADDON_LOADED`; defaults not applied for a fresh profile;
  a schema change without a migration.
- `pcall` results ignored; `error` messages without context.
- Off-by-one on 1-based indices; `#t` on a table with holes; `ipairs` stopping early at a
  `nil`.
- Numeric comparisons on strings from the API; missing `tonumber`.
- Library duplication: a helper already in LibStub libraries or the addon's own utils.

## Testing

- busted (`describe`/`it`/`assert`) for pure logic, run with `busted spec/`; the WoW API
  stubbed through a loader that defines the globals the module reads (frames, events,
  `C_Timer`, saved variables) in `spec/helpers.lua` or a WoW API mock library.
- Keep logic separate from frames so the logic is testable without a client; frame
  handlers call into pure functions.
- Assert on outcomes: the table state, the returned value, the message queued; not on
  a stub being called.
- For addons with no test harness, a smoke run in the client with `/console scriptErrors 1`
  and the BugGrabber/BugSack addons installed, and the steps recorded in the report.

## Tooling

- `luacheck .` with a `.luacheckrc` that declares the WoW globals the addon reads and the
  globals it defines (`globals`/`read_globals`), `std = "lua51"` for WoW.
- `stylua` or `lua-format` if the project uses one; never reformat untouched files.
- TOC file: `## Interface` matches the targeted client version; `## SavedVariables` lists
  every persisted global; file order in the TOC matches load dependencies.
- Packaging through the BigWigs packager or a release script that bumps the version in the
  TOC and tags.

## Pitfalls

- An addon that works in one locale and breaks in another because it parses localised
  strings instead of using API values.
- A handler that assumes the unit exists (`UnitName("target")` returns nil).
- Frame names colliding with other addons; prefix every global frame name.
- Load order: a file using a function defined in a later TOC entry.
- Interface version left stale, so the client marks the addon out of date.
