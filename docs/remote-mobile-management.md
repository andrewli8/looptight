# Remote mobile swarm management

Status: accepted

## Decision

Remote management is opt-in. Prefer a provider's native remote-control feature
when it can operate the existing authenticated CLI session. This keeps identity,
transport security, session revocation, and mobile access inside the provider's
security boundary and creates no Looptight listener. Its tradeoff is that
availability and controls vary by provider.

When native control is unavailable, an authenticated tunnel may proxy a
Looptight control surface that remains bound to loopback. The operator supplies
and configures the tunnel; Looptight does not open a public socket, configure
DNS, or weaken the loopback default. An identity-aware HTTPS tunnel is preferred
to a bare port forward because it can enforce operator identity and revocation
before traffic reaches Looptight. A tunnel adds operational complexity and is
not, by itself, application authorization.

Binding the control surface to a LAN or public interface, with or without a
shared URL secret, is rejected. It makes accidental unauthenticated exposure
too easy and gives a leaked URL broad, hard-to-revoke authority.

## Security boundaries

- **Identity:** the provider authenticates native control. For a tunnel, the
  tunnel authenticates an allowlisted operator and passes a cryptographically
  verified identity; Looptight also establishes its own short-lived session.
  Forwarded identity headers are trusted only from the configured loopback
  proxy and never replace the Looptight session.
- **Authorization:** every request is deny-by-default and tied to one repository
  and swarm. Read status and bounded actions such as stop/cancel are separate
  permissions. Remote requests cannot change configuration, run arbitrary
  commands, bypass claims or verification, commit, merge, or push.
- **CSRF:** mutations use `POST`, require an unpredictable CSRF token bound to
  the session, validate `Origin`, and use `Secure`, `HttpOnly`, `SameSite=Strict`
  session cookies. No mutation is implemented as a link or `GET` request.
- **Replay:** mutation requests carry a single-use nonce and short expiry.
  Looptight atomically records consumed nonces and rejects duplicates, expired
  requests, and requests for another swarm. Actions are idempotent where
  possible and are recorded with operator identity and outcome.
- **Secrets:** tunnel credentials stay in the tunnel provider's keychain or
  environment, not `.looptight.toml`. A one-time bootstrap secret is generated
  with OS randomness, expires after use, and is accepted only over the tunnel.
  Secrets never appear in URLs, tracked files, logs, swarm JSON, or browser
  storage. Session keys remain in private runtime state with restrictive file
  permissions and are rotated on restart or revocation.

## Minimal implementation path

1. Document provider-native remote control as the default remote path; it needs
   no Looptight server changes.
2. Add an explicit remote-control option only after the loopback UI exists. It
   must continue listening on `127.0.0.1`, require a configured trusted proxy,
   and fail closed when verified identity or application session state is
   absent. The operator starts the authenticated HTTPS tunnel separately.
3. Initially expose status plus stop/cancel only. Route actions through the
   existing manager state machine so they cannot skip claims, worker isolation,
   or verification. Add broader actions only with a separate security review.
4. Contract tests must prove direct unauthenticated requests fail, spoofed
   identity headers fail, cross-origin and replayed mutations fail, and startup
   refuses a non-loopback bind.

This path provides mobile access without making an unauthenticated network
listener part of Looptight's default or opt-in behavior.
