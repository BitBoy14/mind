"""Semantisk seleksjon av minneseksjoner – `memory._select_semantic` og
hjelperen `knowledge.section_scores`.

Før denne ruten fantes, tok `select_relevant` med ALT som fikk plass i
budsjettet: relevansfilteret silte kun bort viktighet 1 uten et eneste
nøkkelordtreff. Nå scorer kunnskapsmotoren seksjonene mot syklusens kontekst,
og bare de nærmeste blir med.

Tre krav festes her, i denne rekkefølgen:

  1. Viktighet >= 9 er ubetinget. Ingen score, intet budsjett og ingen topp-k
     kan velge bort hvem brukeren er eller hva som pågår.
  2. Resten kuttes: gulv for relevans, tak på antall, og token-budsjett.
  3. FAIL-OPEN er absolutt. Motor nede, tomt svar, søppelsvar eller exception
     gir dagens alt-inkludert-oppførsel – aldri en feilende syklus.

Kunnskapsmotoren er stengt ute av `ingen_kunnskapsmotor`-fixturen i
conftest.py; her styres svaret eksplisitt med `kb_scores`. Ingen torch, ingen
ekte indeks, ingen MongoDB.
"""
import pytest

from mind import knowledge, memory

# Den EKTE funksjonen, fanget før autouse-fixturen bytter den ut med en fake.
# `section_scores`-testene nederst tester implementasjonen, ikke fixturen.
ekte_section_scores = knowledge.section_scores


def titler(seksjoner):
    return [s["title"] for s in seksjoner]


# ------------------------------------------------------- kjernen er ubetinget

def test_kjerneseksjoner_er_alltid_med(section_factory, kb_scores):
    """Viktighet >= 9 er ikke med i scoringen i det hele tatt – de er med.
    «Kaffe» viser at siling faktisk skjer i samme kall."""
    section_factory("Om brukeren", "x", importance=10)
    section_factory("Pågående arbeid", "y", importance=9)
    naer = section_factory("Nær", "z", importance=5)
    fjern = section_factory("Kaffe", "æ", importance=5)
    kb_scores({naer: 0.9, fjern: 0.02})   # kjernen fikk ingen score i det hele tatt
    assert titler(memory.select_relevant("hva som helst")) == [
        "Om brukeren", "Pågående arbeid", "Nær"]


def test_kjernen_slipper_gjennom_med_elendig_score(section_factory, kb_scores):
    """Samme score på kjernen og på en vanlig seksjon: bare den vanlige
    forsvinner."""
    kjerne = section_factory("Kjerne", "x", importance=9)
    fjern = section_factory("Fjern", "y", importance=5)
    naer = section_factory("Nær", "z", importance=5)
    kb_scores({kjerne: 0.01, fjern: 0.01, naer: 0.5})
    assert titler(memory.select_relevant("q")) == ["Kjerne", "Nær"]


def test_kjernen_belaster_ikke_budsjettet(section_factory, kb_scores):
    """Kjernen legges inn før budsjettet begynner å telle. Prisen er at et
    stort nok kjerneminne kan sprenge budsjettet alene – det er den bevisste
    avveiningen bak «ubetinget»."""
    section_factory("Kjerne A", "x", importance=10, tokens=1_000)
    section_factory("Kjerne B", "y", importance=9, tokens=1_000)
    liten = section_factory("Liten", "z", importance=5, tokens=10)
    kb_scores({liten: 0.9})
    assert titler(memory.select_relevant("q", budget_tokens=100)) == [
        "Kjerne A", "Kjerne B"]


def test_always_core_false_lar_kjernen_scores_som_alle_andre(section_factory,
                                                             kb_scores):
    kjerne = section_factory("Kjerne", "x", importance=10)
    annen = section_factory("Annen", "y", importance=5)
    kb_scores({kjerne: 0.02, annen: 0.9})
    assert titler(memory.select_relevant("q", always_core=False)) == ["Annen"]


# ------------------------------------------------------------------ kuttingen

