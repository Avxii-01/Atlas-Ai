"""Deterministic Neo4j connectivity verification utility for Atlas AI P0-01."""

import os
import sys
import logging
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("neo4j_verify")


def verify_connection() -> bool:
    """Verify connectivity to Neo4j using environment variables."""
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    logger.info(f"Connecting to Neo4j at {uri} as user '{username}'...")

    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 AS ping").single()
            if result and result["ping"] == 1:
                logger.info(f"Successfully connected to Neo4j at {uri}. Ping returned 1.")
                return True
        raise RuntimeError("Neo4j ping query did not return expected result.")
    except Exception as exc:
        logger.error(f"Failed to connect to Neo4j at {uri}: {exc}")
        raise
    finally:
        if driver is not None:
            driver.close()


if __name__ == "__main__":
    try:
        verify_connection()
        print("Neo4j connectivity check passed.")
        sys.exit(0)
    except Exception as err:
        print(f"Neo4j connectivity check failed: {err}", file=sys.stderr)
        sys.exit(1)
