# Verifikasjonsrapport: secrets.conf-herding (commit 55c81fc)

**Verifisert av:** uavhengig verifikasjonsagent (ingen kodeendringer gjort)
**Dato:** 2026-08-01
**Verifisert commit:** `55c81fc1b9f0f355dbf7508cf6048a226a979708`
**Leveransenotat verifisert mot:** `notes/impl-secrets-herding-2026-08-01.md` (commit `4230376`)

## Konklusjon

**OK** – med ett moderat funn anbefalt til oppfølging (ikke blokkerende).

- Fillås (flock) rundt `save_secret()`, `read_secrets()`/`_read_secrets_file()` er korrekt implementert i både PHP og Python, og alle lesere (`secret_is_set()`, `api/action.php::refresh_models()`, `get_secret()`) er konsolidert til å bruke de nye, låste funksjonene – ingen gjenværende ulåst filtilgang funnet.
- Rettighetene på `/etc/mind/secrets.conf` er **faktisk anvendt på disk**, ikke bare i kode: `660 mads:www-data`, ingen ACL. Dette stemmer eksakt med leveransenotatets påstander.
- Alle endrede PHP-filer består `php -l`. `core/mind/config.py` består `python3 -m py_compile`.
- Ett moderat robusthetsfunn: `read_secrets()` i `lib.php` bruker `fopen(SECRETS_FILE, 'c+')`, som **oppretter filen** dersom den ikke finnes – dette er en utilsiktet skrive-side-effekt av en lese-operasjon (se detaljer under punkt 4). Ikke en regresjon mot dagens faktiske tilstand (filen finnes), men en latent svakhet som bør rettes.

## 1) Vurdering av diff (`git show 55c81fc`)

Endrede filer: `.gitignore`, `api/action.php`, `core/mind/config.py`, `lib.php`.

**lib.php:**
- `save_secret()`: åpner filen én gang med `fopen(SECRETS_FILE, 'c+')`, tar eksklusiv lås (`LOCK_EX`, blokkerende – ingen `LOCK_NB` som kunne gitt spinning/tapte oppdateringer), leser gjeldende innhold via `stream_get_contents()`, endrer, `ftruncate(0)` + `rewind()` + `fwrite()` + `fflush()`, låser opp, lukker. Hele read-modify-write-syklusen skjer **innenfor** lås-vinduet → ingen race mellom to samtidige `save_secret()`-kall. Feilhåndtering: kaster `RuntimeException` hvis `fopen` eller `flock` feiler, i stedet for å feile stille.
- `read_secrets()`: ny funksjon, delt lås (`LOCK_SH`) rundt lesing. Brukes nå av `secret_is_set()` og `api/action.php::refresh_models()` – dette er riktig og viktig, siden en eksklusiv skrivelås er verdiløs hvis lesere ikke respekterer den. Verifisert ved grep (se punkt 4) at ingen gjenværende steder leser filen rått.
- `check_secrets_file_perms()`: kjøres ved hver lesing/skriving, logger til `error_log()` hvis modus er videre enn 0660. Logikken (`($mode & 0007) !== 0 || ($mode & ~0660) !== 0`) er korrekt: fanger opp både "andre har tilgang" og uventede biter (f.eks. exec-bit, setuid).
- Ingen død kode observert – alle nye funksjoner (`check_secrets_file_perms`, `read_secrets`) er faktisk i bruk.

**core/mind/config.py:** Samme mønster som PHP – `_check_secrets_file_perms()` og `_read_secrets_file()` med `fcntl.flock(LOCK_SH)`/`LOCK_UN` i `try/finally`, korrekt. `_read_secrets_file()` bruker `open(SECRETS_FILE)` (lesemodus, ikke `'c+'` eller tilsvarende) – oppretter **ikke** filen ved manglende fil, kaster `FileNotFoundError` (arver `OSError`) som fanges og gir `None`. Dette er den robuste varianten (se kontrast med PHP-funnet under).

**api/action.php:** `refresh_models()` byttet fra rå `file_get_contents(SECRETS_FILE)` til `read_secrets()` – konsistent med skrivelåsen, korrekt endring.

