"use client";

import React, { useRef, useMemo, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Grid } from '@react-three/drei';
import * as THREE from 'three';

export interface TwinIssue {
  id: string;
  severity: string; // critical | high | medium | low
  status: string;
  label: string;
  worker_id?: string | null;
}

interface ZoneState {
  id: string; // zone_code
  name?: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  x: number;
  y: number;
  w: number;
  h: number;
  workerCount: number;
  issues: TwinIssue[];
}

const SEVERITY_HEX: Record<string, string> = {
  critical: '#FF3B3B',
  high: '#FFB300',
  medium: '#00D4FF',
  low: '#00C851',
};

const MAX_WORKER_MARKERS = 16;

// Deterministic per-seed pseudo-random so marker layout stays stable across
// re-renders/poll refreshes (a fresh Math.random() each render would make
// workers/issue beacons visibly jitter every ~15s refresh).
function seededRandom(seed: string) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (Math.imul(31, h) + seed.charCodeAt(i)) | 0;
  return () => {
    h = Math.imul(h ^ (h >>> 15), h | 1);
    h ^= h + Math.imul(h ^ (h >>> 7), h | 61);
    return ((h ^ (h >>> 14)) >>> 0) / 4294967296;
  };
}

// A worker headcount is real (Zone.active_worker_count); an individual
// worker's position inside the zone is not tracked anywhere in this system,
// so this scatters N markers at stable-but-arbitrary points within the
// zone's footprint purely to visualize "N people are in here" — never
// presented as tracked identity/position.
function WorkerMarker({ position, index, total, zoneLabel }: { position: [number, number, number]; index: number; total: number; zoneLabel: string }) {
  const [hovered, setHovered] = useState(false);
  return (
    <group position={position}>
      <Html center distanceFactor={22} zIndexRange={[10, 0]}>
        <div
          onPointerOver={() => setHovered(true)}
          onPointerOut={() => setHovered(false)}
          className="relative flex flex-col items-center cursor-default select-none"
        >
          <span className="text-lg leading-none drop-shadow-[0_0_4px_rgba(0,212,255,0.6)]">🧍</span>
          {hovered && (
            <div className="absolute bottom-full mb-1 whitespace-nowrap bg-black/85 text-white text-[10px] font-mono px-2 py-1 rounded border border-cyan-400/40">
              Worker {index + 1} of {total} · Zone {zoneLabel}
            </div>
          )}
        </div>
      </Html>
    </group>
  );
}

function IssueBeacon({ position, issue, onClick }: { position: [number, number, number]; issue: TwinIssue; onClick: () => void }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const color = SEVERITY_HEX[issue.severity] || SEVERITY_HEX.medium;
  const height = position[1];

  useFrame(({ clock }) => {
    if (meshRef.current) {
      const s = 1 + Math.sin(clock.getElapsedTime() * 3 + height) * 0.25;
      meshRef.current.scale.setScalar(s);
    }
  });

  return (
    <group position={[position[0], 0, position[2]]}>
      {/* Beacon beam from ground to marker */}
      <mesh position={[0, height / 2, 0]}>
        <cylinderGeometry args={[0.05, 0.05, height, 6]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <mesh ref={meshRef} position={[0, height, 0]} onClick={(e) => { e.stopPropagation(); onClick(); }}>
        <sphereGeometry args={[0.35, 12, 12]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2} />
      </mesh>
      <Html position={[0, height + 0.6, 0]} center distanceFactor={22} zIndexRange={[20, 0]}>
        <div
          onClick={onClick}
          className="whitespace-nowrap text-[10px] font-mono font-bold px-1.5 py-0.5 rounded cursor-pointer border"
          style={{ color, borderColor: `${color}80`, backgroundColor: `${color}22` }}
        >
          {issue.label}
        </div>
      </Html>
    </group>
  );
}

// A slowly sweeping "scan bar" across the site — pure decoration evoking a
// live site scan, not a claim of an actual LIDAR/laser scanning system.
function ScanSweep({ depth }: { depth: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const t = (clock.getElapsedTime() % 8) / 8; // 8s loop
    ref.current.position.z = -depth / 2 + t * depth;
  });
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.08, 0]}>
      <planeGeometry args={[200, 1.2]} />
      <meshBasicMaterial color="#00D4FF" transparent opacity={0.18} blending={THREE.AdditiveBlending} depthWrite={false} />
    </mesh>
  );
}

// Structural dressing (slab + corner columns + scaffold wireframe rings)
// around a zone footprint — a stylized "site under construction" look built
// from the real zone bounds, not a literal architectural/BIM model (no such
// file exists for this project; see the twin page's own note on this).
function ZoneStructure({ width, depth, color }: { width: number; depth: number; color: string }) {
  const colW = 0.35, colH = 5;
  const insetX = width / 2 - colW;
  const insetZ = depth / 2 - colW;
  const corners: [number, number][] = [[-insetX, -insetZ], [insetX, -insetZ], [-insetX, insetZ], [insetX, insetZ]];

  return (
    <group>
      {/* Floor slab */}
      <mesh position={[0, 0.05, 0]}>
        <boxGeometry args={[width, 0.15, depth]} />
        <meshStandardMaterial color="#3a3a46" roughness={0.9} />
      </mesh>
      {/* Corner columns */}
      {corners.map(([cx, cz], i) => (
        <mesh key={i} position={[cx, colH / 2, cz]}>
          <boxGeometry args={[colW, colH, colW]} />
          <meshStandardMaterial color="#5a5a68" roughness={0.8} />
        </mesh>
      ))}
      {/* Scaffold wireframe levels */}
      {[1.8, 3.6].map((lvl, i) => (
        <lineSegments key={i} position={[0, lvl, 0]}>
          <edgesGeometry args={[new THREE.BoxGeometry(width * 0.94, 0.02, depth * 0.94)]} />
          <lineBasicMaterial color={color} transparent opacity={0.35} />
        </lineSegments>
      ))}
    </group>
  );
}

