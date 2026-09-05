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
   - Open match: look for an earlier comment of yours on it (they start with
     `[tedsbot]`). Add one short comment with the new event count, user
     count and last-seen only when there is no earlier comment or the
     stats changed since it. Otherwise write nothing. Either way STOP
     (⚪ duplicate) and say in the summary headline whether the stats
     changed.
   - Closed as Won't Do: same rule, and respect the decision. STOP (⚪).
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

## Writing style, everywhere you write

Ticket descriptions, comments, QA notes and the run summary are read by the
whole team. Plain sentences, one idea each: no em-dashes, no semicolons, no
markdown headings inside comments. Every comment you write starts with the
marker `[tedsbot]` so later runs can find it. Ticket summaries name the page
or feature and the symptom in plain words, with the exception type in
trailing parentheses.
