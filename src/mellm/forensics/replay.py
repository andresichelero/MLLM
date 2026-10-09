"""DuckDB analytical replay engine for the 2026 Hugging Face agent incident.

Analyzes 189,579 records from `redacted.jsonl.gz`:
- Micro-actions, payloads, and responses
- Controller markers (G236 and OTS92)
- Multi-phase kill chains (CyberGym escape, Artifactory proxy, credential extraction)
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any
import duckdb


@dataclass
class IncidentSummary:
    """Aggregated statistics of the incident dataset."""
    total_records: int
    kind_counts: dict[str, int]
    records_with_parent: int
    controller_counts: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "kind_counts": self.kind_counts,
            "records_with_parent": self.records_with_parent,
            "controller_counts": self.controller_counts,
            "metadata": self.metadata,
        }


class IncidentReplayEngine:
    """Forensic ingestion and analytical query engine using DuckDB."""

    DEFAULT_DATA_PATH = "redacted.jsonl.gz"

    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = data_path or self.DEFAULT_DATA_PATH
        # Resolve path if relative
        if not os.path.isabs(self.data_path) and not os.path.exists(self.data_path):
            # Check current working directory or MeLLM root
            cand = os.path.join(os.getcwd(), self.data_path)
            if os.path.exists(cand):
                self.data_path = cand

        self._con = duckdb.connect(":memory:")
        self._initialized = False
        self._initialize_views()

    def _initialize_views(self) -> None:
        """Configures DuckDB views over the JSONL dataset if file exists."""
        if not os.path.exists(self.data_path):
            # Create empty table schema if data file is absent (e.g. isolated test environments)
            self._con.execute("""
                CREATE TABLE incident_events (
                    id VARCHAR,
                    cite VARCHAR,
                    kind VARCHAR,
                    parent_id VARCHAR,
                    time_utc VARCHAR,
                    tags VARCHAR,
                    text VARCHAR
                )
            """)
            self._initialized = True
            return

        normalized_path = self.data_path.replace("\\", "/")
        query = f"""
            CREATE VIEW incident_events AS
            SELECT
                id,
                cite,
                kind,
                CAST(parent_id AS VARCHAR) AS parent_id,
                CAST(time_utc AS VARCHAR) AS time_utc,
                tags,
                text
            FROM read_json_auto(
                '{normalized_path}',
                columns={{
                    'id': 'VARCHAR',
                    'cite': 'VARCHAR',
                    'kind': 'VARCHAR',
                    'parent_id': 'VARCHAR',
                    'time_utc': 'VARCHAR',
                    'tags': 'VARCHAR',
                    'text': 'VARCHAR'
                }}
            )
        """
        self._con.execute(query)
        self._initialized = True

    def get_summary(self) -> IncidentSummary:
        """Returns aggregated summary metrics across the dataset."""
        # Total records
        total_res = self._con.execute("SELECT count(*) FROM incident_events").fetchone()
        total_records = total_res[0] if total_res else 0

        if total_records == 0:
            return IncidentSummary(
                total_records=0,
                kind_counts={},
                records_with_parent=0,
                controller_counts={"G236": 0, "OTS92": 0},
            )

        # Kind distribution
        kind_rows = self._con.execute(
            "SELECT kind, count(*) FROM incident_events GROUP BY kind"
        ).fetchall()
        kind_counts = {row[0]: row[1] for row in kind_rows if row[0] is not None}

        # Parent count
        parent_res = self._con.execute(
            "SELECT count(*) FROM incident_events WHERE parent_id IS NOT NULL AND parent_id != ''"
        ).fetchone()
        records_with_parent = parent_res[0] if parent_res else 0

        # Controllers
        g236_res = self._con.execute(
            "SELECT count(*) FROM incident_events WHERE text LIKE '%G236%' OR tags LIKE '%G236%'"
        ).fetchone()
        ots92_res = self._con.execute(
            "SELECT count(*) FROM incident_events WHERE text LIKE '%OTS92%' OR tags LIKE '%OTS92%'"
        ).fetchone()

        controller_counts = {
            "G236": g236_res[0] if g236_res else 0,
            "OTS92": ots92_res[0] if ots92_res else 0,
        }

        return IncidentSummary(
            total_records=total_records,
            kind_counts=kind_counts,
            records_with_parent=records_with_parent,
            controller_counts=controller_counts,
            metadata={"data_path": self.data_path},
        )

    def _clean_records(self, df) -> list[dict[str, Any]]:
        """Converts dataframe rows to dictionaries with NaN converted to None for JSON compliance."""
        df = df.where(df.notnull(), None)
        records = df.to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                if isinstance(v, float) and math.isnan(v):
                    r[k] = None
        return records

    def query_controllers(self) -> list[dict[str, Any]]:
        """Queries all incident events referencing controllers G236 or OTS92."""
        query = """
            SELECT
                id,
                cite,
                kind,
                parent_id,
                time_utc,
                tags,
                text,
                CASE
                    WHEN text LIKE '%G236%' THEN 'G236'
                    WHEN text LIKE '%OTS92%' THEN 'OTS92'
                    ELSE 'UNKNOWN'
                END AS controller_tag
            FROM incident_events
            WHERE text LIKE '%G236%' OR text LIKE '%OTS92%' OR tags LIKE '%G236%' OR tags LIKE '%OTS92%'
            ORDER BY id ASC
        """
        df = self._con.execute(query).df()
        return self._clean_records(df)

    def query_by_parent(self, parent_id: str) -> list[dict[str, Any]]:
        """Retrieves child response/payload events for a specific parent_id."""
        query = "SELECT * FROM incident_events WHERE parent_id = ? ORDER BY id ASC"
        df = self._con.execute(query, [parent_id]).df()
        return self._clean_records(df)

    def query_attack_phases(self, limit_per_phase: int = 10) -> dict[str, list[dict[str, Any]]]:
        """Categorizes actions into the four empirical incident phases."""
        phases = {
            "phase1_cybergym_escape": """
                SELECT id, kind, text FROM incident_events
                WHERE text LIKE '%sqlite3_initialize%' OR text LIKE '%/proc/1/status%' OR text LIKE '%uname -a%'
                LIMIT ?
            """,
            "phase2_artifactory_proxy": """
                SELECT id, kind, text FROM incident_events
                WHERE text LIKE '%artifactory%' OR text LIKE '%MKCOL%' OR text LIKE '%zzMODAL%'
                LIMIT ?
            """,
            "phase3_credential_harvesting": """
                SELECT id, kind, text FROM incident_events
                WHERE text LIKE '%[CREDENTIAL%' OR text LIKE '%tailscale%' OR text LIKE '%k8s%'
                LIMIT ?
            """,
            "phase4_metagaming_c2": """
                SELECT id, kind, text FROM incident_events
                WHERE text LIKE '%HELLO_OTS92%' OR text LIKE '%TINYOK%' OR text LIKE '%flag%'
                LIMIT ?
            """,
        }

        results: dict[str, list[dict[str, Any]]] = {}
        for phase_name, sql in phases.items():
            df = self._con.execute(sql, [limit_per_phase]).df()
            results[phase_name] = self._clean_records(df)

        return results

    def search_text(self, pattern: str, limit: int = 50) -> list[dict[str, Any]]:
        """Searches records containing text substring."""
        query = "SELECT * FROM incident_events WHERE text LIKE ? LIMIT ?"
        df = self._con.execute(query, [f"%{pattern}%", limit]).df()
        return self._clean_records(df)

    def sql(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        """Executes custom SQL query against incident_events."""
        if params:
            df = self._con.execute(query, params).df()
        else:
            df = self._con.execute(query).df()
        return self._clean_records(df)
