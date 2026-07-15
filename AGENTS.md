## Shell

User's terminal is **CMD** (Command Prompt), NOT PowerShell.
Use CMD-compatible syntax for all commands (`del` instead of `Remove-Item`, `&&` for chaining).

| Action | Command |
|--------|---------|
| Drop DB + re-ingest | `del data\jokes.db && python -m src.tg_autopost ingest` |
| Publish one post | `python -m src.tg_autopost publish` |
| Post a story | `python -m src.tg_autopost story` |
| Run scheduler + polling | `python -m src.tg_autopost run` |
| `ADMIN_ID` | Add your Telegram user ID in `.env` for submission moderation |

## Web Endpoints (Render)

| Route | Description |
|-------|-------------|
| `/` | SEO homepage — latest 5 jokes, all rubrics, subscribe CTA |
| `/p/<msg_id>` | Landing page per joke — shows joke, share buttons (TG/X/VK/WA/FB), copy link |
| `/share/<msg_id>` | Redirects to `t.me/share/url` with joke text + subscribe CTA pre-filled |
| `/img/<msg_id>` | OG image card with joke text rendered as JPEG |
| `/joke/<id>` | SEO page per joke — all published jokes indexed, schema.org, exit-intent, sticky bar |
| `/img/joke/<id>` | OG image + download card for any joke |
| `/top` | Top 20 paginated jokes (`?page=N`) |
| `/rubric/<slug>` | Jokes by category (semeynoe, rabochee, zhivotnye, etc.) |
| `/search?q=` | Keyword search with result highlighting |
| `/random` | Redirect to a random published joke |
| `/api/random-joke` | JSON API — random joke (CORS enabled, for widgets) |
| `/widget.js` | Embeddable widget — paste `<script src=".../widget.js"></script>` on any site |
| `/widget` | Widget documentation page with live preview |
| `/rss.xml` | RSS 2.0 feed (last 20 jokes) |
| `/sitemap.xml` | Sitemap index → `sitemap-pages.xml` + `sitemap-jokes.xml` (ALL jokes) |
| `/robots.txt` | Robots disallows nothing, points to sitemap |
| `/avatar.png` | Channel avatar image |

## On-page conversion tactics
- **Sticky subscribe bar** — appears on scroll on all pages
- **Exit-intent popup** — "Уже уходите?" popup on mouse leave (once per visitor)
- **Copy attribution** — copying joke text appends "— Подпишись: t.me/Anetdodik"

## YouTube OAuth — DONE ✅
- OAuth refresh token obtained via `urn:ietf:wg:oauth:2.0:oob` + manual code copy
- Client type: Desktop ("installed"), NOT "web"
- PKCE was required — used custom script with saved `code_verifier`
- Secrets added to GitHub: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
- `.env` updated locally with all 5 YouTube vars
- Workflow triggered manually for testing
