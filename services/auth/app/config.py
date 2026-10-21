"""Configuration typée du service d'authentification."""

from __future__ import annotations

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
    # Jeton intermédiaire (mot de passe validé, visage pas encore vérifié),
    # consommé par payment-api : POST /auth/login/face. Durée courte.
    face_pending_expire_seconds: int = 120

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"user={self.postgres_user} password={self.postgres_password} "
            f"dbname={self.postgres_db}"
        )


settings = Settings()
