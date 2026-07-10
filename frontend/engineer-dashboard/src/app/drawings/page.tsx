"use client";
import { useState, useEffect } from 'react';
import { FileBox, History, GitCommit } from 'lucide-react';

export default function DrawingsPage() { 
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/version-control/history/S-101`)
      .then(res => res.json())
      .then(data => {
        if (data.history) {
          setHistory(data.history);
        }
        setLoading(false);
      })
      .catch(() => {
        setHistory([
          { version: 3, state: 'Rebar Installed', timestamp: '2026-07-10T11:30:00Z' },
          { version: 2, state: 'Formwork Installed', timestamp: '2026-07-09T10:00:00Z' },
          { version: 1, state: 'Initial Design', timestamp: '2026-07-01T08:00:00Z' }
        ]);
        setLoading(false);
      });
  }, []);

  return (
    <div className="h-full p-8 max-w-4xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <FileBox className="text-atw-cyan" size={32} />
        <h1 className="text-3xl font-bold text-white">Drawing Version Control</h1>
      </div>
      
      <div className="bg-atw-surface/40 backdrop-blur-md border border-white/10 rounded-xl p-6 shadow-2xl">
        <h2 className="text-xl font-bold text-white mb-6 border-b border-white/10 pb-4">Asset History: S-101</h2>
        
        {loading ? (
          <div className="flex justify-center py-12"><div className="w-8 h-8 rounded-full border-2 border-t-atw-cyan animate-spin"></div></div>
        ) : (
          <div className="space-y-6">
            {history.map((record, idx) => (
              <div key={idx} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="w-8 h-8 rounded-full bg-atw-cyan/20 border border-atw-cyan flex items-center justify-center">
                    <GitCommit size={16} className="text-atw-cyan" />
                  </div>
                  {idx !== history.length - 1 && <div className="w-px h-12 bg-gray-700 mt-2"></div>}
                </div>
                
                <div className="flex-1 bg-gray-900/50 border border-gray-800 rounded-lg p-4">
                  <div className="flex justify-between mb-2">
                    <span className="text-white font-bold">Version {record.version}</span>
                    <span className="text-gray-400 text-sm">{new Date(record.timestamp).toLocaleString()}</span>
                  </div>
                  <p className="text-gray-300">State transition: <span className="text-atw-cyan">{record.state}</span></p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  ); 
}