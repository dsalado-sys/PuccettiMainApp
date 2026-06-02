"""Cache LRU en memoria para parcelas localizadas pero aún no asociadas a proyecto.

Las parcelas viven hasta que se asocian a un Proyecto (entonces pasan a SQLite
vía el aggregate `Proyecto`) o hasta que el cache las descarta.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from app.contextos.localizacion.dominio import Parcela
from app.contextos.localizacion.puertos import ParcelaTemporalRepositorio


class ParcelasEnMemoria(ParcelaTemporalRepositorio):
    def __init__(self, capacidad: int = 200) -> None:
        self._cap = capacidad
        self._datos: "OrderedDict[str, Parcela]" = OrderedDict()
        self._lock = RLock()

    def guardar(self, parcela: Parcela) -> None:
        with self._lock:
            if parcela.id in self._datos:
                self._datos.move_to_end(parcela.id)
            self._datos[parcela.id] = parcela
            while len(self._datos) > self._cap:
                self._datos.popitem(last=False)

    def obtener(self, parcela_id: str) -> Parcela | None:
        with self._lock:
            parcela = self._datos.get(parcela_id)
            if parcela is not None:
                self._datos.move_to_end(parcela_id)
            return parcela
