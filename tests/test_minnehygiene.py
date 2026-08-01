"""Minnehygiene: dedup mot kunnskapsindeksen, `arkiver_detalj` og brukssporing.

Bakgrunnen er målt, ikke antatt: hvert agentsvar ble lagret både på
`agent_tasks.result` og som detaljminne, og BEGGE ble embeddet av
kunnskapsmotoren. Samme kunnskap lå altså indeksert to ganger under to
etiketter, og ett semantisk søk kunne returnere begge som separate «treff».
Samtidig hadde detaljnivået ingen bruksteller i det hele tatt, så «sjelden
brukt» var ikke et lavt tall – det var et manglende felt.

Tre ting testes derfor:

  1. **Kriteriet**, ikke opphavet. En detalj merkes ikke-indekserbar KUN når
     teksten faktisk ligger ordrett i det agent_tasks lagrer. Bærer detaljen
     mer enn oppgaven (fordi `result` er avkortet), skal den fortsatt
     indekseres – ellers gjør ryddingen kunnskap usøkbar.
  2. **Idempotens.** Migreringen skal tåle å kjøres om igjen uten å telle,
     merke eller nullstille noe på nytt.
  3. **Ærlige kvitteringer.** `arkiver_detalj` mot en id som ikke finnes skal
     si det rett ut; hjernen skal aldri tro at noe ble arkivert.
"""
import pytest
from bson import ObjectId

from mind import agents, db, knowledge, memory, prompts


def ukjent_id():
    return str(ObjectId())


def lag_oppgave(fake_db, result, title="Oppgave"):
    return fake_db.agent_tasks.insert_one(
        {"title": title, "result": result, "status": "done"}).inserted_id


# ------------------------------------------------------- duplikat-kriteriet

@pytest.mark.parametrize("detalj, result, forventet", [
    ("nøyaktig samme tekst", "nøyaktig samme tekst", True),
    ("halen", "hodet og halen", True),           # delstreng: ingen ny kunnskap
    ("  samme  ", "samme", True),                # ytre blanktegn er ikke innhold
    ("hodet og halen", "halen", False),          # detaljen bærer MER
    ("noe helt annet", "hodet og halen", False),
    ("", "hodet", False),                        # tomt er ikke duplikat
    ("hodet", "", False),                        # ingen original å peke på
    ("hodet", None, False),
])
def test_duplikatkriteriet(detalj, result, forventet):
    assert memory.duplicates_task_result(detalj, result) is forventet


def test_avkortingshalen_teller_ikke_som_nytt_innhold():
    """add_detail kan selv legge på «[... avkortet, N tegn totalt ...]».

    Den halen er et spor av lagringen, ikke av leveransen, og skal ikke gjøre
    en ellers ordrett kopi til et «unikt» dokument.
    """
    detalj = "leveransen" + "\n\n[... avkortet, 99999 tegn totalt ...]"
    assert memory.duplicates_task_result(detalj, "leveransen") is True


# ------------------------------------------------------------- _new_detail

def test_detaljminne_faar_bruksteller_fra_foerste_stund(fake_db):
    memory.add_detail("T", "innhold")
    (doc,) = fake_db.memory_details.docs
    assert doc["use_count"] == 0
    # ikke nå: et dokument som nettopp ble skrevet, er ikke brukt
    assert doc["last_used_ts"] is None


def test_detaljminne_indekseres_som_foer_uten_flagg(fake_db):
    memory.add_detail("T", "innhold")
    (doc,) = fake_db.memory_details.docs
    assert "kb_index" not in doc


def test_kb_index_false_skrives_kun_naar_den_er_false(fake_db):
    memory.add_detail("T", "innhold", kb_index=False, ref="agent_tasks:abc")
    (doc,) = fake_db.memory_details.docs
    assert doc["kb_index"] is False and doc["ref"] == "agent_tasks:abc"
    assert fake_db.memory_details.count_documents(memory.KB_INDEX_FILTER) == 0


# --------------------------------------------------- agents._deliver-ruten

def test_agentsvar_som_er_ordrett_kopi_merkes_ikke_indekserbart(fake_db, monkeypatch):
    monkeypatch.setattr(agents, "_leveranse_utdrag", lambda r: (None, None))
    tid = lag_oppgave(fake_db, None, "Bygg noe")
    agents._deliver({"_id": tid, "title": "Bygg noe"}, "kort svar", [])

    (task,) = fake_db.agent_tasks.docs
    (detalj,) = fake_db.memory_details.docs
    assert task["result"] == "kort svar"
    assert detalj["content"] == "kort svar"
    assert detalj["kb_index"] is False
    assert detalj["ref"] == "agent_tasks:%s" % tid
    # agent_tasks er da den ENE indekserte kilden til dette svaret
    assert fake_db.memory_details.count_documents(memory.KB_INDEX_FILTER) == 0


