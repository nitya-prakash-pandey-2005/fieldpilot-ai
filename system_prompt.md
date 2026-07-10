# ASK THE WALL — Production System Prompt
## AI Digital Foreman for the Physical World
### Version 1.0 | Hackathon MVP → Production Blueprint

---

## SECTION 0: PROMPT USAGE INSTRUCTIONS

This is a **complete, self-contained system prompt** designed to be passed directly to any capable AI coding agent (Claude Code, GPT-4o, Gemini 1.5 Pro, etc.) or a multi-agent orchestration framework (LangGraph, CrewAI, AutoGen, OpenClaw, NemoClaw).

**How to use:**
- Pass this entire document as the SYSTEM prompt to your agent
- Append your specific task (e.g., "Build Agent 1 first") as the USER message
- The agent has full context to make architectural decisions without ambiguity
- Every technology choice is explicit and justified — do not deviate without flagging

**Agent execution order for MVP:**
1. Infrastructure setup (Docker, Neo4j, Qdrant, Redis)
2. Agent 3 (Drawing Intelligence) + Agent 4 (Knowledge Graph) — data foundation first
3. Agent 1 (Vision) + Agent 2 (Measurement) — perception layer
4. Agent 5 (Compliance) + Agent 6 (Predictive RFI) — intelligence layer
5. Agent 7 (Memory) + Agent 8 (Version Control) + Agent 9 (Notification) — workflow layer
6. Agent 10 (Learning) — feedback loop
7. UI Layer (Worker App, Engineer Dashboard, Executive Dashboard)
8. Integration & End-to-End testing

---

## SECTION 1: PRODUCT IDENTITY

### 1.1 Product Name
**ASK THE WALL**

### 1.2 Tagline
*The AI Digital Foreman for the Physical World*

### 1.3 Product Category
**Physical AI + Construction Technology + Industrial Intelligence Platform**

### 1.4 Core Philosophy
This is NOT:
- A chatbot
- A defect detection tool
- A passive AI assistant

This IS:
- An **AI Digital Foreman** — an autonomous, proactive supervisory intelligence
- A system that **sees, understands, measures, validates, predicts, escalates, and learns**
- A **continuous passive intelligence layer** over physical construction and manufacturing environments

### 1.5 Target Industries (Priority Order)
1. **Construction** (primary MVP target)
2. **Manufacturing** (secondary)
3. **Infrastructure** (tertiary — rail, power, utilities)

### 1.6 Target Users
| User Type | Role | Primary Interface |
|-----------|------|-------------------|
| Field Worker | Executes physical work | Meta Smart Glasses + Mobile App |
| Site Engineer | Validates, approves, resolves | Engineer Dashboard (Web) |
| Project Manager | Oversight, risk management | Executive Dashboard (Web) |
| QC Inspector | Formal inspection | Mobile App + Dashboard |
| Executive | KPIs, ROI, portfolio view | Executive Dashboard |

---

## SECTION 2: PROBLEM STATEMENT (PRECISE, QUANTIFIED)

### 2.1 Construction Industry Problems

| Problem | Quantified Impact |
|---------|------------------|
| Rework from errors | 5–15% of total project cost |
| RFI average response time | 6–10 working days |
| Wrong drawing revision usage | Estimated 30% of field errors |
| Spec violations due to memory failure | Workers cannot retain full specification sets |
| Inspection bottlenecks | Inspection happens post-completion, not during |
| Knowledge silos | Critical decisions buried in emails, WhatsApp, RFIs, meeting minutes |

### 2.2 Manufacturing Industry Problems
- Machine installation parameter errors
- Assembly sequence deviations
- Maintenance SOP non-compliance
- Safety clearance violations
- Production line misconfiguration

### 2.3 Infrastructure Industry Problems
- Utility and cable routing errors
- Pipe misalignment
- Asset compliance violations
- Rail signaling installation errors
- Power plant installation deviations

### 2.4 Current vs. Future Workflow

**CURRENT (Broken):**
```
Worker → Sees Issue → Calls Engineer → Sends WhatsApp → Files RFI
→ Waits 6–10 days → Builds anyway → Rework → Cost overrun
```

**FUTURE (ASK THE WALL):**
```
Worker → Looks at Asset → AI understands context → AI validates instantly
→ AI predicts risks → AI recommends action → AI escalates automatically
→ Near-zero RFIs → Near-zero rework → Continuous project intelligence
```

---

## SECTION 3: SYSTEM ARCHITECTURE (COMPLETE)

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     INPUT LAYER                             │
│  Meta Smart Glasses  │  Mobile Camera  │  Uploaded Docs     │
└──────────────┬───────────────┬────────────────┬────────────┘
               │               │                │
               ▼               ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                  PERCEPTION LAYER                           │
│   Vision Understanding Agent │ Physical Measurement Agent   │
│         (Agent 1)            │        (Agent 2)             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  KNOWLEDGE LAYER                            │
│  Drawing Intelligence Agent  │  Project Knowledge Graph     │
│        (Agent 3)             │       Agent (Agent 4)        │
│                              │       [Neo4j Backend]        │
│   Project Memory Agent       │  Version Control Agent       │
│        (Agent 7)             │       (Agent 8)              │
│              [Qdrant + RAG Backend]                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 INTELLIGENCE LAYER                          │
│  Compliance Validation Agent │  Predictive RFI Agent        │
│        (Agent 5)             │       (Agent 6)              │
│                    Risk Prediction Layer                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   ACTION LAYER                              │
│  Notification Agent (Agent 9) │  Learning Agent (Agent 10)  │
│  [WhatsApp/Slack/Teams/Email] │  [Continuous Training Loop] │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  PRESENTATION LAYER                         │
│  Worker Glasses HUD  │  Mobile App  │  Engineer Dashboard   │
│                      │              │  Executive Dashboard  │
│                 Digital Twin Viewer                         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Orchestration Layer
- **Primary:** OpenClaw (workflow orchestration, human approval loops, audit logging)
- **On-Prem Deployment:** NemoClaw (for enterprise clients who cannot use cloud AI)
- **Agent Communication:** Message bus via Redis Streams or RabbitMQ
- **API Gateway:** FastAPI (Python) with async support

