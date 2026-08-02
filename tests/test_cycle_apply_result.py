"""`cycle._apply_result` – der hovedhjernens JSON-svar blir til handling.

Funksjonen tar imot det modellen svarte og effektuerer alt på én gang:
tanker, chatmelding, minneoperasjoner, agentoppgaver, avbrudd,
admin-forslag, arbeidsnotat og stagnasjonsflagg. Den returnerer et
beslutningssammendrag som havner i syklusloggen og i dashbordet.

Inputen er LLM-generert JSON. Testene her handler derfor om at delvis
utfylte, tomme og rart typede svar fører til riktige – og ærlig
rapporterte – sideeffekter.

Ingen MongoDB, ingen nettverk, ingen LLM: `fake_db`/`fake_jarvis` erstatter
lagringen, og `_apply_result` kaller aldri modellen selv.
"""
import pytest
from bson import ObjectId

from mind import config, cycle, db


# ------------------------------------------------------------------ tomt/minimalt svar

def test_tomt_resultat_gir_ingen_beslutninger(fake_db):
    assert cycle._apply_result({}, "normal") == []
    assert fake_db.thoughts.docs == []
    assert fake_db.chat.docs == []
    assert fake_db.agent_tasks.docs == []


def test_tomt_resultat_nullstiller_likevel_stagnasjonsflagget(fake_db):
    """Stagnasjon settes alltid – også når feltet mangler i svaret. Ellers
    ville en gammel «tomgang»-status blitt hengende igjen for alltid."""
    db.set_state({"stagnation": True})
    cycle._apply_result({}, "normal")
    assert db.get_state()["stagnation"] is False


@pytest.mark.parametrize("felt", [
    "tanker", "minne_ops", "agent_oppgaver", "avbryt_oppgaver", "admin_forslag",
])
def test_none_i_listefelt_behandles_som_tom_liste(fake_db, felt):
    """`res.get(x) or []` – modellen sender ofte null i stedet for []."""
    assert cycle._apply_result({felt: None}, "normal") == []


# ------------------------------------------------------------------ tanker

def test_tanker_som_objekter_lagres_med_type(fake_db):
    beslutninger = cycle._apply_result(
        {"tanker": [{"tekst": "en observasjon", "type": "ide"},
                    {"tekst": "en annen"}]}, "normal")
    assert [(t["text"], t["kind"]) for t in fake_db.thoughts.docs] == [
        ("en observasjon", "ide"), ("en annen", "tanke")]
    assert beslutninger == ["2 tanker logget"]


def test_tanke_som_ren_streng_godtas(fake_db):
    """Modellen bryter kontrakten og sender strenger i stedet for objekter –
    det skal ikke koste oss tanken."""
    cycle._apply_result({"tanker": ["bare en streng"]}, "normal")
    assert [(t["text"], t["kind"]) for t in fake_db.thoughts.docs] == [
        ("bare en streng", "tanke")]


def test_tom_tanketekst_hoppes_over(fake_db):
    cycle._apply_result({"tanker": [{"tekst": ""}, {"tekst": None}, {}]}, "normal")
    assert fake_db.thoughts.docs == []


def test_tanker_faar_tomme_refs_og_kommentarer(fake_db):
    cycle._apply_result({"tanker": ["noe"]}, "normal")
    (t,) = fake_db.thoughts.docs
    assert t["refs"] == [] and t["comments"] == [] and t["ts"] > 0


# ------------------------------------------------------------------ Jarvis-idékanalen

def test_jarvis_ide_havner_i_jarvis_koen(fake_db, fake_jarvis):
    db.update_settings({"jarvis_link": True})
    beslutninger = cycle._apply_result(
        {"tanker": [{"tekst": "JARVIS-IDE: Bedre søk :: vektorindeks slår nøkkelord"}]},
        "normal")
    (ide,) = fake_jarvis.ideas.docs
    assert ide["title"] == "Bedre søk"
    assert ide["hypothesis"] == "vektorindeks slår nøkkelord"
    assert ide["status"] == "queued"
    assert "la idé i Jarvis-køen: Bedre søk" in beslutninger
    # tanken logges i MIND OG sendes videre – ikke enten/eller
    assert len(fake_db.thoughts.docs) == 1


def test_jarvis_ide_uten_hypotese_gjenbruker_tittelen(fake_db, fake_jarvis):
    db.update_settings({"jarvis_link": True})
    cycle._apply_result({"tanker": [{"tekst": "JARVIS-IDE: Bare en tittel"}]}, "normal")
    (ide,) = fake_jarvis.ideas.docs
    assert ide["title"] == "Bare en tittel"
    assert ide["hypothesis"] == "Bare en tittel"


