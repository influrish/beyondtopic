# BeyondTopic

BeyondTopic is an independent, multi-topic editorial publication with a connected publisher studio. The public site and CMS use the same SQLite database. The project uses Python 3.9+, WSGI, and SQLite without third-party Python packages.

## Run locally

From the project folder:

```sh
python3 -m app.server
```

Open <http://127.0.0.1:8000/>. Publisher sign-in is at <http://127.0.0.1:8000/admin/login>. The first run creates an `admin` user and prints a one-time random password in the server terminal. Set `BEYONDTOPIC_ADMIN` and `BEYONDTOPIC_PASSWORD` before the first run to choose local credentials. If the password is lost, run `python3 scripts/reset_password.py` in a terminal.

The app binds to `127.0.0.1` by default. Set `PORT` to choose a port. Only set `BEYONDTOPIC_HOST` when intentionally exposing the server. A public deployment also needs HTTPS, a production WSGI server, and a reverse proxy.

## Configuration and data

- `BEYONDTOPIC_DB` chooses the database file; default: `data/beyondtopic.sqlite3`.
- `BEYONDTOPIC_SECRET` supplies the session and preview signing key. Without it, the first run creates `data/.signing-key` with owner-only file permissions.
- `BEYONDTOPIC_URL` sets the canonical site URL used in SEO and sitemap output.
- `BEYONDTOPIC_TIMEZONE` sets the scheduling timezone; default: `Asia/Kolkata`.
- Uploaded media and the SQLite database are stored under `data/`, which is ignored by Git.

Back up both database and uploads with `python3 scripts/backup.py`. Check the backup and restore process before relying on it.

## Images and sample stories

The first run creates five labelled starter stories in each of Fashion, Lifestyle, Travel, Beauty, Shopping, Technology, and Wellness. Each story has its own descriptive editorial photo URL from Unsplash. The images load from Unsplash’s image CDN, so viewing those covers requires an internet connection. The source and image credit are shown with each story. Starter content is marked on the site and can be edited or moved to trash from **Studio → Stories**. Its starter-content label can be removed in the editor after the story has been replaced and reviewed.

The About, Editorial Policy, and Affiliate Disclosure pages are editable starter pages. Privacy, Terms, Contact, and other legal or operational pages remain drafts until the publisher completes them. Draft pages are not advertised as public links.

## Main routes

Public: `/`, `/blog`, `/blog/<slug>`, `/category/<slug>`, `/tag/<slug>`, `/author/<slug>`, `/search?q=...`, `/page/<slug>`, `/subscribe`, `/unsubscribe`, `/sitemap.xml`, and `/robots.txt`.

Studio: `/admin` with story and page editors, categories, tags, authors, media, products, affiliate links, navigation, homepage sections, subscribers, redirects, settings, SEO, users, activity, and system status.

## Editorial workflow

Use **Studio → Stories → New story** to write a draft. The editor provides a small Markdown formatting toolbar and a safe preview. Assign the author, category, tags, cover image, SEO fields, and workflow state. Stories support draft, pending review, scheduled, published, archived, and trashed states. Authors and contributors can edit only their assigned stories and cannot publish. Editors can publish. Signed story previews are excluded from search indexing. Changing a published slug creates a local redirect.

A background worker publishes scheduled posts while the app process is running. It is an in-process worker, not a durable queue. Reorder and manage homepage sections in **Studio → Homepage**. When no custom sections have been configured, the public homepage uses the enabled top-level categories.

## Roles

- **Administrator:** full studio access and user management.
- **Editor:** editorial and day-to-day studio access; site security and account settings remain restricted.
- **Author / Contributor:** assigned stories and media only; publication requires review.
- **SEO Manager:** SEO settings and redirects.
- **Affiliate Manager:** affiliate product and link records.

The role restrictions are checked on the server. The login reset flow is local command-line only; email password recovery is not configured.

## Tests

```sh
python3 -m unittest discover -s tests
```

The automated suite covers session/password utilities, login and permissions, story/page publishing, search, route access, subscriber consent and opt-out, and public editorial rendering. It is a focused WSGI test suite rather than a complete browser, accessibility, or security audit.

## Implemented

- Responsive editorial identity, image-led public homepage, article and category layouts, archive, database-backed search, author/tag pages, editable published pages, metadata, Open Graph tags, JSON-LD for stories, sitemap, robots, and internal redirects.
- SQLite content system with categories, tags, author profiles, media, subscribers, affiliate products and links, navigation, homepage sections, revisions, sessions, and audit records.
- CSRF-protected login and forms, password hashing, signed sessions and previews, role checks, login throttling, escaped editorial content, constrained raster uploads, safe external-link checks, and database-backed dashboard counts.
- Starter content is marked as sample, uses 35 distinct category-appropriate photo URLs, and is inserted through a versioned, repeat-safe first-run seed.
- Local newsletter consent records, signed unsubscribe flow, opt-out status, and an administrator CSV export.

## Known limits

This is a runnable local publishing project, not a production-certified enterprise CMS. Before public launch, review all starter copy and legal pages, use a managed database and media store if required, enable HTTPS, configure a mail provider, and run broader deployment and security checks.

The writing interface is a Markdown editor with a preview, not a full drag-and-drop block editor. Uploaded images are stored locally and no responsive derivatives are generated. Starter photography is served from Unsplash rather than bundled locally. Newsletter addresses are recorded and can unsubscribe, but confirmation and campaign email require a provider. Analytics shows an honest unconfigured state; external analytics and affiliate conversion data are not integrated. Comments are disabled. Scheduled publishing works only while the app process remains running. There is no managed job queue, email password reset, automated media-usage scan, external broken-link checker, object storage, PostgreSQL migration, multi-factor authentication, or complete revision comparison UI. Tests do not replace real-browser accessibility and responsive checks.

No affiliate commission, product test, live offer, analytics total, or reader figure is claimed by the sample data. Before deployment, use private secrets, a production server, HTTPS, regular backups, and completed privacy/terms pages. Never publish this workspace’s database, uploaded private files, or secrets.
