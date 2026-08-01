"""Tester for testverktøyet selv.

Resten av suiten stoler på at `fakemongo` oppfører seg som pymongo på de
punktene MIND-koden faktisk bruker. Uten disse testene ville en feil i faken
gitt grønne tester og falsk trygghet – nettopp det testsuiten skal beskytte
mot. Her festes de egenskapene de andre testene hviler på.
"""
import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

import fakemongo
from mind import db as mind_db


@pytest.fixture
def col():
    return fakemongo.FakeCollection("test")


# ------------------------------------------------------------------ kopisemantikk

def test_find_one_returnerer_kopi_ikke_referanse(col):
    """`memory.apply_ops` gjør `s.pop("_id")` på et lest dokument og sletter
    deretter originalen. Uten kopi ville faken oppført seg annerledes enn
    ekte pymongo, og arkiveringstesten ville testet en fiksjon."""
    col.insert_one({"_id": 1, "a": {"b": [1, 2]}})
    lest = col.find_one({"_id": 1})
    lest.pop("_id")
    lest["a"]["b"].append(3)
    assert col.find_one({"_id": 1}) == {"_id": 1, "a": {"b": [1, 2]}}


def test_insert_one_kopierer_men_setter_id_paa_originalen(col):
    """Slik ekte pymongo gjør: dokumentet lagres som kopi, men kalleren får
    `_id` satt på sitt eget dict (db.create_agent_task er avhengig av det)."""
    doc = {"a": 1}
    res = col.insert_one(doc)
    assert doc["_id"] == res.inserted_id
    doc["a"] = 999
    assert col.find_one({})["a"] == 1


def test_duplikat_id_avvises(col):
    col.insert_one({"_id": "main"})
    with pytest.raises(DuplicateKeyError):
        col.insert_one({"_id": "main"})


# ------------------------------------------------------------------ filtre

def test_likhetsfilter_og_manglende_felt(col):
    col.insert_one({"_id": 1, "status": "queued"})
    col.insert_one({"_id": 2})
    assert col.find_one({"status": "queued"})["_id"] == 1
    assert col.find_one({"status": "done"}) is None
    assert col.count_documents({}) == 2


def test_in_operator(col):
    for i, status in enumerate(["queued", "running", "done"]):
        col.insert_one({"_id": i, "status": status})
    truffet = [d["_id"] for d in col.find({"status": {"$in": ["queued", "running"]}})]
    assert truffet == [0, 1]


def test_ukjent_filteroperator_kaster(col):
    """Faken skal feile høylytt, ikke stille ignorere det den ikke kan."""
    col.insert_one({"a": 1})
    with pytest.raises(NotImplementedError):
        col.find_one({"a": {"$regex": "x"}})


def test_ukjent_oppdateringsoperator_kaster(col):
    col.insert_one({"_id": 1})
    with pytest.raises(NotImplementedError):
        col.update_one({"_id": 1}, {"$addToSet": {"a": 1}})


def test_pull_med_betingelse_kaster(col):
    """Betingelsesformen ville krevd hele matcheren. Å gjette på den kunne
    fjernet feil element – da er det bedre å feile høylytt."""
    col.insert_one({"_id": 1, "liste": [1, 2, 3]})
    with pytest.raises(NotImplementedError):
        col.update_one({"_id": 1}, {"$pull": {"liste": {"$gt": 1}}})


# ------------------------------------------------------------------ oppdatering

def test_set_inc_og_push(col):
    col.insert_one({"_id": 1, "n": 5, "liste": ["a"]})
    col.update_one({"_id": 1}, {"$set": {"tekst": "ny"},
                                "$inc": {"n": 1},
                                "$push": {"liste": "b"}})
    assert col.find_one({"_id": 1}) == {"_id": 1, "n": 6, "tekst": "ny",
                                        "liste": ["a", "b"]}


def test_inc_paa_manglende_felt_starter_paa_null(col):
    col.insert_one({"_id": 1})
    col.update_one({"_id": 1}, {"$inc": {"use_count": 1}})
    assert col.find_one({"_id": 1})["use_count"] == 1


def test_push_paa_manglende_felt_lager_lista(col):
    col.insert_one({"_id": 1})
    col.update_one({"_id": 1}, {"$push": {"pointers": "x"}})
    assert col.find_one({"_id": 1})["pointers"] == ["x"]


