# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 7.x     | Yes       |
| < 7.0   | No        |

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Email **vashistanshul.7@gmail.com** with:

- A description of the issue and its impact.
- Steps to reproduce (a minimal PoC is ideal).
- Affected version(s) and platform.
- Your name / handle for acknowledgement (optional).

Response timeline:

- Acknowledgement within **48 hours**.
- Initial assessment within **7 days**.
- Fix or mitigation within **90 days** of the initial report.

A **90-day coordinated disclosure** window is followed. If the issue is already
being exploited in the wild, this may be shortened; if a fix is complex, an
extension may be requested in writing.

## Scope

In scope:

- Code execution via crafted prompts or tool arguments.
- Bypass of the tool schema validator.
- Leakage of API keys or local files through the MCP bridge.
- Unsafe path handling in filesystem-touching tools.
- Prompt-injection vectors that cause the agent to ignore the safety policy.

Out of scope:

- Issues that require the attacker to already have shell access on the host.
- Vulnerabilities in Houdini itself — report those to SideFX.
- Vulnerabilities in Ollama or local models — report upstream.

## Hardening defaults

- `safety.allow_filesystem_writes: false` by default.
- `safety.allow_python_exec: false` by default — the agent never runs
  arbitrary Python; all actions go through the schema-validated tool
  dispatcher.
- The MCP server binds to `127.0.0.1` unless explicitly overridden.
- API keys are read only from environment variables and redacted in logs.
