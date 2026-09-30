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
