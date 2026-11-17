"""Applique les réglages d'un agent Ottho à un config.yaml Hermes. Exécuté DANS la cible par le Python de Hermes :
  <python de hermes> - '<spec json>' < profile_apply.py
(copie identique dans chaque plugin, source : shared/kit/lib/profile_apply.py)

Fusion (le reste du fichier est conservé) :
- modèle (provider, default) si fourni ;
- garde-fous non négociables : approvals smart, cron/single_query/unattended en deny, liste deny commune,
  politique smart de l'agent, masquage des secrets ;
- toolsets désactivés et toolsets par plateforme de l'agent ;
- plugins activés, plateformes activées ;
- hook pre_tool_call de périmètre (fail_closed) et sa liste d'autorisation, si fourni.
Écriture atomique (600). La sauvegarde horodatée est faite côté hôte avant l'appel.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import yaml

spec = json.loads(sys.argv[1])
home = os.path.join(spec["hermes_home"], "profiles", spec["profile"])
path = os.path.join(home, "config.yaml")
if not os.path.isdir(home):
    sys.exit(f"profil absent : {home}")

cfg = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}


def section(name, parent=None):
    parent = cfg if parent is None else parent
    val = parent.get(name)
    if not isinstance(val, dict):
        val = {}
        parent[name] = val
    return val


model = spec.get("model") or {}
if model.get("provider") and model.get("model"):
    m = section("model")
    m["provider"] = model["provider"]
    m["default"] = model["model"]

agent = section("agent")
for key in ("max_turns", "reasoning_effort"):
    if spec.get(key) is not None:
        agent[key] = spec[key]
disabled = [t for t in (agent.get("disabled_toolsets") or []) if isinstance(t, str)]
for t in spec.get("disabled_toolsets", []):
    if t not in disabled:
        disabled.append(t)
agent["disabled_toolsets"] = disabled

ap = section("approvals")
ap["mode"] = "smart"
ap["cron_mode"] = "deny"
ap["single_query_mode"] = "deny"
ap["unattended_mode"] = "deny"
ap.setdefault("timeout", 300)
ap.setdefault("denial_breaker_threshold", 3)
if spec.get("smart_policy"):
    ap["smart_policy"] = spec["smart_policy"]
deny = [d for d in (ap.get("deny") or []) if isinstance(d, str)]
for d in spec.get("deny", []):
    if d not in deny:
        deny.append(d)
ap["deny"] = deny

section("security")["redact_secrets"] = True
if spec.get("timezone"):
    cfg["timezone"] = spec["timezone"]

plugins = section("plugins")
enabled = [p for p in (plugins.get("enabled") or []) if isinstance(p, str)]
for p in spec.get("plugins", []):
    if p not in enabled:
        enabled.append(p)
plugins["enabled"] = enabled
plugins.setdefault("disabled", [])

if spec.get("platform_toolsets"):
    pt = section("platform_toolsets")
    for platform, toolsets in spec["platform_toolsets"].items():
        pt[platform] = list(toolsets)
for platform in spec.get("platforms", []):
    section(platform, section("platforms"))["enabled"] = True

hook_cmd = spec.get("hook_command")
if hook_cmd:
    hooks = section("hooks")
    pre = [h for h in (hooks.get("pre_tool_call") or []) if isinstance(h, dict) and h.get("command") != hook_cmd]
    pre.insert(0, {"command": hook_cmd, "matcher": spec.get("hook_matcher") or "^(write_file|patch|terminal|execute_code|process_manage)$",
                   "timeout": 15, "fail_closed": True})
    hooks["pre_tool_call"] = pre
    script = hook_cmd.split()[-1]
    mtime = datetime.fromtimestamp(os.stat(script).st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    allow_path = os.path.join(home, "shell-hooks-allowlist.json")
    allow = {"approvals": []}
    if os.path.exists(allow_path):
        with open(allow_path, encoding="utf-8") as fh:
            allow = json.load(fh) or {"approvals": []}
    approvals = [a for a in allow.get("approvals", [])
                 if not (a.get("command") == hook_cmd and a.get("event") == "pre_tool_call")]
    approvals.append({"approved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                      "command": hook_cmd, "event": "pre_tool_call", "script_mtime_at_approval": mtime})
    allow["approvals"] = approvals
    fd, tmp = tempfile.mkstemp(dir=home, prefix=".allow.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(allow, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, allow_path)

fd, tmp = tempfile.mkstemp(dir=home, prefix=".config.")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print(f"ok {path}")
