"""Prosesskontroll for agentoppgaver – grunnlaget for kooperativ kansellering.

Bakgrunn: to bekreftede tilfeller 2026-08-01 der «avbrutte» agentoppgaver
likevel fullførte arbeidet (b065 renset git-historikk og pushet; b12f låste
mongod på nett) – fordi avbrytelse bare skrev status i MongoDB uten å røre
prosessen. Statusfeltet løy.

Denne modulen gjør avbrytelse til noe fysisk: hver agent kjøres i sin egen
sesjon (og dermed egen prosessgruppe), gruppen drepes samlet med SIGTERM →
SIGKILL, og /proc leses etterpå for å VERIFISERE at den faktisk er borte.
Ingen status skrives på intensjon – bare på observert virkelighet.

Sikring mot PID-gjenbruk: sammen med PID lagres prosessens starttid (felt 22
i /proc/<pid>/stat). Får en fremmed prosess senere samme PID, avviker
starttiden og vi nekter å signalere.
"""
import os
import signal
import time

TERM_GRACE_S = 10.0   # ventetid på at SIGTERM skal virke før vi eskalerer
KILL_GRACE_S = 5.0    # ventetid på at SIGKILL skal ta effekt
POLL_S = 0.1

PROC = "/proc"


def _stat(pid):
    """Utvalgte felt fra /proc/<pid>/stat: state, pgrp, starttime.

    None hvis prosessen ikke finnes. Felt 2 (comm) kan inneholde både
    mellomrom og parenteser, så vi klipper etter SISTE ')'.
    """
    try:
        with open("%s/%d/stat" % (PROC, int(pid)), "rb") as f:
            raw = f.read()
    except (OSError, ValueError, TypeError):
        return None
    try:
        tail = raw[raw.rindex(b")") + 2:].split()
        return {"state": tail[0].decode(),   # felt 3
                "pgrp": int(tail[2]),        # felt 5
                "starttime": int(tail[19])}  # felt 22
    except (ValueError, IndexError, UnicodeDecodeError):
        return None


def _is_live(st):
    """Zombier teller som døde – de venter bare på å bli høstet."""
    return bool(st) and st["state"] != "Z"


def proc_starttime(pid):
    """Prosessens starttid – identitetsnøkkelen som avslører PID-gjenbruk."""
    st = _stat(pid)
    return st["starttime"] if st else None


def pgid_of(pid):
    """Prosessgruppen til pid; faller tilbake til pid selv (start_new_session
    gir pgid == pid) hvis prosessen allerede er borte."""
    try:
        return os.getpgid(int(pid))
    except (OSError, ValueError, TypeError):
        return int(pid) if pid else 0


def pid_alive(pid, starttime=None):
    """True bare hvis PID-en lever OG er den samme prosessen vi startet."""
    st = _stat(pid)
    if not _is_live(st):
        return False
    if starttime is not None and st["starttime"] != int(starttime):
        return False
    return True


def group_members(pgid):
    """Levende (ikke-zombie) PID-er i prosessgruppen. Tom liste = borte."""
    out = []
    try:
        names = os.listdir(PROC)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        st = _stat(int(name))
        if _is_live(st) and st["pgrp"] == int(pgid):
            out.append(int(name))
    return sorted(out)


def kill_group(pid, pgid, starttime=None, term_grace=TERM_GRACE_S,
               kill_grace=KILL_GRACE_S):
    """Drep prosessgruppen og VERIFISER utfallet i /proc.

    Returnerer en ordbok som beskriver hva som faktisk skjedde:

      result         no_pid | refused | pid_reused | not_found |
                     killed_sigterm | killed_sigkill | survived
      verified_dead  True bare når /proc bekrefter at gruppen er borte
      signals        signalene som faktisk ble sendt
      survivors      PID-er som fortsatt lever (ved 'survived')
      detail         menneskelesbar begrunnelse (havner i oppgavedokumentet)

    Kalleren skal aldri skrive 'cancelled' uten at verified_dead er True.
    """
    pid = int(pid or 0)
    pgid = int(pgid or 0)
    info = {"pid": pid, "pgid": pgid, "starttime": starttime,
            "signals": [], "ts": time.time()}

    def done(result, verified, detail, survivors=None):
        info.update({"result": result, "verified_dead": verified,
                     "detail": detail, "survivors": survivors or [],
                     "finished_ts": time.time()})
        return info

    if not pid and not pgid:
        return done("no_pid", True, "ingen prosess registrert på oppgaven")

    # Aldri signalér oss selv, init, eller «alle prosesser» (pgid 0 / -1).
    if pgid <= 1 or pgid == os.getpgrp():
        return done("refused", False,
                    "nekter å signalere prosessgruppe %d (egen eller ugyldig "
                    "gruppe)" % pgid)

    # PID-gjenbruk: lever PID-en, men med en annen starttid, er vår prosess
    # for lengst borte – og vi kan ikke trygt skille gruppen fra en fremmed.
    if pid and starttime is not None:
        st = _stat(pid)
        if _is_live(st) and st["starttime"] != int(starttime):
            return done("pid_reused", True,
                        "PID %d tilhører nå en annen prosess (starttid %d != "
                        "%d) – agentprosessen er borte" %
                        (pid, st["starttime"], int(starttime)))

    members = group_members(pgid)
    if not members:
        return done("not_found", True,
                    "ingen levende prosesser i gruppe %d – allerede død" % pgid)
    info["members_before"] = members

    for sig, grace, label in ((signal.SIGTERM, term_grace, "killed_sigterm"),
                              (signal.SIGKILL, kill_grace, "killed_sigkill")):
        try:
            os.killpg(pgid, sig)
            info["signals"].append(sig.name)
        except ProcessLookupError:
            return done("not_found", True,
                        "gruppe %d forsvant før %s" % (pgid, sig.name))
        except PermissionError as e:
            return done("refused", False,
                        "ingen tilgang til å signalere gruppe %d: %s" % (pgid, e))
        deadline = time.time() + grace
        while True:
            alive = group_members(pgid)
            if not alive:
                return done(label, True,
                            "gruppe %d bekreftet død i /proc etter %s "
                            "(drepte %s)" % (pgid, sig.name, members))
            if time.time() >= deadline:
                break
            time.sleep(POLL_S)

    survivors = group_members(pgid)
    if not survivors:
        return done("killed_sigkill", True,
                    "gruppe %d bekreftet død i /proc etter SIGKILL" % pgid)
    return done("survived", False,
                "gruppe %d LEVER fortsatt etter SIGTERM+SIGKILL: %s" %
                (pgid, survivors), survivors)


def summarize(kill):
    """Én linje om utfallet – til hendelseslogg og dashbord."""
    return "%s: %s" % (kill.get("result", "?"), kill.get("detail", ""))
