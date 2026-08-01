"""Responderen (§5): rask chat-frontlinje. Svarer brukeren umiddelbart med
hovedminne-indeksen + relevante seksjoner + siste del av samtalen. Hver
melding ligger samtidig som hendelse i hjerteslaget, så hovedhjernen kan
supplere, korrigere eller sette agenter i sving i neste syklus.

Ferskhetsvinduet: minnet er alltid ETTER samtalen – en melding er ikke i
minnet før hovedhjernen har kuratert den inn i en senere syklus. Responderen
får derfor den ferskeste råloggen med tidsstempel, pluss de chat_msg-
hendelsene hovedhjernen ennå ikke har behandlet, tydelig merket som «kan
mangle i minnet ennå». Uten dette benektet responderen bestillinger brukeren
nettopp hadde lagt inn (observert 2026-08-01), fordi den behandlet det
kuraterte minnet som fasit.
"""
import datetime
import time

from . import brain, db, memory, prompts

FRESH_MSG_COUNT = 10            # antall ferske chatmeldinger som råloggføres
FRESH_MSG_CHARS = 700           # per melding/hendelse
FRESH_EVENT_MAX_CHARS = 2000    # hendelsesdelen av blokken
FRESH_BLOCK_MAX_CHARS = 8000    # hardt tak på hele tilleggsteksten

ROLE_LABEL = {"user": "BRUKER", "responder": "DEG",
              "brain": "HOVEDHJERNEN (💭)", "system": "SYSTEM"}

FRESH_HEADER = ("FERSKE MELDINGER (kan mangle i minnet ennå – rå chatlogg, "
                "nyest sist; disse er sanne selv om minnet ikke nevner dem):\n")


def _who(role):
    return ROLE_LABEL.get(role, role)


def _clock(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _trim(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " […]"


def _fresh_messages(chat_tail, pending):
    """De ferskeste meldingene – med de ubesvarte garantert med.

    Vinduet er de siste FRESH_MSG_COUNT meldingene, men skulle brukeren ha
    sendt flere ubesvarte enn vinduet rommer, skal ingen av dem falle ut:
    det er nettopp de responderen skal svare på.
    """
    fresh = list(chat_tail[-FRESH_MSG_COUNT:])
    seen = {m.get("_id") for m in fresh}
    fresh += [m for m in pending if m.get("_id") not in seen]
    return sorted(fresh, key=lambda m: m.get("ts", 0))


def _render_fresh(fresh, events):
    """Rålogg-blokken, hardt begrenset til FRESH_BLOCK_MAX_CHARS tegn.

    Hendelsesdelen får sitt eget budsjett først; resten går til meldingene, og
    blir det trangt ofres de ELDSTE linjene – aldri de nyeste.
    """
    ev_block = ""
    if events:
        ev_block = ("\n\nUPROSESSERTE HENDELSER (chat_msg – hovedhjernen har "
                    "ikke lest disse enda):\n" + "\n".join(
                        f"- [{_clock(e['ts'])}] {_trim(e.get('text', ''), FRESH_MSG_CHARS)}"
                        for e in events))[:FRESH_EVENT_MAX_CHARS]
    budget = FRESH_BLOCK_MAX_CHARS - len(FRESH_HEADER) - len(ev_block)
    kept, used = [], 0
    for m in reversed(fresh):
        line = (f"[{_clock(m['ts'])}] {_who(m.get('role'))}: "
                f"{_trim(m.get('text', ''), FRESH_MSG_CHARS)}")
        if used + len(line) + 1 > budget:
            break
        kept.insert(0, line)
        used += len(line) + 1
    if not kept:
        kept = ["(ingen ferske meldinger)"]
    return FRESH_HEADER + "\n".join(kept) + ev_block


def _answer(pending):
    chat_tail = db.chat_since_epoch(limit=20)
    fresh = _fresh_messages(chat_tail, pending)
    fresh_ids = {m.get("_id") for m in fresh}
    # Den eldre delen av samtalen; den ferske delen rendres rått under.
    convo = [f"{_who(m.get('role'))}: {m['text']}"
             for m in chat_tail if m.get("_id") not in fresh_ids]
    try:
        fresh_events = db.unprocessed_events_of_type("chat_msg", limit=20)
    except Exception:
        fresh_events = []   # rålogg er et tillegg – aldri en grunn til å tie
    query = " ".join(m["text"] for m in pending)
    sections = memory.select_relevant(query, budget_tokens=12_000)
    system_blocks = [
        prompts.get("responder"),
        memory.build_index(),
        ("RELEVANTE MINNESEKSJONER:\n\n" + memory.render_sections(sections))
        if sections else "RELEVANTE MINNESEKSJONER: (ingen)",
    ]
    user_prompt = ("SAMTALEN SÅ LANGT (tidligere del):\n" +
                   ("\n".join(convo) if convo else "(ingen tidligere meldinger)") +
                   "\n\n" + _render_fresh(fresh, fresh_events) +
                   "\n\nSvar nå på brukerens siste melding(er). Svar kun med "
                   "selve svaret, ingen merkelapper.")
    return brain.brain_call("responder", user_prompt, system_blocks,
                            purpose="chat-svar", expect_json=False,
                            max_tokens=2000)


def loop(stop_event):
    """Egen tråd: sjekker for ubesvarte brukermeldinger hvert sekund."""
    while not stop_event.is_set():
        try:
            s = db.get_settings()
            if s.get("running"):
                pending = db.unanswered_user_messages()
                if pending:
                    try:
                        text = _answer(pending)
                        db.add_chat("responder", text)
                    except Exception as e:
                        db.add_chat("system",
                                    f"(responderen feilet: {e} – hovedhjernen "
                                    "følger opp i neste pulsslag)")
                        db.log_event("error", f"responder: {e}", priority=3)
                    db.mark_chat_answered([m["_id"] for m in pending])
        except Exception as e:
            db.log_event("error", f"responder-loop: {e}", priority=4)
            time.sleep(5)
        stop_event.wait(1)
