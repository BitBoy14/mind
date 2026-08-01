"""Minnerapporten: tallene, og varselet om at tallene ennå ikke bærer.

To ting er verdt å teste her, og de er ikke like.

Det ene er at rapporten er RENT LESENDE. En rapport som selv rører
brukstellerne, måler sin egen kjøring – og da er hele grunnlaget forurenset av
verktøyet som skulle vurdere det. Derfor sperres skrivemetodene i lagringslaget
mens rapporten bygges: et framtidig `update_one` faller på testen, ikke i
produksjon.

Det andre er varselet om tynt datagrunnlag. Brukssporingen på detaljnivå er
dager gammel. Uten varselet ville rapporten sett ut som beslutningsgrunnlag
lenge før den er det, og den første kurateringen ville arkivert på støy. Testene
fester begge retninger: fersk serie -> varsel, moden serie -> ikke varsel.

All testdata er syntetisk, og tiden («now») sendes inn, slik at døgnbøttene i
vekstdelen er de samme uansett når suiten kjøres.
"""
import importlib.util
import json
import os
from datetime import datetime, time as klokke, timedelta

import pytest

import fakemongo
from mind import memory

# tools/ er ikke en pakke (skriptene kjøres direkte med sin egen shebang), så
# modulen lastes fra sti i stedet for å importeres.
TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _last_modul():
    spec = importlib.util.spec_from_file_location(
        "memory_report", os.path.join(TOOLS_DIR, "memory_report.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mr = _last_modul()


# ------------------------------------------------------------------ hjelpere

# Et fast, «midt på dagen»-tidspunkt: da havner nå, nå-1 døgn og nå-2 døgn i
# hvert sitt kalenderdøgn uansett tidssone og sommertid.
NAA = datetime.combine(datetime(2026, 7, 15).date(), klokke(12, 0)).timestamp()
DOGN = 86400.0

SKRIVEMETODER = ("insert_one", "insert_many", "update_one", "update_many",
                 "find_one_and_update", "delete_one", "delete_many",
                 "create_index")


def sperr_skriving(monkeypatch):
    """Enhver skriving mot lagringslaget blir en testfeil fra nå av."""
    def nekt(navn):
        def _nekt(self, *a, **kw):
            raise AssertionError(
                "memory_report skrev til basen: %s.%s()" % (self.name, navn))
        return _nekt
    for m in SKRIVEMETODER:
        monkeypatch.setattr(fakemongo.FakeCollection, m, nekt(m))


def seksjon(fake_db, tittel, innhold="innhold", viktighet=5, **extra):
    doc = {"title": tittel, "content": innhold, "importance": viktighet,
           "tokens": memory.est_tokens(innhold), "use_count": 0,
           "last_used_ts": None, "pointers": []}
    doc.update(extra)
    return fake_db.memory_main.insert_one(doc).inserted_id


def detalj(fake_db, tittel, innhold="innhold", **extra):
    doc = {"title": tittel, "content": innhold,
           "tokens": memory.est_tokens(innhold), "created_ts": NAA - DOGN,
           "use_count": 0, "last_used_ts": None, "source": "brain"}
    doc.update(extra)
    return fake_db.memory_details.insert_one(doc).inserted_id


def skriv_indeks(tmp_path, rader, tilstand=None):
    d = tmp_path / "index"
    d.mkdir(exist_ok=True)
    (d / "rows.json").write_text(json.dumps(rader), encoding="utf-8")
    if tilstand is not None:
        (d / "state.json").write_text(json.dumps(tilstand), encoding="utf-8")
    return str(d)


def rad(coll, doc_id, text="tekst", field="content", chunk=0, ts=NAA):
    return {"key": "%s:%s" % (coll, doc_id), "coll": coll, "doc_id": doc_id,
            "title": "T", "ts": ts, "chunk": chunk, "field": field, "w": 1.0,
            "text": text}


@pytest.fixture
def tom_indeks(tmp_path):
    return skriv_indeks(tmp_path, [])


# ------------------------------------------------------- rent lesende (hardt krav)

def test_rapporten_skriver_ikke_ett_felt(fake_db, monkeypatch, tom_indeks):
    """Hele rapporten bygges med skrivemetodene sperret.

    Det er den eneste kontrollen som holder over tid: en framtidig «mens vi
    likevel er her»-oppdatering vil velte her i stedet for å forurense
    bruksstatistikken den skulle rapportere.
    """
    sid = seksjon(fake_db, "Om brukeren", "tekst", 10)
    detalj(fake_db, "En detalj", section_id=str(sid))
    fake_db.agent_tasks.insert_one({"title": "T", "created_ts": NAA,
                                    "status": "done"})
    fake_db.chat.insert_one({"role": "user", "text": "hei", "ts": NAA})
    fake_db.events.insert_one({"type": "chat_msg", "ts": NAA})
    fake_db.memory_archive.insert_one({"title": "A", "content": "x",
                                       "archived_ts": NAA})

    sperr_skriving(monkeypatch)
    rap = mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks)

    assert rap["lesende"] is True
    assert mr.formater_tekst(rap)          # tekstformen rører heller ingenting


def test_brukstellerne_er_uendret_etter_en_rapport(fake_db, tom_indeks):
    """Samme krav, målt fra andre siden: tellerne skal stå på nøyaktig samme
    tall etter kjøringen som før."""
    did = detalj(fake_db, "Brukt", use_count=3, last_used_ts=NAA - DOGN)
    sid = seksjon(fake_db, "Seksjon", "tekst", 9, use_count=7,
                  last_used_ts=NAA - DOGN)

    mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks)

    assert fake_db.memory_details.find_one({"_id": did})["use_count"] == 3
    assert fake_db.memory_main.find_one({"_id": sid})["use_count"] == 7


