"""Agentprosesser i egen systemd-scope – utenfor daemonens cgroup.

Bakgrunn: arbeidsagentene ble startet som vanlige barn av mind.service og
arvet dermed tjenestens cgroup. `systemctl restart mind` stopper HELE
cgroupen, så hver eneste kjørende agent ble drept midt i arbeidet – enda
agenten er en selvstendig prosess som fint kunne kjørt ferdig. Daemonen
kunne altså ikke oppdatere seg selv uten å ofre alt pågående arbeid.

Løsningen: hver agent registreres som en transient scope-enhet hos brukerens
systemd-manager (`systemd-run --user --scope`). Prosessen havner da i
/user.slice/user-<uid>.slice/user@<uid>.service/app.slice/<enhet>.scope,
altså utenfor /system.slice/mind.service, og berøres ikke av at daemonen
starter på nytt.

Hvorfor bruker-manageren og ikke en system-scope via sudo: `--scope` EXEC-er
kommandoen i stedet for å forke, så vi beholder alt det andre maskineriet
uendret – PID-en Popen gir oss ER agenten (procctl identifiserer den på
pid + starttid), prosessgruppen er fortsatt agentens egen (kill_group dreper
hele treet), og rørene for stdin/stdout/stderr går rett gjennom. I tillegg
beholdes HELE kredensialkonteksten: uid, gid og tilleggsgrupper. En
system-scope via sudo måtte satt --uid/--gid eksplisitt og ville dermed
stille droppet tilleggsgruppene agentene har i dag (www-data, docker, …).

Forutsetning: brukerens systemd-manager må kjøre. `loginctl enable-linger`
er satt for MIND-brukeren, så manageren står også uten innlogget sesjon.

Fail-safe: klarer vi ikke å lage en scope, startes agenten som før – i
daemonens cgroup. Da mister vi restart-overlevelsen, men oppgaven kjører.
Kalleren får vite hvilken vei det gikk i info-ordboken ('scoped').
"""
import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger("mind.scopes")

UNIT_PREFIX = "mind-agent-"

# En systemd-run som ikke får laget scopen (buss nede, navnekollisjon) dør
# nesten momentant – den gjør bare et bussanrop før exec. Vi ser den an noen
# hundre millisekunder, slik at feilen fanges her og ikke rapporteres som at
# selve agenten feilet.
STARTUP_PROBE_S = 0.5
PROBE_POLL_S = 0.025


def unit_name(task_id, suffix=""):
    """Enhetsnavn for en agentoppgave: mind-agent-<oppgave-id>[-<suffiks>].

    Navnet er forutsigbart med vilje – `systemctl --user list-units
    'mind-agent-*'` viser da nøyaktig hvilke agenter som lever akkurat nå.
    """
    base = "%s%s" % (UNIT_PREFIX, str(task_id))
    return base + ("-" + suffix if suffix else "")


def bus_env(env=None):
    """Miljø der systemd-run finner brukerbussen.

    mind.service setter bare PATH og PYTHONUNBUFFERED, så XDG_RUNTIME_DIR og
    DBUS_SESSION_BUS_ADDRESS mangler i daemonens miljø. Vi utleder dem fra
    uid-en i stedet for å kreve at enheten setter dem.
    """
    env = dict(env if env is not None else os.environ)
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % uid)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS",
                   "unix:path=%s/bus" % env["XDG_RUNTIME_DIR"])
    return env


def available(env=None):
    """(bool, begrunnelse) – ser scope-mekanismen brukbar ut akkurat nå?

    Lettvekts-sjekk: verktøyet finnes og brukerbussens socket er der. Er
    manageren likevel syk, feiler systemd-run ved oppstart og popen() faller
    tilbake – derfor holder det å luke ut de åpenbare tilfellene her.
    """
    if not shutil.which("systemd-run"):
        return False, "systemd-run finnes ikke i PATH"
    bus = os.path.join(bus_env(env)["XDG_RUNTIME_DIR"], "bus")
    if not os.path.exists(bus):
        return False, "brukerbussen mangler (%s)" % bus
    return True, ""


