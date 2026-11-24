# Architecture and HTTP contract

```text
koopec/
  Cargo.toml               # Web workspace
  backend/
    Cargo.toml
    crates/
      calculus/
      archive/
      market-data/
      server-bot/
      api-server/          # Axum binary and HTTP boundary
  api-types/               # Shared JSON contracts
  api-client/              # Browser HTTP client
  frontend/                # Dioxus + Plychart
```

Keep the existing native Cargo workspace under `backend/`. Put the web
workspace manifest in the Koopec root and list `frontend`, `api-client`,
and `api-types` as members. Exclude the existing `backend` workspace and
the transitional `python` package from the web workspace. The backend
depends on `api-types` by path, without enrolling it in the native workspace.
Check actual membership with `cargo metadata` from each workspace and check
in their lockfiles. Run native checks for the backend and explicit checks
for the browser target and shared contracts. Revisit workspace consolidation
after cutover if it simplifies the build.

| Package         | Responsibility                                  |
| --------------- | ----------------------------------------------- |
| `api-types`     | Shared JSON contracts and structured errors     |
| `api-client`    | Browser HTTP requests and typed responses       |
| `frontend`      | Dioxus screens, UI state, and Plychart          |
| `api-server`    | Axum routing, validation, and dependency wiring |
| Existing crates | Storage, calculations, exchange and order state |

The shared contracts define units, UTC timestamps, optional fields and enums.
The client encodes path and query values and exposes request errors. The server
resolves archive IDs and maps failures to HTTP status codes.

Keep calculation logic deterministic. Exchange transport owns timeouts and
retries. The application layer owns workflow orchestration, clock injection,
and synchronization with persistence. Introduce a native replay crate only
if plan assembly and simulation need their own dependency boundary. Execute
synchronous SQLite reads and expensive calculations off async workers and
bound concurrent historical scans and replay jobs.

## First endpoints

All three endpoints use GET.

- `/api/archives` returns configured archive IDs, display names and coverage.
- `/api/archives/{id}/gex/history` returns chronological rows from complete
  collections and the archive version.
- `/api/archives/{id}/gex/profile` takes a UTC timestamp in the `cutoff` query
  parameter. It returns the profile and actual receipt, or an explicit empty
  result.

A malformed cutoff returns 400 and an unknown archive ID returns 404. An
exact cutoff includes the receipt at that instant. An earlier cutoff with
no eligible complete receipt gives a successful empty result. Define
version mismatch behavior before the UI combines independently fetched
history and profile data. A version-aware request can return 409 and ask
the client to refresh if the archive changed. Represent unavailable
analytics explicitly and keep floating-point values JSON-compatible.

Axum serves the compiled Dioxus assets and API from one origin in the
local release. Bind the local launcher to loopback. Resolve archive IDs
against server configuration. Define authentication and archive access
before providing a remotely hosted or shared deployment. Exchange
credentials and filesystem access belong to the server.

## Dioxus and Plychart

Compile Dioxus and the Plychart Rust dependency for
`wasm32-unknown-unknown`. Pin versions after the first browser spike.
Mount a stable canvas, resize it with its container, wire browser events,
and release chart and viewport state on unmount. Keep the API data and
selected receipt in Dioxus. The chart adapter maps the viewport and pointer
coordinates back to receipt IDs. Test the mapping against actual plotted
data and browser scaling. Plychart's generic index helper alone gives no
guarantee of correct receipt selection after zoom or with irregular
timestamps.

Use the existing oscillator renderer during transition. Finish the
migration by replacing its feature logic with Rust/WASM, through Plychart
and Koopec-owned Rust drawing or interaction code where needed. Preserve
accessible HTML controls and data summaries around the Canvas.