def test_langt_agentsvar_forblir_indeksert_fordi_detaljen_baerer_mer(fake_db, monkeypatch):
    """`result` beholder bare halen. Da er detaljen ikke et duplikat, og å
    merke den ville gjort begynnelsen av svaret usøkbar."""
    monkeypatch.setattr(agents, "_leveranse_utdrag", lambda r: (None, None))
    langt = "A" * (agents.RESULT_STORE_CHARS + 500)
    tid = lag_oppgave(fake_db, None, "Langt")
    agents._deliver({"_id": tid, "title": "Langt"}, langt, [])

    (task,) = fake_db.agent_tasks.docs
    (detalj,) = fake_db.memory_details.docs
    assert len(task["result"]) == agents.RESULT_STORE_CHARS
    assert detalj["content"] == langt
    assert "kb_index" not in detalj


# ------------------------------------------------------- flag_agent_duplicates

def test_migreringen_merker_kun_ekte_duplikater(fake_db):
    dup = lag_oppgave(fake_db, "svaret", "Dup")
    unik = lag_oppgave(fake_db, "halen", "Unik")
    d_dup = memory.add_detail("Agentresultat: Dup [%s]" % dup, "svaret")
    d_unik = memory.add_detail("Agentresultat: Unik [%s]" % unik,
                               "hodet og halen")
    d_brain = memory.add_detail("Fullversjon: Pågående arbeid", "noe",
                                source="brain")

    sum_ = memory.flag_agent_duplicates()

    assert sum_["undersokt"] == 2          # hjernens egen detalj er ikke kandidat

    def hent(i):
        return fake_db.memory_details.find_one({"_id": i})
    assert hent(d_dup)["kb_index"] is False
    assert hent(d_dup)["ref"] == "agent_tasks:%s" % dup
    assert "kb_index" not in hent(d_unik)
    assert "kb_index" not in hent(d_brain)
    assert sum_["flagget"] == 1 and sum_["beholdt_indeksert"] == 1


def test_migreringen_er_idempotent(fake_db):
    tid = lag_oppgave(fake_db, "svaret")
    memory.add_detail("Agentresultat: X [%s]" % tid, "svaret")

    foerste = memory.flag_agent_duplicates()
    andre = memory.flag_agent_duplicates()

    assert foerste["flagget"] == 1 and foerste["allerede_flagget"] == 0
    assert andre["flagget"] == 0 and andre["allerede_flagget"] == 1
    assert andre["tokens_ut_av_indeks"] == 0


def test_migreringen_beholder_detalj_uten_kjent_oppgave(fake_db):
    did = memory.add_detail("Agentresultat: Borte [%s]" % ukjent_id(), "svaret")
    sum_ = memory.flag_agent_duplicates()
    assert sum_["uten_oppgave"] == 1 and sum_["flagget"] == 0
    assert "kb_index" not in fake_db.memory_details.find_one({"_id": did})


def test_toerrkjoering_maaler_uten_aa_skrive(fake_db):
    tid = lag_oppgave(fake_db, "svaret")
    did = memory.add_detail("Agentresultat: X [%s]" % tid, "svaret")

    sum_ = memory.flag_agent_duplicates(dry_run=True)

    assert sum_["flagget"] == 1
    assert "kb_index" not in fake_db.memory_details.find_one({"_id": did})
    assert fake_db.memory_log.count_documents({}) == 0


def test_migreringen_finner_opphavet_via_ref_naar_tittelen_er_endret(fake_db):
    tid = lag_oppgave(fake_db, "svaret")
    memory.add_detail("Tittel uten id", "svaret", ref="agent_tasks:%s" % tid)
    assert memory.flag_agent_duplicates()["flagget"] == 1


def test_migreringen_logger_kurateringen(fake_db):
    tid = lag_oppgave(fake_db, "svaret")
    memory.add_detail("Agentresultat: X [%s]" % tid, "svaret")
    memory.flag_agent_duplicates()
    (rad,) = fake_db.memory_log.docs
    assert rad["action"] == "dedup_indeksering" and rad["actor"] == "system"


# ------------------------------------------------------ backfill av telleren

