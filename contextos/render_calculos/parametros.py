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

import uuid
from dataclasses import dataclass, field
from typing import Any

from .dominio import (
    CategoriaApartamentos,
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
    PatioPlacement as PatioPlacementMotor,
)


USOS_PGOU_VALIDOS: tuple[str, ...] = ("residencial", "hotelero", "terciario", "mixto")


@dataclass
class PatioDef:
    """Definición de un patio del edificio (entrada del usuario / frontend).

    `area_m2` es el invariante sagrado: se preserva siempre (capacidad deduce su
    suma; la geometría se construye para tenerlo). `vertices` es el polígono libre
    en coordenadas UTM tal como lo editó el usuario en el lienzo (None = patio sin
    posición → el motor lo auto-coloca, comportamiento histórico). `id` da identidad
    estable para que el frontend siga cada patio entre recálculos y ediciones.
    """
    area_m2: float
    id: str = ""
    vertices: list | None = None
    bloqueado: bool = False   # patio congelado: el usuario no puede editarlo y el motor lo prioriza

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]


def area_de_patio(pd: Any) -> float:
    """Área asignada de un patio, tolerante a `PatioDef` o a un `float` legado."""
    if isinstance(pd, PatioDef):
        return max(0.0, float(pd.area_m2))
    try:
        return max(0.0, float(pd))
    except (TypeError, ValueError):
        return 0.0


def _parse_patio(item: Any) -> PatioDef | None:
    """Parsea una entrada de `patios` del JSON: número suelto (solo área) u objeto
    `{area_m2|area, id?, vertices?}`. Devuelve None si el área no es positiva."""
    if isinstance(item, bool):
        return None
    if isinstance(item, (int, float)):
        a = float(item)
        return PatioDef(area_m2=a) if a > 0 else None
    if isinstance(item, dict):
        try:
            a = float(item.get("area_m2", item.get("area", 0.0)))
        except (TypeError, ValueError):
            return None
        if a <= 0:
            return None
        verts: list | None = None
        raw = item.get("vertices")
        if isinstance(raw, (list, tuple)):
            pts: list[list[float]] = []
            for v in raw:
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    try:
                        pts.append([float(v[0]), float(v[1])])
                    except (TypeError, ValueError):
                        pts = []
                        break
            if len(pts) >= 3:
                verts = pts
        return PatioDef(
            area_m2=a,
            id=str(item.get("id") or ""),
            vertices=verts,
            bloqueado=bool(item.get("bloqueado", False)),
        )
    return None


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
    ocupacion_maxima_pct: float = 100.0      # 0..100 — ocupación de la PLANTA BAJA (y sótano)
    ocupacion_maxima_pct_tipo: float = 100.0  # 0..100 — ocupación de las PLANTAS TIPO (y ático)
    n_plantas_max: int = 3
    diametro_max_vestibulo_m: float = 1.50  # SUPERIOR
    espesor_muro_medianero_max_m: float = 0.25      # SUPERIOR
    espesor_separacion_unidades_max_m: float = 0.20  # SUPERIOR
    pct_muros_normativo: float = 20.0       # SUPERIOR (referencia normativa de muros)

    # ── límites INFERIORES ──
    retranqueo_fachada_m: float = 0.0       # INFERIOR (mínimo normativo)
    retranqueo_linderos_m: float = 0.0      # INFERIOR (mínimo normativo)
    retranqueo_atico_m: float = 3.0         # INFERIOR (mínimo normativo)
    luz_recta_patio_min_m: float = 3.0      # INFERIOR (nombre legacy)
    area_patio_min_m2: float = 12.0                 # INFERIOR
    # Patios reales del edificio: un `PatioDef` por patio (área asignada + polígono
    # libre opcional). Atraviesan todas las plantas (patinejos de luz); el cálculo
    # descuenta su SUMA de áreas en cada planta. `area_patio_min_m2`/`luz_recta_patio_min_m`
    # quedan solo como referencia normativa (validación de cumplimiento). Default = un
    # patio de 12 m² sin posición (auto-colocado = comportamiento histórico).
    patios: list[PatioDef] = field(default_factory=lambda: [PatioDef(area_m2=12.0)])
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
    # % muros INTERIORES de la unidad (tabiquería entre estancias). Resta de la
    # construida, junto con `pct_muros` (perímetro), para obtener la útil neta de la
    # unidad. Default 0 (opt-in): sin él, la útil solo descuenta el perímetro.
    pct_muros_interior: float = 0.0
    pct_circulacion_pb: float = 8.0     # % circulación en planta baja
    pct_circulacion_tipo: float = 8.0   # % circulación en plantas tipo / ático
    pct_nucleo: float = 5.0
    # % circulación INTERIOR de la unidad (pasillos+vestíbulo dentro de cada
    # vivienda/apartamento/habitación). Único, compartido por todos los usos;
    # solo se lee del bloque de PB (`diseno`). Sustituye el 1.15 antes fijo.
    pct_circulacion_interior: float = 15.0


