export const mockIssues = [
  {
    id: 'ws-1718042400000',
    zone_id: 'A12',
    asset_type: 'Rebar Grid',
    severity: 'CRITICAL',
    deviation_pct: 26.6,
    measured_value: '190mm',
    spec_value: '150mm',
    created_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(), // 2 mins ago
    worker_id: 'W-022',
    description: 'Rebar spacing is 190mm. Specification requires 150mm ±10mm. Deviation is 40mm above maximum. STOP WORK.'
  },
  {
    id: 'ws-1718042000000',
    zone_id: 'B3',
    asset_type: 'Conduit Routing',
    severity: 'HIGH',
    deviation_pct: 12.0,
    measured_value: 'Drawing R3',
    spec_value: 'Drawing R5',
    created_at: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
    worker_id: 'W-015',
    description: 'Worker using outdated drawing S-101-R3. Latest approved is R5 (Nov 2, 2024). R5 changes conduit routing in this zone.'
  },
  {
    id: 'ws-1718041500000',
    zone_id: 'C7',
    asset_type: 'HVAC Duct',
    severity: 'MEDIUM',
    deviation_pct: 8.5,
    measured_value: '2.85m',
    spec_value: '3.00m',
    created_at: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    worker_id: 'W-088',
    description: 'Clearance height is 2.85m. Minimum clearance per spec is 3.00m. Warning generated.'
  },
  {
    id: 'ws-1718041000000',
    zone_id: 'A12',
    asset_type: 'Concrete Formwork',
    severity: 'HIGH',
    deviation_pct: 15.0,
    measured_value: '2.3 deg',
    spec_value: '0 deg',
    created_at: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    worker_id: 'W-042',
    description: 'Formwork is leaning by 2.3 degrees. Maximum allowable tolerance is 1.0 degree.'
  },
  {
    id: 'ws-1718040000000',
    zone_id: 'B3',
    asset_type: 'Cable Tray',
    severity: 'MEDIUM',
    deviation_pct: 5.5,
    measured_value: '520mm',
    spec_value: '550mm',
    created_at: new Date(Date.now() - 1000 * 60 * 180).toISOString(),
    worker_id: 'W-015',
    description: 'Cable tray offset is 520mm from wall, expected 550mm.'
  }
];

export const mockRFIs = [
  {
    id: 'pred-rfi-001',
    zone_id: 'A12',
    rfi_category: 'structural_interference',
    probability: 0.87,
    basis: '14 similar RFIs in 8 comparable projects using same design pattern (lap splice junction at C4).',
    recommended_pre_action: 'Engineer to clarify lap splice length at column C4 junction before Zone A12 rebar installation begins.',
    drawing_sections_to_clarify: ['S-101 Detail 4A', 'S-102 Section B-B']
  },
  {
    id: 'pred-rfi-002',
    zone_id: 'B3',
    rfi_category: 'mep_clash',
    probability: 0.76,
    basis: 'Historical clash detected between 300mm HVAC duct and Fire Sprinkler main line in similar corridor layouts.',
    recommended_pre_action: 'Run Navisworks clash detection specifically on B3 corridor ceiling space.',
    drawing_sections_to_clarify: ['M-045-R2', 'FP-012-R1']
  },
  {
    id: 'pred-rfi-003',
    zone_id: 'C7',
    rfi_category: 'material_spec_ambiguity',
    probability: 0.62,
    basis: 'Specification document lists Type II cement, but structural notes mention Type I/II. 5 prior projects had delays due to this ambiguity.',
    recommended_pre_action: 'Issue memo confirming acceptable cement type for C7 foundation pour.',
    drawing_sections_to_clarify: ['Spec Section 03 30 00']
  }
];

export const mockZones = [
  {
    id: 'A12',
    name: 'Foundation Level 1 - North',
    risk_score: 0.85, // 0-1
    active_issues: 2,
    active_workers: 14,
    status: 'RED',
    recent_activity: 'Rebar installation'
  },
  {
    id: 'B3',
    name: 'Podium Level 3 - East',
    risk_score: 0.45,
    active_issues: 2,
    active_workers: 8,
    status: 'AMBER',
    recent_activity: 'MEP rough-in'
  },
  {
    id: 'C7',
    name: 'Tower Floor 12 - Core',
    risk_score: 0.12,
    active_issues: 1,
    active_workers: 22,
    status: 'GREEN',
    recent_activity: 'Concrete curing'
  }
];

export const mockDrawings = [
  {
    id: 'dwg-001',
    number: 'S-101',
    discipline: 'Structural',
    latest_revision: 'R5',
    latest_date: '2024-11-02',
    approved_by: 'David Park, SE',
    field_usage: [
      { worker: 'W-022', revision_scanned: 'R5', status: 'MATCH' },
      { worker: 'W-015', revision_scanned: 'R3', status: 'MISMATCH' }
    ]
  },
  {
    id: 'dwg-002',
    number: 'M-045',
    discipline: 'Mechanical',
    latest_revision: 'R2',
    latest_date: '2024-10-15',
    approved_by: 'Sarah Chen',
    field_usage: [
      { worker: 'W-088', revision_scanned: 'R2', status: 'MATCH' }
    ]
  },
  {
    id: 'dwg-003',
    number: 'A-200',
    discipline: 'Architectural',
    latest_revision: 'R1',
    latest_date: '2024-09-01',
    approved_by: 'Elena Rostova',
    field_usage: [
      { worker: 'W-042', revision_scanned: 'R1', status: 'MATCH' },
      { worker: 'W-019', revision_scanned: 'R0', status: 'MISMATCH' }
    ]
  }
];

export const mockNotifications = [
  {
    id: 'notif-1',
    title: 'CRITICAL: Rebar Spacing Deviation',
    message: 'Zone A12 Rebar spacing 190mm exceeds tolerance (Spec 150mm). STOP WORK ordered.',
    type: 'alert',
    severity: 'CRITICAL',
    time: '2 minutes ago',
    read: false
  },
  {
    id: 'notif-2',
    title: 'HIGH: Outdated Drawing Detected',
    message: 'Worker W-015 scanned drawing S-101-R3 in Zone B3. Current is R5.',
    type: 'alert',
    severity: 'HIGH',
    time: '8 minutes ago',
    read: false
  },
  {
    id: 'notif-3',
    title: 'SYSTEM: Agent 10 Learning Loop',
    message: 'Successfully ingested 14 resolved incidents into Qdrant for RFI prediction model.',
    type: 'system',
    severity: 'INFO',
    time: '1 hour ago',
    read: true
  },
  {
    id: 'notif-4',
    title: 'RFI Approved: Lap Splice Clarification',
    message: 'RFI #1042 has been approved by Structural Engineer. Zone A12 cleared to proceed.',
    type: 'workflow',
    severity: 'LOW',
    time: '3 hours ago',
    read: true
  }
];
