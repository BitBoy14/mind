"""`memory.apply_ops` – hovedhjernens skrivetilgang til sitt eget minne.

Her utføres det hjernen har bestemt seg for: opprette, oppdatere, komprimere
og arkivere seksjoner. To ting testes derfor like hardt:

  1. **Sideeffektene** – at riktig dokument faktisk endres, at tokens
     regnes om, at fullversjonen bevares før komprimering, at arkivering
     ikke mister innhold.
  2. **Kvitteringen** – lista med klartekst som returneres. Den er hjernens
     ENESTE tilbakemelding på om operasjonen gikk gjennom, og går rett inn i
     neste syklus' kontekst. Lyver den, tror hjernen noe usant om seg selv.

Ops kommer fra en LLM og er per definisjon upålidelig input: manglende
felter, feil typer og oppdiktede op-navn testes eksplisitt.
"""
import pytest
from bson import ObjectId

from mind import memory


def ukjent_id():
    """En gyldig, men ubrukt ObjectId."""
    return str(ObjectId())


# ------------------------------------------------------------------ opprett_seksjon

def test_opprett_seksjon_lagrer_og_kvitterer(fake_db):
    kvittering = memory.apply_ops([{"op": "opprett_seksjon",
                                    "tittel": "Om Mads",
                                    "innhold": "Liker fisking.",
                                    "viktighet": 7}])
    (doc,) = fake_db.memory_main.docs
    assert doc["title"] == "Om Mads"
    assert doc["content"] == "Liker fisking."
    assert doc["importance"] == 7
    assert doc["tokens"] == memory.est_tokens("Liker fisking.")
    assert doc["use_count"] == 0 and doc["pointers"] == []
    assert doc["created_ts"] > 0 and doc["last_used_ts"] > 0
    assert kvittering == [f"opprettet seksjon 'Om Mads' [{doc['_id']}]"]


def test_opprett_seksjon_uten_felter_faller_tilbake_paa_defaults(fake_db):
    memory.apply_ops([{"op": "opprett_seksjon"}])
    (doc,) = fake_db.memory_main.docs
    assert (doc["title"], doc["content"], doc["importance"]) == ("Uten tittel", "", 5)


@pytest.mark.parametrize("inn, ut", [
    (7, 7), ("7", 7), (7.9, 7),          # tall og talltekst
    (99, 10), (-3, 1),                   # klemmes til 1..10
    (0, 5), (None, 5), ("", 5),          # falsy => default 5, ikke 0
])
def test_viktighet_normaliseres(fake_db, inn, ut):
    memory.apply_ops([{"op": "opprett_seksjon", "tittel": "T", "viktighet": inn}])
    assert fake_db.memory_main.docs[-1]["importance"] == ut


def test_opprett_seksjon_logger_kurateringen(fake_db):
    memory.apply_ops([{"op": "opprett_seksjon", "tittel": "Om Mads"}], actor="agent")
    (logg,) = fake_db.memory_log.docs
    assert logg["action"] == "opprett_seksjon"
    assert logg["detail"] == "Om Mads"
    assert logg["actor"] == "agent"


# ------------------------------------------------------------------ oppdater_seksjon

def test_oppdater_seksjon_erstatter_innhold_og_tokens(fake_db, section_factory):
    sid = section_factory("Pågående arbeid", "gammelt innhold", tokens=999)
    kvittering = memory.apply_ops([{"op": "oppdater_seksjon", "id": str(sid),
                                    "innhold": "helt nytt innhold"}])
    doc = fake_db.memory_main.find_one({"_id": sid})
    assert doc["content"] == "helt nytt innhold"
    assert doc["tokens"] == memory.est_tokens("helt nytt innhold")
    assert doc["last_used_ts"] > 0
    assert doc["title"] == "Pågående arbeid"        # tittelen røres ikke
    assert kvittering == [f"oppdaterte seksjon [{sid}]"]


