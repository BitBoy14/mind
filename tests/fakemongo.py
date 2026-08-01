"""En liten, ærlig in-memory-erstatning for MongoClient.

Hvorfor ikke bare monkeypatche funksjonene som testes? Fordi da tester vi
stubbene våre, ikke koden. Med denne faken kjører den EKTE koden i
`mind.memory`, `mind.cycle` og `mind.db` – kun selve lagringslaget er byttet
ut. Testene ser dermed reelle sideeffekter (innsatte dokumenter, oppdaterte
felt, slettede seksjoner) i stedet for «ble kalt med»-påstander.

Prinsipper:

* **Feil høylytt.** Alt som ikke er implementert (ukjent filteroperator,
  ukjent oppdateringsoperator) kaster `NotImplementedError`. En fake som
  ignorerer det den ikke forstår, gir grønne tester og falsk trygghet.
* **Kopisemantikk som pymongo.** `find`/`find_one` returnerer dypkopier,
  slik ekte pymongo gjør (dokumentene dekodes fra BSON). Koden i
  `apply_ops` gjør bl.a. `s.pop("_id")` på et lest dokument – uten kopi
  ville faken oppført seg annerledes enn produksjon.
* **Ingen nettverk.** Ingenting her åpner en socket.

Dekker kun det MIND-koden faktisk bruker. Se `test_fakemongo.py`: faken har
egne tester, ellers er den ikke til å stole på.
"""
import copy
import re

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

ASCENDING = 1
DESCENDING = -1

_QUERY_OPS = ("$in", "$nin", "$ne", "$exists", "$gt", "$gte", "$lt", "$lte")
_UPDATE_OPS = ("$set", "$inc", "$push", "$unset", "$setOnInsert")


# ------------------------------------------------------------------ matching

def _is_op_expr(cond):
    return isinstance(cond, dict) and any(k.startswith("$") for k in cond)


def _match_field(value, cond):
    if not _is_op_expr(cond):
        return value == cond
    for op, arg in cond.items():
        if op not in _QUERY_OPS:
            raise NotImplementedError(f"fakemongo: filteroperator {op} mangler")
        if op == "$in" and value not in arg:
            return False
        if op == "$nin" and value in arg:
            return False
        if op == "$ne" and value == arg:
            return False
        if op == "$exists" and bool(arg) != (value is not _MISSING):
            return False
        if op == "$gt" and not (value is not None and value > arg):
            return False
        if op == "$gte" and not (value is not None and value >= arg):
            return False
        if op == "$lt" and not (value is not None and value < arg):
            return False
        if op == "$lte" and not (value is not None and value <= arg):
            return False
    return True


class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()


def _matches(doc, filt):
    if not filt:
        return True
    for key, cond in filt.items():
        if key.startswith("$"):
            raise NotImplementedError(f"fakemongo: toppnivå-operator {key} mangler")
        if not _match_field(doc.get(key, _MISSING), cond):
            return False
    return True


def _sort_key(value):
    """Grov etterligning av BSON-typeordning: manglende/None sorterer først,
    deretter tall, deretter tekst. Nok for feltene MIND sorterer på."""
    if value is _MISSING or value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    return (2, str(value))


def _normalize_sort(key_or_list, direction):
    if isinstance(key_or_list, str):
        return [(key_or_list, DESCENDING if direction == DESCENDING else ASCENDING)]
    return [(k, d) for k, d in key_or_list]


def _apply_sort(docs, spec):
    out = list(docs)
    for field, direction in reversed(spec):
        out.sort(key=lambda d: _sort_key(d.get(field, _MISSING)),
                 reverse=(direction == DESCENDING))
    return out


def _project(doc, projection):
    """Kun inkluderende projeksjon (`{"felt": 1}`), som i MIND-koden.
    `_id` blir med med mindre den eksplisitt slås av."""
    if not projection:
        return doc
    if any(v for v in projection.values()) and any(not v for v in projection.values()
                                                   if v is not None):
        # blandet inkluder/ekskluder er ulovlig i Mongo (unntatt _id)
        illegal = [k for k, v in projection.items() if not v and k != "_id"]
        if illegal:
            raise NotImplementedError("fakemongo: blandet projeksjon støttes ikke")
    out = {k: v for k, v in doc.items()
           if projection.get(k) or (k == "_id" and projection.get("_id", 1))}
    return out


# ------------------------------------------------------------------ resultater

class _InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id
        self.acknowledged = True


