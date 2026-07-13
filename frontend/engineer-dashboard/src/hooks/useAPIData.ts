import { useState, useEffect } from 'react';

export const useAPIData = (endpoint: string, fallback: any, options = {}) => {
  const [data, setData] = useState(fallback);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(false);
  
  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL || "";
    fetch(`${API}${endpoint}`, options)
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setData(d); setIsLive(true); setLoading(false); })
      .catch(() => { setIsLive(false); setLoading(false); });
  }, [endpoint]);
  
  return { data, loading, isLive };
};