def test_jarvis_ide_ignoreres_naar_koblingen_er_av(fake_db, fake_jarvis):
    """Bryteren av = full separasjon. Tanken skal fortsatt logges hos oss."""
    db.update_settings({"jarvis_link": False})
    beslutninger = cycle._apply_result(
        {"tanker": [{"tekst": "JARVIS-IDE: Ide :: hypotese"}]}, "normal")
    assert fake_jarvis.ideas.docs == []
    assert beslutninger == ["1 tanker logget"]
    assert len(fake_db.thoughts.docs) == 1


def test_bare_prefikset_paa_starten_teller(fake_db, fake_jarvis):
    db.update_settings({"jarvis_link": True})
    cycle._apply_result(
        {"tanker": [{"tekst": "jeg vurderte JARVIS-IDE: noe :: noe"}]}, "normal")
    assert fake_jarvis.ideas.docs == []


# ------------------------------------------------------------------ chatmelding

def test_chat_melding_postes_med_hovedhjerne_markor(fake_db):
    beslutninger = cycle._apply_result({"chat_melding": "  hei igjen  "}, "normal")
    (m,) = fake_db.chat.docs
    assert m["role"] == "brain"
    assert m["text"] == "hei igjen"          # trimmet
    assert m["marker"] == "💭 Hovedhjernen"
    assert beslutninger == ["supplerte i chatten"]


@pytest.mark.parametrize("verdi", [None, "", "   ", "null", "NULL", "  Null  "])
def test_tomme_og_null_meldinger_postes_ikke(fake_db, verdi):
    """Modellen skriver ofte strengen «null» når den ikke vil si noe.
    Uten dette filteret ville «null» dukket opp som chatmelding til brukeren."""
    assert cycle._apply_result({"chat_melding": verdi}, "normal") == []
    assert fake_db.chat.docs == []


# ------------------------------------------------------------------ minne_ops

def test_minne_ops_kjores_og_kvitteringen_blir_del_av_beslutningene(fake_db):
    beslutninger = cycle._apply_result(
        {"minne_ops": [{"op": "opprett_seksjon", "tittel": "Ny seksjon",
                        "innhold": "innhold", "viktighet": 6},
                       {"op": "finnes_ikke"}]}, "normal")
    (doc,) = fake_db.memory_main.docs
    assert doc["title"] == "Ny seksjon" and doc["importance"] == 6
    assert beslutninger[0].startswith("opprettet seksjon 'Ny seksjon'")
    assert beslutninger[1] == "ukjent minne-op: finnes_ikke"


def test_minne_ops_utfores_med_brain_som_aktor(fake_db):
    cycle._apply_result({"minne_ops": [{"op": "opprett_seksjon", "tittel": "T"}]},
                        "normal")
    assert fake_db.memory_log.docs[0]["actor"] == "brain"


# ------------------------------------------------------------------ agentoppgaver

OPPGAVE = {"agent_oppgaver": [{"tittel": "Bygg testsuite",
                               "oppdrag": "Skriv pytest-tester",
                               "type": "bygg", "prioritet": 1}]}
CHAT_HENDELSE = [{"type": "chat_msg", "text": "bygg en testsuite"}]


def test_bestilt_agentoppgave_gaar_rett_i_ko(fake_db):
    """Sprang oppgaven ut av noe brukeren sa, skal den starte uten å spørre."""
    beslutninger = cycle._apply_result(OPPGAVE, "normal", CHAT_HENDELSE)
    (t,) = fake_db.agent_tasks.docs
    assert t["title"] == "Bygg testsuite"
    assert t["brief"] == "Skriv pytest-tester"
    assert t["priority"] == 1
    assert t["status"] == "queued"
    assert t["created_by"] == "brain"
    assert t["selfinit"] is False
    assert beslutninger == ["opprettet agentoppgave 'Bygg testsuite'"]


def test_selvinitiert_agentoppgave_venter_paa_godkjenning(fake_db):
    """Uten en utløsende brukerhendelse er oppgaven hjernens eget påfunn."""
    beslutninger = cycle._apply_result(OPPGAVE, "tanke", [])
    (t,) = fake_db.agent_tasks.docs
    assert t["status"] == "avventer_ja"
    assert t["selfinit"] is True
    assert beslutninger == [
        "agentoppgave 'Bygg testsuite' venter på godkjenning (selvinitiert)"]


def test_selvinitiert_gaar_rett_i_ko_naar_porten_er_av(fake_db):
    fake_db.settings.docs[:] = []
    s = dict(config.DEFAULT_SETTINGS)
    s["require_approval_selfinit"] = False
    fake_db.settings.docs.append(s)
    cycle._apply_result(OPPGAVE, "tanke", [])
    (t,) = fake_db.agent_tasks.docs
    assert t["status"] == "queued"
    assert t["selfinit"] is True


