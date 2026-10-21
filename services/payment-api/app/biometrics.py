"""Persistance biométrique : empreinte de référence et journal d'audit.

Seul le vecteur d'empreinte est stocké, jamais l'image (minimisation).
"""

from __future__ import annotations

from . import db


def get_enrollment(username: str) -> dict | None:
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT e.model_name, e.embedding, e.created_at FROM face_enrollment e "
            "JOIN app_user u ON u.id = e.user_id WHERE u.username = %s",
            (username,),
        ).fetchone()


def save_enrollment(username: str, model_name: str, embedding: list[float]) -> bool:
    """Enrôlement unique : False si une empreinte existe déjà (pas d'écrasement
    silencieux par quiconque détient le mot de passe)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "INSERT INTO face_enrollment (user_id, model_name, embedding) "
            "SELECT id, %s, %s FROM app_user WHERE username = %s "
            "ON CONFLICT (user_id) DO NOTHING RETURNING user_id",
            (model_name, embedding, username),
        ).fetchone()
    return row is not None


def replace_enrollment(username: str, model_name: str, embedding: list[float]) -> bool:
    """Réservé à l'outil d'admin (enroll_cli) : écrase l'empreinte existante.
    False si l'utilisateur n'existe pas."""
    with db.get_conn() as conn:
        row = conn.execute(
            "INSERT INTO face_enrollment (user_id, model_name, embedding) "
            "SELECT id, %s, %s FROM app_user WHERE username = %s "
            "ON CONFLICT (user_id) DO UPDATE SET model_name = EXCLUDED.model_name, "
            "embedding = EXCLUDED.embedding, created_at = now() RETURNING user_id",
            (model_name, embedding, username),
        ).fetchone()
    return row is not None


def log_attempt(
    username: str, *, purpose: str, result: str, distance: float | None, tx_id: int | None = None
) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO face_verification_log (user_id, tx_id, purpose, result, distance) "
            "SELECT id, %s, %s, %s, %s FROM app_user WHERE username = %s",
            (tx_id, purpose, result, distance, username),
        )


def recent_failures(username: str, minutes: int, purpose: str = "confirm") -> int:
    """Échecs de reconnaissance (visage différent ou spoof) sur la fenêtre,
    pour un `purpose` donné ('confirm' ou 'login' : compteurs indépendants,
    un client qui rate sa connexion ne doit pas épuiser ses essais sur une
    confirmation de virement en cours, et inversement)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM face_verification_log l "
            "JOIN app_user u ON u.id = l.user_id "
            "WHERE u.username = %s AND l.purpose = %s "
            "AND l.result IN ('mismatch', 'spoof') "
            "AND l.created_at > now() - make_interval(mins => %s)",
            (username, purpose, minutes),
        ).fetchone()
    return row["n"]
