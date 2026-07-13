import { useState, useRef, useCallback, useEffect } from 'react';

export const useRealtimeUpdates = (projectId: string) => {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<any>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    // Determine WS URL based on environment variables or fallback to localhost
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://127.0.0.1:8000';
    const ws = new WebSocket(`${wsUrl}/ws/twin/${projectId}`);
    
    ws.onopen = () => {
      setConnected(true);
      clearTimeout(reconnectTimer.current);
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLastEvent(data);
      } catch (e) {
        console.error("Invalid WS message format");
      }
    };
    
    ws.onclose = () => {
      setConnected(false);
      // Auto-reconnect every 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000);
    };
    
    ws.onerror = () => ws.close();
    
    wsRef.current = ws;
  }, [projectId]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastEvent };
};
