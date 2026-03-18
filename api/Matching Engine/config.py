import os


class Settings:
    def _load_dotenv(self) -> None:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    def __init__(self) -> None:
        self._load_dotenv()
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.batch_size = int(os.getenv("MATCH_BATCH_SIZE", "5"))
        self.verbose = os.getenv("MATCH_VERBOSE", "1").lower() in {"1", "true", "yes", "on"}
        self.queue_max_size = int(os.getenv("MATCH_QUEUE_MAX_SIZE", "100"))
        self.queue_workers = int(os.getenv("MATCH_QUEUE_WORKERS", "3"))

