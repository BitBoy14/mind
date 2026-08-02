"""Orkestrator-daemonen (§2): eier hjerteslag-loopen, køene, agent-trådene og
all tilstand i MongoDB. Kjøres som systemd-service med restart-policy; ved
restart gjenopptas alt fra MongoDB.

Kjør: core/venv/bin/python -m mind.daemon
"""
import datetime
import logging
import os
import threading
import time

from . import agents, config, cycle, db, memory, pulse, responder

log = logging.getLogger("mind")


def _setup_logging():
    os.makedirs(config.LOGS_DIR, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(config.LOGS_DIR, "daemon.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _next_interval(current):
    """Nedtrapping ved stillhet: 10s -> 30s -> 60s -> 300s."""
    steps = config.PULSE_STEPS
    for s in steps:
        if s > current:
            return s
    return steps[-1]


def _resource_check(state):
    """Overvåk eget ressursforbruk – varsle i dashbordet, aldri stille feiling (§1)."""
    try:
        import psutil
        disk = psutil.disk_usage("/")
        mem = psutil.virtual_memory()
        problems = []
        if disk.percent >= 85:
            problems.append(f"disk {disk.percent:.0f}% full")
        if mem.percent >= 90:
            problems.append(f"RAM {mem.percent:.0f}% brukt")
        if problems:
            today = datetime.date.today().isoformat()
            if state.get("last_resource_warn_day") != today:
                msg = "Ressursvarsel: " + ", ".join(problems)
                db.log_event("resource_warning", msg, priority=1)
                db.add_admin_proposal(
                    "ressurs", "Ressursoppgradering anbefales",
                    msg + ". Serveren kan oppgraderes (RAM til 200 GB, disk "
                    "til 300 GB) – eller jeg kan rydde. Godkjenn for at jeg "
                    "skal lage en plan.")
                db.set_state({"last_resource_warn_day": today})
        db.set_state({"resources": {"disk_pct": disk.percent,
                                    "mem_pct": mem.percent,
                                    "load": os.getloadavg()[0],
                                    "ts": time.time()}})
    except Exception as e:
        log.warning("ressurssjekk feilet: %s", e)


def _run_cycle_safe(kind):
    try:
        res, decisions = cycle.run_cycle(kind)
        log.info("syklus (%s): %d beslutninger", kind, len(decisions))
    except Exception as e:
        log.exception("syklus feilet")
        db.log_event("error", f"hovedhjerne-syklus ({kind}) feilet: {e}",
                     priority=2)
        # ikke la en feilende syklus spinne på samme hendelser i hvert pulsslag
        db.set_state({"last_cycle_ts": time.time(), "pulses_since_cycle": 0})


def heartbeat():
    """Nivå 1-loopen: adaptiv rytme, puls-vakt, vekking av hovedhjernen."""
    state = db.get_state()
    interval = state.get("pulse_interval", config.PULSE_MIN)
    last_pulse = 0.0
    last_resource = 0.0
    last_seen_event_ts = 0.0

    while True:
        try:
            time.sleep(1)
            s = db.get_settings()
            now = time.time()

            if now - last_resource > 600:
                _resource_check(db.get_state())
                last_resource = now

            if not s.get("running"):
                db.set_state({"paused": True, "last_pulse_ts": now,
                              "pulse_interval": interval})
                continue

            # Enhver ny hendelse resetter rytmen til 10 sek umiddelbart
            newest = db.db().events.find_one({"processed": False},
                                             sort=[("ts", -1)])
            if newest and newest["ts"] > last_seen_event_ts:
                last_seen_event_ts = newest["ts"]
                interval = config.PULSE_MIN

            if now - last_pulse < interval:
                continue

            # ---- pulsslag ----
            last_pulse = now
            state = db.get_state()
            events = db.unprocessed_events()
            db.set_state({"paused": False, "last_pulse_ts": now,
                          "pulse_interval": interval})

            if events:
                wake, why = pulse.decide(events, state.get("working_note", ""))
                pulses = state.get("pulses_since_cycle", 0) + 1
                if not wake and pulses >= config.FORCE_CYCLE_EVERY_N_PULSES:
                    wake, why = True, "tvungen syklus (minst hvert N. pulsslag)"
                if wake:
                    log.info("vekker hovedhjernen: %s", why)
                    _run_cycle_safe("normal")
                    interval = config.PULSE_MIN
                else:
                    db.set_state({"pulses_since_cycle": pulses})
            else:
                # stillhet: trapp ned rytmen
                interval = _next_interval(interval)

                # Døgnbudsjettet bremser bare det AUTONOME arbeidet. En syklus
                # utløst av noe brukeren gjorde, og chatten, går alltid – det
                # skal aldri virke som om hjernen er død fordi den har tenkt
                # for mye på egen hånd.
                brukt, budsjett, tomt = db.budget_state()
                if tomt:
                    if not state.get("budget_notified_day") == \
                            datetime.date.today().isoformat():
                        log.info("døgnbudsjett brukt opp (%d/%d) – autonome "
                                 "økter pauses til midnatt", brukt, budsjett)
                        db.log_event(
                            "budget_exhausted",
                            f"Døgnbudsjettet er brukt opp ({brukt:,} av "
                            f"{budsjett:,} ut-tokens). Autonome tanke-økter og "
                            "natt-økten står til midnatt; chatten svarer som "
                            "vanlig.".replace(",", " "), priority=3)
                        db.set_state({"budget_notified_day":
                                      datetime.date.today().isoformat()})
                    continue

                # natt-økt: grundig kuratering én gang i døgnet
                hour = datetime.datetime.now().hour
                today = datetime.date.today().isoformat()
                if (hour == int(s.get("night_curation_hour", 3)) and
                        state.get("last_curation_day") != today):
                    log.info("starter natt-økt (kuratering)")
                    _run_cycle_safe("natt")
                    continue

                # planlagt tanke-økt i tomgangstid
                if now - state.get("last_think_ts", 0) > config.IDLE_THINK_INTERVAL_S:
                    log.info("starter tanke-økt (autonom tid)")
                    _run_cycle_safe("tanke")

        except Exception as e:
            log.exception("hjerteslag-feil")
            try:
                db.log_event("error", f"hjerteslag: {e}", priority=3)
            except Exception:
                pass
            time.sleep(5)


def main():
    _setup_logging()
    log.info("MIND-daemon starter …")
    db.ensure_indexes()
    memory.ensure_seed()
    db.get_settings()
    agents.requeue_orphans()
    db.set_state({"daemon_started_ts": time.time()})
    db.log_event("system", "MIND-daemonen startet (hjertet slår).", priority=4)

    stop = threading.Event()
    threading.Thread(target=responder.loop, args=(stop,), daemon=True,
                     name="responder").start()
    threading.Thread(target=agents.manager_loop, args=(stop,), daemon=True,
                     name="agent-manager").start()
    try:
        heartbeat()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
