#!/usr/bin/env python3
"""Collecte de la posture de sécurité du VPS (root, sur l'hôte, bibliothèque standard seule, lecture seule).

Instantané STABLE : aucun horodatage, aucun pid, aucun compteur qui bouge seul. Même posture = même texte, donc aucun
appel au modèle. N'affiche jamais de secret (ni clé, ni jeton, ni contenu de .env) : seulement des noms, des états
et des empreintes courtes.
  python3 collect.py /etc/ottho-agents/securite.json
Réglages lus : ssh_known_sources (adresses ou préfixes séparés par des virgules, ex. "203.0.113.7,2001:db8:1::/48").
"""
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys

CONF = json.load(open(sys.argv[1], encoding="utf-8")) if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else {}
KNOWN = []
for item in str(CONF.get("ssh_known_sources", "")).split(","):
    item = item.strip()
    if item:
        try:
            KNOWN.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            pass


def run(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"(indisponible : {type(exc).__name__})"
    return p.returncode, p.stdout


def section(title):
    print(f"\n## {title}")


def short_hash(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def known(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in KNOWN)


def containers():
    section("Conteneurs (nom image état réseau-hôte privilégié socket-docker)")
    if not shutil.which("docker"):
        print("Docker absent")
        return
    _, ids = run(["docker", "ps", "-aq"])
    rows = []
    for cid in (ids or "").split():
        _, out = run(["docker", "inspect", cid])
        try:
            c = json.loads(out)[0]
        except (ValueError, IndexError, TypeError):
            continue
        st = c.get("State", {})
        health = (st.get("Health") or {}).get("Status")
        state = health or ("up" if st.get("Running") else "arrêté")
        hc = c.get("HostConfig", {})
        mounts = " ".join(m.get("Source", "") for m in c.get("Mounts", []))
        rows.append(f"{c.get('Name', '?').lstrip('/')} {c.get('Config', {}).get('Image', '?')} {state} "
                    f"{'OUI' if hc.get('NetworkMode') == 'host' else 'non'} {'OUI' if hc.get('Privileged') else 'non'} "
                    f"{'OUI' if 'docker.sock' in mounts else 'non'}")
    print("\n".join(sorted(rows)) or "aucun")


def ports():
    section("Ports en écoute hors boucle locale (proto adresse processus)")
    _, out = run(["ss", "-H", "-tulnp"])
    rows = set()
    for line in (out or "").splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        addr = f[4]
        if addr.startswith(("127.", "[::1]", "::1")):
            continue
        proc = re.search(r'\(\("([^"]+)"', line)
        rows.add(f"{f[0]} {addr} {proc.group(1) if proc else '?'}")
    print("\n".join(sorted(rows)) or "aucun")


def firewall():
    section("Pare-feu")
    if shutil.which("ufw"):
        _, out = run(["ufw", "status", "verbose"])
        lines = (out or "").splitlines()
        print("\n".join(l for l in lines if l.startswith(("Status:", "Default:"))) or "ufw : état inconnu")
        rules = sorted(l.strip() for l in lines if re.match(r"^\S.*\s(ALLOW|DENY|REJECT|LIMIT)\b", l))
        print("règles ufw :\n" + ("\n".join("  " + r for r in rules) or "  aucune"))
    if shutil.which("nft"):
        _, out = run(["nft", "list", "ruleset"])
        stable = re.sub(r"counter packets \d+ bytes \d+", "counter", out or "")
        stable = "\n".join(l for l in stable.splitlines() if not l.lstrip().startswith("# Warning:"))
        print(f"empreinte nftables : {short_hash(stable)}")
    if not shutil.which("ufw") and not shutil.which("nft"):
        print("aucun pare-feu local détecté")


def fail2ban():
    section("fail2ban")
    if not shutil.which("fail2ban-client"):
        print("absent")
        return
    _, out = run(["fail2ban-client", "status"])
    jails = re.search(r"Jail list:\s*(.*)", out or "")
    print(f"prisons actives : {jails.group(1).strip() if jails else 'aucune (service arrêté ?)'}")


def ssh():
    section("SSH (réglages effectifs)")
    if shutil.which("sshd"):
        _, out = run(["sshd", "-T"])
        keep = ("port", "permitrootlogin", "passwordauthentication", "kbdinteractiveauthentication",
                "pubkeyauthentication", "maxauthtries", "allowusers", "x11forwarding")
        rows = sorted(l for l in (out or "").splitlines() if l.split(" ", 1)[0] in keep)
        print("\n".join(rows) or "sshd -T indisponible")
    section("Clés SSH autorisées (utilisateur nombre empreinte-du-fichier)")
    rows = []
    for line in open("/etc/passwd", encoding="utf-8", errors="replace"):
        parts = line.split(":")
        if len(parts) < 7:
            continue
        path = os.path.join(parts[5], ".ssh", "authorized_keys")
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        keys = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
        rows.append(f"{parts[0]} {len(keys)} {short_hash(text)}")
    print("\n".join(sorted(rows)) or "aucune")
    section("Connexions SSH acceptées sur 24 h (méthode utilisateur source statut)")
    _, out = run(["journalctl", "--since", "-24h", "--no-pager", "-o", "cat", "_COMM=sshd"])
    if not (out or "").strip():
        try:
            out = open("/var/log/auth.log", encoding="utf-8", errors="replace").read()[-2_000_000:]
        except OSError:
            out = ""
    acc = sorted({f"{m.group(1)} {m.group(2)} {m.group(3)} {'connue' if known(m.group(3)) else 'INCONNUE'}"
                  for m in re.finditer(r"Accepted (\S+) for (\S+) from (\S+)", out or "")})
    print("\n".join(acc) or "aucune")


def accounts():
    section("Comptes à privilèges")
    root_like = sorted(l.split(":")[0] for l in open("/etc/passwd", encoding="utf-8", errors="replace")
                       if len(l.split(":")) > 3 and l.split(":")[2] == "0")
    print("uid 0 : " + ", ".join(root_like))
    sudoers = []
    for line in open("/etc/group", encoding="utf-8", errors="replace"):
        name, _, _, members = (line.rstrip("\n").split(":") + ["", "", "", ""])[:4]
        if name in ("sudo", "wheel", "admin") and members:
            sudoers += members.split(",")
    print("groupes sudo/wheel : " + (", ".join(sorted(set(sudoers))) or "aucun membre"))
    files = sorted(os.listdir("/etc/sudoers.d")) if os.path.isdir("/etc/sudoers.d") else []
    print("fichiers /etc/sudoers.d : " + (", ".join(files) or "aucun"))


def system():
    section("Système")
    _, out = run(["systemctl", "--failed", "--no-legend", "--plain"])
    failed = sorted(l.split()[0] for l in (out or "").splitlines() if l.strip())
    print("services en échec : " + (", ".join(failed) or "aucun"))
    _, out = run(["df", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "overlay", "-x", "squashfs", "-x", "9p", "-x", "drvfs", "-x", "fuse.portal"])
    high = []
    for line in (out or "").splitlines()[1:]:
        f = line.split()
        if len(f) >= 6 and f[4].rstrip("%").isdigit() and int(f[4].rstrip("%")) >= 85:
            high.append(f"{f[5]} ≥ 85 %")
    print("disques presque pleins : " + (", ".join(high) or "aucun"))
    print("redémarrage requis : " + ("oui" if os.path.exists("/var/run/reboot-required") else "non"))
    _, out = run(["systemctl", "is-enabled", "unattended-upgrades"])
    print(f"mises à jour automatiques de sécurité : {(out or '').strip() or 'absentes'}")


def hermes_guardrails():
    section("Garde-fous des agents Hermes (conteneur/profil approvals cron)")
    if not shutil.which("docker"):
        print("Docker absent : contrôle à faire à la main pour une installation native")
        return
    _, names = run(["docker", "ps", "--format", "{{.Names}}"])
    rows = []
    script = ("import glob,os,yaml\n"
              "h=os.environ.get('HERMES_HOME') or '/opt/data'\n"
              "for p in sorted(glob.glob(h+'/profiles/*/config.yaml'))+[h+'/config.yaml']:\n"
              "  try: c=yaml.safe_load(open(p)) or {}\n"
              "  except Exception: continue\n"
              "  a=c.get('approvals') or {}\n"
              "  n='racine' if p==h+'/config.yaml' else p.split('/')[-2]\n"
              "  print(n, a.get('mode','?'), a.get('cron_mode','?'))\n")
    for name in (names or "").split():
        rc, has = run(["docker", "exec", name, "sh", "-c", "command -v hermes"], 30)
        if rc != 0 or not (has or "").strip():
            continue
        rc, py = run(["docker", "exec", name, "sh", "-c",
                      "test -x /opt/hermes/.venv/bin/python && echo /opt/hermes/.venv/bin/python || echo python3"], 30)
        rc, out = run(["docker", "exec", name, (py or "python3").strip(), "-c", script], 60)
        for line in (out or "").splitlines():
            rows.append(f"{name}/{line}")
        rc, env = run(["docker", "exec", name, "sh", "-c",
                       "grep -l '^GATEWAY_ALLOW_ALL_USERS=.*true' ${HERMES_HOME:-/opt/data}/.env "
                       "${HERMES_HOME:-/opt/data}/profiles/*/.env 2>/dev/null | wc -l"], 30)
        if (env or "0").strip() not in ("", "0"):
            rows.append(f"{name}/ATTENTION bot ouvert à tous (GATEWAY_ALLOW_ALL_USERS) dans {env.strip()} fichier(s)")
    print("\n".join(sorted(rows)) or "aucun conteneur Hermes détecté")


def main():
    containers()
    ports()
    firewall()
    fail2ban()
    ssh()
    accounts()
    system()
    hermes_guardrails()


if __name__ == "__main__":
    main()
