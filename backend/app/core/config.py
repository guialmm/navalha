from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://navalha:navalha@localhost:5434/navalha"

    # The shop
    fuso: str = "America/Sao_Paulo"
    # Slots start every 15 minutes; a 45-minute beard + cut fits between 30-minute cuts.
    passo_minutos: int = 15
    # No booking that starts sooner than this: the barber needs to see it coming.
    antecedencia_minutos: int = 30
    # How far ahead a customer may book.
    horizonte_dias: int = 30

    # Gemini (free tier). Text models are tried in order when one is overloaded.
    gemini_api_key: str = ""
    gemini_modelos_texto: list[str] = ["gemini-3.7-flash", "gemini-flash-latest"]
    # Reference paid-tier prices (USD per million tokens) used only to show what a
    # conversation would cost; the demo itself runs on the free tier.
    preco_entrada_usd_mtok: float = 0.30
    preco_saida_usd_mtok: float = 2.50

    # Voice: Gemini Live (native audio) through LiveKit
    gemini_modelo_voz: str = "gemini-3.1-flash-live-preview"
    gemini_voz: str = "Kore"
    preco_voz_entrada_usd_mtok: float = 3.00
    preco_voz_saida_usd_mtok: float = 12.00
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, url: str) -> str:
        """Accept the plain URLs hosts hand out (Neon, Render):
        postgres://…?sslmode=require&channel_binding=require → asyncpg form."""
        parts = urlsplit(url)
        scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql") else parts.scheme
        query = dict(parse_qsl(parts.query))
        if (mode := query.pop("sslmode", None)) and mode != "disable":
            query["ssl"] = "require"
        query.pop("channel_binding", None)
        return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
