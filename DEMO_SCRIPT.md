# QR Wapsi: finale demo script (3 minutes)

Team Hawks · Paytm Build for India AI Hackathon, Track 3. Prototype: synthetic data, integrations simulated.

## Before you go on stage (5 minutes)

1. `.env` has `DEMO_MODE=replay`. Start with `./run.sh`. Replay works with Wi-Fi off.
2. Run `python scripts/warm_cache.py --check` in `backend/` and confirm every line says "cached".
3. Open http://localhost:5173/demo → **Reset demo**. Under System status: DEMO_MODE `replay`, tool transport `MCP`.
4. In the **Demo script** panel, open the tabs in this order in **one** browser window: Dashboard, Shop simulator ·
   M0001, Merchant journey, Field app. Zoom 100%, full screen (F11).
5. In the Shop simulator tab, click **Enable sound** once. Turn the laptop volume up and check the projector's audio.
6. Have the backup recording open in a paused video player (see the end of this file).

If anything goes wrong mid-demo: **Demo control → Reset demo** (takes under a second) and restart from step 1.
Nothing else needs restarting.

## Talk track

### 0:00 – 0:30 · The backlog (tab: Dashboard)
**Say:** "RBI's Payment Aggregator Directions mean every merchant onboarded till December 2025 has to be re-verified.
For a small shop that means a verified PAN or Form 60, one ID document and an in-person check of the shop, done by
Paytm's own staff. Until then, QRs are at risk of being paused. Here are a thousand paused merchants. QR Wapsi is the
AI teammate that clears this queue."

**Point at:** the Paused tile (1,000), then the navy card.
**Say:** "The agent ranks the queue by value at risk, missing documents and how long the shop has been paused. The
score is deterministic; the LLM only explains it. Sharma Kirana Store comes first: ₹3.2 lakh a month of payments
blocked, 55 days paused, PAN and ID missing."

**Click:** **Start agent journey** (opens the merchant journey).

### 0:30 – 1:15 · The shopkeeper, in Hindi (tab: Shop simulator)
**Say:** "This is Ramesh ji's phone and his Soundbox. The agent opens on the Soundbox, which says in Hindi to check
WhatsApp, and sends a Hindi WhatsApp message asking for a PAN photo."
*(The Soundbox speaks. The Hindi message is on the phone, with English underneath.)*

**Click:** **Photo** → **PAN card (blurry photo)**.
**Say:** "He sends a blurry photo. The agent doesn't just say 'invalid'. It checks sharpness locally, tells him
exactly what to fix — 'the photo is blurry, retake it in good light' — and the Soundbox says it too."

**Click:** **Photo** → **PAN card (clear photo)**.
**Say:** "Clear photo: Gemini reads the fields, the PAN format and name are checked, and the PAN is verified with the
issuing authority. Accepted. Now it asks for an ID document."

**Click:** **Photo** → **ID document (clear photo)**.
**Say:** "Both documents done in under a minute, with no human in the loop yet."

### 1:15 – 1:40 · The visit, in the quiet hour (tab: Merchant journey)
**Point at:** the step timeline and the **Field visit route** map.
**Say:** "The agent books the in-person check for 3:10 PM, the shop's quietest hour, read from its own payment
timestamps, so the visit doesn't disturb business. OR-Tools fits it into Neha Tyagi's day as stop 4, with every
visit inside its time window."
**Point at:** **Agent decisions**: "LLM proposed SCHEDULE_VISIT → policy accepted".
**Say:** "At each step the LLM proposes the next action, but only from the actions that are valid right now, and a
deterministic policy accepts or overrides it. Both are in the audit log."

### 1:40 – 2:25 · The in-person check (tab: Field app)
**Say:** "The one thing the AI never does is the physical check. That stays with Paytm's field employee."
**Click:** the **3:10 PM** visit → **Capture location** → **Take photo** → **Shop signboard** → tick
**I confirm I visited the premises** → **Submit in-person check**.
**Say:** "Geo-tag at the shop, signboard photo, and a personal confirmation recorded under her ID."

### 2:25 – 3:00 · QR live (tabs: Shop simulator, then Merchant journey)
**Switch to the Shop simulator tab.** The Soundbox says **"आपका QR फिर से चालू। धन्यवाद!"** and the QR turns teal.
**Say:** "The QR is live again. And this is how it got there:"
**Switch to Merchant journey →** point at **Requirements** (all five ticks) → click **Verify chain** (green tick).
**Say:** "Only a plain-Python rules engine can switch a QR back on: PAN verified, ID collected, names match,
in-person check by a field employee, no open risk flag. Every step is in a hash-chained audit log we can verify.
One shopkeeper, three minutes, and the field team only did what needs a human. That's QR Wapsi."

### If there's time: the escalation path (30 s)
**Demo control → ⚠ Trigger a risky merchant → Review.** "This shop has low payer diversity, mostly round amounts and
late-night payments: a mule pattern. The agent doesn't decide; it escalates with the evidence, and the journey waits
for a person." **Reject**, typing a note, or **Approve** → open the journey: the decision and the note are in the
audit log.

## Likely judge questions

