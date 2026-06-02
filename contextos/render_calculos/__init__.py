"""§2.4–2.7 — Render y cálculos.

Envolvente paramétrica (huella + plantas + patios), distribución plurifamiliar y
tabla de superficies. Adaptado del paquete `Modulos/puccetti-app/puccetti/` con
mínimos cambios para encajar en la arquitectura hexagonal de `app/`.

La regla A2.4 (medianeras sin huecos) y A2.5 (estancias principales ventilan a
fachada, nunca al patio) están cableadas en el motor: las medianeras se distinguen
de las fachadas en `geometria.parcelas.LadoParcela.tipo` y solo los segmentos de
tipo "fachada" cuentan para el cálculo de huecos y para validar la ventilación
de cada vivienda.
"""
