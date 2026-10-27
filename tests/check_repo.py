#!/usr/bin/env python3
"""Repository consistency checks.

    python3 -I tests/check_repo.py [--base <git-ref>]

- every JSON file parses;
- the profile template validates against the profile schema (needs `jsonschema`);
- every stack listed in the schema enum has a skills/stack-<name>/SKILL.md, and back;
- plugin.json and marketplace.json carry the same version;
- with --base: if anything under plugins/ changed since <ref>, the version changed too,
  because installs from git are cached by version and `claude plugin update` does
  nothing for an unchanged version.
Exit 1 on any failure.
"""
import json
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
