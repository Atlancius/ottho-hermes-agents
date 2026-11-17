# Ligne de commande commune des agents de veille (copie identique, source : shared/kit/lib/veille_cli.sh).
# Chaque agent.sh définit avant de sourcer ce fichier :
#   DEFAULT_PROFILE, PROFILE_DESC, COLLECT_CAL, VEILLE_MAX_AGE, SMART_POLICY, REASONING
#   CRONS : lignes « nom|expression|script|prompt »
#   CONF_KEYS : clés réglables par « agent.sh set clé=valeur »
# shellcheck shell=bash

usage() {
  cat <<EOF
Agent Ottho « $AGENT » — commandes (en root sur le VPS) :

  version                      version du kit
  detect                       installations Hermes trouvées sur ce serveur (JSON, une par ligne)
  install --target <docker:conteneur|native:utilisateur> [--profile $DEFAULT_PROFILE] [--owner Prénom]
          [--provider fournisseur --model identifiant] [--timezone Europe/Paris] [--force-soul]
                               crée ou complète le profil, garde-fous, collecte planifiée, tâches Telegram
  secret telegram              jeton du bot de l'agent + ton identifiant Telegram (à taper toi-même)
  secret model <VARIABLE>      clé du fournisseur de modèle dans le .env du profil (à taper toi-même)
  secret login <fournisseur>   connexion OAuth (ex. openai-codex) (à taper toi-même)
  set <clé=valeur>…            réglages : ${CONF_KEYS}
  push                         collecte maintenant et dépose l'instantané pour l'agent
  test                         collecte, affiche ce que l'agent recevra, liste ses tâches
  status                       état court (collecte, instantané, bot, tâches)
  restart                      relance la gateway Hermes de la cible
  logs [N]                     dernières lignes du journal (adresses et jetons masqués)
EOF
}

do_install() {
  local target="" profile="$DEFAULT_PROFILE" owner="" provider="" model="" tz="Europe/Paris"
  while [ $# -gt 0 ]; do
    case "$1" in
      --target) target="$2"; shift 2 ;;
      --profile) profile="$2"; shift 2 ;;
      --owner) owner="$2"; shift 2 ;;
      --provider) provider="$2"; shift 2 ;;
      --model) model="$2"; shift 2 ;;
      --timezone) tz="$2"; shift 2 ;;
      --force-soul) FORCE_SOUL=1; shift ;;
      *) fail "Option inconnue : $1" ;;
    esac
  done
  [ -n "$target" ] || fail "--target attendu (voir « agent.sh detect »)"
  valid_profile "$profile" || fail "Nom de profil invalide : minuscules et chiffres seulement (contrainte Hermes), jamais « default »"
  [[ "$tz" =~ ^[A-Za-z]+(/[A-Za-z_+-]+){0,2}$ ]] || fail "Fuseau invalide : $tz"
  parse_target "$target"
  PROFILE="$profile"
  conf_set "kind=$KIND" "container=$CONTAINER" "user=$HUSER" "home=$HROOT" "profile=$PROFILE" "timezone=$tz"
  [ -n "$owner" ] && conf_set "owner=$owner"
  [ -z "$(conf_get owner)" ] && conf_set "owner=ton humain"
  conf_set "agent_name=$AGENT"
  echo "== Profil Hermes"
  ensure_profile "$PROFILE" "$PROFILE_DESC"
  veille_install_files
  local spec; spec="$(mktemp)"
  python3 - "$spec" "$HROOT" "$PROFILE" "$provider" "$model" "$tz" "$SMART_POLICY" "$REASONING" "$PHOME" "$(t_python)" "$KIT/lib/deny.json" <<'PY'
