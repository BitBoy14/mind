# MIND – arkitekturanalyse (2026-08-01)

Kartlegging av kodebasen i `/var/www/www.shrtct.site/mind` (git HEAD `0c3b199`,
~1670 linjer Python + ~830 linjer PHP). Ingen kode er endret – kun lesing.

## a) Arkitekturoversikt

**Prosesser:**
- `mind.service` (systemd, bruker `mads`) kjører `core/venv/bin/python -m mind.daemon`.
  Restart-policy gjenoppretter alt fra MongoDB (`db=mind`) – ingen tilstand i prosessminne
  overlever en restart uendret.
- PHP 8.1-dashbord (`index.php` + `lib.php` + `api/*.php`) er et helt separat, passordbeskyttet
  polling-UI. Det snakker rått med MongoDB via `ext-mongodb` (ingen composer/ODM) og deler kun
  `/etc/mind/enc_key` (AES-256-CBC) med Python-siden for secrets.

**`daemon.py::main()` starter tre tråder:**
1. **Hjerteslaget** (hovedtråden, `heartbeat()`) – nivå-1-loopen.
2. **`responder.loop`** – rask chat-frontlinje.
3. **`agents.manager_loop`** – agent-dispatcher.

**Hjerteslaget (`pulse.py` + `heartbeat()` i `daemon.py`):**
Adaptiv rytme 10s → 30s → 60s → 300s (`config.PULSE_STEPS`), nullstilt til 10s av enhver ny
hendelse. Hvert pulsslag henter uprosesserte `events`. Mekaniske regler i `pulse.decide()`
vekker hovedhjernen umiddelbart for høyprioritetstyper (`agent_done`, `comment`,
`admin_decision`, …); ellers avgjør et billig Haiku-kall («puls-vakten») om det er verdt å
vekke. Ved LLM-feil vekkes hovedhjernen alltid («bedre én syklus for mye enn tapt info»).
En tvungen syklus kjøres minst hvert `FORCE_CYCLE_EVERY_N_PULSES` (6) pulsslag selv uten
hendelser, pluss en planlagt «tanke-økt» hver 30. min i stillhet og én daglig «natt-økt»
(grundig minnekuratering, kl. 03 som standard).

**Hovedhjerne-syklusen (`cycle.py::run_cycle`)**: Observér → Husk → Tenk → Handle → Kurér →
Forbedre → Planlegg. `_build_call()` setter sammen system-blokker (identitet+kontrakt, deretter
minneindeks – stabile først for cache) og en user-prompt med klokkeslett, arbeidsnotat, nye
hendelser, chat-hale, agentstatus, ventende admin-forslag og evt. Jarvis-status. Modellen svarer
med ett JSON-objekt (kontrakten i `prompts.BRAIN_CYCLE_CONTRACT`); hvis den ber om flere
minneseksjoner (`onskede_seksjoner`) gjøres ett oppfølgingskall. `_apply_result()` effektuerer:
logger tanker, poster ev. chatmelding, kjører minne-operasjoner, oppretter/avbryter
agentoppgaver, legger admin-forslag, lagrer arbeidsnotat og stagnasjonsflagg.

**Motor-abstraksjonen (`brain.py::brain_call`)** er inngangspunktet for *alle* LLM-kall
(rolle: brain/agent/responder/pulse). To motorer bak samme grensesnitt: Motor A (`api`,
offisiell Anthropic SDK m/ prompt-caching og server-side fallback for Fable-modeller) og
Motor B (`claude_code`, headless `claude -p --output-format json` som subprosess – standard).
Eksponentiell backoff (20s → 900s) ved rate limit/overlast; hver kall token-logges til
`tokens`-samlingen.

**Agenter (`agents.py`)**: `manager_loop` plukker køede `agent_tasks` og kjører dem parallelt i
egne tråder (tak = `max_parallel_agents`, default 8) i egen arbeidskatalog
`agentwork/<task_id>/`. Byggeoppgaver kjøres som `claude -p --dangerously-skip-permissions`
(fullt verktøytilgang i arbeidskatalogen); rene tekstoppgaver (`skriv`/`analyser`/`undersok`)
kan i stedet gå via Motor A som et ren tekst-kall. Resultatet postes tilbake som en `agent_done`/
`agent_failed`-hendelse som hjerteslaget plukker opp neste pulsslag (se punkt c).
`requeue_orphans()` setter `running`→`queued` ved oppstart, slik at oppgaver som var i gang ved
en daemon-restart tas opp igjen.

