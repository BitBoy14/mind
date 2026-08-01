#!/usr/bin/env bash
# screenshot.sh -- ta et PNG-screenshot av en URL med en headless nettleser.
#
# BRUK:
#   tools/screenshot.sh [flagg] <URL> <utfilsti.png> [bredde] [hoyde] [ventesekunder]
#
# Flagg (må stå FØR URL-en):
#   --auth              logg inn: lager en kortlivet MINDSESS-sesjon lokalt og
#                       gir den til nettleseren, slik at innloggede sider kan
#                       fotograferes. Sesjonen slettes alltid når skriptet er
#                       ferdig (også ved feil). Krever https og at URL-en peker
#                       på MIND-verten (se MIND_HOST under). Se tools/mind-session.sh.
#   --cookie NAVN=VERDI en vilkårlig cookie (kan gjentas).
#   --full-page         fotografer hele siden, ikke bare vinduet.
#
# Eksempel:
#   tools/screenshot.sh https://www.shrtct.site/mind/ /tmp/innlogging.png
#   tools/screenshot.sh --auth https://www.shrtct.site/mind/ /tmp/dashbord.png
#   tools/screenshot.sh https://example.com out.png 1920 1080 3
#
# ADVARSEL: skriv ALDRI screenshots til repoet/webroot (/var/www/...) -- alt
# der er offentlig lesbart, og et bilde av et innlogget dashbord lekker
# innhold. Bruk /tmp/ eller en katalog utenfor webroot.
#
# Standard vindusstørrelse er 1280x800. "ventesekunder" (default 2) er en
# --virtual-time-budget-ish pause chromium får før snapshot tas, nyttig for
# sider som rendrer asynkront (JS/CSS etter DOMContentLoaded).
#
# NETTLESERVALG: skriptet leter etter en headless-kapabel nettleser i denne
# rekkefølgen: chromium, chromium-browser, google-chrome, google-chrome-stable,
# wkhtmltoimage. Første treff brukes. Hvis ingen finnes avslutter skriptet med
# tydelig feilmelding (exit 3) -- det installeres ALDRI systempakker automatisk.
#
# TO KJØREMÅTER: uten cookies brukes chromiums enkle --screenshot-modus (som
# før). Med --auth/--cookie/--full-page finnes ingen tilsvarende kommandolinje-
# flagg i chromium, så jobben settes ut til tools/cdp_screenshot.py, som styrer
# nettleseren over DevTools-protokollen (kun Python-stdlib, ingen pip/venv).
#
# VIKTIG SNAP-BEGRENSNING (Ubuntu): chromium-browser her er en snap-pakke med
# strict confinement som kun har "home"-interfacet tilkoblet (se
# `snap connections chromium`). Den kan IKKE skrive filer direkte utenfor
# $HOME (f.eks. rett til /var/www/... feiler stille med
# "No such file or directory" fra chromiums headless-handler, selv om stien
# finnes) -- OG den kan heller ikke skrive til skjulte (dot-)kataloger inni
# $HOME (f.eks. $HOME/.cache/...), det feiler med "Permission denied" pga.
# snapens AppArmor-regler. Dette skriptet jobber derfor rundt begge
# begrensningene ved alltid å la nettleseren skrive til en midlertidig fil i
# en SYNLIG (ikke-skjult) katalog under $HOME (~/mind-screenshots/) og
# deretter flytte resultatet til den utfilstien du ba om. Du trenger ikke
# tenke på dette som bruker av skriptet -- oppgi utfilsti hvor som helst du
# har skrivetilgang, så håndterer skriptet flyttingen selv.
#
# Exit-koder: 0 = OK, 1 = feil argumenter, 2 = feil fra nettleseren
#             (f.eks. skriptet krasjer/timeout), 3 = ingen headless nettleser
#             funnet på systemet.
#
# MERK: en DNS-feil, 404 eller annen HTTP-feil gir IKKE exit != 0 -- da
# skriver nettleseren gyldig et skjermbilde AV feilsiden, siden den fra
# nettleserens ståsted rendret ferdig. Sjekk selve PNG-en (eller test URL-en
# med curl først) hvis du må skille "siden lastet, men viste noe uventet"
# fra "verktøyet feilet".
set -euo pipefail

usage() {
    echo "Bruk: $0 [--auth] [--cookie NAVN=VERDI] [--full-page] <URL> <utfilsti.png> [bredde=1280] [hoyde=800] [ventesekunder=2]" >&2
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Verten --auth-sesjonen gjelder for. Cookien sendes ALDRI til noen annen vert:
# det ville lekke et gyldig innloggingsbevis til en tredjepart.
MIND_HOST="${MIND_HOST:-www.shrtct.site}"

AUTH=0
FULLPAGE=0
COOKIES=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --auth)      AUTH=1; shift ;;
        --full-page) FULLPAGE=1; shift ;;
        --cookie)
            [ "$#" -ge 2 ] || usage
            COOKIES+=("$2"); shift 2 ;;
        -h|--help)   usage ;;
        --)          shift; break ;;
        -*)          echo "FEIL: ukjent flagg: $1" >&2; usage ;;
        *)           break ;;
    esac
done

if [ "$#" -lt 2 ]; then
    usage
fi

URL="$1"
OUTFILE="$2"
WIDTH="${3:-1280}"
HEIGHT="${4:-800}"
WAIT_S="${5:-2}"

