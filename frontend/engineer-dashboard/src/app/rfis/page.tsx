"use client";
import { PredictedRFIPanel } from '@/components/PredictedRFIPanel';

export default function RFIsPage() { 
  return (
    <div className="h-full p-8">
      <h1 className="text-3xl font-bold text-white mb-6">Predicted RFIs</h1>
      <PredictedRFIPanel />
    </div>
  ); 
}