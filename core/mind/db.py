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

from pymongo import MongoClient, ASCENDING, DESCENDING

from . import config

_client = None


def client():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI)
    return _client


def db():
    return client()[config.DB_NAME]


def jarvis_db():
    return client()[config.JARVIS_DB_NAME]


def ensure_indexes():
    d = db()
    d.events.create_index([("processed", ASCENDING), ("ts", ASCENDING)])
    d.chat.create_index([("ts", DESCENDING)])
    d.thoughts.create_index([("ts", DESCENDING)])
    d.tokens.create_index([("ts", DESCENDING)])
    d.agent_tasks.create_index([("status", ASCENDING), ("created_ts", ASCENDING)])
    d.memory_details.create_index([("created_ts", DESCENDING)])
    d.memory_archive.create_index([("archived_ts", DESCENDING)])
    d.cycles.create_index([("ts", DESCENDING)])


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

def create_agent_task(title, brief, task_type="bygg", priority=3, created_by="brain"):
    doc = {"created_ts": time.time(), "title": title, "brief": brief,
           "type": task_type, "priority": priority, "status": "queued",
           "created_by": created_by, "started_ts": None, "finished_ts": None,
           "result": None, "assessment": None, "files": [], "progress": ""}
    r = db().agent_tasks.insert_one(doc)
    doc["_id"] = r.inserted_id
    return doc


def queued_tasks():
    return list(db().agent_tasks.find({"status": "queued"})
                .sort([("priority", ASCENDING), ("created_ts", ASCENDING)]))


def running_tasks():
    return list(db().agent_tasks.find({"status": "running"}))


def update_task(task_id, patch):
    db().agent_tasks.update_one({"_id": task_id}, {"$set": patch})


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
