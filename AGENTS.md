## Shell

User's terminal is **CMD** (Command Prompt), NOT PowerShell.
Use CMD-compatible syntax for all commands (`del` instead of `Remove-Item`, `&&` for chaining).

| Action | Command |
|--------|---------|
| Drop DB + re-ingest | `del data\jokes.db && python -m src.tg_autopost ingest` |
| Publish one post | `python -m src.tg_autopost publish` |
| Run scheduler + polling | `python -m src.tg_autopost run` |
| `ADMIN_ID` | Add your Telegram user ID in `.env` for submission moderation |

## Schedule (MSK, 5 posts/day) — handled by **external cron (cron-job.org)**

| Time | Action | Endpoint |
|------|--------|----------|
| 10:00 | Joke (`run_ingest_and_publish`) | `GET /cron/joke?key=CRON_SECRET` |
| 11:30 | Horoscope | `GET /cron/horoscope?key=CRON_SECRET` |
| 14:00 | Joke (`run_ingest_and_publish`) | `GET /cron/joke?key=CRON_SECRET` |
| 17:00 | Meme (`publish_meme_image`) | `GET /cron/meme?key=CRON_SECRET` |
| 20:00 | Newsjacker (fallback: regular joke) | `GET /cron/newsjacker?key=CRON_SECRET` |
| 23:00 | Pin best post | `GET /cron/pin?key=CRON_SECRET` |

## Web Endpoints (Render)

| Route | Description |
|-------|-------------|
| `/` | SEO homepage — latest 5 jokes, all rubrics, subscribe CTA |
| `/p/<msg_id>` | Landing page per joke — shows joke, share buttons (TG/X/VK/WA/FB), copy link |
| `/share/<msg_id>` | Redirects to `t.me/share/url` with joke text + subscribe CTA pre-filled |
| `/img/<msg_id>` | OG image card with joke text rendered as JPEG |
| `/joke/<id>` | SEO page per joke — all published jokes indexed, schema.org, exit-intent, sticky bar |
| `/img/joke/<id>` | OG image + download card for any joke |
| `/top` | Top 20 paginated jokes (`?page=N`) + referrer leaderboard |
| `/rubric/<slug>` | Jokes by category (semeynoe, rabochee, zhivotnye, etc.) |
| `/<slug>` | **66 SEO landing pages** for keyword queries (smeshnye, korotkie, pro-rabotu, etc.) |
| `/search?q=` | Keyword search with result highlighting |
| `/random` | Redirect to a random published joke |
| `/chat` | Page about discussing jokes in channel comments |
| `/manifest.json` | PWA manifest for mobile app install |
| `/sw.js` | Service worker for PWA |
| `/api/random-joke` | JSON API — random joke (CORS enabled, for widgets) |
| `/api/top-referrers` | JSON API — top 10 referrers |
| `/api/publish` | Manual trigger — publishes one joke (POST via browser GET) |
| `/keepalive` | Keep Render free tier alive (cron-job.org pings every 10 min) |
| `/debug` | Bot status: polling alive, bot info, webhook status, **keepalive timestamp, cron locks** |
| `/cron/joke` | **External cron** — triggers joke publish (requires `?key=CRON_SECRET`) |
| `/cron/horoscope` | **External cron** — triggers horoscope (requires `?key=CRON_SECRET`) |
| `/cron/meme` | **External cron** — triggers meme (requires `?key=CRON_SECRET`) |
| `/cron/newsjacker` | **External cron** — triggers newsjacker (requires `?key=CRON_SECRET`) |
| `/cron/pin` | **External cron** — triggers pin best (requires `?key=CRON_SECRET`) |
| `/cron/catchup` | **External cron** — runs catch-up for missed slots (requires `?key=CRON_SECRET`) |
| `/widget.js` | Embeddable widget — paste `<script src=".../widget.js">` on any site |
| `/widget` | Widget documentation page with live preview |
| `/rss.xml` | RSS 2.0 feed (last 20 jokes) |
| `/sitemap.xml` | Sitemap index → `sitemap-pages.xml` (pages + rubrics + 66 SEO landings) + `sitemap-jokes.xml` (ALL jokes) |
| `/robots.txt` | Robots disallows nothing, points to sitemap |
| `/avatar.png` | Channel avatar image |

## Critical architecture notes

- **SQLite (`data/jokes.db`) is ephemeral on Render free tier** — wiped on every deploy/restart. Startup ingest refills DB.
- **External cron (cron-job.org) is PRIMARY scheduler** — hits HTTP endpoints at schedule times. The request itself wakes Render if asleep. In-process APScheduler only runs startup ingest + catch-up.
- **Idempotency locks** per action (via `channel_meta` table) prevent double posts if both external cron and catch-up fire.
- **Ingest timeout**: 120s via `ThreadPoolExecutor`. Prevents hanging on blocked sources.
- **`sendStory` Not supported in Bot API** — only `postStory` for Business accounts. Stories slot removed.
- **Keepalive**: cron-job.org (`kru.kru.dih@mail.ru` / `350045008000Vfrcbv`) pings `/keepalive` every 10 min. Timestamp visible in `/debug`.
- **Catch-up on startup**: after each deploy/wake, missed slots are published (within 2h TTL).

## On-page conversion tactics
- **Sticky subscribe bar** — appears on scroll on all pages
- **Exit-intent popup** — "Уже уходите?" popup on mouse leave (once per visitor)
- **Copy attribution** — copying joke text appends "— Подпишись: t.me/Anetdodik"

## Referral system
- Bot command `/invite` gives personal referral link `t.me/bot?start=ref_<id>`
- When someone joins via link, tracked in `referrals` table
- Leaderboard on `/top` page
- API: `/api/top-referrers` (CORS, cached 5 min)

## YouTube OAuth — DONE ✅
- OAuth refresh token obtained via `urn:ietf:wg:oauth:2.0:oob` + manual code copy
- Client type: Desktop ("installed"), NOT "web"
- PKCE was required — used custom script with saved `code_verifier`
- Secrets added to GitHub: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`
- `.env` updated locally with all 5 YouTube vars
- Workflow triggered manually for testing

## Cron setup (cron-job.org)
- Add 6 jobs hitting the endpoints above at the schedule times
- Use `key=CRON_SECRET` query param
- Ensure job is active (free tier may pause after inactivity — check periodically)