function ZoneBox({
  zone, isSelected, onClick, onSelectIssue,
}: {
  zone: ZoneState;
  isSelected: boolean;
  onClick: () => void;
  onSelectIssue: (issue: TwinIssue) => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (zone.status === 'RED' && meshRef.current) {
      meshRef.current.position.y = 2 + Math.sin(clock.getElapsedTime() * 2) * 0.2;
    }
  });

  const color = useMemo(() => {
    if (zone.status === 'RED') return '#FF3B3B';
    if (zone.status === 'AMBER') return '#FFB300';
    return '#00D4FF';
  }, [zone.status]);

  const pxToUnit = 0.1;
  const width = zone.w * pxToUnit;
  const depth = zone.h * pxToUnit;
  const posX = (zone.x + zone.w / 2) * pxToUnit - 40;
  const posZ = (zone.y + zone.h / 2) * pxToUnit - 30;

  const workerPositions = useMemo(() => {
    const rand = seededRandom(`${zone.id}:workers`);
    const count = Math.min(zone.workerCount, MAX_WORKER_MARKERS);
    return Array.from({ length: count }, () => {
      const rx = (rand() - 0.5) * width * 0.75;
      const rz = (rand() - 0.5) * depth * 0.75;
      return [rx, 0.1, rz] as [number, number, number];
    });
  }, [zone.id, zone.workerCount, width, depth]);

  const issuePositions = useMemo(() => {
    return zone.issues.map(issue => {
      const rand = seededRandom(`${zone.id}:issue:${issue.id}`);
      const rx = (rand() - 0.5) * width * 0.6;
      const rz = (rand() - 0.5) * depth * 0.6;
      const height = 2.2 + rand() * 1.4;
      return { issue, position: [rx, height, rz] as [number, number, number] };
    });
  }, [zone.id, zone.issues, width, depth]);

  return (
    <group position={[posX, 0, posZ]}>
      <ZoneStructure width={width} depth={depth} color={color} />

      {/* Risk-colored hazard volume */}
      <mesh
        ref={meshRef}
        position={[0, zone.status === 'RED' ? 2 : 1.2, 0]}
        onClick={(e) => { e.stopPropagation(); onClick(); }}
        onPointerOver={() => { document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = 'default'; }}
      >
        <boxGeometry args={[width * 0.82, isSelected ? 4 : (zone.status === 'RED' ? 2.5 : 1.5), depth * 0.82]} />
        <meshStandardMaterial
          color={color}
          transparent
          opacity={isSelected ? 0.55 : (zone.status === 'GREEN' ? 0.14 : 0.32)}
          emissive={color}
          emissiveIntensity={zone.status === 'RED' ? 1.5 : (isSelected ? 1 : 0.2)}
        />
      </mesh>

      {workerPositions.map((pos, i) => (
        <WorkerMarker key={i} position={pos} index={i} total={zone.workerCount} zoneLabel={zone.id} />
      ))}
      {zone.workerCount > MAX_WORKER_MARKERS && (
        <Html position={[width * 0.3, 0.6, depth * 0.3]} center distanceFactor={22}>
          <div className="text-[10px] font-mono text-cyan-300/80 bg-black/70 px-1.5 py-0.5 rounded whitespace-nowrap">
            +{zone.workerCount - MAX_WORKER_MARKERS} more
          </div>
        </Html>
      )}

      {issuePositions.map(({ issue, position }) => (
        <IssueBeacon key={issue.id} position={position} issue={issue} onClick={() => onSelectIssue(issue)} />
      ))}

      <Html position={[0, 5.5, 0]} center zIndexRange={[100, 0]}>
        <div className={`px-2 py-1 rounded backdrop-blur-md border text-xs font-mono font-bold whitespace-nowrap ${
          zone.status === 'RED' ? 'bg-red-500/20 text-red-400 border-red-500/50' :
          zone.status === 'AMBER' ? 'bg-amber-500/20 text-amber-400 border-amber-500/50' :
          'bg-cyan-500/10 text-white/70 border-cyan-500/30'
        }`}>
          ZONE {zone.id}
        </div>
      </Html>
    </group>
  );
}

export default function ThreeSiteViewer({
  zones, selectedZoneId, onSelectZone, onSelectIssue,
}: {
  zones: ZoneState[];
  selectedZoneId: string | null;
  onSelectZone: (id: string | null) => void;
  onSelectIssue?: (issue: TwinIssue) => void;
}) {
  return (
    <div className="w-full h-full absolute inset-0 z-0">
      <Canvas camera={{ position: [0, 40, 50], fov: 45 }} onPointerMissed={() => onSelectZone(null)}>
        <color attach="background" args={['#050A15']} />

        <ambientLight intensity={0.5} />
        <directionalLight position={[10, 20, 10]} intensity={1} color="#ffffff" />
        <pointLight position={[-10, 10, -10]} intensity={2} color="#00D4FF" />

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

        <ScanSweep depth={70} />

        {zones.map((zone) => (
          <ZoneBox
            key={zone.id}
            zone={zone}
            isSelected={selectedZoneId === zone.id}
            onClick={() => onSelectZone(selectedZoneId === zone.id ? null : zone.id)}
            onSelectIssue={(issue) => { onSelectZone(zone.id); onSelectIssue?.(issue); }}
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
