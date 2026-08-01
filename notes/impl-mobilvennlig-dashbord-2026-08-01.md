# Mobilvennlig dashbord (responsivt design) — implementasjon og verifikasjon

**Dato:** 2026-08-01 · **Spor:** J · **Fil endret:** `index.php` (kun CSS + ett `<span>`)

## Konklusjon

Dashbordet er nå brukbart på telefon i bredden 375–430px: ingen horisontal
scrolling, alle trykkmål ≥44px, alle skrivefelt 16px (iOS auto-zoomer ikke),
og chatten ligger øverst i stedet for etter ~2000px scrolling. Skrivebordet er
verifisert **piksel-identisk** bortsett fra ett usynlig kantutjevningsavvik.

Dette er ren responsivitet — ørkentemaets farger, rammer, ikoner og typografi
er urørt. Ingen fargevariabel er endret.

## Hva var galt

Siden hadde allerede `<meta name="viewport">` og brøt til én kolonne under
850px, så problemet lå i selve CSS-en:

| Problem | Målt før |
|---|---|
| Topplinjen lå `sticky` og brøt over 4 rader | 170px = 20 % av en 844px skjerm, permanent |
| Chatten lå sist, etter fire paneler | chat-inputfeltet ~2100px ned |
| Knapper for små for en tommel | 27px høye (anbefalt minimum 44px) |
| Skrivefelt utløste iOS-zoom ved fokus | 13px (terskelen er 16px) |
| Sekundærtekst vanskelig å lese | `.kindtag` 10px, `.ts` 11px, `.muted` 12px |
| Panelene spiste over halve skjermen hver | `max-height:460px` |

## Hva ble gjort

**Grunnregler (gjelder alle bredder, verifisert uten visuell effekt):**
- `html { -webkit-text-size-adjust:100% }` — hindrer at mobile nettlesere
  blåser opp skrift på egen hånd.
- `body { overflow-wrap:break-word }` — arves ned; lange URL-er og ID-er
  bryter i stedet for å sprenge kolonnen.
- `#grid > div { min-width:0 }` — opphever grid-elementers auto-minimum, som
  ellers lar bredt innhold presse hele rutenettet ut i bredden.

**`@media (max-width:640px)` — telefon:**
- Topplinjen blir `position:static` (scroller bort) i stedet for `sticky`.
  Den blir ~200px høy fordi fem knapper à 44px må få plass — det er prisen for
  trykkmålene, og derfor skal den ikke ligge fast.
  «Innstillinger»-teksten skjules (`.btxt`), tannhjulet står alene.
- `button { min-height:44px }` og `input/select/textarea { min-height:44px;
  font-size:16px }`. Radio/avkryssing er eksplisitt unntatt så de ikke blir
  44px høye bokser. 16px er nøyaktig terskelen der iOS Safari slutter å zoome.
- `#chatpanel { order:-1 }` — chatten flyttes øverst. Ventende forslag til
  godkjenning (`#adminband`) kommer fortsatt først, siden de krever handling.
- `#chatpanel .panel { height:clamp(320px, 68dvh, 620px) }` med `70vh` som
  fallback. `dvh` følger den *synlige* delen av vinduet, så adresselinje og
  tastatur ikke dytter Send-knappen ut av syne. Chatfeltet ligger i vanlig
  dokumentflyt (ikke `position:fixed`), så nettleseren scroller det selv inn i
  bildet når tastaturet åpnes — det er nettopp derfor det ikke blir skjult.
- Panelkropper `max-height:340px`, sekundærtekst opp til 11–12,5px, og inline-
  lenkene «Kommentér»/«detaljer/filer» får tommelhøyde.
- Modaler fyller skjermen: `.formrow` stables vertikalt med fullbreddefelt.

**`@media (max-height:520px) and (pointer:coarse)` — telefon i landskap:**
Landskap gir 700–950px bredde og faller derfor utenfor regelen over, men
høyden er knapp. `pointer:coarse` gjør at blokken kun treffer berøringsskjermer
— aldri en vanlig skjerm.

## Verifikasjon

Skjermbilder er tatt med `tools/screenshot.sh` (chromium headless) mot en lokal
harness: `index.php` servert av `php -S` med stubbet `is_authed()` og
realistiske testdata. Ingen produksjonssesjon, ingen Mongo, ingen ekte data.

**Målt i nettleser** (`OVERFLOW_N` = elementer som stikker utenfor viewporten):

| Viewport | H-scroll | Knapper <44px | Felt <16px | Chat-input |
|---|---|---|---|---|
| 375×812 | NEI | 0 | 0 | 56px / 16px |
| 390×844 | NEI | 0 | 0 | 56px / 16px |
| 430×932 | NEI | 0 | 0 | 56px / 16px |
| 390×520 (trangt, som med tastatur oppe) | NEI | 0 | 0 | 56px / 16px |
| 844×390 (landskap) | NEI | 0 | 0 | 60px / 16px |

**Skrivebord 1440×900, piksel-diff mot original:** 75 av 1 296 000 piksler
(0,0058 %), største kanalavvik 39/255, alt innenfor 14×9px på ett enkelt
piltegn i token-linjen. Årsaken er `<span class="btxt">` rundt teksten
«Innstillinger», som endrer tekstoppdelingen med en brøkdel av en piksel.
Fjernes den spanen er diffen **0 piksler** — altså er samtlige CSS-endringer
beviselig uten effekt på skrivebordet.

Klokke og CSS-animasjoner ble fryst under målingen (`Date.now()` overstyrt,
`animation:none`), ellers gir den pulserende statusprikken og relative
tidsstempler falske utslag. Determinisme kontrollert: to opptak av samme
versjon gir 0 avvikende piksler.

Skjermbilder: `/tmp/mind-mobil-screenshots/` (01–03 før, 04–14 etter).
Harness og måleskript: `agentwork/6a6df82bc78017879c84b11f/`.

## Vurderingsvalg verdt å vite om

**Chatten ble flyttet øverst på mobil.** Den lå sist, etter fire
informasjonspaneler. På telefon er chatten hovedinngangen til MIND, så det
kostet ~2000px scrolling å gjøre det man kom for. Rekkefølgen er nå:
forslag til godkjenning → chat → Nå → Tankestrøm → Agenter → Minnet.
Skrivebordet beholder sin trekolonners rekkefølge. Ønskes den gamle
rekkefølgen også på mobil, er det én linje: fjern `#chatpanel { order:-1 }`
i begge media-blokkene.
