import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    keyward_url: str
    keyward_agent_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str
    owner_number: str
    allowed_numbers: tuple[str, ...]
    db_path: str
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    public_url: str = ""
    twilio_account_sid: str = ""
    twilio_from: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            keyward_url=e("KEYWARD_URL", "http://127.0.0.1:8787"),
            keyward_agent_token=e("KEYWARD_AGENT_TOKEN", ""),
            whatsapp_phone_number_id=e("WHATSAPP_PHONE_NUMBER_ID", ""),
            whatsapp_verify_token=e("WHATSAPP_VERIFY_TOKEN", ""),
            owner_number=e("OWNER_NUMBER", ""),
            allowed_numbers=tuple(n.strip() for n in e("ALLOWED_NUMBERS", "").split(",") if n.strip()),
            db_path=e("HALO_DB", "halo.db"),
            ollama_url=e("OLLAMA_URL", "http://localhost:11434"),
            ollama_model=e("OLLAMA_MODEL", "qwen2.5:3b"),
            ollama_timeout=float(e("OLLAMA_TIMEOUT", "20")),
            public_url=e("HALO_PUBLIC_URL", "").rstrip("/"),
            twilio_account_sid=e("TWILIO_ACCOUNT_SID", ""),  # an ID, not a secret; the auth token lives in Keyward
            twilio_from=e("TWILIO_FROM", ""),
        )
