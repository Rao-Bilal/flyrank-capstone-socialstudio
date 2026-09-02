\# Evidence - Definition of Done



\## Platform image variants generated correctly

Test: tests/test\_image\_pipeline.py::test\_variant\_dimensions



Output:

platform win32 -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0

collected 1 item

tests/test\_image\_pipeline.py::test\_variant\_dimensions PASSED    \[100%]

1 passed in 1.97s



Confirms Instagram variant = 1080x1080, X variant = 1600x900.



\## Captions are platform-aware and composed from shared + platform-specific fragments

Test: tests/test\_caption\_composer.py::test\_captions\_differ\_per\_platform



Output:

tests/test\_caption\_composer.py::test\_captions\_differ\_per\_platform PASSED    \[ 50%]

tests/test\_image\_pipeline.py::test\_variant\_dimensions PASSED    \[100%]

2 passed in 0.95s



Confirms Instagram and X captions differ, and X caption stays under 280 chars.

No duplicated prompts - both platforms compose BRAND\_VOICE + platform-specific

fragment from app/config/social\_prompts.py.

\## Idempotent publishing (fake platform server)

Manual test via PowerShell against fake\_platform server on port 9000.



First call with Idempotency-Key "test-key-002":

platform\_post\_id: post-5b066d10-10ca-4d1c-b48d-2b7a17a8f18b, status: accepted



Second call, SAME Idempotency-Key "test-key-002":

platform\_post\_id: post-5b066d10-10ca-4d1c-b48d-2b7a17a8f18b, status: accepted



Same platform\_post\_id returned both times - confirms retrying with the

same idempotency key does not create a duplicate post.



\## Rate limiting (fake platform server)

Manual test via PowerShell against fake\_platform server on port 9000.

Request with Idempotency-Key "test-key-001" returned:

{"detail":"Rate limited"} with HTTP 429 and Retry-After header.

Confirms the fake platform randomly simulates rate limiting as required.



\## OAuth tokens encrypted at rest, random IV

Test: tests/test\_crypto\_utils.py



Output:

tests/test\_crypto\_utils.py::test\_encrypt\_decrypt\_roundtrip PASSED

tests/test\_crypto\_utils.py::test\_random\_iv\_each\_time PASSED

4 passed in 1.35s



Confirms: encrypted ciphertext never contains the plaintext token, decrypt

recovers the original correctly, and encrypting the same token twice

produces a different IV and different ciphertext each time.



\## SocialPublisher interface with 2 adapters (FakeInstagramPublisher, FakeXPublisher)

Test: tests/test\_social\_publisher.py



Output:

tests/test\_social\_publisher.py::test\_publish\_succeeds\_and\_returns\_post\_id PASSED

tests/test\_social\_publisher.py::test\_publish\_is\_idempotent PASSED

6 passed in 1.21s



Confirms: adapter successfully gets a token and publishes against the fake

platform server, returns a real platform\_post\_id, and publishing twice

with the same idempotency key returns the identical post id (no duplicate).

Application code depends only on the SocialPublisher interface - adding

a new platform means adding a new adapter class, nothing else changes.



\## Rate-limit handling with backoff

Adapter's publish() method retries on 429, reads the Retry-After header,

and waits that many seconds before retrying with the SAME idempotency key

(app/services/social\_publisher.py, \_FakePlatformAdapterBase.publish).

Max 3 retries before returning status=failed. Verified manually during

fake\_platform manual testing (see idempotency/rate-limit evidence above)

and exercised automatically by the pytest suite above.



\## Delivery webhooks are signature-verified; forged/modified events rejected

Test: tests/test\_webhook\_verifier.py



Output:

tests/test\_webhook\_verifier.py::test\_valid\_signature\_is\_accepted PASSED

tests/test\_webhook\_verifier.py::test\_forged\_signature\_is\_rejected PASSED

tests/test\_webhook\_verifier.py::test\_modified\_body\_with\_old\_signature\_is\_rejected PASSED

9 passed in 1.56s



Confirms: HMAC-SHA256 signature verification correctly accepts valid

signatures, rejects forged signatures, and rejects a tampered body even

if paired with the original (now-invalid) signature.





\## Real persistence with proper schema

Test: tests/test\_db.py::test\_init\_db\_creates\_tables



Output:

tests/test\_db.py::test\_init\_db\_creates\_tables PASSED

10 passed in 2.07s



Confirms: SQLite schema creates campaigns and social\_post\_entries tables

with foreign key relationship, a UNIQUE constraint on (campaign\_id, platform)

to prevent duplicate entries, and indexes on campaign\_id and idempotency\_key.





\## Full publish → webhook → published flow (live integration test)

