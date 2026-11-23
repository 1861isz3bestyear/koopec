mod local_archive;
pub mod options;
// Initial API surface; datasets and backtests are not yet available.
use axum::{
    Json, Router,
    extract::{Query, State},
    http::StatusCode,
    routing::get,
};
use serde::Serialize;
use std::path::PathBuf;

#[derive(Serialize)]
struct Health {
    status: &'static str,
    dependencies: &'static str,
}
#[derive(Serialize)]
struct Capabilities {
    api_version: &'static str,
    endpoints: [&'static str; 4],
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
        endpoints: [
            "health",
            "capabilities",
            "options_exposure",
            "local_gex_archive",
        ],
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
    let path = std::env::var_os("GUI_CALCULATOR_ARCHIVE").map_or_else(
        || {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../../gex_downloads/tunnel_inputs.sqlite")
        },
        PathBuf::from,
    );
    router_with_archive(path)
}

/// Build a router with an explicit local archive path.
pub fn router_with_archive(path: PathBuf) -> Router {
    Router::new()
        .route("/v1/health", get(health))
        .route("/v1/capabilities", get(capabilities))
        .route("/v1/archive", get(load_archive))
        .route(
            "/v1/options/exposure",
            axum::routing::post(options::calculate),
        )
        .fallback(not_found)
        .with_state(path)
}

async fn load_archive(
    State(path): State<PathBuf>,
    Query(selection): Query<local_archive::Selection>,
) -> Result<Json<local_archive::LoadedArchive>, (StatusCode, Json<ErrorBody>)> {
    let path = selection
        .path
        .filter(|value| !value.trim().is_empty())
        .map_or(path, PathBuf::from);
    let result = tokio::task::spawn_blocking(move || {
        local_archive::load(&path, selection.collection.as_deref())
    })
    .await;
    match result {
        Ok(Ok(archive)) => Ok(Json(archive)),
        _ => Err((
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(ErrorBody {
                code: "invalid_archive",
                message: "Cannot load local GEX archive. Check its path and data.",
            }),
        )),
    }
}
