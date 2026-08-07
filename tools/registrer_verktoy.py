#!/var/www/www.shrtct.site/mind/core/venv/bin/python
"""Registrer et verktøy MIND har bygget, slik at det vises i dashbordet.

Verktøymodulen i dashbordet leser samlingen 'tools' i MIND-basen. Bygger du
noe som skal leve videre – et script, en tjeneste, en cron-jobb – er dette
veien inn i listen. Uten den finnes verktøyet bare på disk, og neste agent
(eller neste måned) vet ikke at det er der.

Upsert på navn: kjører du kommandoen på nytt for et verktøy som allerede står
i listen, RETTES raden. Opprettet-datoen settes kun første gang – den
beskriver verktøyet, ikke sist noen rørte raden.

Bruk:
  tools/registrer_verktoy.py liste
  tools/registrer_verktoy.py liste --json
  tools/registrer_verktoy.py registrer \\
      --navn mind-mail \\
      --stack "Python 3 (stdlib), CLI" \\
      --sti /opt/mind-mail \\
      --gjor "Oppretter engangs-innbokser og leser e-post via mail.tm" \\
      --hvorfor "MIND trengte å kunne motta verifiseringsmail selv" \\
      --opprettet 2026-08-08 \\
      --status "under bygging"
  tools/registrer_verktoy.py fjern --navn mind-mail

Statuser: under bygging | i drift | prototyp | pauset | avviklet
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from mind import db  # noqa: E402


def _gyldig_dato(s):
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("dato må være YYYY-MM-DD, ikke %r" % s)
    return s


def cmd_registrer(a):
    doc = db.register_tool(
        name=a.navn, stack=a.stack, path=a.sti, does=a.gjor, why=a.hvorfor,
        created=a.opprettet, status=a.status, registered_by=a.av)
    if not os.path.exists(doc["path"]):
        # Ikke en feil: en sti kan peke på noe som ennå ikke er skrevet, eller
        # på en maskin agenten ikke ser. Men den skal ikke passere ubemerket.
        print("ADVARSEL: stien %s finnes ikke på disk akkurat nå." % doc["path"],
              file=sys.stderr)
    print("Registrert: %s (%s) – %s" % (doc["name"], doc["status"], doc["path"]))


def cmd_liste(a):
    rader = db.list_tools()
    if a.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "_id"}
                          for r in rader], ensure_ascii=False, indent=2))
        return
    if not rader:
        print("Ingen verktøy registrert ennå.")
        return
    for r in rader:
        print("%-18s %-14s %s" % (r["name"], r["status"], r["path"]))
        print("   stack:   %s" % r["stack"])
        print("   gjør:    %s" % r["does"])
        print("   hvorfor: %s" % r["why"])
        print("   opprettet %s" % r.get("created", "?"))


def cmd_fjern(a):
    print("Fjernet: %s" % a.navn if db.remove_tool(a.navn)
          else "Fant ingen rad med navn %s" % a.navn)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="kommando", required=True)

    r = sub.add_parser("registrer", help="legg til eller oppdater et verktøy")
    r.add_argument("--navn", required=True)
    r.add_argument("--stack", required=True, help="teknologi, f.eks. 'Python 3 + cron'")
    r.add_argument("--sti", required=True, help="hvor det ligger på disk")
    r.add_argument("--gjor", required=True, help="hva verktøyet gjør")
    r.add_argument("--hvorfor", required=True, help="hvorfor det ble laget")
    r.add_argument("--opprettet", required=True, type=_gyldig_dato,
                   help="YYYY-MM-DD")
    r.add_argument("--status", default="i drift", choices=list(db.TOOL_STATUSES))
    r.add_argument("--av", default="agent", help="hvem som registrerte raden")
    r.set_defaults(func=cmd_registrer)

    l = sub.add_parser("liste", help="vis registrerte verktøy")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_liste)

    f = sub.add_parser("fjern", help="fjern en rad")
    f.add_argument("--navn", required=True)
    f.set_defaults(func=cmd_fjern)

    a = p.parse_args()
    try:
        a.func(a)
    except ValueError as e:
        print("FEIL: %s" % e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
