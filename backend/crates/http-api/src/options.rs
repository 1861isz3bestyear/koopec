use crate::ErrorBody;
use axum::{Json, http::StatusCode};
use calculus::options::{
    IdentifiedContract, OptionContract, OptionKind, OptionSnapshot, Valuation, aggregate,
};
use serde::{Deserialize, Serialize};
use ts_rs::TS;

#[derive(Deserialize, TS)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExposureRequest {
    #[ts(type = "number")]
    observed_at: i64,
    #[ts(type = "number")]
    available_at: i64,
    #[ts(type = "number")]
    valued_at: i64,
    spot: f64,
    contracts: Vec<Contract>,
}
#[derive(Deserialize, TS)]
#[serde(deny_unknown_fields)]
struct Contract {
    id: String,
    kind: Kind,
    strike: f64,
    #[ts(type = "number")]
    expiry: i64,
    iv: f64,
    open_interest: f64,
    multiplier: f64,
}
#[derive(Deserialize, TS)]
#[serde(rename_all = "lowercase")]
enum Kind {
    Call,
    Put,
}
#[derive(Serialize, TS)]
pub(crate) struct ExposureResponse {
    signed: f64,
    absolute: f64,
    strikes: Vec<Strike>,
}
#[derive(Serialize, TS)]
struct Strike {
    strike: f64,
    call: f64,
    put: f64,
}

fn snapshot(request: ExposureRequest) -> Result<OptionSnapshot, calculus::options::OptionsError> {
    if request.contracts.len() > 10_000 {
        return Err(calculus::options::OptionsError::InvalidInput);
    }
    let contracts = request
        .contracts
        .into_iter()
        .map(|c| {
            let kind = match c.kind {
                Kind::Call => OptionKind::Call,
                Kind::Put => OptionKind::Put,
            };
            IdentifiedContract::new(
                c.id,
                OptionContract::new(
                    kind,
                    c.strike,
                    c.expiry,
                    c.iv,
                    c.open_interest,
                    c.multiplier,
                )?,
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    OptionSnapshot::new(
        request.observed_at,
        request.available_at,
        Valuation::new(request.spot, request.valued_at)?,
        contracts,
    )
}

pub(crate) async fn calculate(
    Json(request): Json<ExposureRequest>,
) -> Result<Json<ExposureResponse>, (StatusCode, Json<ErrorBody>)> {
    let summary = snapshot(request)
        .and_then(|snapshot| aggregate(&snapshot))
        .map_err(|_| {
            (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ErrorBody {
                    code: "invalid_options",
                    message: "The options input cannot be calculated.",
                }),
            )
        })?;
    Ok(Json(ExposureResponse {
        signed: summary.totals.signed,
        absolute: summary.totals.absolute,
        strikes: summary
            .strikes
            .into_iter()
            .map(|s| Strike {
                strike: s.strike,
                call: s.call,
                put: s.put,
            })
            .collect(),
    }))
}

/// Generate API type declarations from the Serde DTOs.
pub fn typescript() -> String {
    [
        Kind::decl(),
        Contract::decl(),
        ExposureRequest::decl(),
        Strike::decl(),
        ExposureResponse::decl(),
    ]
    .into_iter()
    .map(|declaration| format!("export {declaration}\n"))
    .collect()
}
