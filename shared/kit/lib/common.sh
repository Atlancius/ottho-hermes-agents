# Fonctions communes aux kits des agents Ottho (copie identique dans chaque plugin, source : shared/kit/lib/common.sh).
# Une « cible » est l'installation Hermes où vit le profil de l'agent :
#   docker : un conteneur Hermes (cellule Ottho Hermes VPS, image Hostinger, conteneur maison) ;
#   native : Hermes installé directement sur le serveur, pour un utilisateur Linux.
# Réglages de l'élève : /etc/ottho-agents/<agent>.json (aucun secret dedans).
# shellcheck shell=bash

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT="$(cat "$KIT/AGENT")"
CONF_DIR=/etc/ottho-agents
CONF="$CONF_DIR/$AGENT.json"
BACKUPS=/var/backups/ottho-agents

c_ok()   { printf '  \033[32mOK\033[0m %s\n' "$*"; }
c_info() { printf '  .. %s\n' "$*"; }
c_warn() { printf '  \033[33m!!\033[0m %s\n' "$*" >&2; }
fail()   { printf '  \033[31mKO\033[0m %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" = 0 ] || fail "À lancer en root (sudo)."; }
need_tty()  { [ -t 0 ] || fail "Commande à taper toi-même dans un terminal (saisie masquée) : ssh -t <serveur> sudo $KIT/agent.sh …"; }

conf_get() { # clé -> valeur (vide si absente)
  [ -f "$CONF" ] || { echo ""; return; }
  python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$CONF" "$1"
}

conf_set() { # clé=valeur… (fusion, fichier 600)
  install -d -m 700 "$CONF_DIR"
  python3 - "$CONF" "$@" <<'PY'
import json, os, sys
path = sys.argv[1]
data = json.load(open(path)) if os.path.exists(path) else {}
for pair in sys.argv[2:]:
    k, _, v = pair.partition("=")
    data[k] = v
tmp = path + ".tmp"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()); os.close(fd)
os.replace(tmp, path)
PY
}

need_conf() {
  [ -f "$CONF" ] && [ -n "$(conf_get kind)" ] && [ -n "$(conf_get profile)" ] \
    || fail "Agent pas encore installé : lance d'abord « agent.sh install --target … --profile … »."
  KIND="$(conf_get kind)"; CONTAINER="$(conf_get container)"; HUSER="$(conf_get user)"
  HROOT="$(conf_get home)"; PROFILE="$(conf_get profile)"; PHOME="$HROOT/profiles/$PROFILE"
}

valid_profile() { [[ "$1" =~ ^[a-z0-9]{1,31}$ ]] && [ "$1" != default ]; }  # contrainte Hermes

# --- exécution dans la cible ------------------------------------------------------------------------------
native_path() { local h; h="$(getent passwd "$HUSER" | cut -d: -f6)"; echo "$h/.local/bin:$h/.hermes/bin:/usr/local/bin:/usr/bin:/bin"; }
t_exec() { # commande… (sortie standard)
  if [ "$KIND" = docker ]; then docker exec -u "$HUSER" -e HERMES_HOME="$HROOT" "$CONTAINER" "$@"
  else sudo -u "$HUSER" -H env HERMES_HOME="$HROOT" PATH="$(native_path)" "$@"; fi
}
t_exec_i() { # commande… (avec entrée standard)
  if [ "$KIND" = docker ]; then docker exec -i -u "$HUSER" -e HERMES_HOME="$HROOT" "$CONTAINER" "$@"
  else sudo -u "$HUSER" -H env HERMES_HOME="$HROOT" PATH="$(native_path)" "$@"; fi
}
t_hermes() { t_exec hermes -p "$PROFILE" "$@"; }

t_python() { # interpréteur Python de Hermes (celui qui a pyyaml et les modules gateway)
  local bin shebang
  bin="$(t_exec sh -c 'command -v hermes' 2>/dev/null || true)"
  [ -n "$bin" ] || fail "Commande hermes introuvable dans la cible."
  for cand in /opt/hermes/.venv/bin/python; do
    t_exec test -x "$cand" 2>/dev/null && { echo "$cand"; return; }
  done
  shebang="$(t_exec head -1 "$bin" 2>/dev/null | sed -n 's/^#!\s*//p' | awk '{print $1}')"
  case "$shebang" in */python*) echo "$shebang" ;; *) echo python3 ;; esac
}

