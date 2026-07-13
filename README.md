# FieldPilot AI 🚀

FieldPilot AI is an advanced, multi-agent AI system designed to monitor construction sites in real-time using Meta Smart Glasses. It passively detects hazards, measures rebar spacing, compares real-world data against BIM models, and automatically drafts RFIs (Requests For Information) without the worker ever having to pull out a tablet or take off their gloves.

## 🏗️ The Problem We Solve
Construction delays and rework cost the industry billions of dollars annually. Current inspection software requires manual photos and tedious form-filling. 

FieldPilot AI solves this through a **10-Agent Workflow**:
- **Agent 1 (Vision):** Ingests live frames from Meta Glasses.
- **Agent 2 (Measurement):** Uses depth estimation to calculate millimeter-accurate spacing (e.g., rebar).
- **Agent 3 (Compliance):** Compares physical measurements against the digital BIM model.
- **Agent 4 (Safety):** Detects PPE compliance (hard hats, vests) and trip hazards.
- **Agent 5 (Voice NLP):** Processes natural language voice queries from the worker.
- **Agent 6 (RFI Drafter):** Automatically generates RFIs for engineer approval if a deviation is found.
- **Agent 7 (Knowledge):** Looks up exact PDF specs and building codes via RAG.
- **Agent 8 (Notification):** Sends critical alerts to the dashboard or WhatsApp.
- **Agent 9 (Memory):** Logs the incident into a Neo4j Knowledge Graph.
- **Agent 10 (Learning):** Analyzes historical graphs to predict *future* RFIs before they happen.

## 📱 Hardware & Edge Architecture

### The "Mobile Phone Relay" & Offline Mode
While workers wear the Meta Glasses, they do not hold a phone. The phone stays in their pocket acting as a **Mobile Edge Node**. 
- The glasses connect to the pocketed phone via Bluetooth. 
- The FieldPilot mobile app acts as the secure bridge to the cloud.
- **No WiFi? No Problem:** Construction sites often lack internet. We deploy lightweight, quantized AI models (like YOLOv9-tiny for safety) directly on the smartphone's Neural Processing Unit (NPU). It processes hazards locally and gives immediate Text-to-Speech (TTS) audio warnings back to the worker through the glasses' open-ear speakers.
- **Store and Forward:** When the worker re-enters a WiFi zone, the pocketed phone batch-syncs the cached incidents to the cloud.

*(Note: The mobile version of the app uses Expo Go 54.0.0. Currently, the live tunneling functionality is under maintenance, but the core architecture remains intact for edge processing).*

### Location Tracking (400+ Workers)
We do not rely on inaccurate indoor GPS. Instead, we use cheap Bluetooth Low Energy (BLE) beacons attached to concrete pillars around the site. The phone in the worker's pocket triangulates the nearest beacon and automatically tags the live video feed with the correct Zone ID (e.g., "Zone A12"). 

## 🌐 The Command Center Web Dashboard
Site managers cannot see through 400 pairs of glasses at once. The web dashboard acts as the central command hub:
- Engineers review auto-drafted RFIs and approve design deviations.
- Executives view ROI analytics (cost saved, RFIs avoided).
- **Live 3D Site Map:** By aggregating video feeds from all workers, the cloud reconstructs the site in 3D (via NeRF/Gaussian Splatting) and overlays it onto the digital BIM model. Discrepancies glow red in real-time.

---

## 🚀 How to Run the App Locally

To run the complete system, you need to start the Backend (FastAPI), the Engineer Dashboard (Next.js), and the Executive Dashboard (Next.js) concurrently.

### 1. Backend (FastAPI)
The backend powers the 10-Agent orchestration, handles the PostgreSQL database, and streams real-time data via Server-Sent Events (SSE).

```bash
cd api
pip install -r requirements.txt
python -m uvicorn main:app --reload
```
*The API will be available at `http://localhost:8000`*

### 2. Engineer Dashboard (Next.js)
This is the primary operational dashboard for reviewing active issues, the 3D site map, and predictive RFIs.

```bash
cd frontend/engineer-dashboard
npm install
npm run dev
```
*The Engineer Dashboard will be available at `http://localhost:3000`*

### 3. Executive Dashboard (Next.js)
This dashboard provides high-level ROI metrics, cost avoidance stats, and system health.

```bash
cd frontend/executive-dashboard
npm install
npm run dev
```
*The Executive Dashboard will be available at `http://localhost:3001` (or whichever port Next.js assigns if 3000 is taken).*

---

### 📲 Mobile App (Expo Go)
If you wish to run the mobile app locally (Note: Tunneling currently has issues):
```bash
cd frontend/mobile
npm install
npx expo start
```
Scan the QR code with the Expo Go app (SDK 54.0.0) on your mobile device.

## 🌟 Unique Selling Points
- **Passive "Hands-Free" Inspection:** Workers keep their gloves on and tools in hand. The AI watches and files paperwork automatically.
- **Predictive Analytics:** Our Knowledge Graph predicts where the next deviation will happen based on historical site trends.
- **Edge-NPU Processing:** True zero-latency safety alerts by utilizing the pocketed smartphone's AI chip.
