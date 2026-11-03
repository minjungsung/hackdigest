# Seoul Building Discount Monitor

This prototype monitors Seoul commercial and office buildings and emails newly qualifying listings whose advertised price is **at least 40% below a documented formal appraisal**. Regular-sale asking prices and public-auction minimum bids use the same threshold, with their price basis clearly identified in each email.

The monitoring engine is implemented and tested. The `Seoul Building Monitor` GitHub Actions workflow provides hourly cloud execution using HackDigest's existing Gmail secrets. **A deployed runner does not establish live listing coverage:** collection starts only when source credentials are connected, and discount alerts also require verified whole-property appraisal evidence. Regular-sale coverage needs a data supplier. National coverage of private building sales is not available through this prototype.

## Cloud deployment

The workflow runs at minute 17 of every hour on the default branch; GitHub may delay scheduled execution. It also supports a manual run with `send_status=true` to email actual deployment/collection status. Code changes run validation without sending emails. Concurrent production runs are serialized.

Protected repository configuration:

| Secret | Purpose |
| --- | --- |
| `EMAIL_FROM` and `EMAIL_APP_PASSWORD` | Existing HackDigest Gmail sender and SMTP app password, reused within the same repository without extracting the password. |
| `BUILDING_ALERT_TO` | Single recipient authorized to receive building-monitor emails. |
| `ONBID_SERVICE_KEY` | Approved official Onbid list-service key. |
| `BUILDING_REVIEWS_CSV` | Optional verified property/appraisal mapping in the review CSV format. |
| `BUILDING_FEED_URL` and `BUILDING_FEED_TOKEN` | Optional authorized HTTPS regular-sale feed and its bearer token. |

Credentials are injected as environment variables and are not stored in the source repository or collection reports. GitHub caches preserve only the SQLite alert history and request budget, including after a partial collection failure. Article-cache clearing is restricted to HackDigest's article-cache prefix. Health summaries are retained as workflow artifacts for seven days; complete listing inventories and appraisal links are not uploaded as workflow artifacts.

Without a source key or supplier feed, the cloud runner records `awaiting_onbid_credentials` and does not claim to have monitored listings. One-time status emails state this limitation explicitly. A fresh source connection can be tested with a manual workflow run. API authorization and actual collection must both be checked before reporting the source as operational.

## Matching rule

```text
advertised total price <= formal whole-property appraisal × 0.60
```

An appraisal of KRW 5 billion and a price of KRW 3 billion qualify exactly. A price of KRW 3,000,000,001 does not. The engine compares integer KRW with exact decimal arithmetic.

Current policy:

- Seoul only; commercial or office use.
- Entire property, including the land and building. Individual units, floors, partial interests, bundled assets, and unit prices are excluded.
- Active sales, upcoming bids, or available private contracts.
- A verified formal appraisal with an evidence link, appraisal date, matching property identity, and matching valuation scope.
- Appraisals no more than 365 days old and listing observations no more than seven days old. These are configurable prototype defaults.
- Missing prices, unpublished minimum bids, tax values, AI estimates, and unverified appraisals do not generate discount alerts.

An advertised price below an appraisal does not establish a discount to today's market value. A minimum bid also does not determine the eventual winning price.

## Data collection routes

