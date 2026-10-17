import logging
from typing import Dict, Any, List, Optional
from backend.config import settings

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
    HAS_NEO4J_LIB = True
except ImportError:
    HAS_NEO4J_LIB = False

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

class Neo4jGraphService:
    def __init__(self, uri: str = settings.NEO4J_URI, user: str = settings.NEO4J_USER, password: str = settings.NEO4J_PASSWORD):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None
        self._nx_graph = nx.MultiDiGraph() if HAS_NETWORKX else None

    def get_driver(self):
        if not HAS_NEO4J_LIB:
            return None
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                # verify connectivity
                self._driver.verify_connectivity()
            except Exception as e:
                logger.warning(f"Neo4j connection not available: {e}. Falling back to in-memory graph.")
                self._driver = None
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()

    def sync_nodes_and_edges(self, wells: List[Dict[str, Any]], areas: List[Dict[str, Any]]):
        """Populates Neo4j if reachable, and keeps in-memory graph synchronized."""
        driver = self.get_driver()
        if driver:
            try:
                with driver.session() as session:
                    session.run(
                        """
                        UNWIND $wells AS w
                        MERGE (well:Well {id: w.asset_id})
                        SET well.well_type = w.well_type, well.recorded_status = w.status
                        MERGE (area:Area {id: w.area_id})
                        MERGE (area)-[:CONTAINS]->(well)
                        """,
                        wells=wells
                    )
            except Exception as e:
                logger.warning(f"Failed to sync to Neo4j: {e}")

        # Sync in-memory NetworkX graph
        if self._nx_graph is not None:
            for a in areas:
                self._nx_graph.add_node(a["area_id"], type="Area", name=a.get("name"))
            for w in wells:
                self._nx_graph.add_node(w["asset_id"], type="Well", well_type=w.get("well_type"), status=w.get("status"))
                if w.get("area_id"):
                    self._nx_graph.add_edge(w["area_id"], w["asset_id"], relation="CONTAINS")

    def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        """Returns 1-hop connected entities and relation types."""
        driver = self.get_driver()
        if driver:
            try:
                with driver.session() as session:
                    res = session.run(
                        """
                        MATCH (n {id: $node_id})-[r]-(m)
                        RETURN labels(m)[0] AS label, m.id AS id, type(r) AS relation
                        """,
                        node_id=node_id
                    )
                    return [{"label": record["label"], "id": record["id"], "relation": record["relation"]} for record in res]
            except Exception:
                pass
        
        if self._nx_graph is not None and node_id in self._nx_graph:
            results = []
            for neighbor in self._nx_graph.neighbors(node_id):
                edge_data = self._nx_graph.get_edge_data(node_id, neighbor, 0) or {}
                node_data = self._nx_graph.nodes[neighbor]
                results.append({
                    "label": node_data.get("type", "Unknown"),
                    "id": neighbor,
                    "relation": edge_data.get("relation", "CONNECTED_TO")
                })
            return results
        return []

graph_service = Neo4jGraphService()
