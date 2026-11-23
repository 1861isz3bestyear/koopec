mod support;

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

#[tokio::test]
async fn exposure_reports_ranked_walls_and_max_pain_for_live_contracts() {
    let body = serde_json::json!({"observed_at":0,"available_at":0,"valued_at":0,"spot":100.0,"contracts":[
        {"id":"call","kind":"call","strike":100.0,"expiry":31536000,"iv":0.5,"open_interest":10.0,"multiplier":2.0},
        {"id":"put","kind":"put","strike":110.0,"expiry":31536000,"iv":0.5,"open_interest":10.0,"multiplier":2.0},
        {"id":"far","kind":"call","strike":130.0,"expiry":31536000,"iv":0.5,"open_interest":100.0,"multiplier":2.0},
        {"id":"expired","kind":"call","strike":90.0,"expiry":0,"iv":0.5,"open_interest":100.0,"multiplier":1.0}
    ]});
    let response = http_api::router()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/v1/options/exposure")
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = to_bytes(response.into_body(), 4096).await.unwrap();
    let result: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(result["walls"]["calls"].as_array().unwrap().len(), 1);
    assert_eq!(result["walls"]["calls"][0]["strike"], 100.0);
    assert_eq!(result["walls"]["puts"][0]["strike"], 110.0);
    // Python options_model.py SHA-256 53081b2514c9ff192be1c0da7f233a219ac7e51dde1e838283e895f539ce9ffe; zero rates.
    assert!(
        (result["walls"]["calls"][0]["call"].as_f64().unwrap() - 15.466724672113974).abs() < 1e-10
    );
    assert!(
        (result["walls"]["puts"][0]["put"].as_f64().unwrap() - -15.929583055879542).abs() < 1e-10
    );
    assert_eq!(
        result["max_pain"],
        serde_json::json!({"status":"strike","strike":100.0})
    );
}

#[tokio::test]
async fn max_pain_explains_empty_mixed_and_zero_interest() {
    let contract = serde_json::json!({"id":"call","kind":"call","strike":100.0,"expiry":10,"iv":0.5,"open_interest":0.0,"multiplier":1.0});
    let mut other = contract.clone();
    other["id"] = "put".into();
    other["expiry"] = 20.into();
    other["open_interest"] = 1.into();
    let mut expired = contract.clone();
    expired["expiry"] = 0.into();
    for (contracts, status) in [
        (vec![], "empty"),
        (vec![expired], "empty"),
        (vec![contract.clone()], "zero_open_interest"),
        (vec![contract, other], "mixed_expiry"),
    ] {
        let body = serde_json::json!({"observed_at":0,"available_at":0,"valued_at":0,"spot":100.0,"contracts":contracts});
        let response = http_api::router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/v1/options/exposure")
                    .header("content-type", "application/json")
                    .body(Body::from(body.to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let bytes = to_bytes(response.into_body(), 4096).await.unwrap();
        let result: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(result["max_pain"]["status"], status);
    }
}

#[tokio::test]
async fn local_archive_lists_all_collections_and_loads_selected_chain() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("archive.sqlite");
    support::create_archive(&path);
    for (query, expected, spot) in [("", "newer", 200.0), ("?collection=older", "older", 100.0)] {
        let response = http_api::router_with_archive(path.clone())
            .oneshot(
                Request::builder()
                    .uri(format!("/v1/archive{query}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), 100_000).await.unwrap();
        let value: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(value["collections"].as_array().unwrap().len(), 2);
        assert_eq!(value["selected"], expected);
        assert_eq!(value["snapshot"]["spot"], spot);
        assert_eq!(value["snapshot"]["contracts"][0]["open_interest"], 10.0);
        assert_eq!(value["snapshot"]["contracts"][0]["iv"], 0.5);
        // The synthetic archive stores 20 underlying units at multiplier 2.
        let expected_time = if expected == "newer" {
            1_794_225_902
        } else {
            1_794_225_602
        };
        assert_eq!(value["snapshot"]["available_at"], expected_time);
        assert_eq!(
            value["snapshot"]["contracts"][0]["expiry"],
            1_795_003_200_i64
        );
        let response = http_api::router()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/v1/options/exposure")
                    .header("content-type", "application/json")
                    .body(Body::from(value["snapshot"].to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
    }
    let response = http_api::router_with_archive(path)
        .oneshot(
            Request::builder()
                .uri("/v1/archive?collection=missing")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn missing_archive_is_reported_without_creating_a_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("missing.sqlite");
    let response = http_api::router_with_archive(path.clone())
        .oneshot(
            Request::builder()
                .uri("/v1/archive")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert!(!path.exists());
}

#[tokio::test]
async fn local_archive_accepts_an_explicit_path_and_recovers_from_invalid_paths() {
    let dir = tempfile::tempdir().unwrap();
    let missing = dir.path().join("missing.sqlite");
    let fixture = dir.path().join("fixture.sqlite");
    support::create_archive(&fixture);
    let supplied = dir.path().join("archive with spaces.sqlite");
    std::fs::copy(&fixture, &supplied).unwrap();
    let encoded = supplied.display().to_string().replace(' ', "%20");
    let uri = format!("/v1/archive?path={encoded}");
    let response = http_api::router_with_archive(missing.clone())
        .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let response = http_api::router_with_archive(fixture)
        .oneshot(
            Request::builder()
                .uri(format!("/v1/archive?path={}", missing.display()))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert!(!missing.exists());
}