**Responderen (`responder.py`)** er en egen, rask sti: svarer *umiddelbart* (hvert sekund
sjekkes `unanswered_user_messages`) med minneindeks + relevante seksjoner + siste 20
meldinger – uavhengig av hovedhjerne-syklusen. Brukermeldingen ligger *også* som en
`chat_msg`-hendelse, så hovedhjernen kan supplere/korrigere/sette agenter i sving i neste
syklus. To uavhengige lesere av samme minnehierarki (responder og hovedhjerne).

**Minnehierarkiet (`memory.py`, §4)**: fire nivåer – arbeidsminne (bygges per kall: kompakt
indeks + `select_relevant()`-utvalgte seksjoner), hovedminne (`memory_main`, hardt tak
150 000 tokens), detaljminner (`memory_details`, «bøkene», ubegrenset) og Arkivet
(`memory_archive`, ubegrenset, søkbart). `select_relevant()` er nøkkelord-scoring (regex på
ord ≥4 tegn) + viktighetsboost; seksjoner med viktighet ≥9 tas alltid med. Hovedhjernen styrer
alt via `minne_ops` i JSON-kontrakten (opprett/oppdater/tilføy/sett_viktighet/opprett_detalj/
komprimer/arkiver) – ingenting slettes for godt, kun flyttes i hierarkiet.

**Admin-forslag**: hovedhjernen kan foreslå prompt-/kode-/arkitektur-/ressursendringer
(`admin_forslag` i kontrakten → `admin_proposals`-samlingen). Dashbordet
(`api/action.php::proposal_decide`) lar brukeren godkjenne/avvise; godkjente prompt-typer
skrives umiddelbart til `prompts`-samlingen og overstyrer `prompts.py::DEFAULT_PROMPTS` via
`prompts.get()`. Selve *kode*-forslag har ingen automatisert utrulling – de er bare tekst til
brukeren (evt. til en agentoppgave brukeren selv oppretter).

**Jarvis-kobling (`jarvis_link.py`)**: helt av by default. Når bryteren er på, leser den
status fra et søster-prosjekts (`jarvis`) MongoDB-database og kan legge idé-forslag i dets kø
via samme skjema som Jarvis' egen ideation. Full separasjon når av.

## b) Datamodell (MongoDB, db `mind`)

| Samling | Nøkkelfelter |
|---|---|
| `settings` (singleton `_id:"main"`) | `engine`, `*_model` (brain/agent/responder/pulse), `running`, `jarvis_link`, `chat_epoch`, `max_parallel_agents`, `night_curation_hour`, `token_reset_ts`, `models_cache` |
| `state` (singleton) | `working_note`, `pulse_interval`, `last_pulse_ts`, `last_cycle_ts`, `last_think_ts`, `last_curation_day`, `pulses_since_cycle`, `stagnation`, `resources` |
| `events` | `ts`, `type`, `text`, `payload`, `priority` (1=høyest), `processed` |
| `chat` | `ts`, `role` (user/responder/brain/system), `text`, `marker`, `answered` |
| `thoughts` | `ts`, `text`, `kind` (ide/refleksjon/plan/bekymring/laerdom), `refs`, `comments[]` |
| `memory_main` | `title`, `content`, `tokens`, `importance` (1-10), `created_ts`, `last_used_ts`, `use_count`, `pointers[]` |
| `memory_details` | `title`, `content`, `tokens`, `created_ts`, `source`, `section_id` |
| `memory_archive` | som `memory_main` + `archived_ts`, `original_id` |
| `memory_log` | `ts`, `action`, `detail`, `actor` (kurateringslogg) |
| `agent_tasks` | `title`, `brief`, `type`, `priority`, `status`, `created_by`, `started_ts`/`finished_ts`, `result`, `assessment` (**ubrukt – satt til `None` ved opprettelse, aldri lest/skrevet noe annet sted**), `files[]`, `progress`, `workdir` |
| `tokens` | `role`, `engine`, `model`, `input`/`output`/`cache_read`/`cache_creation`, `purpose`, `ms` |
| `prompts` | `_id`=promptnøkkel, `text`, `updated_ts` (overstyrer `DEFAULT_PROMPTS`) |
| `admin_proposals` | `kind`, `title`, `body`, `payload`, `status` (pending/approved/rejected), `decided_ts` |
| `cycles` | `ts`, `kind` (normal/tanke/natt), `observations`, `decisions[]`, `raw` |

