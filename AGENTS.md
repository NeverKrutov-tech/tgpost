## Shell

User's terminal is **CMD** (Command Prompt), NOT PowerShell.
Use CMD-compatible syntax for all commands (`del` instead of `Remove-Item`, `&&` for chaining).

| Action | Command |
|--------|---------|
| Drop DB + re-ingest | `del data\jokes.db && python -m src.tg_autopost ingest` |
| Publish one post | `python -m src.tg_autopost publish` |
| Run scheduler + polling | `python -m src.tg_autopost run` |
| `ADMIN_ID` | Add your Telegram user ID in `.env` for submission moderation |
