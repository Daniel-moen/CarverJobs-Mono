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
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.match_max_tokens = int(os.getenv("MATCH_MAX_TOKENS", "2048"))
        # GPT-5 family only accepts the default temperature, so we omit it unless
        # MATCH_TEMPERATURE is explicitly set (e.g. for older models like gpt-4o-mini).
        _temp = os.getenv("MATCH_TEMPERATURE")
        self.match_temperature = float(_temp) if _temp not in (None, "") else None
        # seed gives reproducible scores on models that ignore temperature.
        _seed = os.getenv("MATCH_SEED", "7")
        self.match_seed = int(_seed) if _seed not in (None, "") else None
        self.batch_size = int(os.getenv("MATCH_BATCH_SIZE", "5"))
        self.verbose = os.getenv("MATCH_VERBOSE", "1").lower() in {"1", "true", "yes", "on"}
        self.queue_max_size = int(os.getenv("MATCH_QUEUE_MAX_SIZE", "100"))
        self.queue_workers = int(os.getenv("MATCH_QUEUE_WORKERS", "3"))

