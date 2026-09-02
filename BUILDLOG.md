\# BUILDLOG — AI Usage Log



This capstone was built with heavy AI assistance (Claude). Per the internship's

ground rules, this log is an honest account of where AI helped, where it was

wrong or introduced bugs, and what I changed or verified myself. "The AI wrote

it" is not treated as an explanation for any line I can't personally walk

through at the demo.



\## How I used AI in this build



I worked interactively, phase by phase: I'd paste the current state of a file

or a terminal error, ask for the next step, run the exact commands given, and

paste real output back before proceeding. Nothing was accepted without running

it against the actual fake platform server and inspecting real output (test

results, HTTP status codes, database rows) rather than trusting that code

"looked right."



\## Where AI helped



\- \*\*Boilerplate and structure\*\*: FastAPI route scaffolding, SQLite schema with

&#x20; indexes and foreign keys, the `SocialPublisher` ABC + adapter pattern, and

&#x20; the AES-GCM token encryption utility were all AI-drafted from the capstone

&#x20; brief's requirements, then run and verified against real tests.

\- \*\*Test scaffolding\*\*: the deterministic rate-limit test (mocking `httpx`

&#x20; responses instead of relying on the fake platform's random 20% chance),

&#x20; the crash-recovery test (calling `publish\_campaign()` twice against an

&#x20; isolated SQLite file), and the webhook forgery/tampering tests were all

&#x20; AI-authored based on describing the scenario I needed proven.

\- \*\*Debugging real failures\*\*: two genuine bugs were found and fixed this way

&#x20; (see below) - in both cases I pasted the actual terminal output and log

&#x20; lines, and the AI diagnosed the root cause from that evidence rather than

&#x20; guessing.



\## Where AI was wrong, and what I changed



\### Bug 1 — Webhook signature mismatch (400 on every delivery webhook)



\*\*What happened\*\*: after wiring up the main FastAPI app and the fake platform

server, every delivery webhook was rejected with `400 Bad Request`, even

though both sides used the identical `WEBHOOK\_SECRET` string.



\*\*Root cause\*\*: the fake platform's `\_send\_delivery\_webhook` function computed

the HMAC signature over `str(payload)` - Python's dict repr (single-quoted,

`True`/`False` casing) - but then sent the webhook body via `httpx`'s

`json=payload` parameter, which independently re-serializes the payload as

real JSON (double-quoted). The signature was computed over one set of bytes;

a completely different set of bytes was actually sent and later re-verified

against. They could never match.



\*\*Fix\*\*: serialize the payload to JSON exactly once with `json.dumps()`, sign

those exact bytes, and send those exact bytes via `content=body` instead of

letting `httpx` re-serialize independently.



\*\*What I verified myself\*\*: I confirmed this by reading both

`webhook\_verifier.py` and `fake\_platform/main.py` side by side and manually

tracing what bytes each side actually produced - I did not just apply the fix

blindly. I then re-ran the full publish flow and confirmed the terminal logs

showed `200 OK` instead of `400` before accepting the fix.



\### Bug 2 — Webhook race condition (status stuck at "publishing" despite a 200 webhook)



\*\*What happened\*\*: after fixing Bug 1, webhooks returned `200 OK`, but

campaign/entry status never flipped to `"published"` in the database.



\*\*Root cause\*\*: the fake platform sends its delivery webhook \*synchronously\*,

inside its own `/publish` handler, before that handler returns a response to

the caller. This meant the webhook could reach my `/webhook/social-delivery`

endpoint and run its `UPDATE ... WHERE platform\_post\_id = ?` query \*before\*

my own `publish\_now` function had received its response back and written

`platform\_post\_id` into the database. The `UPDATE` matched zero rows and

silently did nothing.



\*\*Fix\*\*: match the webhook's `UPDATE` on `idempotency\_key` instead of

`platform\_post\_id`, since `idempotency\_key` is written into the database

during `/generate` - long before `/publish-now` or the scheduler ever run -

so it's guaranteed to already exist by the time any webhook can arrive.



\*\*What I verified myself\*\*: I ran the exact sequence of API calls multiple

times and watched the terminal logs and database state at each step to

understand the actual ordering of events (publish call → fake platform

publishes → webhook fires → my own code tries to update) before accepting

that this was a race condition rather than something else. I can walk through

this ordering and explain why `idempotency\_key` is the correct thing to key

on, versus `platform\_post\_id`, at the demo.



\## What I would explain if asked about any 2-3 lines



\- \*\*Why `idempotency\_key` and not `platform\_post\_id` in the webhook handler\*\*

&#x20; (app/main.py) - see Bug 2 above; this is the fix for a real race condition

&#x20; I hit and diagnosed, not an arbitrary choice.

\- \*\*Why the fake platform's webhook signing uses `content=body` instead of

&#x20; `json=payload`\*\* (fake\_platform/main.py) - see Bug 1 above; signing and

&#x20; sending must operate on the exact same bytes.

\- \*\*Why `publish\_campaign()` checks `entry\["status"] == "published"` and skips

&#x20; already-published entries\*\* (app/services/publish\_service.py) - this is

&#x20; what makes the durable scheduler safe to re-run after a crash without

&#x20; creating duplicate posts (proven in tests/test\_crash\_recovery.py).



\## What I have NOT yet done



\- I have not load-tested this beyond single-request manual/automated tests.

\- The scheduler and app both currently run against SQLite; a genuinely

&#x20; concurrent multi-worker deployment would need a shared job store (see

&#x20; README's "Known limitations" section).

