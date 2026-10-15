"""Límites de tamaño para archivos versionados y para el sitio estático.

GitHub advierte sobre archivos >50 MiB, rechaza push de archivos >100 MiB y
limita las subidas web a 25 MiB. El proyecto fija umbrales propios más
conservadores para los datos rastreados y para cada archivo del sitio.
"""

from collections.abc import Iterable
from pathlib import Path

GITHUB_WARN_BYTES = 50 * 1024 * 1024  # GitHub muestra advertencia >50 MiB
GITHUB_HARD_LIMIT_BYTES = 100 * 1024 * 1024  # GitHub rechaza el push >100 MiB
MAX_TRACKED_DATA_BYTES = 25 * 1024 * 1024  # política del proyecto (límite web)
MAX_SITE_FILE_BYTES = 5 * 1024 * 1024  # tope por archivo del sitio estático


def oversized_files(
    root: Path, limit: int, exclude: Iterable[str] = ("raw",)
) -> list[tuple[Path, int]]:
    """Lista ``(ruta_relativa, bytes)`` de archivos bajo ``root`` sobre ``limit``.

    ``exclude`` omite subdirectorios de primer nivel (por defecto ``raw/``,
    que no está versionado).
    """
    root = Path(root)
    excluded = set(exclude)
    oversized = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in excluded:
            continue
        size = path.stat().st_size
        if size > limit:
            oversized.append((rel, size))
    return oversized


def human_size(size: int) -> str:
    """Formato legible: ``2.1 MiB``."""
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MiB"
    if size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size} B"
