## triage-method

1. **Fetch the error or ticket.** Extract exception type, message, stack
   trace, top in-app frame and its callers; or the reporter's steps,
   expected vs actual, and where in the product it happens.
2. **Read the code** behind the implicated frames or feature. Understand
   what state makes it fail.
3. **Check recent history.** `git log --since="14 days ago" -p -- <files>`
   on the implicated files. A recent change touching the failing line is
   the strongest signal.
4. **Reconcile the timeline.** The code history and the error's first-seen
   and last-seen must tell one story. Trace when the failing code and any
   guards appeared with `git log -S '<exact code>' -- <file>`. Never
   characterise a commit without reading its diff for the cited lines
   (`git show <hash> -- <file>`). If first-seen predates the suspect
   change, the error has more than one chapter; report the chapters you
   can verify and flag any remaining discrepancy instead of smoothing it.
5. **Dedupe against the ticketing system** by exception message and by the
   error label:
   - Open match: comment the new occurrence stats and STOP (⚪ duplicate).
   - Closed as Won't Do: comment stats, respect the decision, STOP (⚪).
   - Closed as Done: this is a regression; create a NEW ticket linked
     "relates to" the old one and cover what un-fixed it.
   - No match: continue.
6. **Write the analysis** in this exact structure:
   - Line 1: the recommendation tier.
   - Root cause: what fails and why, citing `file:line`.
   - Evidence: frames read, commits examined (hashes), event frequency and
     first-seen.
   - Replication steps (see replication-steps).
   - Suggested fix: files to change and how; a sketch, not a diff.
   - Link to the source error.
7. **Land it**: create or comment the ticket, populate the QA notes field
   with the tier line plus a 2–3 sentence root-cause summary, transition
   to the triage target status. Never move a ticket past that status.
8. **Write the run summary file** at the path given in the run
   instructions.

Rules: honesty over confidence; cite evidence for every claim; never edit,
commit, or push any repository file during triage.
