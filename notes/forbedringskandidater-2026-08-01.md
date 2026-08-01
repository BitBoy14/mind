# Forbedringskandidater – ekstrahert fra arkitektur-analyse-2026-08-01.md

Kilde: `notes/arkitektur-analyse-2026-08-01.md`, seksjon d) og e). Ingen kode endret.

1. **Fiks trunkering/hent-full-resultat for agentleveranser** – hovedhjernen ser i dag <300
   tegn (fra *starten*) av et resultat som kan være 8000 tegn, aldri agentens konklusjon på
   slutten; gi en `onskede_seksjoner`-analog vei til fullt resultat + konsistent trunkering.
   Kompleksitet: lav-middels.
2. **Legg til automatiserte tester** for `memory.select_relevant`/`apply_ops`,
   `brain._extract_json`, `cycle._apply_result` – null tester i dag, disse enhetene krever
   verken MongoDB eller LLM. Kompleksitet: lav-middels.
3. **Innfør sti-/handlings-policy for agentoppdrag** – `--dangerously-skip-permissions` uten
   sandboxing lar agentoppdrag (formulert av hovedhjernen selv) instruere agenter til å røre
   filer utenfor `agentwork/`; krev egen branch/worktree eller godkjenning for kode-endringer.
   Kompleksitet: middels-høy.
4. **Bytt/supplér nøkkelord-scoring i `select_relevant` med embedding-søk** – ren ord-overlapp
   vil bomme mer etter hvert som `memory_main` vokser mot 150k-taket og fraseformuleringer
   varierer. Kompleksitet: middels.
5. **Rydd opp `agent_tasks.assessment`** – dødt felt, satt til `None` og aldri lest/skrevet;
   enten fjern det eller la hovedhjernen faktisk fylle det som kvalitetsvurdering over tid.
   Kompleksitet: lav.
6. **Sett opp logrotasjon for `logs/daemon.log`** – ingen `logrotate.d`-oppsett funnet, loggen
   vokser ubegrenset. Kompleksitet: lav.
7. **Flytt dashbord-passordet (`LOGIN_PASSWORD = 'REDACTED'`) ut av kildekoden** til `/etc/mind/`,
   samme mønster som `sudo_pass`/`enc_key` – i dag hardkodet og commitet i klartekst.
   Kompleksitet: lav.
8. **Legg til fillås rundt `secrets.conf`-skriving** (`lib.php::save_secret` gjør read-modify-
   write uten lås) – lav risiko i dag for én bruker, men race kan miste en samtidig endring.
   Kompleksitet: lav.
9. **Håndter orphan-subprosesser eksplisitt ved daemon-restart** i
   `agents.py::requeue_orphans()` – kun DB-status gjenopprettes (`running`→`queued`), ikke
   selve prosessen; minimum logg en advarsel om mulig dobbeltarbeid. Kompleksitet: lav-middels.