# ------------------------------------------------ OBLIGATORISK: tynt datagrunnlag

def test_fersk_maaleserie_gir_varsel_om_tynt_datagrunnlag(fake_db):
    detalj(fake_db, "Brukt i går", use_count=1, last_used_ts=NAA - DOGN)
    detaljer = mr.detalj_rapport(fake_db, NAA)

    t = mr.tynt_datagrunnlag(detaljer, NAA)

    assert t["tynt"] is True
    assert t["eldste_datapunkt_alder_dager"] == pytest.approx(1.0)
    assert t["grense_dager"] == mr.TYNT_GRUNNLAG_DAGER


def test_ingen_bruk_i_det_hele_tatt_er_ogsaa_tynt(fake_db):
    """Null datapunkter er ikke «ingen bruk» – det er ingen måling."""
    detalj(fake_db, "Aldri brukt")
    t = mr.tynt_datagrunnlag(mr.detalj_rapport(fake_db, NAA), NAA)

    assert t["tynt"] is True
    assert t["eldste_datapunkt_ts"] is None
    assert "tom" in t["begrunnelse"]


def test_moden_maaleserie_gir_ikke_varsel(fake_db):
    detalj(fake_db, "Brukt for lenge siden", use_count=2,
           last_used_ts=NAA - 30 * DOGN)
    t = mr.tynt_datagrunnlag(mr.detalj_rapport(fake_db, NAA), NAA)

    assert t["tynt"] is False
    assert t["eldste_datapunkt_alder_dager"] == pytest.approx(30.0)


def test_grensen_gaar_ved_syv_dogn(fake_db):
    detalj(fake_db, "Akkurat på grensen", use_count=1,
           last_used_ts=NAA - mr.TYNT_GRUNNLAG_DAGER * DOGN)
    assert mr.tynt_datagrunnlag(mr.detalj_rapport(fake_db, NAA), NAA)["tynt"] is False

    detalj(fake_db, "Litt innenfor", use_count=1,
           last_used_ts=NAA - (mr.TYNT_GRUNNLAG_DAGER * DOGN - 60))
    assert mr.tynt_datagrunnlag(mr.detalj_rapport(fake_db, NAA), NAA)["tynt"] is False


def test_eldste_datapunkt_avgjoer_ikke_det_nyeste(fake_db):
    """Ett gammelt datapunkt er nok til at serien er lang – et ferskt oppslag
    i dag skal ikke gjøre grunnlaget tynt igjen."""
    detalj(fake_db, "Gammel bruk", use_count=1, last_used_ts=NAA - 40 * DOGN)
    detalj(fake_db, "Fersk bruk", use_count=1, last_used_ts=NAA - 60)

    t = mr.tynt_datagrunnlag(mr.detalj_rapport(fake_db, NAA), NAA)
    assert t["tynt"] is False
    assert t["eldste_datapunkt_alder_dager"] == pytest.approx(40.0)


