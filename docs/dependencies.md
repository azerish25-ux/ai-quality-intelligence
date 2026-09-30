# Reproducible Python dependencies

`backend/uv.lock` is the resolver source of truth, generated with uv 0.12.19 against
PyPI. `backend/requirements.lock` is its hash-checked pip export including development
dependencies for the existing CI/install workflow. They describe one resolved graph,
not independently maintained version lists. Frontend continues to use npm and its
committed package-lock.

Update deliberately:

```sh
uv lock --project backend
uv export --project backend --extra dev --no-emit-project --no-header --format requirements-txt -o backend/requirements.lock
```

`make bootstrap` and the clean committed-source backend CI installer consume the
hash-checked export. The installer still builds a Git archive outside the measured
checkout and rejects source dirtiness; no integrity exemption was introduced.
Historical build fixtures without a lock retain their explicit offline no-dependency
installation path. Runtime image and producer-specific workflow migration to this
lock must be verified separately; pinned producer pytest remains its own declared
fixture version rather than silently relabeled as the general test dependency.

The exported graph installed successfully in the local test environment. Dependency
versions alone are not a vulnerability audit or supported-platform certification.

The backend image consumes `backend/requirements-runtime.lock`, exported from the
same uv graph without the development extra. Regenerate it alongside the dev export:

```sh
uv export --project backend --no-emit-project --no-header --format requirements-txt -o backend/requirements-runtime.lock
```

The gateway uses the vendor's unprivileged Nginx image, with both listening ports
above 1024. The actual Docker smoke test checks nonzero UIDs for API, worker and
gateway rather than inferring non-root execution from Dockerfile text alone.
Vendor reference: https://github.com/nginx/docker-nginx-unprivileged


## Tool isolation and image identity

Quality tools have their own `tools/quality/uv.lock` and hash-checked export; they
are not runtime dependencies. See [gate scopes and current failures](quality-security.md).
Container base/service images are pinned by both human-readable tag and exact OCI
manifest digest. Python, Node, Nginx and PostgreSQL digests were checked against
actual Docker CI pull output and vendor Docker Hub metadata; Jaeger 2.21.0's digest
was checked against its vendor metadata. Digest identity prevents mutable-tag
surprises, but does not imply a vulnerability scan, a supported-lifetime guarantee
or automatic patching. Update deliberately and re-run actual container checks.

The frontend pins Vitest 4.1.11 within its existing major version. This addresses
[the UI/API advisory](https://github.com/advisories/GHSA-5xrq-8626-4rwp) and
[the mocker traversal advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9).
The local 48-test, TypeScript/build and earlier independent post-update npm audit
passed. The dedicated metadata audit requires separate authorization before any
new registry transmission; an unrun gate is never treated as a clean audit.