`jarvis`-databasen (separat, kun lest/skrevet når `jarvis_link=true`): `settings`, `ideas`
(`slug`, `title`, `hypothesis`, `status`, `priority`, `learnings`, …).

## c) Agentresultat → hovedhjerne: flyt og trunkering

Et agentsvar går gjennom **fire uavhengige trunkeringssteg** før hovedhjernen ser det, og de er
inkonsistente i hvilken *ende* av teksten de beholder:

1. **`agents.py::run_task`** – `db.update_task(..., result=(result or "")[-8000:], ...)`:
   det *lagrede* resultatet i `agent_tasks.result` beholder de **siste** 8000 tegnene.
2. Samtidig, i samme funksjon, `db.log_event("agent_done", ..., {"resultat": result[:1500], ...})`:
   hendelsen som faktisk **vekker hovedhjernen** i neste pulsslag bærer kun de **første**
   1500 tegnene av det samme resultatet.
3. **`cycle.py::_render_events`** – når hendelsen rendres inn i syklus-prompten, blir hele
   `payload`-dicten `str()`-et og kappet til 300 tegn (`p[:300] + "…"`). Siden dette er en
   stringifisert Python-dict (`{'task_id': ..., 'resultat': ..., 'filer': [...]}`), spises noe
   av det allerede trange 1500-tegns-budsjettet av nøkkelnavn/anførselstegn/`task_id` før selve
   agentteksten begynner å vises.
4. **`cycle.py::_render_agent_status`** – i statusoversikten over nylig ferdige oppgaver
   (brukt i *hver* syklus, ikke bare rett etter levering) vises kun `result[:200]`.

Netto effekt: agent-instruksen (`prompts.AGENT_PREAMBLE`) ber agenten avslutte med «en kort
oppsummering (maks 20 linjer)» **på slutten** av svaret – nettopp den delen som blir hardt
kuttet bort av steg 3/4 (som begge tar fra *starten*), mens steg 1 bevarer *slutten* i databasen
men det er ikke den teksten hovedhjernen faktisk leser i noen av sine to lesestier (verken
oppvåkningshendelsen eller statusoversikten). Hovedhjernen har **ingen mekanisme** for å hente
det fulle, lagrede resultatet (opptil 8000 tegn) – det finnes et `onskede_seksjoner`-felt for
minneseksjoner, men intet tilsvarende for agent-leveranser. Den fulle teksten er kun synlig for
et menneske via dashbordets `task_files`/`read_file`-endepunkter.

## d) Svakheter / teknisk gjeld

- **Trunkeringskjeden i (c)** er den klareste funksjonelle svakheten: systemet er designet
  rundt at agenter er «selvstendige arbeidere uten hovedhjernens minne» som leverer tilbake via
  hendelser – men leveransen som faktisk når frem er typisk <300 tegn av et resultat som kan
  være opptil 8000 tegn, og det er *starten*, ikke konklusjonen agenten ble bedt om å skrive.
- **Ingen automatiserte tester** finnes i repoet (verken Python `unittest`/`pytest` eller noe
  for PHP-laget). For et system som skal foreslå og potensielt kjøre egne kodeendringer via
  agenter, er dette et tynt sikkerhetsnett.
- **`--dangerously-skip-permissions` uten sti-sandboxing**: byggeagenter kjøres med
  `cwd=agentwork/<id>`, men selve Claude Code-prosessen har ikke verktøystyrt tilgangsbegrensning
  utover det – oppdragsteksten (generert av hovedhjernen, som igjen kan være påvirket av
  brukerkommentarer/hendelser) kan instruere agenten til å jobbe andre steder på serveren (slik
  plattformkode-oppdrag allerede gjør med vilje, jf. `agents.py::_full_brief`). Det finnes ingen
  ekstra bekreftelse/allow-list for hvilke stier utenfor `agentwork/` en agent får røre.
- **Nøkkelord-basert minnerelevans** (`select_relevant`) er ren ord-overlapp + viktighetsboost –
  ingen semantisk/embedding-basert søk. Fungerer greit tidlig, men vil sannsynligvis bomme på
  seksjoner formulert med andre ord enn hendelsesteksten etter hvert som hovedminnet vokser mot
  150k-taket.
- **`agent_tasks.assessment`-feltet er dødt**: satt til `None` ved opprettelse
  (`db.py::create_agent_task`), aldri lest eller skrevet noe annet sted i kodebasen.
