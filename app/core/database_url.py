"""Database URL helpers shared by deployment configurations."""

from sqlalchemy.engine import URL, make_url


def async_database_url(value: str | URL) -> URL:
    """Select asyncpg when a provider supplies a plain PostgreSQL URL."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+asyncpg")
    return url
