//! Initial read-only API surface; datasets and backtests are not yet available.
use axum::{Json, Router, http::StatusCode, routing::get};
use serde::Serialize;

#[derive(Serialize)]
struct Health {
    status: &'static str,
    dependencies: &'static str,
}
#[derive(Serialize)]
struct Capabilities {
    api_version: &'static str,
    endpoints: [&'static str; 2],
    backtests: bool,
    trading: bool,
}
#[derive(Serialize)]
struct ErrorBody {
    code: &'static str,
    message: &'static str,
}

async fn health() -> Json<Health> {
    Json(Health {
        status: "ok",
        dependencies: "not_configured",
    })
}
async fn capabilities() -> Json<Capabilities> {
    Json(Capabilities {
        api_version: "v1",
        endpoints: ["health", "capabilities"],
        backtests: false,
        trading: false,
    })
}
async fn not_found() -> (StatusCode, Json<ErrorBody>) {
    (
        StatusCode::NOT_FOUND,
        Json(ErrorBody {
            code: "not_found",
            message: "The requested endpoint is unavailable.",
        }),
    )
}
/// Build a read-only router without network or database side effects.
pub fn router() -> Router {
    Router::new()
        .route("/v1/health", get(health))
        .route("/v1/capabilities", get(capabilities))
        .fallback(not_found)
}
