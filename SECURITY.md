# Security Policy

Desk Agent can search local files, edit documents, launch applications and send email. Treat every configured tool as a privileged capability.

## Before publishing

- Keep `main/desk-agent/data/.config.yaml` private.
- Restrict `plugins.local_file_search.allowed_directories` to trusted folders.
- Use a random remote API token and restrict Feishu `allowed_open_ids`.
- Never commit API keys, SMTP authorization codes, personal documents, task databases or logs.
- Revoke and recreate any credential that has appeared in a public repository or shared log.

## Reporting a vulnerability

Please report security issues privately to the repository owner instead of opening a public issue. Include the affected version, reproduction steps and potential impact.

