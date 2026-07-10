"use client";
import { ActiveIssuesPanel } from '@/components/ActiveIssuesPanel';

export default function IssuesPage() { 
  return (
    <div className="h-full p-8">
      <h1 className="text-3xl font-bold text-white mb-6">Active Issues</h1>
      <ActiveIssuesPanel />
    </div>
  ); 
}