"""Hovedhjerne-syklusen (§3.2): Observér → Husk → Tenk → Handle → Kurér →
Forbedre → Planlegg. Kalles av daemonen når puls-vakten vekker sjefen, ved
planlagte tanke-økter, og ved natt-økten (grundig kuratering).
"""
import datetime
import time

from bson import ObjectId

from . import brain, config, db, jarvis_link, memory, prompts


def _render_events(events):
    if not events:
        return "(ingen nye hendelser)"
    lines = []
    for e in events:
        ts = datetime.datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
        payload = ""
        if e.get("payload"):
            p = str(e["payload"])
            payload = " | " + (p[:300] + "…" if len(p) > 300 else p)
        lines.append(f"- [{ts}] ({e['type']}, prio {e.get('priority', 3)}) "
                     f"{e.get('text', '')}{payload}")
    return "\n".join(lines)


def _render_chat_tail(n=15):
    msgs = db.chat_since_epoch(limit=n)
    if not msgs:
        return "(tom chat)"
    out = []
    for m in msgs:
        who = {"user": "BRUKER", "responder": "RESPONDER",
               "brain": "HOVEDHJERNE", "system": "SYSTEM"}.get(m["role"], m["role"])
        out.append(f"{who}: {m['text'][:600]}")
    return "\n".join(out)


def _render_agent_status():
    q = db.queued_tasks()
    r = db.running_tasks()
    recent = list(db.db().agent_tasks.find({"status": {"$in": ["done", "failed", "cancelled"]}})
                  .sort("finished_ts", -1).limit(5))
    lines = [f"AGENTSTATUS: {len(q)} i kø, {len(r)} kjører."]
    for t in r:
        lines.append(f"  KJØRER [{t['_id']}] {t['title']}")
    for t in q:
        lines.append(f"  KØ [{t['_id']}] {t['title']}")
    for t in recent:
        res = (t.get("result") or "")[:200]
        lines.append(f"  FERDIG({t['status']}) [{t['_id']}] {t['title']} – {res}")
    return "\n".join(lines)


def _render_pending_proposals():
    props = db.pending_proposals()
    if not props:
        return ""
    lines = ["VENTENDE ADMIN-FORSLAG (venter på brukerens godkjenning – ikke "
             "foreslå det samme igjen):"]
    for p in props:
        lines.append(f"  [{p['_id']}] ({p['kind']}) {p['title']}")
    return "\n".join(lines)


def _build_call(kind, events):
    """Bygg system-blokker (stabile først, for caching) og user-prompt."""
    identity = prompts.get("brain_identity") + "\n\n" + prompts.get("brain_cycle_contract")
    index = memory.build_index()

    query = " ".join(e.get("text", "") for e in events) + " " + _render_chat_tail(6)
    if kind == "natt":
        sections = memory.all_sections()
        # hold arbeidssettet innenfor et romsligere natt-budsjett
        budget, chosen, used = 80_000, [], 0
        for s in sections:
            tk = s.get("tokens", 0)
            if used + tk > budget:
                break
            chosen.append(s)
            used += tk
        sections = chosen
    else:
        sections = memory.select_relevant(query)
    sections_txt = "RELEVANTE MINNESEKSJONER:\n\n" + memory.render_sections(sections) \
        if sections else "RELEVANTE MINNESEKSJONER: (ingen valgt)"

    state = db.get_state()
    parts = [
        f"KLOKKEN ER: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "ARBEIDSNOTAT (fra forrige syklus): " + (state.get("working_note") or "(tomt)"),
        "NYE HENDELSER:\n" + _render_events(events),
        "SISTE CHAT:\n" + _render_chat_tail(),
        _render_agent_status(),
    ]
    pending = _render_pending_proposals()
    if pending:
        parts.append(pending)
    js = jarvis_link.status_summary()
    if js:
        parts.append(js)
        parts.append("(Du kan legge ideer i Jarvis' kø ved å lage en tanke med "
                     "type 'ide' som starter med 'JARVIS-IDE: tittel :: hypotese')")
    if kind == "natt":
        parts.append(prompts.get("night_curation"))
    elif kind == "tanke":
        parts.append("Dette er en planlagt TANKE-ØKT i stillhet: ingen ytre "
                     "hendelser krever deg. Tenk videre på egne ideer, "
                     "prosjekter og forberedelser – eller konstater ærlig "
                     "tomgang hvis det ikke er noe reelt å gjøre.")
    parts.append("Utfør syklusens plikter og svar med KUN JSON-kontrakten.")
    user_prompt = "\n\n".join(parts)
    return [identity, index, sections_txt], user_prompt


