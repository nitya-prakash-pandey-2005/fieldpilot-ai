"use client";
import { FileBox, FileWarning, CheckCircle, Upload, Search } from 'lucide-react';
import { toast } from 'sonner';
import { mockDrawings } from '@/data/mockData';

export default function DrawingsPage() { 
  return (
    <div className="h-full p-8 flex flex-col min-h-0 bg-atw-bg">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
            <FileBox className="text-blue-500" size={32} />
            Drawing Versions
          </h1>
          <p className="text-white/50 mt-2">Agent 8 monitors field usage in real-time to prevent outdated revision usage.</p>
        </div>
        
        <div className="flex gap-4 items-center">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-white/30" size={16} />
            <input 
              type="text" 
              placeholder="Search drawings..." 
              className="bg-black/20 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-blue-500/50 transition-colors"
            />
          </div>
          <button 
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition-all cursor-pointer shadow-lg shadow-blue-900/50"
            onClick={() => toast('Opening file upload dialog...')}
          >
            <Upload size={16} /> Upload New Revision
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="bg-[#12121A] border border-white/10 rounded-xl overflow-hidden shadow-2xl">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-black/40 border-b border-white/10">
                <th className="p-4 text-xs font-bold text-white/40 uppercase tracking-widest">Drawing No.</th>
                <th className="p-4 text-xs font-bold text-white/40 uppercase tracking-widest">Discipline</th>
                <th className="p-4 text-xs font-bold text-white/40 uppercase tracking-widest">Latest Approved</th>
                <th className="p-4 text-xs font-bold text-white/40 uppercase tracking-widest">Approved By</th>
                <th className="p-4 text-xs font-bold text-white/40 uppercase tracking-widest">Field Usage Detections</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {mockDrawings.map(dwg => (
                <tr key={dwg.id} className="hover:bg-white/5 transition-colors group">
                  <td className="p-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                        <FileBox size={14} className="text-blue-500" />
                      </div>
                      <span className="font-bold text-white tracking-wider">{dwg.number}</span>
                    </div>
                  </td>
                  <td className="p-4 text-sm text-white/70">{dwg.discipline}</td>
                  <td className="p-4">
                    <div className="flex flex-col">
                      <span className="font-mono text-atw-green font-bold text-lg">{dwg.latest_revision}</span>
                      <span className="text-xs text-white/40">{dwg.latest_date}</span>
                    </div>
                  </td>
                  <td className="p-4 text-sm text-white/60">{dwg.approved_by}</td>
                  <td className="p-4">
                    <div className="flex flex-col gap-2">
                      {dwg.field_usage.map((usage, idx) => (
                        <div key={idx} className="flex items-center gap-3">
                          <span className="text-xs text-white/50 w-16">{usage.worker}</span>
                          <span className="text-xs font-mono bg-black/40 border border-white/10 px-2 py-0.5 rounded">{usage.revision_scanned}</span>
                          {usage.status === 'MISMATCH' ? (
                            <span className="flex items-center gap-1 text-[10px] font-bold tracking-widest uppercase bg-atw-red/20 text-atw-red border border-atw-red/30 px-2 py-0.5 rounded-full">
                              <FileWarning size={10} /> Mismatch
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[10px] font-bold tracking-widest uppercase text-atw-green/70">
                              <CheckCircle size={12} /> Compliant
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  ); 
}