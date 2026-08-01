"""MIND-konfigurasjon: stier, konstanter, secrets.

Secrets ligger i /etc/mind/ (utenfor web-root). Sudo-passordet leses kun ved
eksplisitt behov for privilegerte handlinger og skal aldri logges eller vises.
"""
import fcntl
import json
import logging
import os
import stat

log = logging.getLogger("mind.config")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../mind
CORE_DIR = os.path.join(BASE_DIR, "core")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
AGENTWORK_DIR = os.path.join(BASE_DIR, "agentwork")
DATA_DIR = os.path.join(BASE_DIR, "data")

ETC_DIR = "/etc/mind"
SECRETS_FILE = os.path.join(ETC_DIR, "secrets.conf")
ENC_KEY_FILE = os.path.join(ETC_DIR, "enc_key")
SUDO_PASS_FILE = os.path.join(ETC_DIR, "sudo_pass")

MONGO_URI = "mongodb://127.0.0.1:27017"
DB_NAME = "mind"

JARVIS_DB_NAME = "jarvis"

# Fallback-modelliste når /v1/models ikke er tilgjengelig (§2.1).
FALLBACK_MODELS = [
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]

DEFAULT_SETTINGS = {
    "_id": "main",
    "engine": "claude_code",            # 'api' | 'claude_code'
    "brain_model": "claude-fable-5",
    "agent_model": "claude-sonnet-5",
    "responder_model": "claude-sonnet-5",
    "pulse_model": "claude-haiku-4-5",
    "running": False,
    "jarvis_link": False,
    "token_reset_ts": 0.0,
    "chat_epoch": 0.0,                  # /clear setter denne til nå
    "max_parallel_agents": 8,
    "night_curation_hour": 3,           # daglig grundig kurateringsøkt
}

# Minnehierarkiets rammer (§4)
MAIN_MEMORY_MAX_TOKENS = 150_000   # tak for hele hovedminnet (lagring)
INDEX_TARGET_TOKENS = 4_000        # indeksen holdes kompakt
WORKSET_TARGET_TOKENS = 25_000     # normalt arbeidssett per kall

# Hjerteslagets rytme (§3.1) — sekunder
PULSE_MIN = 10
PULSE_STEPS = [10, 30, 60, 300]
FORCE_CYCLE_EVERY_N_PULSES = 6     # ved aktivitet: syklus minst hvert N. pulsslag
IDLE_THINK_INTERVAL_S = 1800       # planlagt tanke-økt ved stillhet (30 min)

MAX_OUTPUT_TOKENS = 16000


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _check_secrets_file_perms():
    """Varsle høylytt hvis secrets.conf har videre tilgang enn tiltenkt.

    Filen deles nødvendigvis av to systembrukere (daemonen kjører som
    mads, php-fpm som www-data), så 0660 (eier+gruppe) er selve målet
    – ikke 0600. Vi varsler dersom "andre" har noen tilgang i det hele
    tatt, eller dersom modus er videre enn 0660 (f.eks. 664/666/777).
    """
    try:
        mode = stat.S_IMODE(os.stat(SECRETS_FILE).st_mode)
    except OSError:
        return
    if (mode & 0o007) != 0 or (mode & ~0o660) != 0:
        log.warning(
            "SIKKERHETSVARSEL: %s har modus %o - forventet maks 0660 "
            "(eier+gruppe, ingen tilgang for andre). Kjor: chmod 660 %s",
            SECRETS_FILE, mode, SECRETS_FILE,
        )


def _read_secrets_file():
    """Les secrets.conf med delt lås (unngår å lese filen midt i en skriving)."""
    _check_secrets_file_perms()
    try:
        with open(SECRETS_FILE) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return f.read().strip()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        return None


def enc_key_bytes():
    hexkey = _read(ENC_KEY_FILE)
    return bytes.fromhex(hexkey) if hexkey else None


def decrypt(value_b64):
    """Dekrypter verdi produsert av PHP-UI-et (AES-256-CBC, iv||ct, base64)."""
    if not value_b64:
        return ""
    import base64
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = base64.b64decode(value_b64)
    iv, ct = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(enc_key_bytes()), modes.CBC(iv))
    dec = cipher.decryptor()
    padded = dec.update(ct) + dec.finalize()
    pad = padded[-1]
    return padded[:-pad].decode("utf-8")


def get_secret(name):
    raw = _read_secrets_file()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    enc = data.get(name + "_enc", "")
    try:
        return decrypt(enc)
    except Exception:
        return ""


def anthropic_api_key():
    return get_secret("anthropic_api_key")


def sudo_password():
    return _read(SUDO_PASS_FILE) or ""
