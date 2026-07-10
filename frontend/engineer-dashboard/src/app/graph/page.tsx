"use client";
import { useState } from 'react';
import { Network, Database, Layers, ArrowRight, Activity, Map, Box, FileText, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';

export default function GraphPage() { 
  const [selectedNode, setSelectedNode] = useState('P-001');

  // Mock graph relationships
  const graphData = {
    'P-001': { type: 'Project', label: 'Downtown Tower', links: ['Zone A12', 'Zone B3', 'Zone C7'], icon: Database, color: 'text-white' },
    'Zone A12': { type: 'Zone', label: 'Foundation North', links: ['Asset A-042', 'Asset A-118'], icon: Map, color: 'text-atw-cyan' },
    'Zone B3': { type: 'Zone', label: 'Podium East', links: ['Asset B-991'], icon: Map, color: 'text-atw-cyan' },
    'Asset A-042': { type: 'Asset', label: 'Rebar Grid', links: ['Issue ws-171', 'Spec 03-30-00'], icon: Box, color: 'text-atw-purple' },
    'Asset B-991': { type: 'Asset', label: 'Conduit Route', links: ['Drawing S-101-R3'], icon: Box, color: 'text-atw-purple' },
    'Issue ws-171': { type: 'Observation', label: 'Spacing 190mm (FAIL)', links: [], icon: AlertTriangle, color: 'text-atw-red' },
    'Spec 03-30-00': { type: 'Specification', label: '150mm ±10mm', links: [], icon: FileText, color: 'text-white/60' },
    'Drawing S-101-R3': { type: 'Drawing', label: 'Outdated Revision', links: [], icon: FileText, color: 'text-atw-amber' },
  };

  const currentNode = (graphData as any)[selectedNode];

  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <Network className="text-atw-green" size={32} />
            Knowledge Graph
          </h1>
          <p className="text-white/50 mt-2">Agent 4 Neo4j Semantic Network Explorer.</p>
        </div>
        
        <div className="flex gap-4">
          <button 
            className="bg-atw-green/20 hover:bg-atw-green/30 text-atw-green border border-atw-green/30 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer shadow-[0_0_15px_rgba(0,200,81,0.2)]"
            onClick={() => toast.success('Cypher query interface initialized.')}
          >
            <Database size={16} /> Run Cypher Query
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden min-h-0 flex gap-6">
        
        {/* Graph Explorer Mock UI */}
        <div className="flex-1 bg-[#12121A] border border-white/10 rounded-xl p-8 relative shadow-2xl flex flex-col items-center justify-center overflow-hidden">
          {/* Background grid */}
          <div className="absolute inset-0 opacity-[0.03] bg-[linear-gradient(rgba(255,255,255,1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,1)_1px,transparent_1px)] bg-[size:40px_40px]"></div>
          
          <div className="z-10 flex flex-col items-center max-w-2xl w-full">
            {/* Current Node */}
            <div className="bg-black/60 backdrop-blur-md border border-white/20 p-6 rounded-2xl flex items-center gap-6 shadow-[0_0_30px_rgba(255,255,255,0.05)] transform scale-110 mb-12">
              <div className={`p-4 rounded-xl bg-white/5 border border-white/10`}>
                <currentNode.icon className={currentNode.color} size={32} />
              </div>
              <div>
                <span className="text-xs uppercase tracking-widest text-white/40 font-bold block mb-1">{currentNode.type}</span>
                <h2 className="text-2xl font-bold text-white">{currentNode.label}</h2>
              </div>
            </div>

            {/* Links */}
            <div className="w-full relative">
              {currentNode.links.length > 0 ? (
                <>
                  <div className="absolute left-1/2 top-0 w-px h-12 bg-gradient-to-b from-white/20 to-transparent -translate-x-1/2 -translate-y-12"></div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
                    {currentNode.links.map((link: string, idx: number) => {
                      const linkNode = (graphData as any)[link];
                      if (!linkNode) return null;
                      return (
                        <div 
                          key={idx} 
                          onClick={() => setSelectedNode(link)}
                          className="bg-black/40 hover:bg-black/80 border border-white/10 hover:border-white/30 p-5 rounded-xl flex flex-col items-center gap-3 cursor-pointer transition-all hover:-translate-y-1 group"
                        >
                          <linkNode.icon className={`${linkNode.color} group-hover:scale-110 transition-transform`} size={24} />
                          <div className="text-center">
                            <span className="text-[10px] uppercase tracking-widest text-white/40 font-bold block">{linkNode.type}</span>
                            <span className="text-sm font-semibold text-white/80">{linkNode.label}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div className="text-center text-white/30 text-sm italic mt-8">
                  No outward relationships for this node.
                  <br/>
                  <button 
                    onClick={() => setSelectedNode('P-001')}
                    className="mt-4 text-atw-cyan hover:underline not-italic cursor-pointer"
                  >
                    Return to Root Project Node
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Node Details Sidebar */}
        <div className="w-80 bg-black/40 border border-white/10 rounded-xl p-6 overflow-y-auto hidden md:block">
          <h3 className="text-white font-bold mb-6 flex items-center gap-2 border-b border-white/10 pb-4">
            <Layers size={18} className="text-white/50" /> Node Properties
          </h3>
          
          <div className="space-y-4">
            <div className="bg-white/5 rounded-lg p-3">
              <span className="text-[10px] uppercase tracking-widest text-white/40 block mb-1">ID</span>
              <span className="text-white text-sm font-mono">{selectedNode}</span>
            </div>
            <div className="bg-white/5 rounded-lg p-3">
              <span className="text-[10px] uppercase tracking-widest text-white/40 block mb-1">Entity Type</span>
              <span className="text-white text-sm">{currentNode.type}</span>
            </div>
            
            {selectedNode === 'P-001' && (
              <>
                <div className="bg-white/5 rounded-lg p-3">
                  <span className="text-[10px] uppercase tracking-widest text-white/40 block mb-1">Status</span>
                  <span className="text-atw-green text-sm font-semibold">Active Construction</span>
                </div>
                <div className="bg-white/5 rounded-lg p-3">
                  <span className="text-[10px] uppercase tracking-widest text-white/40 block mb-1">Total Zones</span>
                  <span className="text-white text-sm">24</span>
                </div>
              </>
            )}

            {selectedNode === 'Zone A12' && (
              <div className="bg-atw-red/10 border border-atw-red/20 rounded-lg p-3">
                <span className="text-[10px] uppercase tracking-widest text-atw-red block mb-1">Risk Status</span>
                <span className="text-atw-red text-sm font-bold">CRITICAL</span>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  ); 
}