### 3.3 Infrastructure Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| Container Runtime | Docker + Docker Compose | Reproducible deployments |
| Orchestration (prod) | Kubernetes (K8s) | Horizontal scaling |
| API Layer | FastAPI (Python 3.11+) | Async, fast, typed |
| Message Bus | Redis Streams | Low-latency agent communication |
| Graph Database | Neo4j 5.x (Community/Enterprise) | Native graph for project relationships |
| Vector Database | Qdrant | Fast hybrid search, RAG |
| Cache | Redis | Session, rate limiting |
| File Storage | MinIO (S3-compatible) | Photos, drawings, documents (on-prem) |
| SQL Database | PostgreSQL 15+ | Structured data, user management |
| LLM Serving | vLLM or Ollama | Qwen3 / Llama 3.3 serving |
| Monitoring | Prometheus + Grafana | System health |
| Logging | Loki + Grafana | Centralized logs |
| CI/CD | GitHub Actions | Automated testing and deployment |

---

## SECTION 4: AGENT SPECIFICATIONS (COMPLETE)

---

### AGENT 1: Vision Understanding Agent

**Purpose:** Convert raw camera frames from glasses or mobile into structured asset understanding.

**Responsibilities:**
- Real-time object detection of construction assets
- Instance segmentation for precise asset boundaries
- Scene understanding and zone context
- Asset classification and tagging

**Input:**
```json
{
  "frame": "<base64_encoded_image_or_video_stream>",
  "timestamp": "ISO8601",
  "location": {"zone_id": "A12", "gps": {"lat": 0.0, "lon": 0.0}},
  "worker_id": "W-001",
  "project_id": "P-001"
}
```

**Output:**
```json
{
  "assets_detected": [
    {
      "asset_id": "uuid",
      "asset_type": "rebar",
      "confidence": 0.97,
      "bounding_box": {"x1": 120, "y1": 80, "x2": 340, "y2": 290},
      "segmentation_mask": "<base64_mask>",
      "attributes": {
        "material": "steel",
        "orientation": "horizontal",
        "count": 12
      }
    }
  ],
  "scene_context": "rebar_installation_in_progress",
  "zone_id": "A12",
  "frame_id": "uuid",
  "processing_time_ms": 87
}
```

**Models (in order of execution):**

| Model | Role | Framework | Notes |
|-------|------|-----------|-------|
| YOLOv11x | Primary object detection | Ultralytics | Fine-tune on construction datasets |
| GroundingDINO | Open-vocabulary detection | HuggingFace Transformers | Zero-shot asset detection |
| SAM2 (Segment Anything 2) | Instance segmentation | Meta AI | Run after YOLO bounding box |

**Fine-tuning Datasets:**
- Construction Site Monitoring Dataset (Kaggle)
- Roboflow Construction Datasets (rebar, conduit, beam, valve, electrical panel)
- COCO classes relevant to construction
- MVTec AD (for manufacturing anomaly detection)
- NEU Surface Defect Dataset

**Hardware Requirements:**
- GPU: NVIDIA RTX 4090 / A100 (training), NVIDIA Jetson Orin (edge inference)
- Inference target: <100ms per frame at 1080p
- Edge deployment: TensorRT optimization, INT8 quantization

**API Endpoint:**
```
POST /api/v1/agents/vision/analyze
WebSocket /ws/v1/agents/vision/stream
```

**Technology Stack:**
```
Python 3.11
ultralytics==8.x
transformers==4.x
segment-anything-2
torch==2.x
torchvision
opencv-python
fastapi
```

---

### AGENT 2: Physical Measurement Agent

**Purpose:** Extract real-world metric measurements from images without physical contact.

**Responsibilities:**
- Calculate spacing, overlap, length, angle, clearance
- Monocular depth estimation
- Reference-object-based calibration
- ArUco marker-based metric scaling
- Output measurements with confidence bounds

**Input:**
```json
{
  "frame_id": "uuid",
  "image": "<base64>",
  "assets": ["asset_id_1", "asset_id_2"],
  "measurement_request": {
    "type": "spacing",
    "between": ["rebar_1", "rebar_2"],
    "unit": "mm"
  },
  "calibration": {
    "method": "aruco",
    "marker_size_mm": 100
  }
}
```

**Output:**
```json
{
  "measurements": [
    {
      "measurement_id": "uuid",
      "type": "spacing",
      "value": 190.4,
      "unit": "mm",
      "confidence": 0.93,
      "method_used": "aruco_calibrated",
      "depth_map_path": "s3://bucket/depth/frame_uuid.npy"
    }
  ]
}
```

**Models:**

| Model | Role | Notes |
|-------|------|-------|
| Depth Anything V2 | Monocular relative depth | HuggingFace, fast inference |
| Metric3D v2 | Metric depth estimation | Absolute metric output |
| ArUco OpenCV | Marker-based calibration | Most accurate when markers present |

**Calibration Strategy (Priority Order):**
1. ArUco markers present → Use marker-based metric calibration (highest accuracy)
2. Known reference object (hardhat, brick, standard pipe) → Reference-object calibration
3. No reference → Metric3D monocular estimation (report lower confidence)

**Measurement Types Supported:**
- `spacing` — distance between two parallel elements
- `overlap` — overlap length of two elements
- `clearance` — minimum gap between element and wall/ceiling/floor
- `angle` — angular deviation from reference
- `length` — total length of detected element
- `diameter` — pipe or rebar diameter

**Technology Stack:**
```
Python 3.11
depth-anything-v2
metric3d
opencv-python (ArUco)
numpy
scipy
```

---

### AGENT 3: Drawing Intelligence Agent

**Purpose:** Parse engineering drawings, BIM exports, CAD files, and specifications to extract structured dimensional and material requirements.

**Responsibilities:**
- Extract dimensions, tolerances, material specifications from drawings
- Parse revision information and drawing metadata
- Convert unstructured document content into structured JSON
- Index content into vector database for RAG retrieval

