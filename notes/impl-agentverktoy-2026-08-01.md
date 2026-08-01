# Leveransenotat: Kraftigere kodeverktøy for agentene (2026-08-01)

Oppdrag: implementer godkjent forbedring «Kraftigere kodeverktøy for agenter»
— (1) presis linje-redigering, (2) screenshot-verktøy. Se commit `cc305f8`
for selve kodeendringen.

## Nøkkelfunn / essens

- **Agentene hadde allerede full verktøytilgang.** Runner-koden
  (`core/mind/agents.py`, `_run_claude_agent`) kaller
  `claude -p --dangerously-skip-permissions ...`, som gir agenten
  ubegrenset tilgang til alle innebygde verktøy (Edit, Write, Bash m.fl.) —
  ingen `--allowedTools`-restriksjon fantes å utvide. Det som manglet var
  ikke *tilgang*, men en eksplisitt **instruksjon** om å faktisk bruke
  presise verktøy (Edit / sed / grep / awk) fremfor å skrive hele filer på
  nytt. Denne instruksjonen er nå lagt inn i `AGENT_PREAMBLE`
  (`core/mind/prompts.py`), som går inn i hvert agentoppdrag via
  `_full_brief()`.
- **Nytt verktøy `tools/screenshot.sh`** tar PNG-screenshot av en URL med
  headless nettleser. Systemsjekk fant `chromium-browser` installert (snap:
  Chromium 150.0.7871.128) — ingen `google-chrome` eller `wkhtmltoimage`.
  Skriptet prøver `chromium`, `chromium-browser`, `google-chrome(-stable)`,
  deretter `wkhtmltoimage`; finner det ingen, feiler det tydelig (exit 3)
  uten å installere noe.
- **Viktig snap-fallgruve oppdaget og løst:** `chromium-browser` er en
  strict-confinement snap med kun `home`-interfacet tilkoblet
  (`snap connections chromium`). Den kan **ikke** skrive skjermbilder
  direkte til vilkårlige stier utenfor `$HOME` (feiler stille med
  "No such file or directory" fra Chromiums egen feilhåndtering — prosessen
  selv avslutter med exit 0!) — og den kan heller **ikke** skrive til
  skjulte (dot-)kataloger inni `$HOME` (f.eks. `~/.cache/...`, feiler med
  "Permission denied"). Skriptet jobber rundt begge begrensningene ved
  alltid å skrive til en midlertidig fil i en synlig katalog
  (`~/mind-screenshots/`) og deretter `mv` resultatet til ønsket utfilsti.
  Brukeren av skriptet trenger ikke tenke på dette.
- **Kjent begrensning, dokumentert i skriptet:** en DNS-feil, 404 e.l. gir
  IKKE exit ≠ 0 — nettleseren skriver da et gyldig skjermbilde *av
  feilsiden*, siden den fra sitt eget ståsted rendret ferdig. Skill
  "verktøyet feilet" fra "siden viste noe uventet" ved å inspisere selve
  PNG-en eller teste URL-en med `curl` først.
- **Testet mot mål-URL:** `https://www.shrtct.site/mind/` ble screenshotet
  vellykket (1280×900 PNG, se leveranse-fil under). Feilhåndtering
  (manglende argumenter, ugyldig URL-skjema) verifisert manuelt.
- `secrets.conf`-håndteringen (herdet i commit `55c81fc`) er ikke rørt —
  verifisert med `grep -n secrets` mot de endrede filene (ingen treff).
- Ingen PHP-filer ble endret i dette oppdraget, så `php -l` er ikke
  relevant for denne leveransen. (Sanity-sjekk: `php -l` kjørt mot alle
  `.php`-filer i repo-roten uten feil, som forventet uendret.)

## Commit-hasher

- `cc305f8` — Kraftigere kodeverktøy for agenter: presis redigering +
  screenshot-verktøy (kodeendringen: `core/mind/agents.py`,
  `core/mind/prompts.py`, `tools/screenshot.sh`,
  `notes/eksempel-screenshot-2026-08-01.png`)
- (dette notatet committes separat etter `cc305f8`)

## Leveranser (absolutte stier)

- `/var/www/www.shrtct.site/mind/tools/screenshot.sh` — nytt, kjørbart
  screenshot-verktøy (headless nettleser → PNG).
- `/var/www/www.shrtct.site/mind/core/mind/prompts.py` — `AGENT_PREAMBLE`
  utvidet med instruksjon om presis redigering og screenshot-verktøyet.
- `/var/www/www.shrtct.site/mind/core/mind/agents.py` — `_full_brief()`
  injiserer nå absolutt sti til `screenshot.sh` i hvert agentoppdrag.
- `/var/www/www.shrtct.site/mind/notes/eksempel-screenshot-2026-08-01.png`
  — testskjermbilde av `https://www.shrtct.site/mind/` (1280×900 PNG, tatt
  med `tools/screenshot.sh` som bevis på at verktøyet fungerer).
- `/var/www/www.shrtct.site/mind/notes/impl-agentverktoy-2026-08-01.md` —
  dette notatet.

## Ikke gjort / vurdert og forkastet

- La ikke til `--allowedTools`-flagg i `claude -p`-kallet: det ville kun
  vært relevant for å *begrense* verktøy, mens
  `--dangerously-skip-permissions` allerede gir full tilgang. Å legge til
  en allowlist ville vært en innskrenkning, ikke en utvidelse, og var
  utenfor oppdragets hensikt.
- Ingen systempakker installert (som instruert) — `chromium-browser` fantes
  allerede via snap, så fallback-dokumentasjonen for manglende nettleser er
  utestet i praksis her, men koden (exit 3 + tydelig feilmelding) er på
  plass for miljøer uten nettleser installert.
