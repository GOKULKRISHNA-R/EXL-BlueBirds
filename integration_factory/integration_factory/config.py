import os
from pathlib import Path
from dotenv import load_dotenv
PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
load_dotenv(PROJECT / ".env")
MOCK_DIR = Path(os.getenv("MOCK_SYSTEMS_DIR", str(ROOT / "mockSystems"))).resolve()
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", str(PROJECT / "artifacts"))).resolve()