**Input:**
```json
{
  "document": {
    "type": "drawing",
    "format": "pdf",
    "content": "<base64_pdf>",
    "metadata": {
      "project_id": "P-001",
      "drawing_number": "S-101",
      "revision": "R5",
      "discipline": "structural"
    }
  }
}
```

**Output:**
```json
{
  "drawing_id": "uuid",
  "drawing_number": "S-101",
  "revision": "R5",
  "approved_date": "2024-11-15",
  "extracted_specs": [
    {
      "element_type": "rebar",
      "zone": "A12",
      "spec_id": "uuid",
      "parameter": "spacing",
      "value": 150,
      "unit": "mm",
      "tolerance": {"min": 140, "max": 160},
      "note": "As per ACI 318-19 Section 7.7"
    }
  ],
  "text_chunks": [
    {
      "chunk_id": "uuid",
      "text": "...",
      "page": 3,
      "embedding_vector": null
    }
  ]
}
```

**Models:**

| Model | Role | Use Case |
|-------|------|----------|
| Docling | PDF/drawing parsing | Complex engineering PDFs |
| Marker | Markdown extraction from PDFs | Fast extraction |
| LlamaParse | Advanced document AI | Tables, structured data |
| PaddleOCR | OCR for scanned drawings | Legacy drawing formats |
| DocTR | OCR alternative | Multi-language support |

**Processing Pipeline:**
```
Raw Document
    → Format Detection
    → Docling Parser (primary)
    → PaddleOCR (if scanned)
    → Dimension Extractor (regex + LLM)
    → Spec Structured Output (Qwen3/Llama 3.3 with JSON mode)
    → Qdrant Indexing (BGE-M3 embeddings)
    → Neo4j Node Creation (Drawing node + Spec relationships)
```

**Supported Formats:**
- PDF (vector and rasterized)
- DXF/DWG (via ezdxf)
- IFC (BIM via IfcOpenShell)
- Excel BOQ files
- Word specification documents

**Technology Stack:**
```
Python 3.11
docling
marker-pdf
llama-parse
paddleocr
doctr
ezdxf
ifcopenshell
qdrant-client
sentence-transformers (BGE-M3)
```

---

### AGENT 4: Project Knowledge Graph Agent

**Purpose:** Maintain a live, queryable graph of all project entities, relationships, and current state.

**Database:** Neo4j 5.x

**Graph Schema:**

**Nodes:**
```cypher
(:Project {id, name, type, start_date, status})
(:Zone {id, name, level, coordinates, status})
(:Asset {id, type, installed_date, status, current_spec_version})
(:Drawing {id, number, revision, discipline, approved_date, file_url})
(:Specification {id, parameter, value, unit, tolerance_min, tolerance_max, standard_ref})
(:RFI {id, subject, status, created_date, resolved_date, priority})
(:Inspection {id, result, date, inspector_id, photos})
(:Worker {id, name, role, certifications})
(:Engineer {id, name, discipline, contact})
(:BOQItem {id, description, quantity, unit, material_spec})
(:ChangeOrder {id, description, date, approved_by, cost_impact})
(:Observation {id, timestamp, agent_source, raw_data, processed_result})
```

**Relationships:**
```cypher
(Zone)-[:BELONGS_TO]->(Project)
(Asset)-[:LOCATED_IN]->(Zone)
(Asset)-[:GOVERNED_BY]->(Specification)
(Asset)-[:REFERENCED_IN]->(Drawing)
(Specification)-[:DEFINED_IN]->(Drawing)
(RFI)-[:RELATES_TO]->(Zone)
(RFI)-[:ABOUT]->(Asset)
(RFI)-[:RESOLVED_BY]->(Engineer)
(Inspection)-[:INSPECTS]->(Asset)
(Inspection)-[:CONDUCTED_BY]->(Worker)
(Observation)-[:OBSERVED]->(Asset)
(Observation)-[:IN_ZONE]->(Zone)
(Drawing)-[:SUPERSEDES]->(Drawing)
(ChangeOrder)-[:MODIFIES]->(Specification)
```

**Key Cypher Queries (must be implemented as named procedures):**

```cypher
-- Get all failing assets in a zone
MATCH (z:Zone {id: $zone_id})<-[:LOCATED_IN]-(a:Asset)<-[:INSPECTS]-(i:Inspection {result: "FAIL"})
RETURN a, i ORDER BY i.date DESC

-- Find historical RFIs for same asset type
MATCH (r:RFI)-[:ABOUT]->(a:Asset {type: $asset_type})
WHERE r.status = "resolved"
RETURN r, a ORDER BY r.created_date DESC LIMIT 20

-- Get current approved drawing for zone
MATCH (z:Zone {id: $zone_id})<-[:BELONGS_TO]-(p:Project)<-[:BELONGS_TO]-(d:Drawing)
WHERE NOT (d)-[:SUPERSEDES]->()
RETURN d ORDER BY d.approved_date DESC

-- Risk score aggregation for zone
MATCH (z:Zone {id: $zone_id})<-[:LOCATED_IN]-(a:Asset)<-[:INSPECTS]-(i:Inspection)
WHERE i.date > datetime() - duration('P30D')
RETURN z.id, 
       count(CASE WHEN i.result = 'FAIL' THEN 1 END) as failures,
       count(i) as total,
       toFloat(count(CASE WHEN i.result = 'FAIL' THEN 1 END)) / count(i) as risk_score
```

**API Endpoints:**
```
POST /api/v1/graph/nodes
POST /api/v1/graph/relationships
GET  /api/v1/graph/zone/{zone_id}/status
GET  /api/v1/graph/project/{project_id}/risk-map
POST /api/v1/graph/query (Cypher passthrough for engineers)
GET  /api/v1/graph/asset/{asset_id}/history
```

**Technology Stack:**
```
neo4j==5.x
neo4j-driver (Python)
FastAPI
Pydantic v2
```

---

### AGENT 5: Compliance Validation Agent

**Purpose:** Compare measured physical values against specification requirements and output a structured pass/fail verdict with confidence score.

**Responsibilities:**
- Accept measured value + spec value + tolerance
- Apply validation logic
- Output PASS / FAIL / UNCERTAIN with confidence
- Generate natural language explanation for worker
- Trigger downstream agents on FAIL