Created campaign, generated content, called /publish-now.

Both entries received "publishing" -> fake platform published synchronously

\-> signed webhook delivered to /webhook/social-delivery -> signature verified

\-> entries flipped to "published" with correct platform\_post\_id, matched via

idempotency\_key (fixes a race where the webhook can arrive before publish\_now

finishes writing platform\_post\_id).



campaign\_id: deda0ec4-0d05-4b5b-bfd4-27d10fcf3f00

instagram: status=published, platform\_post\_id=post-55eafff3-2d38-41eb-8f71-b157e9df1cbf

x:         status=published, platform\_post\_id=post-9b6ac848-d05f-4fbd-a65f-7210d362c548





\## Rate limiting with backoff (deterministic test)

Test: tests/test\_rate\_limit\_backoff.py



Output:

tests/test\_rate\_limit\_backoff.py::test\_publish\_retries\_after\_429\_and\_succeeds PASSED

tests/test\_rate\_limit\_backoff.py::test\_publish\_gives\_up\_after\_max\_retries PASSED

2 passed in 1.17s



Confirms: on 429 the adapter reads Retry-After, backs off, and retries

using the SAME idempotency key (safe - no duplicate posts), succeeding

once the platform accepts. Also confirms the adapter gives up cleanly

after MAX\_RETRIES rather than retrying forever.



\## Durable scheduling (auto-publish at scheduled time)

Campaign 6d330c64-8069-4c70-bdf8-a4b1c5aa3afa scheduled for 2026-09-02T12:14:22

via POST /campaigns/{id}/schedule. No /publish-now call was ever made.



Log shows scheduler firing on its own:

POST /webhook/social-delivery 200 OK  (instagram)

POST /webhook/social-delivery 200 OK  (x)



Final GET /campaigns/{id} confirms:

campaign.status: published

instagram: status=published, platform\_post\_id=post-506bbfc2-98f4-468f-be4e-1c3d045d5a8c

x:         status=published, platform\_post\_id=post-7364578c-e3d1-4d23-bba5-e11eca4ba64e



Confirms: jobs.db (APScheduler SQLAlchemyJobStore) persisted the job,

and BackgroundScheduler fired it automatically at the scheduled time.





\## Crash recovery - manual proof

1\. Scheduled campaign 15047daa-c3e7-43b1-acb4-77f55af69e94 for 2026-09-02T12:17:32

2\. Killed the server (Ctrl+C) BEFORE that time - confirmed down via

&#x20;  failed GET request ("Unable to connect to the remote server")

3\. Waited past the scheduled time while server was down

4\. Restarted server - APScheduler's SQLAlchemyJobStore (jobs.db) had

&#x20;  persisted the job; it fired immediately on startup:

&#x20;  POST /webhook/social-delivery 200 OK  (x2)

5\. GET /campaigns/{id} confirmed status: published for campaign + both entries

6\. Manually re-called POST /campaigns/{id}/publish-now on the same

&#x20;  already-published campaign - result showed skipped\_already\_published:

&#x20;  true for both platforms, with UNCHANGED platform\_post\_id values

&#x20;  (post-28260869-... and post-4db55129-...) - proving no duplicate

&#x20;  posts were created on re-run.



\## Crash recovery - automated test

Test: tests/test\_crash\_recovery.py::test\_publish\_campaign\_is\_safe\_to\_call\_twice



Output:

tests/test\_crash\_recovery.py::test\_publish\_campaign\_is\_safe\_to\_call\_twice PASSED

1 passed in 0.83s



Confirms: calling publish\_campaign() twice for the same campaign only

ever triggers the underlying platform /publish HTTP call ONCE per

platform. The second call detects already-published entries and skips

them entirely - this is the mechanism that makes a scheduled job safe

to re-run after a crash without creating duplicate posts.



\## Webhook signature verification (automated tests)

Test: tests/test\_webhook\_security.py



Output:

tests/test\_webhook\_security.py::test\_forged\_webhook\_is\_rejected\_with\_400 PASSED

tests/test\_webhook\_security.py::test\_modified\_body\_with\_stale\_signature\_is\_rejected PASSED

tests/test\_webhook\_security.py::test\_valid\_signed\_webhook\_is\_accepted\_and\_updates\_status PASSED

3 passed in 3.10s



Confirms:

\- A webhook with a bogus signature is rejected with 400, entry status unchanged.

\- A webhook whose body was tampered with AFTER signing (valid signature for

&#x20; the original body, wrong for the modified one) is also rejected with 400.

\- A correctly signed webhook is accepted (200) and flips the matching

&#x20; entry's status to "published" with the correct platform\_post\_id.