def test_oppdater_seksjon_uten_innhold_tommer_seksjonen(fake_db, section_factory):
    """`op.get("innhold", "")` – utelates feltet, blir seksjonen tom.
    Ingen beskyttelse mot at hjernen sletter innhold ved et uhell."""
    sid = section_factory("Viktig", "mye verdifullt innhold")
    memory.apply_ops([{"op": "oppdater_seksjon", "id": str(sid)}])
    assert fake_db.memory_main.find_one({"_id": sid})["content"] == ""


def test_oppdater_seksjon_uten_id_gir_feilkvittering(fake_db):
    kvittering = memory.apply_ops([{"op": "oppdater_seksjon", "innhold": "x"}])
    assert kvittering == ["minne-op feilet (oppdater_seksjon): 'id'"]
    (logg,) = fake_db.memory_log.docs
    assert logg["action"] == "feil"


def test_oppdater_seksjon_med_soppel_id_gir_feilkvittering(fake_db):
    (kvittering,) = memory.apply_ops([{"op": "oppdater_seksjon",
                                       "id": "ikke-en-objectid", "innhold": "x"}])
    assert kvittering.startswith("minne-op feilet (oppdater_seksjon):")


# ------------------------------------------------------------------ tilfoy_seksjon

def test_tilfoy_seksjon_legger_til_med_blank_linje(fake_db, section_factory):
    sid = section_factory("Lærdommer", "første lærdom")
    kvittering = memory.apply_ops([{"op": "tilfoy_seksjon", "id": str(sid),
                                    "innhold": "andre lærdom"}])
    doc = fake_db.memory_main.find_one({"_id": sid})
    assert doc["content"] == "første lærdom\n\nandre lærdom"
    assert doc["tokens"] == memory.est_tokens(doc["content"])
    assert kvittering == [f"tilføyde til seksjon [{sid}]"]


def test_tilfoy_til_tom_seksjon_gir_ikke_ledende_blanke_linjer(fake_db, section_factory):
    sid = section_factory("Ny seksjon", "")
    memory.apply_ops([{"op": "tilfoy_seksjon", "id": str(sid), "innhold": "første"}])
    assert fake_db.memory_main.find_one({"_id": sid})["content"] == "første"


# ------------------------------------------------------------------ sett_viktighet

@pytest.mark.parametrize("inn, ut", [(9, 9), ("9", 9), (42, 10), (0, 1), (-5, 1)])
def test_sett_viktighet_klemmer_til_gyldig_omraade(fake_db, section_factory, inn, ut):
    """Merk forskjellen fra opprett_seksjon: her brukes `int(op.get(...))`
    uten `or`-fallback, så 0 blir 1 – ikke 5."""
    sid = section_factory("Seksjon", "innhold", importance=5)
    kvittering = memory.apply_ops([{"op": "sett_viktighet", "id": str(sid),
                                    "viktighet": inn}])
    assert fake_db.memory_main.find_one({"_id": sid})["importance"] == ut
    assert kvittering == [f"satte viktighet {ut} på [{sid}]"]


def test_sett_viktighet_logges_ikke(fake_db, section_factory):
    """Eneste op som IKKE skriver til memory_log. Festet fordi
    kurateringsloggen dermed er ufullstendig – en endring her er tilsiktet."""
    sid = section_factory("Seksjon", "innhold")
    memory.apply_ops([{"op": "sett_viktighet", "id": str(sid), "viktighet": 3}])
    assert fake_db.memory_log.docs == []


# ------------------------------------------------------------------ opprett_detalj

