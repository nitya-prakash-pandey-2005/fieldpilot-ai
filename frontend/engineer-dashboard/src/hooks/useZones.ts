import { useState, useEffect } from 'react';

export type RiskLevel = 'critical' | 'elevated' | 'normal';

export const getRiskLevel = (score: number): RiskLevel => {
  if (score >= 70) return 'critical';
  if (score >= 40) return 'elevated';
  return 'normal';
};

export interface Zone {
  id: string;
  zone_code: string;
  name: string;
  current_activity: string;
  risk_level: RiskLevel;
  risk_score: number;
  active_worker_count: number;
  open_issue_count: number;
  last_scored_at: string;
}

export interface ZoneSummary {
  critical_count: number;
  total_workers: number;
  total_open_issues: number;
  last_updated: string;
}

export function useZones(projectId: string = "default-project") {
  const [zones, setZones] = useState<Zone[]>([]);
  const [summary, setSummary] = useState<ZoneSummary | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<'live' | 'demo' | 'offline'>('offline');
  
  useEffect(() => {
    const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    
    // Initial fetch
    const fetchZones = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${BASE}/api/v1/projects/${projectId}/zones`);
        if (!res.ok) throw new Error("Failed to fetch zones");
        
        const data = await res.json();
        
        const RISK_ORDER = { critical: 0, elevated: 1, normal: 2 };
        const sortedZones = [...data.zones].sort((a, b) => {
          const levelDiff = RISK_ORDER[getRiskLevel(a.risk_score)] - RISK_ORDER[getRiskLevel(b.risk_score)];
          if (levelDiff !== 0) return levelDiff;
          return b.risk_score - a.risk_score;
        });
        
        setZones(sortedZones);
        setSummary(data.summary);
        setLastUpdated(new Date());
        setError(null);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    
    fetchZones();
    
    // SSE for live updates
    const es = new EventSource(`${BASE}/api/v1/projects/${projectId}/zones/stream`);
    
    es.onopen = () => setConnectionStatus('live');
    
    es.onmessage = (e) => {
      try {
        const updated = JSON.parse(e.data);
        
        setZones(prev => {
          const newZones = prev.map(z => 
            z.id === updated.id ? { ...z, ...updated } : z
          );
          
          const RISK_ORDER = { critical: 0, elevated: 1, normal: 2 };
          return newZones.sort((a, b) => {
            const levelDiff = RISK_ORDER[getRiskLevel(a.risk_score)] - RISK_ORDER[getRiskLevel(b.risk_score)];
            if (levelDiff !== 0) return levelDiff;
            return b.risk_score - a.risk_score;
          });
        });
        
        setLastUpdated(new Date());
      } catch (err) {
        console.error("Error parsing SSE data", err);
      }
    };
    
    es.onerror = () => {
      setConnectionStatus('offline');
      console.warn("SSE connection lost. Reconnecting...");
    };
    
    return () => {
      es.close();
    };
  }, [projectId]);
  
  return { zones, summary, lastUpdated, loading, error, connectionStatus };
}
