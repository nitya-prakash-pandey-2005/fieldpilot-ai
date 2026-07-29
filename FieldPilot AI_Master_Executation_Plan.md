# **FieldPilot AI — Master Execution Plan** 

_Complete, testable, production-ready build plan — 15 days to Stage 2_ 

## 0. Operating principles 

- Build less, make all of it real. A small set of components that visibly work on real hardware beats a large architecture that only exists on slides. 

- Every capability is either fully working live, or explicitly marked in your own notes as a scoped stand-in. Never blur this line, even internally. 

- Have a working Tier 1 demo on a laptop webcam before the glasses arrive — this is non-negotiable and mirrors the strongest competitor's own discipline. 

- Keep the repo private during development. Do not describe your differentiators publicly until final submission. 

- Record real numbers as you go: accuracy, latency, battery drain. These numbers are your credibility. 

## 1. Team roles and ownership 

- ML / Vision Lead — detection, tracking, pose, depth, measurement-vs-spec, fine-tuning 

- Backend / Data Architect — API, databases, agent orchestration, event pipeline, RAG 

- Edge / Hardware Engineer — glasses integration, voice loop, alert channels, offline mode, battery 

- Frontend / Dashboard Engineer — engineer dashboard, live feed, learning-loop panel 

- 5th member (if available) — data curation/labeling, QA across all modules, rehearsal ownership, pitch materials 

FieldPilot Al — safety copilot + digital foreman 



<!-- Start of picture text -->
Tier 0/1: edge, always-on Depth estimation Attention-aware<br>Detect + track + PPE + fall + gaze hazard distance + measurement escalation (gaze-based)<br>NEW: measurement vs NEW: cited spec/drawing NEW: auto RFI draft<br>spec/drawing deviation Q&A via RAG on deviation<br>Unified event + knowledge graph (zone-tagged: hazards, deviations, RFls)<br>NEW: real feedback learning loop — before/after accuracy on held-out set<br>Alert dispatch — audio TTS + phone haptic (no HUD on Wayfarer Gen 2)<br>Engineer dashboard — hazards, deviations, RFls, learning-loop metric<br><!-- End of picture text -->

- Testing for this step: confirm docker-compose up brings up all services cleanly; confirm a hello-world FastAPI endpoint responds; confirm the validation set is committed and locked. 

## 4. Phase 0 — Days 1-5: build and prove Tier 1 before glasses arrive 

### Day 1 

- ML: install Ultralytics YOLO; run a pretrained model on a public construction video to confirm the pipeline runs end to end. 

- Backend: FastAPI skeleton, health check endpoint, Postgres schema for projects/zones/assets/events. 

- Edge: install Meta's Mock Device Kit; confirm a simulated camera/audio stream flows into a test script. 

- Frontend: Next.js shell with mock data, dashboard layout drafted. 

- Test: pipeline runs on one sample video with no crashes; API returns 200 on health check; mock device stream visible in logs. 

### Day 2 

- ML: integrate a PPE detection model (Roboflow/HuggingFace) alongside the general detector; add BoTSORT tracking for persistent worker IDs. 

- Backend: zone-tagged schema finalized; drawing/spec PDF ingestion pipeline built against one public standard-form drawing. 

- Edge: wire Whisper (local) for speech-to-text and a TTS engine; confirm a basic voice round trip on the mock stream. 

- Frontend: RFI/hazard card component built against static mock data. 

- Test: PPE detection correctly flags a missing-hardhat sample image; tracking IDs persist across a short occlusion in a test clip; voice loop produces audible output from typed text. 

### Day 3 

- ML: add pose estimation (17-keypoint) for fall detection and head-yaw gaze estimation. Record baseline accuracy on your locked validation set now — write this number down. 

- Backend: hazard analyzer fusing PPE + fall + proximity signals into a scored assessment object. 

- Edge: export a quantized edge model (ONNX/TFLite); confirm it runs on an actual phone NPU independent of glasses. 

- Frontend: live feed panel wired to a mock WebSocket stream. 

- Test: fall detector correctly fires on a staged fall video and does not fire on normal walking/bending; quantized model produces the same top detection as the full-size model on 5 sample frames; baseline accuracy number recorded and saved. 

