"""El salón privado de Junior Suite / Suite es un mínimo editable del Anexo I.1.

Se siembra como estancia `salon` (solo junior_suite/suite), aparece en `filas_min`,
se consolida como `SALON_UNIDAD` y su edición fluye a la config del motor, cambiando
el útil mínimo de la unidad (habitación + salón + baño).
"""
from __future__ import annotations

import pytest

from app.contextos.render_calculos.geometria import programa_hotelero as ph
from app.plataforma.persistencia.anexo_i_hotelero_sqlalchemy import (
    CatalogoHoteleroSQLAlchemy,
)


def test_salon_aparece_en_editor_solo_para_junior_suite_y_suite(session):
    ho = CatalogoHoteleroSQLAlchemy(session)
    filas = ho.filas_min("hotel_5")
    salon = {f["tipologia"] for f in filas if f["estancia"] == "salon"}
    assert salon == {"junior_suite", "suite"}
    # individual/doble no llevan salón privado.
    assert not any(
        f["estancia"] == "salon" and f["tipologia"] in {"individual", "doble"}
        for f in filas
    )
    # La etiqueta legible es "Salón".
    fila_salon = next(f for f in filas if f["estancia"] == "salon")
    assert fila_salon["etiqueta"] == "Salón"


def test_salon_se_consolida_y_edicion_cambia_util_minimo(session):
    ho = CatalogoHoteleroSQLAlchemy(session)
    cons = ho.consolidadas_hotelero()
    assert cons["SALON_UNIDAD"][("hotel_5", "junior_suite")] == pytest.approx(12.0)

    # Útil mínimo con la config sembrada = habitación (20) + salón (12) + baño (5) = 37.
    cfg0 = ph.config_desde_repo(ho)
    assert ph.util_minimo_habitacion("hotel_5", "junior_suite", cfg0) == pytest.approx(37.0)

    # Editar el salón sube el útil mínimo en la misma medida.
    ho.actualizar("hotel_5", "junior_suite", "salon", 15.0)
    assert ho.consolidadas_hotelero()["SALON_UNIDAD"][("hotel_5", "junior_suite")] == pytest.approx(15.0)
    cfg1 = ph.config_desde_repo(ho)
    assert ph.util_minimo_habitacion("hotel_5", "junior_suite", cfg1) == pytest.approx(40.0)
    # Y el desglose de estancias refleja el salón editado.
    estancias = ph.programa_habitacion("junior_suite", "hotel_5", 45.0, cfg1)
    assert next(e for e in estancias if e.nombre == "salon").area_min_m2 == pytest.approx(15.0)
