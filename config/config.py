from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # ==========================================
    # BASE PATHS
    # ==========================================
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    RAW_DATA_DIR: Path = BASE_DIR / "data" / "01_raw"
    OUTPUT_DIR: Path = BASE_DIR / "data" / "02_processed"
    LOG_DIR: Path = BASE_DIR / "logs"

    # ==========================================
    # SERVICES CONFIGURATION
    # ==========================================
    SERVICE_A_CLIENT_ID: str = ""
    SERVICE_A_TENANT_ID: str = ""
    SERVICE_A_SCOPE: str = ""
    SERVICE_A_CERT_PASSWORD: str = ""
    SERVICE_A_CERT_FILENAME: str = ""

    SERVICE_B_CLIENT_ID: str = ""
    SERVICE_B_CLIENT_SECRET: str = ""

    SERVICE_C_CLIENT_ID: str = ""
    SERVICE_C_CLIENT_SECRET: str = ""

    SERVICE_D_TOKEN_URL: str = ""
    SERVICE_D_CLIENT_ID: str = ""
    SERVICE_D_CLIENT_SECRET: str = ""
    SERVICE_D_API_URL_BASE: str = ""

    SERVICE_E_API_KEY: str = ""
    SERVICE_F_API_KEY: str = ""

    SERVICE_G_CLIENT_SECRET: str = ""
    SERVICE_G_CLIENT_ID: str = ""

    # ==========================================
    # SYSTEM CONFIGURATION
    # ==========================================
    MAX_API_WORKERS: int = 8
    MAX_API_RETRIES: int = 5
    RETRY_BACKOFF_BASE: float = 2.0

    # Read configuration from the local environment file
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Initialize the configuration instance
Config = Settings()
