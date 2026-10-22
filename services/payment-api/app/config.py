"""Configuration typée de l'API métier."""

from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "payuser"
    postgres_password: str = "payuser"
    postgres_db: str = "paymentdb"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    # Jetons intermédiaires du parcours client (§10.1 : identifiant -> visage
    # -> mot de passe), émis par ce service entre deux étapes : durée de vie
    # volontairement courte.
    face_pending_expire_seconds: int = 120

    # Auto-inscription (mot de passe + visage, POST /auth/register).
    registration_starting_balance: Decimal = Decimal("1000.00")

    # Relais WebSocket temps réel des vérifications faciales (indicateur LED
    # ESP8266, voir firmware/face-led/) : jeton partagé, fonctionnalité annexe.
    esp_events_token: str = "dev-only-change-me"

    # Validation faciale des virements (API DeepFace interne).
    face_confirmation_required: bool = True
    face_api_url: str = "http://face-api:5000"
    face_api_token: str = ""
    face_api_timeout_seconds: float = 30.0
    face_model: str = "Facenet512"
    face_detector: str = "yunet"
    face_anti_spoofing: bool = True
    # Seuil de distance cosinus Facenet512 recommandé par DeepFace (0.30).
    face_match_threshold: float = 0.30
    face_confirm_ttl_seconds: int = 300
    face_max_attempts_per_tx: int = 3
    # Verrou anti-force brute : N échecs sur la fenêtre -> 429. Confirmation
    # de virement uniquement (purpose='confirm') : le login a son propre
    # seuil ci-dessous, plus strict (§10.1).
    face_lockout_failures: int = 5
    face_lockout_minutes: int = 15
    # Login (identifiant -> visage -> mot de passe, purpose='login') : 2
    # tentatives AU TOTAL (visage + mot de passe confondus, compteur
    # partagé), puis 5 min de blocage (§10.1).
    login_lockout_failures: int = 2
    login_lockout_minutes: int = 5

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"user={self.postgres_user} password={self.postgres_password} "
            f"dbname={self.postgres_db}"
        )


settings = Settings()
