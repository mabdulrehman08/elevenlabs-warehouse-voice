# Northstar Floor Voice

**Why this project:** ElevenLabs Forward Deployed Engineers turn a customer's operating problem into a working solution. For a logistics company, that problem is the walk from a pallet to an inventory terminal. This pilot lets a worker ask for stock and bin locations through a headset, then hear a short, grounded answer. It proves enterprise workflow discovery, ElevenLabs API integration, inventory semantics, and practical failure recovery in one small deliverable.

Northstar Logistics is a fictional customer. The five SKUs and bin balances are realistic mock data, explicitly labeled as a static snapshot. This is a working local pilot, not a production WMS deployment.

## Run

Python 3.12+ and a browser with microphone support (Chrome recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env
# Set ELEVENLABS_API_KEY in .env, or export it in your shell.
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**. Click **Start hands-free session**, allow microphone access, speak, and pause for roughly a second. The assistant records a turn, transcribes it with ElevenLabs, looks up inventory, speaks the response, and listens again. End session turns off the microphone. Typed queries work without a key; synthesized replies require the key. The default voice is Roger; `ELEVENLABS_VOICE_ID` can select a voice available to your account. API calls consume your ElevenLabs quota.

The browser uses local audio energy detection, echo cancellation, and a 12-second maximum turn. It does not use browser speech recognition. This batch loop is deliberately small; it pauses capture during playback to avoid transcribing itself. Microphone access requires localhost or HTTPS. There is no wake word or interruption during speech playback. A noisy floor may trigger false turns: use a close-talk headset and end the session when idle. Voice failures end continuous capture so the client does not repeatedly spend quota.

## A 60-second customer walkthrough

| Worker says | Assistant does |
| --- | --- |
| “How many units of SKU-4821 are in aisle 7?” | 204 on hand, **168 available**, 24 reserved, 12 held; bins 07-B-03 and 07-B-04 |
| “Where is it in all aisles?” | Uses the previous SKU, expands to all three bins; 328 available |
| “Repeat” | Repeats the last lookup's scope and intent |
| “Where is the stretch wrap in aisle 7?” | Asks 18 inch / SKU 4821 or 12 inch / SKU 4822; retains the aisle |
| “18 inch” | Resolves the ambiguity and returns the aisle 7 locations |
| “How many gloves are available?” | Reports zero available despite 32 on hand, because all are reserved |
| “SKU four eight two one, aisle seven” | Normalizes spoken digits for the exact SKU lookup |
| “Reserve SKU 4821” | Declines: this pilot only reads inventory |
| “Cancel” | Clears item context |

Unknown SKUs never become fuzzy matches. Multiple SKUs require a single-item question. An aisle without a matching bin is reported as no stock record, not a fabricated zero. Replies include the snapshot warning; available stock always excludes allocations and quality holds. The parser intentionally supports inventory counts and locations rather than open-ended conversation. It runs deterministically, without an LLM or a second API key. Client context carries SKU and aisle; stock values are always recomputed from the backend.

## Delivery architecture

```text
Browser microphone → POST /api/transcribe → ElevenLabs Scribe v2
Transcript + turn context → POST /api/query → deterministic inventory lookup
Grounded reply → ElevenLabs Flash v2.5 → MP3 playback → next turn
```

- `data/inventory.json`: backend snapshot, SKU aliases, bin locations, reserved and held units.
- `app/agent.py`: exact SKU resolution, clarification, follow-ups, read-only boundaries.
- `app/main.py`: API adapter, 25-second provider timeouts, actionable quota/auth/network errors. A speech failure preserves the inventory answer as text. Keys stay on the server.
- `static/`: responsive operator console, hands-free loop, transcript and request timings.

ElevenLabs integrations use the documented [speech-to-text endpoint](https://elevenlabs.io/docs/api-reference/speech-to-text/convert) and [text-to-speech endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/convert). Model and voice IDs are configurable in `.env.example`.

## Verify

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Tests cover balances, ambiguity and context, spoken digits, zero availability, unknown items, read-only behavior, the provider request contract, and graceful voice failures. Provider tests mock HTTP; they do not spend credits. For a live acceptance check, run the first three walkthrough turns with a real key and headset, confirm the transcript digits and spoken bin IDs, then revoke microphone permission and confirm typed fallback. Local automated checks do not establish acoustic accuracy on a warehouse floor.

## Customer handoff boundary

Bind to localhost for this unauthenticated demo. A customer rollout needs SSO and warehouse-scoped authorization, per-user quotas, a live WMS adapter with freshness guarantees, and floor/headset acceptance testing. Pilot acceptance targets: 95% correct exact-SKU queries in representative noise, no invented counts, and p95 reply latency under 5 seconds, measured rather than claimed here.

Audio is forwarded to ElevenLabs only after a spoken turn and is not saved by this app. Provider retention follows the customer's ElevenLabs agreement; confirm it before real operations. Server logs contain request ID, outcome, and latency, without transcripts or keys. Browser conversation and item context remain in memory until reload. Stock is read-only, so an STT error cannot change warehouse state. For business-critical picking, confirm the SKU and freshness against the WMS.
