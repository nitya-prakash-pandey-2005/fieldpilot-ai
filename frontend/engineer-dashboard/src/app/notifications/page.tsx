"use client";
import { Bell, AlertTriangle, Info, Settings, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { mockNotifications } from '@/data/mockData';
import { useState } from 'react';

export default function NotificationsPage() { 
  const [notifications, setNotifications] = useState(mockNotifications);

  const markAllRead = () => {
    setNotifications(prev => prev.map(n => ({...n, read: true})));
    toast.success("All notifications marked as read.");
  };

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Bell className="text-white/80" size={32} />
            Notifications
          </h1>
          <p className="text-white/50 mt-2">Agent 9 routing layer for alerts, incidents, and tasks.</p>
        </div>
        
        <div className="flex gap-4">
          <button 
            className="bg-black/20 hover:bg-black/40 text-white/70 border border-white/10 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer"
            onClick={markAllRead}
          >
            <CheckCircle2 size={16} /> Mark All Read
          </button>
          <button 
            className="bg-black/20 hover:bg-black/40 text-white/70 border border-white/10 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer"
            onClick={() => toast('Routing settings opened.')}
          >
            <Settings size={16} /> Routing Rules
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-4xl flex flex-col gap-3 pb-10">
          {notifications.map((notif) => (
            <div 
              key={notif.id} 
              className={`p-5 rounded-xl border transition-all ${
                notif.read ? 'bg-black/20 border-white/5 opacity-70' : 'bg-[#12121A] border-white/10 shadow-lg shadow-black/50'
              } flex gap-4`}
            >
              <div className="mt-1">
                {notif.severity === 'CRITICAL' ? (
                  <div className="w-10 h-10 rounded-full bg-atw-red/20 flex items-center justify-center border border-atw-red/30">
                    <AlertTriangle size={18} className="text-atw-red" />
                  </div>
                ) : notif.severity === 'HIGH' ? (
                  <div className="w-10 h-10 rounded-full bg-orange-500/20 flex items-center justify-center border border-orange-500/30">
                    <AlertTriangle size={18} className="text-orange-500" />
                  </div>
                ) : notif.severity === 'INFO' ? (
                  <div className="w-10 h-10 rounded-full bg-atw-cyan/20 flex items-center justify-center border border-atw-cyan/30">
                    <Info size={18} className="text-atw-cyan" />
                  </div>
                ) : (
                  <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center border border-white/10">
                    <CheckCircle2 size={18} className="text-white/60" />
                  </div>
                )}
              </div>
              
              <div className="flex-1">
                <div className="flex justify-between items-start mb-1">
                  <h3 className={`font-semibold text-lg ${notif.read ? 'text-white/60' : 'text-white'}`}>{notif.title}</h3>
                  <span className="text-xs text-white/40">{notif.time}</span>
                </div>
                <p className={`text-sm ${notif.read ? 'text-white/40' : 'text-white/70'}`}>{notif.message}</p>
                
                {!notif.read && (
                  <div className="mt-4 flex gap-3">
                    <button 
                      onClick={() => {
                        setNotifications(prev => prev.map(n => n.id === notif.id ? {...n, read: true} : n));
                        toast.success('Action acknowledged.');
                      }}
                      className="bg-white/10 hover:bg-white/20 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors cursor-pointer"
                    >
                      Acknowledge
                    </button>
                    {notif.severity === 'CRITICAL' && (
                      <button 
                        onClick={() => toast('Opening incident report...')}
                        className="bg-atw-red/20 hover:bg-atw-red/30 text-atw-red border border-atw-red/30 text-xs font-semibold px-4 py-2 rounded-lg transition-colors cursor-pointer"
                      >
                        View Details
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  ); 
}