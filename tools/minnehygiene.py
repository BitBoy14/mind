#!/var/www/www.shrtct.site/mind/core/venv/bin/python
"""Minnehygiene: engangsrydding som tåler å kjøres om igjen.

To jobber, begge idempotente:

  1. Agentduplikater ut av kunnskapsindeksen. Hvert agentsvar lagres både på
     agent_tasks.result og som detaljminne. Var teksten ordrett den samme, lå
     samme kunnskap embeddet to ganger under to etiketter, og ett semantisk
     søk kunne returnere begge som separate treff. Kopien merkes kb_index=False
     og forsvinner fra indeksen ved neste re-indeksering; originalen
     (agent_tasks) blir den ene indekserte kilden. Ingenting slettes.

     Et detaljminne merkes KUN når innholdet faktisk er en ordrett del av det
     agent_tasks lagrer. Er agentsvaret så langt at oppgavens avkortede
     `result` mangler begynnelsen, bærer detaljen mer enn originalen – da
     forblir den indeksert, ellers hadde vi gjort tekst usøkbar.

  2. Nullpunkt for brukssporingen. Detaljminner fra før use_count fantes får
     use_count=0 / last_used_ts=None, slik at «aldri hentet opp» blir et målbart
     tall i stedet for et manglende felt.

Bruk:
  tools/minnehygiene.py --dry-run     # bare mål, skriv ingenting
  tools/minnehygiene.py               # utfør
  tools/minnehygiene.py --json        # maskinlesbar oppsummering

Etter en kjøring som endret noe: /opt/mind-knowledge/reindex.sh (eller vent på
cron, som går hvert 15. minutt) for at indeksen skal speile flaggene.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from mind import db, memory  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="MIND – minnehygiene")
    ap.add_argument("--dry-run", action="store_true",
                    help="mål uten å skrive")
    ap.add_argument("--json", action="store_true",
                    help="maskinlesbar utskrift")
    args = ap.parse_args()

    d = db.db()
    for_ = {
        "detaljminner": d.memory_details.count_documents({}),
        "indekserbare_detaljer": d.memory_details.count_documents(
            memory.KB_INDEX_FILTER),
        "uten_bruksteller": d.memory_details.count_documents(
            {"use_count": {"$exists": False}}),
        "arkiv": d.memory_archive.count_documents({}),
    }
    dedup = memory.flag_agent_duplicates(dry_run=args.dry_run)
    backfill = 0 if args.dry_run else memory.backfill_detail_usage()
    etter = {
        "detaljminner": d.memory_details.count_documents({}),
        "indekserbare_detaljer": d.memory_details.count_documents(
            memory.KB_INDEX_FILTER),
        "uten_bruksteller": d.memory_details.count_documents(
            {"use_count": {"$exists": False}}),
        "arkiv": d.memory_archive.count_documents({}),
    }
    out = {"dry_run": args.dry_run, "for": for_, "dedup": dedup,
           "bruksteller_backfill": backfill, "etter": etter}

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print("MINNEHYGIENE%s" % (" (tørrkjøring – ingenting skrevet)"
                              if args.dry_run else ""))
    print("  detaljminner totalt      : %d" % etter["detaljminner"])
    print("  indekserbare før/etter   : %d -> %d"
          % (for_["indekserbare_detaljer"], etter["indekserbare_detaljer"]))
    print("  undersøkt (agentavledet) : %d" % dedup["undersokt"])
    print("  merket kb_index=False    : %d (%d tokens ut av indeksen)"
          % (dedup["flagget"], dedup["tokens_ut_av_indeks"]))
    print("  allerede merket          : %d" % dedup["allerede_flagget"])
    print("  beholdt indeksert        : %d (detaljen bærer mer enn oppgaven)"
          % dedup["beholdt_indeksert"])
    print("  uten kjent oppgave       : %d" % dedup["uten_oppgave"])
    print("  bruksteller nullstilt på : %d dokumenter (manglet feltet)"
          % backfill)
    if not args.dry_run and (dedup["flagget"] or backfill):
        print("\nKjør /opt/mind-knowledge/reindex.sh for at indeksen skal "
              "speile flaggene (cron gjør det ellers hvert 15. minutt).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
