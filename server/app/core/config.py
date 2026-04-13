from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DevExec Sentinel"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/devexec"
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "devexec_tasks"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