def test_kommentar_og_admin_svar_teller_som_bestilling(fake_db):
    """En kommentar på en tanke er også brukeren som ber om noe."""
    assert cycle._bestilt_av_bruker([{"type": "comment"}]) is True
    assert cycle._bestilt_av_bruker([{"type": "admin_decision"}]) is True
    assert cycle._bestilt_av_bruker([{"type": "agent_done"}]) is False
    assert cycle._bestilt_av_bruker([]) is False
    assert cycle._bestilt_av_bruker(None) is False


def test_agentoppgave_uten_felter_faar_defaults(fake_db):
    cycle._apply_result({"agent_oppgaver": [{}]}, "normal")
    (t,) = fake_db.agent_tasks.docs
    assert (t["title"], t["brief"], t["type"], t["priority"]) == (
        "Uten tittel", "", "bygg", 3)


def test_prioritet_som_talltekst_konverteres(fake_db):
    cycle._apply_result({"agent_oppgaver": [{"tittel": "T", "prioritet": "2"}]},
                        "normal")
    assert fake_db.agent_tasks.docs[0]["priority"] == 2


# ------------------------------------------------------------------ avbrudd

def test_avbrudd_flagger_aktiv_oppgave_uten_aa_sette_sluttstatus(fake_db):
    """Kontrakten er bevisst: syklusen ber om avbrudd, agent-manageren dreper
    prosessen og skriver den verifiserte sluttstatusen."""
    tid = fake_db.agent_tasks.insert_one(
        {"title": "kjører", "status": "running"}).inserted_id
    beslutninger = cycle._apply_result({"avbryt_oppgaver": [str(tid)]}, "normal")
    t = fake_db.agent_tasks.find_one({"_id": tid})
    assert t["cancel_requested"] is True
    assert t["status"] == "cancelling"          # ikke «cancelled»
    assert t["cancel_requested_by"] == "brain"
    assert beslutninger == [f"ba om avbrudd av oppgave {tid} "
                            "(prosessen drepes og verifiseres)"]


def test_avbrudd_av_ferdig_oppgave_rapporteres_aerlig(fake_db):
    tid = fake_db.agent_tasks.insert_one(
        {"title": "ferdig", "status": "done"}).inserted_id
    beslutninger = cycle._apply_result({"avbryt_oppgaver": [str(tid)]}, "normal")
    assert beslutninger == [f"oppgave {tid} var allerede avsluttet – "
                            "ingenting å avbryte"]
    assert fake_db.agent_tasks.find_one({"_id": tid})["status"] == "done"


def test_ugyldig_oppgave_id_svelges_stille(fake_db):
    """`except Exception: pass`. Ingen kvittering – men heller ingen krasj
    som ville stoppet resten av resultatbehandlingen."""
    beslutninger = cycle._apply_result(
        {"avbryt_oppgaver": ["ikke-en-objectid", None],
         "arbeidsnotat": "skal fortsatt settes"}, "normal")
    assert beslutninger == []
    assert db.get_state()["working_note"] == "skal fortsatt settes"


def test_avbrudd_av_ukjent_men_gyldig_id(fake_db):
    ukjent = ObjectId()
    assert cycle._apply_result({"avbryt_oppgaver": [str(ukjent)]}, "normal") == [
        f"oppgave {ukjent} var allerede avsluttet – ingenting å avbryte"]


# ------------------------------------------------------------------ admin-forslag

def test_admin_forslag_legges_som_ventende(fake_db):
    beslutninger = cycle._apply_result(
        {"admin_forslag": [{"type": "kode", "tittel": "Testsuite",
                            "beskrivelse": "kjerneflytene mangler tester"}]}, "normal")
    (p,) = fake_db.admin_proposals.docs
    assert p["kind"] == "kode"
    assert p["title"] == "Testsuite"
    assert p["body"] == "kjerneflytene mangler tester"
    assert p["status"] == "pending"
    assert p["payload"] == {}
    assert beslutninger == ["la admin-forslag: Testsuite"]


def test_prompt_forslag_baerer_med_seg_prompt_teksten(fake_db):
    """Kun type=prompt får payload – det er payloaden godkjenningsflyten
    senere skriver inn i prompts-samlingen."""
    cycle._apply_result({"admin_forslag": [
        {"type": "prompt", "tittel": "Ny identitet",
         "prompt_navn": "brain_identity", "prompt_tekst": "Du er MIND."}]}, "normal")
    (p,) = fake_db.admin_proposals.docs
    assert p["payload"] == {"prompt_navn": "brain_identity",
                            "prompt_tekst": "Du er MIND."}


