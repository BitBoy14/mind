"""Minnemotoren: fire nivåer (§4).

  Arbeidsminne : bygges per kall = indeks + relevante seksjoner (velges her)
  Hovedminne   : memory_main-seksjoner, maks 150k tokens totalt, med metadata
  Detaljminner : memory_details («bøkene») – ubegrenset
  Arkivet      : memory_archive («Boken») – ubegrenset, søkbart

Ingenting slettes for godt: hierarkiet styrer tilgjengelighet, ikke eksistens.
All kuratering logges til memory_log.
"""
import logging
import re
import time

from bson import ObjectId
from pymongo import DESCENDING

from . import config, db, knowledge

# `log` er navnet på minneloggen lenger nede – modullogger heter derfor `_log`.
_log = logging.getLogger("mind.memory")


def est_tokens(text):
    return int(len(text or "") / 3.5) + 1


# ------------------------------------------------------------------ oppslag

def all_sections():
    return list(db.db().memory_main.find().sort("importance", DESCENDING))


def total_tokens():
    return sum(s.get("tokens", 0) for s in db.db().memory_main.find({}, {"tokens": 1}))


def build_index():
    """Kompakt innholdsfortegnelse over hele hovedminnet – alltid med i
    arbeidsminnet. Holdes rundt INDEX_TARGET_TOKENS."""
    lines = ["HOVEDMINNE-INDEKS (totalt %d tokens av maks %d):" %
             (total_tokens(), config.MAIN_MEMORY_MAX_TOKENS)]
    for s in all_sections():
        first = (s.get("content") or "").strip().splitlines()
        summary = (first[0][:120] if first else "")
        lines.append("[%s] %s (viktighet %d, %d tok, brukt %dx) – %s" % (
            str(s["_id"]), s.get("title", "?"), s.get("importance", 5),
            s.get("tokens", 0), s.get("use_count", 0), summary))
    idx = "\n".join(lines)
    # Nødbrems: kutt bakerste linjer om indeksen vokser seg for stor
    while est_tokens(idx) > config.INDEX_TARGET_TOKENS * 2 and lines[3:]:
        lines = lines[:-1]
        idx = "\n".join(lines) + "\n[... indeks avkortet – kuratering trengs]"
    return idx


def get_sections(ids, mark_used=True):
    out = []
    for sid in ids:
        try:
            oid = ObjectId(str(sid))
        except Exception:
            continue
        s = db.db().memory_main.find_one({"_id": oid})
        if s:
            out.append(s)
            if mark_used:
                db.db().memory_main.update_one(
                    {"_id": oid},
                    {"$set": {"last_used_ts": time.time()},
                     "$inc": {"use_count": 1}})
    return out


def render_sections(sections):
    parts = []
    for s in sections:
        parts.append("### SEKSJON [%s] %s (viktighet %d)\n%s" % (
            str(s["_id"]), s.get("title", ""), s.get("importance", 5),
            s.get("content", "")))
    return "\n\n".join(parts)


_WORD = re.compile(r"[a-zA-ZæøåÆØÅ0-9]{4,}")

# Kjerneseksjonene er MIND selv: hvem brukeren er, hvem MIND er, hva som
# pågår. De kan aldri velges bort, uansett hva syklusen handler om.
CORE_IMPORTANCE = 9

# Semantisk seleksjon. Tallene er kalibrert mot ekte målinger på indeksen:
# en klart urelatert spørring gir 0,03–0,11 på seksjonene, en relevant
# 0,30–0,56. Gulvet på 0,15 skiller de to uten å være nærgående.
SEMANTIC_MIN_SCORE = 0.15
# Tak på antall ikke-kjerne-seksjoner. Bremser først når hovedminnet vokser;
# poenget er at et budsjett på 25k tokens ikke skal fylles med det nest
# nærmeste bare fordi det er plass.
SEMANTIC_TOP_K = 12
# Seksjoner motoren ikke kjenner, er ikke irrelevante – de er usette
# (opprettet eller endret etter siste indeksering). Noen få slipper alltid
# gjennom; ellers ville en fersk seksjon vært usynlig for hjernen helt frem
# til neste indeksering.
SEMANTIC_UNSEEN_QUOTA = 3


