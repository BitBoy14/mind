"""MongoDB-laget: all tilstand lever her, slik at daemonen kan gjenopptas
etter restart uten tap (§2). Samlinger:

  settings        - innstillinger (motor, modeller, running, brytere)
  state           - daemon-tilstand: arbeidsnotat, puls, stagnasjon
  events          - hendelseskø (chat, agent-leveranser, kommentarer, feil)
  chat            - chatmeldinger (user | responder | brain | system)
  thoughts        - tankestrømmen, med kommentarer fra brukeren
  memory_main     - hovedminnets seksjoner (maks 150k tokens totalt)
  memory_details  - detaljminner («bøkene»)
  memory_archive  - Arkivet («Boken»)
  memory_log      - kurateringslogg
  agent_tasks     - agentoppgaver med status og resultat
  tokens          - per-kall tokenlogg
  prompts         - overstyrbare prompter (godkjente promptendringer)
  admin_proposals - selvutviklingsforslag til godkjenning
  cycles          - logg over hovedhjerne-sykluser (dashbordets «Nå»)
"""
import time

from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument

from . import config

_client = None
_jarvis_client = None


def client():
    global _client
    if _client is None:
        _client = MongoClient(config.mongo_uri())
    return _client


def db():
    return client()[config.DB_NAME]


def jarvis_db():
    """Jarvis-basen ligger fortsatt paa den delte instansen (27017), ikke paa
    MINDs dedikerte, autentiserte instans - derfor en egen klient (§7.3)."""
    global _jarvis_client
    if _jarvis_client is None:
        _jarvis_client = MongoClient(config.JARVIS_MONGO_URI)
    return _jarvis_client[config.JARVIS_DB_NAME]


def ensure_indexes():
    d = db()
    d.events.create_index([("processed", ASCENDING), ("ts", ASCENDING)])
    d.chat.create_index([("ts", DESCENDING)])
    d.thoughts.create_index([("ts", DESCENDING)])
    d.tokens.create_index([("ts", DESCENDING)])
    d.agent_tasks.create_index([("status", ASCENDING), ("created_ts", ASCENDING)])
    d.memory_details.create_index([("created_ts", DESCENDING)])
    d.memory_details.create_index([("use_count", ASCENDING),
                                   ("last_used_ts", ASCENDING)])
    d.memory_archive.create_index([("archived_ts", DESCENDING)])
    d.cycles.create_index([("ts", DESCENDING)])


# ------------------------------------------------------------- detaljminner

def mark_details_used(ids):
    """Tell bruk på detaljminnene som faktisk ble lest ut til noen.

    Detaljminner nås ALDRI via memory.get_sections – de hentes av
    kunnskapsmotorens destillat (inn i syklusprompten) og av dashbordets
    utforsker. Uten denne tellingen er «aldri hentet opp» ikke et lavt tall,
    men et manglende felt, og kuratering av detaljnivået må gjettes på alder.

    Ugyldige id-er hoppes over i stillhet: dette er sporing, og en sporing
    skal aldri kunne velte det den sporer. Returnerer antall treff.
    """
    oids = []
    for i in ids or []:
        try:
            oids.append(ObjectId(str(i)))
        except Exception:
            continue
    if not oids:
        return 0
    r = db().memory_details.update_many(
        {"_id": {"$in": oids}},
        {"$set": {"last_used_ts": time.time()}, "$inc": {"use_count": 1}})
    return r.matched_count


# ------------------------------------------------------------------ settings

def get_settings():
    s = db().settings.find_one({"_id": "main"})
    if s is None:
        s = dict(config.DEFAULT_SETTINGS)
        db().settings.insert_one(s)
    # nye defaults som er lagt til etter første oppstart
    changed = False
    for k, v in config.DEFAULT_SETTINGS.items():
        if k not in s:
            s[k] = v
            changed = True
    if changed:
        db().settings.update_one({"_id": "main"}, {"$set": s}, upsert=True)
    return s


def update_settings(patch):
    db().settings.update_one({"_id": "main"}, {"$set": patch}, upsert=True)


# ------------------------------------------------------------------ state

def get_state():
    st = db().state.find_one({"_id": "main"})
    return st or {"_id": "main", "working_note": "", "last_pulse_ts": 0,
                  "pulse_interval": config.PULSE_MIN, "last_cycle_ts": 0,
                  "last_think_ts": 0, "last_curation_day": "",
                  "pulses_since_cycle": 0, "stagnation": False}


def set_state(patch):
    db().state.update_one({"_id": "main"}, {"$set": patch}, upsert=True)


# ------------------------------------------------------------------ events

def log_event(etype, text, payload=None, priority=3):
    """Legg hendelse i køen. priority: 1 høyest, 5 lavest."""
    doc = {"ts": time.time(), "type": etype, "text": text,
           "payload": payload or {}, "priority": priority, "processed": False}
    db().events.insert_one(doc)
    return doc


def unprocessed_events(limit=100):
    return list(db().events.find({"processed": False})
                .sort("ts", ASCENDING).limit(limit))


def mark_events_processed(ids):
    if ids:
        db().events.update_many({"_id": {"$in": ids}},
                                {"$set": {"processed": True}})


