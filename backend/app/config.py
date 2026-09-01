import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("NETDOC_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("NETDOC_DATABASE_URL", f"sqlite:///{DATA_DIR}/netdoc.db")

MASTER_KEY_PATH = DATA_DIR / "master.key"
MASTER_KEY_ENV = os.environ.get("NETDOC_MASTER_KEY")

POLL_INTERVAL_SECONDS = int(os.environ.get("NETDOC_POLL_INTERVAL_SECONDS", "300"))
