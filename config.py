"""Central configuration loaded from .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "")

GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_DEFAULT_OWNER: str = os.getenv("GITHUB_DEFAULT_OWNER", "")

PLATFORM_BASE_URL: str = os.getenv("PLATFORM_BASE_URL", "")
TREVORISM_TENANT_GUID: str = os.getenv("TREVORISM_TENANT_GUID", "")
TREVORISM_USERNAME: str = os.getenv("TREVORISM_USERNAME", "")
TREVORISM_PASSWORD: str = os.getenv("TREVORISM_PASSWORD", "")

# Machine-specific paths – must be set in .env
PS_MODULE_PATH: str = os.getenv("PS_MODULE_PATH", "")
DEV_DIR: Path = Path(os.getenv("DEV_DIR", ""))

MEMORY_DB: str = os.getenv("MEMORY_DB", "memory.db")
WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "./repos"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Set to True via --dry-run flag or DRY_RUN=true env var.
# When True, write/commit/push tools print their intent without making changes.
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"