def cgroup_of(pid):
    """cgroup-stien til en prosess – bevis på hvor den faktisk havnet."""
    try:
        with open("/proc/%d/cgroup" % int(pid)) as f:
            return f.read().strip().split("::")[-1]
    except (OSError, ValueError, TypeError):
        return ""


def _spawn(cmd, env, kwargs):
    return subprocess.Popen(cmd, env=env, **kwargs)


def _wrap(unit, cmd):
    return ["systemd-run", "--user", "--scope", "--collect", "--quiet",
            "--unit=%s" % unit, "--"] + list(cmd)


def _died_early(proc):
    """Vent kort på at en mislykket systemd-run skal avsløre seg.

    Returnerer feilteksten hvis prosessen falt død om med rc != 0, ellers
    None. Selve agenten rekker aldri å bli ferdig på denne tiden, så en
    tidlig exit betyr i praksis alltid at scopen ikke ble laget.
    """
    deadline = time.time() + STARTUP_PROBE_S
    while time.time() < deadline:
        if proc.poll() is not None:
            if proc.returncode == 0:
                return None
            err = ""
            try:
                if proc.stderr:
                    err = proc.stderr.read() or ""
                else:
                    err = "(feilteksten gikk til kallerens stderr-fil)"
            except (OSError, ValueError):
                pass
            return "rc=%s %s" % (proc.returncode, err.strip()[:300])
        time.sleep(PROBE_POLL_S)
    return None


def _close(proc):
    for f in (proc.stdin, proc.stdout, proc.stderr):
        try:
            if f:
                f.close()
        except (OSError, ValueError):
            pass


def popen(cmd, unit, env=None, **kwargs):
    """Start `cmd` i sin egen systemd-scope. Returnerer (proc, info).

    info: {"scoped": bool, "unit": str|None, "cgroup": str, "detail": str}

    Faller tilbake til en helt vanlig Popen hvis scopen ikke lar seg lage –
    en agent som kjører i feil cgroup er alltid bedre enn en agent som ikke
    kjører. Ved navnekollisjon (enheten lever ennå fra en tidligere
    daemon-generasjon) prøves ett suffiks før vi gir opp.
    """
    env = bus_env(env)
    ok, why = available(env)
    attempts = []
    if ok:
        attempts = [unit, unit + "-r1"]
    else:
        log.warning("scope utilgjengelig (%s) – agenten kjører i "
                    "daemonens cgroup", why)

    for name in attempts:
        try:
            proc = _spawn(_wrap(name, cmd), env, kwargs)
        except OSError as e:
            why = "systemd-run kunne ikke startes: %s" % e
            log.warning("%s", why)
            break
        err = _died_early(proc)
        if err is None:
            cg = cgroup_of(proc.pid)
            log.info("agent i scope %s.scope (cgroup %s)", name, cg)
            return proc, {"scoped": True, "unit": name, "cgroup": cg,
                          "detail": "egen systemd-scope – overlever "
                                    "restart av mind.service"}
        why = "systemd-run %s feilet: %s" % (name, err)
        log.warning("%s", why)
        _close(proc)  # prosessen er høstet av poll(); rørene må lukkes selv

    proc = _spawn(cmd, env, kwargs)
    return proc, {"scoped": False, "unit": None, "cgroup": cgroup_of(proc.pid),
                  "detail": "uten scope (%s) – prosessen ligger i daemonens "
                            "cgroup og dør ved restart av mind.service" % why}


def live_units():
    """Navnene på scope-enhetene som lever nå – til orden og feilsøking."""
    env = bus_env()
    try:
        out = subprocess.run(
            ["systemctl", "--user", "list-units", "--no-legend", "--plain",
             "--type=scope", UNIT_PREFIX + "*"],
            capture_output=True, text=True, env=env, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()]