- **Ingen logrotasjon** for `logs/daemon.log` – hverken i `deploy/mind.service` eller noe
  `logrotate.d`-oppsett funnet på serveren. Loggfilen vokser ubegrenset.
- **Passordet `REDACTED` ligger i klartekst i `lib.php`**, som er commitet til git. Fungerer for et
  enbrukersystem, men er en hardkodet credential i versjonskontroll – bør i det minste flyttes
  til `/etc/mind/` slik de andre secrets allerede er organisert.
- **`secrets.conf`-skriving uten fillås** (`lib.php::save_secret` gjør read-modify-write av hele
  JSON-filen): lavt risikonivå for én bruker, men et race hvis to innstillingslagringer skjer
  samtidig kan miste den ene endringen.
- **`requeue_orphans()` gjenoppretter kun DB-status**, ikke selve prosessen: hvis daemonen
  restartes mens en `claude -p`-agent kjører, settes oppgaven tilbake til `queued` og kjøres på
  nytt fra scratch – det finnes ingen sjekk for om den gamle subprosessen fortsatt henger igjen
  (avhengig av systemds `KillMode` kan den være reaped eller foreldreløs).

## e) Forbedringskandidater (rangert verdi/innsats)

1. **Fiks trunkering/hent-full-resultat for agentleveranser.** Gi hovedhjernen en eksplisitt
   vei til å be om det fulle, lagrede resultatet (analogt med `onskede_seksjoner` for minne),
   og gjør trunkeringen konsistent (behold *slutten*, der agentens oppsummering ligger, i alle
   visningslag – ikke bare i databaselagringen). Høy verdi: dette er kjerneflyten «agent
   leverer → hovedhjerne lærer av det», og den er i praksis sterkt informasjonstapende i dag;
   lav-middels innsats siden alt allerede lagres, det er kun lesestiene som må rettes.

2. **Legg til et minimum av automatiserte tester** for de rene, lett-testbare enhetene:
   `memory.select_relevant`/`apply_ops`, `brain._extract_json`, `cycle._apply_result`. Middels
   verdi (fanger regresjoner før de når produksjon), lav-middels innsats – ingen av disse
   krever MongoDB (kan mockes) eller LLM-kall.

3. **Innfør en eksplisitt sti-/handlings-policy for agentoppdrag** (f.eks. krev at
   plattformkode-endringer skjer i en egen branch/worktree agenten selv oppretter, eller at
   admin-forslag av type «kode» går via godkjenning før en agent faktisk får committe til
   `main`). Høy verdi sikkerhetsmessig gitt `--dangerously-skip-permissions` + et system som
   selv formulerer agentoppdrag; middels-høy innsats å designe godt uten å ødelegge
   autonomi-ambisjonen.

4. **Bytt (eller supplér) nøkkelord-scoring i `select_relevant` med embedding-basert søk**
   (f.eks. MongoDB Atlas Vector Search eller en lokal embedding-modell). Middels-høy verdi som
   vokser over tid etter hvert som hovedminnet fylles mot 150k-taket og fraseformuleringer
   varierer; middels innsats (krever embedding-pipeline ved skriving + ved spørring).

5. **Rydd opp `agent_tasks.assessment`**: enten fjern det døde feltet, eller – mer nyttig – la
   hovedhjernen faktisk fylle det ut som en kvalitetsvurdering av agentleveranser over tid
   (nyttig datagrunnlag for å lære hvilke oppdragstyper/modeller som funker). Lav innsats,
   lav-middels verdi avhengig av hvilken vei man velger.

6. **Sett opp logrotasjon for `logs/daemon.log`** (enkel `logrotate.d`-fil). Lav innsats, lav
   men reell driftsverdi – forhindrer at loggen vokser ubegrenset på en server som allerede får
   ressursvarsler ved høyt diskforbruk.

7. **Flytt dashbord-passordet ut av kildekoden** til `/etc/mind/` (samme mønster som
   `sudo_pass`/`enc_key`), i stedet for `const LOGIN_PASSWORD = 'REDACTED'` i en commitet fil. Lav
   innsats, middels verdi som generell sikkerhetshygiene.

8. **Bekreft/håndter orphan-subprosesser eksplisitt ved daemon-restart** i
   `agents.py::requeue_orphans()` – i det minste logg en advarsel om at en gjenopptatt
   oppgave kan duplisere arbeid en fortsatt kjørende `claude -p`-prosess allerede utfører.
   Lav-middels innsats, lav-middels verdi (sjeldent scenario, men kan gi forvirrende dobbeltarbeid).
