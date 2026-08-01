"""Kunnskapsmotoren (/opt/mind-knowledge) inn i hovedhjernens syklus.

Hovedhjernen får minneseksjoner valgt på nøkkelord. Kunnskapsmotoren finner i
tillegg det som ligner SEMANTISK på det som skjer akkurat nå – også når ordene
er andre – på tvers av hovedminne, detaljminner, arkiv og gamle
agentleveranser. Her hentes et kort destillat av de beste treffene og legges
inn i syklusprompten under egen overskrift.

TO ABSOLUTTE KRAV:

1. FAIL-OPEN. Kunnskap er en bonus, aldri en forutsetning. Enhver feil –
   manglende indeks, død arbeidsprosess, tidsavbrudd, ugyldig JSON – gir tom
   streng og en linje i loggen. Syklusen skal aldri kunne stoppe, henge eller
   krasje på grunn av et kunnskapsoppslag. Derfor har hver eneste offentlige
   funksjon her en bred except-blokk; det er bevisst.
2. TIDSBUDSJETT. Oppslaget har et hardt tidsavbrudd (TIMEOUT_S). Modellen bor
   i en varm arbeidsprosess (kb_worker.py) nettopp fordi et kaldstartet
   søk bruker ~11 s – for lenge for en syklus.

Arbeidsprosessen startes ved første oppslag, lever så lenge daemonen lever
(den dør av seg selv når stdin lukkes) og bruker kunnskapsmotorens eget venv.
Første syklus etter en restart får derfor som regel ingen kunnskap: den
returnerer tomt mens modellen varmes opp. Det er fail-open i praksis.
"""
import json
import logging
import os
import select
import subprocess
import threading
import time

log = logging.getLogger("mind.knowledge")

KB_DIR = "/opt/mind-knowledge"
KB_PYTHON = os.path.join(KB_DIR, "venv", "bin", "python")
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_worker.py")

TIMEOUT_S = 5.0          # hardt tak for ett oppslag i syklusen
STARTUP_TIMEOUT_S = 60.0  # kaldstart av modellen (skjer i bakgrunnen)
TOP_HITS = 6

# ~1500 tokens. Norsk ligger grovt på 3,5–4 tegn per token, så 5000 tegn er et
# forsiktig tak som holder seg innenfor selv med ugunstig tokenisering.
MAX_CHARS = 5000

# To låser med ulik levetid: _io_lock holdes bare mens et spørsmål går over
# røret (millisekunder til TIMEOUT_S), _flag_lock kun rundt oppstartsflagget.
# Modellasting på ~10 s skjer UTEN lås, slik at en syklus aldri kan bli
# stående og vente på en oppvarming.
_io_lock = threading.Lock()
_flag_lock = threading.Lock()
_proc = None
_seq = 0
_starting = False


def _worker_alive():
    return _proc is not None and _proc.poll() is None


def _start_worker():
    """Start den varme arbeidsprosessen og vent på klarsignalet.

    Kalles bare fra bakgrunnstråden i _ensure_worker – aldri fra syklustråden,
    for modellastingen tar ~10 s.
    """
    global _proc
    if not os.path.exists(KB_PYTHON) or not os.path.exists(WORKER):
        log.info("kunnskapsmotor ikke tilgjengelig (%s / %s)", KB_PYTHON, WORKER)
        return False
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    p = subprocess.Popen([KB_PYTHON, WORKER], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env, cwd=KB_DIR, start_new_session=True)
    line = _read_line(p, STARTUP_TIMEOUT_S)
    try:
        hello = json.loads(line or "{}")
    except ValueError:
        hello = {}
    if not hello.get("klar"):
        log.warning("kunnskapsmotoren startet ikke: %s",
                    (hello.get("feil") or line or "ingen klarsignal")[:200])
        _terminate(p)
        return False
    log.info("kunnskapsmotoren er varm (%s biter i indeksen)",
             hello.get("biter"))
    _proc = p
    return True


def _terminate(p):
    try:
        p.stdin.close()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        p.terminate()
    except OSError:
        pass


