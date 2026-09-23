# Executed candidates

`backend/lab/contract/candidate.py` — the single path in
`ALLOWED_PATCH_PATHS` — is a **slot**, not a file. A proposal is written
there, the scope gate rules on that path, and the sandbox executes whatever
is in it. It holds one candidate at a time and is never committed.

This directory is where a candidate that actually ran is kept afterwards, one
permanent path each, so its artifact's `source_sha256` keeps matching a file a
reader can open. Two candidates sharing the slot would mean committing the
second over the first and silently invalidating the first run's recorded
patch.

Nothing here is on the `KNOWN_IMPLEMENTATIONS` allowlist, which is why every
one of them routes to the sandbox. Being committed is not what earns local
execution.
