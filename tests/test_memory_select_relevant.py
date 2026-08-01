"""`memory.select_relevant` – hvilke minneseksjoner som havner i arbeidsminnet.

Dette er hovedhjernens «hva husker jeg akkurat nå». Velger den feil, tenker
hjernen på feil grunnlag – uten at noe krasjer. Derfor testes rangeringen,
token-budsjettet og bruks-markeringen, ikke bare at det kommer noe tilbake.

Kjører mot ekte `memory.py` og ekte `db.py`; kun lagringen er in-memory.

Dette er TILBAKEFALLSRUTEN. Etter at den semantiske seleksjonen kom til, går
`select_relevant` først til kunnskapsmotoren; her er den stengt ute av
`ingen_kunnskapsmotor`-fixturen, slik at nøkkelordruten testes rent. Det er
samtidig fail-open-garantien: dette er nøyaktig oppførselen syklusen får når
motoren er kald eller nede. Den semantiske ruten testes i
`test_memory_semantisk_seleksjon.py`.

Scoringsformelen som festes her:
    score = antall unike spørreord (>= 4 tegn) som forekommer som DELSTRENG
            i «tittel\\ninnhold» (små bokstaver)
          + viktighet * 0,5
          + 100 hvis always_core og viktighet >= 9
"""
import pytest

from mind import config, memory


def titler(seksjoner):
    return [s["title"] for s in seksjoner]


# ------------------------------------------------------------------ rangering

def test_nokkelordtreff_rangerer_over_treffloest(section_factory):
    section_factory("Databasedrift", "mongod kjører på port 27018", importance=5)
    section_factory("Kaffevaner", "brenner egne bønner", importance=5)
    assert titler(memory.select_relevant("hva skjer med mongod?"))[0] == "Databasedrift"


def test_flere_ulike_ord_gir_hoyere_score_enn_ett(section_factory):
    section_factory("To treff", "mongod og daemon i samme seksjon", importance=5)
    section_factory("Ett treff", "bare daemon her", importance=5)
    assert titler(memory.select_relevant("mongod daemon")) == ["To treff", "Ett treff"]


def test_samme_ord_flere_ganger_teller_bare_en_gang(section_factory):
    """Scoringen går over et SETT av ord og teller forekomst, ikke antall:
    gjentakelse gir ingen ekstra vekt – verken i spørringen eller i seksjonen."""
    section_factory("Mange", "mongod mongod mongod mongod", importance=5)
    section_factory("Ett", "mongod", importance=5)
    valgt = memory.select_relevant("mongod mongod mongod")
    assert set(titler(valgt)) == {"Mange", "Ett"}
    # nøyaktig samme score (1 + 2,5) – ingen av dem rangeres foran den andre
    assert titler(valgt) == ["Mange", "Ett"]     # uavgjort => opprinnelig rekkefølge


def test_viktighet_teller_med_i_scoren(section_factory):
    """+0,5 per viktighetspoeng: en viktig seksjon uten treff slår en
    mindre viktig med ett treff (0 + 4,0 mot 1 + 1,0)."""
    section_factory("Viktig uten treff", "helt andre ord", importance=8)
    section_factory("Uviktig med ordet", "mongod", importance=2)
    assert titler(memory.select_relevant("mongod"))[0] == "Viktig uten treff"


def test_kjerneseksjoner_kommer_alltid_forst(section_factory):
    """Viktighet >= 9 får +100 og kan ikke utkonkurreres av nøkkelordtreff."""
    section_factory("Om brukeren", "ingen relevante ord her", importance=10)
    section_factory("Om meg selv", "heller ingen", importance=9)
    section_factory("Perfekt treff", "mongod port daemon syklus", importance=8)
    assert titler(memory.select_relevant("mongod port daemon syklus")) == [
        "Om brukeren", "Om meg selv", "Perfekt treff"]