def test_pull_fjerner_alle_forekomster(col):
    col.insert_one({"_id": 1, "pointers": ["a", "b", "a"]})
    col.update_one({"_id": 1}, {"$pull": {"pointers": "a"}})
    assert col.find_one({"_id": 1})["pointers"] == ["b"]


def test_pull_paa_manglende_eller_ikke_liste_er_uskadelig(col):
    col.insert_one({"_id": 1, "tekst": "ikke en liste"})
    col.update_one({"_id": 1}, {"$pull": {"pointers": "a"}})
    col.update_one({"_id": 1}, {"$pull": {"tekst": "a"}})
    assert col.find_one({"_id": 1}) == {"_id": 1, "tekst": "ikke en liste"}


def test_update_one_treffer_bare_forste(col):
    col.insert_one({"_id": 1, "k": "v"})
    col.insert_one({"_id": 2, "k": "v"})
    res = col.update_one({"k": "v"}, {"$set": {"rort": True}})
    assert (res.matched_count, res.modified_count) == (1, 1)
    assert [d.get("rort") for d in col.find({})] == [True, None]


def test_update_one_uten_treff_rapporterer_null(col):
    """`db.request_cancel` returnerer nettopp `matched_count > 0`."""
    res = col.update_one({"_id": ObjectId()}, {"$set": {"a": 1}})
    assert res.matched_count == 0
    assert col.docs == []


def test_upsert_lager_dokument_fra_filter_og_set(col):
    """`db.set_state` er en upsert på {"_id": "main"}."""
    col.update_one({"_id": "main"}, {"$set": {"working_note": "x"}}, upsert=True)
    assert col.find_one({}) == {"_id": "main", "working_note": "x"}
    col.update_one({"_id": "main"}, {"$set": {"working_note": "y"}}, upsert=True)
    assert col.count_documents({}) == 1
    assert col.find_one({})["working_note"] == "y"


def test_delete_one(col):
    col.insert_one({"_id": 1})
    assert col.delete_one({"_id": 1}).deleted_count == 1
    assert col.delete_one({"_id": 1}).deleted_count == 0


# ------------------------------------------------------------------ sortering

def test_sort_synkende_og_stigende(col):
    for i in [2, 10, 5]:
        col.insert_one({"importance": i})
    assert [d["importance"] for d in col.find().sort("importance", -1)] == [10, 5, 2]
    assert [d["importance"] for d in col.find().sort("importance", 1)] == [2, 5, 10]


def test_sort_er_stabil_ved_uavgjort(col):
    """`memory.all_sections` sorterer på viktighet; rekkefølgen mellom like
    viktige seksjoner avgjør rangeringen i select_relevant ved poenglikhet."""
    for navn in ["a", "b", "c"]:
        col.insert_one({"navn": navn, "importance": 5})
    assert [d["navn"] for d in col.find().sort("importance", -1)] == ["a", "b", "c"]


def test_sort_taaler_manglende_felt(col):
    col.insert_one({"_id": 1, "finished_ts": 100})
    col.insert_one({"_id": 2})
    assert [d["_id"] for d in col.find().sort("finished_ts", -1)] == [1, 2]


def test_sort_via_find_one(col):
    """`jarvis_link.add_idea` bruker find_one(sort=[("priority", -1)])."""
    col.insert_one({"priority": 1})
    col.insert_one({"priority": 7})
    assert col.find_one(sort=[("priority", -1)])["priority"] == 7


def test_limit(col):
    for i in range(5):
        col.insert_one({"i": i})
    assert len(list(col.find().sort("i", 1).limit(2))) == 2


# ------------------------------------------------------------------ projeksjon

def test_inkluderende_projeksjon(col):
    col.insert_one({"_id": 1, "tokens": 10, "content": "mye tekst"})
    assert col.find_one({}, {"tokens": 1}) == {"_id": 1, "tokens": 10}


# ------------------------------------------------------------------ vernet mot ekte db

def test_ingen_tester_kan_aapne_ekte_tilkobling():
    """Autouse-fixturen i conftest skal ha stengt ruten helt."""
    with pytest.raises(AssertionError, match="EKTE MongoDB"):
        mind_db.client()


def test_fake_db_fixturen_er_koblet_inn(fake_db):
    assert mind_db.db() is fake_db
    assert fake_db.name == "mind"


def test_databaser_og_samlinger_lages_paa_forespoersel():
    klient = fakemongo.FakeMongoClient()
    assert klient["mind"].memory_main is klient["mind"]["memory_main"]
    assert klient["mind"] is not klient["jarvis"]