def test_opprett_detalj_lagres_og_pekes_til_fra_seksjonen(fake_db, section_factory):
    sid = section_factory("Prosjekt", "kort oppsummering")
    kvittering = memory.apply_ops([{"op": "opprett_detalj",
                                    "tittel": "Full logg",
                                    "innhold": "de lange detaljene",
                                    "seksjon_id": str(sid)}], actor="agent")
    (detalj,) = fake_db.memory_details.docs
    assert detalj["title"] == "Full logg"
    assert detalj["content"] == "de lange detaljene"
    assert detalj["source"] == "agent"
    assert detalj["section_id"] == str(sid)
    assert detalj["tokens"] == memory.est_tokens("de lange detaljene")
    # toveis kobling: seksjonen får en peker tilbake
    assert fake_db.memory_main.find_one({"_id": sid})["pointers"] == [str(detalj["_id"])]
    assert kvittering == [f"opprettet detaljminne 'Full logg' [{detalj['_id']}]"]


def test_opprett_detalj_uten_seksjon_id(fake_db):
    memory.apply_ops([{"op": "opprett_detalj", "innhold": "løs detalj"}])
    (detalj,) = fake_db.memory_details.docs
    assert detalj["title"] == "Detalj"
    assert detalj["section_id"] is None


def test_opprett_detalj_med_ugyldig_seksjon_id_lagrer_likevel(fake_db):
    """Pekerkoblingen har egen try/except: en ubrukelig seksjon_id skal ikke
    koste oss selve detaljminnet."""
    (kvittering,) = memory.apply_ops([{"op": "opprett_detalj", "tittel": "D",
                                       "innhold": "innhold",
                                       "seksjon_id": "ikke-en-objectid"}])
    assert len(fake_db.memory_details.docs) == 1
    assert kvittering.startswith("opprettet detaljminne 'D'")


# ------------------------------------------------------------------ komprimer_seksjon

def test_komprimering_bevarer_fullversjonen_som_detaljminne(fake_db, section_factory):
    langt = "veldig langt innhold " * 50
    sid = section_factory("Prosjekt X", langt, tokens=memory.est_tokens(langt))
    kvittering = memory.apply_ops([{"op": "komprimer_seksjon", "id": str(sid),
                                    "nytt_innhold": "Prosjekt X: kort sagt ferdig."}])
    (detalj,) = fake_db.memory_details.docs
    assert detalj["title"] == "Fullversjon: Prosjekt X"
    assert detalj["content"] == langt          # ingenting går tapt
    doc = fake_db.memory_main.find_one({"_id": sid})
    assert doc["content"] == "Prosjekt X: kort sagt ferdig."
    assert doc["tokens"] == memory.est_tokens(doc["content"])
    assert doc["pointers"] == [str(detalj["_id"])]
    assert kvittering == [f"komprimerte seksjon 'Prosjekt X' "
                          f"(fullversjon i detalj [{detalj['_id']}])"]


def test_komprimering_logger_token_besparelsen(fake_db, section_factory):
    sid = section_factory("Prosjekt X", "x" * 700, tokens=200)
    memory.apply_ops([{"op": "komprimer_seksjon", "id": str(sid),
                       "nytt_innhold": "kort"}])
    (logg,) = fake_db.memory_log.docs
    assert logg["action"] == "komprimer_seksjon"
    assert logg["detail"] == "Prosjekt X (200 -> %d tok)" % memory.est_tokens("kort")


def test_komprimering_uten_nytt_innhold_tommer_seksjonen(fake_db, section_factory):
    """Fullversjonen er reddet i detaljminnet, men hovedminnet står igjen
    med en tom seksjon. Ingen validering stopper det."""
    sid = section_factory("Prosjekt X", "originalt innhold")
    memory.apply_ops([{"op": "komprimer_seksjon", "id": str(sid)}])
    assert fake_db.memory_main.find_one({"_id": sid})["content"] == ""
    assert fake_db.memory_details.docs[0]["content"] == "originalt innhold"


# ------------------------------------------------------------------ arkiver_seksjon

