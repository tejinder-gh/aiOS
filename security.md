# Security

This covers the security posture of aiOS, a self-hosted control plane. It is not the upstream engine's vulnerability policy.

## Local posture

The proxy is protected by a master key. The services control plane is gated three ways, and any one being false makes it read-only: `LITELLM_ENABLE_SERVICE_CONTROL=true` (off by default), a proxy-admin caller, and a registered service whose fixed argv is the only thing ever executed (no shell).

Set a strong `LITELLM_MASTER_KEY` and a real `LITELLM_SALT_KEY` before storing any provider key in the database. The salt key encrypts stored secrets and cannot be rotated afterward, so choose it first.

## Before hosting

aiOS is built for local use today. Before exposing it beyond localhost, work through the hosting-readiness section of [docs/aios/gap-analysis.md](./docs/aios/gap-analysis.md): rotate the master key off any documented default, restrict `/services/register` for non-local callers so an admin cannot run arbitrary commands or read arbitrary files on the host, and add IP allowlisting, a CORS policy, and rate limits on the management endpoints.

## Reporting

This is a private fork. Report security issues to the repository owner.
