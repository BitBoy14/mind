#!/usr/bin/env bash
# screenshot.sh -- ta et PNG-screenshot av en URL med en headless nettleser.
#
# BRUK:
#   tools/screenshot.sh <URL> <utfilsti.png> [bredde] [hoyde] [ventesekunder]
#
# Eksempel:
#   tools/screenshot.sh https://www.shrtct.site/mind/ /var/www/www.shrtct.site/mind/notes/dashbord.png
#   tools/screenshot.sh https://example.com out.png 1920 1080 3
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
    echo "Bruk: $0 <URL> <utfilsti.png> [bredde=1280] [hoyde=800] [ventesekunder=2]" >&2
    exit 1
}

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
