"""Configuration des tests.

Les services ont des noms de dossier avec tiret (non importables directement)
et utilisent des imports relatifs (`from . import config`). On enregistre donc
le dossier `app/` de chaque service comme un package nommé, avec un `__path__`,
afin que les imports relatifs se résolvent correctement.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_service_module(pkg_name: str, service_dir: str, module: str):
    """Charge `<service_dir>/app/<module>.py` comme `<pkg_name>.<module>`,
    en créant le package `<pkg_name>` pointant sur le dossier `app/`."""
    base = ROOT / service_dir / "app"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(base)]  # permet `from . import config`
        sys.modules[pkg_name] = pkg

    full = f"{pkg_name}.{module}"
    spec = importlib.util.spec_from_file_location(full, base / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod
