"""Parámetros del proyecto vistos desde el módulo Render y cálculos.

Iteración 4 (2026-06-04):
- Renombrado `edificabilidad_m2t_m2s` → `coeficiente_edificabilidad`.
- Eliminado `altura_planta_m` (no se usaba en cálculos).
- Tres retranqueos antiguos (frontal/lateral/trasero) reemplazados por dos
  direccionales: `retranqueo_fachada_m` (resta solo desde lados tipo "fachada")
  y `retranqueo_linderos_m` (resta solo desde lados tipo "medianera").
- `usos_permitidos` pasa de `list[UsoEdificio]` a `list[str]` con valores
  fijos del PGOU: "residencial" | "hotelero" | "terciario" | "mixto".
  Hoy es decorativo (sin mapeo al uso del programa).
- Tres porcentajes explícitos: `pct_muros`, `pct_circulacion` y `pct_nucleo`
  (porcentajes 0-100). Suma ≤ 90% (validado en motor).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dominio import (
    CategoriaApartamentos,
    CategoriaVivienda,
    TipologiaApartamento,
    UsoEdificio,
)
from .geometria.config import (
    Parametros as ParametrosMotor,
    ParametrosDiseno as DisenoMotor,
    ParametrosPrograma as ProgramaMotor,
    ParametrosUrbanisticos as UrbMotor,
)


USOS_PGOU_VALIDOS: tuple[str, ...] = ("residencial", "hotelero", "terciario", "mixto")


@dataclass
class ParametrosUrbanisticos:
    """§2.3 — gestionado por el técnico o leído de la BBDD de normativa municipal."""
    coeficiente_edificabilidad: float = 2.5
    usar_coeficiente_edificabilidad: bool = True
    ocupacion_maxima_pct: float = 100.0     # 0..100
    n_plantas_max: int = 3
    retranqueo_fachada_m: float = 0.0
    retranqueo_linderos_m: float = 0.0
    usos_permitidos: list[str] = field(default_factory=lambda: [
        "residencial", "hotelero", "mixto",
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
    """§2.6 — defaults del Anexo II A2.x.

    Iteración 4: tres porcentajes explícitos para muros, circulación y núcleo.
    Suma de los tres ≤ 90% (validado en motor).
    """
    espesor_muro_fachada_m: float = 0.25
    espesor_muro_medianero_m: float = 0.25
    espesor_separacion_unidades_m: float = 0.20
    espesor_tabique_m: float = 0.10
    ancho_min_pasillo_comun_m: float = 1.20
    ancho_min_pasillo_vivienda_m: float = 0.90
    diametro_min_vestibulo_m: float = 1.50
    ancho_min_puerta_m: float = 0.80
    profundidad_max_sin_patio_m: float = 12.0
    pct_muros: float = 20.0
    pct_circulacion: float = 8.0
    pct_nucleo: float = 5.0


@dataclass
class ParametrosPrograma:
    """§2.5 — uso destino + categoría + accesibilidad."""
    uso: UsoEdificio = UsoEdificio.VIVIENDA
    categoria_vivienda: CategoriaVivienda = CategoriaVivienda.DOS_D
    categoria_hotelero: str = "hotel_3"             # placeholder hasta MVP hotel
    categoria_apartamentos: CategoriaApartamentos = CategoriaApartamentos.DOS_LLAVES
    tipologia_apartamento: TipologiaApartamento = TipologiaApartamento.UNO_D
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
        from .dominio import CATEGORIA_A_NUM_DORMS, TIPOLOGIA_APT_A_NUM_DORMS

        if self.programa.uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            n_dorms = TIPOLOGIA_APT_A_NUM_DORMS.get(self.programa.tipologia_apartamento, 1)
            categoria_label = self.programa.categoria_apartamentos.value
        else:
            n_dorms = CATEGORIA_A_NUM_DORMS.get(self.programa.categoria_vivienda, 2)
            categoria_label = self.programa.categoria_vivienda.value

        # Sanitiza porcentajes 0..100; suma se valida en el motor.
        pct_muros = max(0.0, min(80.0, float(self.diseno.pct_muros)))
        pct_circulacion = max(0.0, min(50.0, float(self.diseno.pct_circulacion)))
        pct_nucleo = max(0.0, min(30.0, float(self.diseno.pct_nucleo)))

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
                pct_muros=pct_muros,
                pct_circulacion=pct_circulacion,
                pct_nucleo=pct_nucleo,
            ),
            urbanismo=UrbMotor(
                coeficiente_edificabilidad=self.urbanisticos.coeficiente_edificabilidad,
                usar_coeficiente_edificabilidad=self.urbanisticos.usar_coeficiente_edificabilidad,
                ocupacion_maxima=max(0.0, min(1.0, self.urbanisticos.ocupacion_maxima_pct / 100.0)),
                n_plantas_max=self.urbanisticos.n_plantas_max,
                retranqueo_fachada=self.urbanisticos.retranqueo_fachada_m,
                retranqueo_linderos=self.urbanisticos.retranqueo_linderos_m,
                tiene_atico=self.urbanisticos.tiene_atico,
                retranqueo_atico=self.urbanisticos.retranqueo_atico_m,
                atico_computa_edificabilidad=self.urbanisticos.atico_computa_edificabilidad,
                tiene_sotano=self.urbanisticos.tiene_sotano,
                sotano_computa_edificabilidad=self.urbanisticos.sotano_computa_edificabilidad,
            ),
            programa=ProgramaMotor(
                uso=self.programa.uso.value,
                categoria=categoria_label,
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
            "coeficiente_edificabilidad": p.urbanisticos.coeficiente_edificabilidad,
            "usar_coeficiente_edificabilidad": p.urbanisticos.usar_coeficiente_edificabilidad,
            "ocupacion_maxima_pct": p.urbanisticos.ocupacion_maxima_pct,
            "n_plantas_max": p.urbanisticos.n_plantas_max,
            "retranqueo_fachada_m": p.urbanisticos.retranqueo_fachada_m,
            "retranqueo_linderos_m": p.urbanisticos.retranqueo_linderos_m,
            "usos_permitidos": list(p.urbanisticos.usos_permitidos),
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
            "pct_muros": p.diseno.pct_muros,
            "pct_circulacion": p.diseno.pct_circulacion,
            "pct_nucleo": p.diseno.pct_nucleo,
        },
        "programa": {
            "uso": p.programa.uso.value,
            "categoria_vivienda": p.programa.categoria_vivienda.value,
            "categoria_hotelero": p.programa.categoria_hotelero,
            "categoria_apartamentos": p.programa.categoria_apartamentos.value,
            "tipologia_apartamento": p.programa.tipologia_apartamento.value,
            "salon_cocina_open": p.programa.salon_cocina_open,
            "n_viviendas_por_planta_objetivo": p.programa.n_viviendas_por_planta_objetivo,
            "pct_unidades_adaptadas": p.programa.pct_unidades_adaptadas,
        },
        "seed": p.seed,
    }


def parametros_desde_dict(d: dict[str, Any] | None) -> ParametrosRender:
    """Parser tolerante: campos faltantes / inválidos caen a los defaults.

    Compatibilidad iter. 4 con JSON antiguos:
    - `edificabilidad_m2t_m2s` → `coeficiente_edificabilidad`
    - retranqueos frontal/lateral/trasero → linderos = max de los tres
    - claves obsoletas (`eficiencia_planta`, `altura_planta_m`) → ignoradas
    """
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

    # Compat con JSON antiguo: edificabilidad_m2t_m2s → coeficiente_edificabilidad
    coef = _f(urb_in, "coeficiente_edificabilidad",
              _f(urb_in, "edificabilidad_m2t_m2s", base.urbanisticos.coeficiente_edificabilidad))

    # Compat retranqueos: si vienen los 3 viejos, linderos = max
    if "retranqueo_fachada_m" in urb_in or "retranqueo_linderos_m" in urb_in:
        retr_fachada = _f(urb_in, "retranqueo_fachada_m", base.urbanisticos.retranqueo_fachada_m)
        retr_linderos = _f(urb_in, "retranqueo_linderos_m", base.urbanisticos.retranqueo_linderos_m)
    else:
        r_old = max(
            _f(urb_in, "retranqueo_frontal_m", 0.0),
            _f(urb_in, "retranqueo_lateral_m", 0.0),
            _f(urb_in, "retranqueo_trasero_m", 0.0),
        )
        retr_fachada = 0.0
        retr_linderos = r_old

    usos_raw = urb_in.get("usos_permitidos") or list(base.urbanisticos.usos_permitidos)
    usos_validos = [str(v) for v in usos_raw if isinstance(v, str) and v in USOS_PGOU_VALIDOS]
    if not usos_validos:
        usos_validos = list(base.urbanisticos.usos_permitidos)

    urb = ParametrosUrbanisticos(
        coeficiente_edificabilidad=coef,
        usar_coeficiente_edificabilidad=_b(urb_in, "usar_coeficiente_edificabilidad", base.urbanisticos.usar_coeficiente_edificabilidad),
        ocupacion_maxima_pct=_f(urb_in, "ocupacion_maxima_pct", base.urbanisticos.ocupacion_maxima_pct),
        n_plantas_max=_i(urb_in, "n_plantas_max", base.urbanisticos.n_plantas_max),
        retranqueo_fachada_m=retr_fachada,
        retranqueo_linderos_m=retr_linderos,
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
    pct_muros = max(0.0, min(80.0, _f(dis_in, "pct_muros", base.diseno.pct_muros)))
    pct_circulacion = max(0.0, min(50.0, _f(dis_in, "pct_circulacion", base.diseno.pct_circulacion)))
    pct_nucleo = max(0.0, min(30.0, _f(dis_in, "pct_nucleo", base.diseno.pct_nucleo)))
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
        pct_muros=pct_muros,
        pct_circulacion=pct_circulacion,
        pct_nucleo=pct_nucleo,
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

    try:
        cat_apt = CategoriaApartamentos(prog_in.get("categoria_apartamentos", base.programa.categoria_apartamentos.value))
    except (ValueError, TypeError):
        cat_apt = base.programa.categoria_apartamentos
    try:
        tip_apt = TipologiaApartamento(prog_in.get("tipologia_apartamento", base.programa.tipologia_apartamento.value))
    except (ValueError, TypeError):
        tip_apt = base.programa.tipologia_apartamento

    programa = ParametrosPrograma(
        uso=uso,
        categoria_vivienda=cat,
        categoria_hotelero=str(prog_in.get("categoria_hotelero", base.programa.categoria_hotelero)),
        categoria_apartamentos=cat_apt,
        tipologia_apartamento=tip_apt,
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