def test_arkivering_flytter_seksjonen_til_arkivet(fake_db, section_factory):
    sid = section_factory("Gammelt prosjekt", "alt om et avsluttet prosjekt",
                          importance=4)
    kvittering = memory.apply_ops([{"op": "arkiver_seksjon", "id": str(sid)}])
    assert fake_db.memory_main.find_one({"_id": sid}) is None      # ute av hovedminnet
    (arkivert,) = fake_db.memory_archive.docs
    assert arkivert["title"] == "Gammelt prosjekt"
    assert arkivert["content"] == "alt om et avsluttet prosjekt"
    assert arkivert["original_id"] == str(sid)
    assert arkivert["archived_ts"] > 0
    assert arkivert["_id"] != sid          # nytt dokument, ny id
    assert kvittering == ["arkiverte seksjon 'Gammelt prosjekt'"]


def test_arkivering_med_en_linje_legger_igjen_en_pekerseksjon(fake_db, section_factory):
    sid = section_factory("Gammelt prosjekt", "lange detaljer", importance=6)
    memory.apply_ops([{"op": "arkiver_seksjon", "id": str(sid),
                       "en_linje": "  Prosjektet ble avsluttet i juni.  "}])
    (rest,) = fake_db.memory_main.docs
    (arkivert,) = fake_db.memory_archive.docs
    assert rest["title"] == "Gammelt prosjekt"
    assert rest["content"] == "Prosjektet ble avsluttet i juni."   # trimmet
    assert rest["importance"] == 2                                 # nedprioritert
    assert rest["pointers"] == ["arkiv:" + str(arkivert["_id"])]
    assert rest["_id"] != sid


def test_arkivering_med_blank_en_linje_legger_ikke_igjen_noe(fake_db, section_factory):
    sid = section_factory("Gammelt prosjekt", "lange detaljer")
    memory.apply_ops([{"op": "arkiver_seksjon", "id": str(sid), "en_linje": "   "}])
    assert fake_db.memory_main.docs == []
    assert len(fake_db.memory_archive.docs) == 1


# ------------------------------------------------------------------ ukjent/ugyldig input

def test_ukjent_op_navn_rapporteres_uten_aa_stoppe_resten(fake_db):
    kvittering = memory.apply_ops([
        {"op": "slett_alt_for_alltid", "id": "1"},
        {"op": "opprett_seksjon", "tittel": "Overlevde"},
    ])
    assert kvittering[0] == "ukjent minne-op: slett_alt_for_alltid"
    assert kvittering[1].startswith("opprettet seksjon 'Overlevde'")
    assert len(fake_db.memory_main.docs) == 1


def test_op_uten_op_felt_behandles_som_ukjent(fake_db):
    assert memory.apply_ops([{"tittel": "mangler op-felt"}]) == ["ukjent minne-op: "]
    assert fake_db.memory_main.docs == []


def test_feilende_op_stopper_ikke_de_neste(fake_db):
    """Per-op try/except: én dårlig op skal koste én op, ikke hele runden."""
    kvittering = memory.apply_ops([
        {"op": "opprett_seksjon", "tittel": "Første"},
        {"op": "opprett_seksjon", "tittel": "Ugyldig", "viktighet": "svært høy"},
        {"op": "opprett_seksjon", "tittel": "Tredje"},
    ])
    assert kvittering[0].startswith("opprettet seksjon 'Første'")
    assert kvittering[1].startswith("minne-op feilet (opprett_seksjon):")
    assert kvittering[2].startswith("opprettet seksjon 'Tredje'")
    assert [d["title"] for d in fake_db.memory_main.docs] == ["Første", "Tredje"]


@pytest.mark.parametrize("ops", [None, [], ()])
def test_tom_ops_liste_er_lovlig(fake_db, ops):
    assert memory.apply_ops(ops) == []
    assert fake_db.memory_main.docs == []


def test_flere_ops_utfores_i_rekkefolge(fake_db):
    kvittering = memory.apply_ops([
        {"op": "opprett_seksjon", "tittel": "A", "innhold": "en"},
        {"op": "opprett_seksjon", "tittel": "B", "innhold": "to"},
        {"op": "opprett_detalj", "tittel": "C", "innhold": "tre"},
    ])
    assert len(kvittering) == 3
    assert [d["title"] for d in fake_db.memory_main.docs] == ["A", "B"]
    assert [d["title"] for d in fake_db.memory_details.docs] == ["C"]