def test_always_core_false_fjerner_kjerneboosten(section_factory):
    """Med boosten: kjernen har 100 poeng forsprang. Uten: 4,5 mot 4,5 –
    uavgjort, og seksjonene stiller likt."""
    section_factory("Kjerne", "ingen treff", importance=9)
    section_factory("Treff", "mongod", importance=7)
    assert titler(memory.select_relevant("mongod", always_core=True))[0] == "Kjerne"
    uten = memory.select_relevant("mongod", always_core=False)
    assert set(titler(uten)) == {"Kjerne", "Treff"}


def test_ord_kortere_enn_fire_tegn_ignoreres(section_factory):
    """_WORD krever minst fire tegn – ellers ville «og», «i», «på» matchet alt."""
    assert memory._WORD.findall("abc og på abcd 27018 blåbær") == [
        "abcd", "27018", "blåbær"]
    section_factory("Lang", "abcd", importance=2)
    section_factory("Kort", "abc", importance=2)
    # kun «abcd» blir et søkeord; «abc» forsvinner
    assert titler(memory.select_relevant("abc abcd")) == ["Lang", "Kort"]


def test_matching_er_delstreng_ikke_helord(section_factory):
    """«test» treffer «protest». Kjent svakhet ved delstrengsøket – festet
    her fordi et fremtidig semantisk søk må vite hva dagens oppførsel er."""
    section_factory("Protest", "en protest mot noe", importance=2)
    section_factory("Urelatert", "ingenting felles", importance=2)
    assert titler(memory.select_relevant("test"))[0] == "Protest"


def test_matching_er_case_insensitiv(section_factory):
    section_factory("Stor bokstav", "MONGOD KJØRER", importance=5)
    section_factory("Urelatert", "ingenting", importance=5)
    assert titler(memory.select_relevant("mongod"))[0] == "Stor bokstav"


def test_tittelen_teller_som_soketekst(section_factory):
    section_factory("Mongod-drift", "innholdet nevner ikke ordet", importance=5)
    section_factory("Urelatert", "ingenting", importance=5)
    assert titler(memory.select_relevant("mongod"))[0] == "Mongod-drift"


# ------------------------------------------------------------------ token-budsjett

def test_budsjettet_hindrer_store_seksjoner(section_factory):
    section_factory("Liten", "mongod", importance=6, tokens=10)
    section_factory("Kjempestor", "mongod", importance=5, tokens=50_000)
    assert titler(memory.select_relevant("mongod", budget_tokens=100)) == ["Liten"]


def test_for_stor_seksjon_hopper_over_men_stopper_ikke_utvalget(section_factory):
    """Koden bruker `continue`, ikke `break`. «Liten B» ligger BAK den
    altfor store seksjonen i rangeringen og kommer likevel med."""
    section_factory("Liten A", "mongod", importance=7, tokens=10)
    section_factory("Altfor stor", "mongod", importance=6, tokens=50_000)
    section_factory("Liten B", "mongod", importance=5, tokens=10)
    assert titler(memory.select_relevant("mongod", budget_tokens=100)) == [
        "Liten A", "Liten B"]


def test_forste_seksjon_tas_med_selv_om_den_sprenger_budsjettet(section_factory):
    """`and chosen` gjør at budsjettet kan overskrides av det FØRSTE valget:
    hovedhjernen skal aldri stå helt uten minne. Prisen er at ett kall kan
    bli langt dyrere enn budsjettet antyder."""
    section_factory("Alene og enorm", "mongod", importance=5, tokens=999_999)
    assert titler(memory.select_relevant("mongod", budget_tokens=10)) == ["Alene og enorm"]
    assert titler(memory.select_relevant("mongod", budget_tokens=0)) == ["Alene og enorm"]


def test_standardbudsjettet_hentes_fra_config(section_factory, monkeypatch):
    monkeypatch.setattr(config, "WORKSET_TARGET_TOKENS", 50)
    section_factory("Passer", "mongod", importance=6, tokens=40)
    section_factory("Passer ikke", "mongod", importance=5, tokens=40)
    assert titler(memory.select_relevant("mongod")) == ["Passer"]


