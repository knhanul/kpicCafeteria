from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "구내식당 관리 시스템"
    app_secret: str = "dev-secret"
    admin_username: str = "admin"
    admin_password: str = "change-me"
    admin_display_name: str = "영양사"
    database_url: str = "sqlite:///./cafeteria.db"
    storage_root: Path = Path("./storage")
    public_base_url: str = "http://localhost"
    timezone: str = "Asia/Seoul"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def import_dir(self) -> Path:
        return self.storage_root / "imports"

    @property
    def template_dir(self) -> Path:
        return self.storage_root / "templates"

    @property
    def generated_dir(self) -> Path:
        return self.storage_root / "generated"


settings = Settings()
for path in (settings.storage_root, settings.import_dir, settings.template_dir, settings.generated_dir):
    path.mkdir(parents=True, exist_ok=True)
