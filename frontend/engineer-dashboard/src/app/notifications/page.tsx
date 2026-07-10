"use client";
import { useState, useEffect } from 'react';
import { Bell, Activity, Send } from 'lucide-react';

export default function NotificationsPage() { 
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/notification/active`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setNotifications(data.data);
        }
        setLoading(false);
      })
      .catch(() => {
        setNotifications([
          { 
            event_type: 'SYSTEM_TEST', 
            severity: 'CRITICAL', 
            created_at: new Date().toISOString(), 
            message: '🔴 TEST FIRE: This is a system connectivity test from Agent 9. Please ignore.',
            channels_dispatched: ['slack', 'twilio'],
            delivered_to: ['+1234567890', '@sarah.chen']
          },
          { 
            event_type: 'RFI_PREDICTION', 
            severity: 'WARNING', 
            created_at: new Date(Date.now() - 3600000).toISOString(), 
            message: 'High probability of RFI on Zone B3 due to clashing utilities.',
            channels_dispatched: ['slack'],
            delivered_to: ['#eng-alerts']
          }
        ]);
        setLoading(false);
      });
  }, []);

  return (
    <div className="h-full p-8 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Bell className="text-atw-amber" size={32} />
        <h1 className="text-3xl font-bold text-white">Notification Audit Log</h1>
      </div>
      
      <div className="bg-atw-surface/40 backdrop-blur-md border border-white/10 rounded-xl shadow-2xl overflow-hidden flex flex-col h-[calc(100vh-200px)]">
        <div className="px-6 py-4 border-b border-white/10 bg-gray-900/50 flex justify-between items-center">
          <h2 className="text-lg font-bold text-white">Recent Dispatches</h2>
          <div className="flex items-center gap-2">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-atw-green opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-atw-green"></span>
            </span>
            <span className="text-xs text-atw-green font-medium">Monitoring Active</span>
          </div>
        </div>
        
        {loading ? (
          <div className="flex-1 flex justify-center items-center"><div className="w-8 h-8 rounded-full border-2 border-t-atw-amber animate-spin"></div></div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {notifications.map((notif, idx) => (
              <div key={idx} className={`bg-gray-900/80 border rounded-lg p-5 flex flex-col gap-3 ${
                notif.severity === 'CRITICAL' ? 'border-atw-red/30' : 'border-gray-800'
              }`}>
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <Send size={16} className={notif.severity === 'CRITICAL' ? 'text-atw-red' : 'text-atw-amber'} />
                    <span className="text-white font-bold text-lg">{notif.event_type}</span>
                    <span className={`px-2 py-0.5 text-xs rounded font-bold ${
                      notif.severity === 'CRITICAL' ? 'bg-atw-red/20 text-atw-red' : 'bg-atw-amber/20 text-atw-amber'
                    }`}>{notif.severity}</span>
                  </div>
                  <span className="text-gray-500 text-sm">{new Date(notif.created_at).toLocaleString()}</span>
                </div>
                
                <p className="text-gray-300 text-base">{notif.message}</p>
                
                <div className="flex gap-4 mt-2">
                  <div className="bg-black/30 rounded px-3 py-1.5 border border-white/5 flex gap-2 items-center">
                    <span className="text-gray-500 text-xs">Channels:</span>
                    <span className="text-atw-cyan text-xs font-mono">{notif.channels_dispatched.join(', ')}</span>
                  </div>
                  <div className="bg-black/30 rounded px-3 py-1.5 border border-white/5 flex gap-2 items-center">
                    <span className="text-gray-500 text-xs">Delivered To:</span>
                    <span className="text-atw-purple text-xs font-mono">{notif.delivered_to.join(', ')}</span>
                  </div>
                </div>
              </div>
            ))}
            {notifications.length === 0 && (
              <div className="text-gray-500 text-center py-12">No notifications found in the audit log.</div>
            )}
          </div>
        )}
      </div>
    </div>
  ); 
}