### Day 4 

- ML: build attention tracking — gaze-angle check against each hazard's position, with the PASSIVE → UNNOTICED → ESCALATED state machine, including the dwell-versus-glance refinement (require a minimum gaze hold duration, not just angle, to count as a genuine glance-check). 

- Backend: measurement-vs-spec deviation module (NEW differentiator) — scale calibration against a known reference object, comparison to an ingested spec value. 

- Edge: build the offline store-and-forward queue; test by disabling WiFi mid-run. 

- Frontend: 2D zone map with live-updating status pins against mock events. 

- Test: attention state machine transitions correctly across a scripted test sequence (hazard appears, worker glances briefly — stays PASSIVE, worker holds gaze — becomes ACKNOWLEDGED, worker ignores for 4+ seconds — becomes ESCALATED); offline queue captures events with WiFi off and syncs correctly when restored. 

### Day 5 

- Full mock end-to-end rehearsal on a laptop webcam: detection → tracking → pose → hazard analysis → attention escalation → alert (TTS + earcon placeholder) → dashboard update. This is your “working before the glasses arrive” milestone — do not skip it. 

- Backend: RAG spec Q&A pipeline tested against the ingested spec corpus with a handful of real questions, checking that answers cite the correct clause/page. 

- Test: full mock rehearsal runs for 10 minutes without crashing; at least 3 distinct hazard types correctly trigger through the whole pipeline to a spoken alert; RAG answers are accurate and cited for at least 5 test questions. 

## 5. Phase 1 — Days 6-10: real glasses integration 

### Day 6 

- Swap the Mock Device Kit for the real Ray-Ban Meta Wayfarer Gen 2 stream. Milestone: see one real frame in your backend. 

- Confirm audio-only design decision is correctly implemented — no code path assumes a display exists. 

- Test: real frame received and displayed in a debug view; confirm actual resolution/fps matches the 12MP/3K/30fps spec. 

### Day 7 

- Wire Tier 0 (motion/voice wake) and Tier 1 (edge quantized detection) to run continuously on the real device without manual triggering. 

- Begin shooting your own labeled dataset using the real glasses on a mock or real site. 

- Build the earcon system (NEW): distinct short audio patterns per hazard category, played immediately before the TTS message. 

- Test: system runs unattended for 30 minutes on real hardware without manual restart; each hazard category's earcon is audibly distinguishable in a blind listening test with a teammate. 

### Day 8 

- Integrate real measurement/scale calibration using the live camera feed and a physical reference object. 

- Wire Tier 2 (cloud reasoning, RAG Q&A) to trigger only on a Tier 1 flag or an explicit voice query. 

- Build severity-scaled phone haptic patterns (NEW) synced with earcons and TTS. 

- Test: measurement accuracy checked against 10 physically-measured reference objects, error margin recorded; cloud tier does not fire on idle frames, only on real triggers; haptic pattern differs perceptibly by severity in a blind test. 

### Day 9 

- Connect deviation detection and automatic RFI drafting to the real live pipeline. 

- Fine-tune the edge model again, now including freshly-shot real glasses footage; record the new accuracy number against the same locked validation set from Day 3. 

- Test: a staged spec deviation (e.g. incorrect rebar spacing) correctly produces a drafted RFI citing the right clause; new accuracy number is equal to or better than Day 3's baseline — if not, investigate before proceeding. 

### Day 10 

- Full live end-to-end test: worker wears glasses, looks at a hazard and at a spec-relevant element, gets correct spoken + earcon + haptic alerts, dashboard reflects events in real time. 

- Record real battery drain over one continuous hour of use. 

- Test: full live loop completes with no manual intervention for a 15-minute scripted walkthrough; battery drain number recorded and sane relative to the 8-hour rated life. 

## 6. Phase 2 — Days 11-15: learning loop, cross-worker broadcast, hardening, rehearsal 

### Day 11 

- Build feedback-loop logging: every engineer approve/reject on the dashboard stored as a labeled training example. 

- Build the learning-loop metric panel on the dashboard. 