def test_varselet_staar_oeverst_i_teksten(fake_db, tom_indeks):
    detalj(fake_db, "Brukt nå", use_count=1, last_used_ts=NAA - 3600)
    tekst = mr.formater_tekst(
        mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks))

    assert "TYNT DATAGRUNNLAG" in tekst
    # «øverst» er poenget: varselet skal stå før tallene det gjelder
    assert tekst.index("TYNT DATAGRUNNLAG") < tekst.index("1) HOVEDMINNE")
    assert "IKKE MÅLT ENNÅ" in tekst
    assert "Ikke arkiver" in tekst


def test_teksten_uten_varsel_naar_serien_er_moden(fake_db, tom_indeks):
    detalj(fake_db, "Gammel bruk", use_count=1, last_used_ts=NAA - 40 * DOGN)
    tekst = mr.formater_tekst(
        mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks))

    assert "TYNT DATAGRUNNLAG" not in tekst
    assert "BRUKSSTATISTIKK:" in tekst


# ------------------------------------------------------------------ hovedminnet

def test_hovedminnet_summeres_mot_taket(fake_db):
    seksjon(fake_db, "A", "a" * 350, 10)          # 100 tok + 1
    seksjon(fake_db, "B", "b" * 700, 5)           # 200 tok + 1

    h = mr.hovedminne_rapport(fake_db, NAA)

    assert h["antall"] == 2
    assert h["sum_tokens"] == 302
    assert h["tak_tokens"] == 150_000
    assert h["andel_av_tak_pst"] == pytest.approx(100 * 302 / 150_000)
    assert h["kjerneseksjoner"] == 1               # viktighet >= 9


def test_seksjonene_rapporteres_med_bruk_og_alder(fake_db):
    seksjon(fake_db, "Brukt", "x", 7, use_count=4, last_used_ts=NAA - 2 * DOGN)
    seksjon(fake_db, "Urørt", "x", 3)

    h = mr.hovedminne_rapport(fake_db, NAA)
    brukt, urort = h["seksjoner"]                  # sortert på viktighet

    assert brukt["tittel"] == "Brukt" and brukt["use_count"] == 4
    assert brukt["dager_siden_bruk"] == pytest.approx(2.0)
    assert urort["dager_siden_bruk"] is None
    assert h["aldri_brukt"] == 1
    # id-en er med, slik at en kurateringsop kan peke rett på seksjonen
    assert fakemongo.looks_like_object_id(brukt["id"])


def test_token_avvik_fanges_opp(fake_db):
    """Takregnskapet summerer det LAGREDE tallet. Spriker det fra innholdet,
    er det ikke bare seksjonen som er feil målt – det er taket."""
    seksjon(fake_db, "Løgn", "x" * 3500, 5, tokens=10)
    seksjon(fake_db, "Ærlig", "x" * 350, 5)

    h = mr.hovedminne_rapport(fake_db, NAA)
    assert h["token_avvik"] == 1
    (lognen, _) = sorted(h["seksjoner"], key=lambda s: s["tokens_lagret"])
    assert lognen["tokens_lagret"] == 10 and lognen["tokens_estimert"] == 1001


def test_seksjon_uten_tokenfelt_estimeres_fra_innholdet(fake_db):
    fake_db.memory_main.insert_one({"title": "Uten tokens", "content": "y" * 350,
                                    "importance": 5})
    h = mr.hovedminne_rapport(fake_db, NAA)
    assert h["sum_tokens"] == 101
    assert h["seksjoner"][0]["tokens_lagret"] is None


# ------------------------------------------------------------------ detaljminner

def test_detaljene_telles_med_tokens_og_indeksstatus(fake_db):
    detalj(fake_db, "Indeksert", "a" * 350)
    detalj(fake_db, "Utmeldt", "b" * 700, kb_index=False)

    dt = mr.detalj_rapport(fake_db, NAA)

    assert dt["antall"] == 2 and dt["sum_tokens"] == 302
    assert dt["kb_index_false"] == 1 and dt["indekserbare"] == 1
    assert dt["storste"][0]["tittel"] == "Utmeldt"
    assert dt["storste"][0]["kb_index"] is False