**Input:**
```json
{
  "observation_id": "uuid",
  "asset_id": "uuid",
  "zone_id": "A12",
  "measurement": {
    "parameter": "spacing",
    "measured_value": 190,
    "unit": "mm",
    "confidence": 0.93
  },
  "specification": {
    "spec_id": "uuid",
    "expected_value": 150,
    "tolerance_min": 140,
    "tolerance_max": 160,
    "unit": "mm",
    "standard_ref": "ACI 318-19 Section 7.7.1"
  }
}
```

**Output:**
```json
{
  "validation_id": "uuid",
  "result": "FAIL",
  "confidence": 0.96,
  "deviation": {
    "absolute": 30,
    "percentage": 20.0,
    "direction": "over"
  },
  "severity": "HIGH",
  "explanation": {
    "worker_message": "Rebar spacing is 190mm. Specification requires 150mm ±10mm. Deviation is 30mm above maximum. STOP WORK.",
    "engineer_message": "Zone A12, Rebar Asset A-042: Measured spacing 190mm exceeds tolerance (140-160mm) per ACI 318-19 §7.7.1. Immediate correction required.",
    "glasses_audio": "FAIL. Rebar spacing exceeds tolerance by 30 millimeters. Stop work. Await engineer instruction."
  },
  "downstream_actions": ["trigger_notification_agent", "trigger_predictive_rfi_agent"],
  "timestamp": "ISO8601"
}
```

**Validation Logic:**
```python
def validate(measured: float, expected: float, tol_min: float, tol_max: float, meas_confidence: float):
    if meas_confidence < 0.75:
        return "UNCERTAIN", meas_confidence
    if tol_min <= measured <= tol_max:
        return "PASS", meas_confidence
    deviation_pct = abs(measured - expected) / expected * 100
    if deviation_pct > 25:
        severity = "CRITICAL"
    elif deviation_pct > 10:
        severity = "HIGH"
    else:
        severity = "MEDIUM"
    return "FAIL", meas_confidence, severity
```

**Severity Levels:**
| Severity | Condition | Worker Action | Engineer Action |
|----------|-----------|---------------|-----------------|
| LOW | <5% deviation | Warning shown | Log only |
| MEDIUM | 5-10% deviation | Yellow alert | Notification sent |
| HIGH | 10-25% deviation | Red alert + Stop advisory | Immediate ticket |
| CRITICAL | >25% deviation | STOP WORK mandatory | Emergency escalation |

---

### AGENT 6: Predictive RFI Agent

**Purpose:** The most important innovation. Predict future RFIs before workers encounter them by analyzing historical patterns, current deviations, and project schedule context.

**Responsibilities:**
- Analyze current zone activity against historical RFI patterns
- Score zones for RFI probability in next 7/14/30 days
- Generate pre-emptive alerts for engineers
- Suggest design clarifications before work begins

**Input:**
```json
{
  "project_id": "P-001",
  "zone_id": "A12",
  "current_activity": {
    "work_type": "rebar_installation",
    "drawing_refs": ["S-101-R5", "S-102-R3"],
    "scheduled_completion": "2024-12-01"
  }
}
```

**Output:**
```json
{
  "zone_id": "A12",
  "prediction_horizon_days": 14,
  "rfi_risk_score": 0.87,
  "predicted_rfis": [
    {
      "prediction_id": "uuid",
      "rfi_category": "rebar_overlap_ambiguity",
      "probability": 0.87,
      "basis": "14 similar RFIs in 8 comparable projects using same design pattern",
      "similar_historical_rfis": ["RFI-2023-0412", "RFI-2022-0889"],
      "recommended_pre_action": "Engineer to clarify lap splice length at column C4 junction before Zone A12 rebar installation begins",
      "drawing_sections_to_clarify": ["S-101 Detail 4A", "S-102 Section B-B"]
    }
  ],
  "confidence": 0.82
}
```

**Prediction Pipeline:**
```
Zone Activity Context
    → Historical RFI Retrieval (Neo4j + Qdrant similarity search)
    → Pattern Matching (similar project, similar design, similar phase)
    → Schedule Context Injection (what's being built next)
    → LLM Risk Synthesis (Qwen3 with project context)
    → Risk Score Calculation
    → Pre-emptive Action Recommendation
    → Push to Engineer Dashboard
```

**Data Sources for Prediction:**
1. Neo4j: All historical RFIs linked to asset types and zones
2. Qdrant: Semantic similarity search over resolved RFI descriptions
3. Schedule data: What activities are upcoming in this zone
4. Current deviation data: Are measurements already drifting?

---

### AGENT 7: Project Memory Agent

**Purpose:** Instantly retrieve any past decision, approval, conversation, or document from project history using natural language query.

**Responsibilities:**
- Index all project communications (emails, meeting minutes, WhatsApp exports, change orders)
- Answer natural language questions about past decisions
- Surface approvals and rejections as evidence
- Link memory results back to Neo4j nodes

**Input:**
```json
{
  "query": "Can I install the conduit along the east wall of Zone B3?",
  "project_id": "P-001",
  "zone_id": "B3",
  "worker_id": "W-022"
}
```

**Output:**
```json
{
  "answer": "YES — Engineer Sarah Chen approved alternative east-wall conduit routing in Zone B3 on June 4, 2024.",
  "confidence": 0.94,
  "evidence": [
    {
      "source_type": "meeting_minutes",
      "source_id": "MM-2024-06-04",
      "excerpt": "...[paraphrased: east wall routing approved]...",
      "date": "2024-06-04",
      "approved_by": "Sarah Chen, MEP Engineer",
      "document_url": "s3://bucket/minutes/MM-2024-06-04.pdf",
      "page": 3
    }
  ],
  "related_drawing": "M-045-R2",
  "caution": null
}
```

