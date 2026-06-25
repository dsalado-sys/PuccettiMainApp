"""Edificabilidad: un solo aviso de techo y respeto de la casilla de coeficiente.

- El "techo" (consumo vs límite) lo da `_alertas_envolvente` con el criterio del
  proyecto: por coeficiente o —si se desmarca la casilla— por ocupación × nº de plantas.
- `ValidarCumplimiento` ya NO replica ese techo contra el coeficiente normativo (evitaba
  el aviso duplicado cuando el coeficiente del proyecto es el del PGOU, y persistía al
  desmarcar el coeficiente). Solo contrasta el PARÁMETRO coeficiente declarado vs el
  normativo, y solo cuando el proyecto dimensiona por coeficiente.
"""
from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import box

from app.contextos.render_calculos.casos_uso import (
    ValidarCumplimiento,
    _alertas_envolvente,
)
from app.contextos.render_calculos.geometria.envolvente import construir_envolvente
from app.contextos.render_calculos.parametros import (
    ParametrosRender,
    ParametrosUrbanisticos,
)

PARCELA = box(0.0, 0.0, 20.0, 20.0)   # 400 m²
AREA = 400.0
_PARCELA_NS = SimpleNamespace(lados=[SimpleNamespace(tipo="fachada", longitud_m=20.0)])


def _validar(coef: float, usar_coef: bool):
    params = ParametrosRender()
    params.urbanisticos.coeficiente_edificabilidad = coef
    params.urbanisticos.usar_coeficiente_edificabilidad = usar_coef
    return ValidarCumplimiento().ejecutar(_PARCELA_NS, params, ParametrosUrbanisticos())


def _tiene_alerta_coef(alertas) -> bool:
    return any("Coeficiente edificabilidad" in a.mensaje for a in alertas)


def test_no_avisa_coeficiente_si_no_supera_el_normativo():
    assert not _tiene_alerta_coef(_validar(coef=2.5, usar_coef=True))   # == normativo


def test_avisa_coeficiente_si_supera_el_normativo_y_se_usa():
    assert _tiene_alerta_coef(_validar(coef=3.0, usar_coef=True))       # 3.0 > 2.5


def test_no_avisa_coeficiente_si_se_desmarca_la_casilla():
    # Aunque el coeficiente declarado supere el normativo, al desmarcar la casilla el
    # suelo se rige por ocupación/altura (validadas aparte): el coeficiente no aplica.
    assert not _tiene_alerta_coef(_validar(coef=3.0, usar_coef=False))


def test_validar_cumplimiento_no_emite_aviso_de_consumo():
    # El aviso "supera el máximo del coeficiente normativo" (consumo) ya no lo emite
    # ValidarCumplimiento: el techo lo cubre `_alertas_envolvente`.
    alertas = _validar(coef=2.5, usar_coef=True)
    assert not any("coeficiente normativo" in a.mensaje for a in alertas)


def test_un_unico_aviso_de_techo_cuando_coef_proyecto_es_el_normativo():
    """Diseño que excede el techo con coeficiente de proyecto == normativo: un SOLO aviso
    de edificabilidad (`_alertas_envolvente` → "techo máximo"), sin duplicado en
    cumplimiento (el contraste de parámetro no salta porque son iguales)."""
    p = ParametrosRender()
    p.urbanisticos.coeficiente_edificabilidad = 2.5   # == normativo (default 2.5)
    p.urbanisticos.usar_coeficiente_edificabilidad = True
    p.urbanisticos.ocupacion_maxima_pct = 100.0
    p.urbanisticos.ocupacion_maxima_pct_tipo = 100.0
    p.urbanisticos.n_plantas_max = 4   # 4 × 400 = 1600 consumido; techo = 2.5 × 400 = 1000
    p.urbanisticos.retranqueo_fachada_m = 0.0
    p.urbanisticos.retranqueo_linderos_m = 0.0
    p.urbanisticos.patios = []
    env = construir_envolvente(PARCELA, p.a_parametros_motor(), None, superficie_referencia=AREA)

    env_alertas = _alertas_envolvente(env, _PARCELA_NS, p)
    val_alertas = ValidarCumplimiento().ejecutar(_PARCELA_NS, p, ParametrosUrbanisticos())

    techo = [a for a in env_alertas if "supera el techo máximo" in a.mensaje]
    coef = [a for a in val_alertas if "Coeficiente edificabilidad" in a.mensaje]
    assert len(techo) == 1   # único aviso de techo
    assert len(coef) == 0    # sin duplicado de cumplimiento (coef == normativo)
