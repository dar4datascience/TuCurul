"""Pruebas del CLI y de la actualización del README."""

import pytest

from tucurul.cli import COVERAGE_END, COVERAGE_START, build_parser, update_readme


@pytest.fixture()
def readme(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(
        "# TuCurul\n\n"
        "## Completitud\n\n"
        f"{COVERAGE_START}\n"
        "contenido viejo\n"
        f"{COVERAGE_END}\n"
        "\nTexto posterior.\n",
        encoding="utf-8",
    )
    return path


def test_update_readme_replaces_section(readme):
    assert update_readme(readme) is True
    text = readme.read_text(encoding="utf-8")
    assert "contenido viejo" not in text
    assert "| 09 | Ciudad de México |" in text
    assert "Texto posterior." in text
    assert text.index(COVERAGE_START) < text.index(COVERAGE_END)


def test_update_readme_idempotent(readme):
    update_readme(readme)
    first = readme.read_text(encoding="utf-8")
    assert update_readme(readme) is False
    assert readme.read_text(encoding="utf-8") == first


def test_update_readme_missing_markers(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# Sin marcadores\n", encoding="utf-8")
    with pytest.raises(ValueError):
        update_readme(path)


def test_parser_requires_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
