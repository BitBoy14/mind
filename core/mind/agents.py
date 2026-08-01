"""Agent-rammeverket (§2): arbeidere med smale oppdrag, parallelt der det gir
mening. Byggeoppgaver kjøres som headless Claude Code med verktøy i egen
arbeidskatalog; rene tekst/analyse-oppgaver kan gå via Motor A. Resultater
leveres tilbake som hendelser hovedhjernen vurderer i neste pulsslag.
"""
import json
import os
import subprocess
import threading
import time

from . import brain, config, db, memory, prompts

_active = {}  # task_id(str) -> Thread
_lock = threading.Lock()

SKIP_DIRS = {"venv", "node_modules", ".git", "__pycache__"}

# BSON-dokumentgrensen er 16 MB; hold detaljminnet trygt godt under det.
MAX_DETAIL_CHARS = 500_000


def _workdir(task_id):
    d = os.path.join(config.AGENTWORK_DIR, str(task_id))
    os.makedirs(d, exist_ok=True)
    return d


def _list_files(root, limit=200):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            out.append(rel)
            if len(out) >= limit:
                return out
    return sorted(out)


def _full_brief(task):
    return (prompts.get("agent_preamble") +
            "\n\nHvis oppdraget gjelder plattformkoden i "
            f"{config.BASE_DIR}: gjør endringene der og commit i git med "
            "beskrivende melding (git add -A && git commit -m '...').\n\n"
            f"=== OPPDRAG: {task['title']} ===\n\n{task['brief']}")


def _run_claude_agent(task, workdir, model):
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
    ]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    t0 = time.time()
    proc = subprocess.run(cmd, input=_full_brief(task), capture_output=True,
                          text=True, timeout=3600, env=env, cwd=workdir)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError("agent (claude -p) feilet rc=%d: %s" %
                           (proc.returncode, (proc.stderr or out or "")[-1200:]))
    data = json.loads(out)
    u = data.get("usage", {}) or {}
    db.log_tokens("agent", "claude_code", model, {
        "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_creation": u.get("cache_creation_input_tokens", 0),
    }, f"agent:{task['title'][:40]}", (time.time() - t0) * 1000)
    return data.get("result", "")


def _run_api_agent(task, model):
    return brain.brain_call("agent", _full_brief(task),
                            ["Du er en tekstagent for MIND. Løs oppdraget "
                             "grundig og lever hele resultatet som tekst."],
                            purpose=f"agent:{task['title'][:40]}",
                            expect_json=False, model=model)


def run_task(task):
    tid = task["_id"]
    workdir = _workdir(tid)
    db.update_task(tid, {"status": "running", "started_ts": time.time(),
                         "progress": "agenten arbeider …", "workdir": workdir})
    try:
        s = db.get_settings()
        model = s.get("agent_model")
        text_only = (s.get("engine") == "api" and
                     task.get("type") in ("skriv", "analyser", "undersok"))
        if text_only:
            result = _run_api_agent(task, model)
            files = []
            if result:
                path = os.path.join(workdir, "resultat.md")
                with open(path, "w") as f:
                    f.write(result)
                files = ["resultat.md"]
        else:
            result = _run_claude_agent(task, workdir, model)
            files = _list_files(workdir)
        db.update_task(tid, {"status": "done", "finished_ts": time.time(),
                             "result": (result or "")[-8000:], "files": files,
                             "progress": ""})
        detail_id = None
        if result:
            full = result
            if len(full) > MAX_DETAIL_CHARS:
                full = full[:MAX_DETAIL_CHARS] + (
                    "\n\n[... avkortet, %d tegn totalt ...]" % len(result))
            detail_id = memory.add_detail(
                f"Agentresultat: {task['title']} [{tid}]", full, source="agent")
        payload = {"task_id": str(tid), "resultat": (result or "")[:1500],
                   "filer": files[:30]}
        if detail_id:
            payload["detalj_id"] = str(detail_id)
        db.log_event("agent_done",
                     f"Agent ferdig: {task['title']}",
                     payload, priority=2)
    except Exception as e:
        db.update_task(tid, {"status": "failed", "finished_ts": time.time(),
                             "result": f"FEILET: {e}", "progress": ""})
        db.log_event("agent_failed",
                     f"Agent feilet: {task['title']} – {e}",
                     {"task_id": str(tid)}, priority=2)
    finally:
        with _lock:
            _active.pop(str(tid), None)


def requeue_orphans():
    """Etter daemon-restart: oppgaver som sto som 'running' uten levende tråd
    legges tilbake i køen (tilstanden gjenopptas fra MongoDB, §2)."""
    db.db().agent_tasks.update_many(
        {"status": "running"},
        {"$set": {"status": "queued", "progress": "re-køet etter restart"}})


def manager_loop(stop_event):
    """Kjøres som egen tråd: plukker køede oppgaver og kjører dem parallelt
    (23 kjerner skal utnyttes – taket styres av innstillingen)."""
    while not stop_event.is_set():
        try:
            s = db.get_settings()
            if s.get("running"):
                with _lock:
                    capacity = int(s.get("max_parallel_agents", 8)) - len(_active)
                if capacity > 0:
                    for task in db.queued_tasks()[:capacity]:
                        th = threading.Thread(target=run_task, args=(task,),
                                              daemon=True,
                                              name=f"agent-{task['_id']}")
                        with _lock:
                            _active[str(task["_id"])] = th
                        th.start()
        except Exception as e:
            db.log_event("error", f"agent-manager: {e}", priority=4)
        stop_event.wait(2)