def test_backfill_gir_gamle_detaljer_et_nullpunkt(fake_db):
    gammel = fake_db.memory_details.insert_one(
        {"title": "Fra før tellingen", "content": "x"}).inserted_id
    assert memory.backfill_detail_usage() == 1
    doc = fake_db.memory_details.find_one({"_id": gammel})
    assert doc["use_count"] == 0 and doc["last_used_ts"] is None


def test_backfill_nullstiller_aldri_en_teller_som_har_talt(fake_db):
    did = memory.add_detail("T", "x")
    db.mark_details_used([did])
    assert memory.backfill_detail_usage() == 0
    assert fake_db.memory_details.find_one({"_id": did})["use_count"] == 1


# ------------------------------------------------------------- brukssporing

def test_mark_details_used_teller_og_tidsstempler(fake_db):
    a = memory.add_detail("A", "x")
    b = memory.add_detail("B", "y")

    assert db.mark_details_used([a, b]) == 2
    db.mark_details_used([str(a)])

    doc_a = fake_db.memory_details.find_one({"_id": a})
    doc_b = fake_db.memory_details.find_one({"_id": b})
    assert doc_a["use_count"] == 2 and doc_b["use_count"] == 1
    assert doc_a["last_used_ts"] > 0


def test_mark_details_used_taaler_soppel_uten_aa_kaste(fake_db):
    did = memory.add_detail("A", "x")
    assert db.mark_details_used(["ikke-en-id", None, did]) == 1
    assert db.mark_details_used([]) == 0
    assert db.mark_details_used(None) == 0


def test_kunnskapsoppslaget_teller_detaljene_det_leverte(fake_db, monkeypatch):
    """Destillatet er den ene kodestien der hjernen faktisk får se et
    detaljminne – seksjonsvalget rører bare memory_main."""
    did = memory.add_detail("Detalj", "innhold")
    treff = [
        {"tittel": "Detalj", "kilde": "memory_details", "dokument_id": str(did),
         "utdrag": "innhold", "score": 0.5, "ref": "memory_details:%s" % did},
        {"tittel": "Leveranse", "kilde": "agent_tasks", "dokument_id": ukjent_id(),
         "utdrag": "annet", "score": 0.4, "ref": "agent_tasks:x"},
    ]
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask", lambda *a, **kw: list(treff))

    txt = knowledge.distill("hva vet jeg?")

    assert "Detalj" in txt and "Leveranse" in txt
    assert fake_db.memory_details.find_one({"_id": did})["use_count"] == 1


def test_treff_som_ikke_fikk_plass_i_destillatet_teller_ikke(fake_db, monkeypatch):
    """Tegnbudsjettet kutter halen av trefflisten. Et treff som aldri kom med
    i prompten, ble aldri lest av noen."""
    med = memory.add_detail("Med", "innhold")
    uten = memory.add_detail("Uten", "innhold")
    treff = [{"tittel": t, "kilde": "memory_details", "dokument_id": str(i),
              "utdrag": "u" * 200, "score": 0.5, "ref": "memory_details:%s" % i}
             for t, i in (("Med", med), ("Uten", uten))]
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask", lambda *a, **kw: list(treff))

    # ett treff rendres til ~270 tegn: budsjettet rekker til det første
    knowledge.distill("q", max_chars=300)

    assert fake_db.memory_details.find_one({"_id": med})["use_count"] == 1
    assert fake_db.memory_details.find_one({"_id": uten})["use_count"] == 0


def test_destillatet_overlever_at_brukstellingen_feiler(fake_db, monkeypatch):
    """Fail-open: kunnskap er en bonus, og en teller som ikke lot seg skrive
    skal ikke koste syklusen den kunnskapen."""
    did = memory.add_detail("Detalj", "innhold")
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask", lambda *a, **kw: [
        {"tittel": "Detalj", "kilde": "memory_details", "dokument_id": str(did),
         "utdrag": "innhold", "score": 0.5, "ref": "r"}])

    def eksploder(_ids):
        raise RuntimeError("basen er nede")
    monkeypatch.setattr(knowledge.db, "mark_details_used", eksploder)

    assert "Detalj" in knowledge.distill("q")


# ------------------------------------------------------------ arkiver_detalj

def test_arkiver_detalj_flytter_dokumentet_til_arkivet(fake_db):
    did = memory.add_detail("Utdatert pitch", "gammel tekst", source="brain")

    kvittering = memory.apply_ops([{"op": "arkiver_detalj", "id": str(did)}])

    assert fake_db.memory_details.docs == []
    (ark,) = fake_db.memory_archive.docs
    assert ark["title"] == "Utdatert pitch" and ark["content"] == "gammel tekst"
    assert ark["original_id"] == str(did) and ark["archived_ts"] > 0
    assert ark["from_collection"] == "memory_details"
    assert ark["_id"] != did          # nytt dokument, som i arkiver_seksjon
    assert kvittering == ["arkiverte detaljminne 'Utdatert pitch' "
                          "(arkiv [%s], ute av kunnskapsindeksen)" % ark["_id"]]


