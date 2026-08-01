# MINDs kunnskapsmotor v1 (2026-08-01)

Lokal semantisk søk over MINDs minne. Koden ligger **utenfor** dette repoet
og utenfor webroot, i `/opt/mind-knowledge/` (eier `mads:mads`, modus 0750) –
dels fordi venv-et er 1,3 GB og modellvektene 458 MB, dels fordi repoet er
offentlig på GitHub.

## Kommandoer

    /opt/mind-knowledge/search.py "spørsmål" [--top N] [--kilde SAMLING]
                                             [--min-score X] [--json]
    /opt/mind-knowledge/index.py [--full] [--json] [--quiet]
    /opt/mind-knowledge/reindex.sh        # cron-vennlig delta-indeksering

`search.py` tar flere spørsmål i én kjøring; de deler én modell-lasting
(~10 s), mens selve søket tar 0,03 s. Utdata er alltid korte destillater:
tittel, `samling:dokument-id`, 1–3 setninger, score – aldri fulle dokumenter.

## Hva som indekseres

`memory_main`, `memory_details`, `memory_archive` (title + content) og
`agent_tasks` med status done/failed (title, brief, result, assessment).
`result`/`assessment` vektes over `brief`, så destillatet viser svaret og ikke
bestillingen. Feltlisten er en allowlist i `SOURCES` i `mind_kb.py`; alt annet
(settings, tokens, events, chat, payloads) holdes bevisst utenfor.

Hemmeligheter stanses i tre lag: feltallowlist, rekursiv feltnavn-denylist
(passord/secret/token/api_key/`_enc`/sudo/private_key) og verdiskrubbing av
nøkler, PEM, JWT, `NØKKEL=verdi` og lange hex-/base64-blokker. Skrubbingen
kjøres både ved indeksering og ved utskrift.

## Delta-indeksering

`index/state.json` holder sha256 per dokument over (pipeline-versjon +
modellnavn + tittel + innhold). Kun endrede dokumenter re-embeddes; slettede
faller ut. Ved endret skrubbing/chunking/modell bumpes `PIPELINE_VERSION`, som
tvinger full re-indeksering. Målt: full 20,6 s, uendret kjøring 0,3 s.

Modell: `paraphrase-multilingual-MiniLM-L12-v2` – minnet er norsk, og den
engelske `all-MiniLM-L6-v2` traff dårlig. Ingen API-kall, ingen kostnad.

## Status og neste steg

Full indeksering kjørt (55 dokumenter / 324 biter). Testsuite: 29 sjekker, 0
feil. Cron er **ikke** installert – foreslått `*/15 * * * * /opt/mind-knowledge/reindex.sh`.

Sikkerhetsrydding som gjenstår: to `agent_tasks`-dokumenter
(`6a6dea91c78017879c84afe7` felt `result`, `6a6dec98c78017879c84b028` felt
`brief`) inneholder det gamle – allerede roterte – innloggingspassordet i
klartekst i Mongo. Kunnskapsmotoren maskerer det, men dokumentene bør saneres.
