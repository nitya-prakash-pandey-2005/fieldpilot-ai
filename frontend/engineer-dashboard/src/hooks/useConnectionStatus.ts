import { useState, useEffect } from 'react';

import { apiBase } from '@/lib/api';
export function useConnectionStatus() {
  const [status, setStatus] = useState<'live' | 'demo' | 'offline'>('offline');

  useEffect(() => {
    const BASE = apiBase();
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