def _read_line(p, timeout):
    """Les én linje fra arbeidsprosessen med tidsavbrudd. None ved timeout."""
    deadline = time.time() + timeout
    while True:
        left = deadline - time.time()
        if left <= 0:
            return None
        r, _, _ = select.select([p.stdout], [], [], left)
        if not r:
            return None
        line = p.stdout.readline()
        if line == "":       # EOF – prosessen er død
            return None
        if line.strip():
            return line


def _ensure_worker():
    """Sørg for at arbeidsprosessen er på vei opp. Blokkerer aldri kalleren.

    Returnerer True bare hvis prosessen ER varm nå. Er den under oppvarming,
    returneres False med én gang – syklusen går videre uten kunnskap.
    """
    global _starting
    with _flag_lock:
        if _worker_alive():
            return True
        if _starting:
            return False
        _starting = True

    def boot():
        global _starting
        try:
            _start_worker()
        except Exception as e:
            log.warning("oppstart av kunnskapsmotoren feilet: %s", e)
        finally:
            with _flag_lock:
                _starting = False

    threading.Thread(target=boot, daemon=True, name="kb-boot").start()
    return False


def _drop(p):
    global _proc
    _terminate(p)
    if _proc is p:
        _proc = None


def _ask(query, top, timeout):
    """Ett oppslag mot den varme prosessen. Returnerer treffliste eller []."""
    global _seq
    deadline = time.time() + timeout
    if not _io_lock.acquire(timeout=timeout):
        log.info("kunnskapsmotoren er opptatt – hopper over oppslaget")
        return []
    try:
        if not _worker_alive():
            return []
        _seq += 1
        rid = _seq
        p = _proc
        try:
            p.stdin.write(json.dumps({"id": rid, "q": query, "top": top},
                                     ensure_ascii=False) + "\n")
            p.stdin.flush()
        except (OSError, ValueError) as e:
            log.warning("kunne ikke sende spørsmål til kunnskapsmotoren: %s", e)
            _drop(p)
            return []
        while True:
            left = deadline - time.time()
            if left <= 0:
                # Svaret kan komme etter at vi har gitt opp. Da er røret ute av
                # takt, og eneste ærlige utvei er å forkaste prosessen –
                # ellers ville neste syklus fått forrige syklus' svar.
                log.info("kunnskapsoppslag over tid (%.1f s) – hopper over",
                         timeout)
                _drop(p)
                return []
            line = _read_line(p, left)
            if line is None:
                log.warning("kunnskapsmotoren svarte ikke (død eller taus)")
                _drop(p)
                return []
            try:
                resp = json.loads(line)
            except ValueError:
                continue
            if resp.get("id") != rid:
                continue    # gammelt svar – hopp over
            if resp.get("feil"):
                log.warning("kunnskapsoppslag feilet: %s", str(resp["feil"])[:200])
                return []
            return resp.get("treff") or []
    finally:
        _io_lock.release()


def _format(hits, max_chars=MAX_CHARS):
    lines = []
    used = 0
    for h in hits:
        blokk = ("- %s (%s%s, score %s)\n  id: %s\n  %s"
                 % (h.get("tittel", "?"), h.get("type", ""),
                    (" · " + h["tid"]) if h.get("tid") else "",
                    h.get("score"), h.get("ref", ""),
                    (h.get("utdrag") or "").replace("\n", " ")))
        if used + len(blokk) > max_chars:
            break
        lines.append(blokk)
        used += len(blokk) + 1
    return "\n".join(lines)


def distill(query, top=TOP_HITS, timeout=TIMEOUT_S, max_chars=MAX_CHARS):
    """Kort destillat av det kunnskapsmotoren finner om `query`.

    Returnerer alltid en streng – tom når det ikke er noe å vise ELLER når
    noe som helst gikk galt. Kaster aldri.
    """
    try:
        if not (query or "").strip():
            return ""
        if not _ensure_worker():
            return ""     # varmes opp – neste syklus får svar
        hits = _ask(query[:2000], top, timeout)
        return _format(hits, max_chars)
    except Exception as e:
        log.warning("kunnskapsoppslag hoppet over (%s: %s)", type(e).__name__, e)
        return ""


def status():
    """Kort statuslinje til feilsøking (dashbord/logg)."""
    return {"varm": _worker_alive(), "starter": _starting,
            "pid": _proc.pid if _worker_alive() else None}
