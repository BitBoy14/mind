"""Jarvis-kobling (§9). Kun aktiv når bryteren i dashbordet er PÅ.
Når AV: full separasjon – ingen lesing eller skriving mot Jarvis' data.
"""
import time

from . import db


def enabled():
    return bool(db.get_settings().get("jarvis_link", False))


def status_summary():
    """Kort statuslinje for hovedhjernens arbeidsminne."""
    if not enabled():
        return None
    try:
        j = db.jarvis_db()
        s = j.settings.find_one({"_id": "main"}) or {}
        by_status = {}
        for i in j.ideas.find({}, {"status": 1}):
            by_status[i.get("status", "?")] = by_status.get(i.get("status", "?"), 0) + 1
        recent = list(j.ideas.find({}, {"title": 1, "status": 1, "conclusion": 1})
                      .sort("created_ts", -1).limit(5))
        lines = ["JARVIS-STATUS (kobling PÅ): kjører=%s, ideer per status: %s" %
                 (s.get("running"), ", ".join(f"{k}={v}" for k, v in by_status.items()) or "ingen")]
        for i in recent:
            c = (" – " + i["conclusion"][:80]) if i.get("conclusion") else ""
            lines.append(f"  [{i.get('status')}] {i.get('title', '?')}{c}")
        return "\n".join(lines)
    except Exception as e:
        return f"JARVIS-STATUS: kunne ikke leses ({e})"


def add_idea(title, hypothesis):
    """Legg en idé i Jarvis' kø (samme skjema som Jarvis' egen ideation)."""
    if not enabled():
        return False
    j = db.jarvis_db()
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:40].strip("-")
    if j.ideas.find_one({"slug": slug}):
        slug = f"{slug}-{int(time.time()) % 10000}"
    top = j.ideas.find_one(sort=[("priority", -1)])
    prio = (top["priority"] + 1) if top and "priority" in top else 1
    j.ideas.insert_one({
        "slug": slug, "title": title, "hypothesis": hypothesis,
        "apriori": "Foreslått av MIND-hovedhjernen.",
        "status": "queued", "priority": prio, "created_ts": time.time(),
        "learnings": "", "oos_history": [], "budget_used": 0,
        "budget_extensions": [],
    })
    return True
