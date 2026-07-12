# Security Policy

Photo Drop runs a local HTTPS receiver on your own machine and network. Its safety rests on
a layered design: nothing listens until you open it, the port is firewall-scoped to your local
subnet on the Private profile, the app independently rejects off-subnet clients, transfers are
encrypted, and every upload requires both a 128-bit session token (in the QR code) and a
6-digit code shown on your PC, with lockout after 5 wrong tries.

## Reporting a vulnerability

Please report suspected vulnerabilities privately rather than opening a public issue. Use
GitHub's private "Report a vulnerability" (Security Advisories) on this repository. Include
steps to reproduce and the potential impact. You'll get an acknowledgement, and a fix or
mitigation will be prioritized.

## Scope and trust boundaries

- The tool trusts the local machine's user account. A local attacker already running as your
  user (or as admin) is outside the threat model, since they can read the private keys and act
  as you regardless of this tool.
- The certificate authority created by setup is machine-local, user-scoped (private key ACL is
  600-equivalent), and constrained (`pathlen:0`, cert-signing key usage). It never leaves your
  machine and is never committed to source control.
- Private keys and certificates live only in `%LOCALAPPDATA%\iPhonePhotoDrop\` and are
  gitignored. If you fork or contribute, never commit `*.pem`, `*.key`, or `*.crt`.

## For contributors

Every HTTP route inherits the local-subnet check, but token authentication is opt-in per
handler. Any new route that returns private data or performs an action must verify the session
token. The only intentionally unauthenticated route is `GET /ca.crt`, which serves the public
CA certificate; do not copy that pattern to anything sensitive.
