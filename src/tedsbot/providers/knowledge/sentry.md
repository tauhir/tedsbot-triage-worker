## Sentry

- The Sentry MCP token cannot list organizations; always pass the
  organization slug explicitly (it is in the run facts as `sentry_org`).
- Environment names are case-sensitive in Sentry searches. Use the value
  in `sentry_environment` exactly.
- Performance and N+1 issues have no `level`; searches filtered by level
  never return them.
- The issues API does not expand the `issue.category:performance` alias;
  use the explicit category list.
- First-seen and last-seen on the issue are authoritative for the
  timeline. Reconcile them with git history before naming a root cause.
