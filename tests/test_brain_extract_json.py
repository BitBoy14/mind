"""`brain._extract_json` – uthenting av JSON fra et modellsvar.

Dette er portvokteren mellom LLM-en og resten av systemet: hver syklus,
hvert agentkall og hver responderrunde går gjennom den. Svaret er
uforutsigbar tekst, så testene her handler om ROBUSTHET mot det modeller
faktisk finner på: kodegjerder, prat rundt JSON-en, klammer inni strenger,
escapede anførselstegn.

Ingen MongoDB, ingen nettverk, ingen LLM – funksjonen er ren tekstbehandling.
"""
import json

import pytest

from mind.brain import _extract_json


# ------------------------------------------------------------------ lykkelige stier

def test_rent_json_objekt():
    assert _extract_json('{"observasjoner": "alt rolig", "tanker": []}') == {
        "observasjoner": "alt rolig", "tanker": []}


def test_omkringliggende_blanktegn_ignoreres():
    assert _extract_json('  \n\n {"a": 1}  \n ') == {"a": 1}


@pytest.mark.parametrize("gjerde", [
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    '```JSON\n{"a": 1}\n```',          # stor forbokstav: regexen faller tilbake
    '```json{"a": 1}```',              # uten linjeskift
])
def test_kodegjerder_pakkes_ut(gjerde):
    assert _extract_json(gjerde) == {"a": 1}


def test_prat_for_og_etter_jsonen():
    svar = ('Selvfølgelig! Her er syklusresultatet:\n'
            '{"arbeidsnotat": "fortsetter i morgen"}\n'
            'Si fra hvis du vil ha noe endret.')
    assert _extract_json(svar) == {"arbeidsnotat": "fortsetter i morgen"}


def test_nostede_objekter_og_lister_beholdes_helt():
    svar = '{"a": {"b": {"c": [1, 2, {"d": 3}]}}, "e": "slutt"}'
    assert _extract_json(svar) == json.loads(svar)


def test_forste_objekt_vinner_nar_det_er_flere():
    assert _extract_json('{"a": 1} {"b": 2}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```') == {"a": 1}


def test_norske_tegn_overlever():
    assert _extract_json('{"tekst": "blåbærsyltetøy æøå"}') == {
        "tekst": "blåbærsyltetøy æøå"}


# ------------------------------------------------------------------ strengskanning

def test_klammer_inni_strenger_forvirrer_ikke_dybdetellingen():
    """Uten strengsporing ville `}` her avsluttet objektet for tidlig."""
    assert _extract_json('{"a": "}{", "b": "{{{"}') == {"a": "}{", "b": "{{{"}


def test_escapet_anforselstegn_avslutter_ikke_strengen():
    assert _extract_json(r'{"a": "han sa \"hei\" og gikk"}') == {
        "a": 'han sa "hei" og gikk'}


def test_escapet_backslash_rett_for_avsluttende_anforselstegn():
    """`"c:\\\\"` slutter faktisk strengen – backslashen er escapet, ikke
    anførselstegnet. En naiv skanner ville tro strengen fortsatte."""
    assert _extract_json(r'{"sti": "c:\\"}') == {"sti": "c:\\"}


def test_linjeskift_inni_streng():
    assert _extract_json(r'{"a": "linje1\nlinje2"}') == {"a": "linje1\nlinje2"}


# ------------------------------------------------------------------ feilsituasjoner

def test_ingen_klammeparentes_gir_valueerror():
    with pytest.raises(ValueError, match="ingen JSON i svaret"):
        _extract_json("Beklager, jeg kan ikke svare på det.")


def test_tom_tekst_gir_valueerror():
    with pytest.raises(ValueError, match="ingen JSON i svaret"):
        _extract_json("")


def test_ubalansert_objekt_gir_valueerror():
    with pytest.raises(ValueError, match="ubalansert JSON i svaret"):
        _extract_json('{"a": 1, "b": {"c": 2}')


def test_syntaksfeil_inni_balanserte_klammer_gir_valueerror():
    """json.JSONDecodeError ARVER fra ValueError – kallere som fanger
    ValueError fanger også denne. Det er kontrakten oppstrøms bygger på."""
    with pytest.raises(ValueError):
        _extract_json("{dette er ikke json}")


def test_feilmelding_avkortes_til_400_tegn():
    """Hele modellsvaret skal ikke lekke inn i logger og feilmeldinger."""
    soppel = "x" * 5000
    with pytest.raises(ValueError) as ei:
        _extract_json(soppel)
    assert len(str(ei.value)) == len("ingen JSON i svaret: ") + 400


# ------------------------------------------------------------------ kjente begrensninger
#
# Ikke feil i streng forstand – funksjonen er «best-effort» – men reelle
# grenser det er verdt å ha festet, slik at en fremtidig omskriving vet
# nøyaktig hva den endrer på. Rapportert som observasjoner, ikke bugs.

def test_toppnivaa_liste_gir_forste_element_ikke_lista():
    """`[{"a": 1}]` returnerer objektet INNI lista. Kallere som forventer
    en liste får stille noe annet enn de tror."""
    assert _extract_json('[{"a": 1}, {"b": 2}]') == {"a": 1}


def test_kodegjerde_uten_json_vinner_over_json_lenger_ned():
    """Regexen tar det FØRSTE gjerdet uansett innhold. Skriver modellen et
    ```python-eksempel før JSON-kontrakten, ser funksjonen aldri JSON-en –
    selv om den ligger der, rett etter gjerdet."""
    svar = '```python\nprint("hei")\n```\n{"a": 1}'
    with pytest.raises(ValueError, match="ingen JSON i svaret"):
        _extract_json(svar)


def test_klamme_i_sitert_prosa_for_jsonen_velter_skanningen():
    """Skanningen starter på første `{` uansett kontekst. Ligger den inni et
    sitat i prosaen, blir strengsporingen faseforskjøvet resten av veien."""
    with pytest.raises(ValueError, match="ubalansert JSON i svaret"):
        _extract_json('Han skrev "{" på tavla, og svaret er {"a": 1}')
