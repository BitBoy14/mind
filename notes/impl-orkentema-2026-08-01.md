# Implementert: Ørkentema + SVG-ikoner i MIND-dashbordet

**Bestilt av:** eieren (Mads), eksplisitt UI-oppdrag: hele grensesnittet skal
få ny fargestil i ørkentema (varme, dempede sand-/jordtoner), og
seksjonsoverskriftene «Nå», «Tankestrøm», «Agenter og oppgaver» og «Minnet»
skal få inline SVG-ikoner. Alle eksisterende emojier i UI-et skulle erstattes
med SVG.

Fil endret: `/var/www/www.shrtct.site/mind/index.php` (eneste fil).
**Ingen HTML-elementer, layout eller DOM-hierarki er endret** — kun CSS-verdier
og innhold *inne i* eksisterende elementer (ikoner lagt til før tekst).

## Paletten

Alle farger ble beregnet og verifisert for WCAG AA-kontrast med et lite
Python-script (`contrast.py`, kjørt i venv i arbeidskatalogen — luminans/
kontrastberegning etter WCAG 2.x-formelen, ingen eksterne avhengigheter).
Fasit (kontrastforhold mot de bakgrunnene fargen faktisk brukes på i UI-et):

| Variabel | Verdi | Bruk | Kontrast |
|---|---|---|---|
| `--bg` | `#E8DCC4` | sandbeige, side-bakgrunn | — |
| `--panel` | `#F4ECDA` | lys sand, panelbakgrunn | — |
| `--panel2` | `#E4D5B0` | mellomsand, inputs/knapper/sekundære flater | — |
| `--border` | `#8F754A` | varm jordbrun kantlinje | 3.2:1 / 3.7:1 (mot bg/panel, UI-komponent ≥3:1) |
| `--text` | `#3E2F1C` | mørk jordfarge, brødtekst | 9.5–11:1 mot bg/panel/panel2 |
| `--dim` | `#7A5C3E` | varm brun, dempet/sekundær tekst | 4.5–5.2:1 |
| `--accent` | `#B85C38` | terrakotta — bakgrunner/kantlinjer (knapper, meter, fokus) | ≥3:1 (UI-komponent) |
| `--accent-text` | `#8B3E22` | mørk terrakotta — lenketekst, `.tabs button.active`, `.clicky:hover` | 5.5–6.4:1 |
| `--green` | `#5F7A3D` | oliven — kun dekorativ statuspunkt (`●`) | 3.6–4.1:1 (≥3:1 for grafikk) |
| `--red` | `#9C3A29` | dempet murrød — feiltekst, `button.danger`, badge | 4.7–5.9:1, hvit på rød-badge 6.9:1 |
| `--amber` | `#8A5A18` | gyllenbrun — statuspunkt + kantlinje i tomgangsboks | 4.3–5.0:1 |
| `--amber-dark` | `#6E4610` | mørkere gyllenbrun — brødtekst i tomgangsboks (`.stagn`) | 6.0:1 mot boksens bakgrunn |
| `--purple` | `#7A4A6E` | dempet plomme — adminaksent (kantlinje + h2-tekst) | 5.1–5.9:1 |

To variabler (`--accent-text`, `--amber-dark`) er nye i denne commiten. De
finnes fordi den livlige terrakottaen (`--accent`, 3.3–3.9:1 mot lyse
bakgrunner) er fin som knapp-/kantlinje-/fyll-farge (UI-komponenter trenger
bare 3:1), men for svak som *tekst* (lenker, aktive faner) som krever 4.5:1 —
løsningen er å bruke den livlige versjonen til bakgrunner/kantlinjer og den
mørkere til tekst, i stedet for å gjøre hele paletten dovnere for å tvinge én
enkelt verdi til å dekke begge bruksområder.

Knapper i `button.primary` og chat-boblen `.msg.user` (begge med
`background:var(--accent)`) fikk eksplisitt `color:#fff` (hvit tekst på
terrakotta = 4.5:1, verifisert) — tilsvarende det gamle temaets mønster der
knappteksten var den mørke bakgrunnsfargen speilvendt mot den lyse aksenten.

## Endrede linjeområder i `index.php`

**CSS (`<style>`-blokk):**
- L12–15: `:root`-paletten (full utskifting av alle CSS-variabler).
- L20–21: `a { color:var(--accent-text) }` + ny regel `svg.ic { vertical-align:-2px; flex-shrink:0; }` (justerer alle inline SVG-ikoner til tekstlinjen).
- L25: `button.primary` — tekstfarge endret til hvit.
- L54–55: h2-lys-bakgrunn-overrideen fra commit `11ec470` **bevart konseptuelt**, men recolored: `background:#F8F0DC` (varm ivory, tydelig lysere enn selve panelet for fortsatt fremhevet header), `color:var(--text)` (11.4:1), `.muted`-spannet inni til `#6B5636` (6.1:1).
- L67–68: `.tabs button.active` (tekst → `--accent-text`); `.stagn` (tomgangsboks) redesignet fra mørk boks til lys gyllen boks (`#F2D9A8`) med `--amber-dark`-tekst, siden hele temaet nå er lyst.
- L79, 81: `.msg.user` (terrakotta bakgrunn + hvit tekst), `.msg.brain` (lys plum-tint `#EAD9E2` i stedet for mørk lilla).
- L88: `.modal-back`-overlay endret fra nøytral sort til varm jordfarge-tint (`rgba(62,47,28,.55)`) for helhet.
- L99: `.clicky:hover` → `--accent-text`.

