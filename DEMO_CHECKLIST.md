# ASK THE WALL - DEMO DAY CHECKLIST

## Pre-demo (30 minutes before)
- [ ] `docker compose up` — verify all services are green
- [ ] Call `POST /api/v1/notification/test-fire` → verify WhatsApp arrives on engineer phone
- [ ] Open engineer dashboard → verify WebSocket dot is green ("System is live")
- [ ] Open mobile app → verify camera permissions granted
- [ ] Seed demo data: `python scripts/seed_demo_data.py`
- [ ] Verify Zone A12 shows amber on site map
- [ ] Test FAIL scenario end-to-end once (scan rebar image, wait for buzz)

## Demo Flow (Practice this exact sequence)
1. **Show executive dashboard KPIs loading** (Watch the count-up animation and staggered entry).
2. **Mobile**: scan rebar photo → FAIL verdict fires.
3. **Dashboard**: Zone A12 turns red in real time (pulsing animation).
4. **Engineer phone**: WhatsApp message arrives in real time.
5. **Mobile**: hold up old drawing (S-101 R3) → CRITICAL version mismatch alert flashes with audio.
6. **Dashboard**: Ask AI "what did June meeting say" (Memory Agent).
7. **Dashboard**: Show Predicted RFIs panel (Predictive Agent).
8. **Executive**: Show learning stats "The system has learned from 47 incidents...".

## Contingency Plan
- [ ] Backup: Screen recording of full flow recorded the night before on a working system.
- [ ] Rule: Never apologize — say "let me show you the architecture while that loads."