def test_admin_forslag_uten_type_blir_arkitektur(fake_db):
    cycle._apply_result({"admin_forslag": [{"tittel": "Noe"}]}, "normal")
    assert fake_db.admin_proposals.docs[0]["kind"] == "arkitektur"


# ------------------------------------------------------------------ arbeidsnotat og stagnasjon

def test_arbeidsnotat_lagres(fake_db):
    cycle._apply_result({"arbeidsnotat": "fortsetter med testsuiten"}, "normal")
    assert db.get_state()["working_note"] == "fortsetter med testsuiten"


@pytest.mark.parametrize("verdi", [None, "", 0])
def test_falsy_arbeidsnotat_beholder_det_gamle(fake_db, verdi):
    """Notatet nullstilles ikke av et tomt felt – hjernen mister ikke tråden
    fordi den glemte å fylle ut feltet i én syklus."""
    db.set_state({"working_note": "gammelt notat"})
    cycle._apply_result({"arbeidsnotat": verdi}, "normal")
    assert db.get_state()["working_note"] == "gammelt notat"


def test_stagnasjon_settes_og_rapporteres(fake_db):
    beslutninger = cycle._apply_result({"stagnasjon": True}, "tanke")
    assert db.get_state()["stagnation"] is True
    assert beslutninger == ["flagget stagnasjon (ærlig tomgang)"]


def test_stagnasjon_nullstilles_ved_neste_syklus(fake_db):
    cycle._apply_result({"stagnasjon": True}, "tanke")
    beslutninger = cycle._apply_result({"tanker": ["noe skjer"]}, "normal")
    assert db.get_state()["stagnation"] is False
    assert "flagget stagnasjon (ærlig tomgang)" not in beslutninger


# ------------------------------------------------------------------ helhet

def test_alle_deler_av_et_fullt_resultat_effektueres_i_rekkefolge(fake_db):
    tid = fake_db.agent_tasks.insert_one(
        {"title": "gammel", "status": "queued"}).inserted_id
    beslutninger = cycle._apply_result({
        "observasjoner": "ignoreres av _apply_result",
        "tanker": ["en tanke"],
        "chat_melding": "en melding",
        "minne_ops": [{"op": "opprett_seksjon", "tittel": "S"}],
        "agent_oppgaver": [{"tittel": "O"}],
        "avbryt_oppgaver": [str(tid)],
        "admin_forslag": [{"tittel": "F"}],
        "arbeidsnotat": "notat",
        "stagnasjon": False,
    }, "normal", CHAT_HENDELSE)
    assert beslutninger == [
        "1 tanker logget",
        "supplerte i chatten",
        "opprettet seksjon 'S' [%s]" % fake_db.memory_main.docs[0]["_id"],
        "opprettet agentoppgave 'O'",
        f"ba om avbrudd av oppgave {tid} (prosessen drepes og verifiseres)",
        "la admin-forslag: F",
    ]
    assert db.get_state()["working_note"] == "notat"


def test_kind_paavirker_ikke_effektueringen(fake_db):
    """`kind` er med i signaturen, men brukes ikke i kroppen. Festet slik at
    en fremtidig natt-spesifikk oppførsel blir et bevisst valg."""
    for kind in ("normal", "tanke", "natt", "noe helt annet"):
        assert cycle._apply_result({"tanker": ["x"]}, kind) == ["1 tanker logget"]
    assert len(fake_db.thoughts.docs) == 4


# ------------------------------------------------------------------ fiksede bugs
#
# Var xfail til buggene ble fikset – nå vanlige regresjonstester.

def test_antall_loggede_tanker_skal_stemme_med_det_som_ble_lagret(fake_db):
    """Sammendraget går inn i syklusloggen og i neste syklus' kontekst. Det
    skal telle det som faktisk ble lagret, ikke det modellen sendte inn."""
    beslutninger = cycle._apply_result(
        {"tanker": [{"tekst": "ekte"}, {"tekst": ""}, "også ekte", {"tekst": None}]},
        "normal")
    assert len(fake_db.thoughts.docs) == 2
    assert beslutninger == ["2 tanker logget"]


def test_ugyldig_prioritet_skal_ikke_avbryte_resten_av_resultatet(fake_db):
    """Alt annet i `_apply_result` tåler rar LLM-input. En modell som skriver
    «prioritet: høy» skal ikke ta ned hele effektueringen."""
    cycle._apply_result({
        "agent_oppgaver": [{"tittel": "T", "prioritet": "høy"}],
        "admin_forslag": [{"tittel": "Skal fortsatt registreres"}],
        "arbeidsnotat": "skal fortsatt lagres",
    }, "normal")
    assert len(fake_db.admin_proposals.docs) == 1
    assert db.get_state()["working_note"] == "skal fortsatt lagres"
