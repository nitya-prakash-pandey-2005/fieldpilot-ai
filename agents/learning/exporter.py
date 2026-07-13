import os
import json
import logging
from typing import List, Dict, Any
import asyncpg

logger = logging.getLogger(__name__)

class DatasetExporter:
    def __init__(self):
        self.pg_uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")

    async def _get_all_incidents(self) -> List[Dict[str, Any]]:
        conn = await asyncpg.connect(self.pg_uri)
        try:
            records = await conn.fetch('SELECT * FROM resolved_incidents')
            return [dict(r) for r in records]
        finally:
            await conn.close()

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
