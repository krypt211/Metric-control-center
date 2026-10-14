# Meta database cleanup

Status: COMPLETED FOR THE EXPLICITLY APPROVED SCOPE.
User separately approved exactly 4256 Meta-only rows.
Production cleanup result: 4256 removed; retained-row hashes identical,
foreign keys validated. Meta LIVE 0; advertising WRITE 0.

## Backup and rehearsal
Backup: E:\Creative_Factory\metric-control-center\backups\audit-20261013T204840Z\database.dump
SHA256: 4efd623103cdf4152054b6b11c681e8949f3f8d8dc3905f14d9e9273864e2b78
Size: 6839410 bytes.
Protected archive: E:\Creative_Factory\metric-control-center\backups\audit-20261013T204840Z (owner + SYSTEM ACL).
Restored database: mcc_integrations_audit_20261013_204840.
A PostgreSQL exported REPEATABLE READ snapshot synchronized pg_dump and
all-table checksum inventory. All 70 restored table counts/digests matched.
See [PostgreSQL snapshot documentation](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION).
No working volume was removed; backup and isolated DB retained.

## Deletion boundary
Selection used provider='meta' plus dependency checks, never an external account ID alone.
Frozen candidate row sets were deleted in one transaction with table locks.
All retained rows in every table were compared before commit. MetricFlow rows,
economics, rules, user preferences, credentials and advertising-action history
were preserved. Meta config was reduced while preserving disconnected revision 4.
The obsolete PREPARED session was archived in the verified backup and removed.

Five Meta account rows remain: one participates in another provider's canonical
identity; four have references in retained evaluations/preferences. Their dependent
catalog/fact rows remain rather than silently changing object identity. Historic
Meta sync_runs/raw data and ambiguous/shared switch events are retained; they were
not included in the separately approved 4256-row scope. No additional deletion
is implied by this report.

| Table | Before | Deleted | After |
|---|---:|---:|---:|
| meta_pilot_sessions | 1 | 1 | 0 |
| meta_request_queue | 0 | 0 | 0 |
| meta_request_attempts | 0 | 0 | 0 |
| meta_operations | 0 | 0 | 0 |
| meta_rate_states | 0 | 0 | 0 |
| provider_job_audit | 0 | 0 | 0 |
| provider_jobs | 13 | 1 | 12 |
| provider_catalog | 1336 | 1291 | 45 |
| provider_windows | 51 | 2 | 49 |
| read_statistics | 1040 | 0 | 1040 |
| daily_metrics | 538 | 5 | 533 |
| hourly_metrics | 0 | 0 | 0 |
| tracker_metrics | 0 | 0 | 0 |
| breakdowns | 0 | 0 | 0 |
| entity_current_state | 710 | 364 | 346 |
| ads | 314 | 163 | 151 |
| adsets | 284 | 148 | 136 |
| campaigns | 112 | 53 | 59 |
| creatives | 958 | 927 | 31 |
| provider_account_mappings | 12 | 3 | 9 |
| entities | 1668 | 1291 | 377 |
| ad_accounts | 12 | 3 | 9 |
| api_quotas | 9 | 1 | 8 |
| provider_switch_events | 30 | 3 | 27 |

No schema DROP/TRUNCATE/CASCADE. The production transaction verified no enabled Meta connection, no credential, no active job and zero pilot attempts before deletion.

Deployment verification also matched all 20 protected table digests, unchanged
.env and credentials. All 70 tables remain; no working migration or volume deletion.
