"""Persistance biométrique : pool d'empreintes de référence (une par pose :
face, left, right, up, down) et journal d'audit.

Seuls les vecteurs d'empreinte sont stockés, jamais les photos (minimisation).
"""

from __future__ import annotations

from . import db


def get_enrollment(username: str) -> dict | None:
    """Pool complet de l'utilisateur, ou `None` si rien n'est enrôlé.
    `poses` : `{pose: embedding}` (une entrée par pose enrôlée)."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT e.pose, e.model_name, e.embedding, e.created_at FROM face_enrollment e "
            "JOIN app_user u ON u.id = e.user_id WHERE u.username = %s",
            (username,),
        ).fetchall()
    if not rows:
        return None
    return {
        "model_name": rows[0]["model_name"],
        "created_at": min(r["created_at"] for r in rows),
        "poses": {r["pose"]: r["embedding"] for r in rows},
    }


def _replace_all(conn, user_id: int, model_name: str, poses: dict[str, list[float]]) -> None:
    for pose, embedding in poses.items():
        conn.execute(
            "INSERT INTO face_enrollment (user_id, pose, model_name, embedding) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, pose, model_name, embedding),
        )


def save_enrollment(username: str, model_name: str, poses: dict[str, list[float]]) -> bool:
    """Enrôlement unique : tout le pool (5 poses) est écrit d'un coup, de
    façon atomique. `False` si l'utilisateur n'existe pas, ou si une
    empreinte existe déjà (pas d'écrasement silencieux par quiconque détient
    le mot de passe)."""
    with db.get_conn() as conn:
        user = conn.execute("SELECT id FROM app_user WHERE username = %s", (username,)).fetchone()
        if user is None:
            return False
        exists = conn.execute(
            "SELECT 1 FROM face_enrollment WHERE user_id = %s LIMIT 1", (user["id"],)
        ).fetchone()
        if exists is not None:
            return False
        _replace_all(conn, user["id"], model_name, poses)
    return True


def replace_enrollment(username: str, model_name: str, poses: dict[str, list[float]]) -> bool:
    """Réservé à l'outil d'admin (enroll_cli) : écrase le pool existant.
    `False` si l'utilisateur n'existe pas."""
    with db.get_conn() as conn:
        user = conn.execute("SELECT id FROM app_user WHERE username = %s", (username,)).fetchone()
        if user is None:
            return False
        conn.execute("DELETE FROM face_enrollment WHERE user_id = %s", (user["id"],))
        _replace_all(conn, user["id"], model_name, poses)
    return True


def delete_enrollment(username: str) -> bool:
    """Back-office (§10.1) : réinitialise le visage d'un client (le pool est
    entièrement supprimé, à charge pour lui de le recréer — mot de passe
    d'abord, cf. `db.customer_needs_reenrollment`). `False` si l'utilisateur
    n'avait rien enrôlé (pas une erreur, juste rien à faire)."""
    with db.get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM face_enrollment WHERE user_id = "
            "(SELECT id FROM app_user WHERE username = %s)",
            (username,),
        )
        return cur.rowcount > 0


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
    """Échecs sur la fenêtre, pour un `purpose` donné ('confirm' ou 'login' :
    compteurs indépendants, un client qui rate sa connexion ne doit pas
    épuiser ses essais sur une confirmation de virement en cours, et
    inversement). 'password_mismatch' ne peut survenir qu'en purpose='login'
    (§10.1 : 2 tentatives AU TOTAL pour tout le parcours de connexion,
    visage et mot de passe confondus — un seul compteur partagé)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM face_verification_log l "
            "JOIN app_user u ON u.id = l.user_id "
            "WHERE u.username = %s AND l.purpose = %s "
            "AND l.result IN ('mismatch', 'spoof', 'password_mismatch') "
            "AND l.created_at > now() - make_interval(mins => %s)",
            (username, purpose, minutes),
        ).fetchone()
    return row["n"]
