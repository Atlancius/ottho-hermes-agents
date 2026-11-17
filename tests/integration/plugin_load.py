"""Charge le plugin mail-agent avec le vrai Hermes d'une cellule et appelle register() avec un contexte espion.
  docker exec -u hermes -e HERMES_HOME=/opt/data <cellule> /opt/hermes/.venv/bin/python - <profil_home> < plugin_load.py
Vérifie que chaque module Hermes utilisé existe dans cette version, que la plateforme et les outils s'enregistrent,
et que la procédure de tri se construit avec le mail-agent.yaml du profil. N'ouvre aucune connexion.
"""
import importlib
import os
import sys
import types

home = sys.argv[1]
os.environ["HERMES_HOME"] = home
os.chdir("/opt/hermes") if os.path.isdir("/opt/hermes") else None
sys.path.insert(0, "/opt/hermes")

needed = {
    "gateway.platforms._shared": ["env_is_connected", "get_scoped_secret"],
    "gateway.config": ["Platform", "PlatformConfig"],
    "gateway.platforms.base": ["BasePlatformAdapter", "SendResult"],
    "gateway.platforms.event": ["MessageEvent", "MessageType", "ProcessingOutcome"],
    "gateway.platforms.helpers": ["cancel_task"],
    "gateway.session_context": ["get_session_env", "session_context_engaged"],
    "tools.registry": ["tool_error", "tool_result"],
    "hermes_constants": ["get_hermes_home"],
}
missing = []
for mod, names in needed.items():
    try:
        m = importlib.import_module(mod)
    except Exception as exc:
        missing.append(f"{mod} ({type(exc).__name__})")
        continue
    missing += [f"{mod}.{n}" for n in names if not hasattr(m, n)]
print("API Hermes manquante : " + (", ".join(missing) if missing else "aucune"))

pkg = types.ModuleType("mail_agent_probe")
pkg.__path__ = [os.path.join(home, "plugins", "mail-agent")]
sys.modules["mail_agent_probe"] = pkg
plugin = importlib.import_module("mail_agent_probe")
mod = importlib.import_module("mail_agent_probe.__init__") if False else plugin


class Ctx:
    platforms, tools = [], []

    def register_platform(self, **kw):
        self.platforms.append(kw["name"])

    def register_tool(self, **kw):
        self.tools.append(kw["name"])


init = importlib.util.spec_from_file_location("mail_agent_probe", os.path.join(home, "plugins", "mail-agent", "__init__.py"),
                                              submodule_search_locations=[os.path.join(home, "plugins", "mail-agent")])
module = importlib.util.module_from_spec(init)
sys.modules["mail_agent_probe"] = module
init.loader.exec_module(module)
ctx = Ctx()
module.register(ctx)
print("plateformes :", ctx.platforms)
print("outils :", len(ctx.tools), ", ".join(sorted(ctx.tools)))
settings = sys.modules["mail_agent_probe.settings"]
print("marques :", settings.brands(), "mode live :", settings.live())
print("procédure :", settings.mail_procedure().splitlines()[0])
