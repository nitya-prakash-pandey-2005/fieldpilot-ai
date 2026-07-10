import Link from 'next/link';
import { 
  MapIcon, 
  AlertTriangle, 
  BrainCircuit, 
  Flame, 
  FileBox, 
  Network, 
  Box, 
  Bell 
} from 'lucide-react';

const navItems = [
  { name: 'Live Site Map', href: '/', icon: MapIcon },
  { name: 'Active Issues', href: '/issues', icon: AlertTriangle },
  { name: 'Predicted RFIs', href: '/rfis', icon: BrainCircuit },
  { name: 'High Risk Zones', href: '/zones', icon: Flame },
  { name: 'Drawing Versions', href: '/drawings', icon: FileBox },
  { name: 'Knowledge Graph', href: '/graph', icon: Network },
  { name: 'Digital Twin', href: '/twin', icon: Box },
  { name: 'Notifications', href: '/notifications', icon: Bell },
];

export function Sidebar() {
  return (
    <div className="flex flex-col w-64 h-screen bg-[#0f172a] border-r border-gray-800 text-gray-300">
      <div className="p-6 flex items-center gap-3 border-b border-gray-800">
        <div className="w-8 h-8 rounded-md bg-blue-600 flex items-center justify-center">
          <Box size={20} className="text-white" />
        </div>
        <span className="text-xl font-bold text-white tracking-tight">ASK THE WALL</span>
      </div>
      
      <nav className="flex-1 overflow-y-auto py-6 px-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link 
              key={item.name} 
              href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-800 hover:text-white transition-all duration-200 group"
            >
              <Icon size={18} className="text-gray-400 group-hover:text-blue-400 transition-colors" />
              <span className="font-medium text-sm">{item.name}</span>
            </Link>
          );
        })}
      </nav>
      
      <div className="p-4 border-t border-gray-800">
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center text-xs font-bold text-white">
            SC
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium text-white">Sarah Chen</span>
            <span className="text-xs text-gray-500">Lead Engineer</span>
          </div>
        </div>
      </div>
    </div>
  );
}
