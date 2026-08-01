#!/var/www/www.shrtct.site/mind/core/venv/bin/python
"""Minnerapport: hva minnet består av – og hva tallene ennå ikke kan bære.

RENT LESENDE. Verktøyet teller, summerer og sammenligner; det skriver ikke ett
felt. Det er ikke en detalj: en rapport som selv rører brukstellerne, måler sin
egen kjøring. Alle kall herfra er find/count_documents, og `tests/
test_memory_report.py` sperrer skrivemetodene i lagringslaget mens rapporten
bygges, slik at et framtidig skriv faller på testen og ikke i produksjon.

Fire deler:

  1. Hovedminnet, seksjon for seksjon: viktighet, tokens, bruk – og summen mot
     taket på 150 000 tokens (config.MAIN_MEMORY_MAX_TOKENS).
  2. Detaljminnene: antall, tokens, hvordan bruken fordeler seg, hvor mange som
     er meldt ut av kunnskapsindeksen (kb_index=False), og arkivet.
  3. Kunnskapsindeksens sammensetning per kildesamling, lest rett fra
     /opt/mind-knowledge/index/rows.json – med etterslep mot det basen har nå.
  4. Vekst: dokumenter per døgn i agent_tasks, chat og events.

OBLIGATORISK VARSEL. Brukssporingen på detaljnivå er fersk (use_count/
last_used_ts kom 2026-08-02, commit 24ab11b). Er eldste bruksdatapunkt yngre enn
TYNT_GRUNNLAG_DAGER, står et varsel ØVERST i rapporten: et lavt use_count betyr
da «ikke målt ennå», ikke «ikke i bruk», og skal ikke brukes til å arkivere.
Uten det varselet ville rapporten sett ut som beslutningsgrunnlag lenge før den
er det – og den første kurateringen ville arkivert på støy.

Bruk:
  tools/memory_report.py                 # menneskelesbar tekst
  tools/memory_report.py --json          # maskinlesbar
  tools/memory_report.py --dager 14      # lengre vekstvindu
  tools/memory_report.py --index-dir ... # annen kunnskapsindeks
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from mind import config, db, memory  # noqa: E402

# Kunnskapsindeksen (mind_kb.INDEX_DIR). Samme miljøvariabel som motoren selv
# bruker, slik at et eksperimentelt indeksoppsett rapporteres på likt.
DEFAULT_INDEX_DIR = (os.environ.get("MIND_KB_INDEX_DIR")
                     or "/opt/mind-knowledge/index")

# Under denne alderen på eldste bruksdatapunkt er bruksstatistikken for fersk
# til å arkivere etter. Sju døgn er valgt fordi bruken svinger med uken: en
# seksjon som bare trengs når et bestemt arbeid pågår, kan ligge urørt i flere
# dager uten å være død.
TYNT_GRUNNLAG_DAGER = 7

# Da use_count/last_used_ts ble innført på detaljminner (commit 24ab11b,
# 2026-08-02 00:12 +0200). Måleserien kan aldri være eldre enn dette, uansett
# hva dokumentene sier – tallet står her for å kunne si det ærlig i rapporten
# også når INGEN detalj er brukt ennå og det ikke finnes et datapunkt å måle.
BRUKSSPORING_INNFORT_TS = 1785622372.0

# Samlingsfiltrene kunnskapsmotoren indekserer etter. Speiler SOURCES i
# /opt/mind-knowledge/mind_kb.py, på samme måte som memory.KB_INDEX_FILTER gjør
# det – de bor utenfor repoet og importeres bevisst ikke. Brukes kun til å
# telle hvor mange dokumenter som KVALIFISERER for indeksen nå, mot hvor mange
# som faktisk ligger der.
KB_KILDEFILTRE = {
    "memory_main": {},
    "memory_details": memory.KB_INDEX_FILTER,
    "memory_archive": memory.KB_INDEX_FILTER,
    "agent_tasks": {"status": {"$in": ["done", "ferdig", "failed", "feilet"]}},
    "chat": {},
}

# Tidsstempelet som forteller når et dokument oppsto, per samling. «hvis de
# finnes»: mangler feltet, rapporteres samlingen uten vekstkurve i stedet for å
# gjette.
VEKSTKILDER = [("agent_tasks", "created_ts"), ("chat", "ts"), ("events", "ts")]

# Bøttene use_count fordeles i. Halvåpne intervaller [fra, til).
BRUKSBOTTER = [("0 (aldri)", 0, 1), ("1", 1, 2), ("2-4", 2, 5),
               ("5-9", 5, 10), ("10+", 10, None)]


# ------------------------------------------------------------------ hjelpere

def _lagret_tokens(doc):
    """Det LAGREDE tokentallet, eller None om feltet mangler/er ubrukelig."""
    t = doc.get("tokens")
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    return int(t)


def _tokens_of(doc):
    """Dokumentets tokenanslag: det lagrede tallet når det finnes, ellers et
    friskt estimat av innholdet. Samme estimator som minnemotoren bruker."""
    t = _lagret_tokens(doc)
    return t if t and t > 0 else memory.est_tokens(doc.get("content"))


def _token_avvik(lagret, estimert):
    """Spriker det lagrede tokentallet fra innholdet slik det ser ut nå?

    Takregnskapet (memory.total_tokens) summerer de LAGREDE tallene. Er de
    feil, er ikke bare seksjonen feil målt – hele taket er det. Slingringsmonn
    på 5 % eller 20 tokens, så vanlig avrunding ikke ropes ut som avvik.
    """
    if lagret is None:
        return True
    return abs(lagret - estimert) > max(20, 0.05 * estimert)


def _tokens_av_tegn(antall_tegn):
    """Samme anslag som memory.est_tokens, uten å bygge strengen først –
    indeksen er nesten en million tegn, og de skal bare telles."""
    return int(antall_tegn / 3.5) + 1 if antall_tegn else 0


def _alder_dager(ts, now):
    if not ts:
        return None
    return (now - float(ts)) / 86400.0


def _iso(ts):
    if not ts:
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))


def _n(x):
    """Tusenskille med mellomrom – rapporten leses av et menneske."""
    return "{:,}".format(int(x)).replace(",", " ")


def _pct(del_, hel):
    return (100.0 * del_ / hel) if hel else 0.0


def _bruksbotte(n):
    for navn, fra, til in BRUKSBOTTER:
        if n >= fra and (til is None or n < til):
            return navn
    return BRUKSBOTTER[0][0]


def _dagsgrenser(now, dager):
    """[(dato_iso, start_ts, slutt_ts)] for de siste `dager` døgnene, eldste
    først. Døgnskillene følger lokal tid – rapporten leses i den tidssonen –
    og regnes fra midnatt til midnatt, ikke som 86400 sekunder, slik at et
    sommertidsskifte ikke forskyver hele kurven."""
    i_dag = datetime.fromtimestamp(now).date()
    ut = []
    for i in range(dager - 1, -1, -1):
        d0 = i_dag - timedelta(days=i)
        start = datetime.combine(d0, datetime.min.time()).timestamp()
        slutt = datetime.combine(d0 + timedelta(days=1),
                                 datetime.min.time()).timestamp()
        ut.append((d0.isoformat(), start, slutt))
    return ut


# Dokumenter der feltet mangler ELLER er null er ikke tidfestet. Begge deler
# må stå: i Mongo utelukker `$ne: null` også manglende felt, men å skrive det
# eksplisitt er det eneste som betyr det samme i begge lag.
HAR_TIDSSTEMPEL = {"$exists": True, "$ne": None}


def _ytterpunkt(d, coll, felt, retning):
    """Eldste (1) eller nyeste (-1) verdi av `felt` i samlingen, eller None."""
    doc = d[coll].find_one({felt: dict(HAR_TIDSSTEMPEL)}, {felt: 1},
                           sort=[(felt, retning)])
    return (doc or {}).get(felt)


# ------------------------------------------------------------------ 1) hovedminne

def hovedminne_rapport(d, now):
    seksjoner = []
    sum_tokens = 0
    avvik = 0
    for s in d.memory_main.find({}):
        lagret = _lagret_tokens(s)
        estimert = memory.est_tokens(s.get("content"))
        tok = _tokens_of(s)
        sum_tokens += tok
        if _token_avvik(lagret, estimert):
            avvik += 1
        seksjoner.append({
            "id": str(s["_id"]),
            "tittel": s.get("title", "?"),
            "viktighet": int(s.get("importance", 5) or 0),
            "tokens": tok,
            "tokens_lagret": lagret,
            "tokens_estimert": estimert,
            "use_count": int(s.get("use_count", 0) or 0),
            "last_used_ts": s.get("last_used_ts"),
            "sist_brukt": _iso(s.get("last_used_ts")),
            "dager_siden_bruk": _alder_dager(s.get("last_used_ts"), now),
            "opprettet": _iso(s.get("created_ts")),
            "pekere": len(s.get("pointers") or []),
        })
    seksjoner.sort(key=lambda x: (-x["viktighet"], -x["tokens"]))
    return {
        "antall": len(seksjoner),
        "sum_tokens": sum_tokens,
        "tak_tokens": config.MAIN_MEMORY_MAX_TOKENS,
        "andel_av_tak_pst": _pct(sum_tokens, config.MAIN_MEMORY_MAX_TOKENS),
        "aldri_brukt": sum(1 for s in seksjoner if not s["use_count"]),
        "token_avvik": avvik,
        "kjerneseksjoner": sum(1 for s in seksjoner
                               if s["viktighet"] >= memory.CORE_IMPORTANCE),
        "seksjoner": seksjoner,
    }


# ------------------------------------------------------------------ 2) detaljer

def detalj_rapport(d, now):
    sum_tokens = 0
    bruk = Counter()
    botter = Counter()
    uten_teller = 0
    kb_false = 0
    brukstider = []
    opprettet = []
    storste = []
    mest_brukt = []
    antall = 0
    for doc in d.memory_details.find({}):
        antall += 1
        tok = _tokens_of(doc)
        sum_tokens += tok
        if "use_count" not in doc:
            uten_teller += 1
        n = int(doc.get("use_count", 0) or 0)
        bruk[n] += 1
        botter[_bruksbotte(n)] += 1
        if doc.get("kb_index") is False:
            kb_false += 1
        if doc.get("last_used_ts"):
            brukstider.append(float(doc["last_used_ts"]))
        if doc.get("created_ts"):
            opprettet.append(float(doc["created_ts"]))
        rad = {"id": str(doc["_id"]), "tittel": doc.get("title", "?"),
               "tokens": tok, "use_count": n,
               "sist_brukt": _iso(doc.get("last_used_ts")),
               "kb_index": doc.get("kb_index") is not False,
               "kilde": doc.get("source")}
        storste.append(rad)
        if n:
            mest_brukt.append(rad)
    storste.sort(key=lambda x: -x["tokens"])
    mest_brukt.sort(key=lambda x: (-x["use_count"], -x["tokens"]))

    arkiv = list(d.memory_archive.find({}))
    arkiv_detaljer = sum(1 for a in arkiv
                         if a.get("from_collection") == "memory_details")
    return {
        "antall": antall,
        "sum_tokens": sum_tokens,
        "indekserbare": antall - kb_false,
        "kb_index_false": kb_false,
        "uten_bruksteller": uten_teller,
        "brukt_minst_en_gang": sum(v for k, v in bruk.items() if k > 0),
        "sum_bruk": sum(k * v for k, v in bruk.items()),
        "bruksfordeling": {navn: botter.get(navn, 0)
                           for navn, _, _ in BRUKSBOTTER},
        "eldste_bruk_ts": min(brukstider) if brukstider else None,
        "nyeste_bruk_ts": max(brukstider) if brukstider else None,
        "eldste_opprettet_ts": min(opprettet) if opprettet else None,
        "storste": storste[:5],
        "mest_brukt": mest_brukt[:5],
        "arkiv": {
            "antall": len(arkiv),
            "fra_detaljer": arkiv_detaljer,
            "fra_seksjoner_eller_ukjent": len(arkiv) - arkiv_detaljer,
            "sum_tokens": sum(_tokens_of(a) for a in arkiv),
            "sokbare_i_indeksen": sum(1 for a in arkiv
                                      if a.get("kb_index") is not False),
        },
    }


# -------------------------------------------------- OBLIGATORISK: tynt grunnlag

def tynt_datagrunnlag(detaljer, now):
    """Er bruksstatistikken gammel nok til å arkivere etter?

    Målet er eldste bruksdatapunkt: en serie som startet i går, sier ingenting
    om hva som er i bruk. Finnes ingen datapunkter i det hele tatt, er svaret
    like tydelig – da er ingenting målt ennå.
    """
    eldste = detaljer.get("eldste_bruk_ts")
    alder = _alder_dager(eldste, now)
    sporing_alder = max(0.0, (now - BRUKSSPORING_INNFORT_TS) / 86400.0)
    tynt = (alder is None) or (alder < TYNT_GRUNNLAG_DAGER)
    if alder is None:
        grunn = ("ingen detaljminner er registrert brukt ennå – "
                 "bruksstatistikken er tom")
    elif tynt:
        grunn = ("eldste bruksdatapunkt er %.1f døgn gammelt (grense: %d)"
                 % (alder, TYNT_GRUNNLAG_DAGER))
    else:
        grunn = ("eldste bruksdatapunkt er %.1f døgn gammelt – serien er lang "
                 "nok til å tolkes" % alder)
    return {
        "tynt": tynt,
        "grense_dager": TYNT_GRUNNLAG_DAGER,
        "eldste_datapunkt_ts": eldste,
        "eldste_datapunkt": _iso(eldste),
        "eldste_datapunkt_alder_dager": alder,
        "sporing_innfort_ts": BRUKSSPORING_INNFORT_TS,
        "sporing_innfort": _iso(BRUKSSPORING_INNFORT_TS),
        "maleserie_dager": sporing_alder,
        "brukt_minst_en_gang": detaljer.get("brukt_minst_en_gang", 0),
        "antall_detaljer": detaljer.get("antall", 0),
        "begrunnelse": grunn,
    }


# ------------------------------------------------------------------ 3) indeksen

def indeks_rapport(index_dir, d=None):
    """Kunnskapsindeksens sammensetning, lest slik motoren selv leser den
    (mind_kb.load_index: rows.json + state.json). Vektorene røres ikke – de
    sier ikke noe rapporten trenger, og er 1,5 MB å laste."""
    ut = {"katalog": index_dir, "tilgjengelig": False, "feil": None,
          "per_samling": {}, "rader": 0, "dokumenter": 0, "tilstand": {}}
    rows_path = os.path.join(index_dir, "rows.json")
    state_path = os.path.join(index_dir, "state.json")
    try:
        with open(rows_path, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError) as e:
        ut["feil"] = "%s: %s" % (type(e).__name__, e)
        return ut
    if not isinstance(rows, list):
        ut["feil"] = "rows.json er ikke en liste"
        return ut

    state = {}
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}

    per = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        coll = r.get("coll") or "?"
        p = per.setdefault(coll, {"rader": 0, "dokumenter": set(), "tegn": 0,
                                  "felt": Counter(), "eldste_ts": None,
                                  "nyeste_ts": None})
        p["rader"] += 1
        if r.get("doc_id"):
            p["dokumenter"].add(r["doc_id"])
        p["tegn"] += len(r.get("text") or "")
        p["felt"][r.get("field") or "?"] += 1
        ts = r.get("ts")
        if isinstance(ts, (int, float)) and ts:
            p["eldste_ts"] = ts if p["eldste_ts"] is None else min(p["eldste_ts"], ts)
            p["nyeste_ts"] = ts if p["nyeste_ts"] is None else max(p["nyeste_ts"], ts)

    tilstand_per = (state.get("per_collection") or {})
    samlinger = {}
    for coll, p in per.items():
        dok = len(p["dokumenter"])
        kvalifiserer = None
        if d is not None and coll in KB_KILDEFILTRE:
            kvalifiserer = d[coll].count_documents(KB_KILDEFILTRE[coll])
        samlinger[coll] = {
            "rader": p["rader"],
            "dokumenter": dok,
            "andel_rader_pst": _pct(p["rader"], len(rows)),
            "tegn": p["tegn"],
            "est_tokens": _tokens_av_tegn(p["tegn"]),
            "felt": dict(p["felt"]),
            "eldste": _iso(p["eldste_ts"]),
            "nyeste": _iso(p["nyeste_ts"]),
            "kvalifiserer_naa": kvalifiserer,
            "etterslep": (None if kvalifiserer is None else kvalifiserer - dok),
            "tilstand_dokumenter": tilstand_per.get(coll),
        }
    # Samlinger basen kvalifiserer dokumenter i, men som ikke finnes i indeksen
    # i det hele tatt, er ikke «0 rader» – de er usynlige. Ta dem med.
    if d is not None:
        for coll, filt in KB_KILDEFILTRE.items():
            if coll not in samlinger:
                kval = d[coll].count_documents(filt)
                samlinger[coll] = {
                    "rader": 0, "dokumenter": 0, "andel_rader_pst": 0.0,
                    "tegn": 0, "est_tokens": 0, "felt": {}, "eldste": None,
                    "nyeste": None, "kvalifiserer_naa": kval,
                    "etterslep": kval, "tilstand_dokumenter": tilstand_per.get(coll),
                }

    ut.update({
        "tilgjengelig": True,
        "rader": len(rows),
        "dokumenter": sum(s["dokumenter"] for s in samlinger.values()),
        "per_samling": samlinger,
        "tilstand": {
            "sist_kjort": state.get("last_run_human") or _iso(state.get("last_run_ts")),
            "sist_kjort_ts": state.get("last_run_ts"),
            "modell": state.get("model"),
            "dim": state.get("dim"),
            "docs_total": state.get("docs_total"),
            "chunks_total": state.get("chunks_total"),
            "pipeline_version": state.get("pipeline_version"),
        },
    })
    return ut


# ------------------------------------------------------------------ 4) vekst

def vekst_rapport(d, now, dager=7):
    dagsgrenser = _dagsgrenser(now, dager)
    ut = {"vindu_dager": dager, "samlinger": {}}
    for coll, felt in VEKSTKILDER:
        totalt = d[coll].count_documents({})
        med_ts = d[coll].count_documents({felt: dict(HAR_TIDSSTEMPEL)})
        rad = {"tidsstempelfelt": felt, "totalt": totalt,
               "med_tidsstempel": med_ts, "per_dag": [], "i_vinduet": 0,
               "snitt_per_dag_vindu": 0.0, "forste": None, "siste": None,
               "levetid_dager": None, "snitt_per_dag_levetid": None,
               "levetid_under_ett_dogn": False}
        if not med_ts:
            # Ingen brukbare tidsstempler: si det, ikke gjett en kurve.
            rad["per_dag"] = None
            ut["samlinger"][coll] = rad
            continue
        forste = _ytterpunkt(d, coll, felt, 1)
        siste = _ytterpunkt(d, coll, felt, -1)
        rad["forste"] = _iso(forste)
        rad["siste"] = _iso(siste)
        levetid = max(0.0, (now - float(forste)) / 86400.0) if forste else None
        rad["levetid_dager"] = levetid
        # Under ett døgn er «per døgn» en ekstrapolering, ikke en måling: 98
        # dokumenter på ti timer blir til «222 per døgn». Tallet er greit å ha,
        # men det skal merkes, ellers leses det som en observert rate.
        rad["levetid_under_ett_dogn"] = bool(levetid is not None and levetid < 1.0)
        if levetid:
            rad["snitt_per_dag_levetid"] = med_ts / max(levetid, 1.0 / 24)
        for dato, start, slutt in dagsgrenser:
            n = d[coll].count_documents({felt: {"$gte": start, "$lt": slutt}})
            rad["per_dag"].append({"dato": dato, "antall": n})
            rad["i_vinduet"] += n
        rad["snitt_per_dag_vindu"] = rad["i_vinduet"] / float(dager)
        ut["samlinger"][coll] = rad
    return ut


# ------------------------------------------------------------------ samlet

def bygg_rapport(d=None, now=None, dager=7, index_dir=DEFAULT_INDEX_DIR):
    d = db.db() if d is None else d
    now = time.time() if now is None else now
    hoved = hovedminne_rapport(d, now)
    detaljer = detalj_rapport(d, now)
    return {
        "generert_ts": now,
        "generert": _iso(now),
        "lesende": True,
        "tynt_datagrunnlag": tynt_datagrunnlag(detaljer, now),
        "hovedminne": hoved,
        "detaljminner": detaljer,
        "kunnskapsindeks": indeks_rapport(index_dir, d),
        "vekst": vekst_rapport(d, now, dager),
    }


# ------------------------------------------------------------------ tekstform

def _stor_forbokstav(s):
    return s[:1].upper() + s[1:] if s else s


def _varselblokk(t):
    if not t["tynt"]:
        return ["BRUKSSTATISTIKK: %s." % _stor_forbokstav(t["begrunnelse"]), ""]
    return [
        "=" * 72,
        "TYNT DATAGRUNNLAG – bruksstatistikken er IKKE beslutningsgrunnlag",
        "for arkivering ennå.",
        "",
        "  %s." % _stor_forbokstav(t["begrunnelse"]),
        "  Brukssporing på detaljminner ble innført %s; måleserien er %.1f døgn"
        % (t["sporing_innfort"], t["maleserie_dager"]),
        "  lang, og %d av %d detaljminner er registrert brukt."
        % (t["brukt_minst_en_gang"], t["antall_detaljer"]),
        "",
        "  Et lavt use_count betyr her IKKE MÅLT ENNÅ – ikke «ikke i bruk».",
        "  Ikke arkiver på disse tallene før serien er minst %d døgn lang."
        % t["grense_dager"],
        "=" * 72,
        "",
    ]


def _sist_brukt_kolonne(rad):
    dager = rad.get("dager_siden_bruk")
    if dager is None:
        return "aldri"
    return "%.1f d siden" % dager


def formater_tekst(rap):
    L = []
    L.append("MINNERAPPORT – MIND")
    L.append("Generert %s · kun lesende (ingenting er skrevet til databasen)"
             % rap["generert"])
    L.append("")
    L.extend(_varselblokk(rap["tynt_datagrunnlag"]))

    h = rap["hovedminne"]
    L.append("1) HOVEDMINNE (memory_main)")
    L.append("   Seksjoner        : %d (%d kjerne, viktighet >= %d)"
             % (h["antall"], h["kjerneseksjoner"], memory.CORE_IMPORTANCE))
    L.append("   Tokens           : %s av %s (%.1f %% av taket)"
             % (_n(h["sum_tokens"]), _n(h["tak_tokens"]), h["andel_av_tak_pst"]))
    L.append("   Aldri brukt      : %d seksjon(er)" % h["aldri_brukt"])
    L.append("   Token-avvik      : %d seksjon(er) der lagret `tokens` spriker "
             "fra innholdet" % h["token_avvik"])
    if h["seksjoner"]:
        L.append("")
        L.append("   vikt   tokens  brukt  sist brukt    tittel")
        L.append("   " + "-" * 66)
        for s in h["seksjoner"]:
            L.append("   %4d %8s %6d  %-13s %s"
                     % (s["viktighet"], _n(s["tokens"]), s["use_count"],
                        _sist_brukt_kolonne(s), s["tittel"][:38]))
            L.append("        [%s]  pekere: %d" % (s["id"], s["pekere"]))
    L.append("")

    dt = rap["detaljminner"]
    L.append("2) DETALJMINNER (memory_details)")
    L.append("   Antall           : %d" % dt["antall"])
    L.append("   Tokens           : %s (%.1f %% av hovedminnets tak)"
             % (_n(dt["sum_tokens"]), _pct(dt["sum_tokens"],
                                           config.MAIN_MEMORY_MAX_TOKENS)))
    L.append("   Indekserbare     : %d (kb_index=False: %d)"
             % (dt["indekserbare"], dt["kb_index_false"]))
    L.append("   Uten bruksteller : %d (mangler feltet – ikke målbare)"
             % dt["uten_bruksteller"])
    L.append("   Bruk registrert  : %d dokument(er), %d oppslag totalt"
             % (dt["brukt_minst_en_gang"], dt["sum_bruk"]))
    L.append("   use_count-fordeling:")
    for navn, _f, _t in BRUKSBOTTER:
        L.append("     %-10s %4d" % (navn, dt["bruksfordeling"].get(navn, 0)))
    if dt["mest_brukt"]:
        L.append("   Mest brukt:")
        for r in dt["mest_brukt"]:
            L.append("     %2dx  %-40s (%s tok)"
                     % (r["use_count"], r["tittel"][:40], _n(r["tokens"])))
    if dt["storste"]:
        L.append("   Størst (tokens, ikke bruk – se varselet over):")
        for r in dt["storste"]:
            L.append("     %7s tok  %-40s%s"
                     % (_n(r["tokens"]), r["tittel"][:40],
                        "" if r["kb_index"] else "  [ute av indeksen]"))
    a = dt["arkiv"]
    L.append("   Arkiv (memory_archive): %d dokument(er), %s tokens "
             "(%d fra detaljnivå, %d søkbare)"
             % (a["antall"], _n(a["sum_tokens"]), a["fra_detaljer"],
                a["sokbare_i_indeksen"]))
    L.append("")

    ix = rap["kunnskapsindeks"]
    L.append("3) KUNNSKAPSINDEKSEN (%s)" % ix["katalog"])
    if not ix["tilgjengelig"]:
        L.append("   IKKE LEST: %s" % ix["feil"])
    else:
        t = ix["tilstand"]
        L.append("   Sist indeksert   : %s (modell %s, dim %s)"
                 % (t.get("sist_kjort"), t.get("modell"), t.get("dim")))
        L.append("   Biter / dokument : %s / %s"
                 % (_n(ix["rader"]), _n(ix["dokumenter"])))
        L.append("")
        L.append("   samling          biter   dok   andel   kvalifiserer  etterslep")
        L.append("   " + "-" * 66)
        for coll, s in sorted(ix["per_samling"].items(),
                              key=lambda kv: -kv[1]["rader"]):
            kval = "-" if s["kvalifiserer_naa"] is None else str(s["kvalifiserer_naa"])
            ett = "-" if s["etterslep"] is None else "%+d" % s["etterslep"]
            L.append("   %-15s %6s %5d %6.1f %% %13s %10s"
                     % (coll, _n(s["rader"]), s["dokumenter"],
                        s["andel_rader_pst"], kval, ett))
        L.append("   Etterslep = dokumenter som kvalifiserer nå, minus de som "
                 "ligger i indeksen")
        L.append("   (positivt tall = venter på neste re-indeksering).")
    L.append("")

    v = rap["vekst"]
    L.append("4) VEKST (siste %d døgn)" % v["vindu_dager"])
    for coll, r in v["samlinger"].items():
        L.append("   %s (%s): %d dokument(er) totalt"
                 % (coll, r["tidsstempelfelt"], r["totalt"]))
        if r["per_dag"] is None:
            L.append("     ingen brukbare tidsstempler – ingen vekstkurve")
            continue
        if r["med_tidsstempel"] != r["totalt"]:
            L.append("     %d av %d har tidsstempel"
                     % (r["med_tidsstempel"], r["totalt"]))
        L.append("     %s -> %s (%.1f døgn, snitt %.1f/døgn over levetiden%s)"
                 % (r["forste"], r["siste"], r["levetid_dager"] or 0.0,
                    r["snitt_per_dag_levetid"] or 0.0,
                    " – EKSTRAPOLERT fra under ett døgn"
                    if r["levetid_under_ett_dogn"] else ""))
        L.append("     " + "  ".join("%s:%d" % (p["dato"][5:], p["antall"])
                                     for p in r["per_dag"]))
        L.append("     i vinduet: %d (snitt %.1f/døgn)"
                 % (r["i_vinduet"], r["snitt_per_dag_vindu"]))
    # Kolonnene padder for å stå i flukt; halen av mellomrom skal ikke bli med.
    return "\n".join(linje.rstrip() for linje in L)


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="MIND – lesende minneanalyse (skriver aldri til basen)")
    ap.add_argument("--json", action="store_true", help="maskinlesbar utskrift")
    ap.add_argument("--dager", type=int, default=7,
                    help="vekstvindu i døgn (standard 7)")
    ap.add_argument("--index-dir", default=DEFAULT_INDEX_DIR,
                    help="kunnskapsindeksens katalog (standard %s)"
                         % DEFAULT_INDEX_DIR)
    args = ap.parse_args(argv)
    if args.dager < 1:
        ap.error("--dager må være minst 1")

    rap = bygg_rapport(dager=args.dager, index_dir=args.index_dir)
    if args.json:
        print(json.dumps(rap, ensure_ascii=False, indent=1, default=str))
    else:
        print(formater_tekst(rap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