| Route | Verified availability | Prototype connection | Remaining work |
| --- | --- | --- | --- |
| [Onbid real-estate list API](https://www.data.go.kr/data/15157207/openapi.do) | Official service lists current/upcoming assets, appraisal amounts, minimum-bid information, addresses, categories, and bidding dates. Portal metadata states hourly updates, free access, and automatic API application approval. | Implemented against the published 2026 API specification; authentication and live responses have not been tested. | Obtain a service key and review whole-property identity, appraisal date, and scope. |
| [Onbid real-estate detail API](https://www.data.go.kr/data/15157247/openapi.do) | Official service exposes appraisal-information lists, area details, tenancy information where available, and other asset details. | Research source for manual review; automatic detail enrichment is not implemented. | Open the asset in Onbid using its management number and confirm the appraisal and sale documents. Apply separately for the detail API if adding automated enrichment. |
| Building brokers and owners | A supplier can provide asking prices and appraisal documents for its own available properties. | Local CSV/JSON and an HTTPS JSON feed are implemented. No supplier has been connected. | Arrange a feed/export of Seoul whole-building commercial and office sales. Require stable listing/property IDs and current availability timestamps. |
| [RealtyPlanet](https://www.bdsplanet.com) | Public homepage provides listing, commercial-property, transaction, AI-value, and deal-information navigation. | Supplier candidate only; no crawler or private API is implemented. | Confirm an available integration/export and access terms with the provider. Do not treat its AI value as a formal appraisal. |
| [Court Auction Information](https://www.courtauction.go.kr) | Official court-auction portal is reachable. | Not connected. Court-auction exports can be supplied through the normalized feed format. | Select a documented API, permitted export, or licensed auction-data supplier before implementing collection. |

The regular-sale route is the principal data dependency. A generic feed reader does not collect private listings by itself. A practical initial supply arrangement is a daily broker export of current Seoul commercial/office whole-building sales, accompanied by appraisal documents for properties with a formal appraisal. No brokerage outreach has been sent.

For a supplier, request the fields in [examples/general-sales.csv](examples/general-sales.csv), plus a reviewed appraisal amount, appraisal date, valuation scope, and evidence URL. If there is no formal appraisal, keep the property in the input data with the appraisal fields empty; it will appear in the collection report but will not trigger a 40% discount email. The supplier must explicitly identify the property; the engine does not join appraisals based on approximate address similarity.

Public-source observations and specification hashes are recorded in [sources.json](sources.json). Public web pages confirm service availability, not complete access to listing data or permission for a particular automated integration.

## Run the demonstration

Requires Python 3.10 or later on macOS or Linux, with SQLite and standard timezone data. There are no third-party Python dependencies.

From the project directory:

```sh
python3 -m building_monitor demo
```

This uses four synthetic properties and saves an email preview for the one qualifying property under `data/demo/email-preview.eml`. It does not use credentials, contact live listing sources, or send an email. The other examples demonstrate a price one won above the threshold, a missing appraisal, and an individual unit.

## Configure the live sources and email

```sh
cp config.example.json config.json
cp .env.example .env
cp examples/reviews.csv reviews.csv
chmod 600 .env
```

Keep the credentials in the local `.env`, which is ignored by Git. The loader treats values literally and does not execute shell expressions. Existing environment variables take precedence. A deployment can inject the same environment variables directly.

| Variable | Meaning |
| --- | --- |
| `ONBID_SERVICE_KEY` | Key approved for the Onbid real-estate list service; encoded or decoded forms are accepted. |
| `SMTP_HOST` | Mail server, such as `smtp.gmail.com`. |
| `SMTP_PORT` | SMTP port; default 465 with implicit TLS, or 587 with STARTTLS. |
| `SMTP_USERNAME` | Account used to authenticate to SMTP. |
| `SMTP_PASSWORD` | SMTP credential accepted by the account/provider. |
| `EMAIL_FROM` | Sender address. |
| `EMAIL_TO` | Recipient address; a single recipient is supported. |

The same Gmail account can be the sender and recipient. Gmail setup generally requires two-step verification and an app password when that account permits app passwords; see [Google's app-password instructions](https://support.google.com/accounts/answer/185833) and [Gmail mail-client settings](https://support.google.com/mail/answer/7126229). Use the app password locally as `SMTP_PASSWORD`. If the account does not support this authentication method, use an SMTP provider that does or add Gmail OAuth support; OAuth is not implemented here.

Do not paste credentials into source files, reports, or chat messages.

### Collect Onbid assets for review

Apply for the [official list service](https://www.data.go.kr/data/15157207/openapi.do) and add the issued key to `.env`. With the default configuration:

```sh
python3 -m building_monitor run --dry-run
```

The adapter queries both `pvctTrgtYn=N` and `Y`, requests sale transactions in Seoul, and excludes share interests at query time and again after normalization. It uses the documented endpoint:

```text
https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2
```

`data/latest.json` includes collected records and exclusion reasons. A list response does not establish that a commercial asset is an entire building, or provide the date/scope of its appraisal. Such properties remain excluded until reviewed.

For each appropriate asset, add one row to `reviews.csv`:

- `source`: `onbid`, or the configured feed name.
- `listing_id`: the exact source identifier; for Onbid, `cltrMngNo`.
- `property_id`: your stable property identifier, shared across suppliers only after identity is confirmed.
- `sale_scope`: `whole_property` only when the sale includes the entire land and building.
- `category`: `commercial` or `office`.
- `appraisal_krw`: the exact documented total appraisal in integer KRW.
- `appraisal_date`: `YYYY-MM-DD`, taken from the appraisal document.
- `appraisal_scope`: `whole_property` when it matches the property being sold.
- `appraisal_kind`: `formal`.
- `appraisal_verified`: `true` after the property, amount, date, and scope are confirmed.
- `appraisal_evidence_url`: an HTTPS link to the appraisal document or the specific source record containing it.

Review rows cannot override a conflicting property identifier or a different appraisal amount returned by the source. Changed source appraisal amounts require a new review. Review rows must include the documented appraisal amount to enable verification. A source's share, unit-price, or bundle flags remain disqualifying after review.

Onbid emails currently link to the portal and include the exact management number. A validated direct asset URL has not been implemented. An exact appraisal/source-record link should be supplied in the review.

### Connect regular sales

CSV imports use UTF-8, optionally with a BOM. JSON inputs use an array of records or an object containing a `listings` array. Prices must be integer KRW; convert values such as `30억` explicitly before import. Copy the CSV header template to a local input file, populate it, and add a feed to `config.json`:

```json
{
  "name": "broker-feed",
  "path": "inputs/general-sales.csv",
  "enabled": true
}
```

The feed entry belongs in the existing `feeds` array. Input paths are resolved relative to the configuration file. A broker's HTTPS JSON feed can instead use:

```json
{
  "name": "broker-feed",
  "url": "https://supplier.example/authorized-building-feed.json",
  "token_env": "BROKER_FEED_TOKEN",
  "enabled": true
}
```

A normalized regular-sale record uses:

```json
{
  "listing_id": "supplier-building-id",
  "title": "Commercial building",
  "address": "Verified property address",
  "city": "Seoul",
  "category": "commercial",
  "transaction": "sale",
  "status": "active",
  "price_krw": 3000000000,
  "price_kind": "asking_price",
  "source_url": "https://supplier.example/listings/supplier-building-id",
  "observed_at": "2026-11-03T09:00:00+09:00",
  "property_id": "verified-property-id",
  "sale_scope": "whole_property"
}
```

Use `office` for office buildings. Add the appraisal fields directly to a trusted normalized feed or enrich the record through `reviews.csv`. For a court-auction export, use `price_kind=minimum_bid`, provide `bid_end` and a stable `round_id`, and supply the same verified appraisal fields. No source observation timestamp is refreshed merely because a local file is read again.

## Start periodic monitoring

First review a preview and confirm that a real source was collected successfully:

```sh
python3 -m building_monitor run --dry-run
```

With credentials and reviewed input in place:

```sh
python3 -m building_monitor watch --interval 3600
```

This sends a digest immediately when a polling run finds new qualifying prices. Keep the process running on a host that stays awake, or deploy the one-shot `run` command on a persistent scheduler. Scheduling or a system service has not been installed.

The engine stores alert fingerprints in SQLite. An unchanged property/price/appraisal/bid round does not resend after restart. A different qualifying price, appraisal evidence/date, or bidding round can generate another email. A failed email is retried on the next run because its fingerprints are not marked as sent. A preview also does not mark alerts as sent. SMTP delivery and the local database cannot guarantee exactly-once delivery if the process stops between server acceptance and recording success.

Independent sources are collected separately: one failed source does not prevent alerts from healthy sources. A failed source, failed delivery, missing source configuration, or incomplete pagination produces a nonzero one-shot exit status. Credential-bearing URLs and provider exception text are not written to reports.

`data/health.json` reports source status, counts, delivery status, and unconnected coverage. `data/latest.json` records the most recent collected listings and exclusion reasons. These are the latest attempt, not a retained last-known-good inventory. Source failures do not automatically send an email; monitor the process exit status or health report with the deployment's monitoring system.

The Onbid request budget defaults to 900 calls per Korea calendar day, including retries. Published portal metadata lists 1,000 development-account calls; activity outside this process may consume the same allowance. The adapter caps pages per query and reports incomplete collection as an error instead of claiming full coverage. Increase page limits only within the available request budget. Review and detail-API activity can require its own allowance.

## Validation

```sh
python3 -m unittest discover -s tests -v
```

Tests cover exact threshold boundaries, property/appraisal identity conflicts, incompatible scopes, stale observations, stale and future appraisals, expired bids, Onbid JSON/XML envelopes, pagination, daily request budgets across restarts, SMTP TLS ordering, preview behavior, deduplication, price changes, independent source failures, and delivery retries.

Onbid requests and SMTP transport were tested with controlled responses. There has been no successful authenticated Onbid collection, production supplier-feed collection, or real email delivery. The demonstration records are synthetic and are not investment opportunities.