@dataclass
class ParametrosPrograma:
    """§2.5 — uso destino + categoría + accesibilidad."""
    uso: UsoEdificio = UsoEdificio.VIVIENDA
    categoria_vivienda: CategoriaVivienda = CategoriaVivienda.DOS_D
    categoria_hotelero: CategoriaHotelero = CategoriaHotelero.HOTEL_3          # Anexo I.1
    tipologia_habitacion: TipologiaHabitacion = TipologiaHabitacion.DOBLE      # Anexo I.1
    categoria_apartamentos: CategoriaApartamentos = CategoriaApartamentos.DOS_LLAVES
    tipologia_apartamento: TipologiaApartamento = TipologiaApartamento.DOBLE
    grupo_apartamentos: GrupoApartamentos = GrupoApartamentos.EDIFICIOS        # A1.3 vs A1.4
    salon_cocina_open: bool = False
    # Tipologías adicionales para la mezcla multi-tipología. Los slugs válidos
    # dependen del uso activo (vivienda: estudio/1d/2d/3d/4d+; apartamentos:
    # estudio/1d/2d/3d; hotelero: individual/doble/triple/cuadruple/multiple).
    tipologias_extra: list[str] = field(default_factory=list)
    pct_local_pb: float = 0.0                       # % útil PB destinado a local no residencial
    pct_otros_pb: float = 0.0                       # % útil PB destinado a otros usos
    pct_usos_comunes_pb: float = 0.0                # % útil PB para usos comunes (AT / hoteles)


