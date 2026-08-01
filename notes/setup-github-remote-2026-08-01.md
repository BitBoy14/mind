# Oppsett av GitHub-remote (BitBoy14/mind) — sikkerhetsskann FØRST

Dato: 2026-08-01
Oppdrag: Koble `origin` mot `https://github.com/BitBoy14/mind` (offentlig, tomt repo) og pushe hele historikken — men kun etter et fullstendig sikkerhetsskann av git-historikken.

## Nøkkelfunn (kort)

- **Skann: IKKE REN.** Fant et hardkodet, funksjonelt passord i historikken.
- **PUSH BLOKKERT.** Ingen remote lagt til, ingen push utført.
- Berørt: `lib.php`, linje 9: `const LOGIN_PASSWORD = 'REDACTED';` — innført i commit `0c3b199` (den aller første commiten som la til dashbordet) og til stede uendret i alle senere commits, inkl. HEAD (`333d95c`).
- Dette er selve autentiseringsmekanismen for MIND-dashbordet (`api/action.php`, `action === 'login'` sammenligner innsendt passord direkte mot denne konstanten). Å pushe dette til et offentlig repo ville gitt hvem som helst innloggingstilgang til dashbordet — inkludert mulighet til å sette Anthropic API-nøkkelen, styre agenten, lese minnet osv.
- Ingen andre hemmeligheter funnet: `secrets.conf`, `*.env`, `*.pem`, `*.key`, `enc_key`, `sudo_pass` er aldri committet. `.gitignore` dekker `secrets.conf`, `logs/`, `data/`, `agentwork/` korrekt. Anthropic API-nøkkelen leses kun fra `/etc/mind/secrets.conf` (utenfor repoet, kryptert) — aldri hardkodet i kildekoden.
- **Handling som kreves før push kan skje:** fjern hardkodet passord fra `lib.php` (flytt til `/etc/mind/secrets.conf` eller miljøvariabel, samme mønster som `anthropic_api_key`), bytt passordet (det gamle må anses kompromittert siden det ligger i lokal historikk og var ment for en snart-offentlig repo), commit fiksen, kjør skannet på nytt, og først da vurdere push. Merk også at historikken slik den står nå (commits `0c3b199` t.o.m. `333d95c`) fortsatt vil inneholde det gamle passordet i klartekst selv etter en fiksende commit — en enkel "fix commit" er ikke nok til å fjerne det fra historikken; det må enten aksepteres som skrapd (passordbytte gjør det ufarlig) eller historikken må skrives om (`git filter-repo`/BFG) før push til det offentlige repoet.

## Detaljert skann utført

Repo: `/var/www/www.shrtct.site/mind/` — 8 commits totalt, ingen branches ut over `master`/`main`, ingen tags.

### (a) Kandidatfiler i historikken (navnebasert)

```
git log --all --full-history --oneline -- secrets.conf     → (tomt, aldri committet)
git log --all --full-history --oneline -- '*.conf'         → (tomt)
git log --all --full-history --oneline -- '*.env'          → (tomt)
git log --all --full-history --oneline -- '*.pem'          → (tomt)
git log --all --full-history --oneline -- '*.key'          → (tomt)
```

Filer noensinne trackt med "secret"/"credential" i navnet: kun `notes/impl-secrets-herding-2026-08-01.md` (dokumentasjon om herding av secrets.conf-mekanismen — ikke selve hemmeligheten).

Full liste over alle filer noensinne trackt i repoet (16 stk, ingen `.conf/.env/.pem/.key`-filer):
`api/action.php`, `api/state.php`, `core/mind/agents.py`, `core/mind/brain.py`, `core/mind/config.py`, `core/mind/cycle.py`, `core/mind/daemon.py`, `core/mind/db.py`, `core/mind/__init__.py`, `core/mind/jarvis_link.py`, `core/mind/memory.py`, `core/mind/prompts.py`, `core/mind/pulse.py`, `core/mind/responder.py`, `core/requirements.txt`, `deploy/mind.service`, `.gitignore`, `index.php`, `lib.php`, samt 5 notatfiler under `notes/`.

