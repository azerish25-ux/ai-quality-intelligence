from sqlalchemy.orm import configure_mappers


def test_relationship_mappers_are_unambiguous() -> None:
    """The live API must be able to configure all ORM joins before first use."""
    configure_mappers()
