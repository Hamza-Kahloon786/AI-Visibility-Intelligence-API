import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL_DISCOVERY = os.environ.get("OPENAI_MODEL_DISCOVERY", "gpt-4o")
    OPENAI_MODEL_SCORING = os.environ.get("OPENAI_MODEL_SCORING", "gpt-4o-mini")
    OPENAI_MODEL_RECOMMENDATION = os.environ.get("OPENAI_MODEL_RECOMMENDATION", "gpt-4o")

    DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN")
    DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    PIPELINE_RUN_RATE_LIMIT = os.environ.get("PIPELINE_RUN_RATE_LIMIT", "10 per hour")

    # Pipeline tuning knobs -- kept here (not hardcoded in services) so they're
    # visible/overridable in one place.
    MAX_DISCOVERY_QUERIES = int(os.environ.get("MAX_DISCOVERY_QUERIES", 18))
    MAX_GAP_QUERIES_FOR_RECOMMENDATIONS = int(
        os.environ.get("MAX_GAP_QUERIES_FOR_RECOMMENDATIONS", 8)
    )


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    RATELIMIT_ENABLED = False


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
