import { apiBase } from '@/lib/api';
// Real scene analysis via POST /api/v1/vision/understand (agents/vision/
// vlm_analyzer.py + agents/vision/detector.py combined). Previously the
// Glasses page's "upload image" and "webcam" flows either returned a
// hardcoded canned result regardless of image content, or picked a random
// demo scenario — neither ever called this endpoint.
//
// The VLM does scene understanding (what's happening, hazards, compliance
// concerns) — it does NOT do numeric measurement (that's Agent 2's job,
// wired separately). This mapping is honest about that: no fabricated mm
// values, only what the model actually returned.

const API = apiBase();

const URGENCY_TO_VERDICT: Record<string, string> = {
  critical: 'CRITICAL',
  high: 'HIGH',
  medium: 'WARNING',
  low: 'PASS',
};

export interface SceneAnalysisResult {
  name: string;
  image: string;
  verdict: string;
  issue: string;
  measured: string;
  required: string;
  deviation: string;
  confidence: string;
  agentChain: string;
  time: string;
  spokenResponse: string;
  raw: any;
}

export async function analyzeSceneReal(
  imageDataUrl: string,
  zoneId: string = 'A12',
  language: string = 'en',
  projectId: string = 'default-project',
): Promise<SceneAnalysisResult> {
  const base64 = imageDataUrl.includes(',') ? imageDataUrl.split(',')[1] : imageDataUrl;
  const start = Date.now();

  const res = await fetch(`${API}/api/v1/vision/understand`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image: base64, zone_id: zoneId, language, project_id: projectId }),
  });
  if (!res.ok) throw new Error(`Vision analysis failed: ${res.status}`);
  const data = await res.json();
  const elapsed = ((Date.now() - start) / 1000).toFixed(1);

  const scene = data.scene || {};
  const urgency = (scene.urgency || 'low').toLowerCase();
  const hazards: string[] = scene.safety_hazards || [];
  const complianceIssues: string[] = scene.compliance_issues || [];
  const issueCount = hazards.length + complianceIssues.length;
  const primaryIssue = complianceIssues[0] || hazards[0] || scene.work_type || 'Scene analyzed, no issues flagged';
  const confidencePct = typeof scene.confidence === 'number' ? Math.round(scene.confidence * 100) : null;

  return {
    name: scene.work_type || 'Live Scene Analysis',
    image: imageDataUrl,
    verdict: URGENCY_TO_VERDICT[urgency] || 'PASS',
    issue: primaryIssue,
    measured: scene.scene_description || 'No description returned',
    required: complianceIssues.length > 0 ? 'Per project specification' : 'N/A',
    deviation: issueCount > 0 ? `${issueCount} issue${issueCount > 1 ? 's' : ''} flagged` : 'N/A',
    confidence: confidencePct !== null ? `${confidencePct}%` : 'N/A',
    agentChain: 'V1→VLM(Groq)',
    time: `${elapsed}s`,
    spokenResponse: scene.spoken_response || '',
    raw: data,
  };
}
