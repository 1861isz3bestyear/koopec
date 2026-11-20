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

#[tokio::test]
async fn options_exposure_uses_validated_calculus_and_rejects_duplicate_identity() {
    let body = serde_json::json!({"observed_at":0,"available_at":0,"valued_at":0,"spot":100.0,"contracts":[{"id":"call","kind":"call","strike":100.0,"expiry":31536000,"iv":0.5,"open_interest":10.0,"multiplier":2.0},{"id":"put","kind":"put","strike":100.0,"expiry":31536000,"iv":0.5,"open_interest":10.0,"multiplier":2.0}]});
    let request = |value: &serde_json::Value| {
        Request::builder()
            .method("POST")
            .uri("/v1/options/exposure")
            .header("content-type", "application/json")
            .body(Body::from(value.to_string()))
            .unwrap()
    };
    let response = http_api::router().oneshot(request(&body)).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), 4096).await.unwrap();
    let result: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(result["signed"], 0.0);
    assert!((result["absolute"].as_f64().unwrap() - 30.933449344227946).abs() < 1e-12);
    let mut duplicate = body.clone();
    duplicate["contracts"][1]["id"] = "call".into();
    let response = http_api::router()
        .oneshot(request(&duplicate))
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let bytes = to_bytes(response.into_body(), 4096).await.unwrap();
    let error: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(error["code"], "invalid_options");
}

#[tokio::test]
async fn options_exposure_distinguishes_zero_expiry_and_invalid_requests() {
    let send = |body: serde_json::Value| async move {
        http_api::router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/v1/options/exposure")
                    .header("content-type", "application/json")
                    .body(Body::from(body.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap()
    };
    let mut input = serde_json::json!({"observed_at":0,"available_at":0,"valued_at":10,"spot":100.0,"contracts":[{"id":"x","kind":"call","strike":100.0,"expiry":10,"iv":0.5,"open_interest":0.0,"multiplier":1.0}]});
    let response = send(input.clone()).await;
    assert_eq!(response.status(), StatusCode::OK);
    let data: serde_json::Value =
        serde_json::from_slice(&to_bytes(response.into_body(), 4096).await.unwrap()).unwrap();
    assert_eq!(data["signed"], 0.0);
    assert_eq!(data["strikes"].as_array().unwrap().len(), 0);
    input["available_at"] = 11.into();
    assert_eq!(
        send(input.clone()).await.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    input["available_at"] = 0.into();
    input["contracts"][0]["iv"] = 0.into();
    assert_eq!(
        send(input.clone()).await.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    input["contracts"][0]["kind"] = "invalid".into();
    assert_eq!(send(input).await.status(), StatusCode::UNPROCESSABLE_ENTITY);
}
