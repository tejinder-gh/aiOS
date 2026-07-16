# aiOS gap analysis

A review of the config, docs, and feature set against the stated vision, grouped by theme with the most material items first. Each item maps to a roadmap phase or a concrete config change.

## Capability present but not wired

The engine can do these; the current setup does not use them.

1. Model substitution is barely configured. `dev_config.yaml` defines only two fallback chains (`anthropic-haiku-4-5` and `gpt-4o-mini`), and the second falls back from a cloud GPT to a small local model, which is a large capability drop. Every family a client can call (opus, sonnet, gpt-5.5, the bedrock/vertex/azure mirrors) needs a same-capability chain, otherwise "substitute the model when limits are exhausted" silently does not happen for them. Roadmap Phase 0.

2. Self-refining routing is available but off. `routing_strategy` is `usage-based-routing-v2`; the adaptive bandit in `router_strategy/adaptive_router` is not enabled, so "refine constantly" is not active for routing. Roadmap Phase 0.

3. Interactions are not stored as content. `success_callback` is prometheus and otel only. Spend logs capture metadata (tokens, cost, model), not the request and response bodies, so there is no substrate for "store and adapt to every interaction." Roadmap Phase 1.

## Self-sufficiency gaps

These contradict the "self-sufficient" and "integrate with any project" goals.

4. Skills are a passthrough, not a corpus. The Skills page and `POST /v1/skills` proxy Anthropic's remote Skills API and create resources on Anthropic's side. If that access lapses or the app is offline, the skill corpus disappears, which is the opposite of self-sufficient. Store skills locally as `SKILL.md` folders with a registry and treat Anthropic as one optional backend. Roadmap Phase 2.

5. Prompt versioning is unverified. Prompts exist as dotprompt templates, but it is not clear they carry versions, labels, or a link back to the interactions that used them. Without that, you cannot roll back a prompt or measure which version performed better. Roadmap Phase 2.

## Hosting-readiness gaps

These do not matter for a local-only tool but do the moment aiOS is exposed beyond localhost.

6. The documented master key is `sk-1234`. Fine on a laptop, dangerous once reachable. Rotate to a strong secret and remove the default from the docs before any non-local exposure. Note that `LITELLM_SALT_KEY` cannot be rotated after secrets are stored, so set a real one first too.

7. `/services/register` accepts arbitrary `argv` and `working_dir`. It is admin-only and the control flag gates execution, but locally "admin" is the host owner, whereas hosted, "admin" is a tenant, so this becomes host-level remote code execution and arbitrary file access. Before hosting, restrict `argv` and `working_dir` for non-local callers, or gate registration itself behind the same env flag as control.

8. Service control assumes localhost trust. The TCP-probe health model, the CORS posture, IP allowlisting, and rate limits on management endpoints all need a review pass before exposure.

## Ports

Health status is derived from a TCP probe of one port per service, so two services sharing a port cannot be told apart. This is acceptable by design because port assignment and uniqueness are handled when each app is configured in the OS. The current config still lists intentional duplicates (postgres and the agents stack on 5432, several web apps on 3000) for apps that never run at the same time; that is a known operator choice, documented here so it is not mistaken for a bug.

## Documentation and branding

9. The README, `ARCHITECTURE.md`, and the dashboard title still present the project as LiteLLM. `security.md` is BerriAI's upstream vulnerability policy (reports and bug bounty go to BerriAI), which does not apply to a private fork and should either be replaced with an aiOS policy or removed. The rebrand covers the first three; `security.md` is left for a decision.