def test_seksjon_under_gulvet_velges_bort(section_factory, kb_scores):
    naer = section_factory("Nær", "x", importance=5)
    fjern = section_factory("Fjern", "y", importance=5)
    kb_scores({naer: 0.42, fjern: 0.05})
    assert titler(memory.select_relevant("q")) == ["Nær"]


def test_bare_topp_k_ikke_kjerneseksjoner_velges(section_factory, kb_scores):
    """Taket biter selv når alt ville fått plass i budsjettet: et arbeidssett
    skal ikke fylles med det nest nærmeste bare fordi det er ledig plass."""
    ider = [section_factory("S%02d" % i, "x", importance=5, tokens=1)
            for i in range(20)]
    kb_scores({sid: 1.0 - i / 100 for i, sid in enumerate(ider)})
    valgt = titler(memory.select_relevant("q", budget_tokens=10_000))
    assert valgt == ["S%02d" % i for i in range(memory.SEMANTIC_TOP_K)]


def test_budsjettet_gjelder_ogsa_semantisk(section_factory, kb_scores):
    """Som i nøkkelordruten: `continue`, ikke `break` – en enorm seksjon
    stenger ikke døren for de mindre bak seg."""
    best = section_factory("Best", "x", importance=5, tokens=10)
    stor = section_factory("Enorm", "y", importance=5, tokens=50_000)
    tredje = section_factory("Tredje", "z", importance=5, tokens=10)
    kb_scores({best: 0.9, stor: 0.8, tredje: 0.7})
    assert titler(memory.select_relevant("q", budget_tokens=100)) == [
        "Best", "Tredje"]


def test_lik_score_brytes_pa_viktighet_og_rekkefolge(section_factory, kb_scores):
    """Uavgjort skal aldri avgjøres av tilfeldig dict-rekkefølge: rangeringen
    faller tilbake på plasseringen i all_sections (viktighet synkende)."""
    lav = section_factory("Lav viktighet", "x", importance=3)
    hoy = section_factory("Høy viktighet", "y", importance=7)
    kb_scores({lav: 0.5, hoy: 0.5})
    assert titler(memory.select_relevant("q")) == [
        "Høy viktighet", "Lav viktighet"]


def test_semantisk_valg_markerer_bruk(fake_db, section_factory, kb_scores):
    valgt = section_factory("Nær", "x", importance=5)
    vraket = section_factory("Fjern", "y", importance=5)
    kb_scores({valgt: 0.42, vraket: 0.02})
    memory.select_relevant("q")
    lagret = {d["_id"]: d for d in fake_db.memory_main.docs}
    assert lagret[valgt]["use_count"] == 1
    assert lagret[vraket]["use_count"] == 0


def test_sporringen_sendes_videre_til_motoren(section_factory, monkeypatch):
    sett = []
    monkeypatch.setattr(knowledge, "section_scores",
                        lambda q, *a, **kw: sett.append(q) or None)
    section_factory("A", "x")
    memory.select_relevant("nye hendelser + arbeidsnotat")
    assert sett == ["nye hendelser + arbeidsnotat"]


# ---------------------------------------------- ukjent for indeksen != vraket

def test_ukjent_seksjon_er_usett_naar_trefflisten_var_uttommende(section_factory,
                                                                 kb_scores):
    """Gulv = None betyr at motoren ga hele trefflisten. En seksjon som
    mangler, er da ikke rangert ned – den er ikke indeksert ennå. Slike
    slipper gjennom, ellers ville en fersk seksjon vært usynlig for hjernen
    frem til neste indeksering."""
    naer = section_factory("Nær", "x", importance=5)
    fjern = section_factory("Scoret og vraket", "y", importance=5)
    section_factory("Helt fersk", "z", importance=5)
    kb_scores({naer: 0.42, fjern: 0.02}, gulv=None)
    assert titler(memory.select_relevant("q")) == ["Nær", "Helt fersk"]