**RAG Architecture:**
```
Documents Ingested:
  - Emails (EML/MSG → text)
  - Meeting minutes (PDF/DOCX → text)
  - WhatsApp exports (TXT → structured)
  - RFIs (PDF/structured → text)
  - Change orders (PDF → text)
  - BOQ items (XLSX → text)

Ingestion Pipeline:
  Raw Document
      → Format Parser (Docling/LlamaParse)
      → Text Chunking (512 tokens, 64 overlap)
      → BGE-M3 Embedding
      → Qdrant Upsert (project_id namespace)
      → Neo4j link (chunk → source document node)

Retrieval Pipeline:
  Natural Language Query
      → BGE-M3 Query Embedding
      → Qdrant Hybrid Search (BM25 + Vector, top-10)
      → Reranker (BGE-Reranker-v2)
      → Context Window Assembly
      → Qwen3/Llama 3.3 Answer Generation (with citations)
      → Answer + Evidence JSON
```

**Vector DB Schema (Qdrant):**
```python
collection_name = f"project_{project_id}_memory"
vectors_config = VectorParams(size=1024, distance=Distance.COSINE)
payload_schema = {
    "source_type": str,     # email | meeting | rfi | change_order | whatsapp
    "source_id": str,
    "date": str,
    "zone_ids": list[str],
    "asset_types": list[str],
    "approved_by": str,
    "project_id": str,
    "chunk_index": int
}
```

---

### AGENT 8: Version Control Agent

**Purpose:** Prevent workers from using outdated drawing revisions by automatically detecting and alerting on revision mismatches.

**Responsibilities:**
- Scan physical drawing in worker's hand via camera
- Extract drawing number, revision, date using OCR
- Compare with latest approved revision in Knowledge Graph
- Alert worker immediately if mismatch detected

**Input:**
```json
{
  "frame": "<base64_image_of_drawing>",
  "project_id": "P-001",
  "worker_id": "W-012"
}
```

**Output:**
```json
{
  "drawing_detected": {
    "number": "S-101",
    "revision": "R3",
    "date": "2024-08-10",
    "ocr_confidence": 0.98
  },
  "current_approved": {
    "number": "S-101",
    "revision": "R5",
    "date": "2024-11-02",
    "approved_by": "David Park, SE",
    "key_changes": "Rebar spacing in Zone A12 changed from 200mm to 150mm"
  },
  "status": "OUTDATED",
  "alert": {
    "severity": "CRITICAL",
    "glasses_audio": "WARNING. Drawing S-101 Revision 3 detected. Current approved revision is Revision 5. DO NOT BUILD from this drawing.",
    "worker_message": "Stop. You are holding drawing S-101-R3. Latest approved is R5 (Nov 2, 2024). R5 changes rebar spacing in your zone.",
    "action": "STOP_WORK_UNTIL_CORRECT_DRAWING_OBTAINED"
  }
}
```

**OCR Pipeline:**
```
Camera Frame of Drawing
    → PaddleOCR (text extraction from title block)
    → Regex Extraction (drawing number, revision, date patterns)
    → Neo4j Lookup (latest approved revision for this number)
    → Revision Comparison
    → Alert Generation
```

**Drawing Title Block Regex Patterns:**
```python
patterns = {
    "drawing_number": r"DWG\s*NO[.:]\s*([A-Z0-9\-]+)",
    "revision": r"REV[.:]\s*([A-Z0-9]+)",
    "revision_alt": r"REVISION\s+([A-Z0-9]+)",
    "date": r"DATE[.:]\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})"
}
```

---

### AGENT 9: Notification Agent

**Purpose:** Route alerts, incidents, and tasks to the right people via the right channel at the right time.

**Responsibilities:**
- Receive severity-classified alerts from other agents
- Route based on severity, project role, and preference
- Create formal RFI or incident tickets when required
- Maintain audit log of all notifications

**Input:**
```json
{
  "event_type": "COMPLIANCE_FAIL",
  "severity": "HIGH",
  "zone_id": "A12",
  "asset_id": "uuid",
  "worker_id": "W-022",
  "message": "Rebar spacing 190mm exceeds tolerance. Expected 150mm ±10mm.",
  "evidence": {
    "photo_url": "s3://bucket/obs/uuid.jpg",
    "measurement_report": "s3://bucket/reports/uuid.pdf"
  },
  "routing": {
    "engineer_id": "E-005",
    "escalation_path": ["E-005", "PM-001"]
  }
}
```

**Routing Matrix:**
| Severity | Primary Channel | Secondary | Escalation | SLA |
|----------|----------------|-----------|------------|-----|
| LOW | In-app notification | — | — | 24h |
| MEDIUM | WhatsApp + In-app | Email | — | 4h |
| HIGH | WhatsApp + Slack + Email | SMS | PM after 2h | 1h |
| CRITICAL | All channels simultaneously | Phone call trigger | PM + Director immediately | 15min |

**Integrations:**
```python
integrations = {
    "whatsapp": "Twilio WhatsApp API",
    "slack": "Slack Bolt SDK",
    "teams": "Microsoft Graph API",
    "email": "SendGrid / SMTP",
    "sms": "Twilio SMS"
}
```

**Notification Payload (WhatsApp Example):**
```
🔴 FAIL ALERT — ASK THE WALL
Project: Downtown Tower Phase 2
Zone: A12 | Asset: Rebar Grid
Issue: Spacing 190mm (Spec: 150mm ±10mm)
Deviation: +30mm | Severity: HIGH
Worker: Ali Hassan (W-022)
📸 Photo: [link]
📋 Report: [link]
Action Required: Review and approve correction
Reply CONFIRM to acknowledge
```

**OpenClaw Integration:**
- Each FAIL alert creates an OpenClaw task
- Task includes: zone, asset, deviation, evidence, assigned engineer
- Human approval loop for STOP WORK decisions
- Full audit trail of all actions

---

### AGENT 10: Learning Agent

**Purpose:** Capture every resolved issue as structured training data so the system improves continuously across projects.

**Responsibilities:**
- Capture question → context → answer → outcome loops
- Store resolution data in searchable format
- Generate training datasets for model fine-tuning
- Surface lessons learned for similar future scenarios

