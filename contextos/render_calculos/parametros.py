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
    CategoriaHotelApartamento,
    CategoriaHotelero,
    CategoriaVivienda,
    GrupoApartamentos,
    TipologiaApartamento,
    TipologiaHabitacion,
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
    """Valores de referencia de la normativa municipal.

    Semántica de las comparaciones que hace `ValidarCumplimiento`:
    - SUPERIOR: si el valor del proyecto > el de la normativa → incumplimiento.
    - INFERIOR: si el valor del proyecto < el de la normativa → aviso.
    - FIJO: si el valor del proyecto ≠ al de la normativa → aviso.
    """
    # ── límites SUPERIORES ──
    coeficiente_edificabilidad: float = 2.5
    usar_coeficiente_edificabilidad: bool = True
    ocupacion_maxima_pct: float = 100.0     # 0..100
    n_plantas_max: int = 3
    retranqueo_fachada_m: float = 0.0       # SUPERIOR
    retranqueo_linderos_m: float = 0.0      # SUPERIOR
    luz_recta_patio_min_m: float = 3.0      # SUPERIOR (nombre legacy)
    diametro_max_vestibulo_m: float = 1.50  # SUPERIOR
    espesor_muro_medianero_max_m: float = 0.25      # SUPERIOR
    espesor_separacion_unidades_max_m: float = 0.20  # SUPERIOR
    pct_muros_normativo: float = 20.0       # SUPERIOR (referencia normativa de muros)

    # ── límite FIJO ──
    retranqueo_atico_m: float = 3.0         # FIJO

    # ── límites INFERIORES ──
    area_patio_min_m2: float = 12.0                 # INFERIOR
    pct_unidades_adaptadas_min: float = 5.0         # INFERIOR
    ancho_min_fachada_m: float = 5.0                # INFERIOR (sobre la parcela)
    espesor_tabique_min_m: float = 0.10             # INFERIOR
    ancho_min_pasillo_comun_m: float = 1.20         # INFERIOR
    ancho_min_pasillo_vivienda_m: float = 1.00      # INFERIOR
    ancho_min_puerta_m: float = 0.80                # INFERIOR

    # ── informativos / no comparados ──
    usos_permitidos: list[str] = field(default_factory=lambda: [
        "residencial", "hotelero", "mixto",
    ])
    tiene_atico: bool = False
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
    ancho_min_pasillo_vivienda_m: float = 1.00
    diametro_min_vestibulo_m: float = 1.50
    ancho_min_puerta_m: float = 0.80
    pct_muros: float = 20.0
    pct_circulacion_pb: float = 8.0     # % circulación en planta baja
    pct_circulacion_tipo: float = 8.0   # % circulación en plantas tipo / ático
    pct_nucleo: float = 5.0