class _UpdateResult:
    def __init__(self, matched, modified, upserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_id = upserted_id
        self.acknowledged = True


class _DeleteResult:
    def __init__(self, deleted):
        self.deleted_count = deleted
        self.acknowledged = True


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key_or_list, direction=None):
        self._docs = _apply_sort(self._docs, _normalize_sort(key_or_list, direction))
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def __iter__(self):
        return iter(self._docs)

    def __len__(self):
        return len(self._docs)


# ------------------------------------------------------------------ collection

class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []          # rådokumentene; testene kan inspisere direkte
        self.indexes = []

    # --- lesing
    def find(self, filter=None, projection=None, sort=None, limit=0):
        hits = [copy.deepcopy(d) for d in self.docs if _matches(d, filter)]
        if projection:
            hits = [_project(d, projection) for d in hits]
        if sort:
            hits = _apply_sort(hits, _normalize_sort(sort, None))
        if limit:
            hits = hits[:limit]
        return FakeCursor(hits)

    def find_one(self, filter=None, projection=None, sort=None):
        for d in self.find(filter, projection, sort):
            return d
        return None

    def count_documents(self, filter=None):
        return sum(1 for d in self.docs if _matches(d, filter))

    # --- skriving
    def insert_one(self, document):
        doc = copy.deepcopy(document)
        if "_id" not in doc:
            doc["_id"] = ObjectId()
            document["_id"] = doc["_id"]   # pymongo muterer originalen
        elif any(d["_id"] == doc["_id"] for d in self.docs):
            raise DuplicateKeyError(f"duplicate key: {doc['_id']}")
        self.docs.append(doc)
        return _InsertOneResult(doc["_id"])

    def insert_many(self, documents):
        return [self.insert_one(d).inserted_id for d in documents]

    def update_one(self, filter, update, upsert=False):
        for d in self.docs:
            if _matches(d, filter):
                before = copy.deepcopy(d)
                _apply_update(d, update)
                return _UpdateResult(1, 0 if d == before else 1)
        if upsert:
            doc = {k: v for k, v in (filter or {}).items() if not _is_op_expr(v)}
            _apply_update(doc, update, upsert=True)
            res = self.insert_one(doc)
            return _UpdateResult(0, 0, upserted_id=res.inserted_id)
        return _UpdateResult(0, 0)

    def update_many(self, filter, update):
        n = 0
        for d in self.docs:
            if _matches(d, filter):
                _apply_update(d, update)
                n += 1
        return _UpdateResult(n, n)

    def find_one_and_update(self, filter, update, return_document=None, **kw):
        for d in self.docs:
            if _matches(d, filter):
                _apply_update(d, update)
                return copy.deepcopy(d)
        return None

    def delete_one(self, filter):
        for i, d in enumerate(self.docs):
            if _matches(d, filter):
                del self.docs[i]
                return _DeleteResult(1)
        return _DeleteResult(0)

    def delete_many(self, filter):
        keep = [d for d in self.docs if not _matches(d, filter)]
        n = len(self.docs) - len(keep)
        self.docs = keep
        return _DeleteResult(n)

    def create_index(self, *a, **kw):
        self.indexes.append((a, kw))
        return "fake_index"


def _apply_update(doc, update, upsert=False):
    for op, changes in update.items():
        if op not in _UPDATE_OPS:
            raise NotImplementedError(f"fakemongo: oppdateringsoperator {op} mangler")
        if op == "$set":
            doc.update(copy.deepcopy(changes))
        elif op == "$setOnInsert":
            if upsert:
                doc.update(copy.deepcopy(changes))
        elif op == "$inc":
            for k, v in changes.items():
                doc[k] = (doc.get(k) or 0) + v
        elif op == "$push":
            for k, v in changes.items():
                doc.setdefault(k, []).append(copy.deepcopy(v))
        elif op == "$unset":
            for k in changes:
                doc.pop(k, None)


# ------------------------------------------------------------------ db/klient

class FakeDatabase:
    def __init__(self, name):
        self.name = name
        self._collections = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection(name)
        return self._collections[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def list_collection_names(self):
        return sorted(self._collections)


class FakeMongoClient:
    """Erstatter `pymongo.MongoClient`. Åpner aldri en socket."""

    def __init__(self, *a, **kw):
        self.args = a
        self.kwargs = kw
        self._databases = {}

    def __getitem__(self, name):
        if name not in self._databases:
            self._databases[name] = FakeDatabase(name)
        return self._databases[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def close(self):
        pass


# Praktisk for testene: sjekk at en streng ser ut som en ObjectId
_OID_RE = re.compile(r"^[0-9a-f]{24}$")


def looks_like_object_id(value):
    return bool(_OID_RE.match(str(value)))
