# Security Policy

SignalWalk is an **experimental, single-user, local tool**. It has not been security-audited.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository (Security tab, "Report a vulnerability").
Replace this paragraph with a contact address of your choice before publishing.

## Design for safety

- **Local only by default.** The server binds to `127.0.0.1`. Starting it on another address
  prints a warning, because **there is no authentication**: anyone who can reach the port can read the
  floor plan and survey and trigger Wi-Fi measurements.
- **No secrets.** There are no API keys or passwords. `.env` is git-ignored; `.env.example` has no secrets.
- **Fixed commands only.** Real mode runs a short fixed list of OS commands (`netsh`, `nmcli`,
  `system_profiler`) with no shell and no user-controlled arguments.
- **Privacy.** Only signal strength and a 6-character one-way tag of the access point's address (to detect
  roaming) are kept. SSIDs and MAC addresses are never stored. The tag is stored in JSON surveys, not in CSV
  exports. A survey still describes the layout of your home, so keep it out of public repositories
  (the `.gitignore` excludes `survey.json` / `survey.csv`).
- **Input validation.** Positions, signal values, floor plans and surveys are validated; errors are reported
  without stack traces.
- **Browser hardening.** Content-Security-Policy (`script-src 'self'`), `nosniff`, `no-store`; server text is
  inserted with `textContent` only.

## Known limits

- No TLS, no authentication, no rate limiting. Do not expose it to a network you do not trust.
- A real-mode measurement briefly runs OS commands; concurrent requests are refused (HTTP 409).
- The shipped example surveys are simulated and contain no real network data.