**Data Captured Per Incident:**
```json
{
  "incident_id": "uuid",
  "project_id": "P-001",
  "zone_id": "A12",
  "asset_type": "rebar",
  "issue_type": "spacing_violation",
  "measurement_at_detection": 190,
  "spec_value": 150,
  "resolution": {
    "action_taken": "Rebar repositioned to 152mm",
    "time_to_resolve_hours": 2.5,
    "resolved_by": "E-005",
    "resolution_notes": "Temporary support form caused misalignment. Corrected before concrete pour.",
    "rework_required": false
  },
  "photos": {
    "before": "s3://bucket/incidents/uuid_before.jpg",
    "after": "s3://bucket/incidents/uuid_after.jpg"
  },
  "outcome_metrics": {
    "cost_avoided_usd": 12000,
    "time_avoided_hours": 16
  },
  "created_at": "ISO8601",
  "tags": ["rebar", "spacing", "formwork_interference", "zone_a12"]
}
```

**Learning Loop:**
```
Resolved Incident
    → Structured Storage (PostgreSQL)
    → Vector Indexing (Qdrant — for similarity retrieval)
    → Neo4j Update (resolution node linked to asset + zone)
    → Fine-tuning Dataset Accumulation
    → Monthly: Export JSONL for LLM fine-tuning
    → Quarterly: Retrain Predictive RFI model
```

---

## SECTION 5: LLM LAYER

### 5.1 Primary LLM

**Preferred:** Qwen3-32B (instruction-tuned)
**Alternative:** Llama 3.3-70B-Instruct

**Deployment:** vLLM serving with OpenAI-compatible API
```bash
vllm serve Qwen/Qwen3-32B-Instruct \
  --tensor-parallel-size 4 \
  --max-model-len 32768 \
  --enable-prefix-caching
```

### 5.2 Embeddings
**Model:** BGE-M3 (BAAI/bge-m3)
- Supports: Dense + Sparse + Multi-vector
- Dimension: 1024
- Languages: Multilingual (Arabic, Hindi, English — key for construction sites)

### 5.3 Reranker
**Model:** BGE-Reranker-v2-M3 (BAAI/bge-reranker-v2-m3)

### 5.4 LLM System Prompt Template
```
You are the ASK THE WALL AI Digital Foreman.

You are operating on a live construction site in Zone {zone_id} of Project {project_name}.

Current context:
- Detected asset: {asset_type}
- Measurement: {measured_value} {unit}
- Specification: {spec_value} {unit} (tolerance: {tol_min}–{tol_max})
- Validation result: {validation_result}
- Historical context: {rag_context}

Your responsibilities:
1. Provide a clear, immediate instruction to the field worker
2. Generate an engineer notification if severity >= MEDIUM
3. Reference the specific drawing and specification clause
4. Predict if this issue is likely to recur based on historical patterns

Worker communication style:
- Simple language
- Maximum 2 sentences for glasses display
- Action-oriented
- No jargon

Engineer communication style:
- Technical and precise
- Include spec reference, deviation magnitude, suggested resolution
- Include historical parallel cases if available

Respond in JSON format as specified in the output schema.
```

---

## SECTION 6: UI/UX SPECIFICATIONS

### 6.1 Meta Smart Glasses HUD

**Design Principles:** Minimal, non-distracting, action-oriented

**HUD Layout:**
```
┌──────────────────────────────────┐
│ ZONE A12          [PROJECT NAME] │  ← Top bar (always visible)
│                                  │
│                                  │
│      [DETECTED ASSET OVERLAY]    │  ← Center: bounding box on asset
│      Rebar Grid — 12 bars        │
│                                  │
│                                  │
│ ████████████████  FAIL  190mm   │  ← Bottom bar
│ Spec: 150mm ±10mm  Deviation +30 │
└──────────────────────────────────┘

Colors:
- PASS: #00C851 (green)
- FAIL: #FF4444 (red)
- UNCERTAIN: #FFBB33 (amber)
- INFO: #33B5E5 (blue)
```

**Audio Feedback:**
- PASS: Short positive chime + "Conduit spacing compliant."
- FAIL: Alert tone + "FAIL. Rebar spacing exceeds tolerance by 30 millimeters. Stop work."
- UNCERTAIN: Neutral tone + "Measurement uncertain. Manual verification recommended."
- VERSION ALERT: Urgent tone + "Warning. Outdated drawing detected. Revision 3. Current is Revision 5."

### 6.2 Worker Mobile App

**Framework:** React Native (iOS + Android)

**Tab Structure:**
```
Bottom Tabs:
├── 📷 SCAN         — Camera view with AR overlay
├── ⚠️  ISSUES       — Active FAIL items assigned to this worker
├── 📜 HISTORY      — Past scans and resolutions
├── 💬 ASK AI       — Natural language project memory query
└── 👤 PROFILE      — Worker profile, certifications, notifications
```

**Scan Screen:**
- Camera feed with real-time asset bounding boxes
- Live compliance status overlay
- Tap asset for detailed measurement report
- One-tap photo capture for evidence

**Ask AI Screen:**
- Natural language input field
- Voice input button (critical for field use)
- Shows source evidence with date and approver name
- Drawing reference links

### 6.3 Engineer Dashboard (Web)

**Framework:** Next.js 14 + TypeScript + Tailwind CSS

**Layout:**
```
Sidebar Navigation:
├── 🗺️  Live Site Map        — Real-time zone status heatmap
├── ⚠️  Active Issues        — FAIL alerts requiring action
├── 🔮 Predicted RFIs       — AI-predicted future issues
├── 🔥 High Risk Zones      — Risk scoring by zone
├── 📐 Drawing Versions     — Latest vs field revisions
├── 📊 Knowledge Graph      — Interactive Neo4j explorer
├── 🏗️  Digital Twin        — Live project twin view
└── 🔔 Notifications        — All alerts and actions
```

**Live Site Map:**
- Floor plan / site plan base layer
- Zones color-coded by risk score (green/amber/red)
- Real-time observation dots appearing on new scans
- Click zone → zone detail drawer
- Heatmap mode: density of FAIL observations

**Active Issues Panel:**
```
[CRITICAL] Zone A12 — Rebar Spacing 190mm (Spec 150mm)        2 min ago
Worker: Ali Hassan | Photo | Measurement Report | RESOLVE | ESCALATE

[HIGH] Zone B3 — Conduit outdated drawing R3 (Current R5)     8 min ago
Worker: James Osei | Photo | Drawing Diff | RESOLVE | ESCALATE
```

