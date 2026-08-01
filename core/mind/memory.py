"""Minnemotoren: fire nivåer (§4).

  Arbeidsminne : bygges per kall = indeks + relevante seksjoner (velges her)
  Hovedminne   : memory_main-seksjoner, maks 150k tokens totalt, med metadata
  Detaljminner : memory_details («bøkene») – ubegrenset
  Arkivet      : memory_archive («Boken») – ubegrenset, søkbart

Ingenting slettes for godt: hierarkiet styrer tilgjengelighet, ikke eksistens.
All kuratering logges til memory_log.
"""
import re
import time

from bson import ObjectId
from pymongo import DESCENDING

from . import config, db


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


def select_relevant(query_text, budget_tokens=None, always_core=True):
    """Velg de mest relevante seksjonene for en tekst, innenfor token-budsjett.
    Enkel nøkkelord-scoring + viktighetsboost; kjerneseksjoner (viktighet >= 9)
    tas alltid med først."""
    if budget_tokens is None:
        budget_tokens = config.WORKSET_TARGET_TOKENS
    words = set(w.lower() for w in _WORD.findall(query_text or ""))
    scored = []
    for s in all_sections():
        hay = ((s.get("title", "") + "\n" + s.get("content", ""))).lower()
        score = sum(1 for w in words if w in hay)
        score += s.get("importance", 5) * 0.5
        if always_core and s.get("importance", 5) >= 9:
            score += 100
        scored.append((score, s))
    scored.sort(key=lambda t: -t[0])
    chosen, used = [], 0
    for score, s in scored:
        tk = s.get("tokens", est_tokens(s.get("content", "")))
        if used + tk > budget_tokens and chosen:
            continue
        if score <= 0.5 and s.get("importance", 5) < 9:
            continue
        chosen.append(s)
        used += tk
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
