# Historikk-rensing, verifisert rent skann og første push til GitHub

Dato: 2026-08-01
Oppdrag: Fjerne det gamle hardkodede dashbord-passordet (identifisert i tidligere
skann, se `notes/setup-github-remote-2026-08-01.md`) fra git-historikken i
`/var/www/www.shrtct.site/mind`, verifisere et rent skann av den nye historikken,
og deretter gjøre første push til `github.com/BitBoy14/mind`.

**Konklusjon: fullført. Push OK.**

## 1) Backup

Full tar-backup av hele repokatalogen (inkl. `.git`) tatt FØR noen historikk ble
endret:

```
sudo tar -czf /var/backups/mind-repo-pre-filterrepo-2026-08-01.tar.gz -C /var/www/www.shrtct.site mind
sudo chmod 600 /var/backups/mind-repo-pre-filterrepo-2026-08-01.tar.gz
```

Verifisert lesbart med `sudo tar -tzf ...` (5824 oppføringer, inkl. 212 objekter
under `mind/.git/` og `mind/lib.php`). Arkivet eies av root, modus 600.

## 2) Identifisert hemmelighet

Det hardkodede passordet lå i `lib.php` som en klartekst-konstant, introdusert i
den aller første commiten og fjernet i commiten som flyttet det til
`secrets.conf`-mekanismen (`decrypt_secret(read_secrets()[...])`). Verdien er
IKKE gjengitt her eller i noen annen fil i repoet.

## 3) git filter-repo

- Installerte `git-filter-repo` (via `pip3 install git-filter-repo`, sudo).
- Laget en replace-text-fil i `/tmp` (modus 600, kun eid av kjørende bruker)
  med formatet `<gammel-verdi>==>REDACTED`.
- Kjørte `git filter-repo --replace-text <fil> --force` i repoet.
- Slettet `/tmp`-fila umiddelbart etter kjøring.
- Alle 15 commits ble skrevet om (nye hasher). Som forventet fjernet
  filter-repo alle remotes.

## 4) Skann av ny historikk (alt rent)

Kommandoer brukt:

```
git log -S'<gammel-verdi>' --all --oneline          # 0 treff
git log --all -p -- lib.php | grep -c REDACTED       # 2 treff (forventet — de to
                                                       # stedene konstanten tidligere sto)

git rev-list --all | xargs -I{} git grep -Iln -E \
  'BEGIN (RSA|OPENSSH|PRIVATE) KEY|mongodb://[^/]*:[^/]*@|postgres://[^/]*:[^/]*@|
   mysql://[^/]*:[^/]*@|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]+|
   sk-[A-Za-z0-9]{20,}' {} -- ':!notes/*'              # 0 treff

git rev-list --all | xargs -I{} git grep -I -n -i -E \
  'password|passwd|secret|api[_-]?key|token' {} -- ':!notes/*'
  # 1946 treff totalt, alle gjennomgått. Alle er ufarlige: filnavn/stier
  # (secrets.conf), funksjonsnavn (encrypt_secret/decrypt_secret/read_secrets),
  # LLM-token-telling i UI/minne, HTML `type="password"`-attributt, og en
  # variabelbasert (ikke literal) API-nøkkel-header i api/action.php.
```

**Skannet er rent.** Diff av de 5 nyeste commitene (fiks + påfølgende arbeid)
ble også gjennomgått separat og inneholder ingen nye hemmeligheter.

## 5) Remote og push

- `notes/setup-github-remote-2026-08-01.md` beskrev målet
  `https://github.com/BitBoy14/mind`, men ingen HTTPS-credential var
  tilgjengelig (ingen `gh`, ingen `~/.git-credentials`).
- Fant en fungerende SSH-nøkkel (`~/.ssh/id_ed25519`) allerede autentisert mot
  GitHub som `BitBoy14` (`ssh -T git@github.com` → "Hi BitBoy14!"). Brukte
  derfor `git@github.com:BitBoy14/mind.git` som origin (samme repo, SSH i
  stedet for HTTPS, siden det var den eneste tilgjengelige autentiseringen).
- Bekreftet at remote var tomt (`git ls-remote origin` → ingen refs) før push.
- `git push -u origin master` → OK, ny branch opprettet på remote.
- Verifisert at `git rev-parse HEAD` og `git ls-remote origin master` er
  identiske etter push.

## Nye commit-hasher (etter filter-repo, HEAD først)

```
07a45b3 Leveransenotat for ørkentema-endringen (commit 02a3b4d)
02a3b4d Ørkentema: varme sand-/jordtoner + SVG-ikoner i dashbordet
3dfac54 Flytt innloggingspassord fra hardkodet konstant til secrets.conf
b772f87 Leveransenotat for agentverktoy-forbedring (commit 0c31633)
0c31633 Kraftigere kodeverktøy for agenter: presis redigering + screenshot-verktøy
8b71c55 Rapport: sikkerhetsskann av historikk før GitHub-push - PUSH BLOKKERT
d11d2c4 Verifikasjonsrapport for commit 296e313 (secrets.conf-herding)
0f36eab Leveransenotat for h2-kontrast-endring (commit d41e08f)
d41e08f Tydeligere h2-overskrifter i dashbordet (lys bakgrunn, mørk tekst)
bda5142 Leveransenotat for secrets.conf-herding (commit 296e313)
296e313 Herding av secrets.conf: fillås mot samtidig skriving, strenge rettigheter
d513439 Legg til verifikasjonsrapport for commit 61fec27 (agentresultater)
61fec27 Agentresultater lagres fullt som detaljminner (memory_details)
5e870b5 Dashbord (PHP), API-endepunkter, nginx-blokkering, systemd-service
e48d16d Grunnmur: Python-kjerne (motorabstraksjon, minnehierarki, hjerteslag)
```

## Viktig merknad om passordet

Det gamle passordet må anses kompromittert (det lå i klartekst i lokal
historikk beregnet for et snart-offentlig repo, selv om det aldri nådde
GitHub). Passordbytte var allerede initiert i et parallelt oppdrag
(`notes/impl-passordrotasjon-2026-08-01.md`, ikke committet ennå da dette
oppdraget ble utført) — anbefaler å fullføre og committe den rotasjonen
uavhengig av denne rensingen.
