"""Parámetros del proyecto vistos desde el módulo Render y cálculos.

Diferencia importante: aquí vive el modelo "rico" que el técnico edita en la
UI (§2.3 urbanismo + §2.6 diseño + §2.5 programa + ático/sótano). El motor de
geometría sigue trabajando con `geometria.config.Parametros` (estructura más
compacta); el método `a_parametros_motor()` traduce de uno al otro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dominio import CategoriaVivienda, UsoEdificio
from .geometria.config import (
    Parametros as ParametrosMotor,
    ParametrosDiseno as DisenoMotor,
    ParametrosPrograma as ProgramaMotor,
    ParametrosUrbanisticos as UrbMotor,
)


@dataclass
class ParametrosUrbanisticos:
    """§2.3 — gestionado por el técnico o leído de la BBDD de normativa municipal."""
    edificabilidad_m2t_m2s: float = 2.5
    ocupacion_maxima_pct: float = 100.0     # 0..100
    n_plantas_max: int = 3
    retranqueo_frontal_m: float = 0.0
    retranqueo_lateral_m: float = 0.0
    retranqueo_trasero_m: float = 0.0
    altura_planta_m: float = 3.0
    usos_permitidos: list[UsoEdificio] = field(default_factory=lambda: [
        UsoEdificio.VIVIENDA,
        UsoEdificio.APARTAMENTOS_TURISTICOS,
        UsoEdificio.HOTELERO,
    ])
    luz_recta_patio_min_m: float = 3.0
    area_patio_min_m2: float = 12.0
    tiene_atico: bool = False
    retranqueo_atico_m: float = 3.0
    atico_computa_edificabilidad: bool = False
    tiene_sotano: bool = False
    sotano_computa_edificabilidad: bool = False


@dataclass
class ParametrosDiseno:
    """§2.6 — defaults del Anexo II A2.x."""
    espesor_muro_fachada_m: float = 0.25
    espesor_muro_medianero_m: float = 0.25
    espesor_separacion_unidades_m: float = 0.20
    espesor_tabique_m: float = 0.10
    ancho_min_pasillo_comun_m: float = 1.20
    ancho_min_pasillo_vivienda_m: float = 0.90
    diametro_min_vestibulo_m: float = 1.50
    ancho_min_puerta_m: float = 0.80
    profundidad_max_sin_patio_m: float = 12.0


@dataclass
class ParametrosPrograma:
    """§2.5 — uso destino + categoría + accesibilidad."""
    uso: UsoEdificio = UsoEdificio.VIVIENDA
    categoria_vivienda: CategoriaVivienda = CategoriaVivienda.DOS_D
    categoria_hotelero: str = "hotel_3"             # placeholder hasta MVP hotel
    categoria_apartamentos: str = "2_llaves"        # placeholder hasta MVP apt.
    salon_cocina_open: bool = False
    n_viviendas_por_planta_objetivo: int | None = None
    pct_unidades_adaptadas: float = 5.0


@dataclass
class ParametrosRender:
    """Bundle global del módulo Render y cálculos."""
    urbanisticos: ParametrosUrbanisticos = field(default_factory=ParametrosUrbanisticos)
    diseno: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    programa: ParametrosPrograma = field(default_factory=ParametrosPrograma)
    seed: int = 42

    def a_parametros_motor(self) -> ParametrosMotor:
        """Traduce a la estructura que espera el motor de geometría."""
        from .dominio import CATEGORIA_A_NUM_DORMS

        n_dorms = CATEGORIA_A_NUM_DORMS.get(self.programa.categoria_vivienda, 2)
        return ParametrosMotor(
            diseno=DisenoMotor(
                espesor_muro_fachada=self.diseno.espesor_muro_fachada_m,
                espesor_muro_medianero=self.diseno.espesor_muro_medianero_m,
                espesor_separacion_unidades=self.diseno.espesor_separacion_unidades_m,
                espesor_tabiqueria=self.diseno.espesor_tabique_m,
                ancho_min_pasillo_comun=self.diseno.ancho_min_pasillo_comun_m,
                ancho_min_pasillo_vivienda=self.diseno.ancho_min_pasillo_vivienda_m,
                diametro_min_vestibulo=self.diseno.diametro_min_vestibulo_m,
                radio_apertura_puerta=self.diseno.ancho_min_puerta_m,
                luz_recta_patio_min=self.urbanisticos.luz_recta_patio_min_m,
                area_patio_min=self.urbanisticos.area_patio_min_m2,
                profundidad_max_sin_patio=self.diseno.profundidad_max_sin_patio_m,
            ),
            urbanismo=UrbMotor(
                edificabilidad=self.urbanisticos.edificabilidad_m2t_m2s,
                ocupacion_maxima=max(0.0, min(1.0, self.urbanisticos.ocupacion_maxima_pct / 100.0)),
                n_plantas_max=self.urbanisticos.n_plantas_max,
                retranqueo_frontal=self.urbanisticos.retranqueo_frontal_m,
                retranqueo_lateral=self.urbanisticos.retranqueo_lateral_m,
                retranqueo_trasero=self.urbanisticos.retranqueo_trasero_m,
                altura_planta=self.urbanisticos.altura_planta_m,
            ),
            programa=ProgramaMotor(
                uso=self.programa.uso.value,
                categoria=self.programa.categoria_vivienda.value,
                n_dormitorios=n_dorms,
                salon_cocina_open=self.programa.salon_cocina_open,
                n_plantas=self.urbanisticos.n_plantas_max,
                n_viviendas_por_planta=self.programa.n_viviendas_por_planta_objetivo or 1,
                pct_unidades_adaptadas=self.programa.pct_unidades_adaptadas,
            ),
            seed=self.seed,
        )


# ─── Serialización JSON ─────────────────────────────────────────────────────
def parametros_a_dict(p: ParametrosRender) -> dict[str, Any]:
    return {
        "urbanisticos": {
            "edificabilidad_m2t_m2s": p.urbanisticos.edificabilidad_m2t_m2s,
            "ocupacion_maxima_pct": p.urbanisticos.ocupacion_maxima_pct,
            "n_plantas_max": p.urbanisticos.n_plantas_max,
            "retranqueo_frontal_m": p.urbanisticos.retranqueo_frontal_m,
            "retranqueo_lateral_m": p.urbanisticos.retranqueo_lateral_m,
            "retranqueo_trasero_m": p.urbanisticos.retranqueo_trasero_m,
            "altura_planta_m": p.urbanisticos.altura_planta_m,
            "usos_permitidos": [u.value for u in p.urbanisticos.usos_permitidos],
            "luz_recta_patio_min_m": p.urbanisticos.luz_recta_patio_min_m,
            "area_patio_min_m2": p.urbanisticos.area_patio_min_m2,
            "tiene_atico": p.urbanisticos.tiene_atico,
            "retranqueo_atico_m": p.urbanisticos.retranqueo_atico_m,
            "atico_computa_edificabilidad": p.urbanisticos.atico_computa_edificabilidad,
            "tiene_sotano": p.urbanisticos.tiene_sotano,
            "sotano_computa_edificabilidad": p.urbanisticos.sotano_computa_edificabilidad,
        },
        "diseno": {
            "espesor_muro_fachada_m": p.diseno.espesor_muro_fachada_m,
            "espesor_muro_medianero_m": p.diseno.espesor_muro_medianero_m,
            "espesor_separacion_unidades_m": p.diseno.espesor_separacion_unidades_m,
            "espesor_tabique_m": p.diseno.espesor_tabique_m,
            "ancho_min_pasillo_comun_m": p.diseno.ancho_min_pasillo_comun_m,
            "ancho_min_pasillo_vivienda_m": p.diseno.ancho_min_pasillo_vivienda_m,
            "diametro_min_vestibulo_m": p.diseno.diametro_min_vestibulo_m,
            "ancho_min_puerta_m": p.diseno.ancho_min_puerta_m,
            "profundidad_max_sin_patio_m": p.diseno.profundidad_max_sin_patio_m,
        },
        "programa": {
            "uso": p.programa.uso.value,
            "categoria_vivienda": p.programa.categoria_vivienda.value,
            "categoria_hotelero": p.programa.categoria_hotelero,
            "categoria_apartamentos": p.programa.categoria_apartamentos,
            "salon_cocina_open": p.programa.salon_cocina_open,
            "n_viviendas_por_planta_objetivo": p.programa.n_viviendas_por_planta_objetivo,
            "pct_unidades_adaptadas": p.programa.pct_unidades_adaptadas,
        },
        "seed": p.seed,
    }


def parametros_desde_dict(d: dict[str, Any] | None) -> ParametrosRender:
    """Parser tolerante: campos faltantes / inválidos caen a los defaults."""
    base = ParametrosRender()
    if not d:
        return base

    def _f(node: dict[str, Any], clave: str, defecto: float) -> float:
        try:
            return float(node.get(clave, defecto))
        except (TypeError, ValueError):
            return defecto

    def _i(node: dict[str, Any], clave: str, defecto: int) -> int:
        try:
            return int(node.get(clave, defecto))
        except (TypeError, ValueError):
            return defecto

    def _b(node: dict[str, Any], clave: str, defecto: bool) -> bool:
        v = node.get(clave, defecto)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "si", "sí")
        return bool(v)

    urb_in = d.get("urbanisticos") or {}
    usos = urb_in.get("usos_permitidos") or [u.value for u in base.urbanisticos.usos_permitidos]
    usos_validos: list[UsoEdificio] = []
    for v in usos:
        try:
            usos_validos.append(UsoEdificio(v))
        except (ValueError, TypeError):
            continue
    if not usos_validos:
        usos_validos = list(base.urbanisticos.usos_permitidos)

    urb = ParametrosUrbanisticos(
        edificabilidad_m2t_m2s=_f(urb_in, "edificabilidad_m2t_m2s", base.urbanisticos.edificabilidad_m2t_m2s),
        ocupacion_maxima_pct=_f(urb_in, "ocupacion_maxima_pct", base.urbanisticos.ocupacion_maxima_pct),
        n_plantas_max=_i(urb_in, "n_plantas_max", base.urbanisticos.n_plantas_max),
        retranqueo_frontal_m=_f(urb_in, "retranqueo_frontal_m", base.urbanisticos.retranqueo_frontal_m),
        retranqueo_lateral_m=_f(urb_in, "retranqueo_lateral_m", base.urbanisticos.retranqueo_lateral_m),
        retranqueo_trasero_m=_f(urb_in, "retranqueo_trasero_m", base.urbanisticos.retranqueo_trasero_m),
        altura_planta_m=_f(urb_in, "altura_planta_m", base.urbanisticos.altura_planta_m),
        usos_permitidos=usos_validos,
        luz_recta_patio_min_m=_f(urb_in, "luz_recta_patio_min_m", base.urbanisticos.luz_recta_patio_min_m),
        area_patio_min_m2=_f(urb_in, "area_patio_min_m2", base.urbanisticos.area_patio_min_m2),
        tiene_atico=_b(urb_in, "tiene_atico", base.urbanisticos.tiene_atico),
        retranqueo_atico_m=_f(urb_in, "retranqueo_atico_m", base.urbanisticos.retranqueo_atico_m),
        atico_computa_edificabilidad=_b(urb_in, "atico_computa_edificabilidad", base.urbanisticos.atico_computa_edificabilidad),
        tiene_sotano=_b(urb_in, "tiene_sotano", base.urbanisticos.tiene_sotano),
        sotano_computa_edificabilidad=_b(urb_in, "sotano_computa_edificabilidad", base.urbanisticos.sotano_computa_edificabilidad),
    )

    dis_in = d.get("diseno") or {}
    diseno = ParametrosDiseno(
        espesor_muro_fachada_m=_f(dis_in, "espesor_muro_fachada_m", base.diseno.espesor_muro_fachada_m),
        espesor_muro_medianero_m=_f(dis_in, "espesor_muro_medianero_m", base.diseno.espesor_muro_medianero_m),
        espesor_separacion_unidades_m=_f(dis_in, "espesor_separacion_unidades_m", base.diseno.espesor_separacion_unidades_m),
        espesor_tabique_m=_f(dis_in, "espesor_tabique_m", base.diseno.espesor_tabique_m),
        ancho_min_pasillo_comun_m=_f(dis_in, "ancho_min_pasillo_comun_m", base.diseno.ancho_min_pasillo_comun_m),
        ancho_min_pasillo_vivienda_m=_f(dis_in, "ancho_min_pasillo_vivienda_m", base.diseno.ancho_min_pasillo_vivienda_m),
        diametro_min_vestibulo_m=_f(dis_in, "diametro_min_vestibulo_m", base.diseno.diametro_min_vestibulo_m),
        ancho_min_puerta_m=_f(dis_in, "ancho_min_puerta_m", base.diseno.ancho_min_puerta_m),
        profundidad_max_sin_patio_m=_f(dis_in, "profundidad_max_sin_patio_m", base.diseno.profundidad_max_sin_patio_m),
    )

    prog_in = d.get("programa") or {}
    try:
        uso = UsoEdificio(prog_in.get("uso", base.programa.uso.value))
    except (ValueError, TypeError):
        uso = base.programa.uso
    try:
        cat = CategoriaVivienda(prog_in.get("categoria_vivienda", base.programa.categoria_vivienda.value))
    except (ValueError, TypeError):
        cat = base.programa.categoria_vivienda

    n_viv_pp_raw = prog_in.get("n_viviendas_por_planta_objetivo")
    try:
        n_viv_pp = int(n_viv_pp_raw) if n_viv_pp_raw not in (None, "", "auto") else None
    except (TypeError, ValueError):
        n_viv_pp = None

    programa = ParametrosPrograma(
        uso=uso,
        categoria_vivienda=cat,
        categoria_hotelero=str(prog_in.get("categoria_hotelero", base.programa.categoria_hotelero)),
        categoria_apartamentos=str(prog_in.get("categoria_apartamentos", base.programa.categoria_apartamentos)),
        salon_cocina_open=_b(prog_in, "salon_cocina_open", base.programa.salon_cocina_open),
        n_viviendas_por_planta_objetivo=n_viv_pp,
        pct_unidades_adaptadas=_f(prog_in, "pct_unidades_adaptadas", base.programa.pct_unidades_adaptadas),
    )

    return ParametrosRender(
        urbanisticos=urb,
        diseno=diseno,
        programa=programa,
        seed=_i(d, "seed", base.seed),
    )
