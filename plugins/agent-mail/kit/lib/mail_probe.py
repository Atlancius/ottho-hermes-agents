"""Sonde IMAP de l'agent mail, exécutée DANS la cible par le Python de Hermes :
  <python> - <action> <profil_home> < mail_probe.py
Actions :
  imap-save   lit l'adresse et le mot de passe sur stdin (2 lignes), teste la connexion, puis les écrit dans le .env
  test        teste la connexion avec les accès du .env
  folders     liste les dossiers du serveur et ceux des catégories qui manquent
  validate    valide mail-agent.yaml lu sur stdin (sans l'écrire)
Aucune valeur secrète n'est jamais affichée.
"""
import importlib
import os
import re
import sys
import types

action, home = sys.argv[1], sys.argv[2]
plugin_dir = os.path.join(home, "plugins", "mail-agent")
env_path = os.path.join(home, ".env")


def load_plugin():
    pkg = types.ModuleType("ottho_mail")
    pkg.__path__ = [plugin_dir]
    sys.modules["ottho_mail"] = pkg
    return importlib.import_module("ottho_mail.imap_client")


def read_env():
    values = {}
    try:
        from dotenv import dotenv_values
        values = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    except Exception:
        try:
            for line in open(env_path, encoding="utf-8"):
                k, sep, v = line.strip().partition("=")
                if sep:
                    values[k] = v.strip().strip("'\"")
        except OSError:
            pass
    return values


def config():
    import yaml
    with open(os.path.join(home, "mail-agent.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def connect(address, password):
    m = load_plugin()
    imap = config().get("imap") or {}
    host = str(imap.get("host") or "")
    if not host:
        sys.exit("ÉCHEC : imap.host absent de mail-agent.yaml")
    proxy = os.environ.get("MAIL_AGENT_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    s = m.ImapSettings(host=host, port=int(imap.get("port") or 993), address=address, password=password, proxy=proxy)
    try:
        return m, m.Mailbox(s)
    except Exception as exc:
        sys.exit(f"ÉCHEC : {type(exc).__name__}")


def quoted(value):
    if "'" not in value:
        return "'" + value + "'"
    if "${" not in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    sys.exit("REFUSÉ : mot de passe contenant à la fois une apostrophe et ${ : change-le chez ton fournisseur.")


def probe(address, password):
    m, box = connect(address, password)
    try:
        with box as mb:
            folders = mb.list_folders()
            print(f"IMAP OK : {len(folders)} dossiers, IDLE {'oui' if 'IDLE' in mb.caps else 'non'}")
            return folders
    except m.AuthError:
        sys.exit("ÉCHEC : identifiants refusés par le serveur (mot de passe, mot de passe d'application ou IMAP désactivé)")
    except Exception as exc:
        sys.exit(f"ÉCHEC : {type(exc).__name__} (serveur, port ou pare-feu de sortie)")


if action == "imap-save":
    address = "".join(sys.stdin.readline().split())
    password = sys.stdin.readline().rstrip("\r\n")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", address):
        sys.exit("REFUSÉ : adresse invalide")
    if not password:
        sys.exit("REFUSÉ : mot de passe vide")
    probe(address, password)
    lines = []
    if os.path.exists(env_path):
        lines = [l for l in open(env_path, encoding="utf-8").read().splitlines()
                 if not re.match(r"MAIL_AGENT_(ADDRESS|PASSWORD)=", l)]
    lines += ["MAIL_AGENT_ADDRESS=" + address, "MAIL_AGENT_PASSWORD=" + quoted(password)]
    fd = os.open(env_path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, ("\n".join(lines) + "\n").encode())
    os.close(fd)
    os.replace(env_path + ".tmp", env_path)
    if read_env().get("MAIL_AGENT_PASSWORD") != password:
        sys.exit("ÉCHEC : relecture du .env différente de la saisie")
    print("Accès enregistrés dans le .env du profil (600).")
elif action == "test":
    env = read_env()
    if not (env.get("MAIL_AGENT_ADDRESS") and env.get("MAIL_AGENT_PASSWORD")):
        sys.exit("ÉCHEC : accès IMAP absents (agent.sh secret imap)")
    probe(env["MAIL_AGENT_ADDRESS"], env["MAIL_AGENT_PASSWORD"])
elif action == "folders":
    env = read_env()
    folders = probe(env.get("MAIL_AGENT_ADDRESS", ""), env.get("MAIL_AGENT_PASSWORD", ""))
    names = sorted(f.name for f in folders)
    print("Dossiers du serveur :")
    for n in names:
        print("  " + n)
    wanted = {str(v.get("folder") if isinstance(v, dict) else v) for v in (config().get("categories") or {}).values()}
    lower = {n.casefold() for n in names}
    missing = sorted(w for w in wanted if w and w.casefold() not in lower and w.upper() != "INBOX")
    print("Dossiers des catégories absents du serveur : " + (", ".join(missing) if missing else "aucun"))
elif action == "validate":
    import yaml
    try:
        data = yaml.safe_load(sys.stdin.read()) or {}
    except yaml.YAMLError as exc:
        sys.exit(f"YAML invalide : {exc}")
    errors = []
    if str(data.get("mode", "shadow")) not in ("shadow", "live"):
        errors.append("mode doit valoir shadow ou live")
    if not str((data.get("imap") or {}).get("host") or ""):
        errors.append("imap.host manquant")
    cats = data.get("categories")
    if not isinstance(cats, dict) or not cats:
        errors.append("categories : au moins une catégorie")
    else:
        for key, val in cats.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", str(key)):
                errors.append(f"catégorie {key!r} : clé en minuscules sans espace")
            if not (isinstance(val, dict) and str(val.get("folder") or "").strip()):
                errors.append(f"catégorie {key} : folder manquant")
    brands = data.get("brands") or {}
    if not isinstance(brands, dict):
        errors.append("brands doit être une liste clé: {label, description, from_name, signature}")
    for key in brands:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", str(key)) or key in ("indetermine", "commun"):
            errors.append(f"marque {key!r} : clé en minuscules, ni « indetermine » ni « commun »")
    for line in yaml.safe_dump(data, allow_unicode=True).splitlines():
        if re.search(r"(password|mot_de_passe|token|secret|api_key)\s*:", line, re.I):
            errors.append("aucun secret dans mail-agent.yaml : ils vont dans le .env (agent.sh secret …)")
            break
    if errors:
        sys.exit("REFUSÉ :\n  - " + "\n  - ".join(errors))
    print("VALIDE")
else:
    sys.exit(f"action inconnue : {action}")