def _tokens_of(s):
    return s.get("tokens", est_tokens(s.get("content", "")))


def _select_keywords(query_text, budget_tokens, always_core):
    """Nøkkelordrangeringen: delstrengtreff + viktighetsboost.

    Dette er tilbakefallet når kunnskapsmotoren ikke kan svare, og oppførselen
    er bevisst uendret fra før den semantiske ruten fantes: den tar med alt som
    får plass i budsjettet, rangert. Den siler i praksis ikke bort noe.
    """
    words = set(w.lower() for w in _WORD.findall(query_text or ""))
    scored = []
    for s in all_sections():
        hay = ((s.get("title", "") + "\n" + s.get("content", ""))).lower()
        score = sum(1 for w in words if w in hay)
        score += s.get("importance", 5) * 0.5
        if always_core and s.get("importance", 5) >= CORE_IMPORTANCE:
            score += 100
        scored.append((score, s))
    scored.sort(key=lambda t: -t[0])
    chosen, used = [], 0
    for score, s in scored:
        tk = _tokens_of(s)
        if used + tk > budget_tokens and chosen:
            continue
        if score <= 0.5 and s.get("importance", 5) < CORE_IMPORTANCE:
            continue
        chosen.append(s)
        used += tk
    return chosen


def _select_semantic(query_text, budget_tokens, always_core):
    """Kjerneseksjonene + de semantisk nærmeste av resten.

    Returnerer None så snart grunnlaget svikter – motoren er kald, svarer
    ikke, eller kjente ikke igjen én eneste seksjon. Da har vi ikke noe å
    kutte på, og kalleren skal falle tilbake til nøkkelordrangeringen.
    Kaster aldri.
    """
    try:
        sections = all_sections()
        if not sections:
            return None
        core = [s for s in sections
                if always_core and s.get("importance", 5) >= CORE_IMPORTANCE]
        core_ids = set(str(s["_id"]) for s in core)
        rest = [s for s in sections if str(s["_id"]) not in core_ids]

        svar = knowledge.section_scores(query_text)
        if svar is None:
            return None
        scores, gulv = svar
        if not scores:
            return None     # motoren kjente ikke igjen noen seksjon i det hele tatt

        naere, usette = [], []
        for pos, s in enumerate(rest):
            sc = scores.get(str(s["_id"]))
            if sc is None:
                # Utenfor trefflisten. Ble listen avkortet under gulvet vårt,
                # VET vi at seksjonen scorer svakere enn det – da er den
                # irrelevant. Ellers er den bare ukjent for indeksen.
                if gulv is not None and gulv <= SEMANTIC_MIN_SCORE:
                    continue
                usette.append(s)
            elif sc >= SEMANTIC_MIN_SCORE:
                # pos er posisjonen i all_sections (viktighet synkende, så
                # innsettingsrekkefølge): gjør uavgjort deterministisk.
                naere.append((-sc, pos, s))
        naere.sort(key=lambda t: t[:2])

        # Kjernen først og uten å belaste budsjettet – den er ubetinget.
        chosen = list(core)
        used = sum(_tokens_of(s) for s in chosen)
        # `continue`, ikke `break`: én diger seksjon skal ikke stenge døren for
        # de mindre bak den i rangeringen.
        for s in ([t[2] for t in naere[:SEMANTIC_TOP_K]]
                  + usette[:SEMANTIC_UNSEEN_QUOTA]):
            tk = _tokens_of(s)
            if used + tk > budget_tokens and chosen:
                continue
            chosen.append(s)
            used += tk
        return chosen
    except Exception as e:
        _log.warning("semantisk seksjonsvalg hoppet over (%s: %s)",
                     type(e).__name__, e)
        return None


