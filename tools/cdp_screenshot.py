#!/usr/bin/env python3
"""cdp_screenshot.py -- screenshot av en URL MED cookies, via Chrome DevTools Protocol.

Hvorfor denne finnes: chromiums enkle `--screenshot`-modus kan ikke sette
cookies eller headere, så innloggede sider blir usynlige for selvverifisering.
CDP kan det (Network.setCookie), men krever en WebSocket-klient. Denne filen
snakker CDP med KUN Python-standardbibliotek (ingen pip, ingen venv, ingen
node) slik at verktøyet virker uendret over tid.

BRUK (kalles normalt av tools/screenshot.sh, men kan brukes direkte):
  cdp_screenshot.py --url URL --out FIL.png [--width 1280] [--height 800]
                    [--wait 2] [--cookie NAVN=VERDI] [--cookies-stdin]
                    [--cookie-domain vert] [--cookie-path /] [--full-page]
                    [--browser chromium-browser]

--cookie kan gjentas. Cookies settes som Secure+HttpOnly når URL-en er https.
FORETRUKKET for hemmelige cookies (f.eks. en sesjons-ID) er --cookies-stdin,
som leser NAVN=VERDI linjevis fra stdin: argumenter i en kommandolinje er
lesbare for alle lokale brukere via ps/proc, det stdin ikke er.

Exit-koder: 0 = OK, 1 = feil argumenter, 2 = feil fra nettleser/CDP,
            3 = fant ingen nettleser.

BEGRENSNINGER (samme som tools/screenshot.sh):
  * En 404/500/DNS-feil gir IKKE exit != 0 -- da tas det et gyldig bilde AV
    feilsiden. Sjekk PNG-en, eller curl URL-en først.
  * chromium er en snap med strict confinement: brukerprofilen må ligge i en
    SYNLIG katalog under $HOME. Derfor opprettes profilen under
    ~/mind-screenshots/. Selve PNG-en skrives av Python (ikke nettleseren), så
    utfilstien kan ligge hvor som helst du har skrivetilgang.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

BROWSER_CANDIDATES = [
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
]


class CdpError(RuntimeError):
    pass


# ----------------------------------------------------------------- websocket


class WebSocket:
    """Minimal RFC6455-klient: nok til CDP (tekstrammer, ingen utvidelser)."""

    def __init__(self, url: str, timeout: float = 30.0):
        u = urlparse(url)
        if u.scheme != "ws":
            raise CdpError(f"forventet ws://-URL, fikk {url}")
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        self.sock = socket.create_connection((u.hostname, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {u.hostname}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        # Merk: vi sender bevisst INGEN Origin-header. Chrome avviser
        # WebSocket-oppkoblinger mot DevTools fra ukjente origins.
        self.sock.sendall(req.encode())
        self._buf = b""
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("nettleseren lukket forbindelsen under WS-håndtrykk")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise CdpError(f"WS-håndtrykk avvist: {status.decode(errors='replace')}")

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CdpError("forbindelsen til nettleseren ble brutt")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def recv_text(self) -> str:
        """Les én komplett tekstmelding (håndterer fragmentering og ping)."""
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._read(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if b1 & 0x80:  # serveren skal ikke maskere, men vær robust
                mask = self._read(4)
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._read(n)))
            else:
                data = self._read(n)
            if opcode == 0x8:
                raise CdpError("nettleseren lukket WebSocket-en")
            if opcode == 0x9:  # ping -> pong
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:  # pong
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# ----------------------------------------------------------------------- cdp


class Cdp:
    def __init__(self, ws_url: str, timeout: float = 30.0):
        self.ws = WebSocket(ws_url, timeout=timeout)
        self._id = 0
        self.events: list[dict] = []

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None, timeout: float = 60.0) -> dict:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send_text(json.dumps(msg))
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                raise CdpError(f"tidsavbrudd på {method}")
            resp = json.loads(self.ws.recv_text())
            if resp.get("id") == msg["id"]:
                if "error" in resp:
                    raise CdpError(f"{method}: {resp['error'].get('message')}")
                return resp.get("result", {})
            if "method" in resp:
                self.events.append(resp)

    def wait_event(self, method: str, timeout: float = 30.0) -> dict | None:
        """Vent på en hendelse. None ved tidsavbrudd (ikke en feil -- sider
        som allerede er ferdiglastet sender ikke load-hendelsen på nytt)."""
        for i, ev in enumerate(self.events):
            if ev.get("method") == method:
                return self.events.pop(i)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.ws.sock.settimeout(max(0.5, deadline - time.monotonic()))
            try:
                resp = json.loads(self.ws.recv_text())
            except (socket.timeout, TimeoutError):
                return None
            finally:
                self.ws.sock.settimeout(60.0)
            if resp.get("method") == method:
                return resp
            if "method" in resp or "id" in resp:
                self.events.append(resp)
        return None

    def close(self) -> None:
        self.ws.close()


# -------------------------------------------------------------------- browser


def find_browser(explicit: str | None) -> str:
    if explicit:
        p = shutil.which(explicit)
        if not p:
            raise CdpError(f"fant ikke nettleseren '{explicit}'")
        return p
    for name in BROWSER_CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    raise CdpError(
        "fant ingen headless nettleser (chromium, chromium-browser, "
        "google-chrome, google-chrome-stable). Dette skriptet installerer "
        "ALDRI pakker automatisk."
    )


def launch(browser: str, profile_dir: str, width: int, height: int):
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        "--remote-debugging-port=0",  # fri port; faktisk port leses fra fil
        "about:blank",
    ]
    log = open(os.path.join(profile_dir, "browser.log"), "wb")
    # start_new_session: chromium (snap) starter en hel prosessfamilie via et
    # wrapper-skript. Egen prosessgruppe lar oss avslutte HELE familien -- ellers
    # lever barna videre noen hundre millisekunder og gjenskaper profilkatalogen
    # rett etter at vi har slettet den.
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    port_file = os.path.join(profile_dir, "DevToolsActivePort")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise CdpError(f"nettleseren avsluttet med kode {proc.returncode}")
        if os.path.exists(port_file):
            try:
                port = int(open(port_file).read().split("\n")[0].strip())
                if port > 0:
                    return proc, port
            except (ValueError, IndexError):
                pass
        time.sleep(0.15)
    proc.kill()
    raise CdpError("nettleseren startet ikke DevTools-porten i tide")


def stop_browser(proc: subprocess.Popen) -> None:
    """Avslutt hele prosessgruppen, ikke bare wrapper-prosessen."""
    import signal
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def sweep_stale_profiles(base: str, max_age_s: float = 3600.0) -> None:
    """Rydd profilkataloger fra kjøringer som ble drept før finally-blokken."""
    now = time.time()
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not name.startswith("cdp-profile-"):
            continue
        path = os.path.join(base, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > max_age_s:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


# ------------------------------------------------------------------------ run


def shoot(args) -> None:
    browser = find_browser(args.browser)
    base = os.path.join(os.path.expanduser("~"), "mind-screenshots")
    os.makedirs(base, exist_ok=True)
    sweep_stale_profiles(base)
    # Snap-confinement: profilen MÅ ligge i en synlig katalog under $HOME.
    profile_dir = tempfile.mkdtemp(prefix="cdp-profile-", dir=base)
    proc = None
    cdp = None
    try:
        proc, port = launch(browser, profile_dir, args.width, args.height)
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=15) as r:
            ws_url = json.load(r)["webSocketDebuggerUrl"]
        cdp = Cdp(ws_url)

        target = cdp.call("Target.createTarget", {"url": "about:blank"})
        sid = cdp.call("Target.attachToTarget",
                       {"targetId": target["targetId"], "flatten": True})["sessionId"]

        cdp.call("Page.enable", session_id=sid)
        cdp.call("Network.enable", session_id=sid)
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": args.width, "height": args.height,
            "deviceScaleFactor": 1, "mobile": False,
        }, session_id=sid)

        secure = urlparse(args.url).scheme == "https"
        host = urlparse(args.url).hostname or ""
        for raw in args.cookie:
            if "=" not in raw:
                raise CdpError(f"--cookie må være NAVN=VERDI (fikk: {raw})")
            name, value = raw.split("=", 1)
            cdp.call("Network.setCookie", {
                "name": name,
                "value": value,
                "domain": args.cookie_domain or host,
                "path": args.cookie_path,
                "secure": secure,
                "httpOnly": True,
                "sameSite": "Lax",
            }, session_id=sid)

        cdp.call("Page.navigate", {"url": args.url}, session_id=sid)
        cdp.wait_event("Page.loadEventFired", timeout=args.load_timeout)
        if args.wait > 0:
            time.sleep(args.wait)  # la SPA-er rekke å hente og rendre data

        params = {"format": "png", "captureBeyondViewport": bool(args.full_page)}
        if args.full_page:
            m = cdp.call("Page.getLayoutMetrics", session_id=sid)
            css = m.get("cssContentSize") or m.get("contentSize") or {}
            if css:
                params["clip"] = {
                    "x": 0, "y": 0,
                    "width": css["width"], "height": css["height"], "scale": 1,
                }
        data = cdp.call("Page.captureScreenshot", params, session_id=sid,
                        timeout=args.load_timeout)["data"]
        png = base64.b64decode(data)
        if not png:
            raise CdpError("nettleseren returnerte et tomt bilde")
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "wb") as fh:
            fh.write(png)
    finally:
        if cdp is not None:
            cdp.close()
        if proc is not None:
            stop_browser(proc)
        # Nettleseren kan rekke å gjenskape tomme kataloger idet den dør, så
        # slett én gang til hvis noe ble liggende igjen.
        shutil.rmtree(profile_dir, ignore_errors=True)
        if os.path.exists(profile_dir):
            time.sleep(0.5)
            shutil.rmtree(profile_dir, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description=__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--wait", type=float, default=2.0)
    ap.add_argument("--load-timeout", type=float, default=45.0)
    ap.add_argument("--cookie", action="append", default=[],
                    metavar="NAVN=VERDI", help="kan gjentas")
    ap.add_argument("--cookies-stdin", action="store_true",
                    help="les i tillegg NAVN=VERDI linjevis fra stdin")
    ap.add_argument("--cookie-domain", default="")
    ap.add_argument("--cookie-path", default="/")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--browser", default="")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        print(f"FEIL: URL må starte med http:// eller https:// (fikk: {args.url})",
              file=sys.stderr)
        return 1
    if args.cookies_stdin:
        for line in sys.stdin.read().splitlines():
            line = line.strip()
            if line:
                args.cookie.append(line)
    try:
        shoot(args)
    except CdpError as e:
        print(f"FEIL: {e}", file=sys.stderr)
        return 3 if "fant ingen headless" in str(e) or "fant ikke nettleseren" in str(e) else 2
    except Exception as e:  # nettverk, filsystem, ...
        print(f"FEIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(f"OK: screenshot lagret til {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
