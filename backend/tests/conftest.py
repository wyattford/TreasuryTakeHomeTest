import os
import tempfile

# Point the app at a throwaway database before anything imports app.config,
# and don't try to reach Ollama on startup.
_TMP = tempfile.mkdtemp(prefix="ttb-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["OLLAMA_WARMUP_ON_STARTUP"] = "false"
