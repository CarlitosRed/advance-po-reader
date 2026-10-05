# All products catalog pool

October 5 T-017 note: the current backend head is `0009_review_answers`;
the `0008` migration instructions below describe this pool change's original
checkpoint. The [free synthetic POC](poc-demo-runbook.md) uses an owned fresh
database and explicit vendor scope. It does not add synthetic namespaces to
a pool or migrate the existing live-demo database.

This change adds a persisted, tenant-local pool boundary over existing catalog
namespaces. It does not copy or combine product rows. A pool member remains an
original `catalog_namespace`; each product keeps its original ID, vendor, raw
source fields, attributes, detail sections and import provenance. Equal SKUs in
different members remain separate candidates and can produce an ambiguous
result.

New uploads without a vendor selector use the tenant's configured default pool.
The source and run save that pool ID. Later changes to the tenant's default do
not change an existing run's allowed catalog. Legacy uploads with an explicit
`vendor_id` continue to use that one vendor and have no pool ID. Product search,
product details, retrieval, manual proposals, review approval and agent reads
are tenant scoped and check pool membership when a run has a pool. Synthetic
namespaces cannot be added to a pool.

## Migration

Revision `0008_catalog_pools` follows
`0006_catalog_description_hint` directly. There is no `0007` revision in this
branch. The migration creates `catalog_pools` and immutable
`catalog_pool_members`, adds nullable pool IDs to sources/runs, replaces the
source hash uniqueness rule with separate pool and legacy scopes, and updates
the database review-candidate guard. Existing runs keep a null pool ID and
their historical vendor meaning. Existing suggestions and review events are
not rewritten.

Before applying this on another database, make a verified database backup and
confirm that `PO_BACKEND_DATABASE_URL` resolves to the intended tenant's local
database. In the demo checkout, with that database selected through its
existing ignored environment:

```powershell
.\.venv-backend\Scripts\python.exe -m alembic -c backend.alembic.ini upgrade head
.\.venv-backend\Scripts\python.exe -m alembic -c backend.alembic.ini current
```

The expected head is `0008_catalog_pools`. This branch was tested with a fresh
synthetic database; it did not migrate the live/demo database.

## Configure the tenant pool

The list command prints only non-synthetic namespaces belonging to the
provided tenant. Review that output and pass only the namespace IDs authorized
for that tenant. No vendor IDs or product fields are hardcoded into this
command:

```powershell
$authorizedTenant = 'TENANT-UUID-FROM-YOUR-LOCAL-ADMIN-RECORD'
.\.venv-backend\Scripts\python.exe -m backend.configure_catalog_pool `
  --tenant-id $authorizedTenant --list
```

After checking the names/source revisions against the authorization record,
create the pool from the chosen IDs:

```powershell
.\.venv-backend\Scripts\python.exe -m backend.configure_catalog_pool `
  --tenant-id $authorizedTenant `
  --name 'All products' `
  --namespace-id 'AUTHORIZED-NAMESPACE-UUID-1' `
  --namespace-id 'AUTHORIZED-NAMESPACE-UUID-2' `
  --namespace-id 'AUTHORIZED-NAMESPACE-UUID-3' `
  --default
```

The command is idempotent if the named pool has exactly the same members. A
different membership under the same pool name is rejected; create a separately
named/versioned pool instead. `--default` selects it for new uploads for that
tenant. There can be only one default pool per tenant. The command reports the
pool UUID and active product count after commit; check `/website/workspaces`
and `/website/corpus` for the configured default and count before using the
website.

## Compatibility and rollback

The application remains dual-path: an upload with `vendor_id` stays in that
legacy vendor catalog; an upload without one requires a default pool and saves
its pool ID on the source/run. If no default exists, the API returns
`default_catalog_pool_setup_required` and does not store the upload.

This evidence migration deliberately rejects Alembic downgrade because it
would remove membership/run-boundary history. To revert an activation, select a
verified pre-migration backup in a separate replacement database and switch
configuration only after confirming the restore; do not delete pool history
or rewrite old runs/suggestions in place. A compatible forward-only app can
stop using the default pool for newly selected vendor workflows while leaving
already pool-bound sources/runs unchanged.

## Verification

Synthetic tests cover exact, normalized, numeric description-hint and fuzzy
lookup within a pool; same-SKU ambiguity and candidate bounds; excluded and
cross-tenant records; original namespace/vendor provenance; pool counts/search
and detail reads; upload without a vendor selector; explicit legacy vendor
uploads; no-default setup responses; idempotent membership; and proposal and
approval guards. Agent search uses the same tenant-bound pool endpoint as the
website. All review decisions remain explicit human events.
