"use client";
import { useState, useEffect } from 'react';
import { Network, Database } from 'lucide-react';

export default function GraphPage() { 
  const [nodes, setNodes] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/graph/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: "MATCH (n) RETURN n LIMIT 15", parameters: {} })
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setNodes(data.data.map((r: any) => r.n));
        }
        setLoading(false);
      })
      .catch(() => {
        setNodes([
          { elementId: '1', labels: ['Zone'], properties: { id: 'A12', name: 'Zone A12' } },
          { elementId: '2', labels: ['Asset'], properties: { id: 'S-101', type: 'Slab', state: 'Formwork Installed' } },
          { elementId: '3', labels: ['Inspection'], properties: { id: 'INSP-404', date: '2026-07-10', result: 'FAIL' } }
        ]);
        setLoading(false);
      });
  }, []);

  return (
    <div className="h-full p-8 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Network className="text-atw-purple" size={32} />
        <h1 className="text-3xl font-bold text-white">Knowledge Graph</h1>
      </div>
      
      <div className="bg-atw-surface/40 backdrop-blur-md border border-white/10 rounded-xl p-6 shadow-2xl h-[calc(100vh-200px)] overflow-hidden flex flex-col">
        <h2 className="text-xl font-bold text-white mb-6 border-b border-white/10 pb-4">Entity Inspector</h2>
        
        {loading ? (
          <div className="flex-1 flex justify-center items-center"><div className="w-8 h-8 rounded-full border-2 border-t-atw-purple animate-spin"></div></div>
        ) : (
          <div className="flex-1 overflow-y-auto pr-4 space-y-4">
            {nodes.map((node, idx) => (
              <div key={idx} className="bg-gray-900/50 border border-gray-800 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Database size={16} className="text-atw-purple" />
                  <span className="text-white font-bold tracking-wider text-sm uppercase">Entity Record</span>
                </div>
                <pre className="text-gray-300 text-xs font-mono whitespace-pre-wrap break-words bg-black/30 p-4 rounded border border-white/5">
                  {JSON.stringify(node, null, 2)}
                </pre>
              </div>
            ))}
            {nodes.length === 0 && (
              <div className="text-gray-500 text-center py-8">No entities found in the graph database.</div>
            )}
          </div>
        )}
      </div>
    </div>
  ); 
}