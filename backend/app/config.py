from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    GROQ_API_KEY: str = ""
    GROQ_API_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3"
    GROQ_LLM_MODEL: str = "llama-3.3-70b-versatile"

    VLM_API_URL: str = ""
    VLM_API_KEY: str = ""
    VLM_MODEL: str = ""

    EMBEDDING_API_URL: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384

    DATABASE_MODE: str = "auto"

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str | int = 5432
    POSTGRES_USER: str = "hackathon"
    POSTGRES_PASSWORD: str = "hackathon_pass"
    POSTGRES_DB: str = "multimodal_rag"

    SQLITE_PATH: Path = Path("./storage/multimodal_rag.sqlite3")

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_COLLECTION: str = "evidence"
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""

    FFMPEG_PATH: str = "ffmpeg"
    FRAME_SAMPLE_INTERVAL: int = 3
    SCENE_CHANGE_THRESHOLD: float = 15.0
    MAX_IMPORTANT_FRAMES: int = 200

    STORAGE_PATH: Path = Path("./storage")
    UPLOAD_PATH: Path = Path("./storage/uploads")
    FRAME_PATH: Path = Path("./storage/frames")
    AUDIO_PATH: Path = Path("./storage/audio")
    EVIDENCE_PATH: Path = Path("./storage/evidence")

    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    @property
    def DATABASE_URL(self) -> str:
        if self.POSTGRES_HOST.startswith("postgres://") or self.POSTGRES_HOST.startswith("postgresql://"):
            return self.POSTGRES_HOST.replace("postgres://", "postgresql+psycopg2://")

        mode = self.DATABASE_MODE.lower()
        port = self.POSTGRES_PORT if self.POSTGRES_PORT else 5432
        if mode == "sqlite":
            return f"sqlite:///{self.SQLITE_PATH.resolve()}"
        if mode == "postgres":
            return f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{port}/{self.POSTGRES_DB}"
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect((self.POSTGRES_HOST, int(port)))
            s.close()
            return f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{port}/{self.POSTGRES_DB}"
        except Exception:
            return f"sqlite:///{self.SQLITE_PATH.resolve()}"

    def ensure_dirs(self) -> None:
        for path in [self.STORAGE_PATH, self.UPLOAD_PATH, self.FRAME_PATH, self.AUDIO_PATH, self.EVIDENCE_PATH]:
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
