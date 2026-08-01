"""Felles oppsett for MIND-testene.

Harde krav for hele suiten (fra oppdraget bak testene):

* **Ingen MongoDB.** `mind.db.MongoClient` byttes ut i en autouse-fixture som
  kaster hvis noe forsøker å koble til på ekte. Lagringen er in-memory
  (`fakemongo`), men koden som testes er den ekte.
* **Ingen nettverk, ingen LLM.** Ingenting her importerer eller kaller
  `brain.brain_call`, Anthropic-SDK-en eller `claude`-subprosessen.
* **Ingen lesing av /etc/mind/secrets.conf.** Den skjer kun i
  `config.mongo_uri()`, som bare kalles av `db.client()` – og den ruten er
  stengt her.

All testdata er syntetisk.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_DIR = os.path.join(REPO_ROOT, "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from mind import db as mind_db            # noqa: E402
from fakemongo import FakeMongoClient     # noqa: E402


@pytest.fixture(autouse=True)
def no_real_mongo(monkeypatch):
    """Sperr enhver ekte tilkobling og nullstill modulglobalene mellom tester.

    `mind.db` cacher klienten i en modulglobal. Uten nullstilling ville en
    fake fra én test lekket inn i neste og gjort rekkefølgen betydningsfull.
    """
    def _forbidden(*a, **kw):
        raise AssertionError(
            "En test forsøkte å åpne en EKTE MongoDB-tilkobling. "
            "Bruk fake_db/fake_jarvis-fixturene.")

    monkeypatch.setattr(mind_db, "MongoClient", _forbidden)
    monkeypatch.setattr(mind_db, "_client", None, raising=False)
    monkeypatch.setattr(mind_db, "_jarvis_client", None, raising=False)
    yield
    mind_db._client = None
    mind_db._jarvis_client = None


@pytest.fixture
def fake_db(monkeypatch):
    """MIND-databasen, in-memory. Returnerer FakeDatabase-objektet, slik at
    testene kan lese `fake_db.memory_main.docs` direkte."""
    client = FakeMongoClient()
    monkeypatch.setattr(mind_db, "_client", client, raising=False)
    from mind import config
    return client[config.DB_NAME]


@pytest.fixture
def fake_jarvis(monkeypatch):
    """Jarvis-basen, in-memory (egen klient i produksjon, egen fake her)."""
    client = FakeMongoClient()
    monkeypatch.setattr(mind_db, "_jarvis_client", client, raising=False)
    from mind import config
    return client[config.JARVIS_DB_NAME]


# ------------------------------------------------------------------ hjelpere

def make_section(db_, title, content, importance=5, tokens=None, **extra):
    """Legg en hovedminne-seksjon rett i lagringen og returner _id.

    Går bevisst utenom `memory._new_section` – testene skal kunne sette
    nøyaktige token-tall og utelate felter for å treffe `.get(...)`-defaultene
    i koden som testes.
    """
    doc = {"title": title, "content": content, "importance": importance,
           "use_count": 0, "pointers": []}
    if tokens is not None:
        doc["tokens"] = tokens
    doc.update(extra)
    return db_.memory_main.insert_one(doc).inserted_id


@pytest.fixture
def section_factory(fake_db):
    def _make(title, content="", importance=5, tokens=None, **extra):
        return make_section(fake_db, title, content, importance, tokens, **extra)
    return _make