**Statisk HTML (topbar + seksjonsoverskrifter):**
- L131–141: 🛠-emoji → skiftenøkkel-SVG (adminvarsel), ⚠️-emoji → varseltrekant-SVG (tomgangsvarsel), ⚙-emoji → tannhjul-SVG (innstillinger-knapp).
- L150, 154, 160, 164: nye ikoner lagt til foran de fire påkrevde overskriftene — klokke («Nå»), strømlinjer («Tankestrøm»), sjekkliste («Agenter og oppgaver»), hjerne («Minnet»). `.panel h2` hadde allerede `display:flex;align-items:center;gap:8px`, så ikonene får automatisk riktig avstand/justering uten CSS-endringer.

**JS (`<script>`-blokk):**
- L186–196: ny `const ICO = {...}` med gjenbrukbare SVG-strenger (wrench, gear, comment, folder, thought, file, play, pause, bolt) for ikonene som settes dynamisk via JS-templates.
- L245: `rb.textContent` → `rb.innerHTML` (nødvendig for å kunne injisere SVG i stedet for ren tekst) for ⏸/▶ Pause/Start-knappen.
- L250, 262, 301–302, 316, 388–391, 461, 469, 477: alle resterende emoji-forekomster (⚡ 🛠 💬 📁 💭 📄 ⚙) byttet til `${ICO.x}`.

**Viktig sikkerhetsdetalj (L388–391):** `drawChat()` bygde tidligere
«hvem»-linjen med `esc(who)`, der `who` kunne inneholde emoji-teksten. Hadde
jeg satt SVG-markup inn i samme streng ville `esc()` HTML-escapet SVG-en til
synlig tekst (`&lt;svg...&gt;`) i UI-et. Løst ved å skille ikon (usanert,
klarert konstant fra `ICO`) fra den faktiske merkelappen (`whoText`, fortsatt
kjørt gjennom `esc()` siden `m.marker` kan komme fra hjernens egen tekst og
skal fortsatt escapes for XSS-sikkerhet).

## Ikoner — hva ble konvertert, hva ble bevisst latt være

Konvertert til SVG (regnes som ekte pictogram-emoji): 🛠 ⚠️ 💬 📁 💭 📄 ⚙ ⚡ ▶ ⏸.

**Bevisst IKKE konvertert:** ↺ (reset-knapp) og ↑ / ↓ (token-linje-piler).
Disse er rene typografiske pilsymboler (Unicode «Arrows»-blokken), ikke
pictogram-emoji, og rendres allerede som nøytrale, ensfargede glyffer i de
fleste fonter/nettlesere — samme visuelle rolle som et CSS-ikon ville hatt.
Å konvertere dem ville lagt til kompleksitet uten lesbarhetsgevinst.

Alle SVG-er er `fill="none" stroke="currentColor"` (unntatt play/pause/bolt
som er `fill="currentColor"`) — de arver dermed tekstfargen fra konteksten de
står i (h2 mot lys bakgrunn, topbar-knapp mot panelbakgrunn, osv.), så
kontrasten følger automatisk samme kontrollerte palett som all annen tekst.
Ingen eksterne ikonfonter eller CDN-er — alt er håndskrevet inline SVG.

## Verifisering

- `php -l index.php` → «No syntax errors detected».
- Begge `<script>`-blokkene i filen ekstrahert og kjørt gjennom `node --check`
  → OK (ingen JS-syntaksfeil, spesielt viktig siden `.textContent` ble endret
  til `.innerHTML` ett sted).
- `grep -P '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' index.php` → ingen treff
  (alle pictogram-emojier borte).
- Alle kontrastforhold i tabellen over beregnet med et eget script
  (WCAG 2.x relativ luminans-formel), se metode i seksjonen «Paletten».
  Border-fargen ble justert tre ganger (fra for svak `#C7B48C` @1.5:1, via
  `#9C8152` @2.7–3.2:1, til endelig `#8F754A` @3.2–3.7:1) før den nådde
  3:1-terskelen som gjelder for synlige UI-avgrensninger.
- `git diff index.php` gjennomgått linje for linje: bekrefter at ingen
  `<div>`/`<span>`/andre strukturelle elementer er lagt til eller fjernet —
  kun CSS-verdier og SVG-markup satt inn *foran* eksisterende tekstinnhold i
  allerede eksisterende elementer.
- **Ikke testet visuelt i nettleser.** `php -S` ble startet lokalt og
  innloggingssiden ble hentet med `curl` (HTTP 200, palett bekreftet i
  utskrevet HTML via `grep` på hex-verdiene) — men selve dashbordet krever
  innlogging mot ekte backend (Mongo/daemon), som ikke er satt opp i denne
  arbeidskatalogen. Forsøk på skjermbilde med headless Chromium feilet
  (verktøyet meldte at filen ble skrevet, men den dukket aldri opp på disk —
  sannsynligvis snap-sandkasse-isolasjon av `/tmp` i dette miljøet, ikke noe
  spesifikt for denne endringen). Anbefaler visuell sjekk ved neste innlogging
  i en ekte nettleser, spesielt for chat-boblene og «Nå»/«Tankestrøm»-ikonene.

## Push-status

`git remote -v` er tomt — ingen `origin` konfigurert i dette repoet i det
hele tatt. Per oppdragets push-regel («HVIS origin er konfigurert OG …») er
betingelsen dermed ikke oppfylt uansett, og push er **hoppet over**. (Som en
ekstra opplysning: selv om `origin` hadde vært satt opp, viser
`notes/setup-github-remote-2026-08-01.md` at forrige sikkerhetsskann endte
med PUSH BLOKKERT pga. et hardkodet passord i `lib.php` sin historikk — denne
oppdaterte konklusjonen er fortsatt gjeldende og uendret av denne commiten.)
