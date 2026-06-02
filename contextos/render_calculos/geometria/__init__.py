"""Motor geométrico paramétrico — vivienda plurifamiliar (§2.4/§2.5).

Copia adaptada del paquete `Modulos/puccetti-app/puccetti/`. Cambios respecto
al original:

- `config.py` ya no usa Pydantic: las dataclasses estándar son suficientes y
  evitan acoplar el dominio a un framework de validación.
- Las constantes hardcodeadas (Anexo I.5 vivienda, dimensiones del núcleo) se
  mantienen aquí como defaults pero serán sobreescritas por la capa de
  persistencia (BBDD) en producción.
- Se eliminan utilidades de I/O específicas de Streamlit; las cargas desde
  `data/parcelas_sevilla.gpkg` se conservan únicamente como fallback de tests.
"""
