"""
Where the researcher's model configuration and API key live.

The key is theirs, not the platform's: every call goes from their machine
straight to the endpoint, and Epsilon never sees the prompt. Resolution order
is environment, then OS keyring, then -- reluctantly -- the config file.

The key must never end up inside a project directory. `epsilon build` packages
the tree and ships it to the coordinator, so a key in project.yml or a .env is
an exfiltrated credential. Hence: config lives under the user's home, and
sdk.checks scans the packaged tree for credential shapes on every build.
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from typing import Optional

from sdk.config import CREDENTIALS_DIR

AI_CONFIG_FILE = "config.ini"
AI_SECTION = "ai"

KEYRING_SERVICE = "epsilon-sdk"
KEYRING_ACCOUNT = "ai"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI_COMPATIBLE = "openai-compatible"
PROVIDERS = (PROVIDER_ANTHROPIC, PROVIDER_OPENAI_COMPATIBLE)

DEFAULT_MODELS = {
    PROVIDER_ANTHROPIC: "claude-sonnet-5",
    PROVIDER_OPENAI_COMPATIBLE: "",
}

# Environment variables consulted first, in order.
ENV_KEYS = ("EPSILON_LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

# Capability tiers. Open models vary by more than an order of magnitude in
# instruction-following, and a weak model that emits a snippet printing raw
# records is a disclosure incident rather than a quality problem. Features
# declare the tier they need and refuse below it instead of degrading quietly.
TIER_A = "A"  # frontier hosted: agent loop with tools, code generation
TIER_B = "B"  # strong open weights: structured output, template filling
TIER_C = "C"  # small local: prose and summarisation only
TIER_ORDER = {TIER_C: 0, TIER_B: 1, TIER_A: 2}


def tier_at_least(configured: str, required: str) -> bool:
    return TIER_ORDER.get(configured, -1) >= TIER_ORDER.get(required, 99)


@dataclass
class AIConfig:
    provider: str = PROVIDER_ANTHROPIC
    model: str = DEFAULT_MODELS[PROVIDER_ANTHROPIC]
    base_url: Optional[str] = None
    tier: str = TIER_A
    api_key: Optional[str] = None
    key_source: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self.provider == PROVIDER_OPENAI_COMPATIBLE \
            and bool(self.base_url)


def config_dir() -> str:
    return os.path.join(os.path.expanduser("~"), CREDENTIALS_DIR)


def config_path() -> str:
    return os.path.join(config_dir(), AI_CONFIG_FILE)


# -- keyring, if the platform offers one -----------------------------------

def _keyring():
    """Import keyring lazily; it is an optional convenience, not a dependency."""
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:
        return None


def keyring_available() -> bool:
    return _keyring() is not None


def store_key(api_key: str) -> str:
    """Persist the key as securely as this machine allows. Returns where."""
    ring = _keyring()
    if ring is not None:
        try:
            ring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, api_key)
            return "keyring"
        except Exception:
            pass
    return "unavailable"


def delete_key() -> bool:
    ring = _keyring()
    if ring is None:
        return False
    try:
        ring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        return True
    except Exception:
        return False


def _key_from_keyring() -> Optional[str]:
    ring = _keyring()
    if ring is None:
        return None
    try:
        return ring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        return None


def _key_from_env() -> Optional[tuple]:
    for name in ENV_KEYS:
        value = os.environ.get(name)
        if value:
            return value, "env:" + name
    return None


# -- read / write ----------------------------------------------------------

def load(include_key: bool = True) -> AIConfig:
    """Load AI configuration, resolving the key by precedence."""
    config = AIConfig()
    parser = configparser.ConfigParser()
    path = config_path()
    if os.path.exists(path):
        try:
            parser.read(path)
        except configparser.Error:
            parser = configparser.ConfigParser()
    if parser.has_section(AI_SECTION):
        section = parser[AI_SECTION]
        config.provider = section.get("provider", config.provider)
        config.model = section.get("model", DEFAULT_MODELS.get(config.provider, ""))
        config.base_url = section.get("base_url") or None
        config.tier = section.get("tier", TIER_A)

    if not include_key:
        return config

    from_env = _key_from_env()
    if from_env:
        config.api_key, config.key_source = from_env
        return config

    from_ring = _key_from_keyring()
    if from_ring:
        config.api_key, config.key_source = from_ring, "keyring"
        return config

    if parser.has_section(AI_SECTION):
        file_key = parser[AI_SECTION].get("api_key")
        if file_key:
            config.api_key, config.key_source = file_key, "config file"
    return config


def save(provider: str, model: str, base_url: Optional[str], tier: str) -> str:
    """Write the non-secret settings. Never writes the key."""
    directory = config_dir()
    if not os.path.isdir(directory):
        os.makedirs(directory, mode=0o700)
    path = config_path()
    parser = configparser.ConfigParser()
    if os.path.exists(path):
        try:
            parser.read(path)
        except configparser.Error:
            parser = configparser.ConfigParser()
    if not parser.has_section(AI_SECTION):
        parser.add_section(AI_SECTION)
    parser.set(AI_SECTION, "provider", provider)
    parser.set(AI_SECTION, "model", model or "")
    parser.set(AI_SECTION, "base_url", base_url or "")
    parser.set(AI_SECTION, "tier", tier)
    with open(path, "w", encoding="utf-8") as fh:
        parser.write(fh)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