def unprocessed_events_of_type(etype, limit=20):
    """Uprosesserte hendelser av én type, eldste først.

    Brukes av responderen for chat_msg: en brukermelding er «uprosessert»
    helt til hovedhjernen har lest den i en syklus, og fram til da finnes den
    ikke i minnet. Responderen må se den likevel.
    """
    return list(db().events.find({"processed": False, "type": etype})
                .sort("ts", ASCENDING).limit(limit))


# ------------------------------------------------------------------ tokens

def log_tokens(role, engine, model, usage, purpose, ms):
    db().tokens.insert_one({
        "ts": time.time(), "role": role, "engine": engine, "model": model,
        "input": usage.get("input", 0), "output": usage.get("output", 0),
        "cache_read": usage.get("cache_read", 0),
        "cache_creation": usage.get("cache_creation", 0),
        "purpose": purpose, "ms": round(ms),
    })


# ------------------------------------------------------------------ chat

def add_chat(role, text, marker=None):
    doc = {"ts": time.time(), "role": role, "text": text, "marker": marker}
    db().chat.insert_one(doc)
    return doc


def chat_since_epoch(limit=30):
    epoch = get_settings().get("chat_epoch", 0.0)
    msgs = list(db().chat.find({"ts": {"$gt": epoch}})
                .sort("ts", DESCENDING).limit(limit))
    return list(reversed(msgs))


def unanswered_user_messages():
    """Brukermeldinger (etter epoch) som responderen ikke har svart på enda."""
    epoch = get_settings().get("chat_epoch", 0.0)
    msgs = list(db().chat.find({"ts": {"$gt": epoch}}).sort("ts", ASCENDING))
    pending = []
    for m in msgs:
        if m["role"] == "user" and not m.get("answered"):
            pending.append(m)
    return pending


def mark_chat_answered(ids):
    if ids:
        db().chat.update_many({"_id": {"$in": ids}},
                              {"$set": {"answered": True}})


# ------------------------------------------------------------------ thoughts

def add_thought(text, kind="tanke", refs=None):
    doc = {"ts": time.time(), "text": text, "kind": kind,
           "refs": refs or [], "comments": []}
    db().thoughts.insert_one(doc)
    return doc


# ------------------------------------------------------------------ agent tasks

# Statuser der en oppgave fortsatt kan avbrytes (og der et avbruddsflagg
# ennå ikke er ferdig håndhevet).
CANCEL_PENDING_STATUSES = ["queued", "running", "cancelling"]


def create_agent_task(title, brief, task_type="bygg", priority=3, created_by="brain"):
    doc = {"created_ts": time.time(), "title": title, "brief": brief,
           "type": task_type, "priority": priority, "status": "queued",
           "created_by": created_by, "started_ts": None, "finished_ts": None,
           "result": None, "assessment": None, "files": [], "progress": "",
           "cancel_requested": False, "process": None}
    r = db().agent_tasks.insert_one(doc)
    doc["_id"] = r.inserted_id
    return doc


def queued_tasks():
    # Flaggede oppgaver skal ikke startes – de går til kanselleringssveipet.
    return list(db().agent_tasks.find({"status": "queued",
                                       "cancel_requested": {"$ne": True}})
                .sort([("priority", ASCENDING), ("created_ts", ASCENDING)]))


def running_tasks():
    return list(db().agent_tasks.find({"status": {"$in": ["running", "cancelling"]}}))


def update_task(task_id, patch):
    db().agent_tasks.update_one({"_id": task_id}, {"$set": patch})


# ---------------------------------------------- prosess og kansellering (§2)

def register_task_process(task_id, info):
    """Lagre PID/prosessgruppe på oppgaven SÅ SNART prosessen er startet.

    Uten dette har en kansellering ingenting å drepe – det var nettopp
    dette som gjorde at «avbrutte» agenter fullførte arbeidet.
    """
    db().agent_tasks.update_one({"_id": task_id}, {"$set": {"process": info}})


def mark_task_process_exited(task_id, returncode):
    db().agent_tasks.update_one({"_id": task_id}, {"$set": {
        "process.exited_ts": time.time(), "process.returncode": returncode}})


def request_cancel(task_id, by="brain", reason=""):
    """Sett avbruddsflagget. Selve drepingen (og den verifiserte slutt-
    statusen) håndheves av agent-manageren i daemonen, som eier prosessen.

    Returnerer True hvis oppgaven fortsatt var aktiv og altså ble flagget.
    """
    r = db().agent_tasks.update_one(
        {"_id": task_id, "status": {"$in": CANCEL_PENDING_STATUSES}},
        {"$set": {"cancel_requested": True, "cancel_requested_ts": time.time(),
                  "cancel_requested_by": by, "cancel_reason": reason,
                  "status": "cancelling",
                  "progress": "avbrudd bestilt – dreper prosessen …"}})
    return r.matched_count > 0


def is_cancel_requested(task_id):
    d = db().agent_tasks.find_one({"_id": task_id}, {"cancel_requested": 1})
    return bool(d and d.get("cancel_requested"))