t_write() { # chemin mode < contenu : écrit atomiquement dans la cible, propriétaire = utilisateur Hermes
  local path="$1" mode="${2:-600}"
  t_exec_i sh -c 'set -e; d=$(dirname "$1"); mkdir -p "$d"; t="$1.ottho-tmp"; umask 077; cat > "$t"; chmod "$2" "$t"; mv "$t" "$1"' _ "$path" "$mode"
}

t_backup() { # chemin : copie horodatée sur l'hôte avant modification (jamais de suppression)
  local path="$1" stamp dest
  t_exec test -f "$path" 2>/dev/null || return 0
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"; dest="$BACKUPS/$AGENT/$stamp"
  install -d -m 700 "$dest"
  t_exec cat "$path" > "$dest/$(basename "$path")"
  chmod 600 "$dest/$(basename "$path")"
}

t_restart_gateway() {
  if [ "$KIND" = docker ]; then
    c_info "Redémarrage du conteneur $CONTAINER (gateway Hermes)…"
    docker restart "$CONTAINER" >/dev/null
    local i; for i in $(seq 1 60); do
      [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = true ] && { sleep 5; c_ok "$CONTAINER relancé"; return 0; }
      sleep 3
    done
    c_warn "$CONTAINER lent à redémarrer : docker logs --tail 80 $CONTAINER"
  else
    if t_hermes gateway restart >/dev/null 2>&1; then c_ok "gateway du profil $PROFILE relancée"
    else c_warn "Relance la gateway toi-même : sudo -u $HUSER -H hermes -p $PROFILE gateway restart (ou ton service systemd Hermes)"; fi
  fi
}

# --- détection ------------------------------------------------------------------------------------------
detect_targets() { # une ligne JSON par installation Hermes trouvée
  if command -v docker >/dev/null 2>&1; then
    docker ps --format '{{.Names}}' | while read -r c; do
      v="$(docker exec "$c" sh -c 'command -v hermes >/dev/null && hermes --version 2>/dev/null | head -1' 2>/dev/null || true)"
      [ -n "$v" ] || continue
      home="$(docker exec "$c" sh -c 'echo "${HERMES_HOME:-}"' 2>/dev/null)"
      [ -n "$home" ] || { docker exec "$c" test -d /opt/data && home=/opt/data; }
      user="$(docker exec "$c" sh -c "stat -c %U '${home:-/opt/data}' 2>/dev/null" || true)"
      profiles="$(docker exec "$c" sh -c "ls '${home:-/opt/data}/profiles' 2>/dev/null | tr '\n' ' '" || true)"
      python3 -c 'import json,sys; print(json.dumps({"kind":"docker","container":sys.argv[1],"version":sys.argv[2],"home":sys.argv[3],"user":sys.argv[4],"profiles":sys.argv[5].split()}, ensure_ascii=False))' \
        "$c" "$v" "${home:-?}" "${user:-?}" "$profiles"
    done
  fi
  getent passwd | awk -F: '$3==0 || $3>=1000 {print $1":"$6}' | while IFS=: read -r u h; do
    [ -d "$h/.hermes" ] || continue
    v="$(sudo -u "$u" -H bash -lc 'hermes --version 2>/dev/null | head -1' 2>/dev/null || true)"
    [ -n "$v" ] || continue
    profiles="$(ls "$h/.hermes/profiles" 2>/dev/null | tr '\n' ' ')"
    python3 -c 'import json,sys; print(json.dumps({"kind":"native","user":sys.argv[1],"version":sys.argv[2],"home":sys.argv[3],"profiles":sys.argv[4].split()}, ensure_ascii=False))' \
      "$u" "$v" "$h/.hermes" "$profiles"
  done
}

