# igtt — Instagram Content Intelligence for @drinktoiletwine

**Date:** 2026-09-07
**Status:** Approved design, ready for implementation planning

## Purpose

A daily job that monitors public Instagram accounts in the wine / meme / hospitality
space, finds the posts that are outperforming, works out *why* they worked, abstracts
each into a reusable format, and generates original content briefs for
[@drinktoiletwine](https://www.instagram.com/drinktoiletwine/). Content that gets
published is tracked with the same machinery, so the system learns which formats work
for this account specifically.

Goal: grow followers and engagement on one account. Every design decision below is
subordinate to that.

## Scope

**In scope (v1):** Instagram only. Collection, scoring, two-tier AI analysis, pattern
detection, idea generation, HTML report, email delivery, approve-then-publish, own-post
performance tracking, weekly account discovery.

**Out of scope (v1):** TikTok (added later as an adapter behind the same `posts`
schema). AI video generation. Any web dashboard, React frontend, Docker, Airtable,
Make, Zapier, or hosted database.

**Deferred deliberately:** unattended auto-posting (config flag exists, defaults off);
multi-brand support; comment/DM automation.

## Constraints

- Python 3.11, stdlib `sqlite3`, no database server.
- Maintainable by a non-developer: ongoing changes should touch `config.yaml` and
  `.env` only.
- Runs unattended on GitHub Actions; laptop may be closed.
- Hard spend ceilings enforced in code, not by convention.
- No competitor content is copied. Formats are abstracted; assets are not reused
  except through the explicitly permission-gated repost lane.

## Architecture

Three entry points against one SQLite file.

```
discover.py (weekly)        app.py (daily)                   post.py (on dispatch)
──────────────────────      ─────────────────────────────    ────────────────────────
hashtag + niche search      collect: Apify -> posts          read approved idea id
  -> candidate accounts     snapshot: metrics -> snapshots   upload media -> Blotato
Claude relevance 0-100      score:  numeric rank (all)       POST /v2/posts
  >=70 activate             analyze: Claude text (top 40)    mark idea posted
  <50  deactivate           analyze: Gemini video (top 15)   register our post for
                            patterns: cluster 7/30/90d         later snapshotting
                            ideas:   10 briefs
                            report:  latest.html + email
```

### Component boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `src/db.py` | schema creation, all SQL, migrations | sqlite3 |
| `src/apify.py` | "give me recent posts for these usernames" -> normalized dicts | requests |
| `src/score.py` | percentile normalization, velocity, acceleration, final score | pure functions |
| `src/analyze.py` | Claude text tier + Gemini video tier -> validated JSON | anthropic, google-genai |
| `src/patterns.py` | cluster analyses into recurring patterns, trend direction | anthropic |
| `src/ideas.py` | generate briefs from top posts + patterns + our results | anthropic |
| `src/report.py` | render jinja2 template, optional SMTP send | jinja2 |
| `src/blotato.py` | media upload + post publish | requests |

`src/apify.py` is the only module that knows scraping exists. It returns a normalized
post dict; swapping providers or adding TikTok touches this file and nothing else.
`src/score.py` is pure functions over lists of dicts — no I/O, trivially testable.

## Data model

One SQLite file at `data/intelligence.db`.

```sql
accounts(
  id, username, platform, category, followers,
  relevance_score, active, last_checked, added_at, notes
)

posts(
  id, platform, shortcode UNIQUE, account_id, url, video_url, thumbnail_url,
  caption, content_type, posted_at, duration_sec,
  is_ours, first_seen_at
)

post_snapshots(
  id, post_id, captured_at,
  views, likes, comments, shares
)

analyses(
  id, post_id, tier,            -- 'text' | 'video'
  json, ai_virality_score, model, created_at
)

patterns(
  id, pattern, description, first_seen, last_seen,
  occurrences_7d, occurrences_30d, occurrences_90d,
  avg_performance, trend_direction, dtw_relevance
)

ideas(
  id, created_at, brief_json, source_pattern_id,
  similarity_risk, confidence, status,   -- 'new' | 'posted' | 'rejected'
  posted_shortcode, posted_at
)

repost_candidates(
  id, post_id, permission_granted, credit_handle,
  requested_at, granted_at, status
)
```

**Rules:**

- A metric that does not exist for a post type stores `NULL`, never `0`. A carousel has
  no view count; a missing share count is not zero shares. Scoring skips `NULL`s rather
  than treating them as lows.
- `post_snapshots` is append-only. Multiple rows per post is the point — the delta
  between rows is what produces velocity and acceleration.
- `posts.is_ours` marks @drinktoiletwine's own content. It flows through the identical
  collect / snapshot / score path as competitor content.
- `shortcode` is the natural key. Re-collection upserts posts and always appends a
  snapshot.

## Scoring

Two stages: a free numeric stage over every post, then an AI stage over survivors only.

### Numeric (all posts, no API cost)

Per-post metrics, computed from the latest snapshot and account follower count:

```
views_per_follower    = views / followers
engagement_rate       = (likes + comments + shares) / views
total_engagement      = likes + comments + shares
raw_views             = views
comments_per_follower = comments / followers
```

Each is converted to a percentile within the day's collected set, then weighted:

```
performance_score = 0.30 * pct(views_per_follower)
                  + 0.25 * pct(engagement_rate)
                  + 0.20 * pct(total_engagement)
                  + 0.15 * pct(raw_views)
                  + 0.10 * pct(comments_per_follower)
```

### Age handling

Raw totals unfairly favour older posts. From consecutive snapshots:

```
views_per_hour   = (views_n - views_n-1) / hours_elapsed
acceleration     = views_per_hour(latest window) / views_per_hour(previous window)
```

`acceleration > 1.5` sets an `accelerating` flag. A two-hour-old post with steep
acceleration surfaces alongside a six-day-old post with a large total, which is the
early-viral signal the whole system exists to catch.

### Final ranking

```
final_score = 0.80 * performance_score + 0.20 * ai_virality_score
```

Posts without an AI analysis use `performance_score` alone and are ranked below
analyzed posts of equal score.

## AI analysis — two tiers, two vendors

Never send every post to a model. The numeric stage does the filtering.

**Tier 1 — text (top 40 by `performance_score`).** Claude receives caption, metrics,
account context, post type and timing. Returns the strategist JSON: hook, hook type,
payoff, emotional driver, social driver, comment driver, rewatch driver, audience,
timing, three reasons it overperformed, reusable pattern, six sub-scores, and an
`ai_virality_score` 0-100.

**Tier 2 — video (top 15 after tier 1).** Gemini 2.5 Flash ingests the MP4 URL
natively and returns the recreation blueprint. Schema reused verbatim from the existing
n8n "Short Form Video Analyzer" workflow:

```json
{
  "core_concept": "", "target_audience": "",
  "hook_analysis": {"visual_elements":"", "audio_elements":"",
                    "psychological_trigger":"", "hook_formula":""},
  "content_structure": {"opening":"", "development":"",
                        "climax_payoff":"", "call_to_action":""},
  "visual_style": {"layout":"", "text_overlays":"", "camera_work":"",
                   "ui_style":"", "speaker_framing":"", "music":""},
  "recreation_framework": {"universal_elements":[], "customizable_elements":[],
                           "common_variations":[]}
}
```

**Why two vendors.** Claude has no native video input; feeding it a Reel would require
frame extraction plus audio transcription — more code, more failure surface, worse
result. Gemini 2.5 Flash takes the URL directly. Claude keeps all text work: analysis,
clustering, ideas, report copy. Two keys in `.env`, one clear split of duties.

Both tiers validate against the expected JSON shape. A malformed response is retried
once, then logged and skipped. One bad post never fails the run.

## Pattern detection

Patterns are not asked for daily. Claude receives the accumulated `analyses` for the
last 7, 30 and 90 days and clusters the `reusable_pattern` fields into named recurring
formats, each with occurrence counts per window, average performance, and a trend
direction derived from 7d-vs-prior-7d movement.

Output is a diff, not a snapshot: "Hospitality confessionals appeared in 11
high-performing posts this week versus 3 last week" is actionable; "here are some
popular posts" is not.

## Idea generation

Inputs: today's top 25, the 7/30/90-day patterns, the last 20 DTW ideas, and — the part
that closes the loop — the measured performance of DTW posts already published.

Ten briefs per day, each containing: concept, why now, source pattern, hook, opening
frame, script, on-screen text, shot list, caption, CTA, format, difficulty, confidence,
and `similarity_risk` (LOW / MEDIUM / HIGH).

Any idea scored HIGH similarity to a single competitor post is rejected at generation
time and never reaches the report.

## The feedback loop

Without this the system only ever admires other people's posts.

1. A published DTW post is inserted into `posts` with `is_ours = 1`.
2. It is snapshotted daily like any tracked post.
3. The report carries a "How ours did" block: each recent DTW post against the account's
   own 30-day baseline, and against the competitor formula it was derived from.
4. Those results are fed into the next idea-generation prompt, so Claude is told which
   formats have actually worked for this account, not just for the niche.

## Publishing

`post.py` takes one argument: an idea id. It uploads media to
`POST https://backend.blotato.com/v2/media`, publishes with
`POST https://backend.blotato.com/v2/posts` targeting Instagram, marks the idea
`posted`, and inserts the resulting post with `is_ours = 1`.

Approval requires no UI. A GitHub Actions workflow with `workflow_dispatch` and a single
`idea_id` input drives it; the daily report prints each idea's id next to a link to the
Run-workflow page. Approving is two taps on a phone.

`config.yaml` carries `posting.auto: false`. Setting it true lets the daily run publish
the top-confidence idea unattended. It stays false until the briefs have proven
themselves.

Blotato is chosen over the Instagram Graph API to avoid Meta app review entirely.

## Repost lane

Reposting another creator's Reel is their copyright, and repeat strikes cost the very
account this system exists to grow. The lane exists but is fenced:

- `repost_candidates` rows require `permission_granted = 1` and a non-empty
  `credit_handle` before `post.py` will act on them.
- Permission is obtained by the operator, out of band. The system records it; it does
  not request it.
- Default posture is refilming the abstracted format, which is what
  `recreation_framework` is for.

## Error handling

- Every external call is wrapped; a failure logs and returns `None` rather than raising.
- Apify failure for one account does not abort collection for the rest.
- AI failure for one post does not abort the batch.
- Email failure never fails the daily run — the report is already written to disk.
- The run reports what it managed to do: accounts reached, posts collected, analyses
  completed, failures by category.
- Logging via stdlib `logging` to stdout, so Actions captures it.

## Cost control

Hard limits in `config.yaml`, enforced in code by truncation, not by trust:

```yaml
brand:
  name: Drink Toilet Wine
  instagram: drinktoiletwine

monitoring:
  max_accounts: 75
  posts_lookback_days: 7
  candidate_posts_for_text_ai: 40
  candidate_posts_for_video_ai: 15
  daily_top_posts: 25

categories: [wine, wine memes, alcohol, hospitality, restaurants,
             lifestyle, food, comedy]

scoring:
  views_per_follower: 0.30
  engagement_rate: 0.25
  total_engagement: 0.20
  raw_views: 0.15
  comments: 0.10
  ai_weight: 0.20

discovery:
  activate_above: 70
  deactivate_below: 50

ideas:
  daily_count: 10

posting:
  auto: false
  max_per_day: 1
```

Exceeding a limit logs a warning and truncates. It never silently spends more.

## Testing

- `src/score.py` is pure functions — unit tested directly, including the `NULL`-metric
  and single-snapshot (no velocity yet) edge cases.
- Apify and Blotato responses are captured once as fixtures under `tests/fixtures/`.
  No live network calls in CI, ever.
- AI calls are mocked at the client boundary; what is tested is that a malformed
  response is handled, not that the model is smart.
- One end-to-end test runs the full daily pipeline against fixtures into a temporary
  SQLite file and asserts a report is produced.

## Deployment

GitHub Actions, cron daily plus `workflow_dispatch`. All credentials from Actions
secrets: `APIFY_TOKEN`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `BLOTATO_API_KEY`,
`SMTP_*`.

**State persistence:** Actions has no persistent disk. `data/intelligence.db` is
committed back to the repository after each successful run. This grows the repo by a
few MB a month and keeps full history. The alternative, Actions cache, silently evicts
and would destroy the trend data the 30- and 90-day windows depend on. The commit is
deliberate.

## Repository

Renamed from `yt-analyzer` to `igtt`. The YouTube-specific modules
(`src/fetch_channel.py`, `src/analyze_topics.py`, and their tests) are deleted; they
remain in git history. The scaffolding that already works is kept and repurposed: the
orchestrator shape of `run.py`, the jinja2 report template with autoescape enabled,
pytest with shared fixtures, and the Actions workflow.

```
igtt/
├── app.py                  daily run
├── discover.py             weekly account discovery
├── post.py                 publish one approved idea
├── config.yaml
├── .env.example
├── requirements.txt
├── src/
│   ├── db.py  apify.py  score.py  analyze.py
│   ├── patterns.py  ideas.py  report.py  blotato.py
│   └── templates/report.html
├── prompts/
│   ├── analyze_text.md  analyze_video.md
│   ├── patterns.md  ideas.md  discover.md
├── data/intelligence.db
├── reports/latest.html
└── tests/
```

Prompts live in `prompts/*.md` as plain files, not embedded in Python, so they can be
tuned without touching code.

## Build order

Each phase is runnable and testable before the next begins.

0. Gut the YouTube code. `config.yaml`, `.env.example`, schema, `db.py`.
1. Collection: Apify -> normalized posts -> SQLite, fixture-backed tests.
2. Snapshots and numeric scoring, including velocity and acceleration.
3. Tier 1 text analysis (top 40), then tier 2 video analysis (top 15).
4. Pattern clustering, idea generation, HTML report, optional email.
5. Own-post tracking and the feedback loop into idea generation.
6. `post.py`, Blotato integration, dispatch workflow.
7. `discover.py`.
8. Actions cron, secrets, DB commit-back.

Later: TikTok adapter behind the existing `posts` schema.

## Open items

- **Rotate the exposed Apify token.** The token in
  `Short Form Video Analyzer (1).json` is live and has been shared. Rotate before
  first run and keep the replacement in `.env` only.
- Seed account list (~55 usernames across wine, memes, hospitality, alcohol brands,
  lifestyle/food) needs to be supplied or bootstrapped by a first `discover.py` run.
- Gmail SMTP app password required if email delivery is enabled at phase 4.
