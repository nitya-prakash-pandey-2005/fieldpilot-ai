"use client";
import { BrainCircuit, Info, Search, FileText, ArrowRight, Eye, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { mockRFIs } from '@/data/mockData';

export default function RFIsPage() { 
  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <BrainCircuit className="text-atw-purple" size={32} />
            Predicted RFIs
          </h1>
          <p className="text-white/50 mt-2">AI-driven predictive issue generation based on historical patterns and current site trajectory.</p>
        </div>
        
        <div className="flex gap-4 items-center">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/30" size={16} />
            <input 
              type="text" 
              placeholder="Search predictions..." 
              className="bg-black/20 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-atw-purple/50 transition-colors"
            />
          </div>
          <button 
            className="bg-atw-purple/20 hover:bg-atw-purple/30 text-atw-purple border border-atw-purple/30 px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer"
            onClick={() => toast.success('Forcing AI re-evaluation of current project state...')}
          >
            <Sparkles size={16} /> Refresh Analysis
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 pb-10">
          {mockRFIs.map((rfi) => (
            <div key={rfi.id} className="bg-[#12121A] border border-white/10 rounded-xl flex flex-col shadow-2xl relative overflow-hidden group hover:border-atw-purple/40 transition-colors">
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-atw-purple via-atw-cyan to-transparent opacity-70"></div>
              
              <div className="p-6 border-b border-white/5 flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="bg-white/5 border border-white/10 text-white/70 px-2 py-0.5 rounded text-xs font-mono font-bold tracking-wider">
                      ZONE {rfi.zone_id}
                    </span>
                    <span className="text-sm font-semibold text-atw-purple bg-atw-purple/10 px-2 py-0.5 rounded uppercase tracking-wider border border-atw-purple/20">
                      {rfi.rfi_category.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <h3 className="text-white text-xl font-bold mt-3">High Probability: {rfi.rfi_category.replace(/_/g, ' ')}</h3>
                </div>
                <div className="flex flex-col items-end">
                  <div className="text-3xl font-bold font-mono text-white tracking-tighter">
                    {Math.round(rfi.probability * 100)}<span className="text-atw-purple text-xl">%</span>
                  </div>
                  <span className="text-[10px] uppercase tracking-widest text-white/40 font-bold">Probability</span>
                </div>
              </div>

              <div className="p-6 flex-1 flex flex-col gap-6">
                <div>
                  <h4 className="text-xs uppercase tracking-widest text-white/40 mb-2 font-bold flex items-center gap-2">
                    <Info size={14} className="text-atw-cyan" /> Basis of Prediction
                  </h4>
                  <p className="text-white/80 text-sm leading-relaxed bg-white/5 p-4 rounded-lg border border-white/5">
                    {rfi.basis}
                  </p>
                </div>

                <div>
                  <h4 className="text-xs uppercase tracking-widest text-white/40 mb-2 font-bold flex items-center gap-2">
                    <BrainCircuit size={14} className="text-atw-purple" /> Recommended Action
                  </h4>
                  <div className="bg-atw-purple/10 border border-atw-purple/20 rounded-lg p-4 text-atw-purple/90 text-sm leading-relaxed relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-24 h-24 bg-atw-purple/20 blur-2xl rounded-full"></div>
                    {rfi.recommended_pre_action}
                  </div>
                </div>

                <div>
                  <h4 className="text-xs uppercase tracking-widest text-white/40 mb-2 font-bold">Related Documents</h4>
                  <div className="flex gap-2 flex-wrap">
                    {rfi.drawing_sections_to_clarify.map((doc, i) => (
                      <span key={i} className="text-xs bg-black/40 border border-white/10 text-white/60 px-3 py-1.5 rounded-full flex items-center gap-2">
                        <FileText size={12} /> {doc}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="p-4 border-t border-white/5 bg-black/20 flex gap-4">
                <button 
                  onClick={() => toast('Retrieving historical RFI examples from Qdrant vector database...', { icon: <Eye size={16} /> })}
                  className="flex-1 bg-white/5 hover:bg-white/10 text-white font-semibold py-3 rounded-lg transition-colors border border-white/10 flex items-center justify-center gap-2 cursor-pointer text-sm"
                >
                  <Eye size={16} /> View Similar Historical RFIs
                </button>
                <button 
                  onClick={() => toast.success('Draft clarification RFI has been generated and pushed to your inbox.')}
                  className="flex-1 bg-atw-purple hover:bg-atw-purple/80 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2 cursor-pointer text-sm shadow-[0_0_15px_rgba(123,97,255,0.3)]"
                >
                  Draft Clarification <ArrowRight size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  ); 
}