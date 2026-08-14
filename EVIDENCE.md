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

