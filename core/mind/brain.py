"""Motor-abstraksjonen: brain_call(role, prompt, ...) -> tekst/JSON (§2.1).

To motorer bak ett grensesnitt:
  - 'api':         Anthropic API via offisiell SDK (prompt caching + server-side
                   fallback for Fable-modeller: sikkerhetsavslag rutes automatisk
                   til anbefalt fallback-modell)
  - 'claude_code': `claude -p --output-format json` headless subprocess

Hvert kall token-logges til MongoDB. Rate limits/overlast håndteres med
eksponentiell backoff – systemet venter, det dør aldri.

Cache-vennlig struktur: system_blocks skal ha stabile blokker FØRST
(identitet/kontrakt, deretter minneindeks); de to første blokkene cache-merkes
på Motor A. Volatilt innhold hører hjemme i user_prompt.
"""
import json
import os
import re
import subprocess
import time

from . import config, db

BACKOFF_START = 20
BACKOFF_MAX = 900

ROLE_MODEL_KEY = {
    "brain": "brain_model",
    "agent": "agent_model",
    "responder": "responder_model",
    "pulse": "pulse_model",
}


class TransientAPIError(Exception):
    def __init__(self, msg, retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


def _extract_json(text):
    """Best-effort-uthenting av første JSON-objekt i et svar."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("ingen JSON i svaret: " + text[:400])
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("ubalansert JSON i svaret: " + text[:400])


# ------------------------------------------------------------------ motorer

_sdk_client = None


def _api_client():
    global _sdk_client
    import anthropic
    key = config.anthropic_api_key()
    if not key:
        raise RuntimeError("Motor A er valgt, men ingen Anthropic API-nøkkel "
                           "er lagret i innstillingene.")
    if _sdk_client is None or _sdk_client.api_key != key:
        _sdk_client = anthropic.Anthropic(api_key=key, timeout=1200.0, max_retries=0)
    return _sdk_client


def _call_api(model, system_blocks, user_prompt, max_tokens):
    import anthropic
    client = _api_client()
    system = []
    for i, block in enumerate(system_blocks):
        b = {"type": "text", "text": block}
        if i < 2:  # cache den stabile prefiksen (systemprompt + minneindeks)
            b["cache_control"] = {"type": "ephemeral"}
        system.append(b)
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    try:
        if "fable" in model or "mythos" in model:
            # Fable: sikkerhetsklassifisering kan avslå – server-side fallback
            # ruter da kallet til anbefalt modell i samme forespørsel.
            resp = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        retry_after = None
        try:
            retry_after = float(e.response.headers.get("retry-after"))
        except (TypeError, ValueError, AttributeError):
            pass
        raise TransientAPIError("rate limit (429)", retry_after)
    except anthropic.APIStatusError as e:
        if e.status_code >= 500 or e.status_code == 529:
            raise TransientAPIError(f"HTTP {e.status_code}")
        raise
    except anthropic.APIConnectionError:
        raise TransientAPIError("nettverksfeil mot api.anthropic.com")

    if resp.stop_reason == "refusal":
        cat = getattr(getattr(resp, "stop_details", None), "category", None)
        raise RuntimeError(f"Modellen avslo forespørselen (refusal, kategori={cat}).")

    text = "".join(b.text for b in resp.content if b.type == "text")
    u = resp.usage
    usage = {
        "input": getattr(u, "input_tokens", 0) or 0,
        "output": getattr(u, "output_tokens", 0) or 0,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }
    return text, usage


def _call_claude_code(model, system_blocks, user_prompt):
    """Motor B: headless Claude Code. Prompt via stdin (lange prompter)."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", "\n\n".join(system_blocks),
        "--tools", "",
        "--no-session-persistence",
    ]
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # tillat nøstet invokasjon
    proc = subprocess.run(
        cmd, input=user_prompt, capture_output=True, text=True,
        timeout=1800, env=env, cwd=config.LOGS_DIR,
    )
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or out or "")[-1500:]
        low = err.lower()
        if any(k in low for k in ("rate limit", "overloaded", "429", "529", "usage limit")):
            raise TransientAPIError("claude_code rate limited: " + err[-300:])
        raise RuntimeError(f"claude -p feilet rc={proc.returncode}: {err}")
    data = json.loads(out)
    if data.get("subtype") not in (None, "success"):
        raise TransientAPIError("claude_code non-success: " + str(data.get("subtype")))
    text = data.get("result", "")
    u = data.get("usage", {}) or {}
    usage = {
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_creation": u.get("cache_creation_input_tokens", 0),
    }
    return text, usage


# ------------------------------------------------------------------ hoved-API

def brain_call(role, user_prompt, system_blocks, purpose="", expect_json=True,
               model=None, max_attempts=8, max_tokens=None):
    """Ett inngangspunkt for ALLE LLM-kall.

    role: 'brain' | 'agent' | 'responder' | 'pulse' – velger modell fra
    innstillingene med mindre `model` er angitt. system_blocks: list[str] med
    stabile blokker først (de prompt-caches på Motor A).
    """
    s = db.get_settings()
    engine = s.get("engine", "claude_code")
    if model is None:
        model = s.get(ROLE_MODEL_KEY.get(role, "brain_model"))
    if max_tokens is None:
        max_tokens = config.MAX_OUTPUT_TOKENS

    backoff = BACKOFF_START
    last_err = None
    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        try:
            if engine == "api":
                text, usage = _call_api(model, system_blocks, user_prompt, max_tokens)
            else:
                text, usage = _call_claude_code(model, system_blocks, user_prompt)
            db.log_tokens(role, engine, model, usage, purpose, (time.time() - t0) * 1000)
            if not expect_json:
                return text
            try:
                return _extract_json(text)
            except ValueError as je:
                last_err = je
                if attempt >= 3:
                    raise
                user_prompt = (user_prompt +
                               "\n\nVIKTIG: Forrige svar var ikke gyldig JSON. "
                               "Svar med KUN ett gyldig JSON-objekt.")
                continue
        except TransientAPIError as e:
            last_err = e
            wait = e.retry_after or backoff
            db.log_event("backoff",
                         f"LLM-kall ({purpose}) fikk midlertidig feil, "
                         f"venter {int(wait)}s: {e}", priority=4)
            time.sleep(min(wait, BACKOFF_MAX))
            backoff = min(backoff * 2, BACKOFF_MAX)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            last_err = e
            db.log_event("backoff",
                         f"LLM-kall ({purpose}) feilet ({type(e).__name__}), "
                         f"venter {backoff}s", priority=4)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
    raise RuntimeError(f"brain_call ga opp etter {max_attempts} forsøk "
                       f"({purpose}): {last_err}")


def list_models():
    """Hent oppdatert modelliste fra Anthropic; fallback til hardkodet (§2.1)."""
    key = config.anthropic_api_key()
    if key:
        try:
            client = _api_client()
            ids = [m.id for m in client.models.list()]
            if ids:
                return ids
        except Exception:
            pass
    return list(config.FALLBACK_MODELS)
