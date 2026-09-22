# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in **hackdigest**, please report it responsibly.

### How to Report

1. **Do NOT open a public GitHub issue.**
2. Use [GitHub Private Vulnerability Reporting](https://github.com/minjungsung/hackdigest/security/advisories/new) to submit your report directly.

### What to Include

- A clear description of the vulnerability
- Steps to reproduce the issue
- Potential impact and severity
- Any suggested fix (optional but appreciated)

### What to Expect

- **Acknowledgment** within 48 hours of your report
- **Status update** within 7 days with an assessment and remediation plan
- **Credit** in the fix release notes (unless you prefer to remain anonymous)

## Scope

The following are in scope for security reports:

- Hardcoded credentials or secrets in source code
- Insecure handling of API keys or email credentials
- Injection vulnerabilities in fetcher, summarizer, or notifier modules
- GitHub Actions workflow security issues (e.g., secret exposure, unsafe inputs)
- Docker image security concerns
- Dependency vulnerabilities

## Out of Scope

- Vulnerabilities in third-party services (Hacker News API, Gmail, Microsoft Teams)
- Social engineering attacks
- Denial of service attacks against GitHub Actions

## Security Best Practices

This project follows these security practices:

- All secrets are managed via GitHub Secrets — never hardcoded
- Built-in credential scan runs as part of the workflow
- Dependencies are pinned in `requirements.txt`
