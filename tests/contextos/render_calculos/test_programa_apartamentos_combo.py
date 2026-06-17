"""Tests del sizer por COMBINACIÓN de dormitorios (§2.5 · paradigma nuevo).

Comprueban el dimensionado en m² de una `ComboDormitorios`: composición de
salón + N dormitorios + cocina + baño(s) según el Anexo A1.3 (edificios) /
A1.4 (conjuntos), el factor 1.15 del objetivo, el 2º baño en conjuntos y la
equivalencia con el sizer monodormitorio en los casos degenerados.
"""
from __future__ import annotations

from app.contextos.render_calculos.geometria.combinador_tipologias import (
    ComboDormitorios,
)
from app.contextos.render_calculos.geometria.programa_apartamentos import (
    MIN_BANO,
    MIN_COCINA,
    MIN_DORMITORIO,
    MIN_SALON_COMEDOR,
    SUP_ADICIONAL_PLAZA,
    descriptor_tipologia_combo,
    programa_apartamentos,
    programa_apartamentos_combo,
    util_minimo_apartamento,
    util_minimo_combo,
    util_objetivo_combo,
)


# ── Útil mínimo de la combinación ────────────────────────────────────────────
def test_util_minimo_combo_suma_piezas_del_anexo():
    # 1 individual + 1 doble en categoría 3L (grupo edificios). Plazas = 1+2 = 3
    # (< 4 → sin superficie adicional de salón).
    combo = ComboDormitorios({"individual": 1, "doble": 1})
    cat = "3L"
    esperado = (
        MIN_SALON_COMEDOR[cat]
        + MIN_DORMITORIO["individual"][cat]
        + MIN_DORMITORIO["doble"][cat]
        + MIN_COCINA[cat]
        + MIN_BANO[cat]
    )
    assert util_minimo_combo(combo, cat) == round(esperado, 2)


def test_util_minimo_combo_aplica_adicional_salon_desde_quinta_plaza():
    # 2 triples = 6 plazas → 2 plazas por encima de 4 → 2 × adicional.
    combo = ComboDormitorios({"triple": 2})
    cat = "4L"
    salon = MIN_SALON_COMEDOR[cat] + SUP_ADICIONAL_PLAZA[cat] * 2
    esperado = salon + 2 * MIN_DORMITORIO["triple"][cat] + MIN_COCINA[cat] + MIN_BANO[cat]
    assert util_minimo_combo(combo, cat) == round(esperado, 2)


def test_util_objetivo_combo_es_minimo_por_1_15():
    combo = ComboDormitorios({"doble": 2})
    assert util_objetivo_combo(combo, "2L") == round(util_minimo_combo(combo, "2L") * 1.15, 2)


def test_estudio_combo_equivale_al_sizer_monodormitorio():
    # El estudio es N=0: debe coincidir con la pieza "estudio" del Anexo.
    estudio = ComboDormitorios({})
    for cat in ("1L", "2L", "3L", "4L"):
        assert util_minimo_combo(estudio, cat) == util_minimo_apartamento(cat, "estudio")


def test_combo_de_un_solo_dormitorio_iguala_al_sizer_monodormitorio():
    # Una combinación con un único dormitorio doble == apartamento "doble" actual.
    combo = ComboDormitorios({"doble": 1})
    for cat in ("1L", "2L", "3L", "4L"):
        assert util_minimo_combo(combo, cat) == util_minimo_apartamento(cat, "doble")


# ── Programa de estancias ────────────────────────────────────────────────────
def test_programa_combo_genera_un_dormitorio_por_unidad_nombrado():
    combo = ComboDormitorios({"individual": 1, "doble": 1})
    estancias = programa_apartamentos_combo(combo, "3L", 0.0)
    nombres = [e.nombre for e in estancias]
    assert nombres == ["salon_comedor", "dormitorio_1", "dormitorio_2", "cocina", "bano"]


def test_programa_combo_tres_dormitorios():
    combo = ComboDormitorios({"individual": 1, "doble": 1, "triple": 1})
    estancias = programa_apartamentos_combo(combo, "4L", 0.0)
    dorms = [e for e in estancias if e.nombre.startswith("dormitorio_")]
    assert [e.nombre for e in dorms] == ["dormitorio_1", "dormitorio_2", "dormitorio_3"]


def test_programa_combo_a_util_cero_cae_a_minimos_y_suma_util_minimo():
    # Con util_disponible=0 cada estancia cae a su mínimo y la suma de mínimos
    # coincide con util_minimo_combo (invariante usado por el sizer base).
    combo = ComboDormitorios({"doble": 1, "triple": 1})
    cat = "2L"
    estancias = programa_apartamentos_combo(combo, cat, 0.0)
    suma_min = round(sum(e.area_min_m2 for e in estancias), 2)
    assert suma_min == util_minimo_combo(combo, cat)
    # A útil cero, target == mínimo en cada estancia.
    assert all(e.area_target_m2 == round(e.area_min_m2, 2) for e in estancias)