def test_actor_folger_med_i_logg_og_detaljkilde(fake_db, section_factory):
    sid = section_factory("Seksjon", "innhold")
    memory.apply_ops([{"op": "komprimer_seksjon", "id": str(sid),
                       "nytt_innhold": "kort"}], actor="nattkurator")
    assert fake_db.memory_log.docs[0]["actor"] == "nattkurator"
    assert fake_db.memory_details.docs[0]["source"] == "nattkurator"


# ------------------------------------------------------------------ bekreftede bugs
#
# Testene under beskriver ØNSKET oppførsel og er merket xfail fordi koden i
# dag gjør noe annet. De skal IKKE tilpasses koden – de skal bli grønne den
# dagen buggen fikses (xfail_strict=true fanger det opp).

@pytest.mark.kjent_bug
@pytest.mark.xfail(raises=AttributeError,
                   reason="BUG: except-blokken kaller selv op.get() og kaster på nytt "
                          "når op ikke er en dict. Hele ops-lista avbrytes, og "
                          "unntaket forplanter seg opp i cycle._apply_result.")
def test_op_som_ikke_er_dict_skal_rapporteres_ikke_velte_runden(fake_db):
    """En LLM som svarer `"minne_ops": ["opprett_seksjon"]` (liste av strenger
    i stedet for objekter) tar ned hele minneskrivingen for den syklusen –
    inkludert de gyldige opene lenger ned i lista."""
    kvittering = memory.apply_ops(["opprett_seksjon",
                                   {"op": "opprett_seksjon", "tittel": "Gyldig"}])
    assert kvittering[0].startswith("minne-op feilet")
    assert [d["title"] for d in fake_db.memory_main.docs] == ["Gyldig"]


@pytest.mark.kjent_bug
@pytest.mark.xfail(reason="BUG: oppdater_seksjon og sett_viktighet sjekker aldri at "
                          "seksjonen finnes, og kvitterer «oppdaterte seksjon» selv "
                          "når update_one traff null dokumenter.")
def test_oppdatering_av_ikke_eksisterende_seksjon_skal_ikke_kvittere_suksess(fake_db):
    """Hjernen oppgir en id som er arkivert eller hallusinert. Kvitteringen
    sier at oppdateringen gikk gjennom; ingenting ble skrevet. Neste syklus
    tror endringen ligger i minnet."""
    borte = ukjent_id()
    kvittering = memory.apply_ops([
        {"op": "oppdater_seksjon", "id": borte, "innhold": "nytt"},
        {"op": "sett_viktighet", "id": borte, "viktighet": 9},
    ])
    assert fake_db.memory_main.docs == []
    assert not any(k.startswith("oppdaterte seksjon") for k in kvittering)
    assert not any(k.startswith("satte viktighet") for k in kvittering)


@pytest.mark.kjent_bug
@pytest.mark.xfail(reason="BUG: tilfoy_seksjon, komprimer_seksjon og arkiver_seksjon "
                          "returnerer INGEN kvittering når `if s:` slår til – hjernen "
                          "får ingen beskjed om at operasjonen ikke skjedde.")
def test_ops_mot_ikke_eksisterende_seksjon_skal_gi_tilbakemelding(fake_db):
    """Motsatt feil av testen over: her er kvitteringen taus i stedet for
    løgnaktig. Begge deler bryter samme kontrakt – hjernen skal kunne stole
    på at lista beskriver hva som faktisk skjedde."""
    borte = ukjent_id()
    kvittering = memory.apply_ops([
        {"op": "tilfoy_seksjon", "id": borte, "innhold": "nytt"},
        {"op": "komprimer_seksjon", "id": borte, "nytt_innhold": "kort"},
        {"op": "arkiver_seksjon", "id": borte},
    ])
    assert len(kvittering) == 3