def test_ukjent_seksjon_kuttes_naar_avkortingen_gikk_under_gulvet(section_factory,
                                                                 kb_scores):
    """Ble trefflisten avkortet på en score som allerede lå under gulvet, VET
    vi at den manglende seksjonen er svakere enn det. Da er den irrelevant,
    ikke usett."""
    naer = section_factory("Nær", "x", importance=5)
    section_factory("Bak avkortingen", "y", importance=5)
    kb_scores({naer: 0.42}, gulv=0.10)
    assert titler(memory.select_relevant("q")) == ["Nær"]


def test_ukjent_seksjon_beholdes_naar_avkortingen_stoppet_over_gulvet(
        section_factory, kb_scores):
    """Avkorting over gulvet sier ingenting: seksjonen kan like gjerne ligge
    rett under kuttet som langt nede. Tvilen kommer den til gode."""
    naer = section_factory("Nær", "x", importance=5)
    fjern = section_factory("Scoret og vraket", "y", importance=5)
    section_factory("Kanskje relevant", "z", importance=5)
    kb_scores({naer: 0.42, fjern: 0.02}, gulv=0.30)
    assert titler(memory.select_relevant("q")) == ["Nær", "Kanskje relevant"]


def test_usette_seksjoner_har_en_kvote(section_factory, kb_scores):
    """Kvoten hindrer at en hel hale av uindekserte seksjoner spiser
    arbeidssettet – f.eks. rett etter en gjenoppbygging av indeksen."""
    naer = section_factory("Nær", "x", importance=5, tokens=1)
    for i in range(6):
        section_factory("U%d" % i, "y", importance=4, tokens=1)
    kb_scores({naer: 0.42})
    valgt = titler(memory.select_relevant("q", budget_tokens=10_000))
    assert valgt == ["Nær"] + ["U%d" % i
                               for i in range(memory.SEMANTIC_UNSEEN_QUOTA)]


# ------------------------------------------------------------------ fail-open

def _to_seksjoner(section_factory):
    section_factory("Treffer", "mongod", importance=5)
    section_factory("Treffer ikke", "urelatert", importance=5)


def test_motor_nede_gir_dagens_oppforsel(section_factory, kb_scores):
    _to_seksjoner(section_factory)
    kb_scores(None)
    assert titler(memory.select_relevant("mongod")) == [
        "Treffer", "Treffer ikke"]


def test_motor_som_kaster_gir_dagens_oppforsel(section_factory, kb_scores):
    _to_seksjoner(section_factory)
    kb_scores(feil=RuntimeError("kunnskapsmotoren brant opp"))
    assert titler(memory.select_relevant("mongod")) == [
        "Treffer", "Treffer ikke"]


def test_ingen_gjenkjent_seksjon_gir_dagens_oppforsel(section_factory, kb_scores):
    """Motoren svarte, men ikke om én eneste minneseksjon (trefflisten var
    full av agentleveranser). Da finnes det ikke noe grunnlag for å kutte."""
    _to_seksjoner(section_factory)
    kb_scores({}, gulv=0.9)
    assert titler(memory.select_relevant("mongod")) == [
        "Treffer", "Treffer ikke"]


def test_soppelsvar_fra_motoren_gir_dagens_oppforsel(section_factory, monkeypatch):
    """Ingen antakelser om formen på svaret: går utpakkingen i stykker, går
    valget videre uten motor."""
    _to_seksjoner(section_factory)
    monkeypatch.setattr(knowledge, "section_scores", lambda *a, **kw: "tull")
    assert titler(memory.select_relevant("mongod")) == [
        "Treffer", "Treffer ikke"]


def test_semantic_false_hopper_over_motoren(section_factory, kb_scores):
    """Nødbrems: `semantic=False` går rett til nøkkelordruten selv når motoren
    svarer helt fint."""
    _to_seksjoner(section_factory)
    naer = section_factory("Nær", "helt andre ord", importance=5)
    kb_scores({naer: 0.9}, gulv=0.05)
    assert titler(memory.select_relevant("mongod")) == ["Nær"]
    assert titler(memory.select_relevant("mongod", semantic=False)) == [
        "Treffer", "Treffer ikke", "Nær"]