def test_programa_combo_escala_salon_y_dormitorios_no_cocina_ni_bano():
    combo = ComboDormitorios({"doble": 1})
    cat = "2L"
    minimo = util_minimo_combo(combo, cat)
    estancias = programa_apartamentos_combo(combo, cat, minimo * 2.0)
    por_nombre = {e.nombre: e for e in estancias}
    # Cocina y baño se mantienen en su mínimo (no escalan).
    assert por_nombre["cocina"].area_target_m2 == round(MIN_COCINA[cat], 2)
    assert por_nombre["bano"].area_target_m2 == round(MIN_BANO[cat], 2)
    # Salón y dormitorio crecen por encima de su mínimo.
    assert por_nombre["salon_comedor"].area_target_m2 > por_nombre["salon_comedor"].area_min_m2
    assert por_nombre["dormitorio_1"].area_target_m2 > por_nombre["dormitorio_1"].area_min_m2


def test_segundo_bano_en_conjuntos_si_mas_de_5_plazas():
    # 2 triples = 6 plazas > 5 → 2º baño obligatorio en conjuntos (A1.4).
    combo = ComboDormitorios({"triple": 2})
    estancias = programa_apartamentos_combo(combo, "2L", 0.0, grupo="conjuntos")
    nombres = [e.nombre for e in estancias]
    assert nombres.count("bano") == 1
    assert "aseo" in nombres


def test_sin_segundo_bano_en_edificios_aunque_supere_5_plazas():
    # En "edificios" (A1.3) no hay 2º baño por nº de usuarios.
    combo = ComboDormitorios({"triple": 2})
    estancias = programa_apartamentos_combo(combo, "4L", 0.0, grupo="edificios")
    assert "aseo" not in [e.nombre for e in estancias]


def _banos(estancias):
    return [e.nombre for e in estancias if e.nombre.startswith(("bano", "aseo"))]


def test_banos_segun_dormitorios_y_holgura():
    # §2.5: 1 dorm → 1 baño siempre; 2 dorm → 1 base / 2 si caben; 3 dorm →
    # 2 obligatorios / 3 si caben. "Caben" = los m² útiles dan para el extra.
    cat = "2L"
    for comp, n_min, n_max in [
        ({"doble": 1}, ["bano"], ["bano"]),                       # 1 dorm
        ({"doble": 2}, ["bano"], ["bano", "aseo"]),               # 2 dorm
        ({"doble": 3}, ["bano", "aseo"], ["bano", "aseo", "aseo_2"]),  # 3 dorm
    ]:
        combo = ComboDormitorios(comp)
        minimo = util_minimo_combo(combo, cat)
        # Ajustado al mínimo → opción reducida (baños obligatorios).
        assert _banos(programa_apartamentos_combo(combo, cat, minimo)) == n_min
        # Con holgura amplia → se añade el baño extra si la política lo permite.
        assert _banos(programa_apartamentos_combo(combo, cat, minimo * 2.0)) == n_max


def test_tres_dormitorios_garantiza_dos_banos_aunque_no_haya_holgura():
    # 3 dormitorios: 2 baños SÍ O SÍ, incluso ajustando al útil mínimo.
    combo = ComboDormitorios({"doble": 2, "individual": 1})
    estancias = programa_apartamentos_combo(combo, "2L", 0.0)
    assert _banos(estancias) == ["bano", "aseo"]


def test_estudio_combo_genera_mismas_estancias_que_estudio_monodormitorio():
    estudio = ComboDormitorios({})
    a = programa_apartamentos_combo(estudio, "3L", 100.0)
    b = programa_apartamentos("estudio", "3L", 100.0)
    assert [e.nombre for e in a] == [e.nombre for e in b]


# ── Descriptor ───────────────────────────────────────────────────────────────
def test_descriptor_combo_lleva_slug_canonico_y_plazas():
    combo = ComboDormitorios({"individual": 1, "doble": 1})
    d = descriptor_tipologia_combo(combo, "3L")
    assert d.slug == "doble*1+individual*1"
    assert d.tipo_unidad == "apartamento"
    assert d.n_dorms_label == 2
    assert d.plazas == 3  # 1 + 2
    assert d.util_objetivo == util_objetivo_combo(combo, "3L")
    assert d.util_maximo == round(d.util_objetivo * 1.25, 2)
