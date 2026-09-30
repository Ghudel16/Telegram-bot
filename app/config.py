from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_bot_token: str
    gmgn_api_key: str | None = None
    gmgn_base_url: str | None = None

    # AI provider keys. Never commit these to GitHub.
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
    conduit_api_key_2: str | None = None

    # Optional overrides. If empty, built-in provider defaults are used.
    seekai_base_url: str = 'https://seekai.cc/v1'
    seekai_model: str = 'gpt-5.6'
    agentrouter_base_url: str = 'https://agentrouter.org/v1'
    agentrouter_model: str = 'gpt-5.6-sol'
    kapibala_base_url: str = 'https://kapibala.asia/v1'
    kapibala_model: str = 'gpt-5.6-sol'
    tokenharbor_base_url: str = 'https://tokenharbor.ai/v1'
    tokenharbor_model: str = 'th-orchestra'
    xkiro_base_url: str = 'https://api.xkiro.com/v1'
    xkiro_model: str = 'openai/gpt-5.6-sol'
    infercom_base_url: str = 'https://api.infercom.ai/v1'
    infercom_model: str = 'MiniMax-M2.7'
    morphllm_base_url: str = 'https://api.morphllm.com/v1'
    morphllm_model: str = 'auto'
    iamhc_base_url: str = 'https://api.iamhc.cn/v1'
    iamhc_model: str = 'auto'
    conduit_base_url: str = 'https://conduit.ozdoev.net/v1'
    conduit_model: str = 'gpt-5.6'
    ai_router_order: str = 'agentrouter,gemini,seekai,kapibala,tokenharbor,xkiro,infercom,morphllm,iamhc,conduit'

    database_url: str = 'sqlite:///data/bot.db'
    allowed_telegram_user_ids: str = ''
    min_ath_mc_usd: float = 3_000_000
    default_wallet_limit: int = 30
    railway_public_domain: str | None = None
    webhook_path: str = 'telegram'
    port: int = 8080

    model_config = SettingsConfigDict(
        env_file='.env',
        extra='ignore',
        case_sensitive=False,
    )

    @property
    def allowed_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(',') if x.strip()}