import json, sys
out, home, profile, provider, model, tz, policy, effort, phome, py, deny = sys.argv[1:12]
spec = {
    "hermes_home": home, "profile": profile, "timezone": tz, "smart_policy": policy,
    "reasoning_effort": effort, "max_turns": 60,
    "model": {"provider": provider, "model": model} if provider and model else {},
    "deny": json.load(open(deny)),
    "disabled_toolsets": ["terminal", "code_execution", "browser", "vision", "video", "image_gen", "video_gen",
                          "tts", "delegation", "cronjob", "computer_use", "desktop_ui", "kanban"],
    "hook_command": f"{py} {phome}/hooks/ottho_perimeter.py",
    "platforms": ["telegram"],
}
json.dump(spec, open(out, "w"))
PY
  apply_profile "$spec"; : >"$spec"
  c_ok "Garde-fous : approbations smart, crons en refus, terminal coupé, écriture limitée à workspace/"
  install_soul "$KIT/templates/SOUL.md"
  echo "== Collecte (hôte, lecture seule)"
  VEILLE_MAX_AGE="$VEILLE_MAX_AGE" veille_push && c_ok "Instantané déposé dans $PHOME/inbox/"
  veille_timer "$COLLECT_CAL"
  echo "== Tâches planifiées de l'agent"
  local name expr mode prompt cron_ko=0
  while IFS='|' read -r name expr mode prompt; do
    [ -n "$name" ] || continue
    veille_cron "$name" "$expr" "$mode" "$prompt" </dev/null || cron_ko=1
  done <<<"$CRONS"
  [ "$cron_ko" = 0 ] || c_warn "Au moins une tâche planifiée manque : relance « install » après correction (rejouable)"
  echo
  echo "Reste à faire, toi-même dans ton terminal :"
  [ "$(secret_present TELEGRAM_BOT_TOKEN)" = oui ] || echo "  sudo $KIT/agent.sh secret telegram"
  [ -n "$provider" ] || echo "  (modèle) le profil garde le modèle par défaut de ta cellule ; pour en fixer un : relance install avec --provider et --model"
  echo "Puis : sudo $KIT/agent.sh test"
}

do_set() {
  need_conf
  local pair key
  for pair in "$@"; do
    key="${pair%%=*}"
    case " $CONF_KEYS " in *" $key "*) ;; *) fail "Clé inconnue : $key (clés : $CONF_KEYS)" ;; esac
    [[ "${pair#*=}" =~ ^[A-Za-z0-9\ ,.:/_@+-]*$ ]] || fail "Valeur refusée pour $key (caractères spéciaux)"
    conf_set "$pair"
    c_ok "$key enregistré"
  done
  install_soul "$KIT/templates/SOUL.md"
}

veille_main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    help|-h|--help) usage ;;
    version) cat "$KIT/VERSION" ;;
    detect) need_root; detect_targets ;;
    install) need_root; do_install "$@" ;;
    secret)
      need_root; need_conf
      case "${1:-}" in
        telegram) telegram_secret ;;
        model) model_secret "${2:-}" ;;
        login) model_login "${2:-}" ;;
        *) fail "secret telegram | secret model <VARIABLE> | secret login <fournisseur>" ;;
      esac ;;
    set) need_root; do_set "$@" ;;
    push) need_root; VEILLE_MAX_AGE="$VEILLE_MAX_AGE" veille_push ;;
    test)
      need_root; need_conf
      VEILLE_MAX_AGE="$VEILLE_MAX_AGE" veille_push && c_ok "Instantané collecté"
      echo "== Ce que l'agent recevra à sa prochaine tâche (sans modifier son état)"
      t_exec "$(t_python)" "$PHOME/scripts/watch.py" --full | head -80
      echo "== Tâches planifiées"; t_hermes cron list 2>/dev/null || c_warn "hermes cron list indisponible"
      echo "== Bot : TELEGRAM_BOT_TOKEN $(secret_present TELEGRAM_BOT_TOKEN)" ;;
    status) need_root; veille_status ;;
    restart) need_root; need_conf; t_restart_gateway ;;
    logs) need_root; need_conf; t_logs "${1:-120}" ;;
    *) usage >&2; exit 2 ;;
  esac
}