case "$URL" in
    http://*|https://*) ;;
    *)
        echo "FEIL: URL må starte med http:// eller https:// (fikk: $URL)" >&2
        exit 1
        ;;
esac

mkdir -p "$(dirname "$OUTFILE")"

# Verten i URL-en, uten skjema, bruker@, port og sti.
url_host() {
    printf '%s' "$1" | sed -e 's|^[a-zA-Z][a-zA-Z0-9+.-]*://||' \
                           -e 's|[/?#].*$||' -e 's|^[^@]*@||' -e 's|:[0-9]*$||'
}

if [ "$AUTH" -eq 1 ]; then
    case "$URL" in
        https://*) ;;
        *) echo "FEIL: --auth krever https (sesjonscookien er Secure)" >&2; exit 1 ;;
    esac
    if [ "$(url_host "$URL")" != "$MIND_HOST" ]; then
        echo "FEIL: --auth er kun tillatt mot $MIND_HOST (fikk: $(url_host "$URL"))." >&2
        echo "      Sett MIND_HOST hvis plattformen har flyttet." >&2
        exit 1
    fi
    if ! MIND_SID="$("$SCRIPT_DIR/mind-session.sh" create)"; then
        echo "FEIL: klarte ikke opprette midlertidig sesjon (se melding over)" >&2
        exit 2
    fi
    # Rydd ALLTID opp: sesjons-ID-en er et gyldig innloggingsbevis så lenge
    # filen finnes. Ingen exec nedenfor -- det ville hoppet over denne fella.
    trap '"$SCRIPT_DIR/mind-session.sh" destroy "$MIND_SID" >/dev/null 2>&1 || true' EXIT
    COOKIES+=("MINDSESS=$MIND_SID")
fi

# Cookies og helside krever DevTools-veien; chromium har ingen flagg for det.
if [ "${#COOKIES[@]}" -gt 0 ] || [ "$FULLPAGE" -eq 1 ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "FEIL: --auth/--cookie/--full-page krever python3 (kun stdlib brukes)" >&2
        exit 3
    fi
    CDP_ARGS=(--url "$URL" --out "$OUTFILE" --width "$WIDTH" --height "$HEIGHT" --wait "$WAIT_S")
    [ "$FULLPAGE" -eq 1 ] && CDP_ARGS+=(--full-page)
    rc=0
    if [ "${#COOKIES[@]}" -gt 0 ]; then
        # Cookies sendes på stdin, ikke som argumenter: kommandolinjer er
        # lesbare for alle lokale brukere via ps/proc.
        printf '%s\n' "${COOKIES[@]}" \
            | python3 "$SCRIPT_DIR/cdp_screenshot.py" "${CDP_ARGS[@]}" --cookies-stdin || rc=$?
    else
        python3 "$SCRIPT_DIR/cdp_screenshot.py" "${CDP_ARGS[@]}" || rc=$?
    fi
    exit "$rc"
fi

find_browser() {
    for bin in chromium chromium-browser google-chrome google-chrome-stable; do
        if command -v "$bin" >/dev/null 2>&1; then
            echo "$bin"
            return 0
        fi
    done
    return 1
}

TMPDIR_SHOT="$HOME/mind-screenshots"
mkdir -p "$TMPDIR_SHOT"
TMP_PNG="$TMPDIR_SHOT/shot_$$_$(date +%s 2>/dev/null || echo tmp).png"

cleanup() { rm -f "$TMP_PNG"; }
trap cleanup EXIT

if BROWSER_BIN="$(find_browser)"; then
    # --virtual-time-budget gir siden tid til å rendre JS/CSS før snapshot
    # (i millisekunder); --hide-scrollbars gir et penere bilde.
    VTB_MS=$(( WAIT_S * 1000 ))
    if ! timeout 60 "$BROWSER_BIN" \
        --headless=new \
        --disable-gpu \
        --no-sandbox \
        --hide-scrollbars \
        --window-size="${WIDTH},${HEIGHT}" \
        --virtual-time-budget="$VTB_MS" \
        --screenshot="$TMP_PNG" \
        "$URL" >/tmp/mind-screenshot-$$.log 2>&1; then
        echo "FEIL: $BROWSER_BIN feilet ved screenshot av $URL" >&2
        tail -n 20 "/tmp/mind-screenshot-$$.log" >&2 || true
        rm -f "/tmp/mind-screenshot-$$.log"
        exit 2
    fi
    rm -f "/tmp/mind-screenshot-$$.log"
elif command -v wkhtmltoimage >/dev/null 2>&1; then
    if ! timeout 60 wkhtmltoimage --width "$WIDTH" --height "$HEIGHT" "$URL" "$TMP_PNG"; then
        echo "FEIL: wkhtmltoimage feilet ved screenshot av $URL" >&2
        exit 2
    fi
else
    cat >&2 <<'EOF'
FEIL: fant ingen headless nettleser (chromium, chromium-browser,
google-chrome, google-chrome-stable eller wkhtmltoimage) på systemet.
Dette skriptet installerer ALDRI pakker automatisk -- installer en av dem
manuelt (f.eks. `sudo apt install chromium-browser`) og prøv igjen.
EOF
    exit 3
fi

if [ ! -s "$TMP_PNG" ]; then
    echo "FEIL: screenshot-filen ble ikke opprettet eller er tom ($TMP_PNG)" >&2
    exit 2
fi

mv -f "$TMP_PNG" "$OUTFILE"
trap - EXIT
echo "OK: screenshot lagret til $OUTFILE"
