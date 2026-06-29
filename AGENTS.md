## Shell

User's terminal is **CMD** (Command Prompt), NOT PowerShell.
Use CMD-compatible syntax for all commands (`del` instead of `Remove-Item`, `&&` for chaining).

| Action | Command |
|--------|---------|
| Drop DB + re-ingest | `del data\jokes.db && python -m src.tg_autopost ingest` |
| Publish one post | `python -m src.tg_autopost publish` |
| Run scheduler + polling | `python -m src.tg_autopost run` |
| `ADMIN_ID` | Add your Telegram user ID in `.env` for submission moderation |

## YouTube OAuth — DONE ✅
- OAuth refresh token obtained via `urn:ietf:wg:oauth:2.0:oob` + manual code copy
- Client type: Desktop ("installed"), NOT "web"
- PKCE was required — used custom script with saved `code_verifier`
- Secrets added to GitHub: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
- `.env` updated locally with all 5 YouTube vars
- Workflow triggered manually for testing
