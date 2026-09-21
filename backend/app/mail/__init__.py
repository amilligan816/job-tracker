"""Reading job-application mail out of a connected mailbox.

The pieces, in the order a sync uses them:

- `provider`  the shape every mailbox has to present (headers, then bodies)
- `gmail`     Google OAuth and the Gmail REST API, spoken over httpx
- `classify`  which application an email is about, and what it says happened
- `sync`      the run itself -- fetch, classify, persist suggestions
"""
