import os
import sys
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Make the api/ package (models.*, db.py) importable — same convention as
# agents/learning/ingestor.py.
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
if _API_DIR not in sys.path:
    sys.path.append(_API_DIR)


class DatasetExporter:
    """
    Reads from the unified `fieldpilot` Postgres DB/ORM (models.resolved_incident.
    ResolvedIncident) — previously this connected via raw asyncpg to a separate
    `askthewall` database that no longer exists.
    """

    async def _get_all_incidents(self) -> List[Dict[str, Any]]:
        from db import async_session
        from sqlalchemy import select
        from models.resolved_incident import ResolvedIncident

        async with async_session() as session:
            result = await session.execute(select(ResolvedIncident))
            rows = result.scalars().all()
            return [
                {
                    "incident_id": r.incident_id,
                    "project_id": r.project_id,
                    "zone_id": r.zone_id,
                    "asset_type": r.asset_type,
                    "issue_type": r.issue_type,
                    "measurement_at_detection": r.measurement_at_detection,
                    "spec_value": r.spec_value,
                    "resolution": r.resolution,
                    "photos": r.photos,
                    "outcome_metrics": r.outcome_metrics,
                    "tags": r.tags,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def _generate_resolution_pair(self, row: dict) -> dict:
        resolution = json.loads(row['resolution']) if isinstance(row['resolution'], str) else row['resolution']
        return {
            "export_type": "resolution",
            "messages": [
                {"role": "system", "content": "You are FieldPilot AI Digital Foreman..."},
                {"role": "user", "content": f"{row['asset_type'].capitalize()} {row['issue_type'].replace('_', ' ')} measured {row['measurement_at_detection']}mm in Zone {row['zone_id']}. Spec is {row['spec_value']}mm. What action should be taken?"},
                {"role": "assistant", "content": f"FAIL. Deviation is {row['measurement_at_detection'] - row['spec_value']}mm. Stop work in Zone {row['zone_id']}. {resolution.get('action_taken')}."}
            ]
        }

    def _generate_prediction_pair(self, row: dict) -> dict:
        resolution = json.loads(row['resolution']) if isinstance(row['resolution'], str) else row['resolution']
        return {
            "export_type": "prediction",
            "messages": [
                {"role": "system", "content": "You are FieldPilot AI Digital Foreman..."},
                {"role": "user", "content": f"Zone {row['zone_id']} starting {row['asset_type']} installation. What RFIs should we anticipate?"},
                {"role": "assistant", "content": f"High probability of {row['issue_type'].replace('_', ' ')} based on previous resolved incidents in this zone. {resolution.get('resolution_notes', '')}"}
            ]
        }

    def _generate_memory_pair(self, row: dict) -> dict:
        resolution = json.loads(row['resolution']) if isinstance(row['resolution'], str) else row['resolution']
        return {
            "export_type": "memory",
            "messages": [
                {"role": "system", "content": "You are FieldPilot AI Digital Foreman..."},
                {"role": "user", "content": f"Has Zone {row['zone_id']} had {row['asset_type']} issues before?"},
                {"role": "assistant", "content": f"Yes. Incident {row['incident_id']}: {row['issue_type'].replace('_', ' ')} corrected from {row['measurement_at_detection']}mm to {row['spec_value']}mm. Resolved by {resolution.get('resolved_by')} in {resolution.get('time_to_resolve_hours')} hours. Notes: {resolution.get('resolution_notes')}"}
            ]
        }

    async def export_jsonl(self) -> str:
        incidents = await self._get_all_incidents()
        lines = []
        for inc in incidents:
            lines.append(json.dumps(self._generate_resolution_pair(inc)))
            lines.append(json.dumps(self._generate_prediction_pair(inc)))
            lines.append(json.dumps(self._generate_memory_pair(inc)))

        return "\n".join(lines)

    async def get_stats(self) -> dict:
        incidents = await self._get_all_incidents()

        total = len(incidents)
        by_issue_type = {}
        by_zone = {}
        total_time = 0.0
        rework_prevented = 0
        total_cost_usd = 0
        root_causes = {}

        for inc in incidents:
            # Type counts
            issue = inc['issue_type']
            by_issue_type[issue] = by_issue_type.get(issue, 0) + 1

            # Zone counts
            zone = inc['zone_id']
            by_zone[zone] = by_zone.get(zone, 0) + 1

            # JSON parsing with safety for None values
            res_raw = inc.get('resolution') or "{}"
            out_raw = inc.get('outcome_metrics') or "{}"

            res = json.loads(res_raw) if isinstance(res_raw, str) else res_raw
            out = json.loads(out_raw) if isinstance(out_raw, str) else out_raw

            if not isinstance(res, dict): res = {}
            if not isinstance(out, dict): out = {}

            total_time += float(res.get('time_to_resolve_hours', 0))
            if not res.get('rework_required', True):
                rework_prevented += 1

            total_cost_usd += float(out.get('cost_avoided_usd', out.get('cost_avoided', 0)))

            cause = res.get('resolution_notes', 'unknown').lower()
            if 'formwork' in cause:
                root_causes['formwork_interference'] = root_causes.get('formwork_interference', 0) + 1
            else:
                root_causes['general_deviation'] = root_causes.get('general_deviation', 0) + 1

        avg_time = (total_time / total) if total > 0 else 0
        most_common_cause = max(root_causes.items(), key=lambda x: x[1])[0] if root_causes else "unknown"

        return {
            "total_incidents_learned": total,
            "by_issue_type": by_issue_type,
            "by_zone": by_zone,
            "avg_resolution_time_hours": round(avg_time, 2),
            "rework_prevented_count": rework_prevented,
            "total_cost_avoided_usd": int(total_cost_usd),
            "most_common_root_cause": most_common_cause,
            "dataset_ready_for_export": total > 0,
            "jsonl_pairs_available": total * 3
        }

    async def get_trends(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Daily trend data (incident count + cost avoided) for the last N
        days. Previously a raw asyncpg query with Postgres JSONB operators
        (outcome_metrics->>'cost_avoided_usd') against the now-removed
        askthewall DB; now aggregates in Python over ORM rows, matching
        get_stats()'s existing JSON-parsing approach.
        """
        from datetime import datetime, timedelta, timezone

        incidents = await self._get_all_incidents()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        by_date: Dict[str, Dict[str, float]] = {}
        for inc in incidents:
            created_at = inc.get("created_at")
            if created_at is None or created_at < cutoff:
                continue
            date_key = created_at.strftime("%Y-%m-%d")

            out_raw = inc.get('outcome_metrics') or "{}"
            out = json.loads(out_raw) if isinstance(out_raw, str) else out_raw
            if not isinstance(out, dict):
                out = {}
            cost = float(out.get('cost_avoided_usd', out.get('cost_avoided', 0)))

            bucket = by_date.setdefault(date_key, {"incidents": 0, "cost_avoided": 0.0})
            bucket["incidents"] += 1
            bucket["cost_avoided"] += cost

        return [
            {"date": date, "incidents": int(v["incidents"]), "cost_avoided": v["cost_avoided"]}
            for date, v in sorted(by_date.items())
        ]