# --- installation commune d'un profil --------------------------------------------------------------------
parse_target() { # docker:<conteneur> | native:<utilisateur> -> KIND CONTAINER HUSER HROOT
  local spec="$1"
  case "$spec" in
    docker:*)
      KIND=docker; CONTAINER="${spec#docker:}"
      docker inspect "$CONTAINER" >/dev/null 2>&1 || fail "Conteneur introuvable : $CONTAINER"
      docker exec "$CONTAINER" sh -c 'command -v hermes' >/dev/null 2>&1 || fail "Pas de Hermes dans $CONTAINER"
      HROOT="$(docker exec "$CONTAINER" sh -c 'echo "${HERMES_HOME:-}"')"; [ -n "$HROOT" ] || HROOT=/opt/data
      HUSER="$(docker exec "$CONTAINER" stat -c %U "$HROOT")" ;;
    native:*)
      KIND=native; CONTAINER=""; HUSER="${spec#native:}"
      local h; h="$(getent passwd "$HUSER" | cut -d: -f6)"; [ -n "$h" ] || fail "Utilisateur inconnu : $HUSER"
      HROOT="$h/.hermes"; [ -d "$HROOT" ] || fail "Aucune installation Hermes dans $HROOT"
      sudo -u "$HUSER" -H bash -lc 'command -v hermes' >/dev/null || fail "Commande hermes absente pour $HUSER" ;;
    *) fail "Cible attendue : docker:<conteneur> ou native:<utilisateur> (voir « agent.sh detect »)" ;;
  esac
}

ensure_profile() { # profil description
  PHOME="$HROOT/profiles/$PROFILE"
  if t_exec test -d "$PHOME"; then
    c_ok "Profil $PROFILE déjà présent : il est complété, rien n'est effacé"
  else
    t_exec hermes profile create "$PROFILE" --no-alias --description "$2" >/dev/null \
      || fail "Création du profil $PROFILE impossible (hermes profile create)"
    c_ok "Profil $PROFILE créé"
  fi
}

apply_profile() { # fichier JSON de spécification (voir lib/profile_apply.py)
  local spec="$1" py
  t_backup "$PHOME/config.yaml"
  py="$(t_python)"
  t_exec_i "$py" - "$(cat "$spec")" < "$KIT/lib/profile_apply.py" || fail "Application des réglages du profil en échec"
}

install_soul() { # gabarit -> SOUL.md (conservé s'il a été modifié à la main depuis la dernière installation)
  local tpl="$1" want want_sha cur_sha last_sha
  want="$(python3 "$KIT/lib/render.py" "$tpl" "$CONF")"
  want_sha="$(printf '%s' "$want" | sha256sum | cut -c1-16)"
  cur_sha="$(t_exec cat "$PHOME/SOUL.md" 2>/dev/null | sha256sum | cut -c1-16)"
  last_sha="$(conf_get soul_sha)"
  if [ "$cur_sha" = "$want_sha" ]; then return 0; fi
  if [ -z "$last_sha" ] || [ "$cur_sha" = "$last_sha" ] || [ "${FORCE_SOUL:-0}" = 1 ] || ! t_exec test -s "$PHOME/SOUL.md"; then
    t_backup "$PHOME/SOUL.md"
    printf '%s' "$want" | t_write "$PHOME/SOUL.md" 644
    conf_set "soul_sha=$want_sha"
    c_ok "SOUL.md écrit"
  else
    c_warn "SOUL.md modifié à la main : conservé (--force-soul pour le remplacer, une copie est gardée dans $BACKUPS)"
  fi
}

secret_set() { # VARIABLE (valeur sur stdin, jamais en argument) -> .env du profil
  local py; py="$(t_python)"
  t_backup "$PHOME/.env"
  t_exec_i "$py" -c '
import os, re, sys
name, path = sys.argv[1], sys.argv[2]
value = sys.stdin.readline().rstrip("\r\n")
if not value:
    sys.exit("saisie vide : rien n a change")
if "\x27" not in value:
    quoted = "\x27" + value + "\x27"
elif "${" not in value:
    quoted = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
else:
    sys.exit("valeur contenant a la fois une apostrophe et ${ : choisis-en une autre")
lines = open(path).read().splitlines() if os.path.exists(path) else []
lines = [l for l in lines if not re.match(re.escape(name) + r"=", l)] + [name + "=" + quoted]
fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, ("\n".join(lines) + "\n").encode()); os.close(fd)
os.replace(path + ".tmp", path)
' "$1" "$PHOME/.env"
}

