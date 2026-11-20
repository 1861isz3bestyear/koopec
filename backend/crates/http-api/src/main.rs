//! Local HTTP entry point for the API.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:8000").await?;
    axum::serve(listener, http_api::router()).await?;
    Ok(())
}
