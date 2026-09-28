# Dashboard accessibility, URL state and browser acceptance

This document records the M5.2 dashboard contract. It is an engineering boundary, not a claim that every assistive-technology and browser combination has been independently certified.

## Keyboard and focus contract

- The first focusable control is **Skip to main content**. Activating it focuses the `main` landmark.
- The desktop sidebar and compact narrow-layout navigation expose the same authorized destinations.
- Native links, buttons, form controls, `details`/`summary` disclosures and tables are retained instead of simulated clickable containers.
- Focus is visibly indicated with a non-color-only outline. Opening an item from the review queue moves focus to the failure workspace after the selected run/failure is loaded.
- Mutation results are announced through a polite live region; validation and API failures remain assertive alerts.
- Status chips contain readable text. Decorative dots are hidden from accessibility APIs and never carry status by themselves.
- `prefers-reduced-motion: reduce` disables smooth scrolling and shortens animation/transition duration.

## Narrow layout

At widths below 1100 pixels the sticky sidebar is replaced by a keyboard-operable compact navigation disclosure. Tables remain in bounded horizontal scroll containers rather than widening the page. Review/audit filters and system-status cards collapse from multi-column layouts to one column as available width decreases.

The narrow Playwright project uses a 390 × 844 viewport and asserts that the document and body do not exceed the viewport width, while review, settings and health controls remain reachable.

## URL-restored state

The dashboard stores investigation selections and meaningful filters in query parameters using `history.replaceState`. Reloading or sharing the URL retains valid state; unavailable identifiers safely fall back to the first authorized persisted record.

| Area | Parameters |
|---|---|
| Investigation | `project`, `run`, `failure`, `cluster`, `impact` |
| History | `history_scope`, `history_browser`, `history_branch`, `history_environment`, `history_workers`, `history_shards` |
| Review queue | `review_status`, `review_category`, `review_search`, `review_sort`, `review_page` |
| Audit | `audit_search`, `audit_action`, `audit_outcome`, `audit_sort`, `audit_page` |

Default values are omitted to keep URLs readable. Browser back/forward navigation reapplies the represented state without bypassing API authorization.

## Review and audit behavior

The review queue requests a bounded latest-analysis window of up to 500 authorized records, then exposes explicit pending/reviewed/category/search/sort filters and ten-row pages. A needs-more-evidence decision remains pending; accept, reject and category correction are terminal for queue filtering. The visible matching/total count prevents the client-side view from implying that an empty filtered page means no analysis exists.

Audit filters operate only on a bounded window of up to 500 records already authorized and returned for the selected project. CSV export includes timestamp, actor, actor kind, action, outcome, resource type/id and reason, protects formula-leading fields, and never includes session secrets, password hashes or ingestion-token values. The export is a client-side view convenience, not a retention or cryptographic-immutability guarantee.

## Browser projects

`frontend/playwright.config.ts` defines:

1. `chromium-desktop`
2. `firefox-desktop`
3. `webkit-desktop`
4. `chromium-narrow`

Desktop projects execute the durable ingestion/review, impact override and accessibility/URL-restoration journeys. The narrow project executes the responsive-navigation and overflow journey. CI installs all three desktop engines and retains traces and screenshots only on failure.

## Automated accessibility assertions

The API-backed accessibility journey checks representative authenticated views for:

- keyboard access to the skip link and focused main landmark;
- visible form controls with an associated label or accessible name;
- named buttons and disclosures;
- non-skipping heading order in rendered views;
- visible tables with captions and scoped column headers;
- non-empty status labels;
- URL persistence across reload;
- reachable review/audit filters and export controls.

These checks intentionally avoid claiming exhaustive WCAG conformance. Manual screen-reader testing, high-contrast/forced-colors testing and a broader account-recovery workflow remain future work.

## Local and CI commands

```bash
cd frontend
npm ci --no-audit --no-fund
npm test
npm run build
npx playwright install --with-deps chromium firefox webkit
npm run test:e2e
```

The Playwright command requires the API, worker and dashboard processes plus a migrated PostgreSQL database. `.github/workflows/ci.yml` provides the authoritative reproducible environment. A source-only static compile is not a substitute for the exact delivered CI run.
