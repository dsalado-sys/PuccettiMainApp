"""Tests del combinador puro de tipologías de dormitorio (§2.5).

Solo lógica de enumeración / orden / codec de slug. Sin m², sin Anexo, sin
parcela (eso se prueba en el sizer y en el caso de uso).
"""
from __future__ import annotations

from app.contextos.render_calculos.geometria.combinador_tipologias import (
    ComboDormitorios,
    SLUG_ESTUDIO,
    combo_a_slug,
    enumerar_combinaciones,
    es_slug_combo,
    slug_a_combo,
)

# Alfabeto de ocupaciones de apartamento turístico (filas dormitorio A1.3/A1.4).
TAMANOS = ("individual", "doble", "triple", "cuadruple")


# ── Enumeración ──────────────────────────────────────────────────────────────
def test_enumerar_n2_cuatro_tamanos_da_diez_combos():
    # Combinaciones con repetición C(4+2-1, 2) = 10.
    combos = enumerar_combinaciones(2, TAMANOS)
    assert len(combos) == 10
    assert all(c.n_dorms == 2 for c in combos)
    # Sin duplicados (composición canónica).
    assert len({c.slug for c in combos}) == 10


def test_enumerar_n2_tres_tamanos_replica_ejemplo_del_prompt():
    combos = enumerar_combinaciones(2, ("individual", "doble", "triple"))
    slugs = {c.slug for c in combos}
    assert slugs == {
        "individual*2",
        "doble*1+individual*1",
        "individual*1+triple*1",
        "doble*2",
        "doble*1+triple*1",
        "triple*2",
    }


def test_enumerar_n1_da_un_combo_por_tamano():
    combos = enumerar_combinaciones(1, TAMANOS)
    assert len(combos) == 4
    assert {c.slug for c in combos} == {
        "individual*1", "doble*1", "triple*1", "cuadruple*1",
    }


def test_enumerar_n5_no_explota():
    # C(4+5-1, 5) = C(8,5) = 56 combinaciones (manejable).
    combos = enumerar_combinaciones(5, TAMANOS)
    assert len(combos) == 56
    assert all(c.n_dorms == 5 for c in combos)


def test_estudio_es_el_caso_n0():
    combos = enumerar_combinaciones(0, TAMANOS)
    assert len(combos) == 1
    estudio = combos[0]
    assert estudio.es_estudio
    assert estudio.n_dorms == 0
    assert estudio.composicion == {}
    assert estudio.slug == SLUG_ESTUDIO


def test_enumerar_negativo_o_sin_tamanos_da_vacio():
    assert enumerar_combinaciones(-1, TAMANOS) == []
    assert enumerar_combinaciones(2, ()) == []


# ── Normalización / igualdad ─────────────────────────────────────────────────
def test_composicion_se_normaliza_y_es_canonica():
    a = ComboDormitorios({"doble": 1, "individual": 1})
    b = ComboDormitorios({"individual": 1, "doble": 1})
    assert a == b                       # orden de construcción irrelevante
    assert a.slug == b.slug
    # Recuentos <= 0 se descartan.
    c = ComboDormitorios({"doble": 2, "triple": 0})
    assert c.composicion == {"doble": 2}


# ── Codec de slug (round-trip) ───────────────────────────────────────────────
def test_slug_round_trip_para_todas_las_combos_n3():
    for combo in enumerar_combinaciones(3, TAMANOS):
        assert slug_a_combo(combo_a_slug(combo)) == combo


def test_slug_round_trip_estudio():
    estudio = ComboDormitorios({})
    assert combo_a_slug(estudio) == SLUG_ESTUDIO
    assert slug_a_combo(SLUG_ESTUDIO) == estudio
    assert slug_a_combo("") == estudio


def test_es_slug_combo_distingue_combo_de_ocupacion_heredada():
    assert es_slug_combo("doble*1+individual*1")
    assert es_slug_combo("doble*2")
    assert not es_slug_combo("doble")        # slug de ocupación heredado
    assert not es_slug_combo(SLUG_ESTUDIO)   # estudio
    assert not es_slug_combo("")


def test_slug_a_combo_tolerante_con_ocupacion_heredada():
    # Un slug sin '*' cuenta como 1 dormitorio de ese tamaño.
    assert slug_a_combo("doble") == ComboDormitorios({"doble": 1})


# ── Plazas ───────────────────────────────────────────────────────────────────
def test_plazas_suma_ocupacion_segun_tabla_del_uso():
    plazas = {"individual": 1, "doble": 2, "triple": 3, "cuadruple": 4}
    assert ComboDormitorios({"individual": 1, "doble": 1}).plazas(plazas) == 3
    assert ComboDormitorios({"doble": 2}).plazas(plazas) == 4
    assert ComboDormitorios({"triple": 1, "cuadruple": 1}).plazas(plazas) == 7
    assert ComboDormitorios({}).plazas(plazas) == 0
