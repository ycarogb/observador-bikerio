"""A interface não coleta, e a documentação registra o método e o QGIS."""

from pathlib import Path

from observador_bikerio.textos import NOTA_INDICADORES

RAIZ = Path(__file__).resolve().parents[1]


def test_interface_nao_dispara_coleta():
    texto = (RAIZ / "observador_bikerio" / "interface.py").read_text(encoding="utf-8")
    assert "coletar_uma_vez" not in texto
    assert "coletar_continuo" not in texto
    assert "ClienteGbfs" not in texto
    assert "Movimentação total" in texto
    assert "NOTA_INDICADORES" in texto


def test_readme_explica_metodo_comandos_e_qgis():
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert NOTA_INDICADORES in texto
    assert "python -m observador_bikerio coletar-continuo" in texto
    assert "GeoPackage" in texto
    assert "EPSG:4326" in texto
    assert "America/Sao_Paulo" in texto
    assert "cobertura" in texto.lower()


def test_gitignore_protege_base_local():
    texto = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for item in ("data/", "logs/", "config.toml"):
        assert item in texto
