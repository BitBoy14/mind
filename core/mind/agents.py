"""Agent-rammeverket (§2): arbeidere med smale oppdrag, parallelt der det gir
mening. Byggeoppgaver kjøres som headless Claude Code med verktøy i egen
arbeidskatalog; rene tekst/analyse-oppgaver kan gå via Motor A. Resultater
leveres tilbake som hendelser hovedhjernen vurderer i neste pulsslag.

Kansellering er kooperativ OG fysisk: hver agent får sin egen prosessgruppe,
PID-en lagres i oppgavedokumentet ved oppstart, og et avbruddsflagg fører til
at gruppen faktisk drepes (SIGTERM → SIGKILL) og verifiseres død før noen
slutt-status skrives. Se procctl.py.
"""
import json
import os
import re
import subprocess
import threading
import time

from . import brain, config, db, memory, procctl, prompts

_active = {}  # task_id(str) -> Thread
_cancelling = set()  # task_id(str) som har et pågående kanselleringsforsøk
_lock = threading.Lock()

SKIP_DIRS = {"venv", "node_modules", ".git", "__pycache__"}

# BSON-dokumentgrensen er 16 MB; hold detaljminnet trygt godt under det.
MAX_DETAIL_CHARS = 500_000

AGENT_TIMEOUT_S = 3600

# Hvor mye av agentsvaret som følger med agent_done-hendelsen. Hele svaret
# ligger alltid i detaljminnet, men hovedhjernen leser hendelsen FØRST og
# handlet tidligere på et 250-tegns utdrag – da forsvant konklusjonen.
RESULTAT_CHARS = 4000

# Peker agenten på en leveransefil med absolutt sti, tar vi med starten av
# selve filen. Bare tekstlignende filtyper leses, og hemmelighetskataloger
# hoppes over – utdraget havner både i Mongo og i hovedhjernens prompt.
LEVERANSE_CHARS = 3000
LEVERANSE_EXT = (".md", ".txt", ".json", ".csv", ".log", ".yml", ".yaml")
LEVERANSE_SKIP = ("/.ssh/", "/.aws/", "/.gnupg/", "/.claude/", "/.git/")
_ABS_PATH_RE = re.compile(r"(?<![\w/])(/(?:[\w.@+-]+/)*[\w.@+-]+\.[A-Za-z0-9]+)")

