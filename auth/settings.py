import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuthSettings:
    database_url: str
    production: bool
    origins: frozenset
    registration_enabled: bool
    idle_seconds: int = 1800
    absolute_seconds: int = 43200
    namespace: str = "local"
    password_registration_enabled: bool = False

    @property
    def cookie_name(self):
        return "__Host-medix_session" if self.production else "medix_dev_session"

    @classmethod
    def from_env(cls):
        mode = os.getenv("MEDIX_ENV", "development")
        if mode not in {"development", "production"}:
            raise ValueError("MEDIX_ENV must be development or production")
        production = mode == "production"
        origins = frozenset(x.strip().rstrip("/") for x in os.getenv(
            "MEDIX_ALLOWED_ORIGINS", "http://127.0.0.1:8765,http://localhost:8765"
        ).split(",") if x.strip())
        if production and (not origins or any(not x.startswith("https://") for x in origins)):
            raise ValueError("Production requires explicit HTTPS MEDIX_ALLOWED_ORIGINS")
        data_dir = Path(os.getenv("MEDIX_DATA_DIR", str(Path(__file__).resolve().parents[1] / ".medix-data")))
        url = os.getenv("MEDIX_DATABASE_URL", "sqlite:///" + (data_dir / "app.db").as_posix())
        namespace = os.getenv("MEDIX_IDENTITY_NAMESPACE", "local")
        if not namespace or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in namespace):
            raise ValueError("Invalid MEDIX_IDENTITY_NAMESPACE")
        return cls(url, production, origins,
                   os.getenv("MEDIX_ALLOW_REGISTRATION", "false" if production else "true").lower() == "true",
                   namespace=namespace)
