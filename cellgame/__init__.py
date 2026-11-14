"""CellGame: multiplayer cellular automata.

The source checkout keeps its components at the project root. Published wheels
install them under this namespace to avoid generic top-level package names.
"""
from pathlib import Path

__version__ = "0.2.0"

_source_root = Path(__file__).resolve().parent.parent
if (_source_root / "pyproject.toml").is_file() and (_source_root / "species" / "composer.py").is_file():
    __path__.append(str(_source_root))
