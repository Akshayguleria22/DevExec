from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DevExec Sentinel"
    database_url: str = "postgresql+psycopg://postgres:A1k2s3h4a5y6@localhost:5432/Devexec"
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "devexec_tasks"
    agent_queue_name: str = "devexec_agents"
    webhook_secret: str = ""
    default_api_base_url: str = ""
    notification_webhook_url: str = ""
    notification_timeout_seconds: int = 10
    github_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    enable_github_pr_comment: bool = False
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    sandbox_image: str = "devexec-sandbox:latest"
    sandbox_workspace_root: str = "./sandbox-data/workspaces"
    sandbox_artifact_root: str = "./sandbox-data/artifacts"
    sandbox_default_timeout_seconds: int = 300
    sandbox_cpu_limit: float = 1.0
    sandbox_memory_limit_mb: int = 1024
    sandbox_pids_limit: int = 256
    sandbox_network_enabled: bool = False
    sandbox_user: str = "1000:1000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
