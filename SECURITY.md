# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in StixDB, please report it by opening a [GitHub Security Advisory](https://github.com/Pr0fe5s0r/StixDB/security/advisories/new). This keeps the report private while we investigate.

Alternatively, email **security@your-org.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

We will acknowledge your report within **48 hours** and aim to release a patch within **7 days** for critical issues.

## Scope

The following are in scope:

- `stix/` core engine
- `stix/api/` REST server
- `sdk/` Python client
- Docker/compose configuration

Out of scope: third-party dependencies (report those to the respective maintainers).

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Best Practices

When self-hosting StixDB:

1. **Always set `STIXDB_API_KEY`** — every inbound request is authenticated against this key.
2. **Never commit `.env`** — use your infrastructure's secret manager (Vault, AWS Secrets Manager, etc.).
3. **Run behind a reverse proxy** (nginx / Caddy) — do not expose the raw FastAPI server to the public internet.
4. **Use `STIXDB_STORAGE_MODE=neo4j` or `persistent`** for production — in-memory mode loses data on restart.
5. **Enable TLS** on Neo4j and Qdrant endpoints.
6. **Restrict Neo4j credentials** — use a dedicated read/write user for StixDB, not the admin account.