def test_bruksfordelingen_bottes(fake_db):
    for n in (0, 0, 1, 3, 4, 7, 12, 40):
        detalj(fake_db, "d%d" % n, use_count=n,
               last_used_ts=(NAA - DOGN) if n else None)

    dt = mr.detalj_rapport(fake_db, NAA)

    assert dt["bruksfordeling"] == {"0 (aldri)": 2, "1": 1, "2-4": 2,
                                    "5-9": 1, "10+": 2}
    assert dt["brukt_minst_en_gang"] == 6
    assert dt["sum_bruk"] == 67
    assert [r["use_count"] for r in dt["mest_brukt"]] == [40, 12, 7, 4, 3]


def test_detaljer_uten_bruksteller_telles_som_umaalte(fake_db):
    """Mangler feltet, er «aldri brukt» ikke et lavt tall – det er fravær av
    måling, og rapporten skal skille de to."""
    fake_db.memory_details.insert_one({"title": "Fra før tellingen",
                                       "content": "x"})
    detalj(fake_db, "Med teller")

    dt = mr.detalj_rapport(fake_db, NAA)
    assert dt["antall"] == 2 and dt["uten_bruksteller"] == 1


def test_arkivet_deles_i_detaljer_og_seksjoner(fake_db):
    fake_db.memory_archive.insert_one({
        "title": "Arkivert detalj", "content": "x" * 350, "archived_ts": NAA,
        "from_collection": "memory_details", "kb_index": False})
    fake_db.memory_archive.insert_one({
        "title": "Arkivert seksjon", "content": "y" * 350, "archived_ts": NAA})

    a = mr.detalj_rapport(fake_db, NAA)["arkiv"]

    assert a["antall"] == 2 and a["fra_detaljer"] == 1
    assert a["fra_seksjoner_eller_ukjent"] == 1
    assert a["sokbare_i_indeksen"] == 1        # kun seksjonen er søkbar (§4)
    assert a["sum_tokens"] == 202


# ------------------------------------------------------------- kunnskapsindeksen

def test_indeksen_summeres_per_kildesamling(fake_db, tmp_path):
    katalog = skriv_indeks(tmp_path, [
        rad("memory_main", "a", "x" * 35),
        rad("memory_main", "a", "x" * 35, chunk=1),
        rad("memory_details", "b"),
        rad("agent_tasks", "c", field="result"),
        rad("agent_tasks", "c", field="brief"),
    ], tilstand={"last_run_human": "2026-07-15 12:00", "model": "m", "dim": 384,
                 "per_collection": {"memory_main": 1}})

    ix = mr.indeks_rapport(katalog)

    assert ix["tilgjengelig"] is True and ix["rader"] == 5
    hoved = ix["per_samling"]["memory_main"]
    assert hoved["rader"] == 2 and hoved["dokumenter"] == 1
    assert hoved["tegn"] == 70 and hoved["est_tokens"] == 21
    assert ix["per_samling"]["agent_tasks"]["felt"] == {"result": 1, "brief": 1}
    assert ix["tilstand"]["sist_kjort"] == "2026-07-15 12:00"


def test_etterslep_maales_mot_det_basen_har_naa(fake_db, tmp_path):
    """Indeksen er et øyeblikksbilde. Differansen mot basen er ikke en feil,
    men den skal være synlig – ellers leses en gammel indeks som fasit."""
    detalj(fake_db, "Indeksert")
    detalj(fake_db, "Ikke indeksert ennå")
    detalj(fake_db, "Utmeldt", kb_index=False)     # kvalifiserer ikke

    katalog = skriv_indeks(tmp_path, [rad("memory_details", "b")])
    ix = mr.indeks_rapport(katalog, fake_db)

    s = ix["per_samling"]["memory_details"]
    assert s["dokumenter"] == 1 and s["kvalifiserer_naa"] == 2
    assert s["etterslep"] == 1


def test_samling_som_mangler_helt_i_indeksen_er_ikke_usynlig(fake_db, tmp_path):
    fake_db.chat.insert_one({"role": "user", "text": "hei", "ts": NAA})
    ix = mr.indeks_rapport(skriv_indeks(tmp_path, []), fake_db)

    chat = ix["per_samling"]["chat"]
    assert chat["rader"] == 0 and chat["kvalifiserer_naa"] == 1
    assert chat["etterslep"] == 1


def test_bare_ferdige_agentoppgaver_kvalifiserer(fake_db, tmp_path):
    """Samme filter som kunnskapsmotoren: køede og kjørende oppgaver er ikke
    kunnskap ennå, og skal ikke telle som etterslep."""
    for status in ("done", "failed", "queued", "running"):
        fake_db.agent_tasks.insert_one({"title": status, "status": status,
                                        "created_ts": NAA})
    ix = mr.indeks_rapport(skriv_indeks(tmp_path, []), fake_db)
    assert ix["per_samling"]["agent_tasks"]["kvalifiserer_naa"] == 2


