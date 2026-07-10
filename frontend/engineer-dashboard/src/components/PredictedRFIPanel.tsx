"use client";

import { useEffect, useState } from 'react';
import { BrainCircuit, AlertCircle, ArrowRight, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { mockRFIs } from '@/data/mockData';

export function PredictedRFIPanel() {
  const [data, setData] = useState<any[]>(mockRFIs);
  const [loading, setLoading] = useState(false);

  // Mock data loaded immediately
  /*
  useEffect(() => { ... }, []);
  */

  return (
    <div className="h-full flex flex-col relative animate-fade-in" style={{ animationDelay: '350ms', animationFillMode: 'both' }}>
      <div className="p-4 border-b border-white/5 bg-gradient-to-r from-atw-purple/20 to-transparent flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BrainCircuit className="text-atw-purple" size={20} />
          <h2 className="font-semibold tracking-wide text-white/90 uppercase text-sm">Predicted RFIs</h2>
        </div>
        <span className="bg-atw-purple/20 text-atw-purple text-xs px-2.5 py-1 rounded-full border border-atw-purple/30 tracking-wider">
          LIVE AI ANALYSIS
        </span>
      </div>
      
      <div className="p-5 flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-atw-purple border-t-transparent rounded-full animate-spin"></div>
          </div>
        ) : !data || data.length === 0 ? (
          <div className="text-white/40 text-sm text-center py-10">No predictive data available.</div>
        ) : (
          <div className="space-y-4">
            {data.map((rfi: any, idx: number) => (
              <div key={idx} className="bg-black/40 backdrop-blur-md rounded-lg p-4 border border-atw-purple/30 group hover:border-atw-purple/60 hover:shadow-[0_0_15px_rgba(123,97,255,0.2)] transition-all duration-300 relative overflow-hidden">
                <div className="absolute top-0 left-0 w-1 h-full bg-atw-purple opacity-70"></div>
                
                <div className="flex items-start justify-between mb-3 ml-2">
                  <div className="flex items-center gap-2 text-white/90">
                    <span className="font-semibold text-sm">Zone {rfi.zone_id} — {rfi.rfi_category.replace(/_/g, ' ').toUpperCase()}</span>
                  </div>
                  <div className="text-xs font-mono font-bold text-atw-purple bg-atw-purple/20 border border-atw-purple/30 px-2 py-0.5 rounded shadow-[0_0_8px_rgba(123,97,255,0.4)]">
                    {Math.round(rfi.probability * 100)}% PROB
                  </div>
                </div>
                
                <p className="text-white/50 text-xs mb-3 ml-2 leading-relaxed">
                  <span className="text-white/70 font-medium">Basis:</span> {rfi.basis}
                </p>
                
                <div className="bg-atw-cyan/10 border border-atw-cyan/30 rounded p-3 mb-4 ml-2 relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-16 h-16 bg-atw-cyan/20 blur-xl rounded-full"></div>
                  <span className="text-atw-cyan text-[10px] font-bold uppercase tracking-widest block mb-1">Recommended Action</span>
                  <p className="text-atw-cyan/90 text-sm leading-relaxed">{rfi.recommended_pre_action}</p>
                </div>
                
                <div className="flex gap-3 ml-2">
                  <button 
                    onClick={() => toast('Fetching similar RFIs from database...', { icon: <FileText size={14} className="text-atw-cyan" /> })}
                    className="flex-1 bg-white/5 hover:bg-white/10 text-white border border-white/10 text-xs py-2 rounded transition-colors tracking-wider font-medium cursor-pointer"
                  >
                    View Similar RFIs
                  </button>
                  <button 
                    onClick={() => toast.success('Draft clarification RFI has been generated.')}
                    className="flex-1 bg-atw-purple hover:bg-atw-purple/80 text-white text-xs py-2 rounded flex items-center justify-center gap-1 transition-colors tracking-wider font-semibold cursor-pointer"
                  >
                    Draft Clarification <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
