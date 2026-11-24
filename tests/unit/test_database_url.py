from app.core.database_url import async_database_url


def test_plain_postgres_url_is_normalized_to_asyncpg() -> None:
    url = async_database_url("postgresql://user:secret@db.example/finpilot")

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db.example"
    assert url.database == "finpilot"


def test_explicit_asyncpg_url_is_preserved() -> None:
    url = async_database_url(
        "postgresql+asyncpg://user:secret@localhost/finpilot_test"
    )

    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "finpilot_test"
