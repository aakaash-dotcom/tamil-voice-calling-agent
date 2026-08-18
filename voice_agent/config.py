"""
voice_agent.config — Centralized settings loaded from environment / .env file.

All runtime configuration lives here. No other module reads os.environ directly.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All tunable settings for the voice agent. Loaded from .env or environment."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_env: Literal["development", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # --- Business context ---
    business_mode: Literal["tuition", "pg", "shared"] = "shared"
    default_language: str = "ta-IN"

    # --- Groq LLM ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.4
    groq_max_tokens: int = 400
    groq_stream: bool = True

    # --- Edge-TTS ---
    tts_voice: str = "ta-IN-PallaviNeural"
    tts_rate: str = "+5%"
    tts_volume: str = "+0%"
    tts_pitch: str = "+0Hz"

    # --- Faster-Whisper ---
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = "ta"
    whisper_vad_filter: bool = True

    # --- Twilio ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_whatsapp_number: str = ""

    # --- Public webhook URL ---
    public_base_url: str = "http://localhost:8000"

    # --- Database ---
    database_path: str = str(PROJECT_ROOT / "voice_agent.db")

    # --- Recordings ---
    recordings_dir: str = str(PROJECT_ROOT / "download" / "recordings")

    # --- Lead thresholds ---
    lead_hot_score: int = 80
    lead_warm_score: int = 50

    # --- Tuition Centre business info ---
    tuition_name: str = "Vidhya Tuition Centre"
    tuition_address: str = ""
    tuition_phone: str = ""
    tuition_location_pin: str = ""
    tuition_fees_pdf_path: str = ""
    tuition_subjects: str = ""
    tuition_batches: str = ""
    tuition_fees: str = ""
    tuition_trial: bool = True

    # --- Gents PG business info ---
    pg_name: str = "Shanthi Gents PG"
    pg_address: str = ""
    pg_phone: str = ""
    pg_location_pin: str = ""
    pg_fees_pdf_path: str = ""
    pg_rent: str = ""
    pg_deposit: str = ""
    pg_amenities: str = ""
    pg_vacancy: str = ""

    # --- Convenience derived paths ---
    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def assets_dir(self) -> Path:
        p = PROJECT_ROOT / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def download_dir(self) -> Path:
        p = PROJECT_ROOT / "download"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def recordings_path(self) -> Path:
        p = Path(self.recordings_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @field_validator("whisper_language")
    @classmethod
    def _validate_whisper_lang(cls, v: str | None) -> str | None:
        if v in (None, "", "None", "null"):
            return None
        return v.lower()

    def business_context(self, business: str) -> dict:
        """Return a dict of business fields for the given business type."""
        if business == "tuition":
            return {
                "name": self.tuition_name,
                "address": self.tuition_address,
                "phone": self.tuition_phone,
                "location_pin": self.tuition_location_pin,
                "fees_pdf_path": self.tuition_fees_pdf_path,
                "subjects": self.tuition_subjects,
                "batches": self.tuition_batches,
                "fees": self.tuition_fees,
                "trial_available": self.tuition_trial,
            }
        if business == "pg":
            return {
                "name": self.pg_name,
                "address": self.pg_address,
                "phone": self.pg_phone,
                "location_pin": self.pg_location_pin,
                "fees_pdf_path": self.pg_fees_pdf_path,
                "rent": self.pg_rent,
                "deposit": self.pg_deposit,
                "amenities": self.pg_amenities,
                "vacancy": self.pg_vacancy,
            }
        raise ValueError(f"Unknown business: {business}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — reads .env once on first call."""
    return Settings()


def reload_settings() -> Settings:
    """Force re-read of .env (useful for tests)."""
    get_settings.cache_clear()
    return get_settings()