**Predicted RFI Panel:**
```
🔮 Zone A12 — Rebar overlap ambiguity at column C4 junction
   Probability: 87% | Basis: 14 similar RFIs in comparable projects
   Recommended action: Clarify lap splice length before Zone A12 resumes
   [VIEW SIMILAR RFIs] [CREATE CLARIFICATION] [DISMISS]
```

### 6.4 Executive Dashboard (Web)

**KPI Cards (Real-time):**
```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│  RFIs Avoided│ Rework Preven│  Time Saved  │  Cost Saved  │
│     47       │   12 events  │  340 hours   │  $187,000    │
│  ↑23% vs LM  │  ↑15% vs LM  │  ↑31% vs LM  │  ↑28% vs LM  │
└──────────────┴──────────────┴──────────────┴──────────────┘

┌──────────────┬──────────────┬──────────────┐
│ Safety Risks │  Active FAILs│  Open RFIs   │
│  Detected: 8 │     3        │     0        │
│  Resolved: 7 │              │  (AI handled)│
└──────────────┴──────────────┴──────────────┘
```

**Trend Charts:**
- Daily FAIL rate by zone (line chart)
- RFI prediction accuracy over time
- Cost avoidance cumulative (area chart)
- Time-to-resolution trend

---

## SECTION 7: DIGITAL TWIN LAYER

### 7.1 Definition
A live, continuously-updated virtual representation of the physical project that combines:
- Engineering drawings and BIM model
- Current observations and measurements
- Compliance status by zone and asset
- Predicted future state

### 7.2 Technical Implementation

**BIM Integration:**
```python
# IFC file parsing
import ifcopenshell
ifc_model = ifcopenshell.open("project.ifc")
zones = ifc_model.by_type("IfcSpace")
assets = ifc_model.by_type("IfcElement")
```

**Twin Update Mechanism:**
```
New Observation Event
    → Agent 1 + Agent 2 output
    → Twin State Manager
    → Update Asset node in Neo4j (status, last_measured, compliance_status)
    → Push update to dashboard via WebSocket
    → Update zone risk score
    → Trigger visualization refresh
```

**WebSocket Events:**
```json
{
  "event": "observation_update",
  "zone_id": "A12",
  "asset_id": "uuid",
  "compliance_status": "FAIL",
  "timestamp": "ISO8601"
}
```

---

## SECTION 8: DATA PIPELINE

### 8.1 Ingestion Sources
| Source | Format | Ingestion Method | Frequency |
|--------|--------|-----------------|-----------|
| Camera frames | JPEG/MP4 | WebSocket stream | Real-time |
| Drawings | PDF/DXF/IFC | REST upload | On change |
| Emails | EML/MSG | IMAP connector | Hourly |
| WhatsApp | ZIP export | Manual upload | Weekly |
| Meeting minutes | PDF/DOCX | REST upload | Per meeting |
| RFIs | PDF | REST upload | On creation |
| Schedule | XER/XML | REST upload | Weekly |
| BOQ | XLSX | REST upload | On revision |

### 8.2 Data Flow
```
Raw Input
    → Validation (schema, format, size)
    → Virus scan (ClamAV)
    → MinIO storage (raw bucket)
    → Processing queue (Redis Streams)
    → Agent processing
    → Structured output
    → PostgreSQL (metadata) + Neo4j (relationships) + Qdrant (vectors)
    → MinIO (processed files)
    → Event bus (downstream agents)
```

---

## SECTION 9: SECURITY AND COMPLIANCE

### 9.1 Authentication
- JWT tokens with 8-hour expiry
- Role-based access control (RBAC): Worker, Engineer, PM, Admin, Executive
- Multi-factor authentication for Engineer and above
- API key authentication for agent-to-agent communication

### 9.2 Data Security
- All data encrypted at rest (AES-256)
- All API traffic over TLS 1.3
- Drawing and document access logs for audit
- On-prem NemoClaw deployment for clients requiring air-gap

### 9.3 Audit Trail
- Every agent action logged with timestamp, input hash, output hash
- Human approval events recorded (who approved, when, from what device)
- Immutable audit log in PostgreSQL with append-only table

### 9.4 Construction Industry Compliance Considerations
- Document retention policies (7 years standard)
- RFI audit trail requirements
- Drawing version control traceability
- Inspection record integrity

---

## SECTION 10: OPEN SOURCE DATASETS AND TRAINING

### 10.1 Computer Vision Datasets

**Construction:**
| Dataset | Classes | Use |
|---------|---------|-----|
| Construction Site Monitoring (Kaggle) | Workers, machinery, materials | Scene understanding |
| Roboflow Construction Universe | Rebar, conduit, beam, valve | Asset detection fine-tuning |
| COCO (construction classes) | General objects | Base model |
| Building Defect Dataset | Cracks, spalling, delamination | Defect detection |
| Concrete Crack Dataset | Crack types | Surface inspection |
| Rebar Detection Dataset | Rebar grids | Primary use case |
| Bridge Damage Dataset | Structural damage | Infrastructure module |

**Manufacturing:**
| Dataset | Classes | Use |
|---------|---------|-----|
| MVTec AD | 15 industrial categories | Anomaly detection |
| NEU Surface Defect | Steel surface defects | Steel inspection |
| Severstal Steel Defect | Steel manufacturing defects | Steel inspection |
| PCB Defect Dataset | Electronic defects | Electronics manufacturing |
| DAGM | Industrial texture defects | General manufacturing |

**Infrastructure:**
| Dataset | Classes | Use |
|---------|---------|-----|
| RDD2022 | Road damage categories | Road inspection |
| CrackForest | Pavement cracks | Surface inspection |
| Aerial Infrastructure Inspection | Power lines, towers | Utility inspection |

### 10.2 Model Fine-tuning Strategy

```
Base Model: YOLOv11x-seg (detection + segmentation)

Fine-tuning Pipeline:
1. Aggregate all construction datasets
2. Harmonize class labels (unified taxonomy)
3. Augmentation: random rotate, flip, brightness, blur, occlusion
4. Train on A100 80GB x 4 GPUs
5. Validate on held-out site photos
6. Export: ONNX + TensorRT (for Jetson edge deployment)
7. Deploy: Triton Inference Server
```

