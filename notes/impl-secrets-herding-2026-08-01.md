# Implementert: Herding av secrets.conf (fillås og strenge rettigheter)

**Commit:** `55c81fc1b9f0f355dbf7508cf6048a226a979708`
**Kandidat:** forbedringskandidat #8 i `notes/forbedringskandidater-2026-08-01.md`
(«Legg til fillås rundt secrets.conf-skriving»), utvidet av oppdraget til også
å dekke filrettigheter og git-sporing.

## Hva ble gjort

1. **Fillås** (`lib.php`):
   - `save_secret()` gjorde tidligere read-modify-write uten lås (race:
     to samtidige lagringer kunne miste hverandres endring). Nå åpnes
     filen én gang og hele les-endre-skriv-operasjonen kjører under
     eksklusiv `flock(LOCK_EX)`.
   - Ny `read_secrets()`-hjelpefunksjon leser med delt lås (`LOCK_SH`) –
     en eksklusiv skrivelås er verdiløs hvis lesere ikke respekterer den,
     så `secret_is_set()` og `api/action.php::refresh_models()` bruker nå
     samme funksjon i stedet for å lese filen rått hver for seg.

2. **Filrettigheter** (`/etc/mind/secrets.conf`):
   - Satt/bekreftet eksplisitt til **0660** (eier `mads` rw, gruppe
     `www-data` rw, «andre» ingen tilgang), eier `mads:www-data`.
   - **0600 slik oppdraget ba om var ikke mulig uten å ødelegge
     funksjonalitet**, og er derfor bevisst IKKE gjort: MIND-daemonen
     kjører som systembruker `mads` (jf. `deploy/mind.service`), mens
     PHP-dashbordet kjører som `www-data` via en delt php-fpm-pool som
     betjener *alle* nettsteder på maskinen (`/etc/php/8.1/fpm/pool.d/www.conf`).
     To ulike Unix-kontoer må begge kunne lese/skrive filen (dashbordets
     «lagre API-nøkkel» og innloggingens modell-oppdatering skriver/leser
     via `www-data`; daemonen leser via `mads`). Med 0600 og eier `mads`
     ville `www-data`-prosessene mistet all tilgang og dashbordet sluttet
     å fungere.
   - Vurderte og forkastet POSIX-ACL (`setfacl -m u:www-data:rw` + `chmod 600`)
     som mellomløsning: `www-data`-gruppa inneholder i praksis kun
     tjenestekontoen `www-data` selv og eieren `mads` (`getent group
     www-data` → `www-data:x:33:mads`), så en ACL for brukeren `www-data`
     gir *nøyaktig* samme eksponering som gruppebiten allerede gjør – ingen
     reell sikkerhetsgevinst. I tillegg gjør Linux' ACL-maske at enkle
     `stat()`-baserte rettighetssjekker (både i PHP og Python) feilrapporterer
     gruppebiten, noe som ville gjort varselet i punkt 3 upålitelig. 0660
     uten ACL er derfor den reelt strengeste og mest robuste løsningen her.
   - «Andre» hadde forøvrig allerede 0 tilgang før denne endringen (filen
     var aldri verdenslesbar).

3. **Varsel ved feilkonfigurasjon** (`lib.php::check_secrets_file_perms()` og
   `core/mind/config.py::_check_secrets_file_perms()`):
   - Kjøres ved hver lesing/skriving av `secrets.conf` (fra `read_secrets()`,
     `save_secret()` i PHP; fra `_read_secrets_file()`/`get_secret()` i Python).
   - Logger et tydelig sikkerhetsvarsel (`error_log()` i PHP,
     `logging.getLogger("mind.config").warning()` i Python → `logs/daemon.log`)
     hvis filen har videre tilgang enn 0660 – dvs. hvis «andre» har noen
     tilgang i det hele tatt, eller hvis modus avviker fra 0660 (f.eks. 664,
     666, 777, eller uventede eksekverbar-biter).
   - Merk: sjekken varsler bevisst IKKE på gruppe-tilgang alene, siden
     gruppetilgang for `www-data` er arkitektonisk påkrevd (se punkt 2).
     En bokstavelig «varsle på all gruppe/andre-tilgang»-sjekk ville gitt
     et permanent falskt varsel ved hver eneste lesing/skriving og blitt
     ignorert («cry wolf»).
   - Verifisert manuelt: `chmod 644` trigget varselet i begge språk;
     `chmod 660` er stille.

4. **Git-sporing**:
   - `secrets.conf` (den faktiske filen på `/etc/mind/secrets.conf`) ligger
     utenfor repoet (`/var/www/www.shrtct.site/mind`) og var aldri sporet
     (`git ls-files | grep -i secret` → tomt, både før og etter).
   - La likevel til `secrets.conf` i `.gitignore` som forsvar i dybden, i
     tilfelle en lokal/dev-kopi noen gang havner i repo-katalogen.

## Endrede filer

- `/var/www/www.shrtct.site/mind/lib.php` – fillås, rettighetssjekk,
  ny `read_secrets()`/`check_secrets_file_perms()`.
- `/var/www/www.shrtct.site/mind/api/action.php` – `refresh_models()` bruker
  nå `read_secrets()` i stedet for rå filles.
- `/var/www/www.shrtct.site/mind/core/mind/config.py` – delt lås ved lesing,
  rettighetssjekk (`_check_secrets_file_perms`, `_read_secrets_file`).
- `/var/www/www.shrtct.site/mind/.gitignore` – lagt til `secrets.conf`.
- Systemendring (ikke i git): `/etc/mind/secrets.conf` bekreftet/satt til
  `chmod 660`, eier `mads:www-data`; eventuell ACL fjernet igjen
  (`setfacl -b`).

## Hvordan verifisere

```bash
# Syntaks
php -l lib.php && php -l api/action.php
python3 -m py_compile core/mind/config.py

# Rettigheter (forvent 660, mads:www-data, ingen "+"/ACL)
stat -c '%a %U:%G' /etc/mind/secrets.conf
getfacl -p /etc/mind/secrets.conf   # forvent kun user::/group::/other::, ingen ekstra ACL-linjer

# Funksjonstest av lås + varsel (PHP)
cd /var/www/www.shrtct.site/mind
php -r "require 'lib.php'; var_dump(read_secrets()); save_secret('probe','x'); var_dump(secret_is_set('probe'));"
# rydd opp testverdien manuelt i /etc/mind/secrets.conf etterpå om ønskelig

# Varsel-sjekk: skru midlertidig opp rettigheter og se at varselet trigger
chmod 644 /etc/mind/secrets.conf
php -r "require 'lib.php'; check_secrets_file_perms();"   # forvent stderr-varsel
cd core && venv/bin/python -c "from mind import config; config._check_secrets_file_perms()"  # forvent WARNING
chmod 660 /etc/mind/secrets.conf   # sett tilbake

# Git-sporing
git ls-files | grep -i secret   # forvent tomt resultat
grep secrets.conf .gitignore    # forvent treff
```

Dashbordets innlogging (som kaller `refresh_models()`) og «lagre API-nøkkel»
(`save_secret()`) ble ikke funksjonstestet i nettleser i denne økten – kun
via PHP CLI mot en midlertidig kopi av `secrets.conf` (gjenopprettet etterpå).
Anbefales verifisert i dashbordet ved neste innlogging.

## Utenfor omfang / mulig oppfølging

- Å isolere MIND sitt PHP fra andre nettsteder på boksen (alle kjører i dag
  som samme `www-data`-bruker via delt php-fpm-pool) krever en egen
  php-fpm-pool med egen systembruker for MIND – større infrastrukturendring,
  ikke gjort her.
