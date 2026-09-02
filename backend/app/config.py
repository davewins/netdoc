import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("NETDOC_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("NETDOC_DATABASE_URL", f"sqlite:///{DATA_DIR}/netdoc.db")

MASTER_KEY_PATH = DATA_DIR / "master.key"
MASTER_KEY_ENV = os.environ.get("NETDOC_MASTER_KEY")

# Bearer token required on the /mcp endpoint. Generated and persisted the
# same way as the master encryption key above (see crypto.py) since the
# rest of the API has no authentication at all - this is the only thing
# standing between the network and an MCP client that can trigger connector
# polls and confirm/reject asset links.
MCP_TOKEN_PATH = DATA_DIR / "mcp_token"
MCP_TOKEN_ENV = os.environ.get("NETDOC_MCP_TOKEN")

POLL_INTERVAL_SECONDS = int(os.environ.get("NETDOC_POLL_INTERVAL_SECONDS", "300"))
