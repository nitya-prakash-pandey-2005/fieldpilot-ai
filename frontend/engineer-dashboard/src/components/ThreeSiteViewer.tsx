"use client";

import React, { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Box, Plane, Grid } from '@react-three/drei';
import * as THREE from 'three';

interface ZoneState {
  id: string;
  name?: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  x: number;
  y: number;
  w: number;
  h: number;
}

// Sub-component for an individual zone box
function ZoneBox({ zone, isSelected, onClick }: { zone: ZoneState, isSelected: boolean, onClick: () => void }) {
  const meshRef = useRef<THREE.Mesh>(null);
  
  // Animate the critical zones
  useFrame(({ clock }) => {
    if (zone.status === 'RED' && meshRef.current) {
      meshRef.current.position.y = 0.5 + Math.sin(clock.getElapsedTime() * 2) * 0.2;
    }
  });

  const color = useMemo(() => {
    if (zone.status === 'RED') return '#FF3B3B';
    if (zone.status === 'AMBER') return '#FFB300';
    return '#00D4FF';
  }, [zone.status]);

  // Convert SVG coordinates to 3D space
  // Original SVG was 800x600. Let's map to 80x60 units.
  const pxToUnit = 0.1;
  const width = zone.w * pxToUnit;
  const height = zone.h * pxToUnit;
  // SVG origin is top-left, 3D origin is center.
  const posX = (zone.x + zone.w / 2) * pxToUnit - 40;
  const posZ = (zone.y + zone.h / 2) * pxToUnit - 30;

  return (
    <group position={[posX, zone.status === 'RED' ? 0.5 : 0.1, posZ]}>
      <mesh ref={meshRef} onClick={onClick} onPointerOver={(e) => { document.body.style.cursor = 'pointer'; }} onPointerOut={(e) => { document.body.style.cursor = 'default'; }}>
        <boxGeometry args={[width, isSelected ? 2 : (zone.status === 'RED' ? 1.5 : 0.5), height]} />
        <meshStandardMaterial 
          color={color} 
          transparent 
          opacity={isSelected ? 0.8 : (zone.status === 'GREEN' ? 0.2 : 0.6)} 
          emissive={color}
          emissiveIntensity={zone.status === 'RED' ? 1.5 : (isSelected ? 1 : 0.2)}
        />
      </mesh>
      
      <Html position={[0, 2, 0]} center zIndexRange={[100, 0]}>
        <div className={`px-2 py-1 rounded backdrop-blur-md border text-xs font-mono font-bold whitespace-nowrap ${
          zone.status === 'RED' ? 'bg-atw-red/20 text-atw-red border-atw-red/50' : 
          zone.status === 'AMBER' ? 'bg-atw-amber/20 text-atw-amber border-atw-amber/50' : 
          'bg-atw-cyan/10 text-white/70 border-atw-cyan/30'
        }`}>
          ZONE {zone.id}
        </div>
      </Html>
    </group>
  );
}

export default function ThreeSiteViewer({ zones, selectedZoneId, onSelectZone }: { 
  zones: ZoneState[], 
  selectedZoneId: string | null, 
  onSelectZone: (id: string | null) => void 
}) {
  return (
    <div className="w-full h-full absolute inset-0 z-0">
      <Canvas camera={{ position: [0, 40, 50], fov: 45 }}>
        <color attach="background" args={['#050A15']} />
        
        <ambientLight intensity={0.5} />
        <directionalLight position={[10, 20, 10]} intensity={1} color="#ffffff" />
        <pointLight position={[-10, 10, -10]} intensity={2} color="#00D4FF" />
        
        {/* Floor Grid */}
        <Grid 
          infiniteGrid 
          fadeDistance={100} 
          sectionColor="#00D4FF" 
          cellColor="#00D4FF" 
          sectionThickness={1}
          cellThickness={0.5}
          sectionSize={10}
          cellSize={2}
          position={[0, 0, 0]} 
        />
        
        {/* Render Zones */}
        {zones.map((zone) => (
          <ZoneBox 
            key={zone.id} 
            zone={zone} 
            isSelected={selectedZoneId === zone.id}
            onClick={() => onSelectZone(selectedZoneId === zone.id ? null : zone.id)} 
          />
        ))}

        <OrbitControls 
          makeDefault 
          maxPolarAngle={Math.PI / 2 - 0.1} 
          minDistance={10} 
          maxDistance={100} 
          autoRotate={!selectedZoneId}
          autoRotateSpeed={0.5}
        />
      </Canvas>
    </div>
  );
}
