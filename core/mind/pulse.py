"""Puls-vakten (§3.1): billig, rask nivå-1-sjekk. Ren mekanikk der kode
holder; LLM (Haiku) kun når det faktisk er en vurderingssak.
"""
from . import brain, db, prompts

# Hendelsestyper som ALLTID vekker hovedhjernen uten LLM-kall
ALWAYS_WAKE = {"agent_done", "agent_failed", "comment", "admin_decision",
               "user_command", "resource_warning"}
# Ren støy: markeres prosessert uten å vekke noen
NOISE = {"backoff"}


def decide(events, working_note):
    """Returner (vekk: bool, hvorfor: str). Mekaniske snarveier først."""
    real = [e for e in events if e["type"] not in NOISE]
    noise = [e for e in events if e["type"] in NOISE]
    if noise:
        db.mark_events_processed([e["_id"] for e in noise])
    if not real:
        return False, "ingen reelle hendelser"

    if any(e["type"] in ALWAYS_WAKE or e.get("priority", 3) <= 1 for e in real):
        return True, "høyprioritetshendelse (mekanisk regel)"

    # Vurderingssak → puls-vakten (billig modell) avgjør
    lines = [f"- ({e['type']}, prio {e.get('priority', 3)}) {e.get('text', '')[:200]}"
             for e in real[:20]]
    user_prompt = ("NYE HENDELSER SIDEN SIST:\n" + "\n".join(lines) +
                   "\n\nHOVEDHJERNENS ARBEIDSNOTAT: " +
                   (working_note or "(tomt)") +
                   "\n\nSkal hovedhjernen vekkes? Svar med JSON.")
    try:
        res = brain.brain_call("pulse", user_prompt,
                               [prompts.get("pulse_guard")],
                               purpose="puls-vakt", expect_json=True,
                               max_attempts=2, max_tokens=300)
        return bool(res.get("vekk_hovedhjernen")), res.get("hvorfor", "")
    except Exception as e:
        # Ved tvil/feil: vekk hovedhjernen – bedre én syklus for mye enn tapt info
        return True, f"puls-vakt feilet ({e}); vekker for sikkerhets skyld"
