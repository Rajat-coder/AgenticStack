from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str

    # AI providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ai_provider: str = "anthropic"

    # JIRA
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""
    jira_in_review_status: str = "In Review"

    # GitHub
    github_token: str = ""
    github_repo_owner: str = ""
    github_repo_name: str = ""

    # Target repo
    target_repo_path: str = ""

    # Ollama — ( runs locally )
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "codellama:7b-instruct"

settings = Settings()