secret_present() { # VARIABLE -> oui/non (jamais la valeur)
  t_exec sh -c 'grep -q "^$1=..*" "$2" 2>/dev/null && echo oui || echo non' _ "$1" "$PHOME/.env"
}

ask_hidden() { # invite -> REPLY_SECRET
  local a
  printf '%s : ' "$1" >/dev/tty; IFS= read -rs a </dev/tty; printf '\n' >/dev/tty
  [ -n "$a" ] || fail "Saisie vide : rien n'a été modifié."
  REPLY_SECRET="$a"
}

telegram_secret() { # jeton du bot + identifiants autorisés -> .env du profil
  need_tty
  echo "Bot Telegram de l'agent : crée-le avec @BotFather (/newbot), puis colle ici la ligne complète du jeton."
  ask_hidden "Jeton du bot (ne s'affiche pas)"
  local tok="$REPLY_SECRET"; REPLY_SECRET=""
  [[ "$tok" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]] || fail "Format attendu : <chiffres>:<35 caractères> (la ligne donnée par @BotFather)."
  local me; me="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$tok" | curl -sS --max-time 15 -K - 2>/dev/null || true)"
  python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "{}"); sys.exit(0 if d.get("ok") else 1)' "$me" \
    || fail "Telegram ne reconnaît pas ce jeton (révoqué ou mal copié)."
  local uname; uname="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["result"]["username"])' "$me")"
  printf 'Ton identifiant Telegram numérique (demande-le à @userinfobot ; plusieurs : séparés par des virgules) : ' >/dev/tty
  local ids; IFS= read -r ids </dev/tty
  [[ "$ids" =~ ^[0-9]{4,15}(,[0-9]{4,15})*$ ]] || fail "Identifiant(s) invalide(s) : uniquement des chiffres, séparés par des virgules."
  printf '%s\n' "$tok" | secret_set TELEGRAM_BOT_TOKEN
  printf '%s\n' "$ids" | secret_set TELEGRAM_ALLOWED_USERS
  printf '%s\n' "${ids%%,*}" | secret_set TELEGRAM_HOME_CHANNEL
  tok=""
  c_ok "Bot @$uname enregistré ; seuls $ids peuvent lui parler"
  t_restart_gateway
}

model_secret() { # VARIABLE de clé de fournisseur
  need_tty
  local var="${1:?variable attendue, ex. OPENROUTER_API_KEY}"
  [[ "$var" =~ ^[A-Z][A-Z0-9_]{2,40}$ ]] || fail "Nom de variable invalide : $var"
  ask_hidden "Valeur de $var (ne s'affiche pas)"
  printf '%s\n' "$REPLY_SECRET" | secret_set "$var"; REPLY_SECRET=""
  c_ok "$var enregistrée dans le .env du profil $PROFILE"
  t_restart_gateway
}

model_login() { # fournisseur OAuth (ex. openai-codex)
  need_tty
  local prov="${1:?fournisseur attendu, ex. openai-codex}"
  if [ "$KIND" = docker ]; then docker exec -it -u "$HUSER" -e HERMES_HOME="$HROOT" "$CONTAINER" hermes -p "$PROFILE" auth add "$prov" --type oauth --no-browser
  else sudo -u "$HUSER" -H env HERMES_HOME="$HROOT" PATH="$(native_path)" hermes -p "$PROFILE" auth add "$prov" --type oauth --no-browser; fi
}

t_logs() { # N : dernières lignes du journal de la cible, adresses mail et jetons masqués
  local n="${1:-120}"
  [[ "$n" =~ ^[0-9]{1,4}$ ]] || n=120
  {
    if [ "$KIND" = docker ]; then docker logs --tail "$n" "$CONTAINER" 2>&1
    else journalctl --no-pager -n "$n" -o cat _UID="$(id -u "$HUSER")" 2>/dev/null || echo "journal indisponible pour $HUSER"; fi
  } | sed -E \
      -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[adresse]/g' \
      -e 's/[0-9]{6,12}:[A-Za-z0-9_-]{30,}/[jeton]/g' \
      -e 's/(sk|key|token|bearer|password)([-_ =:"]+)[A-Za-z0-9._-]{12,}/\1\2[masqué]/Ig'
}
