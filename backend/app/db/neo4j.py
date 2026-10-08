"""Reusable Neo4j connection and session management layer for Atlas AI."""

from collections.abc import Generator
import logging
from neo4j import Driver, GraphDatabase, Session

from app.core.config import settings

logger = logging.getLogger("atlas_ai.neo4j")


class Neo4jConnectionError(Exception):
    """Raised when Neo4j connection, driver, or session operations fail."""


_driver: Driver | None = None


def init_driver(
    uri: str | None = None,
    auth: tuple[str, str] | None = None,
) -> Driver:
    """Initialize the singleton application-level Neo4j driver.

    Args:
        uri: Optional connection URI. Defaults to settings.NEO4J_URI.
        auth: Optional (username, password) tuple. Defaults to configured settings.

    Returns:
        Driver: Initialized Neo4j driver instance.

    Raises:
        Neo4jConnectionError: If driver instantiation fails.
    """
    global _driver

    if _driver is not None:
        close_driver()

    target_uri = uri if uri is not None else settings.NEO4J_URI
    username = auth[0] if auth is not None else settings.NEO4J_USERNAME
    password = auth[1] if auth is not None else settings.NEO4J_PASSWORD

    try:
        _driver = GraphDatabase.driver(target_uri, auth=(username, password))
        logger.info("Initialized Neo4j driver for %s", target_uri)
        return _driver
    except Exception as exc:
        logger.error("Failed to initialize Neo4j driver: %s", type(exc).__name__)
        raise Neo4jConnectionError("Failed to initialize Neo4j driver.") from None


def get_driver() -> Driver:
    """Return the active application-level Neo4j driver instance.

    Returns:
        Driver: Active Neo4j driver.

    Raises:
        Neo4jConnectionError: If the driver has not been initialized.
    """
    if _driver is None:
        raise Neo4jConnectionError("Neo4j driver is not initialized.")
    return _driver


def set_driver(driver: Driver | None) -> None:
    """Set or override the active Neo4j driver instance (primarily for testing)."""
    global _driver
    _driver = driver


def close_driver() -> None:
    """Close the application-level Neo4j driver instance safely."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
            logger.info("Closed Neo4j driver")
        except Exception as exc:
            logger.warning("Error closing Neo4j driver: %s", type(exc).__name__)
        finally:
            _driver = None


def get_neo4j_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped Neo4j session.

    Acquires a session from the application-level driver and ensures it is
    safely closed after the request completes or if an error occurs.

    Yields:
        Session: Request-scoped Neo4j database session.

    Raises:
        Neo4jConnectionError: If the driver is uninitialized or session acquisition fails.
    """
    driver = get_driver()
    try:
        session = driver.session()
    except Exception as exc:
        logger.error("Failed to acquire Neo4j session: %s", type(exc).__name__)
        raise Neo4jConnectionError("Failed to acquire Neo4j session.") from None

    try:
        yield session
    finally:
        try:
            session.close()
        except Exception as exc:
            logger.warning("Error closing Neo4j session: %s", type(exc).__name__)


def verify_connectivity(driver: Driver | None = None) -> bool:
    """Verify connectivity to Neo4j using a minimal deterministic ping query.

    Responsibility is strictly: 'Can the configured application connect to Neo4j?'
    Executes 'RETURN 1 AS ping'. Does not modify schema, data, or create nodes/relationships.

    Args:
        driver: Optional driver instance to verify. If omitted, uses application driver.

    Returns:
        bool: True if connection is healthy and ping returns expected result.

    Raises:
        Neo4jConnectionError: If connection fails or ping query returns unexpected output.
    """
    target_driver = driver if driver is not None else get_driver()
    try:
        target_driver.verify_connectivity()
        with target_driver.session() as session:
            result = session.run("RETURN 1 AS ping").single()
            if result is not None and result.get("ping") == 1:
                return True
        raise Neo4jConnectionError("Neo4j ping query did not return expected result.")
    except Neo4jConnectionError:
        raise
    except Exception as exc:
        logger.error("Neo4j connectivity verification failed: %s", type(exc).__name__)
        raise Neo4jConnectionError("Failed to connect to Neo4j.") from None