def select_relevant(query_text, budget_tokens=None, always_core=True,
                    semantic=True):
    """Velg de mest relevante seksjonene for en tekst, innenfor token-budsjett.

    Kjerneseksjoner (viktighet >= 9) tas alltid med, ubetinget og uten å
    belaste budsjettet. Resten scores semantisk av kunnskapsmotoren mot
    syklusens kontekst og kuttes til de nærmeste innenfor budsjettet – det er
    forskjellen fra før, da alt som fikk plass ble med.

    FAIL-OPEN, absolutt: svarer ikke motoren, eller svarer den noe vi ikke kan
    bruke, faller valget tilbake til den gamle nøkkelordrangeringen. Ingen
    syklus skal kunne feile fordi et semantisk oppslag gikk galt.
    """
    if budget_tokens is None:
        budget_tokens = config.WORKSET_TARGET_TOKENS
    chosen = None
    if semantic:
        chosen = _select_semantic(query_text, budget_tokens, always_core)
    if chosen is None:
        chosen = _select_keywords(query_text, budget_tokens, always_core)
    ids = [str(s["_id"]) for s in chosen]
    return get_sections(ids)  # markerer bruk


# ------------------------------------------------------------------ logg

def log(action, detail, actor="brain"):
    db.db().memory_log.insert_one({
        "ts": time.time(), "action": action, "detail": detail, "actor": actor})


# ------------------------------------------------------------------ operasjoner

def _new_section(title, content, importance=5, pointers=None):
    doc = {"title": title, "content": content, "tokens": est_tokens(content),
           "importance": max(1, min(10, int(importance or 5))),
           "created_ts": time.time(), "last_used_ts": time.time(),
           "use_count": 0, "pointers": pointers or []}
    r = db.db().memory_main.insert_one(doc)
    return r.inserted_id


def _new_detail(title, content, source="brain", section_id=None):
    doc = {"title": title, "content": content, "tokens": est_tokens(content),
           "created_ts": time.time(), "source": source,
           "section_id": str(section_id) if section_id else None}
    r = db.db().memory_details.insert_one(doc)
    return r.inserted_id


def add_detail(title, content, source="agent", section_id=None):
    """Offentlig inngang for å opprette et detaljminne utenfor minne_ops,
    f.eks. fra agent-rammeverket når en oppgave fullføres."""
    return _new_detail(title, content, source, section_id)