- Build a minimal cross-worker hazard broadcast (NEW): a second glasses/phone pair in the same zone receives a lower-priority advisory when the first flags a hazard. 

- Test: feedback events correctly stored and retrievable; broadcast correctly reaches a second test device within the same zone and does not reach a device tagged to a different zone. 

### Day 12 

- Run one real fine-tuning cycle using feedback collected so far; compare against the locked validation set and record the improved number. 

- Re-test offline store-and-forward mode in the real deployment environment. 

- Test: before/after accuracy delta is real and documented; offline mode correctly queues and syncs in the actual test environment, not just the earlier lab test. 

### Day 13 

- Load-test the backend under simulated multi-worker event load. 

- Add the confidence indicator (NEW) to flagged events on the dashboard — show the model's own certainty, not just a binary flag. 

- Polish the dashboard: consistent styling, remove all placeholder/mock data. 

- Test: backend holds up under simulated load of at least 3 concurrent workers' event streams without dropped events; confidence indicator displays sensible values correlated with known-easy vs known-hard test cases. 

### Day 14 

- Full rehearsal number one, timed, on the real demo scenario, with real hardware, in front of the whole team. 

- Fix whatever breaks. No new features added from this point forward — only reliability fixes. 

- Test: full rehearsal completed start to finish without a fatal failure; every timing checkpoint noted against your target demo script. 

#### 

#### 

- Full rehearsal number two. Finalize pitch deck and a recorded backup video in case of live demo failure. 

- • Showcase. 

- Test: second rehearsal matches or beats the first in reliability and timing; backup video is a faithful, nonexaggerated recording of real functionality. 

## 7. Full testing matrix (run continuously, not just on the days above) 

|**Module**|**Test**|**Pass criteria**|
|---|---|---|
|Detection|Run on 20 held-out validation frames|mAP50 recorded and trending upward week<br>overweek|
|Tracking|Occlusion test clip (worker passes behind<br>object)|Same track ID retained after re-appearance|
|Fall detection|Staged fall vs normal bending/kneeling clips|Fires on fall, does not fire on normal<br>movement|
|Attention tracking|Scripted glance vs hold vs ignore sequence|Correct state transitions every time across 10<br>runs|
|Measurement/spec|10 physically-measured reference checks|Error margin recorded and stated honestly in<br>pitch|
|RAG Q&A|5+ real spec questions|Correct answer with correct citation every<br>time|
|RFI drafting|Staged deviation triggers draft|Draft cites correct clause/drawing, human-<br>reviewable|
|Alerts (TTS/earcon/haptic)|Blind listening/feeling test with teammates|Hazard category correctly identified without<br>seeing screen|
|Offline mode|Disable WiFi mid-run, then restore|Events queued locally, sync correctly on<br>reconnect|
|Learning loop|Before/after accuracy on locked validation<br>set|Documented, non-zero improvement, or<br>honestlyreportedif flat|
|Cross-worker broadcast|Two devices, same and different zones|Same-zone device alerted, different-zone<br>deviceisnot|
|Battery|One continuous hour of real use|Drain rate recorded and stated plainly in<br>pitch|
|Latency|Hazard-to-alert timing, 10 trials|Median time recorded, target under 500ms<br>forcriticalalerts|



_Run this full matrix at least once at the end of Phase 0, Phase 1, and Phase 2 — not just once at the very end. Catching a regression on Day 8 is cheap; catching it on Day 15 is not._ 

## 8. Pitch talking points, grounded in what you actually tested 

- "We built and validated our core detection pipeline before the glasses arrived, on a laptop webcam, and moved it onto real hardware rather than designing blind." 

- "We cover both halves of the brief — real-time hazard safety, and the spec-and-paperwork bottleneck the brief itself names — not just one." 

- "Every number we're showing you — accuracy, latency, battery — is something we actually measured this week, including where it isn't perfect." 

- "Our system gets measurably better from real feedback — here is the before-and-after number on our own held-out validation set." 

- "We designed for the real hardware constraints of the Wayfarer Gen 2 — audio and haptic only, no assumed display — and used that constraint to build something original: distinct sound and vibration patterns per hazard type." 

