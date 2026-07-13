# FieldPilot AI: The Hands-Free Digital Foreman for the Physical World 🚀

## 💡 What Inspired Us
Construction is one of the world’s largest industries, accounting for over 10% of global GDP, yet it remains painfully undigitized. Every year, the industry bleeds trillions of dollars globally due to rework, delayed RFIs (Requests for Information), and undetected structural deviations. 

Our inspiration struck when we observed the daily struggle of a site engineer on a modern construction site. We watched an engineer attempt to balance on scaffolding in bulky Personal Protective Equipment (PPE). With a tablet in one hand, a tape measure in the other, and trying to reference a complex 2D blueprint, it became obvious: **Construction tech is forcing physical workers into a digital bottleneck.** Every time a worker has to take off their gloves to tap a screen, take a photo, or fill out a form, construction stops.

We asked ourselves a radical question: **What if the worker didn't have to hold a device at all?**

We envisioned a future where Artificial Intelligence acts as a passive, omnipresent "Digital Foreman." By utilizing Meta Smart Glasses, FieldPilot AI simply watches what the worker sees. It measures physical dimensions in real-time, cross-references digital BIM (Building Information Modeling) models, and automatically files the necessary paperwork—leaving the worker’s hands entirely free to actually build the world.

---

## 🎯 What it Does
FieldPilot AI is an advanced, multi-agent Edge-to-Cloud AI system designed to monitor construction sites in real-time using Meta Smart Glasses. It operates completely passively:
1. **Passive Inspection:** Uses computer vision to calculate millimeter-accurate spacing (e.g., rebar grids) without physical tape measures.
2. **Hazard Detection:** Scans the worker's periphery for missing hard hats, fall hazards, and safety violations.
3. **Automated RFI Drafting:** When a deviation is detected (e.g., a pipe is 50mm off-spec), it grabs a screenshot, cites the exact PDF building code via RAG, and auto-drafts the RFI form. The engineer at the office just clicks "Approve."
4. **Predictive Analytics:** Learns from past mistakes on the site to predict where the next deviation will happen.

---

## 🧠 How We Built It (Architecture Deep Dive)

FieldPilot AI is not a simple wrapper around an LLM. It is a highly robust, multi-modal architecture designed for the harsh, disconnected realities of a physical construction site.

### 1. The 10-Agent Swarm Orchestration
To prevent hallucinations and ensure enterprise-grade reliability, we moved away from monolithic prompting. We built a swarm of 10 specialized, asynchronous AI agents using **FastAPI** and **Python**:

![FieldPilot 10-Agent Architecture Workflow](https://mermaid.ink/img/eyJjb2RlIjogImZsb3djaGFydCBURFxuICAgIEdbXCJNZXRhIEdsYXNzZXNcIl0gLS0-fFwiVmlkZW8vQXVkaW8gdmlhIEJsdWV0b290aFwifCBNW1wiUG9ja2V0IE1vYmlsZSBQaG9uZTxicj5FZGdlIE5vZGVcIl1cbiAgICBNIC0tPnxcIldlYlJUQyAvIFJUTVAgU3RyZWFtXCJ8IENbXCJDbG91ZCBJbmdlc3Rpb24gTGF5ZXJcIl1cbiAgICBcbiAgICBzdWJncmFwaCBNdWx0aS1BZ2VudCBTeXN0ZW1cbiAgICAgICAgQTFbXCJBZ2VudCAxOjxicj5WaXNpb24gSW5nZXN0aW9uXCJdIC0tPiBBMltcIkFnZW50IDI6PGJyPk1lYXN1cmVtZW50XCJdXG4gICAgICAgIEExIC0tPiBBNFtcIkFnZW50IDQ6PGJyPkhhemFyZC9TYWZldHlcIl1cbiAgICAgICAgXG4gICAgICAgIEEyIC0tPiBBM1tcIkFnZW50IDM6PGJyPkNvbXBsaWFuY2VcIl1cbiAgICAgICAgQTQgLS0-IEE4W1wiQWdlbnQgODo8YnI-Tm90aWZpY2F0aW9uXCJdXG4gICAgICAgIEEzIC0tPiBBOFxuICAgICAgICBBMyAtLT4gQTZbXCJBZ2VudCA2Ojxicj5SRkkgRHJhZnRlclwiXVxuICAgICAgICBcbiAgICAgICAgVltcIlZvaWNlIEF1ZGlvXCJdIC0tPiBBNVtcIkFnZW50IDU6PGJyPlZvaWNlL05MUFwiXVxuICAgICAgICBBNSAtLT4gQTdbXCJBZ2VudCA3Ojxicj5Lbm93bGVkZ2UgUmV0cmlldmFsXCJdXG4gICAgICAgIFxuICAgICAgICBBNiAtLT4gQTlbXCJBZ2VudCA5Ojxicj5Qcm9qZWN0IE1lbW9yeVwiXVxuICAgICAgICBBOCAtLT4gQTlcbiAgICAgICAgXG4gICAgICAgIEE5IC0tPiBBMTBbXCJBZ2VudCAxMDo8YnI-TGVhcm5pbmcvUHJlZGljdGl2ZVwiXVxuICAgIGVuZFxuICAgIFxuICAgIEMgLS0-IEExXG4gICAgQyAtLT4gVlxuICAgIEE4IC0tPnxcIlRUUyBBdWRpbyBBbGVydFwifCBNXG4gICAgTSAtLT58XCJBdWRpbyBGZWVkYmFja1wifCBHIiwgIm1lcm1haWQiOiB7InRoZW1lIjogImRlZmF1bHQifX0=)

* **Agent 1 (Vision):** Receives raw frames from the glasses. Extracts objects, bounding boxes, and scene context.
* **Agent 2 (Measurement):** Uses depth estimation algorithms to calculate real-world distances.
* **Agent 3 (Compliance):** Compares Agent 2's measurements against the digital BIM/Spec sheet.
* **Agent 4 (Safety):** Scans for missing PPE using quantized YOLOv9.
* **Agent 5 (Voice NLP):** Processes natural language queries from the worker via Whisper ASR.
* **Agent 6 (RFI Drafter):** Automatically drafts an RFI if Agent 3 detects a deviation.
* **Agent 7 (Knowledge):** RAG agent that looks up exact PDF specs or building codes using Qdrant Vector DB.
* **Agent 8 (Notification):** Routes critical alerts to the Web Dashboard.
* **Agent 9 (Memory):** Logs the incident into our **Neo4j Knowledge Graph**.
* **Agent 10 (Learning):** Analyzes historical graphs to predict *future* RFIs before they happen.

### 2. Hardware Integration & The "Pocket Node"
Meta Glasses do not currently have an open API for third-party cloud streaming. Furthermore, the worker cannot hold a mobile phone while working.
* **The Relay:** The glasses connect to a smartphone in the worker's pocket via Bluetooth. The FieldPilot mobile app runs securely in the background, acting as a bridge to the cloud.
* **Worker Audio Commands:** The worker taps the glasses and speaks. The microphone records the audio, the cloud processes it, and sends a Text-to-Speech (TTS) payload back to the phone, which plays directly in their ears: *"Stop work. Rebar spacing deviation detected."*

### 3. Indoor Localization for Multiple Workers
GPS is useless indoors. To track exactly which room or zone a worker is in (essential for checking the correct blueprint):
* We utilize cheap **Bluetooth Low Energy (BLE) beacons** attached to concrete pillars. 
* The pocketed phone triangulates these beacons to automatically tag the live video feed with the correct Zone ID (e.g., "Zone A12").

### 4. Dual Next.js Command Centers
Site managers cannot look through 400 pairs of glasses at once. We built real-time Web Dashboards (Engineer & Executive) using **Next.js** and **React**. Using Server-Sent Events (SSE), the dashboard receives live issue injections. It features real-time ROI calculators and a **Live 3D Site Map** that aggregates video from all workers to reconstruct the physical site via NeRF/Gaussian Splatting concepts.

---

## 🔬 The Mathematics of FieldPilot 

To achieve millimeter-accuracy using a single RGB camera, we relied on deep monocular depth networks. The depth Z of a pixel is inversely proportional to disparity d, modeled dynamically as:

`Z = (f × B) / d`

Where f is the focal length of the Meta glasses and B is the baseline. We fine-tuned Depth Anything V2 to map these pixel distances to real-world coordinates.

For hazard detection, we calculate bounding boxes to ensure safety compliance. The confidence of our PPE detection is gated by the Intersection over Union (IoU) metric:

`IoU = Area of Overlap / Area of Union`

Where A is the predicted bounding box for a hard hat and B is the ground truth. Only detections with IoU > 0.75 trigger a safety alert, drastically reducing false positives.

---

## 🧗 Challenges We Ran Into

1. **The "No-WiFi" Construction Site Problem:** Job sites are notorious for dead zones. If the AI relies on the cloud, it fails the moment a worker steps into a basement. 
   * *Solution:* We engineered an offline **Store-and-Forward** architecture. The pocketed smartphone processes critical safety hazards locally via its Neural Processing Unit (NPU). When the worker walks back into a WiFi zone, the mobile app batch-syncs the cached incident data to the cloud.
2. **Meta’s Closed Ecosystem:** Meta does not provide a seamless B2B streaming API. We had to reverse-engineer local broadcasting and build a custom Android bridge to intercept the RTMP feed and route it securely to our backend.
3. **Acoustic Noise Constraints:** 100+ decibels of jackhammers ruin voice recognition. We had to utilize the directional bone-conduction mics built into the glasses, paired with deep-learning noise cancellation.
4. **Battery Life:** Streaming video continuously drains smart glasses fast. We had to implement aggressive duty-cycling (analyzing 1 frame every 5 seconds) to extend operational life.

---

## 🏆 Accomplishments That We're Proud Of

- Successfully orchestrating **10 independent AI agents** to work harmoniously without stepping on each other's toes.
- Solving the "hands-free" interaction problem. Creating an AI that is entirely passive—watching, learning, and alerting only when necessary—feels like magic.
- Implementing a robust Edge-to-Cloud fallback system that utilizes the smartphone's NPU for zero-latency safety alerts.
- Integrating a Neo4j Knowledge Graph to turn raw computer vision data into a queryable semantic map of the construction site.

---

## 📚 What We Learned

- **AI Must Be Multi-Modal and Physical:** Moving from text-generation to processing raw, noisy physical data (video streams, audio chunks, IMU sensor data) requires a massive paradigm shift in how we handle asynchronous events.
- **The Harsh Reality of Edge Compute:** We quickly realized that cloud AI is a luxury. We had to learn optimization techniques: duty-cycling cameras, dropping bitrates, and quantizing neural networks to prevent smartphones from overheating.
- **Humans Hate Friction:** The biggest lesson was about User Experience. A worker won't use AI if it requires them to press buttons. 

---

## 🚀 What's Next for FieldPilot AI

1. **Enterprise Hardware Pivot:** Moving from Meta Glasses to true enterprise AR hardware (like RealWear or Magic Leap) that offers proper B2B SDKs and hard-hat mounting capabilities.
2. **Procore/Autodesk Integration:** Seamlessly pushing our auto-drafted RFIs directly into industry-standard ERP systems.
3. **Drone Swarm Integration:** Pairing our ground-level glasses data with aerial drone photogrammetry to create a pixel-perfect 3D digital twin of the site every single day.

FieldPilot AI isn’t just a hackathon project; it’s a scalable, production-ready blueprint for the future of construction.