@dataclass
class ParametrosPrograma:
    """§2.5 — uso destino + categoría + accesibilidad."""
    uso: UsoEdificio = UsoEdificio.VIVIENDA
    categoria_vivienda: CategoriaVivienda = CategoriaVivienda.DOS_D
    categoria_hotelero: CategoriaHotelero = CategoriaHotelero.HOTEL_3          # Anexo I.1
    tipologia_habitacion: TipologiaHabitacion = TipologiaHabitacion.DOBLE      # Anexo I.1
    categoria_apartamentos: CategoriaApartamentos = CategoriaApartamentos.DOS_LLAVES
    tipologia_apartamento: TipologiaApartamento = TipologiaApartamento.DOBLE
    categoria_hotel_apartamento: CategoriaHotelApartamento = CategoriaHotelApartamento.TRES_E  # Anexo I.2
    grupo_apartamentos: GrupoApartamentos = GrupoApartamentos.EDIFICIOS        # A1.3 vs A1.4
    salon_cocina_open: bool = False
    # Tipologías adicionales para la mezcla multi-tipología. Los slugs válidos
    # dependen del uso activo (vivienda: estudio/1d/2d/3d/4d+; apartamentos y
    # hotel-apartamento: estudio/1d/2d/3d; hotelero: individual/doble/triple/
    # cuadruple/multiple).
    tipologias_extra: list[str] = field(default_factory=list)
    pct_local_pb: float = 0.0                       # % útil PB destinado a local no residencial
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
        from .dominio import (
            CATEGORIA_A_NUM_DORMS,
            TIPOLOGIA_APT_A_NUM_DORMS,
            TIPOLOGIA_HABITACION_A_PLAZAS,
            TIPOLOGIA_HAP_A_NUM_DORMS,
        )

        uso = self.programa.uso
        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            n_dorms = TIPOLOGIA_APT_A_NUM_DORMS.get(self.programa.tipologia_apartamento, 1)
            categoria_label = self.programa.categoria_apartamentos.value
        elif uso == UsoEdificio.HOTEL_APARTAMENTO:
            n_dorms = TIPOLOGIA_HAP_A_NUM_DORMS.get(self.programa.tipologia_apartamento, 1)
            categoria_label = self.programa.categoria_hotel_apartamento.value
        elif uso == UsoEdificio.HOTELERO:
            # "n_dorms" para hotelero es solo etiqueta (plazas de la habitación);
            # el reparto real usa el útil objetivo inyectado por casos_uso.
            n_dorms = TIPOLOGIA_HABITACION_A_PLAZAS.get(self.programa.tipologia_habitacion, 2)
            categoria_label = self.programa.categoria_hotelero.value
        else:  # VIVIENDA
            n_dorms = CATEGORIA_A_NUM_DORMS.get(self.programa.categoria_vivienda, 2)
            categoria_label = self.programa.categoria_vivienda.value

        # Sanitiza porcentajes 0..100; suma se valida en el motor.
        pct_muros = max(0.0, min(80.0, float(self.diseno.pct_muros)))
        pct_circulacion_pb = max(0.0, min(50.0, float(self.diseno.pct_circulacion_pb)))
        pct_circulacion_tipo = max(0.0, min(50.0, float(self.diseno.pct_circulacion_tipo)))
        pct_nucleo = max(0.0, min(30.0, float(self.diseno.pct_nucleo)))

        # La vía int-based de `tipologias_extra` solo la consume el preview de
        # vivienda. Para el resto de usos la mezcla la resuelve `casos_uso`
        # construyendo descriptores, así que aquí se pasa lista vacía.
        tipologias_extra_n: list[int] = []
        if uso == UsoEdificio.VIVIENDA:
            for slug in self.programa.tipologias_extra:
                if slug == "estudio":
                    tipologias_extra_n.append(0)
                elif slug == "4d+":
                    tipologias_extra_n.append(4)
                else:
                    try:
                        cat = CategoriaVivienda(slug)
                        tipologias_extra_n.append(CATEGORIA_A_NUM_DORMS.get(cat, 1))
                    except ValueError:
                        pass

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
                pct_muros=pct_muros,
                pct_circulacion_pb=pct_circulacion_pb,
                pct_circulacion_tipo=pct_circulacion_tipo,
                pct_nucleo=pct_nucleo,
                pct_muros_normativo=max(0.0, min(80.0, float(self.urbanisticos.pct_muros_normativo))),
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
                pct_unidades_adaptadas=self.programa.pct_unidades_adaptadas,
                tipologias_extra=tipologias_extra_n,
                pct_local_pb=max(0.0, min(100.0, float(self.programa.pct_local_pb))),
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
            "diametro_max_vestibulo_m": p.urbanisticos.diametro_max_vestibulo_m,
            "espesor_muro_medianero_max_m": p.urbanisticos.espesor_muro_medianero_max_m,
            "espesor_separacion_unidades_max_m": p.urbanisticos.espesor_separacion_unidades_max_m,
            "pct_unidades_adaptadas_min": p.urbanisticos.pct_unidades_adaptadas_min,
            "ancho_min_fachada_m": p.urbanisticos.ancho_min_fachada_m,
            "espesor_tabique_min_m": p.urbanisticos.espesor_tabique_min_m,
            "ancho_min_pasillo_comun_m": p.urbanisticos.ancho_min_pasillo_comun_m,
            "ancho_min_pasillo_vivienda_m": p.urbanisticos.ancho_min_pasillo_vivienda_m,
            "ancho_min_puerta_m": p.urbanisticos.ancho_min_puerta_m,
            "pct_muros_normativo": p.urbanisticos.pct_muros_normativo,
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
            "pct_muros": p.diseno.pct_muros,
            "pct_circulacion_pb": p.diseno.pct_circulacion_pb,
            "pct_circulacion_tipo": p.diseno.pct_circulacion_tipo,
            "pct_nucleo": p.diseno.pct_nucleo,
        },
        "programa": {
            "uso": p.programa.uso.value,
            "categoria_vivienda": p.programa.categoria_vivienda.value,
            "categoria_hotelero": p.programa.categoria_hotelero.value,
            "tipologia_habitacion": p.programa.tipologia_habitacion.value,
            "categoria_apartamentos": p.programa.categoria_apartamentos.value,
            "tipologia_apartamento": p.programa.tipologia_apartamento.value,
            "categoria_hotel_apartamento": p.programa.categoria_hotel_apartamento.value,
            "grupo_apartamentos": p.programa.grupo_apartamentos.value,
            "salon_cocina_open": p.programa.salon_cocina_open,
            "tipologias_extra": list(p.programa.tipologias_extra),
            "pct_local_pb": p.programa.pct_local_pb,
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
        diametro_max_vestibulo_m=_f(urb_in, "diametro_max_vestibulo_m", base.urbanisticos.diametro_max_vestibulo_m),
        espesor_muro_medianero_max_m=_f(urb_in, "espesor_muro_medianero_max_m", base.urbanisticos.espesor_muro_medianero_max_m),
        espesor_separacion_unidades_max_m=_f(urb_in, "espesor_separacion_unidades_max_m", base.urbanisticos.espesor_separacion_unidades_max_m),
        pct_unidades_adaptadas_min=_f(urb_in, "pct_unidades_adaptadas_min", base.urbanisticos.pct_unidades_adaptadas_min),
        ancho_min_fachada_m=_f(urb_in, "ancho_min_fachada_m", base.urbanisticos.ancho_min_fachada_m),
        espesor_tabique_min_m=_f(urb_in, "espesor_tabique_min_m", base.urbanisticos.espesor_tabique_min_m),
        ancho_min_pasillo_comun_m=_f(urb_in, "ancho_min_pasillo_comun_m", base.urbanisticos.ancho_min_pasillo_comun_m),
        ancho_min_pasillo_vivienda_m=_f(urb_in, "ancho_min_pasillo_vivienda_m", base.urbanisticos.ancho_min_pasillo_vivienda_m),
        ancho_min_puerta_m=_f(urb_in, "ancho_min_puerta_m", base.urbanisticos.ancho_min_puerta_m),
        pct_muros_normativo=_f(urb_in, "pct_muros_normativo", base.urbanisticos.pct_muros_normativo),
        tiene_atico=_b(urb_in, "tiene_atico", base.urbanisticos.tiene_atico),
        retranqueo_atico_m=_f(urb_in, "retranqueo_atico_m", base.urbanisticos.retranqueo_atico_m),
        atico_computa_edificabilidad=_b(urb_in, "atico_computa_edificabilidad", base.urbanisticos.atico_computa_edificabilidad),
        tiene_sotano=_b(urb_in, "tiene_sotano", base.urbanisticos.tiene_sotano),
        sotano_computa_edificabilidad=_b(urb_in, "sotano_computa_edificabilidad", base.urbanisticos.sotano_computa_edificabilidad),
    )

    dis_in = d.get("diseno") or {}
    pct_muros = max(0.0, min(80.0, _f(dis_in, "pct_muros", base.diseno.pct_muros)))
    # Compat con JSON antiguo: `pct_circulacion` único → se usa como tipo y PB.
    pct_circ_legacy = _f(dis_in, "pct_circulacion", base.diseno.pct_circulacion_tipo)
    pct_circulacion_pb = max(0.0, min(50.0,
        _f(dis_in, "pct_circulacion_pb", pct_circ_legacy)))
    pct_circulacion_tipo = max(0.0, min(50.0,
        _f(dis_in, "pct_circulacion_tipo", pct_circ_legacy)))
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
        pct_muros=pct_muros,
        pct_circulacion_pb=pct_circulacion_pb,
        pct_circulacion_tipo=pct_circulacion_tipo,
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

    try:
        cat_apt = CategoriaApartamentos(prog_in.get("categoria_apartamentos", base.programa.categoria_apartamentos.value))
    except (ValueError, TypeError):
        cat_apt = base.programa.categoria_apartamentos
    try:
        tip_apt = TipologiaApartamento(prog_in.get("tipologia_apartamento", base.programa.tipologia_apartamento.value))
    except (ValueError, TypeError):
        tip_apt = base.programa.tipologia_apartamento

    try:
        cat_hot = CategoriaHotelero(prog_in.get("categoria_hotelero", base.programa.categoria_hotelero.value))
    except (ValueError, TypeError):
        cat_hot = base.programa.categoria_hotelero
    try:
        tip_hab = TipologiaHabitacion(prog_in.get("tipologia_habitacion", base.programa.tipologia_habitacion.value))
    except (ValueError, TypeError):
        tip_hab = base.programa.tipologia_habitacion
    try:
        cat_hap = CategoriaHotelApartamento(prog_in.get("categoria_hotel_apartamento", base.programa.categoria_hotel_apartamento.value))
    except (ValueError, TypeError):
        cat_hap = base.programa.categoria_hotel_apartamento
    try:
        # Default tolerante "edificios": JSON antiguos sin el campo no cambian de resultado.
        grupo_apt = GrupoApartamentos(prog_in.get("grupo_apartamentos", base.programa.grupo_apartamentos.value))
    except (ValueError, TypeError):
        grupo_apt = base.programa.grupo_apartamentos

    # Los slugs válidos de la mezcla dependen del uso activo.
    if uso == UsoEdificio.HOTELERO:
        slugs_validos = {"individual", "doble", "triple", "cuadruple", "multiple"}
    elif uso in (UsoEdificio.APARTAMENTOS_TURISTICOS, UsoEdificio.HOTEL_APARTAMENTO):
        slugs_validos = {"estudio", "individual", "doble", "triple", "cuadruple"}
    else:  # VIVIENDA
        slugs_validos = {"estudio", "1d", "2d", "3d", "4d+"}
    tip_extra_raw = prog_in.get("tipologias_extra") or []
    tip_extra = [str(s) for s in tip_extra_raw if isinstance(s, str) and s in slugs_validos]

    programa = ParametrosPrograma(
        uso=uso,
        categoria_vivienda=cat,
        categoria_hotelero=cat_hot,
        tipologia_habitacion=tip_hab,
        categoria_apartamentos=cat_apt,
        tipologia_apartamento=tip_apt,
        categoria_hotel_apartamento=cat_hap,
        grupo_apartamentos=grupo_apt,
        salon_cocina_open=_b(prog_in, "salon_cocina_open", base.programa.salon_cocina_open),
        tipologias_extra=tip_extra,
        pct_local_pb=max(0.0, min(100.0, _f(prog_in, "pct_local_pb", base.programa.pct_local_pb))),
        pct_unidades_adaptadas=_f(prog_in, "pct_unidades_adaptadas", base.programa.pct_unidades_adaptadas),
    )

    return ParametrosRender(
        urbanisticos=urb,
        diseno=diseno,
        programa=programa,
        seed=_i(d, "seed", base.seed),
    )