def test_seksjon_uten_token_felt_estimeres(section_factory):
    """Mangler `tokens`-feltet, faller koden tilbake på est_tokens(innhold).
    Uten den fallbacken ville seksjonen telt som 0 tokens og alltid fått plass."""
    assert memory.est_tokens("a" * 3500) == 1001
    section_factory("Med tokenfelt", "mongod", importance=6, tokens=10)
    section_factory("Uten tokenfelt", "a" * 3500, importance=5)
    assert titler(memory.select_relevant("mongod", budget_tokens=100)) == [
        "Med tokenfelt"]


# ------------------------------------------------------------------ relevansfilteret

@pytest.mark.parametrize("viktighet", list(range(1, 11)))
def test_bare_viktighet_1_faller_ut_av_relevansfilteret(section_factory, viktighet):
    """Terskelen `score <= 0,5` treffer kun viktighet 1 uten nøkkelordtreff:
    allerede viktighet 2 gir 1,0 poeng helt uten treff.

    To reelle konsekvenser, begge verdt å kjenne før minnesøket bygges om:
      * funksjonen returnerer i praksis ALT som får plass i budsjettet,
        rangert – den siler ikke bort irrelevant innhold.
      * unntaket `and viktighet < 9` i filteret er dødt: en seksjon med
        viktighet >= 9 kommer aldri ned på 0,5 poeng i utgangspunktet.
    """
    section_factory("Uten et eneste treff", "kaffe og vaffel", importance=viktighet)
    valgt = memory.select_relevant("mongod port daemon", always_core=False)
    assert bool(valgt) is (viktighet >= 2)


def test_treff_redder_seksjon_med_viktighet_1(section_factory):
    section_factory("Bagatell uten treff", "helt urelatert", importance=1)
    section_factory("Bagatell med treff", "mongod", importance=1)
    assert titler(memory.select_relevant("mongod")) == ["Bagatell med treff"]


# ------------------------------------------------------------------ sideeffekter

def test_valgte_seksjoner_markeres_som_brukt(fake_db, section_factory):
    valgt_id = section_factory("Databasedrift", "mongod", importance=5)
    vraket_id = section_factory("Bagatell", "urelatert", importance=1)
    memory.select_relevant("mongod")
    lagret = {d["_id"]: d for d in fake_db.memory_main.docs}
    assert lagret[valgt_id]["use_count"] == 1
    assert lagret[valgt_id]["last_used_ts"] > 0
    assert lagret[vraket_id]["use_count"] == 0
    assert "last_used_ts" not in lagret[vraket_id]


def test_gjentatte_kall_oker_bruksteller(fake_db, section_factory):
    sid = section_factory("Databasedrift", "mongod", importance=5)
    for _ in range(3):
        memory.select_relevant("mongod")
    assert fake_db.memory_main.find_one({"_id": sid})["use_count"] == 3


# ------------------------------------------------------------------ kanttilfeller

def test_tomt_hovedminne_gir_tom_liste(fake_db):
    assert memory.select_relevant("hva som helst") == []


def test_tom_og_none_sporring_faller_tilbake_paa_viktighet(section_factory):
    """Ingen spørretekst = ingen nøkkelordpoeng; rangeringen blir ren
    viktighetsrangering. None skal ikke krasje (`query_text or ""`)."""
    section_factory("Viktigst", "a", importance=9)
    section_factory("Middels", "b", importance=5)
    section_factory("Minst", "c", importance=2)
    assert titler(memory.select_relevant("")) == ["Viktigst", "Middels", "Minst"]
    assert titler(memory.select_relevant(None)) == ["Viktigst", "Middels", "Minst"]


def test_returnerer_hele_dokumenter_ikke_bare_id(section_factory):
    section_factory("Databasedrift", "mongod kjører", importance=6)
    (s,) = memory.select_relevant("mongod")
    assert s["title"] == "Databasedrift"
    assert s["content"] == "mongod kjører"
    assert s["importance"] == 6
    assert "_id" in s
