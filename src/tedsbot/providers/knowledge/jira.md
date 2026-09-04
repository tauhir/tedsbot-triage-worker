## Jira

- Rich-text custom fields (QA Notes, QA Instructions) require an
  Atlassian Document Format object, not a plain string. Minimal skeleton:
  `{"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"text","text":"..."}]}]}`.
  The `contentFormat` parameter converts the system description only.
- Editing a custom field replaces it; resend the full document.
- Always fetch available transitions live before transitioning, and match
  on the target status name (`to.name`), not the transition label. Labels
  and target names differ on some workflows.
- Never move a ticket backwards. If it is already at or past the target
  status, leave it.
- Comments are written as ADF too. Write real line breaks as separate
  paragraphs, never literal `\n` escape sequences.
- Ticket summaries describe the user-visible symptom in plain language,
  with the exception type in trailing parentheses.
