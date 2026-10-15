"""Pruebas de la matriz de cobertura por entidad."""

import re

import pytest

from tucurul.coverage import Status, load_coverage, render_markdown_table, score
from tucurul.states import load_states


@pytest.fixture(scope="module")
def coverage():
    return load_coverage()


def test_coverage_claves_match_states(coverage):
    state_claves = {s.clave for s in load_states()}
    coverage_claves = {r.clave for r in coverage}
    assert coverage_claves == state_claves


def test_every_status_valid(coverage):
    for row in coverage:
        for dimension, status in row.statuses.items():
            assert isinstance(status, Status), (row.clave, dimension)


def test_score_bounds(coverage):
    for row in coverage:
        assert 0.0 <= score(row) <= 100.0


def test_rendered_table_has_32_data_rows():
    table = render_markdown_table()
    data_rows = [
        line for line in table.splitlines() if re.match(r"\| \d{2} \|", line)
    ]
    assert len(data_rows) == 32


def test_rendered_table_totals():
    table = render_markdown_table()
    assert "**300**" in table
    assert "128 curules" in table
    assert "Leyenda" in table
