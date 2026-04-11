"""Configuration for the GivLocally application."""

from dataclasses import dataclass, field
import os


DEFAULT_HOST = "192.168.0.100"
DEFAULT_PORT = 8899
DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 30.0


@dataclass
class InverterConfig:
    """Connection and operational configuration for a GivEnergy inverter."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    number_batteries: int = 1
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY

    @classmethod
    def from_env(cls) -> "InverterConfig":
        """Load config from environment variables (GIVENERGY_HOST, etc.)."""
        host = os.environ.get("GIVENERGY_HOST", DEFAULT_HOST)
        return cls(
            host=host,
            port=int(os.environ.get("GIVENERGY_PORT", DEFAULT_PORT)),
            number_batteries=int(os.environ.get("GIVENERGY_BATTERIES", 1)),
            timeout=float(os.environ.get("GIVENERGY_TIMEOUT", DEFAULT_TIMEOUT)),
        )
