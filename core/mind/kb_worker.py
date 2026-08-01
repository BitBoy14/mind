#!/opt/mind-knowledge/venv/bin/python
"""Varm arbeidsprosess for kunnskapsmotoren i /opt/mind-knowledge.

Hvorfor denne finnes: et kall til search.py bruker ~11 sekunder, og over 7 av
dem går med til å importere torch og laste embeddingmodellen. Med et
tidsavbrudd på 5 s i syklusen ville kunnskapsmotoren aldri rukket å svare.
Her lastes modellen ÉN gang; deretter koster et oppslag noen hundredeler.

Protokoll (én JSON-linje inn, én JSON-linje ut, på stdin/stdout):

    inn : {"id": 7, "q": "spørsmål", "top": 6}
    ut  : {"id": 7, "treff": [...]}  eller  {"id": 7, "feil": "..."}

Stdout er ren protokoll: alt bibliotekene måtte finne på å skrive dit under
modellasting og søk, dirigeres til stderr, slik at én linje alltid er ett
svar.

Prosessen eies av daemonen: lukkes stdin (daemonen dør eller restartes),
avslutter den seg selv. Indeksen leses inn på nytt når vectors.npy endrer
seg, så en re-indeksering i bakgrunnen slår gjennom uten omstart.

Kjøres med kunnskapsmotorens eget venv (shebang over) – MINDs kjerne-venv har
verken torch eller sentence-transformers, og skal ikke ha det.
"""
import contextlib
import json
import os
import sys

KB_DIR = "/opt/mind-knowledge"
sys.path.insert(0, KB_DIR)

import mind_kb as kb          # noqa: E402
import search as kb_search    # noqa: E402  (samme rangering som CLI-en)


class Index:
    """Indeksen med et enkelt mtime-basert oppfriskningsstempel."""

    def __init__(self):
        self.vectors = None
        self.rows = []
        self.state = {}
        self.mtime = None

    def _stamp(self):
        try:
            return os.path.getmtime(kb.VECTORS_PATH)
        except OSError:
            return None

    def fresh(self):
        stamp = self._stamp()
        if self.vectors is None or stamp != self.mtime:
            self.vectors, self.rows, self.state = kb.load_index()
            self.mtime = stamp
        return self.vectors, self.rows, self.state


def _reply(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    index = Index()
    with contextlib.redirect_stdout(sys.stderr):
        vectors, rows, _ = index.fresh()
        model = kb.load_model() if (vectors is not None and rows) else None
    if model is None:
        _reply({"id": 0, "feil": "ingen indeks i %s" % kb.INDEX_DIR})
        return 1
    # Klarsignal: kalleren venter på denne linjen før den sender spørsmål.
    _reply({"id": 0, "klar": True, "biter": len(rows)})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id", 0)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                vectors, rows, state = index.fresh()
                q = req.get("q") or ""
                qv = model.encode([q], convert_to_numpy=True,
                                  normalize_embeddings=True).astype("float32")[0]
                hits = kb_search.rank(q, vectors, rows, qv,
                                      top=int(req.get("top") or 5),
                                      min_score=float(req.get("min_score") or 0.0))
            resp = {"id": rid, "treff": hits,
                    "indeks": state.get("last_run_human", "")}
        except Exception as e:  # aldri dø av ett dårlig spørsmål
            resp = {"id": rid, "feil": "%s: %s" % (type(e).__name__, e)}
        _reply(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
