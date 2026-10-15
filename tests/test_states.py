"""Pruebas del catálogo de entidades federativas."""

import pytest

from tucurul.states import get_state, load_states


def test_exactly_32_states():
    assert len(load_states()) == 32


def test_claves_unique_and_contiguous():
    claves = sorted(s.clave for s in load_states())
    assert len(set(claves)) == 32
    assert claves == [f"{i:02d}" for i in range(1, 33)]


def test_distritos_federales_sum_300():
    # Distritación federal del INE: 300 distritos uninominales.
    assert sum(s.distritos_federales for s in load_states()) == 300


def test_senadores_all_3():
    states = load_states()
    assert all(s.senadores == 3 for s in states)
    # 96 de mayoría relativa + 32 de representación proporcional = 128
    # curules; los 32 RP no están en states.csv porque son nacionales.
    assert sum(s.senadores for s in states) == 96


def test_get_state_by_clave_and_abbr():
    cdmx = get_state("09")
    assert cdmx.nombre == "Ciudad de México"
    assert get_state("CDMX") is cdmx or get_state("CDMX") == cdmx
    assert get_state("9") == cdmx


def test_get_state_unknown_raises():
    with pytest.raises(KeyError):
        get_state("XX")