def test_tomt_hovedminne_gir_tom_liste_ogsa_med_motor(fake_db, kb_scores):
    kb_scores({"000000000000000000000001": 0.9})
    assert memory.select_relevant("q") == []


# -------------------------------------------------- knowledge.section_scores

TREFF = [
    {"kilde": "agent_tasks", "dokument_id": "a1", "score": 0.90},
    {"kilde": "memory_main", "dokument_id": "m1", "score": 0.50},
    {"kilde": "memory_details", "dokument_id": "d1", "score": 0.30},
    {"kilde": "memory_main", "dokument_id": "m2", "score": 0.20},
]


@pytest.fixture
def varm_motor(monkeypatch):
    """Kunnskapsmotoren svarer med `TREFF` – uten prosess, torch eller indeks."""
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask",
                        lambda q, top, timeout: list(TREFF))


def test_section_scores_plukker_ut_hovedminnet(varm_motor):
    scores, _ = ekte_section_scores("q", top=10)
    assert scores == {"m1": 0.50, "m2": 0.20}


def test_section_scores_setter_gulv_naar_listen_ble_avkortet(varm_motor):
    """Fikk vi like mange treff som vi ba om, er listen kuttet: gulvet er
    laveste score i HELE listen, ikke bare i hovedminnedelen."""
    assert ekte_section_scores("q", top=len(TREFF))[1] == 0.20


def test_section_scores_uten_avkorting_gir_intet_gulv(varm_motor):
    assert ekte_section_scores("q", top=len(TREFF) + 1)[1] is None


def test_section_scores_kan_hente_en_annen_kilde(varm_motor):
    scores, _ = ekte_section_scores("q", kilde="memory_details", top=10)
    assert scores == {"d1": 0.30}


def test_section_scores_er_none_naar_motoren_er_kald(monkeypatch):
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: False)
    assert ekte_section_scores("q") is None


def test_section_scores_er_none_ved_tomt_svar(monkeypatch):
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask", lambda q, top, timeout: [])
    assert ekte_section_scores("q") is None


@pytest.mark.parametrize("tom", ["", "   ", None])
def test_section_scores_sporr_ikke_pa_tom_tekst(monkeypatch, tom):
    """Motoren skal ikke engang vekkes. (En AssertionError her ville blitt
    svelget av except-blokken og gitt grønt uansett – derfor telles kallene.)"""
    vekket = []
    monkeypatch.setattr(knowledge, "_ensure_worker",
                        lambda: vekket.append(1) or True)
    monkeypatch.setattr(knowledge, "_ask", lambda q, top, timeout: list(TREFF))
    assert ekte_section_scores(tom) is None
    assert vekket == []


def test_section_scores_svelger_exceptions(monkeypatch):
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)

    def _eksploder(q, top, timeout):
        raise OSError("røret er brutt")
    monkeypatch.setattr(knowledge, "_ask", _eksploder)
    assert ekte_section_scores("q") is None


def test_section_scores_takler_treff_uten_score(monkeypatch):
    """Et misdannet treff skal ikke velte oppslaget – det hoppes over."""
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask", lambda q, top, timeout: [
        {"kilde": "memory_main", "dokument_id": "m1"},
        {"kilde": "memory_main", "dokument_id": "m2", "score": 0.4},
    ])
    assert ekte_section_scores("q", top=10)[0] == {"m2": 0.4}


def test_section_scores_kutter_lange_sporringer(monkeypatch):
    sendt = []
    monkeypatch.setattr(knowledge, "_ensure_worker", lambda: True)
    monkeypatch.setattr(knowledge, "_ask",
                        lambda q, top, timeout: sendt.append(q) or list(TREFF))
    ekte_section_scores("x" * 5000)
    assert len(sendt[0]) == 2000