**.gitignore:** `secrets.conf` lagt til som forsvar i dybden. Bekreftet at filen aldri har vært sporet i git-historikken (se punkt 5).

Vurdering: fillås er korrekt og robust implementert på skrivesiden i begge språk, og på lesesiden i Python. Se punkt 4 for ett unntak på PHP-lesesiden.

## 2) `php -l` på endrede PHP-filer

```
$ php -l lib.php
No syntax errors detected in lib.php
$ php -l api/action.php
No syntax errors detected in api/action.php
$ python3 -m py_compile core/mind/config.py
(ingen output = OK)
```

Ingen syntaksfeil.

## 3) Faktisk tilstand på disk

```
$ ls -l /etc/mind/secrets.conf
-rw-rw---- 1 mads www-data 3 aug.  1 14:40 /etc/mind/secrets.conf

$ stat -c '%a %U:%G %n' /etc/mind/secrets.conf
660 mads:www-data /etc/mind/secrets.conf

$ getfacl -p /etc/mind/secrets.conf
user::rw-
group::rw-
other::---
(ingen ekstra ACL-linjer)

$ getent group www-data
www-data:x:33:mads
```

Innhold: `{}` (tom, ingen secrets lagret p.t. – ufarlig å vise).

Dette **stemmer eksakt** med leveransenotatets påstand om `660`, eier `mads:www-data`, ingen ACL. Notatet argumenterer eksplisitt for at `0660` (ikke `0600`, som var forventningen i oppdragsbeskrivelsen) er det reelle sikkerhetsmålet fordi daemonen (bruker `mads`) og php-fpm (bruker `www-data`, delt pool for alle vhost på boksen) begge må ha tilgang, og at `www-data`-gruppa kun inneholder `www-data` og `mads` (bekreftet over via `getent group`). Dette er en velbegrunnet og korrekt avveining – IKKE en svakere herding enn påstått, gitt de reelle systemkravene. `other` har uansett 0 tilgang, som var kjernekravet.

`/etc/mind`-katalogen: `drwxr-x--- root:www-data` – `www-data` har `rwx` på katalognivå (relevant for punkt 4).

## 4) Regresjonssjekk – hvor leses/skrives secrets.conf

```
$ grep -rn "secrets\.conf\|SECRETS_FILE" --include="*.php" --include="*.py" .
lib.php:10:const SECRETS_FILE = '/etc/mind/secrets.conf';
lib.php: check_secrets_file_perms(), read_secrets(), save_secret() – alle bruker konstanten
core/mind/config.py:21:SECRETS_FILE = os.path.join(ETC_DIR, "secrets.conf")
core/mind/config.py: _check_secrets_file_perms(), _read_secrets_file() – bruker konstanten
```

Ingen gjenværende `file_get_contents(SECRETS_FILE)` eller `fopen(SECRETS_FILE, ...)` utenfor de nye, låste funksjonene. Alle kjente lesere (`secret_is_set()`, `refresh_models()`, `get_secret()`) går nå via låste funksjoner. Funksjonell smoke-test (read-only, ingen mutasjon av prod-filen):

```
$ php -r "require 'lib.php'; var_dump(read_secrets()); var_dump(secret_is_set('anthropic_api_key'));"
array(0) {}
bool(false)
# forventet, siden secrets.conf p.t. inneholder {}

$ python3 -c "from mind import config; print(repr(config.anthropic_api_key()))"
''
# forventet, samme årsak
```

Ingen exceptions, ingen brutt flyt – lesing fungerer logisk som før endringen, nå med lås.