# Fil agenten selv kan se etter i arbeidskatalogen sin (kooperativt steg før
# signalene): eksisterer den, er oppdraget avbrutt.
CANCEL_MARKER = ".mind_cancel"


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
            f"Screenshot-verktøyet ligger på "
            f"{config.BASE_DIR}/tools/screenshot.sh — bruk det slik omtalt "
            "over dersom oppdraget krever et visuelt bevis.\n\n"
            "AVBRUDD: dukker filen ./" + CANCEL_MARKER + " opp i arbeidskatalogen "
            "din, er oppdraget avbrutt – stopp umiddelbart uten å fullføre "
            "flere irreversible steg. Sjekk den før hvert irreversibelt steg "
            "(push, sletting, tjenesteendring) i lange oppdrag.\n\n"
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
    # start_new_session ⇒ egen sesjon og egen prosessgruppe (pgid == pid).
    # Da kan HELE treet – claude og alt den selv starter – drepes samlet ved
    # kansellering, i stedet for at foreldreløse barn jobber videre.
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env,
                            cwd=workdir, start_new_session=True)
    pgid = procctl.pgid_of(proc.pid)
    # Registreres FØR vi venter: et avbrudd som kommer i neste sekund skal
    # finne noe å drepe.
    db.register_task_process(task["_id"], {
        "kind": "claude_code", "pid": proc.pid, "pgid": pgid,
        "starttime": procctl.proc_starttime(proc.pid),
        "started_ts": time.time(), "host": os.uname().nodename,
        "cmd": " ".join(cmd), "exited_ts": None, "returncode": None,
    })
    try:
        out, err = proc.communicate(_full_brief(task), timeout=AGENT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        kill = procctl.kill_group(proc.pid, pgid)
        proc.communicate()  # høst prosessen etter drapet
        db.mark_task_process_exited(task["_id"], proc.returncode)
        raise RuntimeError("agent (claude -p) tidsavbrudd etter %d s – %s" %
                           (AGENT_TIMEOUT_S, procctl.summarize(kill)))
    db.mark_task_process_exited(task["_id"], proc.returncode)
    out = (out or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError("agent (claude -p) feilet rc=%d: %s" %
                           (proc.returncode, (err or out or "")[-1200:]))
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


def _leveranse_utdrag(result):
    """Finn leveransefilen agenten peker på i svaret, og les starten av den.

    Agenter skriver ofte konklusjonen sin i en fil (typisk /tmp/*.md) og nevner
    bare stien i svaret. Uten innholdet må hovedhjernen gjette.

    Aldri kritisk: finner vi ingenting lesbart, returnerer vi (None, None).
    Hendelsesskrivingen skal ikke kunne feile på grunn av en manglende fil.
    """
    try:
        seen = []
        for m in _ABS_PATH_RE.finditer(result or ""):
            p = m.group(1)
            if p not in seen:
                seen.append(p)
        for path in seen[:30]:
            if not path.lower().endswith(LEVERANSE_EXT):
                continue
            if any(skip in path for skip in LEVERANSE_SKIP):
                continue
            try:
                if not os.path.isfile(path):
                    continue
                with open(path, "r", errors="replace") as f:
                    text = f.read(LEVERANSE_CHARS + 1)
            except OSError:
                continue
            if not text.strip():
                continue
            if len(text) > LEVERANSE_CHARS:
                text = text[:LEVERANSE_CHARS] + "\n[... avkortet, se filen ...]"
            return path, text
    except Exception:
        pass
    return None, None


def run_task(task):
    tid = task["_id"]
    workdir = _workdir(tid)
    # Betinget: rekker et avbrudd å komme mellom køplukk og oppstart, skal vi
    # ikke skrive oppgaven tilbake til 'running'.
    if db.update_task_if_active(tid, {
            "status": "running", "started_ts": time.time(),
            "progress": "agenten arbeider …", "workdir": workdir}) == 0:
        return
    try:
        s = db.get_settings()
        model = s.get("agent_model")
        text_only = (s.get("engine") == "api" and
                     task.get("type") in ("skriv", "analyser", "undersok"))
        if text_only:
            # Tekstagenten har ingen egen prosess – kallet lever i denne
            # tråden. Registrer det, så kansellering kan si det ærlig i
            # stedet for å påstå at noe ble drept.
            db.register_task_process(tid, {
                "kind": "api", "pid": None, "pgid": None, "starttime": None,
                "started_ts": time.time(), "host": os.uname().nodename,
                "cmd": "brain.brain_call(agent)", "exited_ts": None,
                "returncode": None})
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
        if db.update_task_if_active(tid, {
                "status": "done", "finished_ts": time.time(),
                "result": (result or "")[-8000:], "files": files,
                "progress": ""}) == 0:
            # Oppgaven var flagget avbrutt, men arbeidet ble fullført likevel.
            # Nettopp dette skjedde med b065 og b12f – det skal stå svart på
            # hvitt i dokumentet, ikke skjules bak en pen 'cancelled'.
            _finish_completed_despite_cancel(task, result, files)
            return
        detail_id = None
        if result:
            full = result
            if len(full) > MAX_DETAIL_CHARS:
                full = full[:MAX_DETAIL_CHARS] + (
                    "\n\n[... avkortet, %d tegn totalt ...]" % len(result))
            detail_id = memory.add_detail(
                f"Agentresultat: {task['title']} [{tid}]", full, source="agent")
        payload = {"task_id": str(tid),
                   "resultat": (result or "")[:RESULTAT_CHARS],
                   "filer": files[:30]}
        if detail_id:
            payload["detalj_id"] = str(detail_id)
        lev_sti, lev_tekst = _leveranse_utdrag(result)
        if lev_tekst:
            payload["leveranse_fil"] = lev_sti
            payload["leveranse_utdrag"] = lev_tekst
        db.log_event("agent_done",
                     f"Agent ferdig: {task['title']}",
                     payload, priority=2)
    except Exception as e:
        if db.update_task_if_active(tid, {
                "status": "failed", "finished_ts": time.time(),
                "result": f"FEILET: {e}", "progress": ""}) == 0:
            # Feilen er nesten alltid at vi nettopp drepte prosessen. Ikke
            # skriv status her – kanselleringssveipet eier slutt-statusen og
            # skriver den først når drapet er verifisert.
            db.update_task(tid, {"thread_finished_ts": time.time(),
                                 "result": f"AVBRUTT: {e}"})
            return
        db.log_event("agent_failed",
                     f"Agent feilet: {task['title']} – {e}",
                     {"task_id": str(tid)}, priority=2)
    finally:
        with _lock:
            _active.pop(str(tid), None)


def _finish_completed_despite_cancel(task, result, files):
    """En avbrutt oppgave som likevel kjørte ferdig: si det rett ut.

    Status blir 'cancel_failed', ikke 'cancelled' – ellers ville dashbordet
    hevde at arbeidet ble stanset mens det i virkeligheten ble utført.
    """
    tid = task["_id"]
    note = {"result": "completed_despite_cancel", "verified_dead": False,
            "detail": "prosessen rakk å fullføre arbeidet før/til tross for "
                      "avbruddet – resultatet er beholdt",
            "signals": [], "ts": time.time()}
    db.db().agent_tasks.update_one({"_id": tid}, {
        "$set": {"status": "cancel_failed", "finished_ts": time.time(),
                 "result": "AVBRUTT, MEN ARBEIDET BLE LIKEVEL FULLFØRT:\n\n" +
                           (result or "")[-7000:],
                 "files": files, "progress": ""},
        "$push": {"cancel_log": note}})
    db.log_event("agent_cancel_failed",
                 "Avbrutt agent fullførte likevel: %s – slutt-tilstanden på "
                 "systemet må verifiseres." % task.get("title", ""),
                 {"task_id": str(tid), "kill": note}, priority=1)


# ------------------------------------------------------------- kansellering

def _write_cancel_marker(task):
    """Kooperativt steg: legg avbruddsflagget i agentens egen arbeidskatalog
    (den er instruert om å se etter det) før vi tyr til signaler."""
    wd = task.get("workdir") or _workdir(task["_id"])
    try:
        with open(os.path.join(wd, CANCEL_MARKER), "w") as f:
            f.write("AVBRUTT %s av %s\n%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                task.get("cancel_requested_by", "?"),
                task.get("cancel_reason", "")))
    except OSError:
        pass


def _enforce_cancel(task):
    """Håndhev ett avbruddsflagg: drep prosessgruppen og skriv VERIFISERT
    slutt-status.

    Regelen som gjør dette til noe annet enn før: 'cancelled' skrives kun når
    /proc bekrefter at prosessen er borte. Overlever den – eller finnes det
    ingen prosess å drepe mens arbeidertråden fortsatt lever – sier
    dokumentet det, og statusen blir 'cancel_failed' eller forblir
    'cancelling'. Status skal aldri være penere enn virkeligheten.
    """
    tid = task["_id"]
    _write_cancel_marker(task)
    p = task.get("process") or {}

    if not p and task.get("status") == "queued":
        kill = {"result": "not_started", "verified_dead": True, "signals": [],
                "detail": "oppgaven sto i kø – ingen prosess var startet",
                "ts": time.time()}
    else:
        kill = procctl.kill_group(p.get("pid"), p.get("pgid"),
                                  p.get("starttime"))

    with _lock:
        thread_alive = str(tid) in _active

    if thread_alive and kill.get("result") in ("no_pid", "not_started"):
        # Ingenting å drepe, men arbeidertråden lever fortsatt (tekstagent
        # via API, eller en oppgave startet før denne mekanismen fantes).
        # Da kan vi ikke påstå at oppgaven er stanset – vent og prøv igjen.
        kill = dict(kill, verified_dead=False, result="thread_alive",
                    detail=kill["detail"] + " – men arbeidertråden lever "
                                            "fortsatt, avventer verifikasjon")
        db.note_cancel_progress(tid, kill,
                                "avbrudd bestilt – venter på at tråden avslutter")
        return

    status = "cancelled" if kill.get("verified_dead") else "cancel_failed"
    db.record_cancel_outcome(tid, kill, status)
    db.log_event("agent_cancelled" if status == "cancelled"
                 else "agent_cancel_failed",
                 "Avbrutt (%s): %s – %s" % (status, task.get("title", ""),
                                            procctl.summarize(kill)),
                 {"task_id": str(tid), "kill": kill},
                 priority=2 if status == "cancelled" else 1)


def _enforce_cancel_safe(task):
    try:
        _enforce_cancel(task)
    except Exception as e:
        db.log_event("error", "kansellering feilet for %s: %s"
                     % (task.get("_id"), e), priority=2)
    finally:
        with _lock:
            _cancelling.discard(str(task["_id"]))


def enforce_cancellations():
    """Sveip over flaggede oppgaver. Hvert drap kjøres i egen tråd, så en
    treg prosess ikke stopper køplukkingen."""
    for t in db.tasks_awaiting_cancel():
        tid = str(t["_id"])
        with _lock:
            if tid in _cancelling:
                continue
            _cancelling.add(tid)
        threading.Thread(target=_enforce_cancel_safe, args=(t,), daemon=True,
                         name=f"cancel-{tid}").start()


def requeue_orphans():
    """Etter daemon-restart: oppgaver som sto som 'running' uten levende tråd
    legges tilbake i køen (tilstanden gjenopptas fra MongoDB, §2).

    Flaggede oppgaver gjenopplives aldri – de går til kanselleringssveipet,
    som verifiserer at prosessen er borte og skriver slutt-status."""
    db.db().agent_tasks.update_many(
        {"status": "running", "cancel_requested": {"$ne": True}},
        {"$set": {"status": "queued", "progress": "re-køet etter restart"}})


def manager_loop(stop_event):
    """Kjøres som egen tråd: plukker køede oppgaver og kjører dem parallelt
    (23 kjerner skal utnyttes – taket styres av innstillingen)."""
    while not stop_event.is_set():
        try:
            # Kanselleringer håndheves ALLTID – også når systemet står på
            # pause. Et avbrudd skal ikke vente på at noen trykker start.
            enforce_cancellations()
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
