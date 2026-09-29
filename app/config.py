from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str
    gmgn_api_key: str | None = None
    gmgn_base_url: str | None = None
    seekai_api_key: str | None = None
    gemini_api_key: str | None = None
    agentrouter_api_key: str | None = None
    kapibala_api_key: str | None = None
    tokenharbor_api_key: str | None = None
    xkiro_api_key: str | None = None
    infercom_api_key: str | None = None
    morphllm_api_key: str | None = None
    iamhc_api_key: str | None = None
    conduit_api_key: str | None = None
    conduit_base_url: str = 'https://conduit.ozdoev.net/v1'
    database_url: str = 'sqlite:///data/bot.db'
    allowed_telegram_user_ids: str = ''
    min_ath_mc_usd: float = 3_000_000
    default_wallet_limit: int = 30
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)

    @property
    def allowed_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(',') if x.strip()}
