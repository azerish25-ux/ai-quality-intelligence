# Bounded operational telemetry

Manual OpenTelemetry spans cover HTTP, durable jobs, ingestion, validation,
redaction, parsing, clustering, history, analysis, evidence, persistence, GitHub
publication and optional provider calls. A validated W3C traceparent links queued
API requests to workers; baggage and tracestate are not persisted. Stage timings
are inclusive and may overlap. Export sampling follows the SDK sampler settings;
process-local counters count every completed call, not unique analyses.
The HTTP span ends when the handler produces the response; it does not measure
subsequent streamed-body transfer. Client benchmark latencies remain separate.

Export is disabled by default. Generic OTLP environment variables cannot enable it.
To use an operator-controlled collector, explicitly set
`FAILURELENS_TELEMETRY_EXPORT_ENABLED=true` and
`FAILURELENS_TELEMETRY_ENDPOINT=https://collector.example.invalid/v1/traces`
(replace the illustrative host). HTTP is allowed only for loopback or the local
`otel-collector` hostname. Endpoints cannot contain credentials, queries or fragments.
No collector credentials are inferred or supported by this boundary.

The bounded OTLP/protobuf transport uses explicit headers, no ambient proxy/auth,
no redirects or retries, a two-second total export deadline, a 1 MB payload cap and a
64 KiB response cap. A 256-span queue exports batches of at most 64. Collector
outages can drop traces; they do not change analysis results. Generic exporter
headers, resource attributes and credential providers are not inherited. This
is intentional: SDK exporter header arguments alone merge environment headers.
An export that exceeds its total deadline disables that exporter until app/process
restart; at most one transport task can remain in flight. This fail-closed behavior
prevents a trickling or stalled collector from accumulating requests. Ordinary
bounded connection/HTTP failures may recover on later batches. App shutdown drains
with one shared deadline; worker SIGTERM finishes its current job before draining.

Spans contain fixed stage names and approved enum/numeric fields, route templates,
and random trace/span IDs. No artifact bodies, claims, prompts, test names, model
names, resource IDs, user identifiers, exception text/events or links are emitted.
Structured package logs contain redacted messages and valid trace IDs; unknown
extras and stack/exception text are omitted. Redaction is defense in depth, not
proof that arbitrary sensitive strings can safely be logged.

System administrators can GET `/api/v1/operations/telemetry` for current-process
stage durations/counts, exception counts, category/provider-call outcomes, HTTP
status classes (including unhandled 500s), evidence accepted/rejected record counts,
validation degradation, provider cost status, redaction operation/class counts,
recovered worker leases and database queue-state counts/oldest queued age. No project or
user IDs are returned. API and worker counters are separate and reset on restart;
this endpoint is not a persistent audit log or cross-process metrics aggregator.

Verification includes an actual loopback HTTP receiver decoding OTLP protobuf,
API-to-persisted-job trace continuity, secret/baggage canaries, strict admin access,
redirect/error/response-bound tests, and disabled-export tests. No real external
collector or paid provider was invoked. The local Docker integration has its own
execution gate below; source and unit checks alone do not establish a Docker pass.
Reference: [OTel manual instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/).

## Optional local collector and viewer

The explicit overlay/profile enables API and worker export to the local Jaeger
2.21.0 OpenTelemetry Collector distribution. It adds no remote exporter, hosted
account, credential, browser telemetry or AI-agent connection:

```sh
docker compose -f compose.yaml -f compose.telemetry.yaml --profile telemetry up --build
```

Open `http://localhost:16686`, choose service `loose-thread`, upload a supported
report and inspect the request/worker trace. The viewer is loopback-only and has
no login; do not expose it publicly. It contains operational timing metadata,
even though artifact content and identifiers are excluded. Only fixed-route,
GET/HEAD viewer traffic crosses the edge gateway. OTLP ingestion is internal-only;
API, worker, database and collector retain the isolated runtime network.

Storage is memory-only, bounded to 1,000 traces, and disappears when the collector
restarts. A 256 MiB container limit, 160 MiB memory-limiter target, 1 MiB receiver
body cap and batches of at most 64 bound the profile. Overload/outage can drop
traces; this is a development viewer, not a persistent audit system. Disable it by
stopping this profile and restarting the default `docker compose up --build` stack.

`scripts/compose_telemetry_smoke.sh --confirm-disposable-stack` creates its own
disposable Compose project, executes a real PostgreSQL-backed upload/worker,
queries the collected parent trace, checks required stages and secret/baggage
canaries, verifies viewer ingress, retains runtime Internet denial and checks core
readiness after stopping the collector. The dedicated `telemetry.yml` job retains
actual results and failures. Docker is unavailable in the development cloud shell;
actual execution is pending exact-source CI until recorded in the delivery ledger.

Configuration references checked 2026-09-30:
[Jaeger v2 architecture](https://www.jaegertracing.io/docs/2.21/architecture/),
[deployment](https://www.jaegertracing.io/docs/2.21/deployment/), and
[versioned collector configuration](https://github.com/jaegertracing/jaeger/blob/v2.21.0/cmd/jaeger/config.yaml).
