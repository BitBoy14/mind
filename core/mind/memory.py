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
    arbeidsminnet.

    Indeksen ligger i den CACHEDE delen av kallet (system_blocks[1]), og
    prompt-caching er en ren prefiks-match: endres ett tegn her, faller
    cachen for alt som kommer etter – hver eneste gang.

    Derfor står det ingen bruksstatistikk i denne strengen. `use_count`
    inkrementeres hver gang en seksjon LESES, så en indeks som bar den var
    ulik ved hvert kall og senket hovedhjernens cache-treffrate til 0,6 %
    mot agentenes 96,5 % (målt 2026-08-02). Totalsummen er ute av samme
    grunn: den endres hver gang en seksjon skrives.

    Tallene er ikke tapt – kuratering trenger dem. De leveres av
    build_usage_note() i den volatile delen av prompten, der de kan endre
    seg fritt uten å koste noe.
    """
    lines = ["HOVEDMINNE-INDEKS:"]
    for s in all_sections():
        first = (s.get("content") or "").strip().splitlines()
        summary = (first[0][:120] if first else "")
        lines.append("[%s] %s (viktighet %d) – %s" % (
            str(s["_id"]), s.get("title", "?"), s.get("importance", 5),
            summary))
    idx = "\n".join(lines)
    # Nødbrems: kutt bakerste linjer om indeksen vokser seg for stor
    while est_tokens(idx) > config.INDEX_TARGET_TOKENS * 2 and lines[3:]:
        lines = lines[:-1]
        idx = "\n".join(lines) + "\n[... indeks avkortet – kuratering trengs]"
    return idx


def build_usage_note():
    """Bruksstatistikk for kuratering – hører hjemme i den VOLATILE delen.

    Motstykket til build_index(): alt som endrer seg ofte samles her, slik at
    indeksen over kan ligge urørt i cachen. Formelen i §4.4 er
    viktighet × recency × bruksfrekvens, og de to siste leddene bor her.
    """
    now = time.time()
    lines = ["MINNETS TILSTAND (størrelse og bruk – grunnlag for kuratering):",
             "Hovedminnet bruker %d av maks %d tokens." %
             (total_tokens(), config.MAIN_MEMORY_MAX_TOKENS)]
    for s in all_sections():
        sist = s.get("last_used_ts") or s.get("created_ts") or now
        timer = max(0, (now - sist) / 3600.0)
        lines.append("[%s] %s: %d tok, brukt %dx, sist lest for %.1f timer siden" % (
            str(s["_id"]), s.get("title", "?"), s.get("tokens", 0),
            s.get("use_count", 0), timer))
    return "\n".join(lines)


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


def _new_detail(title, content, source="brain", section_id=None,
                kb_index=True, ref=None):
    """Opprett et detaljminne.

    `use_count`/`last_used_ts` settes fra første stund. Uten dem er «aldri
    hentet opp» ikke et lavt tall, men et manglende felt – og da er sjelden
    brukt detaljminne ikke målbart i det hele tatt. `last_used_ts` er None,
    ikke nå: et dokument som nettopp ble skrevet, er ikke brukt.

    `kb_index=False` merker dokumentet som ikke-indekserbart for
    kunnskapsmotoren (se KB_INDEX_FILTER). Feltet skrives KUN når det er
    False, slik at «mangler feltet» fortsatt betyr «indekseres», og
    eksisterende dokumenter beholder sin oppførsel.
    """
    doc = {"title": title, "content": content, "tokens": est_tokens(content),
           "created_ts": time.time(), "source": source,
           "section_id": str(section_id) if section_id else None,
           "use_count": 0, "last_used_ts": None}
    if not kb_index:
        doc["kb_index"] = False
    if ref:
        doc["ref"] = ref
    r = db.db().memory_details.insert_one(doc)
    return r.inserted_id


def add_detail(title, content, source="agent", section_id=None,
               kb_index=True, ref=None):
    """Offentlig inngang for å opprette et detaljminne utenfor minne_ops,
    f.eks. fra agent-rammeverket når en oppgave fullføres."""
    return _new_detail(title, content, source, section_id, kb_index, ref)


# ------------------------------------------------- dedup mot kunnskapsindeksen

# Filteret kunnskapsmotoren (/opt/mind-knowledge/mind_kb.py: SOURCES) bruker på
# memory_details og memory_archive. Gjengitt her fordi det er MINDs side av
# kontrakten: skriver vi kb_index=False, forsvinner dokumentet fra den
# semantiske indeksen ved neste re-indeksering.
KB_INDEX_FILTER = {"kb_index": {"$ne": False}}

# Halen add_detail selv kan ha lagt på et avkortet agentsvar. Den er et spor av
# lagringen, ikke av leveransen, og skal ikke telle som «nytt innhold» når vi
# avgjør om detaljen er en ren kopi.
_DETAIL_TRUNC_NOTE = re.compile(r"\n\n\[\.\.\. avkortet, \d+ tegn totalt \.\.\.\]\s*$")

# Agentresultat-titler bærer oppgavens id: «Agentresultat: … [<24 hex>]».
# Formatet er eneste kobling tilbake for detaljer skrevet før `ref` fantes.
_TASK_ID_IN_TITLE = re.compile(r"\[([0-9a-fA-F]{24})\]\s*$")


def duplicates_task_result(detail_content, task_result):
    """Sant når detaljteksten allerede ligger ORDRETT i agentoppgavens lagrede
    `result` – altså når detaljen ikke tilfører kunnskapsindeksen noe
    agent_tasks ikke allerede har.

    Merk at agent_tasks.result er avkortet til de siste tegnene av et langt
    agentsvar mens detaljminnet holder hele. Et langt svar er derfor IKKE et
    duplikat, og skal fortsatt indekseres – ellers ville begynnelsen av svaret
    blitt usøkbar. Nettopp derfor er innholdsmatch kriteriet, ikke opphavet.
    """
    c = _DETAIL_TRUNC_NOTE.sub("", (detail_content or "")).strip()
    r = (task_result or "").strip()
    return bool(c) and bool(r) and c in r


def _task_id_of(detail):
    """Agentoppgaven et detaljminne stammer fra: eksplisitt `ref` først,
    ellers id-en i tittelen. Returnerer None for detaljer uten opphav."""
    ref = str(detail.get("ref") or "")
    if ref.startswith("agent_tasks:"):
        return ref.split(":", 1)[1]
    m = _TASK_ID_IN_TITLE.search((detail.get("title") or "").strip())
    return m.group(1) if m else None


def flag_agent_duplicates(dry_run=False):
    """Merk auto-lagrede agentduplikater som ikke-indekserbare.

    Samme kunnskap lå indeksert to ganger – én gang som agent_tasks.result og
    én gang som detaljminne – slik at ett semantisk søk kunne returnere begge
    som separate «treff». Her merkes kopien, ikke originalen: agent_tasks
    forblir den ene indekserte kilden til agentsvar.

    IDEMPOTENT. Dokumenter som allerede er merket telles og hoppes over, og et
    dokument merkes KUN når teksten faktisk er en ordrett del av det
    agent_tasks lagrer. Ingenting slettes – dokumentet blir liggende, det blir
    bare ikke embeddet.

    `dry_run=True` måler uten å skrive. Returnerer en oppsummering.
    """
    d = db.db()
    sum_ = {"undersokt": 0, "flagget": 0, "allerede_flagget": 0,
            "beholdt_indeksert": 0, "uten_oppgave": 0, "tokens_ut_av_indeks": 0}
    for doc in d.memory_details.find({}):
        tid = _task_id_of(doc)
        if not tid:
            continue                      # ikke et agentavledet detaljminne
        sum_["undersokt"] += 1
        if doc.get("kb_index") is False:
            sum_["allerede_flagget"] += 1
            continue
        try:
            task = d.agent_tasks.find_one({"_id": ObjectId(tid)}, {"result": 1})
        except Exception:
            task = None
        if task is None:
            sum_["uten_oppgave"] += 1     # originalen finnes ikke – behold kopien
            continue
        if not duplicates_task_result(doc.get("content"), task.get("result")):
            sum_["beholdt_indeksert"] += 1
            continue
        if not dry_run:
            d.memory_details.update_one(
                {"_id": doc["_id"]},
                {"$set": {"kb_index": False, "ref": "agent_tasks:%s" % tid}})
        sum_["flagget"] += 1
        sum_["tokens_ut_av_indeks"] += (doc.get("tokens")
                                        or est_tokens(doc.get("content")))
    if sum_["flagget"] and not dry_run:
        log("dedup_indeksering",
            "%d agentduplikater merket kb_index=False (%d tokens ut av "
            "kunnskapsindeksen)" % (sum_["flagget"], sum_["tokens_ut_av_indeks"]),
            "system")
    return sum_


def backfill_detail_usage():
    """Gi detaljminner fra før brukssporingen et ærlig nullpunkt.

    Uten feltet er «aldri brukt» og «ikke målt» umulig å skille. Idempotent:
    rører kun dokumenter som mangler use_count, og nullstiller derfor aldri en
    teller som allerede har talt.
    """
    r = db.db().memory_details.update_many(
        {"use_count": {"$exists": False}},
        {"$set": {"use_count": 0, "last_used_ts": None}})
    return r.modified_count


def _ingen_seksjon(name, sid):
    """Kvittering når en op peker på en seksjon som ikke finnes (arkivert
    eller oppdiktet id). Hjernen skal aldri tro at noe ble skrevet."""
    return f"fant ikke seksjon [{sid}] – {name} gjorde ingenting"


def _ingen_detalj(name, did):
    """Samme kvittering for detaljminner: en op mot en id som ikke finnes
    skal si det rett ut, ikke gå stille."""
    return f"fant ikke detaljminne [{did}] – {name} gjorde ingenting"


def apply_ops(ops, actor="brain"):
    """Utfør en liste minne_ops fra hovedhjernen. Returnerer klartekst-sammendrag."""
    done = []
    for op in ops or []:
        # Hjernen kan svare med en liste strenger i stedet for objekter. Da
        # skal den enkelte op-en avvises – ikke resten av lista.
        if not isinstance(op, dict):
            done.append(f"minne-op feilet (ikke et objekt): {op!r}")
            log("feil", f"minne-op er ikke et objekt: {op!r}", actor)
            continue
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
                r = db.db().memory_main.update_one(
                    {"_id": oid},
                    {"$set": {"content": content, "tokens": est_tokens(content),
                              "last_used_ts": time.time()}})
                if r.matched_count:
                    log("oppdater_seksjon", str(op["id"]), actor)
                    done.append(f"oppdaterte seksjon [{op['id']}]")
                else:
                    done.append(_ingen_seksjon(name, op["id"]))

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
                else:
                    done.append(_ingen_seksjon(name, op["id"]))

            elif name == "sett_viktighet":
                oid = ObjectId(str(op["id"]))
                v = max(1, min(10, int(op.get("viktighet", 5))))
                r = db.db().memory_main.update_one({"_id": oid},
                                                   {"$set": {"importance": v}})
                if r.matched_count:
                    done.append(f"satte viktighet {v} på [{op['id']}]")
                else:
                    done.append(_ingen_seksjon(name, op["id"]))

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
                else:
                    done.append(_ingen_seksjon(name, op["id"]))

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
                    done.append(_ingen_seksjon(name, op["id"]))

            elif name == "arkiver_detalj":
                # Samme arkivmekanisme som arkiver_seksjon: dokumentet flyttes
                # til memory_archive med archived_ts + original_id, og
                # forsvinner fra nivået det lå på. Forskjellen er kb_index:
                # en arkivert detalj skal UT av det semantiske søket, ellers
                # ville arkiveringen bare flyttet treffet til en ny etikett.
                oid = ObjectId(str(op["id"]))
                dtl = db.db().memory_details.find_one({"_id": oid})
                if dtl:
                    dtl.pop("_id")
                    dtl["archived_ts"] = time.time()
                    dtl["original_id"] = str(oid)
                    dtl["from_collection"] = "memory_details"
                    dtl["kb_index"] = False
                    r = db.db().memory_archive.insert_one(dtl)
                    db.db().memory_details.delete_one({"_id": oid})
                    # Pekeren i seksjonen skal følge dokumentet, ikke bli
                    # hengende igjen som en brutt lenke. To skrivinger fordi
                    # $pull og $push på samme felt kolliderer i én.
                    sid = dtl.get("section_id")
                    if sid:
                        try:
                            soid = ObjectId(str(sid))
                            db.db().memory_main.update_one(
                                {"_id": soid}, {"$pull": {"pointers": str(oid)}})
                            db.db().memory_main.update_one(
                                {"_id": soid},
                                {"$push": {"pointers": "arkiv:" + str(r.inserted_id)}})
                        except Exception:
                            pass
                    log("arkiver_detalj", dtl.get("title", ""), actor)
                    done.append(f"arkiverte detaljminne '{dtl.get('title')}' "
                                f"(arkiv [{r.inserted_id}], ute av kunnskapsindeksen)")
                else:
                    done.append(_ingen_detalj(name, op["id"]))

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