def tasks_awaiting_cancel():
    """Flaggede oppgaver som ennå ikke har fått en verifisert slutt-status."""
    return list(db().agent_tasks.find(
        {"cancel_requested": True,
         "status": {"$in": CANCEL_PENDING_STATUSES}}))


def update_task_if_active(task_id, patch):
    """Skriv patch bare hvis oppgaven IKKE er flagget avbrutt.

    Returnerer 0 hvis den er flagget – da skal kalleren ikke overskrive
    kanselleringens slutt-status med 'done'/'failed'.
    """
    r = db().agent_tasks.update_one(
        {"_id": task_id, "cancel_requested": {"$ne": True}}, {"$set": patch})
    return r.matched_count


def record_cancel_outcome(task_id, kill_info, status, result=None):
    """Skriv det VERIFISERTE utfallet av en kansellering – med compare-and-set.

    status er 'cancelled' kun når kill_info bekrefter at prosessen er død;
    ellers 'cancel_failed'. Hele kill_info lagres, så dokumentet alltid
    forklarer hvorfor statusen ble som den ble.

    Statusfilteret er ikke pynt. Uten det var dette en åpen TOCTOU-luke:
    arbeidertråden kunne rekke å skrive 'done' i sekundene mellom
    drapsforsøket og denne skrivingen, og kanselleringen malte deretter
    'cancelled' over ferdig arbeid. Skrivingen gjelder derfor kun så lenge
    oppgaven fortsatt står i en avbrytbar tilstand – en terminal status
    (done/failed/cancel_failed) skal ALDRI overskrives i etterkant.

    Returnerer (skrevet, status_naa): skrevet=False betyr at oppgaven alt
    hadde en terminal status; kill_info legges da bare i cancel_log som
    revisjonsspor, med applied=False.
    """
    patch = {"status": status, "cancel_kill": kill_info,
             "cancel_enforced_ts": time.time(), "finished_ts": time.time(),
             "progress": ""}
    if result is not None:
        patch["result"] = result
    doc = db().agent_tasks.find_one_and_update(
        {"_id": task_id, "status": {"$in": CANCEL_PENDING_STATUSES}},
        {"$set": patch, "$push": {"cancel_log": kill_info}},
        return_document=ReturnDocument.AFTER)
    if doc is not None:
        return True, doc.get("status")
    late = dict(kill_info, applied=False,
                detail="avbruddet kom for sent: oppgaven hadde allerede en "
                       "terminal status – den beholdes uendret. "
                       + str(kill_info.get("detail", "")))
    doc = db().agent_tasks.find_one_and_update(
        {"_id": task_id}, {"$push": {"cancel_log": late}},
        return_document=ReturnDocument.AFTER)
    return False, (doc or {}).get("status")


def finish_completed_despite_cancel(task_id, patch, note):
    """Avbrutt oppgave som likevel kjørte ferdig – med compare-and-set.

    Motsatt vei av record_cancel_outcome: her ER arbeidet fullført, og
    dokumentet skal si det. Vi tillater derfor å korrigere en 'cancelled'
    som et samtidig kanselleringssveip rakk å skrive (den ville vært en
    ren løgn), men rører aldri en oppgave som allerede står som
    done/failed/cancel_failed.

    Returnerer True hvis korreksjonen ble skrevet.
    """
    doc = db().agent_tasks.find_one_and_update(
        {"_id": task_id,
         "status": {"$in": CANCEL_PENDING_STATUSES + ["cancelled"]}},
        {"$set": patch, "$push": {"cancel_log": note}},
        return_document=ReturnDocument.AFTER)
    return doc is not None


def note_cancel_progress(task_id, kill_info, progress):
    """Mellomtilstand: avbrudd er bestilt, men ikke ferdig verifisert.

    Samme statusfilter som over: rekker oppgaven å bli ferdig mens vi venter
    på verifikasjon, skal ingen 'venter på …'-tekst legge seg oppå det
    ferdige dokumentet.
    """
    r = db().agent_tasks.update_one(
        {"_id": task_id, "status": {"$in": CANCEL_PENDING_STATUSES}},
        {"$set": {"cancel_kill": kill_info, "progress": progress}})
    return r.matched_count > 0


# ------------------------------------------------------------------ prompts

def get_prompt_override(key):
    doc = db().prompts.find_one({"_id": key})
    return doc["text"] if doc else None


def set_prompt(key, text):
    db().prompts.update_one({"_id": key}, {"$set": {"text": text,
                            "updated_ts": time.time()}}, upsert=True)


# ------------------------------------------------------------------ admin

def add_admin_proposal(kind, title, body, payload=None):
    doc = {"ts": time.time(), "kind": kind, "title": title, "body": body,
           "payload": payload or {}, "status": "pending", "result": None}
    db().admin_proposals.insert_one(doc)
    return doc


def pending_proposals():
    return list(db().admin_proposals.find({"status": "pending"})
                .sort("ts", ASCENDING))


# ------------------------------------------------------------------ cycles

def log_cycle(kind, observations, decisions, raw=None):
    db().cycles.insert_one({
        "ts": time.time(), "kind": kind, "observations": observations,
        "decisions": decisions, "raw": raw,
    })