def _apply_result(res, kind):
    """Effektuer hovedhjernens beslutninger. Returnerer beslutningssammendrag."""
    decisions = []

    for t in res.get("tanker") or []:
        txt = t.get("tekst", "") if isinstance(t, dict) else str(t)
        knd = t.get("type", "tanke") if isinstance(t, dict) else "tanke"
        if not txt:
            continue
        # Jarvis-idé-kanalen: "JARVIS-IDE: tittel :: hypotese"
        if txt.startswith("JARVIS-IDE:") and jarvis_link.enabled():
            body = txt[len("JARVIS-IDE:"):].strip()
            title, _, hyp = body.partition("::")
            if jarvis_link.add_idea(title.strip(), hyp.strip() or title.strip()):
                decisions.append(f"la idé i Jarvis-køen: {title.strip()}")
        db.add_thought(txt, knd)
    if res.get("tanker"):
        decisions.append(f"{len(res['tanker'])} tanker logget")

    msg = (res.get("chat_melding") or "").strip()
    if msg and msg.lower() != "null":
        db.add_chat("brain", msg, marker="💭 Hovedhjernen")
        decisions.append("supplerte i chatten")

    ops_done = memory.apply_ops(res.get("minne_ops") or [], actor="brain")
    decisions.extend(ops_done)

    for a in res.get("agent_oppgaver") or []:
        t = db.create_agent_task(a.get("tittel", "Uten tittel"),
                                 a.get("oppdrag", ""),
                                 a.get("type", "bygg"),
                                 int(a.get("prioritet", 3)))
        decisions.append(f"opprettet agentoppgave '{t['title']}'")

    for tid in res.get("avbryt_oppgaver") or []:
        try:
            db.db().agent_tasks.update_one(
                {"_id": ObjectId(str(tid)), "status": {"$in": ["queued", "running"]}},
                {"$set": {"status": "cancelled", "finished_ts": time.time()}})
            decisions.append(f"avbrøt oppgave {tid}")
        except Exception:
            pass

    for p in res.get("admin_forslag") or []:
        payload = {}
        if p.get("type") == "prompt":
            payload = {"prompt_navn": p.get("prompt_navn"),
                       "prompt_tekst": p.get("prompt_tekst")}
        db.add_admin_proposal(p.get("type", "arkitektur"),
                              p.get("tittel", "Forslag"),
                              p.get("beskrivelse", ""), payload)
        decisions.append(f"la admin-forslag: {p.get('tittel')}")

    note = res.get("arbeidsnotat")
    if note:
        db.set_state({"working_note": note})

    if res.get("stagnasjon"):
        db.set_state({"stagnation": True})
        decisions.append("flagget stagnasjon (ærlig tomgang)")
    else:
        db.set_state({"stagnation": False})

    return decisions


def run_cycle(kind="normal"):
    """Kjør en full hovedhjerne-syklus. kind: normal | tanke | natt."""
    events = db.unprocessed_events(limit=100)
    system_blocks, user_prompt = _build_call(kind, events)
    res = brain.brain_call("brain", user_prompt, system_blocks,
                           purpose=f"syklus:{kind}", expect_json=True)

    # Hovedhjernen kan be om flere seksjoner før den konkluderer
    wanted = res.get("onskede_seksjoner") or []
    if wanted:
        extra = memory.get_sections(wanted)
        if extra:
            system_blocks[2] = (system_blocks[2] + "\n\n=== ETTERSPURTE SEKSJONER ===\n\n" +
                                memory.render_sections(extra))
            user_prompt += ("\n\nDu har nå fått seksjonene du ba om. Svar på "
                            "nytt med komplett JSON.")
            res = brain.brain_call("brain", user_prompt, system_blocks,
                                   purpose=f"syklus:{kind}:oppfolging",
                                   expect_json=True)

    decisions = _apply_result(res, kind)
    db.mark_events_processed([e["_id"] for e in events])
    db.log_cycle(kind, res.get("observasjoner", ""), decisions)
    db.set_state({"last_cycle_ts": time.time(), "pulses_since_cycle": 0})
    if kind in ("tanke",):
        db.set_state({"last_think_ts": time.time()})
    if kind == "natt":
        db.set_state({"last_curation_day": datetime.date.today().isoformat()})
    return res, decisions