def test_manglende_indeks_rapporteres_som_utilgjengelig(fake_db, tmp_path):
    ix = mr.indeks_rapport(str(tmp_path / "finnes-ikke"), fake_db)
    assert ix["tilgjengelig"] is False and "FileNotFoundError" in ix["feil"]


def test_ulesbar_indeks_velter_ikke_rapporten(fake_db, tmp_path):
    katalog = tmp_path / "index"
    katalog.mkdir()
    (katalog / "rows.json").write_text("{ikke json", encoding="utf-8")

    rap = mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=str(katalog))

    assert rap["kunnskapsindeks"]["tilgjengelig"] is False
    assert "IKKE LEST" in mr.formater_tekst(rap)


# ------------------------------------------------------------------ vekst

def test_vekst_telles_per_doegn(fake_db):
    for i in (0, 0, 1, 2, 9):                     # 9 er utenfor et 3-døgns vindu
        fake_db.agent_tasks.insert_one({"title": "t", "status": "done",
                                        "created_ts": NAA - i * DOGN})

    v = mr.vekst_rapport(fake_db, NAA, dager=3)
    a = v["samlinger"]["agent_tasks"]

    assert [p["antall"] for p in a["per_dag"]] == [1, 1, 2]   # eldste først
    assert a["totalt"] == 5 and a["i_vinduet"] == 4
    assert a["snitt_per_dag_vindu"] == pytest.approx(4 / 3)
    assert a["levetid_dager"] == pytest.approx(9.0)


def test_rate_fra_under_ett_doegn_merkes_som_ekstrapolert(fake_db, tom_indeks):
    """98 dokumenter på ti timer blir til «222 per døgn». Tallet er greit å ha,
    men det er en ekstrapolering – leses det som en observert rate, ser veksten
    dobbelt så voldsom ut som den er målt."""
    for i in range(10):
        fake_db.events.insert_one({"type": "x", "ts": NAA - i * 3600})

    v = mr.vekst_rapport(fake_db, NAA, dager=3)["samlinger"]["events"]
    assert v["levetid_under_ett_dogn"] is True
    assert v["snitt_per_dag_levetid"] > 10        # 10 dokumenter på 9 timer

    tekst = mr.formater_tekst(
        mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks))
    assert "EKSTRAPOLERT fra under ett døgn" in tekst


def test_lang_levetid_merkes_ikke_som_ekstrapolert(fake_db):
    fake_db.events.insert_one({"type": "x", "ts": NAA - 10 * DOGN})
    v = mr.vekst_rapport(fake_db, NAA, dager=3)["samlinger"]["events"]
    assert v["levetid_under_ett_dogn"] is False
    assert v["snitt_per_dag_levetid"] == pytest.approx(0.1)


def test_teksten_har_ingen_etterslepende_mellomrom(fake_db, tom_indeks):
    """Kolonnene padder for å stå i flukt – halen av mellomrom skal ikke bli
    med ut i filen rapporten lagres i."""
    seksjon(fake_db, "Om brukeren", "tekst", 10)
    detalj(fake_db, "En detalj")
    tekst = mr.formater_tekst(
        mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks))

    assert [x for x in tekst.splitlines() if x != x.rstrip()] == []


def test_alle_tre_vekstkildene_rapporteres(fake_db):
    fake_db.chat.insert_one({"role": "user", "text": "hei", "ts": NAA})
    fake_db.events.insert_one({"type": "chat_msg", "ts": NAA})

    v = mr.vekst_rapport(fake_db, NAA, dager=2)

    assert set(v["samlinger"]) == {"agent_tasks", "chat", "events"}
    assert v["samlinger"]["chat"]["per_dag"][-1]["antall"] == 1
    assert v["samlinger"]["events"]["totalt"] == 1


def test_samling_uten_tidsstempler_faar_ingen_kurve(fake_db):
    """«hvis de finnes»: mangler feltet, sier rapporten det – den gjetter ikke
    en kurve ut av ingenting."""
    fake_db.chat.insert_one({"role": "user", "text": "uten ts"})

    c = mr.vekst_rapport(fake_db, NAA, dager=3)["samlinger"]["chat"]

    assert c["totalt"] == 1 and c["med_tidsstempel"] == 0
    assert c["per_dag"] is None and c["forste"] is None


