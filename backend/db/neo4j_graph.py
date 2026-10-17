import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from backend.config import settings

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase, exceptions as neo4j_exc
    HAS_NEO4J_LIB = True
except ImportError:
    HAS_NEO4J_LIB = False
    neo4j_exc = None

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

class Neo4jGraphService:
    def __init__(
        self,
        uri: str = settings.NEO4J_URI,
        user: str = settings.NEO4J_USER,
        password: str = settings.NEO4J_PASSWORD,
        database: str = settings.NEO4J_DATABASE
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self._driver = None
        self._connection_attempted = False
        self._last_error_class: Optional[str] = None
        self._nx_graph = nx.MultiDiGraph() if HAS_NETWORKX else None

    def get_driver(self):
        if not HAS_NEO4J_LIB:
            self._last_error_class = "lib_missing"
            return None
        if self._driver is not None:
            return self._driver
        if self._connection_attempted:
            return None

        self._connection_attempted = True
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                driver.verify_connectivity()
                self._driver = driver
                self._last_error_class = None
                logger.info(f"Connected to Neo4j database at {self.uri}")
                self.init_constraints()
                return self._driver
            except Exception as e:
                err_str = str(e).lower()
                if "unauthorized" in err_str or "authentication" in err_str:
                    self._last_error_class = "auth"
                elif "refused" in err_str or "serviceunavailable" in err_str:
                    self._last_error_class = "refused"
                elif "database" in err_str or "not found" in err_str:
                    self._last_error_class = "wrong_database"
                elif "tls" in err_str or "ssl" in err_str or "certificate" in err_str:
                    self._last_error_class = "tls"
                else:
                    self._last_error_class = "connection_failed"

                if self._last_error_class in ("auth", "wrong_database") or attempt == max_retries:
                    logger.warning(
                        f"Neo4j connection to {self.uri} failed after {attempt} attempts "
                        f"(Cause Class: {self._last_error_class}): {e}. Falling back to in-memory graph."
                    )
                    self._driver = None
                    return None
                time.sleep(0.2)
        return None

    def get_status(self) -> Dict[str, Any]:
        driver = self.get_driver()
        if driver:
            return {
                "active_backend": "Neo4j",
                "uri": self.uri,
                "database": self.database,
                "status": "connected"
            }
        return {
            "active_backend": "In-Memory fallback (NetworkX)",
            "status": "fallback",
            "last_error_cause": self._last_error_class or "unreachable"
        }

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def init_constraints(self):
        """Creates uniqueness constraints and indexes in Neo4j."""
        driver = self.get_driver()
        if not driver:
            return
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (w:Well) REQUIRE w.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (w:Well) REQUIRE w.asset_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Inspection) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Inspection) REQUIRE i.inspection_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Maintenance) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Maintenance) REQUIRE m.maintenance_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RegulatoryEvent) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RegulatoryEvent) REQUIRE r.event_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:ContextNote) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:ContextNote) REQUIRE c.note_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Area) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Area) REQUIRE a.area_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
        ]
        try:
            with driver.session(database=self.database) as session:
                for c in constraints:
                    try:
                        session.run(c)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not initialize Neo4j constraints: {e}")

    def sync_all_entities(
        self,
        areas: List[Dict[str, Any]],
        users: List[Dict[str, Any]],
        wells: List[Dict[str, Any]],
        inspections: List[Dict[str, Any]],
        maintenance: List[Dict[str, Any]],
        regulatory_events: List[Dict[str, Any]],
        context_notes: List[Dict[str, Any]],
        batch_size: int = 1000
    ):
        """
        Idempotent bulk ingest into Neo4j using UNWIND in batches of 1000 with MERGE.
        Maintains an identical in-memory NetworkX graph for seamless offline operation.
        """
        driver = self.get_driver()
        batch_size = 1000

        # Helper to batch slice
        def chunks(lst, n):
            for i in range(0, len(lst), n):
                yield lst[i:i + n]

        if driver:
            try:
                with driver.session(database=self.database) as session:
                    # 1. Areas
                    for batch in chunks(areas, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS a
                            MERGE (area:Area {id: a.area_id})
                            SET area.area_id = a.area_id, area.name = a.name
                            """,
                            batch=batch
                        )

                    # 2. Users
                    for batch in chunks(users, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS u
                            MERGE (user:User {id: u.user_id})
                            SET user.user_id = u.user_id, user.name = u.name, user.role = u.role
                            """,
                            batch=batch
                        )

                    # 3. Wells & Area Containment
                    for batch in chunks(wells, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS w
                            MERGE (well:Well {id: w.asset_id})
                            SET well.asset_id = w.asset_id, well.well_type = w.well_type,
                                well.recorded_status = w.status, well.lat = w.lat, well.lon = w.lon
                            WITH well, w
                            WHERE w.area_id IS NOT NULL
                            MERGE (area:Area {id: w.area_id})
                            MERGE (area)-[:CONTAINS]->(well)
                            """,
                            batch=batch
                        )

                    # 4. Inspections & Relations
                    for batch in chunks(inspections, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS i
                            MERGE (ins:Inspection {id: i.inspection_id})
                            SET ins.inspection_id = i.inspection_id, ins.inspected_at = i.inspected_at,
                                ins.method = i.method, ins.spill_detected = i.spill_detected,
                                ins.temp_delta_c = i.temp_delta_c
                            WITH ins, i
                            MERGE (well:Well {id: i.asset_id})
                            MERGE (well)-[:HAS_INSPECTION]->(ins)
                            """,
                            batch=batch
                        )

                    # 5. Maintenance & Reports
                    for batch in chunks(maintenance, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS m
                            MERGE (mnt:Maintenance {id: m.maintenance_id})
                            SET mnt.maintenance_id = m.maintenance_id, mnt.started_at = m.started_at,
                                mnt.equipment_kind = m.equipment_kind, mnt.cost_total_usd = m.cost_total_usd,
                                mnt.issue = m.issue
                            WITH mnt, m
                            MERGE (well:Well {id: m.asset_id})
                            MERGE (well)-[:HAS_MAINTENANCE]->(mnt)
                            WITH mnt, m
                            WHERE m.report_file IS NOT NULL AND m.report_file <> ''
                            MERGE (rep:Report {id: m.report_file})
                            SET rep.file = m.report_file
                            MERGE (mnt)-[:HAS_REPORT]->(rep)
                            """,
                            batch=batch
                        )

                    # 6. Regulatory Events
                    for batch in chunks(regulatory_events, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS r
                            MERGE (reg:RegulatoryEvent {id: r.event_id})
                            SET reg.event_id = r.event_id, reg.event_date = r.event_date,
                                reg.protocol_id = r.protocol_id, reg.agency = r.agency,
                                reg.fine_usd = r.fine_usd
                            WITH reg, r
                            MERGE (well:Well {id: r.asset_id})
                            MERGE (well)-[:HAS_REGULATORY_EVENT]->(reg)
                            """,
                            batch=batch
                        )

                    # 7. Context Notes & Corrections
                    for batch in chunks(context_notes, batch_size):
                        session.run(
                            """
                            UNWIND $batch AS c
                            MERGE (note:ContextNote {id: c.note_id})
                            SET note.note_id = c.note_id, note.created_at = c.created_at,
                                note.note_type = c.note_type, note.text = c.text
                            WITH note, c
                            MERGE (well:Well {id: c.asset_id})
                            MERGE (well)-[:HAS_NOTE]->(note)
                            WITH note, c
                            WHERE c.inspection_id IS NOT NULL AND c.inspection_id <> ''
                            MERGE (ins:Inspection {id: c.inspection_id})
                            MERGE (note)-[:CORRECTS]->(ins)
                            """,
                            batch=batch
                        )
            except Exception as e:
                logger.warning(f"Error executing Neo4j batch sync: {e}")

        # Sync in-memory NetworkX graph
        if self._nx_graph is not None:
            for a in areas:
                self._nx_graph.add_node(a["area_id"], type="Area", name=a.get("name"))
            for u in users:
                self._nx_graph.add_node(u["user_id"], type="User", name=u.get("name"), role=u.get("role"))
            for w in wells:
                self._nx_graph.add_node(w["asset_id"], type="Well", well_type=w.get("well_type"), status=w.get("status"))
                if w.get("area_id"):
                    self._nx_graph.add_edge(w["area_id"], w["asset_id"], relation="CONTAINS")
            for i in inspections:
                self._nx_graph.add_node(i["inspection_id"], type="Inspection", inspected_at=i.get("inspected_at"))
                self._nx_graph.add_edge(i["asset_id"], i["inspection_id"], relation="HAS_INSPECTION")
            for m in maintenance:
                self._nx_graph.add_node(m["maintenance_id"], type="Maintenance", equipment=m.get("equipment_kind"))
                self._nx_graph.add_edge(m["asset_id"], m["maintenance_id"], relation="HAS_MAINTENANCE")
                if m.get("report_file"):
                    self._nx_graph.add_node(m["report_file"], type="Report")
                    self._nx_graph.add_edge(m["maintenance_id"], m["report_file"], relation="HAS_REPORT")
            for r in regulatory_events:
                self._nx_graph.add_node(r["event_id"], type="RegulatoryEvent", protocol=r.get("protocol_id"))
                self._nx_graph.add_edge(r["asset_id"], r["event_id"], relation="HAS_REGULATORY_EVENT")
            for c in context_notes:
                self._nx_graph.add_node(c["note_id"], type="ContextNote", note_type=c.get("note_type"))
                self._nx_graph.add_edge(c["asset_id"], c["note_id"], relation="HAS_NOTE")
                if c.get("inspection_id"):
                    self._nx_graph.add_edge(c["note_id"], c["inspection_id"], relation="CORRECTS")

    def _ensure_graph_populated(self):
        if self._nx_graph is not None and len(self._nx_graph) == 0:
            try:
                from backend.ingest.celery_worker import sync_all_entities_to_graph
                sync_all_entities_to_graph()
            except Exception as e:
                logger.warning(f"Could not lazily populate graph: {e}")

    def get_neighborhood(self, asset_id: str, depth: int = 1) -> Dict[str, Any]:
        """
        Returns sub-graph neighborhood (nodes and edges) for a given asset_id up to specified depth.
        Works across both Neo4j and in-memory NetworkX fallback.
        """
        driver = self.get_driver()
        if not driver:
            self._ensure_graph_populated()
        if driver:
            try:
                with driver.session(database=self.database) as session:
                    res = session.run(
                        """
                        MATCH path = (root {id: $asset_id})-[r*1..2]-(target)
                        UNWIND nodes(path) AS n
                        UNWIND relationships(path) AS rel
                        RETURN DISTINCT
                            labels(n)[0] AS node_label, n.id AS node_id, properties(n) AS node_props,
                            startNode(rel).id AS edge_src, endNode(rel).id AS edge_tgt, type(rel) AS edge_rel
                        """,
                        asset_id=asset_id
                    )
                    nodes_dict = {}
                    edges_set = set()
                    for rec in res:
                        nid = rec["node_id"]
                        if nid and nid not in nodes_dict:
                            nodes_dict[nid] = {
                                "id": nid,
                                "label": rec["node_label"] or "Entity",
                                "properties": {k: v for k, v in (rec["node_props"] or {}).items() if k != "id"}
                            }
                        if rec["edge_src"] and rec["edge_tgt"]:
                            edges_set.add((rec["edge_src"], rec["edge_tgt"], rec["edge_rel"]))

                    return {
                        "root_id": asset_id,
                        "nodes": list(nodes_dict.values()),
                        "edges": [{"source": s, "target": t, "relation": r} for s, t, r in edges_set]
                    }
            except Exception as e:
                logger.warning(f"Neo4j neighborhood query failed: {e}")

        # In-memory NetworkX neighborhood traversal
        if self._nx_graph is not None and asset_id in self._nx_graph:
            sub_nodes = {asset_id}
            frontier = {asset_id}
            for _ in range(depth):
                next_f = set()
                for n in frontier:
                    next_f.update(self._nx_graph.neighbors(n))
                    next_f.update(self._nx_graph.predecessors(n) if hasattr(self._nx_graph, "predecessors") else [])
                sub_nodes.update(next_f)
                frontier = next_f

            nodes = []
            for n in sub_nodes:
                ndata = self._nx_graph.nodes[n]
                nodes.append({
                    "id": n,
                    "label": ndata.get("type", "Entity"),
                    "properties": {k: v for k, v in ndata.items() if k != "type"}
                })

            edges = []
            for u in sub_nodes:
                for v in self._nx_graph.successors(u) if hasattr(self._nx_graph, "successors") else self._nx_graph.neighbors(u):
                    if v in sub_nodes:
                        edge_data = self._nx_graph.get_edge_data(u, v, 0) or {}
                        edges.append({
                            "source": u,
                            "target": v,
                            "relation": edge_data.get("relation", "CONNECTED_TO")
                        })

            return {"root_id": asset_id, "nodes": nodes, "edges": edges}

        return {"root_id": asset_id, "nodes": [], "edges": []}

    def get_label_counts(self) -> Dict[str, int]:
        """Returns node count per label: MATCH (n) RETURN labels(n), count(*)"""
        driver = self.get_driver()
        if driver:
            try:
                with driver.session(database=self.database) as session:
                    res = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count")
                    return {record["label"]: record["count"] for record in res if record["label"]}
            except Exception:
                pass

        self._ensure_graph_populated()
        if self._nx_graph is not None:
            counts: Dict[str, int] = {}
            for n in self._nx_graph.nodes:
                lbl = self._nx_graph.nodes[n].get("type", "Unknown")
                counts[lbl] = counts.get(lbl, 0) + 1
            return counts
        return {}

    def get_relationship_counts(self) -> Dict[str, int]:
        """Returns relationship count per type."""
        driver = self.get_driver()
        if driver:
            try:
                with driver.session(database=self.database) as session:
                    res = session.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS count")
                    return {record["rel"]: record["count"] for record in res if record["rel"]}
            except Exception:
                pass

        self._ensure_graph_populated()

        if self._nx_graph is not None:
            counts: Dict[str, int] = {}
            for u, v, k, d in self._nx_graph.edges(data=True, keys=True):
                r = d.get("relation", "CONNECTED_TO")
                counts[r] = counts.get(r, 0) + 1
            return counts
        return {}

    def verify_consistency(self, sql_counts: Dict[str, int]) -> Dict[str, Any]:
        """
        Consistency check: counts in SQL vs Neo4j/In-memory per entity type must match.
        Logs mismatches as errors.
        """
        graph_counts = self.get_label_counts()
        label_map = {
            "wells": "Well",
            "inspections": "Inspection",
            "maintenance": "Maintenance",
            "regulatory_events": "RegulatoryEvent",
            "context_notes": "ContextNote",
            "areas": "Area",
            "users": "User"
        }
        mismatches = []
        for table, label in label_map.items():
            sql_c = sql_counts.get(table, 0)
            graph_c = graph_counts.get(label, 0)
            if sql_c != graph_c:
                msg = f"Consistency Mismatch: {table} has {sql_c} rows in SQL but {graph_c} {label} nodes in Graph."
                logger.error(msg)
                mismatches.append(msg)

        return {
            "consistent": len(mismatches) == 0,
            "sql_counts": sql_counts,
            "graph_counts": graph_counts,
            "mismatches": mismatches
        }

graph_service = Neo4jGraphService()