### (b) Innholdsbasert grep gjennom alle commits (alle blober i alle 8 commits)

Kjørt: `git rev-list --all | xargs -I{} git grep -Iln -e <mønster> {} --` for hvert av mønstrene:
`api_key`, `api-key`, `apikey`, `password`, `passwd`, `secret`, `token`, `BEGIN PRIVATE KEY`, `BEGIN RSA`, `BEGIN OPENSSH`, `mongodb://`, `postgres://`, `mysql://`, `AKIA` (AWS-nøkkelprefiks), `ghp_` (GitHub PAT-prefiks), `xox[baprs]-` (Slack-token), `sk-[a-zA-Z0-9]{20,}` (generisk API-nøkkelform).

Treff gjennomgått fil for fil:
- `core/mind/config.py`: leser hemmeligheter fra `/etc/mind/secrets.conf` (kryptert, utenfor repo) og `/etc/mind/sudo_pass`; ingen literale verdier i kildekoden. `MONGO_URI = "mongodb://127.0.0.1:27017"` — lokal, uten credentials.
- `lib.php`: **`LOGIN_PASSWORD = 'REDACTED'` — literal hemmelighet, se over.** Ellers samme mønster som config.py for secrets.conf/mongodb (kryptering, filnavn/stier — ingen andre literale verdier).
- `api/action.php`, `api/state.php`, `index.php`: bruker ordene `password`/`token`/`api_key`/`apikey` kun som feltnavn i skjema/JSON (innloggingsskjema, token-teller i UI, felt for å sette API-nøkkel via UI) — ingen literale nøkkelverdier.
- `core/mind/agents.py`, `brain.py`, `cycle.py`, `db.py`, `memory.py`, `prompts.py`, `pulse.py`, `responder.py`: treff er kun ordet "token" i betydningen LLM-tokens (telling/budsjett), ikke credentials.
- Ingen treff i det hele tatt på: `passwd`, `BEGIN PRIVATE KEY`, `BEGIN RSA`, `BEGIN OPENSSH`, `postgres://`, `mysql://`, `AKIA`, `ghp_`, `xox[baprs]-`, `sk-[a-zA-Z0-9]{20,}`.
- Ekstra søk etter lange base64/hex-aktige literaler (`['\"][A-Za-z0-9+/]{32,}={0,2}['\"]`) gjennom hele `git log --all -p`: ingen treff.

### (c) `.gitignore`-dekning

```
core/venv/
__pycache__/
*.pyc
logs/
agentwork/
data/

secrets.conf
```
Dekker `secrets.conf` eksplisitt (med kommentar om at den normalt uansett ligger i `/etc/mind/` og ikke i repoet), samt `logs/`, `data/`, `agentwork/`. `enc_key` og `sudo_pass` ligger også i `/etc/mind/` (utenfor repo-treet) og er derfor ikke en trussel via dette repoet, men er heller ikke eksplisitt i `.gitignore` — anbefaler å legge dem til der for forsvar-i-dybden, tilsvarende begrunnelsen som allerede står for `secrets.conf`.

## Remote- og auth-status

- `git remote -v` → tomt, ingen remote konfigurert. **Ingen remote lagt til** (Steg 2 ble bevisst hoppet over pga. blokkert skann).
- Autentiseringsmetode (gh/SSH/credential helper) ble **ikke sjekket**, siden det er irrelevant før skannet er rent.

## Konklusjon

**PUSH BLOKKERT.**

Neste steg (for et fremtidig oppdrag, ikke utført her): fiks `lib.php` (fjern hardkodet passord, flytt til secrets.conf-mekanismen), bytt det kompromitterte passordet, avgjør om historikken skal skrives om før push, kjør skannet på nytt, og gjenta deretter Steg 2 (remote + push) i denne oppdragsbeskrivelsen.
