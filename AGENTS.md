# Project working instructions

## Requests and answers with Nick

- Use repository-root `DEV.txt` as the single place for every request that needs
  Nick to take an action, supply information, test something, or make a decision.
  This applies to future turns, automatic goal continuations, and new sessions.
- Read `DEV.txt` at the start of each turn and before waiting on Nick. Check the
  answer section and referenced public reports before repeating a request.
- `DEV.txt` is a local ignored worksheet. Keep it out of Git and packages. If it
  is missing, create REQUESTS and ANSWERS sections before asking for an action.
- Before asking Nick for anything, add or update its request in `DEV.txt` with a
  stable ID, priority/status, concise steps, exact relevant paths, what result is
  needed, and a matching field under ANSWERS. Prepare and verify the actionable
  artifacts first. Do not create duplicate entries for the same pending action.
- Chat may briefly announce that `DEV.txt` changed and link it. Do not leave a
  request only in chat or a question tool. If a platform approval prompt is
  mandatory, retain the matching request in `DEV.txt` as well.
- Preserve Nick's answers and other concurrent edits. Re-read the file before
  editing, make targeted changes, record reviewed results, and update the plan
  from actual evidence. An empty answer or elapsed time is not a result.
- Keep pending requests visible. Archive completed or superseded requests with
  their result and reason; do not silently delete them or reset the answer form.
- D6 startup acceptance closed on owner-result review93: post-reboot menu20s,
  repeat2s and visible AI/results/Continue/Quit without issues. Preserve the
  accepted manual71 candidate; do not request that completed check again.
  D1's corrected LAN setup98 is COMPLETE:owner report passed at ready,verified
  TLS/native health. Do not request setup again. Two-PC match/rematch observations
  remain unrecorded. Preserve failed53/93 files and Nick's original answers.

## Delivery records

- Continue the full Windows server/client roadmap in
  `docs/REMAINING_DELIVERY_PLAN.txt`; document findings and scoped evidence.
- Keep original game files, assets, raw captures, credentials and built binaries
  out of Git. Use the existing ignored local/build locations for those inputs.
