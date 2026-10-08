"""Atlas AI - Backend Service Placeholder (P0-01).

This minimal application serves as the foundation placeholder for P0-01,
verifying that the backend container starts and connects to Neo4j.
"""

from contextlib import asynccontextmanager
import logging
import os
from fastapi import FastAPI
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("atlas_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler verifying Neo4j connectivity at container startup."""
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    logger.info(f"Verifying Neo4j connectivity to {uri}...")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 AS ping").single()
            if result and result["ping"] == 1:
                logger.info(f"Neo4j connectivity verified successfully at {uri}.")
        app.state.neo4j_driver = driver
    except Exception as exc:
        logger.error(f"Failed to connect to Neo4j at {uri}: {exc}")
        driver.close()
        raise

    yield

    logger.info("Closing Neo4j connection driver...")
    driver.close()


app = FastAPI(
    title="Atlas AI Backend Placeholder",
    description="Minimal FastAPI placeholder for P0-01 foundation verification",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def read_root():
    """Placeholder root endpoint."""
    return {
        "status": "online",
        "service": "atlas-ai-backend",
        "database": "neo4j-connected",
    }
