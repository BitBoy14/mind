"""Verktøyregisteret: samlingen 'tools' bak dashbordets Verktøy-modul.

Registeret er skrevet for at FREMTIDIGE agenter skal legge inn det de bygger,
uten å ha lest koden først. Da er det to ting som må holde:

* En ny kjøring for et verktøy som allerede står der, skal RETTE raden – ikke
  lage nummer to med samme navn. Ellers råtner listen første gang noen
  oppdaterer en beskrivelse.
* Opprettet-datoen tilhører verktøyet, ikke raden. Den skal overleve enhver
  senere oppdatering, ellers viser listen når noen sist skrev, og påstår at
  det er da verktøyet ble laget.

Resten er avvisninger: en rad uten «hvorfor», eller med en status dashbordet
ikke kan fargelegge, er verre enn ingen rad – den ser komplett ut.
"""
import pytest

from mind import db


FULL = dict(name="mind-mail", stack="Python 3 (stdlib), CLI",
            path="/opt/mind-mail", does="Leser e-post via mail.tm",
            why="MIND måtte kunne motta verifiseringsmail selv",
            created="2026-08-08", status="under bygging")


def test_registrering_lagrer_alle_feltene(fake_db):
    doc = db.register_tool(**FULL, registered_by="agent:test")
    (rad,) = fake_db.tools.docs
    assert rad["name"] == "mind-mail"
    assert rad["stack"] == "Python 3 (stdlib), CLI"
    assert rad["path"] == "/opt/mind-mail"
    assert rad["does"] == "Leser e-post via mail.tm"
    assert rad["why"] == "MIND måtte kunne motta verifiseringsmail selv"
    assert rad["created"] == "2026-08-08"
    assert rad["status"] == "under bygging"
    assert rad["registered_by"] == "agent:test"
    assert rad["registered_ts"] > 0 and rad["updated_ts"] > 0
    assert doc["name"] == "mind-mail"


def test_ny_registrering_retter_raden_i_stedet_for_aa_duplisere(fake_db):
    db.register_tool(**FULL)
    endret = dict(FULL, status="i drift", does="Leser og venter på e-post")
    db.register_tool(**endret)
    (rad,) = fake_db.tools.docs            # fortsatt ÉN rad
    assert rad["status"] == "i drift"
    assert rad["does"] == "Leser og venter på e-post"


def test_opprettet_dato_overlever_senere_oppdateringer(fake_db):
    """Datoen beskriver verktøyet – ikke sist noen rørte raden."""
    db.register_tool(**FULL)
    db.register_tool(**dict(FULL, created="2027-01-01", status="i drift"))
    (rad,) = fake_db.tools.docs
    assert rad["created"] == "2026-08-08"


def test_ukjent_status_avvises(fake_db):
    with pytest.raises(ValueError, match="ukjent status"):
        db.register_tool(**dict(FULL, status="halvveis"))
    assert fake_db.tools.docs == []


@pytest.mark.parametrize("felt", ["stack", "path", "does", "why", "created"])
def test_tomt_paakrevd_felt_avvises_og_skriver_ingenting(fake_db, felt):
    with pytest.raises(ValueError, match="mangler felt: " + felt):
        db.register_tool(**dict(FULL, **{felt: ""}))
    assert fake_db.tools.docs == []


def test_tomt_navn_avvises(fake_db):
    with pytest.raises(ValueError, match="navn"):
        db.register_tool(**dict(FULL, name="   "))
    assert fake_db.tools.docs == []


def test_navnet_trimmes_saa_samme_verktoy_ikke_blir_to_rader(fake_db):
    db.register_tool(**FULL)
    db.register_tool(**dict(FULL, name="  mind-mail  "))
    (rad,) = fake_db.tools.docs
    assert rad["name"] == "mind-mail"


def test_listen_har_nyeste_verktoy_forst(fake_db):
    db.register_tool(**dict(FULL, name="gammelt", created="2026-08-02"))
    db.register_tool(**dict(FULL, name="nytt", created="2026-08-08"))
    assert [t["name"] for t in db.list_tools()] == ["nytt", "gammelt"]


def test_fjerning_sier_fra_om_noe_faktisk_ble_fjernet(fake_db):
    db.register_tool(**FULL)
    assert db.remove_tool("mind-mail") is True
    assert db.remove_tool("mind-mail") is False
    assert fake_db.tools.docs == []
