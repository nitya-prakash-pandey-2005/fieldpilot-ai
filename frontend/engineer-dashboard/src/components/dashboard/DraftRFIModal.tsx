"use client";

import React from 'react';

interface DraftRFIModalProps {
  isOpen: boolean;
  onClose: () => void;
  rfiId: string;
  title: string;
  zone: string;
}

export function DraftRFIModal({ isOpen, onClose, rfiId, title, zone }: DraftRFIModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="bg-[var(--bg-surface)] border border-[var(--border-accent)] rounded-xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between bg-black/20">
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-bold bg-[var(--purple-dim)] text-[var(--purple)] px-2 py-0.5 rounded border border-[var(--purple)]/30 uppercase tracking-wider">
              AGENT 7: Auto-Draft
            </span>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Draft RFI: {rfiId}</h2>
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white transition-colors">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-6 flex flex-col gap-4">
          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Subject</label>
            <div className="text-sm text-[var(--text-primary)] font-medium p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
              {title}
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Location</label>
              <div className="text-sm text-[var(--text-secondary)] p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
                {zone}
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Impact Level</label>
              <div className="text-sm text-[var(--fail)] font-bold p-2 bg-black/20 rounded border border-[var(--border-subtle)]">
                High (Schedule Blocked)
              </div>
            </div>
          </div>

          <div>
            <label className="block text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1">Question / Deviation</label>
            <div className="text-sm text-[var(--text-secondary)] p-3 bg-black/20 rounded border border-[var(--border-subtle)] font-mono whitespace-pre-wrap">
{`Per the OSHA 3146 Fall Protection guidelines and the structural drawings for ${zone}, there is an ambiguity regarding the required tie-off anchor points above the HVAC ductwork.

The field team observed that the current structural layout does not provide adequate clearance for standard 6ft lanyards without clashing with the primary duct mains.

Please advise on:
1. Approved alternative tie-off locations
2. Whether temporary anchors can be welded to beam W12x26

Attached: Glasses Capture 14:02 PM, Structural Spec 4.2.1`}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[var(--border-subtle)] bg-black/20 flex items-center justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-xs font-semibold text-[var(--text-muted)] hover:text-white transition-colors">
            Cancel
          </button>
          <button onClick={onClose} className="px-4 py-2 text-xs font-bold text-black bg-[var(--purple)] hover:bg-[var(--purple-hover)] transition-colors rounded">
            Send to Procore
          </button>
        </div>
      </div>
    </div>
  );
}