def test_arkivert_detalj_faller_ut_av_kunnskapsindeksen(fake_db):
    did = memory.add_detail("Utdatert", "tekst")
    memory.apply_ops([{"op": "arkiver_detalj", "id": str(did)}])
    (ark,) = fake_db.memory_archive.docs
    assert ark["kb_index"] is False
    assert fake_db.memory_archive.count_documents(memory.KB_INDEX_FILTER) == 0


def test_arkivert_seksjon_forblir_soekbar(fake_db, section_factory):
    """Kontrasten til testen over: arkivet er søkbart for seksjoner (§4).
    Bare detaljer meldes ut."""
    sid = section_factory("Gammelt prosjekt", "innhold")
    memory.apply_ops([{"op": "arkiver_seksjon", "id": str(sid)}])
    (ark,) = fake_db.memory_archive.docs
    assert "kb_index" not in ark
    assert fake_db.memory_archive.count_documents(memory.KB_INDEX_FILTER) == 1


def test_arkiver_detalj_flytter_pekeren_med_seg(fake_db, section_factory):
    sid = section_factory("Seksjon", "innhold")
    memory.apply_ops([{"op": "opprett_detalj", "tittel": "D", "innhold": "i",
                       "seksjon_id": str(sid)}])
    (detalj,) = fake_db.memory_details.docs
    assert fake_db.memory_main.find_one({"_id": sid})["pointers"] == [str(detalj["_id"])]

    memory.apply_ops([{"op": "arkiver_detalj", "id": str(detalj["_id"])}])

    (ark,) = fake_db.memory_archive.docs
    # ingen brutt lenke: pekeren peker videre, nå inn i arkivet
    assert fake_db.memory_main.find_one({"_id": sid})["pointers"] == [
        "arkiv:%s" % ark["_id"]]


def test_arkiver_detalj_logger_kurateringen(fake_db):
    did = memory.add_detail("Utdatert", "tekst")
    memory.apply_ops([{"op": "arkiver_detalj", "id": str(did)}])
    (rad,) = fake_db.memory_log.docs
    assert rad["action"] == "arkiver_detalj" and rad["detail"] == "Utdatert"


def test_arkiver_detalj_paa_ukjent_id_kvitterer_aerlig(fake_db):
    ukjent = ukjent_id()
    kvittering = memory.apply_ops([{"op": "arkiver_detalj", "id": ukjent}])
    assert kvittering == ["fant ikke detaljminne [%s] – arkiver_detalj "
                          "gjorde ingenting" % ukjent]
    assert fake_db.memory_archive.docs == []


def test_arkiver_detalj_paa_seksjons_id_arkiverer_ikke_seksjonen(fake_db, section_factory):
    """Hjernen kan forveksle nivåene. Da skal op-en gjøre ingenting – ikke
    plukke et vilkårlig dokument fra feil samling."""
    sid = section_factory("Viktig seksjon", "innhold")
    kvittering = memory.apply_ops([{"op": "arkiver_detalj", "id": str(sid)}])
    assert kvittering[0].startswith("fant ikke detaljminne")
    assert fake_db.memory_main.find_one({"_id": sid}) is not None
    assert fake_db.memory_archive.docs == []


def test_arkiver_detalj_uten_id_feiler_uten_aa_velte_resten(fake_db):
    did = memory.add_detail("Beholdes", "tekst")
    kvittering = memory.apply_ops([
        {"op": "arkiver_detalj"},
        {"op": "opprett_seksjon", "tittel": "Går likevel gjennom"}])
    assert kvittering[0].startswith("minne-op feilet (arkiver_detalj)")
    assert len(fake_db.memory_main.docs) == 1
    assert fake_db.memory_details.find_one({"_id": did}) is not None


# ------------------------------------------------------------- JSON-kontrakten

def test_op_en_staar_i_syklusprompten():
    """Uten dette kan hovedhjernen ikke kalle op-en – den kjenner bare
    kontrakten den får utlevert."""
    kontrakt = prompts.DEFAULT_PROMPTS["brain_cycle_contract"]
    assert '"op": "arkiver_detalj"' in kontrakt
    assert "arkiver_detalj" in kontrakt.split("Viktige presiseringer")[1]
