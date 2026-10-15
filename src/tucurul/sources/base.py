"""Interfaz común para las fuentes de información legislativa."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar


class Level(str, Enum):
    """Nivel de gobierno que cubre una fuente."""

    FEDERAL = "federal"
    ESTATAL = "estatal"
    MUNICIPAL = "municipal"


class Source(ABC):
    """Fuente de datos sobre representantes y su actividad legislativa.

    Las subclases declaran metadatos como atributos de clase e implementan
    ``fetch()`` para descargar o extraer los datos crudos.
    """

    name: ClassVar[str]
    url: ClassVar[str]
    levels: ClassVar[tuple[Level, ...]]
    dimensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def fetch(self) -> Any:
        """Descarga o extrae los datos crudos de la fuente."""
        raise NotImplementedError