def apply_ops(ops, actor="brain"):
    """Utfør en liste minne_ops fra hovedhjernen. Returnerer klartekst-sammendrag."""
    done = []
    for op in ops or []:
        try:
            name = op.get("op", "")
            if name == "opprett_seksjon":
                sid = _new_section(op.get("tittel", "Uten tittel"),
                                   op.get("innhold", ""),
                                   op.get("viktighet", 5))
                log("opprett_seksjon", op.get("tittel", ""), actor)
                done.append(f"opprettet seksjon '{op.get('tittel')}' [{sid}]")

            elif name == "oppdater_seksjon":
                oid = ObjectId(str(op["id"]))
                content = op.get("innhold", "")
                db.db().memory_main.update_one(
                    {"_id": oid},
                    {"$set": {"content": content, "tokens": est_tokens(content),
                              "last_used_ts": time.time()}})
                log("oppdater_seksjon", str(op["id"]), actor)
                done.append(f"oppdaterte seksjon [{op['id']}]")

            elif name == "tilfoy_seksjon":
                oid = ObjectId(str(op["id"]))
                s = db.db().memory_main.find_one({"_id": oid})
                if s:
                    content = (s.get("content", "") + "\n\n" +
                               op.get("innhold", "")).strip()
                    db.db().memory_main.update_one(
                        {"_id": oid},
                        {"$set": {"content": content,
                                  "tokens": est_tokens(content),
                                  "last_used_ts": time.time()}})
                    log("tilfoy_seksjon", str(op["id"]), actor)
                    done.append(f"tilføyde til seksjon [{op['id']}]")

            elif name == "sett_viktighet":
                oid = ObjectId(str(op["id"]))
                v = max(1, min(10, int(op.get("viktighet", 5))))
                db.db().memory_main.update_one({"_id": oid},
                                               {"$set": {"importance": v}})
                done.append(f"satte viktighet {v} på [{op['id']}]")

            elif name == "opprett_detalj":
                did = _new_detail(op.get("tittel", "Detalj"),
                                  op.get("innhold", ""), actor,
                                  op.get("seksjon_id"))
                if op.get("seksjon_id"):
                    try:
                        db.db().memory_main.update_one(
                            {"_id": ObjectId(str(op["seksjon_id"]))},
                            {"$push": {"pointers": str(did)}})
                    except Exception:
                        pass
                log("opprett_detalj", op.get("tittel", ""), actor)
                done.append(f"opprettet detaljminne '{op.get('tittel')}' [{did}]")

            elif name == "komprimer_seksjon":
                oid = ObjectId(str(op["id"]))
                s = db.db().memory_main.find_one({"_id": oid})
                if s:
                    # Fullversjonen bevares som detaljminne før komprimering
                    did = _new_detail("Fullversjon: " + s.get("title", ""),
                                      s.get("content", ""), actor, oid)
                    content = op.get("nytt_innhold", "")
                    db.db().memory_main.update_one(
                        {"_id": oid},
                        {"$set": {"content": content,
                                  "tokens": est_tokens(content)},
                         "$push": {"pointers": str(did)}})
                    log("komprimer_seksjon",
                        "%s (%d -> %d tok)" % (s.get("title", ""),
                                               s.get("tokens", 0),
                                               est_tokens(content)), actor)
                    done.append(f"komprimerte seksjon '{s.get('title')}' "
                                f"(fullversjon i detalj [{did}])")

            elif name == "arkiver_seksjon":
                oid = ObjectId(str(op["id"]))
                s = db.db().memory_main.find_one({"_id": oid})
                if s:
                    s.pop("_id")
                    s["archived_ts"] = time.time()
                    s["original_id"] = str(oid)
                    r = db.db().memory_archive.insert_one(s)
                    db.db().memory_main.delete_one({"_id": oid})
                    one = (op.get("en_linje") or "").strip()
                    if one:
                        _new_section(s.get("title", "Arkivert"),
                                     one, importance=2,
                                     pointers=["arkiv:" + str(r.inserted_id)])
                    log("arkiver_seksjon", s.get("title", ""), actor)
                    done.append(f"arkiverte seksjon '{s.get('title')}'")

            else:
                done.append(f"ukjent minne-op: {name}")
        except Exception as e:
            done.append(f"minne-op feilet ({op.get('op')}): {e}")
            log("feil", f"{op.get('op')}: {e}", actor)
    return done


# ------------------------------------------------------------------ oppstart

def ensure_seed():
    """Førstegangsoppsett: gi hovedminnet en grunnstruktur."""
    if db.db().memory_main.count_documents({}) > 0:
        return
    _new_section("Om brukeren",
                 "Brukeren heter Mads (mads@numeriq.no). Mer lærer jeg etter "
                 "hvert som vi snakker – dette er min faste seksjon for hvem "
                 "brukeren er, preferanser og kontekst.", 10)
    _new_section("Om meg selv (MIND)",
                 "Jeg er MIND: en persistent hovedhjerne bak en chat på "
                 "https://www.shrtct.site/mind/. Jeg tenker mellom meldingene, "
                 "delegerer arbeid til agenter, kuraterer mitt eget minne og "
                 "foreslår forbedringer av meg selv i admin-seksjonen. "
                 "Koden min ligger i /var/www/www.shrtct.site/mind/ (git-repo).", 10)
    _new_section("Pågående arbeid",
                 "Ingen aktive prosjekter ennå. Her holder jeg status på alt "
                 "som pågår: prosjekter, agentoppgaver, ventende beslutninger.", 9)
    _new_section("Lærdommer og beslutninger",
                 "Her samler jeg lærdommer, prinsipper og beslutninger som er "
                 "tatt, så jeg ikke gjentar feil eller re-diskuterer avgjorte "
                 "ting.", 8)
    log("seed", "hovedminnet initialisert med grunnseksjoner", "system")