@dataclass
class ParametrosRender:
    """Bundle global del módulo Render y cálculos.

    Diferenciación por categoría de planta (iter. 6 — PB independiente):
    - `diseno`/`programa` describen la PLANTA BAJA (y los valores de edificio:
      urbanismo, uso destino, categoría, % local PB…).
    - `diseno_tipo`/`programa_tipo` describen las PLANTAS TIPO. `programa_tipo`
      solo difiere en la tipología (el uso y la categoría de edificio se heredan
      de `programa`).
    - `diseno_atico`/`diseno_sotano` aportan, de momento, su propio % muros y %
      circulación (el resto hereda de tipo/PB). El ático usa la tipología de las
      plantas tipo; el sótano no aloja unidades.
    """
    urbanisticos: ParametrosUrbanisticos = field(default_factory=ParametrosUrbanisticos)
    diseno: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    programa: ParametrosPrograma = field(default_factory=ParametrosPrograma)
    diseno_tipo: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    diseno_atico: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    diseno_sotano: ParametrosDiseno = field(default_factory=ParametrosDiseno)
    programa_tipo: ParametrosPrograma = field(default_factory=ParametrosPrograma)
    seed: int = 42

    def a_parametros_motor(self) -> ParametrosMotor:
        """Motor para la planta baja / valores de edificio."""
        return self._motor_desde(self.diseno, self.programa)

    def a_parametros_motor_tipo(self) -> ParametrosMotor:
        """Motor para las plantas tipo (y ático): tipología de `programa_tipo`."""
        return self._motor_desde(self.diseno_tipo, self.programa_tipo)

    def _motor_desde(self, diseno: ParametrosDiseno, programa: ParametrosPrograma) -> ParametrosMotor:
        """Traduce (diseño, programa) + urbanismo de edificio a la estructura del motor."""
        from .dominio import (
            CATEGORIA_A_NUM_DORMS,
            TIPOLOGIA_APT_A_NUM_DORMS,
            TIPOLOGIA_HABITACION_A_PLAZAS,
        )

        uso = programa.uso
        if uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            n_dorms = TIPOLOGIA_APT_A_NUM_DORMS.get(programa.tipologia_apartamento, 1)
            categoria_label = programa.categoria_apartamentos.value
        elif uso == UsoEdificio.HOTELERO:
            # "n_dorms" para hotelero es solo etiqueta (plazas de la habitación);
            # el reparto real usa el útil objetivo inyectado por casos_uso.
            n_dorms = TIPOLOGIA_HABITACION_A_PLAZAS.get(programa.tipologia_habitacion, 2)
            categoria_label = programa.categoria_hotelero.value
        else:  # VIVIENDA
            n_dorms = CATEGORIA_A_NUM_DORMS.get(programa.categoria_vivienda, 2)
            categoria_label = programa.categoria_vivienda.value

        # Sanitiza porcentajes 0..100; suma se valida en el motor.
        pct_muros = max(0.0, min(80.0, float(diseno.pct_muros)))
        pct_muros_interior = max(0.0, min(80.0, float(getattr(diseno, "pct_muros_interior", 0.0))))
        pct_circulacion_pb = max(0.0, min(50.0, float(diseno.pct_circulacion_pb)))
        pct_circulacion_tipo = max(0.0, min(50.0, float(diseno.pct_circulacion_tipo)))
        pct_nucleo = max(0.0, min(30.0, float(diseno.pct_nucleo)))

        # La vía int-based de `tipologias_extra` solo la consume el preview de
        # vivienda. Para el resto de usos la mezcla la resuelve `casos_uso`
        # construyendo descriptores, así que aquí se pasa lista vacía.
        tipologias_extra_n: list[int] = []
        if uso == UsoEdificio.VIVIENDA:
            for slug in programa.tipologias_extra:
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
                espesor_muro_fachada=diseno.espesor_muro_fachada_m,
                espesor_muro_medianero=diseno.espesor_muro_medianero_m,
                espesor_separacion_unidades=diseno.espesor_separacion_unidades_m,
                espesor_tabiqueria=diseno.espesor_tabique_m,
                ancho_min_pasillo_comun=diseno.ancho_min_pasillo_comun_m,
                ancho_min_pasillo_vivienda=diseno.ancho_min_pasillo_vivienda_m,
                diametro_min_vestibulo=diseno.diametro_min_vestibulo_m,
                radio_apertura_puerta=diseno.ancho_min_puerta_m,
                luz_recta_patio_min=self.urbanisticos.luz_recta_patio_min_m,
                # El motor descuenta la SUMA de los patios definidos por planta;
                # el mínimo normativo (`area_patio_min_m2`) queda solo como
                # referencia para la validación de cumplimiento.
                area_patio_min=sum(area_de_patio(pd) for pd in self.urbanisticos.patios),
                pct_muros=pct_muros,
                pct_muros_interior=pct_muros_interior,
                pct_circulacion_pb=pct_circulacion_pb,
                pct_circulacion_tipo=pct_circulacion_tipo,
                pct_nucleo=pct_nucleo,
                pct_muros_normativo=max(0.0, min(80.0, float(self.urbanisticos.pct_muros_normativo))),
            ),
            urbanismo=UrbMotor(
                coeficiente_edificabilidad=self.urbanisticos.coeficiente_edificabilidad,
                usar_coeficiente_edificabilidad=self.urbanisticos.usar_coeficiente_edificabilidad,
                ocupacion_maxima=max(0.0, min(1.0, self.urbanisticos.ocupacion_maxima_pct / 100.0)),
                ocupacion_maxima_tipo=max(0.0, min(1.0, self.urbanisticos.ocupacion_maxima_pct_tipo / 100.0)),
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
                uso=programa.uso.value,
                categoria=categoria_label,
                n_dormitorios=n_dorms,
                salon_cocina_open=programa.salon_cocina_open,
                n_plantas=self.urbanisticos.n_plantas_max,
                tipologias_extra=tipologias_extra_n,
                pct_local_pb=max(0.0, min(100.0, float(programa.pct_local_pb))),
                pct_otros_pb=max(0.0, min(100.0, float(programa.pct_otros_pb))),
                pct_usos_comunes_pb=max(0.0, min(100.0, float(programa.pct_usos_comunes_pb))),
            ),
            # Colocación individual de cada patio (polígono libre opcional). El motor
            # los dibuja uno a uno y los resta del interior; capacidad sigue usando solo
            # la SUMA de áreas (`area_patio_min`), así los números no se mueven.
            patios=[
                PatioPlacementMotor(
                    area_m2=area_de_patio(pd),
                    id=(pd.id if isinstance(pd, PatioDef) else ""),
                    vertices=(pd.vertices if isinstance(pd, PatioDef) else None),
                    bloqueado=(pd.bloqueado if isinstance(pd, PatioDef) else False),
                )
                for pd in self.urbanisticos.patios
                if area_de_patio(pd) > 0
            ],
            seed=self.seed,
        )