**"Isn't the LLM making compliance decisions?"**
No, and it can't. Compliance is decided by `rules_engine.py`, plain Python with no LLM, reading evidence from the
database. The only code that switches a QR live re-runs that engine first. The LLM proposes next actions, but only
from the actions valid in that state, and a deterministic policy accepts or overrides it. It also writes messages,
explains rankings and reads document fields; every output is schema-validated. We test this: only one function can
set LIVE, the compliance code can't import the LLM even indirectly, and a test makes the vision model lie that a
blurry PAN is perfect — it still gets rejected. If the LLM is down, the policy decides alone and the journey
continues.

**"What if the document is fake?"**
There are several independent layers, and the LLM's reading is never trusted alone; it isn't even told the name it
should find:
1. Local quality and format checks: sharpness, the PAN pattern.
2. PAN verification with the issuing authority. An invented PAN doesn't exist, and someone else's PAN fails the
   name check.
3. Name match across the PAN, the ID and the merchant record. A mismatch goes to a human.
4. The in-person visit: a Paytm employee is physically at the shop (geo-tag within 250 m, signboard photo).
5. Mule-risk scoring from payment behaviour flags pass-through accounts for human review, however good the
   documents look.

What the prototype doesn't do yet: image forensics for tampered photos, and verifying the ID document with its
issuer (DigiLocker or the issuing database). Both plug in as tools behind the same interfaces.

**"What's simulated?"**
- **Simulated:** the merchants and their payment data (1,000 synthetic shops); CKYCR, PAN verification and
  DigiLocker (mock clients with real-looking interfaces); WhatsApp, IVR and the Soundbox device; the GPS fix; the
  specimen photos.
- **Real:** the agent (LangGraph with checkpoints), the Gemini calls, the Sarvam Hindi voice, the MCP tool server,
  the rules engine, the audit chain, the scoring, the quiet-hour finder and the OR-Tools routing.
- **Pre-recorded for the stage:** the AI responses are recorded and replayed, so the demo can't fail on Wi-Fi.

Every screen carries the "simulated" banner.

**"How does this scale to lakhs of merchants?"**
- **Cheap work:** most of the work is deterministic and cheap. Ranking all 1,000 merchants takes about 0.14 s on a
  laptop.
- **LLM usage:** one full journey here made 17 short LLM calls: one ranking explanation, eight next-action
  proposals, five messages and three document readings.
- **Independent journeys:** each journey is its own checkpointed thread, so they run in parallel and survive
  restarts. In production that means a job queue, Postgres instead of SQLite, and more workers; the agent code
  doesn't change.
- **The real limit is field visits.** We attack it three ways: CKYCR merchants skip document collection entirely;
  visits are booked only after documents are verified, so each is a short check; and OR-Tools packs each employee's
  day around shops' quiet hours.
- **Human review stays small:** people only see escalations, about 3% of this synthetic backlog are mule-like.

**"Why Paytm? Why not a vendor?"**
- **The channels are Paytm's:** Paytm already has the relationship and the channels — the Soundbox on the counter,
  the app, WhatsApp — and the payment data that makes this work: quiet hours for visits, and payment patterns for
  mule risk. Sending that data to a vendor is a privacy and compliance cost.
- **The rules point in-house:** they put the in-person check on the aggregator's own staff, and accountability for
  due diligence stays with the aggregator.
- **It amplifies Paytm's team:** QR Wapsi multiplies that team; it doesn't replace it.
- **Vendors still fit:** external verification services plug in as MCP tools behind the same interfaces, so Paytm
  can use a vendor where one is better without giving up control of the journey.

**"What does the RBI rule actually require?"**
As we read the RBI Payment Aggregator Directions (September 2025): aggregators must bring merchants onboarded till
31 December 2025 up to the new due-diligence norms.
- **Small merchants** (turnover up to ₹40 lakh) not found in CKYCR need three things: PAN or Form 60 verified with
  the issuing authority, one officially valid document, and a contact point verification — a physical check of the
  business, done by the aggregator's own staff.
- **Merchants found in CKYCR** can use that record for identity, but still need the in-person check.
- **Larger merchants** need full due diligence, which our prototype routes to a human.

These rules live in `rules_config.yaml`, owned by compliance, so they can change without code changes. It's our
team's reading, not legal advice.

## Backup screen recording (record it before the event)

Record one clean run in replay mode, with sound, using Windows' built-in tools.

**Option A: Xbox Game Bar** (records one app window, with its audio):
1. Settings → Gaming → Captures: set **Captured audio** to "Game" (or "All") and video quality to "Standard".
2. Reset the demo and arrange the four tabs in **one** Chrome window. Game Bar records a single window, and tab
   switches inside it are captured.
3. Click into Chrome, press **Win + Alt + R** to start recording, and run the five steps.
4. Press **Win + Alt + R** to stop. The file is in `Videos\Captures`.

**Option B: Snipping Tool** (records any screen area):
1. Open Snipping Tool, switch to the **Record** (video camera) mode, and choose **New**.
2. Drag over the browser window. If your version shows an audio toggle, turn system audio on. Click **Start**.
3. Run the demo, then click **Stop** and **Save**. Default folder: `Videos\Screen Recordings`.

Watch the file once to check the Soundbox audio is in it. Keep a copy on a USB stick.
