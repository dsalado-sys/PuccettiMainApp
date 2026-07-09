"""Tests de `aprobar_informe` (camino de escritura del semáforo por escenario)."""
from __future__ import annotations

from app.contextos.informe.casos_uso import aprobar_informe
from app.nucleo.modelo import ModuloPuccetti, Proyecto


def _proyecto_con_escenarios(*ids: str, modo: str = "obra-nueva") -> Proyecto:
    p = Proyecto(nombre="P")
    p.fijar_datos(ModuloPuccetti.RENDER_CALCULOS, {
        modo: {"activo": ids[0], "escenarios": [{"id": i, "nombre": i} for i in ids]},
    })
    return p


def test_aprobar_informe_marca_estado_por_escenario():
    p = _proyecto_con_escenarios("e1")
    assert aprobar_informe(p, "obra-nueva", "e1") is True
    inf = p.datos_por_modulo[ModuloPuccetti.INFORME.value]
    assert inf["escenarios"]["obra-nueva:e1"]["estado"] == "aprobado"


def test_aprobar_informe_escenario_inexistente_devuelve_false():
    p = _proyecto_con_escenarios("e1")
    assert aprobar_informe(p, "obra-nueva", "NOPE") is False
    # No crea aprobaciones fantasma.
    assert ModuloPuccetti.INFORME.value not in (p.datos_por_modulo or {})


def test_aprobar_informe_preserva_otras_aprobaciones():
    p = _proyecto_con_escenarios("e1", "e2")
    assert aprobar_informe(p, "obra-nueva", "e1")
    assert aprobar_informe(p, "obra-nueva", "e2")
    esc = p.datos_por_modulo[ModuloPuccetti.INFORME.value]["escenarios"]
    assert esc["obra-nueva:e1"]["estado"] == "aprobado"
    assert esc["obra-nueva:e2"]["estado"] == "aprobado"
