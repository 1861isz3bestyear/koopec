use axum::{
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

#[tokio::test]
async fn health_and_capabilities_describe_only_available_features() {
    for (path, expected) in [
        ("/v1/health", "status"),
        ("/v1/capabilities", "api_version"),
    ] {
        let response = http_api::router()
            .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert!(value.get(expected).is_some());
        if path.ends_with("capabilities") {
            assert_eq!(value["backtests"], false);
            assert_eq!(value["trading"], false);
        } else {
            assert_eq!(value["dependencies"], "not_configured");
        }
    }
}

#[tokio::test]
async fn unknown_version_and_unimplemented_routes_return_safe_not_found() {
    for path in ["/v2/health", "/v1/datasets/open", "/v1/runs/123/summary"] {
        let response = http_api::router()
            .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        let body = to_bytes(response.into_body(), 4096).await.unwrap();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(value["code"], "not_found");
    }
}

#[tokio::test]
async fn health_is_read_only() {
    let response = http_api::router()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/v1/health")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
}
