"""Configuration des tests — expose la racine du dépôt et les modules services.

Les services ont des noms de dossier avec tiret (non importables directement) :
on charge les modules utiles par chemin de fichier via importlib.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_module(name: str, relpath: str):
    """Charge un module par chemin de fichier (pour les packages à tiret)."""
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