**Moderat funn:** `read_secrets()` i `lib.php` bruker `fopen(SECRETS_FILE, 'c+')`. PHP-modus `c+` **oppretter filen hvis den ikke finnes** (dokumentert PHP-oppførsel, bekreftet i sandkasse: nyopprettet fil fikk `644` gitt `www-data`s reelle umask `022`). Siden `/etc/mind` er `drwxr-x---root:www-data` (www-data har skriverettighet på katalogen), *kan* php-fpm faktisk opprette filen der. Konsekvens: dersom `secrets.conf` noen gang forsvinner (feiltrykk, utilsiktet sletting, ufullstendig provisjonering ved ny installasjon), vil neste **lesing** (f.eks. `secret_is_set()` kalt fra innloggingsflyten) stille opprette en ny, tom fil med potensielt for åpne rettigheter (`644`, dvs. verdensleselig) – istedenfor å feile synlig eller matche gammel oppførsel (`@file_get_contents()` på manglende fil returnerte tidligere bare `false`, uten å opprette noe). Ekstra alvorlig: `check_secrets_file_perms()` kjøres **før** `fopen`-kallet og finner `file_exists() === false`, så funksjonen returnerer tidlig **uten varsel** akkurat i det øyeblikket filen opprettes feil – varselet trigges først ved *neste* kall. Python-siden har ikke dette problemet: `_read_secrets_file()` bruker standard lesemodus (`open(SECRETS_FILE)`), som kaster `FileNotFoundError` i stedet for å opprette filen.

Dette er ikke en aktiv regresjon akkurat nå (filen finnes med korrekte `660`-rettigheter, bekreftet i punkt 3), men svekker robusthets-/feilhåndteringspåstanden i commit-meldingen ("ingen race conditions") for dette spesifikke edge-caset. Anbefalt fiks: endre `read_secrets()` til å åpne med `'r'` (kun-lesing, ingen filopprettelse) i stedet for `'c+'`, ev. med samme try/catch-mønster som Python-siden.

## 5) Leveransenotat vs. observert virkelighet

Kryssjekket alle konkrete påstander i `notes/impl-secrets-herding-2026-08-01.md`:

| Påstand i notat | Observert | Stemmer? |
|---|---|---|
| `save_secret()` under eksklusiv `flock(LOCK_EX)` | Bekreftet i kode | Ja |
| `read_secrets()` med delt lås, brukt av `secret_is_set()` og `refresh_models()` | Bekreftet i kode og via grep | Ja |
| `/etc/mind/secrets.conf` er `0660`, eier `mads:www-data` | `stat` viser `660 mads:www-data` | Ja |
| Ingen ACL i bruk (`getfacl -p`) | Kun `user::`/`group::`/`other::`, ingen ekstra linjer | Ja |
| "Andre" hadde allerede 0 tilgang før endringen | Kan ikke verifiseres retroaktivt (ingen historikk på filsystem-nivå), men plausibelt og konsistent med nåværende `660` | Rimelig |
| Varsel trigges ved `chmod 644`, stille ved `660` | Ikke gjentestet mot prod-filen (ville krevd midlertidig å svekke rettighetene på en live secrets-fil – vurdert unødvendig risiko for en verifikasjonsagent); koden er lest og logikken (`mode & 0007 != 0 || mode & ~0660 != 0`) er korrekt for de nevnte casene | Verifisert via kodelesning, ikke re-eksekvert |
| `secrets.conf` aldri sporet i git | `git log --all --full-history -- '*secrets.conf'` → tomt resultat | Ja |
| `.gitignore` oppdatert | Bekreftet, `secrets.conf` står i `.gitignore` | Ja |
| Python-varsel havner i `logs/daemon.log` | `core/mind/daemon.py` setter `logging.basicConfig(filename=.../daemon.log, level=logging.INFO)` – `log.warning()` fra `config.py` propagerer til root-logger og skrives dit siden `WARNING > INFO` | Ja |
| Dashbord-innlogging/lagre-API-nøkkel ikke browsertestet i implementeringsøkten | Notatet er ærlig om dette selv | Ja (ærlig avgrenset) |

Alle konkrete, verifiserbare påstander i leveransenotatet stemte med det jeg observerte uavhengig. Notatets avvik fra oppdragets "typisk 600"-forventning (valgte `660` i stedet) er godt begrunnet og reflekterer faktiske systemkrav (delt php-fpm-pool på tvers av vhost, daemon kjører som annen bruker) – vurderes som korrekt teknisk beslutning, ikke et avvik fra intensjonen.

## Anbefalt oppfølging (ikke blokkerende for denne verifikasjonen)

1. Endre `read_secrets()` i `lib.php` til å åpne filen i ren lesemodus (`'r'`) i stedet for `'c+'`, slik at en lese-operasjon aldri kan opprette filen som side-effekt. Dette bringer PHP-siden i tråd med den mer robuste Python-implementasjonen.