def test_dokumenter_med_null_tidsstempel_teller_ikke_som_tidfestet(fake_db):
    fake_db.events.insert_one({"type": "x", "ts": None})
    fake_db.events.insert_one({"type": "y", "ts": NAA})

    e = mr.vekst_rapport(fake_db, NAA, dager=2)["samlinger"]["events"]
    assert e["totalt"] == 2 and e["med_tidsstempel"] == 1


def test_doegnbottene_foelger_kalenderdoegn(fake_db):
    """Bøttene er midnatt-til-midnatt i lokal tid, ikke «siste 24 timer»:
    to dokumenter samme kveld og morgen etter hører til hvert sitt døgn."""
    grenser = mr._dagsgrenser(NAA, 2)
    (i_gaar, _, _), (i_dag, start_i_dag, _) = grenser
    fake_db.events.insert_one({"type": "x", "ts": start_i_dag - 60})
    fake_db.events.insert_one({"type": "y", "ts": start_i_dag + 60})

    e = mr.vekst_rapport(fake_db, NAA, dager=2)["samlinger"]["events"]
    assert [p["dato"] for p in e["per_dag"]] == [i_gaar, i_dag]
    assert [p["antall"] for p in e["per_dag"]] == [1, 1]


@pytest.mark.parametrize("dag", [
    datetime(2026, 3, 30, 12),      # rett etter vårens omstilling
    datetime(2026, 10, 26, 12),     # rett etter høstens
    datetime(2026, 7, 15, 12),
])
def test_doegnbottene_henger_sammen_uten_hull(dag):
    """Regnet fra midnatt til midnatt, ikke som 86400 sekunder: et døgn med
    tidsomstilling er kortere eller lengre enn 24 timer, og en kurve bygget på
    et fast sekundtall ville forskjøvet seg gradvis over et slikt skifte."""
    grenser = mr._dagsgrenser(dag.timestamp(), 4)

    assert len(grenser) == 4
    for (dato, start, slutt), (neste_dato, neste_start, _) in zip(grenser,
                                                                  grenser[1:]):
        assert slutt == neste_start                      # verken hull eller overlapp
        d0 = datetime.fromisoformat(dato).date()
        assert datetime.fromisoformat(neste_dato).date() == d0 + timedelta(days=1)
        assert start < slutt
    assert grenser[-1][0] == dag.date().isoformat()      # siste bøtte er «i dag»


# ------------------------------------------------------------------ CLI

def test_json_utskriften_er_gyldig_json(fake_db, capsys, tom_indeks):
    seksjon(fake_db, "Om brukeren", "tekst", 10)
    detalj(fake_db, "En detalj")

    assert mr.main(["--json", "--dager", "2", "--index-dir", tom_indeks]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["hovedminne"]["antall"] == 1
    assert data["detaljminner"]["antall"] == 1
    assert data["tynt_datagrunnlag"]["tynt"] is True
    assert data["vekst"]["vindu_dager"] == 2


def test_standardutskriften_er_tekst(fake_db, capsys, tom_indeks):
    seksjon(fake_db, "Om brukeren", "tekst", 10)

    assert mr.main(["--index-dir", tom_indeks]) == 0

    ut = capsys.readouterr().out
    assert ut.startswith("MINNERAPPORT")
    for overskrift in ("1) HOVEDMINNE", "2) DETALJMINNER",
                       "3) KUNNSKAPSINDEKSEN", "4) VEKST"):
        assert overskrift in ut


def test_cli_avviser_et_tomt_vekstvindu(fake_db, tom_indeks):
    with pytest.raises(SystemExit) as e:
        mr.main(["--dager", "0", "--index-dir", tom_indeks])
    assert e.value.code == 2


def test_tomt_minne_gir_en_rapport_og_ikke_en_krasj(fake_db, tom_indeks):
    """Nyoppsett: ingen seksjoner, ingen detaljer, ingen indeks."""
    rap = mr.bygg_rapport(fake_db, now=NAA, dager=3, index_dir=tom_indeks)
    tekst = mr.formater_tekst(rap)

    assert rap["hovedminne"]["sum_tokens"] == 0
    assert rap["tynt_datagrunnlag"]["tynt"] is True
    assert "TYNT DATAGRUNNLAG" in tekst
