"""Combinador de tipologías de dormitorio — §2.5 (apartamentos turísticos).

§2.5 del PDF clasifica los apartamentos turísticos por **número de dormitorios**
(estudio, 1, 2, 3…), no por la ocupación de un único dormitorio. Cada dormitorio
se dimensiona por su ocupación (individual / doble / triple / cuádruple — las
filas de dormitorio del Anexo A1.3/A1.4). Dado un número de dormitorios N, este
módulo enumera **todas** las combinaciones posibles de ocupaciones (multiconjuntos
de tamaño N): son las "combinaciones totales" que el técnico podrá comparar.

Ejemplo (N=2, alfabeto {individual, doble, triple}):
    (ind,ind) · (ind,doble) · (ind,triple) · (doble,doble) · (doble,triple) ·
    (triple,triple)  → 6 combinaciones.

Módulo **puro**: no conoce m², ni el Anexo, ni la parcela. Solo trabaja con
etiquetas de tamaño (`str`) y recuentos. El dimensionado en m² (que depende del
Anexo) lo resuelve el sizer del uso (`programa_apartamentos`); cuántas unidades
caben lo resuelve el caso de uso reutilizando `calcular_capacidad`.

El **estudio es el caso N=0**: una única "combinación" sin dormitorios.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Mapping, Sequence

# Cota anti-explosión del enumerador por área (§ hotel): con varias tipologías el
# frontal de empaquetados maximales de una planta crece; se muestran las N de mayor
# capacidad y se informa del resto.
_COMB_MAX = 60


# Slug del estudio (N=0): combinación sin dormitorios.
SLUG_ESTUDIO = "estudio"

# Separadores del slug canónico de una combinación: "doble*1+individual*1".
_SEP_CUENTA = "*"
_SEP_UNION = "+"


@dataclass
class ComboDormitorios:
    """Una combinación de ocupaciones para los N dormitorios de una unidad.

    `composicion` mapea cada tamaño de dormitorio a su recuento, p. ej.
    `{"individual": 1, "doble": 1}` = 1 dormitorio individual + 1 doble. El
    estudio (N=0) es `composicion == {}`.

    Tras la construcción la composición queda **normalizada**: sin recuentos
    <= 0 y con claves en orden alfabético, de modo que dos combinaciones con la
    misma composición son iguales (`==`) y comparten `slug` con independencia del
    orden en que se construyeran.
    """
    composicion: Mapping[str, int]

    def __post_init__(self) -> None:
        limpio = {str(k): int(v) for k, v in self.composicion.items() if int(v) > 0}
        self.composicion = dict(sorted(limpio.items()))

    @property
    def n_dorms(self) -> int:
        return sum(self.composicion.values())

    @property
    def es_estudio(self) -> bool:
        return self.n_dorms == 0

    @property
    def slug(self) -> str:
        if not self.composicion:
            return SLUG_ESTUDIO
        return _SEP_UNION.join(
            f"{tam}{_SEP_CUENTA}{n}" for tam, n in self.composicion.items()
        )

    def plazas(self, plazas_por_tamano: Mapping[str, int]) -> int:
        """Σ plazas (ocupación) de los dormitorios según la tabla del uso."""
        return sum(int(plazas_por_tamano.get(t, 0)) * n for t, n in self.composicion.items())


def enumerar_combinaciones(
    n_dorms: int, tamanos: Sequence[str],
) -> list[ComboDormitorios]:
    """Todas las combinaciones (multiconjuntos) de `n_dorms` dormitorios.

    - `n_dorms == 0` → una sola combinación: el estudio (sin dormitorios).
    - `n_dorms >= 1` → combinaciones con repetición sobre `tamanos`.
    - `n_dorms < 0` o `tamanos` vacío (con N>=1) → `[]`.

    No ordena por m² (eso necesita el sizer y lo hace el caso de uso); la
    enumeración es determinista y preserva el orden de `tamanos`.
    """
    if n_dorms < 0:
        return []
    if n_dorms == 0:
        return [ComboDormitorios({})]
    if not tamanos:
        return []
    return [
        ComboDormitorios(dict(Counter(tupla)))
        for tupla in combinations_with_replacement(tamanos, n_dorms)
    ]


def combo_a_slug(combo: ComboDormitorios) -> str:
    """Slug canónico de la combinación (inverso de `slug_a_combo`)."""
    return combo.slug


def es_slug_combo(slug: str) -> bool:
    """True si el slug codifica una combinación multi-dormitorio (lleva '*').

    Permite a la serialización distinguir un slug-combinación (`"doble*1"`) de un
    slug de ocupación heredado (`"doble"`) o del estudio (`"estudio"`).
    """
    return _SEP_CUENTA in (slug or "")


def slug_a_combo(slug: str) -> ComboDormitorios:
    """Inverso de `combo_a_slug`. `"estudio"`/`""` → estudio (N=0).

    Tolerante: un token sin `*` (p. ej. un slug de ocupación heredado) cuenta
    como 1 dormitorio de ese tamaño, de modo que `slug_a_combo("doble")` da una
    combinación de un solo dormitorio doble.
    """
    s = (slug or "").strip()
    if not s or s == SLUG_ESTUDIO:
        return ComboDormitorios({})
    composicion: dict[str, int] = {}
    for token in s.split(_SEP_UNION):
        if not token:
            continue
        tam, sep, cnt = token.partition(_SEP_CUENTA)
        if sep:
            try:
                n = int(cnt)
            except ValueError:
                continue
            composicion[tam] = composicion.get(tam, 0) + n
        else:
            composicion[token] = composicion.get(token, 0) + 1
    return ComboDormitorios(composicion)


def enumerar_combinaciones_por_area(
    util_planta: float,
    tamanos_util: Mapping[str, float],
    cap: int = _COMB_MAX,
    requerir_todas: bool = False,
) -> tuple[list[ComboDormitorios], dict]:
    """Empaquetados MAXIMALES de una planta con unidades enteras (§ hotel).

    Dado el útil de UNA planta y el tamaño en m² de cada tipología de unidad, enumera
    todas las combinaciones (multiconjuntos de unidades **enteras**) `M` tales que
    `Σ ≤ util_planta` y `util_planta − Σ < min(tamaños)` (no cabe ni la unidad más
    pequeña). Es el problema per-planta del ejemplo del arquitecto:
    100 m², doble=50, individual=25 → {2 dobles, 1 doble+2 ind, 4 ind}.

    `requerir_todas=True`: solo se devuelven combinaciones que incluyan TODAS las
    tipologías pasadas (cada una ≥ 1). Criterio del arquitecto: si eligió individual +
    doble + triple, quiere solo mezclas con las tres presentes (si quisiera solo dos,
    elegiría dos). Si alguna tipología no cabe ni una vez, no hay ninguna combinación
    con todas → lista vacía (y el aviso lo señala con `no_caben_tipos`).

    Distinto de `enumerar_combinaciones`, que enumera multiconjuntos de tamaño **N
    fijo** de dormitorios DENTRO de una unidad; aquí el nº de unidades es variable y lo
    acota el área. Módulo puro: los m² por tipología los aporta el sizer del uso.

    Devuelve `(combinaciones, meta)`:
    - `combinaciones`: hasta `cap` `ComboDormitorios` (`composicion = {slug: count}`),
      ordenadas por nº de unidades asc y slug (el caso de uso reordena si procede).
    - `meta`: `{total, mostradas, no_mostradas, no_caben_tipos}` para el aviso «no caben».
    """
    util_planta = float(util_planta)
    tamanos = {str(k): float(v) for k, v in tamanos_util.items() if float(v) > 0}
    # Tipologías cuya unidad ni siquiera cabe una vez en la planta.
    no_caben_tipos = sorted(s for s, u in tamanos.items() if u > util_planta + 1e-6)
    caben = {s: u for s, u in tamanos.items() if u <= util_planta + 1e-6}
    vacio_meta = {"total": 0, "mostradas": 0, "no_mostradas": 0,
                  "no_caben_tipos": no_caben_tipos}
    if not caben or util_planta <= 0:
        return [], vacio_meta
    # Con «todas presentes», si alguna elegida no cabe es imposible incluirlas todas.
    if requerir_todas and no_caben_tipos:
        return [], vacio_meta

    # Tipologías ordenadas de mayor a menor útil (DFS determinista).
    orden = sorted(caben.items(), key=lambda kv: (-kv[1], kv[0]))
    slugs = [s for s, _ in orden]
    sizes = [u for _, u in orden]
    min_size = min(sizes)

    resultados: list[dict[str, int]] = []
    tope_coleccion = max(cap * 4, cap)   # margen para ordenar y cortar después
    nodos = [0]
    LIMITE_NODOS = 200_000

    def dfs(i: int, restante: float, actual: dict[str, int]) -> None:
        if len(resultados) >= tope_coleccion or nodos[0] > LIMITE_NODOS:
            return
        nodos[0] += 1
        if i >= len(slugs):
            # Maximal: no cabe ni la unidad más pequeña y hay al menos una unidad.
            # Con `requerir_todas`, además toda tipología debe estar presente (≥1).
            if actual and restante < min_size - 1e-9 and (
                not requerir_todas or len(actual) == len(slugs)
            ):
                resultados.append(dict(actual))
            return
        s, u = slugs[i], sizes[i]
        maxc = int((restante + 1e-9) // u)
        for c in range(maxc, -1, -1):
            if c > 0:
                actual[s] = c
            dfs(i + 1, restante - c * u, actual)
            if c > 0:
                actual.pop(s, None)

    dfs(0, util_planta, {})

    total = len(resultados)
    resultados.sort(key=lambda m: (sum(m.values()), sorted(m.items())))
    mostradas = resultados[:cap]
    combos = [ComboDormitorios(m) for m in mostradas]
    meta = {
        "total": total,
        "mostradas": len(combos),
        "no_mostradas": max(0, total - len(combos)),
        "no_caben_tipos": no_caben_tipos,
    }
    return combos, meta
