"""Responderen (§5): rask chat-frontlinje. Svarer brukeren umiddelbart med
hovedminne-indeksen + relevante seksjoner + siste del av samtalen. Hver
melding ligger samtidig som hendelse i hjerteslaget, så hovedhjernen kan
supplere, korrigere eller sette agenter i sving i neste syklus.
"""
import time

from . import brain, db, memory, prompts


def _answer(pending):
    chat_tail = db.chat_since_epoch(limit=20)
    convo = []
    for m in chat_tail:
        who = {"user": "BRUKER", "responder": "DEG",
               "brain": "HOVEDHJERNEN (💭)", "system": "SYSTEM"}.get(m["role"], m["role"])
        convo.append(f"{who}: {m['text']}")
    query = " ".join(m["text"] for m in pending)
    sections = memory.select_relevant(query, budget_tokens=12_000)
    system_blocks = [
        prompts.get("responder"),
        memory.build_index(),
        ("RELEVANTE MINNESEKSJONER:\n\n" + memory.render_sections(sections))
        if sections else "RELEVANTE MINNESEKSJONER: (ingen)",
    ]
    user_prompt = ("SAMTALEN SÅ LANGT:\n" + "\n".join(convo) +
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
