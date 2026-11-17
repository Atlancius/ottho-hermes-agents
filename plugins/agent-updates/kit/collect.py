#!/usr/bin/env python3
"""Collecte des mises à jour du VPS (root, sur l'hôte, bibliothèque standard seule).

Instantané STABLE : aucun horodatage, aucun compteur qui bouge seul ; mêmes versions = même texte, donc aucun appel
au modèle. N'affiche aucun secret. Seule action qui écrit : `apt-get update` (cache des listes de paquets, désactivable
avec "apt_refresh": "non" dans /etc/ottho-agents/updates.json).
  python3 collect.py /etc/ottho-agents/updates.json
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

CONF = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else {}


def run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"(indisponible : {' '.join(cmd[:2])}, {type(exc).__name__})"
    return p.returncode, p.stdout


def section(title):
    print(f"\n## {title}")


def capped(rows, limit=40):
    """Liste bornée : l'agent reçoit l'essentiel sans des centaines de lignes (le total est dans le titre)."""
    if not rows:
        return "aucune"
    extra = len(rows) - limit
    return "\n".join(rows[:limit]) + (f"\n… et {extra} autres (liste complète : apt list --upgradable)" if extra > 0 else "")


def os_release():
    info = {}
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            info[k] = v.strip('"')
    except OSError:
        pass
    return info


def apt_part():
    if not shutil.which("apt-get"):
        section("Paquets système")
        print("gestionnaire apt absent : collecte des paquets non prise en charge sur ce système")
        return
    if str(CONF.get("apt_refresh", "oui")).lower() != "non":
        run(["apt-get", "update", "-qq"], timeout=300)
    _, out = run(["apt", "list", "--upgradable"])
    rows, security = [], []
    for line in (out or "").splitlines():
        m = re.match(r"^([^/\s]+)/(\S+)\s+(\S+)\s+\S+\s+\[upgradable from: ([^\]]+)\]", line)
        if not m:
            continue
        name, suites, new, old = m.groups()
        row = f"{name} {old} -> {new}"
        (security if "-security" in suites else rows).append(row)
    section(f"Mises à jour de sécurité en attente : {len(security)} (paquet actuelle -> disponible)")
    print(capped(sorted(security)))
    section(f"Autres mises à jour en attente : {len(rows)}")
    print(capped(sorted(rows), 25))
    section("Mises à jour automatiques")
    rc, out = run(["systemctl", "is-enabled", "unattended-upgrades"])
    auto = (out or "").strip() or "absent"
    periodic = ""
    for path in ("/etc/apt/apt.conf.d/20auto-upgrades", "/etc/apt/apt.conf.d/10periodic"):
        try:
            text = open(path, encoding="utf-8").read()
            if re.search(r'Unattended-Upgrade\s+"1"', text):
                periodic = "actives"
        except OSError:
            continue
    print(f"unattended-upgrades : {auto} ; mises à jour périodiques : {periodic or 'non configurées'}")
    section("Redémarrage nécessaire")
    if os.path.exists("/var/run/reboot-required"):
        pkgs = ""
        try:
            pkgs = ", ".join(sorted(set(open("/var/run/reboot-required.pkgs").read().split())))
        except OSError:
            pass
        print(f"oui (noyau ou bibliothèque système) : {pkgs or 'paquets non listés'}")
    else:
        print("non")
    if shutil.which("needrestart"):
        _, out = run(["needrestart", "-b", "-r", "l"])
        svc = sorted(l.split(":", 1)[1].strip() for l in (out or "").splitlines() if l.startswith("NEEDRESTART-SVC:"))
        print("services à relancer : " + (", ".join(svc) if svc else "aucun"))


def docker_part():
    section("Docker")
    if not shutil.which("docker"):
        print("Docker absent")
        return []
    _, ver = run(["docker", "version", "--format", "{{.Server.Version}}"])
    print(f"moteur Docker : {(ver or '?').strip()}")
    _, out = run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"])
    section("Conteneurs en service (nom image)")
    rows = sorted(l.replace("\t", " ") for l in (out or "").splitlines() if l.strip())
    print("\n".join(rows) or "aucun")
    _, out = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    images = sorted({l for l in (out or "").splitlines() if l and "<none>" not in l})
    used = {r.split(" ", 1)[1] for r in rows if " " in r}
    unused = [i for i in images if i not in used]
    section("Images présentes non utilisées")
    print("\n".join(unused) or "aucune")
    return [r.split(" ", 1)[0] for r in rows]


def hermes_part(containers):
    section("Hermes Agent en service")
    seen = False
    for name in containers:
        rc, out = run(["docker", "exec", name, "sh", "-c", "command -v hermes >/dev/null && hermes --version 2>/dev/null | head -1"], 60)
        if rc == 0 and (out or "").strip():
            seen = True
            print(f"{name} : {out.strip()[:80]}")
    for user_home in sorted({os.path.expanduser("~" + u) for u in CONF.get("native_users", "").split(",") if u}):
        print(f"{user_home} : installation native (version lue par l'agent avec son humain)")
    if not seen:
        print("aucun conteneur Hermes détecté")
    try:
        req = urllib.request.Request("https://api.github.com/repos/NousResearch/hermes-agent/releases/latest",
                                     headers={"User-Agent": "ottho-agent-updates", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print("dernière publication Hermes : " + json.load(r)["tag_name"])
    except Exception as exc:
        print(f"dernière publication Hermes : inconnue ({type(exc).__name__})")


def main():
    info = os_release()
    section("Système")
    print(f"{info.get('PRETTY_NAME', '?')}")
    _, kern = run(["uname", "-r"])
    print(f"noyau en service : {(kern or '?').strip()}")
    apt_part()
    containers = docker_part()
    hermes_part(containers)


if __name__ == "__main__":
    main()