---

## SECTION 11: API REFERENCE (COMPLETE)

### 11.1 Base URL
```
Production:  https://api.askthewall.ai/api/v1
Development: http://localhost:8000/api/v1
```

### 11.2 Core Endpoints

```
Authentication:
POST   /auth/login
POST   /auth/refresh
POST   /auth/logout

Vision Agent:
POST   /agents/vision/analyze          # Single frame analysis
WS     /ws/agents/vision/stream        # Real-time stream

Measurement Agent:
POST   /agents/measurement/calculate   # Measurement from frame

Drawing Intelligence:
POST   /agents/drawing/ingest          # Upload and process drawing
GET    /agents/drawing/{id}            # Get processed drawing
GET    /agents/drawing/latest/{number} # Get latest revision

Knowledge Graph:
POST   /graph/query                    # Cypher query (engineers only)
GET    /graph/zone/{id}               # Zone status and assets
GET    /graph/project/{id}/risk-map   # Full risk map
GET    /graph/asset/{id}/history      # Asset observation history

Compliance:
POST   /agents/compliance/validate     # Manual validation request
GET    /compliance/report/{zone_id}   # Zone compliance report

Predictive RFI:
GET    /agents/rfi/predict/{zone_id}  # RFI prediction for zone
GET    /agents/rfi/project/{id}       # All predictions for project

Project Memory:
POST   /agents/memory/query           # Natural language query
POST   /agents/memory/ingest          # Ingest document into memory

Notifications:
GET    /notifications/                # List notifications
POST   /notifications/acknowledge     # Acknowledge notification
GET    /notifications/history         # Full history

Digital Twin:
GET    /twin/project/{id}/state       # Full twin state
WS     /ws/twin/{id}/updates          # Real-time twin updates

Analytics:
GET    /analytics/kpis/{project_id}  # Executive KPIs
GET    /analytics/trends/{project_id} # Trend data
GET    /analytics/roi/{project_id}   # ROI calculation
```

---

## SECTION 12: DEVELOPMENT ENVIRONMENT SETUP

### 12.1 Prerequisites
```bash
# System requirements
Docker Desktop 4.x (24GB RAM minimum for full stack)
NVIDIA GPU with CUDA 12.x (for local model serving)
Python 3.11+
Node.js 20+
Git
```

### 12.2 Repository Structure
```
ask-the-wall/
├── agents/
│   ├── vision/                 # Agent 1
│   ├── measurement/            # Agent 2
│   ├── drawing/                # Agent 3
│   ├── knowledge_graph/        # Agent 4
│   ├── compliance/             # Agent 5
│   ├── predictive_rfi/         # Agent 6
│   ├── memory/                 # Agent 7
│   ├── version_control/        # Agent 8
│   ├── notification/           # Agent 9
│   └── learning/               # Agent 10
├── api/                        # FastAPI gateway
├── frontend/
│   ├── mobile/                 # React Native worker app
│   ├── engineer-dashboard/     # Next.js engineer UI
│   └── executive-dashboard/    # Next.js executive UI
├── infra/
│   ├── docker-compose.yml      # Full stack local
│   ├── docker-compose.gpu.yml  # GPU-enabled override
│   ├── k8s/                    # Kubernetes manifests
│   └── terraform/              # Cloud infrastructure
├── models/
│   ├── training/               # Fine-tuning scripts
│   ├── evaluation/             # Benchmark scripts
│   └── weights/                # Model weight management
├── data/
│   ├── schemas/                # JSON schemas for all I/O
│   ├── fixtures/               # Test data
│   └── migrations/             # DB migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
    ├── architecture/
    ├── api/
    └── deployment/
```

### 12.3 Docker Compose (Full Stack)
```yaml
version: '3.9'
services:
  neo4j:
    image: neo4j:5.15-community
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/askthewall_dev
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
    volumes:
      - neo4j_data:/data

  qdrant:
    image: qdrant/qdrant:v1.7.4
    ports: ["6333:6333", "6334:6334"]
    volumes:
      - qdrant_data:/qdrant/storage

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: askthewall
      POSTGRES_USER: atw_user
      POSTGRES_PASSWORD: atw_dev_password
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports: ["9000:9000", "9001:9001"]
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    volumes:
      - minio_data:/data

  vllm:
    image: vllm/vllm-openai:latest
    runtime: nvidia
    command: >
      --model Qwen/Qwen3-32B-Instruct
      --tensor-parallel-size 4
      --max-model-len 16384
    ports: ["8080:8000"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  api:
    build: ./api
    ports: ["8000:8000"]
    environment:
      NEO4J_URI: bolt://neo4j:7687
      QDRANT_URL: http://qdrant:6333
      POSTGRES_URL: postgresql://atw_user:atw_dev_password@postgres/askthewall
      REDIS_URL: redis://redis:6379
      MINIO_URL: http://minio:9000
      LLM_BASE_URL: http://vllm:8000/v1
    depends_on:
      - neo4j
      - qdrant
      - postgres
      - redis
      - minio

volumes:
  neo4j_data:
  qdrant_data:
  postgres_data:
  minio_data:
```

---

## SECTION 13: SUCCESS METRICS (MVP)

### 13.1 Technical Metrics
| Metric | Target |
|--------|--------|
| Vision inference latency | <100ms per frame |
| End-to-end FAIL alert time | <5 seconds from detection |
| RAG query response time | <3 seconds |
| Knowledge graph query time | <500ms |
| System uptime | >99.5% |
| Vision detection accuracy (mAP50) | >0.85 on construction assets |
| Measurement accuracy | ±5% error vs physical measurement |

### 13.2 Business Metrics (Demo Day)
| Metric | Demo Target |
|--------|-------------|
| Live PASS/FAIL demo accuracy | 100% on prepared scenario |
| Predictive RFI demo | 2+ predictions shown with historical basis |
| Memory query demo | Instant answer with source citation |
<truncated 4320 bytes>
