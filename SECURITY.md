# Security Policy

## Sensitive data

Do not commit any of the following:

- Passwords, application passwords, API tokens, or recovery codes
- SSH private keys or certificate private keys
- Production `config.json` files
- Internal IP addresses, hostnames, domains, or usernames
- Production logs, reports, database files, or backups

Use `config.example.json` for documentation and keep the real `config.json` local. Store runtime secrets outside the repository and use a dedicated, least-privileged service account where possible.

## Reporting a vulnerability

Do not open a public issue containing credentials, internal infrastructure details, or exploit data. Contact the repository owner privately with a minimal, redacted reproduction.

