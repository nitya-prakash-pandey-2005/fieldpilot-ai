import React from 'react';
import { X, Clock, AlertTriangle, User, Camera, FileText, CheckCircle, ArrowUpRight } from 'lucide-react';
import { FieldIssue } from '@/hooks/useFieldIssues';
import { SEVERITY } from '@/theme/severityColors';
import { formatDistanceToNow } from 'date-fns';

interface IssueDetailPanelProps {
  issue: FieldIssue | null;
  isOpen: boolean;
  onClose: () => void;
  onResolve: (id: string, note: string) => void;
  onEscalate: (id: string, role: string, note: string) => void;
}

export default function IssueDetailPanel({ issue, isOpen, onClose, onResolve, onEscalate }: IssueDetailPanelProps) {
  const [resolveNote, setResolveNote] = React.useState('');
  const [escalateNote, setEscalateNote] = React.useState('');
  const [escalateRole, setEscalateRole] = React.useState('Project Manager');
  const [isResolving, setIsResolving] = React.useState(false);
  const [isEscalating, setIsEscalating] = React.useState(false);

  if (!isOpen || !issue) return null;

  const severityData = SEVERITY[issue.severity as keyof typeof SEVERITY] || SEVERITY.medium;

  const handleResolve = () => {
    if (resolveNote.length < 10) return;
    onResolve(issue.id, resolveNote);
    setIsResolving(false);
    setResolveNote('');
  };

  const handleEscalate = () => {
    onEscalate(issue.id, escalateRole, escalateNote);
    setIsEscalating(false);
    setEscalateNote('');
  };

  return (
    <>
      <div 
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 transition-opacity"
        onClick={onClose}
      />
      
      <div className="fixed top-0 right-0 h-full w-full max-w-xl bg-[#0f0f15] border-l border-white/10 z-50 overflow-y-auto shadow-2xl flex flex-col">
        <div className="p-6 border-b border-white/5 flex items-start justify-between sticky top-0 bg-[#0f0f15]/95 backdrop-blur z-10">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className={`text-xs font-bold px-2.5 py-1 rounded-full uppercase tracking-wider ${severityData.bg} ${severityData.text} ${severityData.border} border`}>
                {issue.severity}
              </span>
              <span className="text-white/40 text-sm font-mono">{issue.id}</span>
            </div>
            <h2 className="text-xl font-bold text-white">{issue.issue_type} in Zone {issue.zone_code}</h2>
          </div>
          <button 
            onClick={onClose}
            className="text-white/40 hover:text-white bg-white/5 hover:bg-white/10 p-2 rounded-full transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-6 flex-1 flex flex-col gap-8">
          {/* Status & Timeline */}
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-white/40">Status:</span>
              <span className={`font-semibold uppercase tracking-wider ${issue.status === 'open' ? 'text-yellow-500' : issue.status === 'resolved' ? 'text-green-500' : 'text-orange-500'}`}>
                {issue.status}
              </span>
            </div>
            <div className="flex items-center gap-2 text-white/40">
              <Clock size={14} />
              <span>{formatDistanceToNow(new Date(issue.created_at), { addSuffix: true })}</span>
            </div>
          </div>

          {/* Description */}
          <div>
            <h3 className="text-xs uppercase tracking-widest text-white/40 mb-3 font-semibold">Description</h3>
            <div className="text-white/90 leading-relaxed text-sm">
              {issue.description}
            </div>
          </div>

          {/* Measurements */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
              <div className="text-xs uppercase tracking-widest text-white/40 mb-1">Measured Value</div>
              <div className={`text-xl font-mono ${issue.deviation_pct && issue.deviation_pct > 10 ? 'text-atw-red' : 'text-white'}`}>
                {issue.measured_value || 'N/A'}
              </div>
            </div>
            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
              <div className="text-xs uppercase tracking-widest text-white/40 mb-1">Expected / Tolerance</div>
              <div className="text-xl font-mono text-white/80">
                {issue.expected_value || 'N/A'}
              </div>
            </div>
            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
              <div className="text-xs uppercase tracking-widest text-white/40 mb-1">Deviation</div>
              <div className="text-xl font-mono text-white/80">
                {issue.deviation_pct ? `${issue.deviation_pct}%` : 'N/A'}
              </div>
            </div>
            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
              <div className="text-xs uppercase tracking-widest text-white/40 mb-1">Worker</div>
              <div className="text-xl font-mono text-atw-cyan">
                {issue.worker_id || 'Unknown'}
              </div>
            </div>
          </div>

          {/* Detection Info */}
          <div className="bg-white/5 rounded-xl border border-white/5 p-4 flex flex-col gap-3">
             <div className="flex items-center gap-2 text-sm text-white/70">
                <Camera size={16} className="text-white/40" />
                Detected by <span className="font-semibold text-white">{issue.detected_by || 'System'}</span>
             </div>
             {issue.drawing_ref && (
               <div className="flex items-center gap-2 text-sm text-white/70">
                  <FileText size={16} className="text-white/40" />
                  Reference <span className="font-semibold text-white">{issue.drawing_ref}</span>
               </div>
             )}
          </div>
        </div>

        {/* Actions Footer */}
        {issue.status === 'open' && (
          <div className="p-6 border-t border-white/10 bg-black/40">
            {!isResolving && !isEscalating ? (
              <div className="flex gap-4">
                <button 
                  onClick={() => setIsResolving(true)}
                  className="flex-1 bg-atw-cyan hover:bg-atw-cyan/90 text-black font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
                >
                  <CheckCircle size={18} /> Resolve Issue
                </button>
                <button 
                  onClick={() => setIsEscalating(true)}
                  className="flex-1 bg-white/5 hover:bg-white/10 text-white font-semibold py-3 rounded-lg transition-colors border border-white/10 flex items-center justify-center gap-2"
                >
                  <ArrowUpRight size={18} /> Escalate
                </button>
              </div>
            ) : isResolving ? (
              <div className="flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-4">
                <h3 className="text-white font-semibold flex items-center gap-2"><CheckCircle size={18} className="text-atw-cyan"/> Resolve Issue</h3>
                <textarea 
                  className="w-full bg-black/50 border border-white/10 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-atw-cyan/50 resize-none"
                  rows={3}
                  placeholder="Enter resolution notes (min 10 chars)..."
                  value={resolveNote}
                  onChange={(e) => setResolveNote(e.target.value)}
                />
                <div className="flex gap-3">
                  <button 
                    onClick={handleResolve}
                    disabled={resolveNote.length < 10}
                    className="flex-1 bg-atw-cyan hover:bg-atw-cyan/90 disabled:opacity-50 disabled:hover:bg-atw-cyan text-black font-semibold py-2.5 rounded-lg transition-colors"
                  >
                    Confirm Resolution
                  </button>
                  <button 
                    onClick={() => setIsResolving(false)}
                    className="px-6 bg-white/5 hover:bg-white/10 text-white font-semibold py-2.5 rounded-lg transition-colors border border-white/10"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-4">
                <h3 className="text-white font-semibold flex items-center gap-2"><ArrowUpRight size={18} className="text-orange-500"/> Escalate Issue</h3>
                
                <select 
                  className="w-full bg-black/50 border border-white/10 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-orange-500/50 appearance-none"
                  value={escalateRole}
                  onChange={(e) => setEscalateRole(e.target.value)}
                >
                  <option value="Project Manager">Project Manager</option>
                  <option value="Lead Engineer">Lead Engineer</option>
                  <option value="Safety Officer">Safety Officer</option>
                  <option value="Quality Control">Quality Control</option>
                </select>

                <textarea 
                  className="w-full bg-black/50 border border-white/10 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-orange-500/50 resize-none"
                  rows={2}
                  placeholder="Optional escalation note..."
                  value={escalateNote}
                  onChange={(e) => setEscalateNote(e.target.value)}
                />
                <div className="flex gap-3">
                  <button 
                    onClick={handleEscalate}
                    className="flex-1 bg-orange-500 hover:bg-orange-600 text-white font-semibold py-2.5 rounded-lg transition-colors"
                  >
                    Confirm Escalation
                  </button>
                  <button 
                    onClick={() => setIsEscalating(false)}
                    className="px-6 bg-white/5 hover:bg-white/10 text-white font-semibold py-2.5 rounded-lg transition-colors border border-white/10"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        
        {issue.status !== 'open' && (
          <div className="p-6 border-t border-white/10 bg-black/40 text-center">
            <p className="text-white/40 text-sm flex items-center justify-center gap-2">
               {issue.status === 'resolved' ? <CheckCircle size={16} className="text-green-500"/> : <ArrowUpRight size={16} className="text-orange-500"/>}
               This issue was {issue.status} on {issue.resolved_at || issue.escalated_at ? formatDistanceToNow(new Date(issue.resolved_at || issue.escalated_at!), {addSuffix: true}) : 'recently'}.
            </p>
          </div>
        )}
      </div>
    </>
  );
}
