# Gas Photo receiver 0.1.0

Standalone YAML custom integration targeting **Home Assistant Core 2026.7.2**. Copy this entire `gas_photo` directory to `/config/custom_components/gas_photo`. Back up HA first. Add:

```yaml
gas_photo:
  max_m3_per_hour: 6
```

Restart HA, check logs, and use a separate test installation first. The default 6 m³/h is a conservative example: configure your meter's physical maximum. Validation compares both temporal neighbors, permits equal readings, and adds one litre rounding tolerance. This is not proof of OCR accuracy.

## Actions and REST

An administrator token can call `POST /api/services/gas_photo/import_readings?return_response` with:

```json
{"readings":[{"id":"1111111111111111111111111111111111111111111111111111111111111111","meter_id":"gas_main","captured_at":"2026-01-01T12:43:42.865+01:00","value":"100.000","revision":1,"source":"manual_review","metadata":{}}]}
```

HA wraps the response in `service_response`. The inner result is `{"accepted":[{"id":"...","revision":1}],"statistics_status":"queued"}`. The status is `pending` if all readings are in the open hour or Recorder queueing failed. This confirms the exact ledger was saved, **not** that Recorder committed statistics. Maximum 100 records per call, metadata 16 KiB per record. Metadata must be JSON-safe. Timestamps must have offsets and cannot be future; values support five integer and three fractional digits.

`POST /api/services/gas_photo/get_readings?return_response` with `{"ids":["..."]}` verifies up to 100 requested IDs. Alternatively use `{"offset":0,"limit":500,"start":"2026-01-01T00:00:00+00:00","end":"2026-02-01T00:00:00+00:00"}`; end is exclusive. Response `{"readings":[...]}` preserves original timestamp spelling and fractional seconds. Read-only authenticated websocket command `gas_photo/get_readings` takes the same fields. The `ids` filter takes precedence over pagination/time filters.

## Exact history card

Add a dashboard JavaScript module resource `/gas_photo/gas-photo-card.js` (Settings → Dashboards → Resources, advanced mode), then a manual card:

```yaml
type: custom:gas-photo-card
title: Pontos gázóra-leolvasások
```

The integration serves this module itself, without a build step or external CDN. It contains no credentials or ledger. Data uses the HA authenticated websocket. The table shows exact original timestamps with offsets, values and within-page differences; pagination shows 50 readings. Refresh explicitly after imports. The first row on a page has no difference because its predecessor is on the previous page.

Two latest-observation sensors are discovered automatically. Neither has `state_class`, so Recorder does not create another consumption sum. They show the chronologically latest reading and photo timestamp; their normal HA history is import-time state history. Exact photo history lives in the separate card.

## Statistics semantics and correction limits

Only **`gas_photo:gas_main`** is written, with `mean_type: 0`, `has_sum: true`, `unit_class: volume` and `m³`. No legacy sources or Energy settings are touched. Do not enable overlapping old and new sources together in Energy.

The first exact observation is the consumption origin (sum zero). Each closed UTC hour containing observations uses that hour's latest reading and sum = reading − origin. If two observations occur in the first hour, the hourly sum can already include the difference from the first exact observation. Empty hours are not invented; change is attributed to the later observation hour. Current-hour readings remain in the exact ledger and publish after the hour closes.

The baseline and capture times of publication-eligible records lock before the first Recorder queue attempt. This is deliberately conservative because a queued write may have committed even when a response is lost. Higher revisions can correct non-baseline values if all neighbors remain plausible. They retain previous revisions in Store audit history and regenerate observed buckets. A published capture timestamp, baseline value/time, or insertion before the published baseline is rejected and requires a separately reviewed migration. This prevents obsolete buckets or changing the consumption origin. Import initial historical records together in chronological batches starting at the earliest intended baseline.

Exact records and the pending flag are saved to `.storage/gas_photo.ledger` before queueing. Pending remains true because enqueue is not commit confirmation. All closed buckets are idempotently resubmitted at startup and hourly at `:00:05`, including after Recorder failures. Preserve this Store file together with the Recorder backup: deleting it alone loses the origin and correction locks. Never rebuild an empty ledger against an existing nonempty `gas_photo:gas_main` series.

For acceptance, read back exact IDs using `get_readings`, then independently inspect Recorder hourly statistics for `gas_photo:gas_main` after queue processing. Verify UTC start, state, sum and metadata, including a known 100 → 110 example (sum 0 → 10). A queued response alone does not satisfy this check.

## Verification and rollback

The pure ledger has local tests for duplicate retries, revision conflicts, audit, exact timestamps, out-of-order readings, hourly grouping, baseline protection, future/invalid values and consumption bounds. Python compilation checks the integration. The pinned HA Core 2026.7.2 runtime was exercised in an isolated temporary configuration: integration setup, service registration, sensor creation, exact readback and a Recorder roundtrip were verified. Run the same checks in a separate test installation before production use.

To disable: remove `gas_photo:` from configuration, remove its card/resource, restart HA. Keep `.storage/gas_photo.ledger` and Recorder backups. Existing legacy Energy data was never modified; removing the component does not erase the new statistic. Any statistics deletion or production Energy migration is a separate explicit operation.

### Recorder readback action

Call `POST /api/services/gas_photo/get_statistics?return_response` with offset-bearing `start` and `end` (maximum 31-day range). It returns `statistic_id`, actual Recorder `statistics` rows, and `expected` rows derived from the ledger. Recorder timestamps retain the HA API representation; expected starts are ISO UTC. This reads actual Recorder data using its executor and never treats queue acceptance as verification. Compare state/sum/start after the queue drains; missing actual rows or discrepancies mean verification is incomplete. The action was exercised against the isolated runtime; repeat it in the target HA instance before enabling overlapping Energy sources.