# ─── Serialización JSON ─────────────────────────────────────────────────────
def _patio_def_a_dict(pd: Any) -> dict[str, Any]:
    """Serializa un patio para el frontend / persistencia. Emite siempre `id` +
    `area_m2`, y `vertices` (polígono libre UTM) cuando los hay. Tolera floats legados."""
    if isinstance(pd, PatioDef):
        out: dict[str, Any] = {"id": pd.id or "", "area_m2": float(pd.area_m2)}
        if pd.vertices:
            out["vertices"] = [[float(x), float(y)] for x, y in pd.vertices]
        if pd.bloqueado:
            out["bloqueado"] = True
        return out
    return {"id": "", "area_m2": float(pd)}


def _diseno_a_dict(d: ParametrosDiseno) -> dict[str, Any]:
    return {
        "espesor_muro_fachada_m": d.espesor_muro_fachada_m,
        "espesor_muro_medianero_m": d.espesor_muro_medianero_m,
        "espesor_separacion_unidades_m": d.espesor_separacion_unidades_m,
        "espesor_tabique_m": d.espesor_tabique_m,
        "ancho_min_pasillo_comun_m": d.ancho_min_pasillo_comun_m,
        "ancho_min_pasillo_vivienda_m": d.ancho_min_pasillo_vivienda_m,
        "diametro_min_vestibulo_m": d.diametro_min_vestibulo_m,
        "ancho_min_puerta_m": d.ancho_min_puerta_m,
        "pct_muros": d.pct_muros,
        "pct_muros_interior": d.pct_muros_interior,
        "pct_circulacion_pb": d.pct_circulacion_pb,
        "pct_circulacion_tipo": d.pct_circulacion_tipo,
        "pct_nucleo": d.pct_nucleo,
        "pct_circulacion_interior": d.pct_circulacion_interior,
    }


def _programa_a_dict(prog: ParametrosPrograma) -> dict[str, Any]:
    return {
        "uso": prog.uso.value,
        "categoria_vivienda": prog.categoria_vivienda.value,
        "categoria_hotelero": prog.categoria_hotelero.value,
        "tipologia_habitacion": prog.tipologia_habitacion.value,
        "categoria_apartamentos": prog.categoria_apartamentos.value,
        "tipologia_apartamento": prog.tipologia_apartamento.value,
        "grupo_apartamentos": prog.grupo_apartamentos.value,
        "salon_cocina_open": prog.salon_cocina_open,
        "tipologias_extra": list(prog.tipologias_extra),
        "pct_local_pb": prog.pct_local_pb,
        "pct_otros_pb": prog.pct_otros_pb,
        "pct_usos_comunes_pb": prog.pct_usos_comunes_pb,
    }


