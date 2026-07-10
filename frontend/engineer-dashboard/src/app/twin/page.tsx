"use client";
import LiveSiteMap from '@/components/LiveSiteMap';

export default function TwinPage() { 
  return (
    <div className="h-full p-8 flex flex-col h-full">
      <h1 className="text-3xl font-bold text-white mb-6">Digital Twin</h1>
      <div className="flex-1 relative rounded-xl overflow-hidden border border-gray-800">
        <LiveSiteMap />
      </div>
    </div>
  ); 
}