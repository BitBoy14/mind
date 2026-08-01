#!/usr/bin/env bash
# mind-session.sh -- lag/slett en KORTLIVET innlogget MINDSESS-sesjon lokalt.
#
# HENSIKT: gjøre innloggede sider verifiserbare for agenter (screenshot, curl)
# uten å røre auth-koden, uten nye HTTP-endepunkter og uten å ta i
# innloggingspassordet. Sesjonen opprettes rett i PHPs sesjonslager på disk
# (files-handler), akkurat slik php-fpm selv ville skrevet den, og slettes
# igjen etterpå.
#
# BRUK:
#   tools/mind-session.sh create           # skriver sesjons-ID til stdout
#   tools/mind-session.sh destroy <ID>     # sletter sesjonen igjen
#   tools/mind-session.sh sweep [MINUTTER]  # rydder glemte agent-sesjoner (default 15)
#
# Typisk (rydder ALLTID opp, også ved feil):
#   SID="$(tools/mind-session.sh create)"
#   trap 'tools/mind-session.sh destroy "$SID"' EXIT
#   curl -s --cookie "MINDSESS=$SID" https://www.shrtct.site/mind/ | head
#
# SIKKERHET -- les dette før du utvider skriptet:
#   * Krever lokal root (sudo -n) fordi sesjonsfilen må eies av php-fpm-brukeren.
#     Ingen nettverkstilgang gir sesjoner; alt skjer på filsystemet på serveren.
#   * Sesjons-ID-en er et fullverdig innloggingsbevis så lenge den finnes.
#     Den skal ALDRI skrives til repoet, til logger i webroot, til rapporter
#     eller commit-meldinger -- kun holdes i en variabel i et kort skall-løp.
#   * Sesjoner merkes med nøkkelen mind_eph (tidsstempel) slik at `sweep` kan
#     kjenne dem igjen. lib.php bryr seg ikke om nøkkelen; kun mind_auth teller.
#   * Selv om `destroy` glipper, dør sesjonen av seg selv: PHPs
#     session.gc_maxlifetime (24 min på denne maskinen) + phpsessionclean.timer.
#     `sweep` er et raskere sikkerhetsnett for nettopp det tilfellet.
#
# Exit-koder: 0 = OK, 1 = feil bruk, 2 = miljøfeil (mangler sudo/katalog).
set -euo pipefail

die() { echo "FEIL: $*" >&2; exit "${2:-2}"; }

# --- finn php-fpm sitt sesjonslager og bruker (ikke hardkodet) --------------
fpm_ini="$(ls -1 /etc/php/*/fpm/php.ini 2>/dev/null | tail -n1 || true)"
fpm_pool="$(ls -1 /etc/php/*/fpm/pool.d/www.conf 2>/dev/null | tail -n1 || true)"

SESS_DIR="${MIND_SESSION_DIR:-}"
if [ -z "$SESS_DIR" ] && [ -n "$fpm_ini" ]; then
    # kun ukommenterte linjer teller
    SESS_DIR="$(sed -n 's/^[[:space:]]*session\.save_path[[:space:]]*=[[:space:]]*"\?\([^";]*\)"\?.*/\1/p' "$fpm_ini" | tail -n1)"
fi
SESS_DIR="${SESS_DIR:-/var/lib/php/sessions}"

FPM_USER="${MIND_SESSION_USER:-}"
if [ -z "$FPM_USER" ] && [ -n "$fpm_pool" ]; then
    FPM_USER="$(sed -n 's/^[[:space:]]*user[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$fpm_pool" | head -n1)"
fi
FPM_USER="${FPM_USER:-www-data}"

[ -d "$SESS_DIR" ] || die "sesjonskatalogen finnes ikke: $SESS_DIR"
sudo -n true 2>/dev/null || die "trenger passordfri sudo for å skrive som $FPM_USER"

# Gyldig ID: PHPs eget alfabet ved sid_bits_per_character=5 er a-z0-5.
# Mønsteret hindrer samtidig at 'destroy' kan peke utenfor sesjonskatalogen.
valid_id() { [[ "$1" =~ ^[a-z0-5]{20,64}$ ]]; }

cmd_create() {
    local id
    id="$(LC_ALL=C tr -dc 'a-z0-5' </dev/urandom | head -c 26 || true)"
    [ "${#id}" -eq 26 ] || die "klarte ikke generere sesjons-ID"
    local tmp
    tmp="$(mktemp)"
    chmod 600 "$tmp"
    # PHPs 'php'-serialisering: <navn>|<serialisert verdi> etter hverandre.
    printf 'mind_auth|b:1;mind_eph|i:%s;' "$(date +%s)" >"$tmp"
    sudo -n install -o "$FPM_USER" -g "$FPM_USER" -m 600 "$tmp" "$SESS_DIR/sess_$id"
    rm -f "$tmp"
    printf '%s\n' "$id"
}

cmd_destroy() {
    local id="${1:-}"
    [ -n "$id" ] || die "bruk: $0 destroy <sesjons-ID>" 1
    valid_id "$id" || die "ugyldig sesjons-ID-format" 1
    sudo -n rm -f -- "$SESS_DIR/sess_$id"
}

cmd_sweep() {
    local minutes="${1:-15}"
    [[ "$minutes" =~ ^[0-9]+$ ]] || die "bruk: $0 sweep [MINUTTER]" 1
    # Bare filer som BÅDE er merket som agent-sesjon og er gamle nok.
    # -print går til telleren, aldri til skjermen: filnavnet ER sesjons-ID-en.
    local n
    n="$(sudo -n find "$SESS_DIR" -maxdepth 1 -name 'sess_*' -type f -mmin "+$minutes" \
            -exec grep -qF 'mind_eph|i:' {} \; -print -delete 2>/dev/null | wc -l || true)"
    echo "sweep: fjernet ${n:-0} glemt(e) agent-sesjon(er) eldre enn $minutes min" >&2
}

case "${1:-}" in
    create)  cmd_create ;;
    destroy) shift; cmd_destroy "${1:-}" ;;
    sweep)   shift; cmd_sweep "${1:-15}" ;;
    *)
        echo "Bruk: $0 create | destroy <ID> | sweep [MINUTTER]" >&2
        exit 1
        ;;
esac