def parametros_a_dict(p: ParametrosRender) -> dict[str, Any]:
    return {
        "urbanisticos": {
            "coeficiente_edificabilidad": p.urbanisticos.coeficiente_edificabilidad,
            "usar_coeficiente_edificabilidad": p.urbanisticos.usar_coeficiente_edificabilidad,
            "ocupacion_maxima_pct": p.urbanisticos.ocupacion_maxima_pct,
            "ocupacion_maxima_pct_tipo": p.urbanisticos.ocupacion_maxima_pct_tipo,
            "n_plantas_max": p.urbanisticos.n_plantas_max,
            "retranqueo_fachada_m": p.urbanisticos.retranqueo_fachada_m,
            "retranqueo_linderos_m": p.urbanisticos.retranqueo_linderos_m,
            "usos_permitidos": list(p.urbanisticos.usos_permitidos),
            "luz_recta_patio_min_m": p.urbanisticos.luz_recta_patio_min_m,
            "area_patio_min_m2": p.urbanisticos.area_patio_min_m2,
            "patios": [_patio_def_a_dict(pd) for pd in p.urbanisticos.patios],
            "diametro_max_vestibulo_m": p.urbanisticos.diametro_max_vestibulo_m,
            "espesor_muro_medianero_max_m": p.urbanisticos.espesor_muro_medianero_max_m,
            "espesor_separacion_unidades_max_m": p.urbanisticos.espesor_separacion_unidades_max_m,
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
        "diseno": _diseno_a_dict(p.diseno),
        "diseno_tipo": _diseno_a_dict(p.diseno_tipo),
        "diseno_atico": _diseno_a_dict(p.diseno_atico),
        "diseno_sotano": _diseno_a_dict(p.diseno_sotano),
        "programa": _programa_a_dict(p.programa),
        "programa_tipo": _programa_a_dict(p.programa_tipo),
        "seed": p.seed,
    }


# Cota dura de plantas: el motor recorre `range(n_plantas)` construyendo geometría
# con Shapely, así que un POST con un valor enorme colgaría el worker (DoS). 60
# plantas cubre cualquier edificio real con margen.
N_PLANTAS_LIMITE = 60


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

    def _parse_diseno(node: dict[str, Any] | None, base_d: ParametrosDiseno) -> ParametrosDiseno:
        """Parsea un bloque de diseño; cada campo ausente HEREDA de `base_d`.

        Permite que `diseno_tipo`/`diseno_atico`/`diseno_sotano` lleguen parciales
        (p. ej. solo % muros + % circulación) y completen el resto desde su padre.
        """
        node = node or {}

        def _circ(field: str, base_val: float) -> float:
            # Compat JSON antiguo: `pct_circulacion` único alimenta pb y tipo.
            if "pct_circulacion" in node and field not in node:
                return max(0.0, min(50.0, _f(node, "pct_circulacion", base_val)))
            return max(0.0, min(50.0, _f(node, field, base_val)))

        return ParametrosDiseno(
            espesor_muro_fachada_m=_f(node, "espesor_muro_fachada_m", base_d.espesor_muro_fachada_m),
            espesor_muro_medianero_m=_f(node, "espesor_muro_medianero_m", base_d.espesor_muro_medianero_m),
            espesor_separacion_unidades_m=_f(node, "espesor_separacion_unidades_m", base_d.espesor_separacion_unidades_m),
            espesor_tabique_m=_f(node, "espesor_tabique_m", base_d.espesor_tabique_m),
            ancho_min_pasillo_comun_m=_f(node, "ancho_min_pasillo_comun_m", base_d.ancho_min_pasillo_comun_m),
            ancho_min_pasillo_vivienda_m=_f(node, "ancho_min_pasillo_vivienda_m", base_d.ancho_min_pasillo_vivienda_m),
            diametro_min_vestibulo_m=_f(node, "diametro_min_vestibulo_m", base_d.diametro_min_vestibulo_m),
            ancho_min_puerta_m=_f(node, "ancho_min_puerta_m", base_d.ancho_min_puerta_m),
            pct_muros=max(0.0, min(80.0, _f(node, "pct_muros", base_d.pct_muros))),
            pct_muros_interior=max(0.0, min(80.0, _f(node, "pct_muros_interior", base_d.pct_muros_interior))),
            pct_circulacion_pb=_circ("pct_circulacion_pb", base_d.pct_circulacion_pb),
            pct_circulacion_tipo=_circ("pct_circulacion_tipo", base_d.pct_circulacion_tipo),
            pct_nucleo=max(0.0, min(30.0, _f(node, "pct_nucleo", base_d.pct_nucleo))),
            pct_circulacion_interior=max(0.0, min(40.0, _f(node, "pct_circulacion_interior", base_d.pct_circulacion_interior))),
        )

    def _parse_programa(node: dict[str, Any] | None, base_prog: ParametrosPrograma) -> ParametrosPrograma:
        """Parsea un bloque de programa; campos ausentes HEREDAN de `base_prog`."""
        node = node or {}

        def _enum(cls, clave, defecto):
            try:
                return cls(node.get(clave, defecto.value))
            except (ValueError, TypeError):
                return defecto

        uso = _enum(UsoEdificio, "uso", base_prog.uso)
        cat = _enum(CategoriaVivienda, "categoria_vivienda", base_prog.categoria_vivienda)
        cat_apt = _enum(CategoriaApartamentos, "categoria_apartamentos", base_prog.categoria_apartamentos)
        tip_apt = _enum(TipologiaApartamento, "tipologia_apartamento", base_prog.tipologia_apartamento)
        cat_hot = _enum(CategoriaHotelero, "categoria_hotelero", base_prog.categoria_hotelero)
        tip_hab = _enum(TipologiaHabitacion, "tipologia_habitacion", base_prog.tipologia_habitacion)
        # Default tolerante "edificios": JSON antiguos sin el campo no cambian de resultado.
        grupo_apt = _enum(GrupoApartamentos, "grupo_apartamentos", base_prog.grupo_apartamentos)

        # Los slugs válidos de la mezcla dependen del uso activo.
        if uso == UsoEdificio.HOTELERO:
            slugs_validos = {"individual", "doble", "triple", "cuadruple", "multiple"}
        elif uso == UsoEdificio.APARTAMENTOS_TURISTICOS:
            slugs_validos = {"estudio", "individual", "doble", "triple", "cuadruple"}
        else:  # VIVIENDA
            slugs_validos = {"estudio", "1d", "2d", "3d", "4d+"}
        tip_extra_raw = node.get("tipologias_extra")
        if tip_extra_raw is None:
            tip_extra = list(base_prog.tipologias_extra)
        else:
            tip_extra = [str(s) for s in tip_extra_raw if isinstance(s, str) and s in slugs_validos]

        return ParametrosPrograma(
            uso=uso,
            categoria_vivienda=cat,
            categoria_hotelero=cat_hot,
            tipologia_habitacion=tip_hab,
            categoria_apartamentos=cat_apt,
            tipologia_apartamento=tip_apt,
            grupo_apartamentos=grupo_apt,
            salon_cocina_open=_b(node, "salon_cocina_open", base_prog.salon_cocina_open),
            tipologias_extra=tip_extra,
            pct_local_pb=max(0.0, min(100.0, _f(node, "pct_local_pb", base_prog.pct_local_pb))),
            pct_otros_pb=max(0.0, min(100.0, _f(node, "pct_otros_pb", base_prog.pct_otros_pb))),
            pct_usos_comunes_pb=max(0.0, min(100.0, _f(node, "pct_usos_comunes_pb", base_prog.pct_usos_comunes_pb))),
        )

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

    # Ocupación máxima: PB y plantas tipo. Si el JSON no trae la clave de tipo,
    # HEREDA la de PB → un proyecto con una sola ocupación da la misma huella en
    # todas las plantas (comportamiento idéntico al histórico).
    ocup_pb = _f(urb_in, "ocupacion_maxima_pct", base.urbanisticos.ocupacion_maxima_pct)
    ocup_tipo = _f(urb_in, "ocupacion_maxima_pct_tipo", ocup_pb)

    usos_raw = urb_in.get("usos_permitidos") or list(base.urbanisticos.usos_permitidos)
    usos_validos = [str(v) for v in usos_raw if isinstance(v, str) and v in USOS_PGOU_VALIDOS]
    if not usos_validos:
        usos_validos = list(base.urbanisticos.usos_permitidos)

    # Patios reales del edificio. Cada entrada admite un número suelto (= solo área,
    # auto-colocado, formato histórico) o un objeto `{area_m2|area, id?, vertices?}`
    # (polígono libre editado en el lienzo). Si la clave está presente se respeta tal
    # cual (lista vacía = sin patios, intencional). JSON legado sin la clave → un patio
    # del área mínima normativa, preservando el patio único histórico.
    area_patio_min = _f(urb_in, "area_patio_min_m2", base.urbanisticos.area_patio_min_m2)
    if "patios" in urb_in:
        patios: list[PatioDef] = []
        for item in (urb_in.get("patios") or []):
            pd = _parse_patio(item)
            if pd is not None:
                patios.append(pd)
    else:
        patios = [PatioDef(area_m2=area_patio_min)] if area_patio_min > 0 else []

    urb = ParametrosUrbanisticos(
        coeficiente_edificabilidad=coef,
        usar_coeficiente_edificabilidad=_b(urb_in, "usar_coeficiente_edificabilidad", base.urbanisticos.usar_coeficiente_edificabilidad),
        ocupacion_maxima_pct=ocup_pb,
        ocupacion_maxima_pct_tipo=ocup_tipo,
        n_plantas_max=max(1, min(_i(urb_in, "n_plantas_max", base.urbanisticos.n_plantas_max), N_PLANTAS_LIMITE)),
        retranqueo_fachada_m=retr_fachada,
        retranqueo_linderos_m=retr_linderos,
        usos_permitidos=usos_validos,
        luz_recta_patio_min_m=_f(urb_in, "luz_recta_patio_min_m", base.urbanisticos.luz_recta_patio_min_m),
        area_patio_min_m2=area_patio_min,
        patios=patios,
        diametro_max_vestibulo_m=_f(urb_in, "diametro_max_vestibulo_m", base.urbanisticos.diametro_max_vestibulo_m),
        espesor_muro_medianero_max_m=_f(urb_in, "espesor_muro_medianero_max_m", base.urbanisticos.espesor_muro_medianero_max_m),
        espesor_separacion_unidades_max_m=_f(urb_in, "espesor_separacion_unidades_max_m", base.urbanisticos.espesor_separacion_unidades_max_m),
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

    # Diseño por categoría de planta. Cadena de herencia: tipo←pb, atico←tipo,
    # sotano←pb. Un JSON legado sin estos bloques deja todas las categorías = PB.
    diseno = _parse_diseno(d.get("diseno"), base.diseno)
    diseno_tipo = _parse_diseno(d.get("diseno_tipo"), diseno)
    diseno_atico = _parse_diseno(d.get("diseno_atico"), diseno_tipo)
    diseno_sotano = _parse_diseno(d.get("diseno_sotano"), diseno)

    programa = _parse_programa(d.get("programa"), base.programa)

    # `programa_tipo`: el uso y la categoría de edificio son globales (de PB);
    # solo se toma del bloque la TIPOLOGÍA (lo que el usuario edita por planta).
    prog_tipo_node = d.get("programa_tipo") or {}
    programa_tipo = _parse_programa(
        {
            "uso": programa.uso.value,
            "categoria_apartamentos": programa.categoria_apartamentos.value,
            "grupo_apartamentos": programa.grupo_apartamentos.value,
            "categoria_hotelero": programa.categoria_hotelero.value,
            "salon_cocina_open": programa.salon_cocina_open,
            "pct_local_pb": programa.pct_local_pb,
            "pct_otros_pb": programa.pct_otros_pb,
            "pct_usos_comunes_pb": programa.pct_usos_comunes_pb,
            "categoria_vivienda": prog_tipo_node.get("categoria_vivienda", programa.categoria_vivienda.value),
            "tipologia_apartamento": prog_tipo_node.get("tipologia_apartamento", programa.tipologia_apartamento.value),
            "tipologia_habitacion": prog_tipo_node.get("tipologia_habitacion", programa.tipologia_habitacion.value),
            "tipologias_extra": prog_tipo_node.get("tipologias_extra", list(programa.tipologias_extra)),
        },
        programa,
    )

    return ParametrosRender(
        urbanisticos=urb,
        diseno=diseno,
        programa=programa,
        diseno_tipo=diseno_tipo,
        diseno_atico=diseno_atico,
        diseno_sotano=diseno_sotano,
        programa_tipo=programa_tipo,
        seed=_i(d, "seed", base.seed),
    )
