# Passordrotasjon: dashbord-passord flyttet fra lib.php til secrets.conf

## Essens / nøkkelfunn
- Det hardkodede innloggingspassordet (`const LOGIN_PASSWORD = 'FJERNET – passord rotert 2026-08-01'` på gammel linje 9 i `lib.php`) er fjernet fra kildekoden.
- Ny verdi er satt **kun** i `/etc/mind/secrets.conf` (kryptert, nøkkel `login_password_enc`), lagt inn via den eksisterende `save_secret()`-mekanismen fra `lib.php` (samme AES-256-CBC + fillås som øvrige hemmeligheter).
- `lib.php` leser og dekrypterer passordet ved oppstart via `read_secrets()` (samme mekanisme som resten av secrets-systemet, jf. commit 55c81fc) og definerer `LOGIN_PASSWORD` med `define()` i stedet for `const`. Dermed er `api/action.php` sin sammenligning (`$in['password'] === LOGIN_PASSWORD`) uendret og trengte **ingen** kodeendring.
- Verifisert med reell curl-innlogging mot det kjørende dashbordet (se punkt 4): ny verdi gir `{"ok":true}`, gammel verdi (`FJERNET – passord rotert 2026-08-01`) og en tilfeldig feil verdi gir begge `401 {"ok":false,"error":"Feil passord"}`.
- Passordverdien er bekreftet fraværende fra hele git-repoet (`grep -rn <verdi> .` i repoet ga ingen treff) og forekommer ikke i denne filen, i commit-meldingen eller andre steder i repoet — kun i `/etc/mind/secrets.conf`.
- **IKKE pushet** – kun lokal commit, som avtalt (historikk renses av annen agent før push).

## Leveranser (absolutte stier)
- Kodeendring: `/var/www/www.shrtct.site/mind/lib.php`
  - Fjernet: `const LOGIN_PASSWORD = 'FJERNET – passord rotert 2026-08-01';`
  - Lagt til: `decrypt_secret(string $value_b64): string` — motstykke til eksisterende `encrypt_secret()`.
  - Lagt til (etter `secret_is_set()`): `define('LOGIN_PASSWORD', decrypt_secret(read_secrets()['login_password_enc'] ?? ''));`
- Secret: `/etc/mind/secrets.conf` — ny nøkkel `login_password_enc` (kryptert verdi), satt via `php -r 'require "lib.php"; save_secret("login_password", ...);'` kjørt fra repo-roten. Filrettigheter uendret: `-rw-rw---- mads:www-data` (660), verifisert med `ls -l` før og etter.
- Commit: `a23113e44a479b342fc5412d52b70c4c70f6db85` på branch `master` i `/var/www/www.shrtct.site/mind/` — inneholder **kun** `lib.php` (1 fil, 13 insertions, 1 deletion). Ingen passordverdi i diff eller commit-melding.
- Dette notatet: `/var/www/www.shrtct.site/mind/notes/impl-passordrotasjon-2026-08-01.md`

## Detaljer

### 1. secrets.conf
Ny verdi satt direkte via eksisterende `save_secret()`-funksjon (samme kode-path som brukes for API-nøkler o.l.), for å garantere identisk krypteringsformat/format på fila. Filen inneholdt kun `{}` fra før (ingen andre secrets var satt ennå). Etter endring: én nøkkel, `login_password_enc`. Rettigheter kontrollert:
```
-rw-rw---- 1 mads www-data 70 aug.   1 14:56 /etc/mind/secrets.conf
```
(uendret fra før: 660, eier mads, gruppe www-data — som forventet av `check_secrets_file_perms()` i `lib.php`).

### 2. lib.php-endring
- `decrypt_secret()` er nøyaktig det motsatte av eksisterende `encrypt_secret()` (samme AES-256-CBC, iv||ct, base64-format), plassert rett under den i secrets-seksjonen.
- `LOGIN_PASSWORD` defineres nederst i fila (etter at `read_secrets()`/`decrypt_secret()` er deklarert) med `define()`, fordi PHP-`const` krever en verdi kjent ved kompilering — `define()` tillater en runtime-utledet verdi mens navnet `LOGIN_PASSWORD` og bruksstedet i `api/action.php` forblir helt uendret.
- Ingen andre filer trengte endring som følge av dette (verifisert med `grep -rln LOGIN_PASSWORD` — kun `lib.php` og `api/action.php`, og sistnevnte leser bare konstanten, endrer ikke hvordan den settes).

### 3. Absolutt krav om ingen forekomst av verdien i repoet
Kontrollert eksplisitt med:
```
grep -rn "<ny-verdi>" /var/www/www.shrtct.site/mind --exclude-dir=.git
```
→ ingen treff. Verdien er heller ikke limt inn i denne fila, i commit-meldingen, eller i sluttsvaret til hovedhjernen.

### 4. Verifisering
- `php -l lib.php` → "No syntax errors detected in lib.php".
- Funksjonstest i PHP CLI: dekryptert `LOGIN_PASSWORD` sammenlignet med `hash_equals()` mot riktig verdi (MATCH) og en feil verdi (NO MATCH) — bekrefter dekrypteringen fungerer korrekt uten å skrive verdien til disk.
- **Reell innlogging testet mot kjørende dashbord** (nginx + php8.1-fpm på denne boksen, samme kodebase, `Host: www.shrtct.site`):
  - `POST /mind/api/action.php {"action":"login","password":"<ny verdi>"}` → `200 {"ok":true}`
  - `POST /mind/api/action.php {"action":"login","password":"FJERNET – passord rotert 2026-08-01"}` (gammelt passord) → `401 {"ok":false,"error":"Feil passord"}`
  - `POST /mind/api/action.php {"action":"login","password":"<vilkårlig feil verdi>"}` → `401 {"ok":false,"error":"Feil passord"}`
  - Alle tre resultatene er som forventet: gammelt passord er nå ugyldig, nytt passord logger inn, feil passord avvises fortsatt.

## Merknad om urelaterte endringer i arbeidskatalogen
`index.php` og en ny fil `notes/verif-agentverktoy-2026-08-01.md` lå allerede endret/utrackede i repoet ved oppstart av dette oppdraget (fra annet, pågående arbeid). Disse er **ikke** rørt eller committet av dette oppdraget — kun `lib.php` ble staget og committet, i tråd med instruksjonen om å committe kun kodeendringen.

## Problemer
Ingen. Alle steg i oppdraget lot seg gjennomføre og verifisere direkte på boksen (samme miljø som produksjon kjører i).
