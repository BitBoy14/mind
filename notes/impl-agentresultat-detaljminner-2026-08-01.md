# Implementasjon: fulle agentresultater som detaljminner (2026-08-01)

## Oppdrag
Når en agentoppgave fullføres skal FULLE resultatet automatisk lagres som et
detaljminne i MongoDB (`memory_details`, samme skjema som `opprett_detalj`/
`komprimer_seksjon` allerede bruker), med tittel som refererer agentoppgavens
tittel og task-id. Den trunkerte versjonen i hendelsesloggen (`events`) skal
få med en referanse til detaljminnets id.

## Endrede filer

### `core/mind/memory.py`
Lagt til en offentlig funksjon `add_detail(title, content, source="agent",
section_id=None)` som er en tynn wrapper rundt den eksisterende private
`_new_detail(...)`. Ingen endring i `_new_detail` eller `memory_details`-
skjemaet (title, content, tokens, created_ts, source, section_id) – kun en
offentlig inngang slik at andre moduler (agents.py) ikke trenger å kalle en
understreks-prefikset "privat" funksjon på tvers av moduler (ingen andre
steder i kodebasen gjør det – fulgte eksisterende konvensjon).

### `core/mind/agents.py`
- Importerer nå `memory` (`from . import brain, config, db, memory, prompts`).
- Ny konstant `MAX_DETAIL_CHARS = 500_000` (langt under MongoDBs
  16 MB BSON-dokumentgrense) som sikkerhetstak mot svært store resultater.
- I `run_task()`, rett etter at oppgaven markeres `done`:
  - Hvis `result` er ikke-tomt: oppretter et detaljminne via
    `memory.add_detail(f"Agentresultat: {task['title']} [{tid}]", full,
    source="agent")`. `full` er hele resultatet, avkortet til
    `MAX_DETAIL_CHARS` tegn med en tydelig avkortingsnotis på slutten hvis
    det faktisk overskrider grensen (i praksis skjer dette nesten aldri –
    agentresultater er typisk noen KB).
  - Hvis `result` er tomt (`""`/`None`): ingen detaljminne opprettes
    (håndterer tom-case eksplisitt, ingen tomme detaljminner søles ut).
  - `db.log_event("agent_done", ..., payload, priority=2)` – `payload` er
    identisk med før (`task_id`, `resultat` trunkert til 1500 tegn, `filer`),
    men får nå i tillegg `detalj_id` (streng) når et detaljminne ble
    opprettet, slik at hovedhjernen kan slå opp fullversjonen via
    detaljminnets `_id` i `memory_details`.
- `agent_failed`-stien er UENDRET (feilede oppgaver har ikke noe "resultat" å
  lagre – kun feilteksten, som allerede er kort).

## Diff-oppsummering
```
core/mind/memory.py  | +5 linjer (ny add_detail-wrapper)
core/mind/agents.py  | +1 import (memory), +2 (MAX_DETAIL_CHARS-konstant),
                       ~15 linjer endret/lagt til i run_task() sin "done"-gren
```

## Hvordan verifisere
1. Syntakssjekk: `core/venv/bin/python -m py_compile core/mind/agents.py core/mind/memory.py` → OK (kjørt).
2. Importtest uten sirkulær avhengighet:
   `core/venv/bin/python -c "import mind.agents, mind.memory"` fra `core/` → OK (kjørt).
3. Funksjonell verifisering i drift (krever kjørende daemon + Mongo):
   - Opprett en agentoppgave, la den fullføre.
   - Sjekk `db.agent_tasks` – uendret oppførsel (`result` fortsatt trunkert
     til siste 8000 tegn som før).
   - Sjekk `db.memory_details` – nytt dokument med
     `title = "Agentresultat: <tittel> [<task_id>]"`, `content` = fullt
     resultat, `source = "agent"`, `section_id = null`.
   - Sjekk `db.events` for `type = "agent_done"` – `payload.detalj_id`
     inneholder samme id som det nye `memory_details`-dokumentets `_id`.
   - Test tom-case: en oppgave hvor agenten ikke returnerer noe resultat
     (f.eks. feilende `text_only`-gren med tomt svar) skal IKKE opprette
     noe detaljminne, og `payload` skal ikke inneholde `detalj_id`.

## Ingen andre endringer
Ingen endring i `agent_failed`-flyten, dashbord/API (`api/*.php`), skjema for
eksisterende detaljminner, eller andre moduler. Fant ingen automatiserte
tester i repoet å kjøre (`find . -iname "test*"` uten treff utenom venv).
