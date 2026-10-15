"""Valores esperados del catálogo INE y utilidades para archivos sintéticos."""

from dbfutil import write_dbf

from tucurul.states import load_states

EXPECTED_DL = {
    "01": 18, "02": 17, "03": 16, "04": 21, "05": 16, "06": 16, "07": 24,
    "08": 22, "09": 33, "10": 15, "11": 22, "12": 28, "13": 18, "14": 20,
    "15": 45, "16": 24, "17": 12, "18": 18, "19": 26, "20": 25, "21": 26,
    "22": 15, "23": 15, "24": 15, "25": 24, "26": 21, "27": 21, "28": 22,
    "29": 15, "30": 30, "31": 21, "32": 18,
}

EXPECTED_SECCIONES = {
    "01": 685, "02": 2155, "03": 525, "04": 548, "05": 1789, "06": 406,
    "07": 2268, "08": 3231, "09": 5579, "10": 1390, "11": 3266, "12": 2704,
    "13": 1858, "14": 3905, "15": 6835, "16": 2767, "17": 945, "18": 1002,
    "19": 2974, "20": 2547, "21": 2904, "22": 1007, "23": 1111, "24": 1843,
    "25": 3828, "26": 1613, "27": 1185, "28": 2107, "29": 631, "30": 4963,
    "31": 1181, "32": 1789,
}

SECCION_FIELDS = [
    ("ENTIDAD", "N", 11, 0),
    ("DISTRITO_F", "N", 11, 0),
    ("DISTRITO_L", "N", 11, 0),
    ("MUNICIPIO", "N", 11, 0),
    ("SECCION", "N", 11, 0),
    ("TIPO", "N", 11, 0),
]
MUNICIPIO_FIELDS = [
    ("ENTIDAD", "N", 11, 0),
    ("MUNICIPIO", "N", 11, 0),
    ("NOMBRE", "C", 60, 0),
]


def make_archive(tmp_path, secc_rows, muni_rows):
    """Empaqueta DBFs sintéticos en un .7z (requiere py7zr)."""
    import py7zr

    archive = tmp_path / "SHAPEFILE.7z"
    with py7zr.SevenZipFile(archive, "w") as z:
        z.writestr(write_dbf(SECCION_FIELDS, secc_rows), "SECCION.dbf")
        z.writestr(write_dbf(MUNICIPIO_FIELDS, muni_rows), "MUNICIPIO.dbf")
        z.writestr(b"dummy", "SECCION.shp")
    return archive


def valid_fixture_rows():
    """Filas sintéticas válidas: una sección por distrito federal."""
    secc_rows, muni_rows = [], []
    for s in load_states():
        muni_rows.append(
            {"ENTIDAD": int(s.clave), "MUNICIPIO": 1, "NOMBRE": f"MPIÓ {s.clave}"}
        )
        for df in range(1, s.distritos_federales + 1):
            secc_rows.append(
                {
                    "ENTIDAD": int(s.clave),
                    "DISTRITO_F": df,
                    "DISTRITO_L": 1,
                    "MUNICIPIO": 1,
                    "SECCION": df,
                    "TIPO": 1,
                }
            )
    return secc_rows, muni_rows
