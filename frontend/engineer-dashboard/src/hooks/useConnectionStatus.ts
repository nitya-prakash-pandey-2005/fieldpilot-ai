import { useState, useEffect } from 'react';

export function useConnectionStatus() {
  const [status, setStatus] = useState<'live' | 'demo' | 'offline'>('offline');

  useEffect(() => {
    const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const es = new EventSource(`${BASE}/api/v1/projects/default-project/zones/stream`);
    
    es.onopen = () => setStatus('live');
    
    es.onerror = () => {
      setStatus('offline');
    };
    
    return () => {
      es.close();
    };
  }, []);

  return { status };
}
