## recommendation-tiers

Every analysis opens with exactly one of:

- 🟢 low-risk fix — root cause is clear and the fix is small and contained
- 🟡 needs review — plausible root cause but the fix has design implications
- ⚪ not a code bug — config, data, third-party outage, expected behaviour,
  or a duplicate
- 🔴 insufficient context — could not establish a credible root cause

A wrong confident analysis costs more than an honest shrug. Use 🔴.
