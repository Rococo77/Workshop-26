"""Le test qui compte pour la détection : le modèle non supervisé doit
distinguer un trafic nominal d'attaques (flood / injection) avec un rappel
élevé et peu de faux positifs. Sinon la chaîne de reprise ne se déclenche pas.
"""
from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

import ml.train as train  # noqa: E402


def _fit():
    X = train.nominal()
    mean, std = X.mean(axis=0), X.std(axis=0) + 1e-9
    from sklearn.ensemble import IsolationForest
    clf = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    clf.fit((X - mean) / std)
    return clf, mean, std


def test_detecte_les_attaques_et_limite_les_faux_positifs():
    clf, mean, std = _fit()
    nom = (train.nominal(1000) - mean) / std
    atk = (train.attacks(300) - mean) / std

    recall = float((clf.predict(atk) == -1).mean())
    false_positive = float((clf.predict(nom) == -1).mean())

    # Seuils de non-régression : la détection doit rester exploitable.
    assert recall >= 0.80, f"rappel insuffisant: {recall:.2%}"
    assert false_positive <= 0.15, f"trop de faux positifs: {false_positive:.2%}"
