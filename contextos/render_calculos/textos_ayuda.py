"""Etiquetas cortas para los parámetros del módulo Render y cálculos.

Diccionario de un único campo por parámetro: `label`. La audiencia son
arquitectos, así que no se incluyen descripciones largas.
"""
from __future__ import annotations

from typing import TypedDict


class AyudaParametro(TypedDict):
    label: str


TEXTOS_AYUDA: dict[str, dict[str, AyudaParametro]] = {
    "urbanisticos": {
        "edificabilidad_m2t_m2s": {"label": "Edificabilidad"},
        "ocupacion_maxima_pct": {"label": "Ocupación máxima"},
        "n_plantas_max": {"label": "Número máximo de plantas"},
        "altura_planta_m": {"label": "Altura de planta"},
        "retranqueo_frontal_m": {"label": "Retranqueo frontal"},
        "retranqueo_lateral_m": {"label": "Retranqueo lateral"},
        "retranqueo_trasero_m": {"label": "Retranqueo trasero"},
        "luz_recta_patio_min_m": {"label": "Luz mínima de patio"},
        "area_patio_min_m2": {"label": "Superficie mínima de patio"},
        "tiene_atico": {"label": "Ático"},
        "retranqueo_atico_m": {"label": "Retranqueo del ático"},
        "atico_computa_edificabilidad": {"label": "Ático computa edificabilidad"},
        "tiene_sotano": {"label": "Sótano"},
        "sotano_computa_edificabilidad": {"label": "Sótano computa edificabilidad"},
    },
    "diseno": {
        "espesor_muro_fachada_m": {"label": "Muro de fachada"},
        "espesor_muro_medianero_m": {"label": "Muro medianero"},
        "espesor_separacion_unidades_m": {"label": "Separación entre unidades"},
        "espesor_tabique_m": {"label": "Tabique"},
        "ancho_min_pasillo_comun_m": {"label": "Pasillo común"},
        "ancho_min_pasillo_vivienda_m": {"label": "Pasillo de vivienda"},
        "diametro_min_vestibulo_m": {"label": "Diámetro de vestíbulo"},
        "ancho_min_puerta_m": {"label": "Paso libre de puerta"},
        "profundidad_max_sin_patio_m": {"label": "Profundidad máxima sin patio"},
    },
    "programa": {
        "uso": {"label": "Uso destino"},
        "categoria_vivienda": {"label": "Tipología de vivienda"},
        "pct_unidades_adaptadas": {"label": "% unidades adaptadas"},
        "salon_cocina_open": {"label": "Salón-cocina integrado"},
        "n_viviendas_por_planta_objetivo": {"label": "Viviendas por planta (forzar)"},
    },
}
