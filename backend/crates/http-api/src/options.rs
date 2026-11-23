use crate::ErrorBody;
use axum::{Json, http::StatusCode};
use calculus::options::{
    IdentifiedContract, MaxPain, OptionContract, OptionKind, OptionSnapshot, Valuation, aggregate,
    max_pain, ranked_walls,
};
use serde::{Deserialize, Serialize};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ExposureRequest {
    pub(crate) observed_at: i64,
    pub(crate) available_at: i64,
    pub(crate) valued_at: i64,
    pub(crate) spot: f64,
    pub(crate) contracts: Vec<Contract>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Contract {
    pub(crate) id: String,
    pub(crate) kind: Kind,
    pub(crate) strike: f64,
    pub(crate) expiry: i64,
    pub(crate) iv: f64,
    pub(crate) open_interest: f64,
    pub(crate) multiplier: f64,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Kind {
    Call,
    Put,
}
#[derive(Serialize)]
pub(crate) struct ExposureResponse {
    signed: f64,
    absolute: f64,
    strikes: Vec<Strike>,
    walls: Walls,
    max_pain: Pain,
}
#[derive(Serialize)]
struct Walls {
    calls: Vec<Strike>,
    puts: Vec<Strike>,
}
#[derive(Serialize)]
#[serde(tag = "status", content = "strike", rename_all = "snake_case")]
enum Pain {
    Strike(f64),
    Empty,
    MixedExpiry,
    ZeroOpenInterest,
}

#[derive(Serialize)]
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
    let spot = request.spot;
    let valuation = Valuation::new(spot, request.valued_at).map_err(invalid_options)?;
    let snapshot = snapshot(request)
        .and_then(|snapshot| snapshot.revalue(valuation))
        .map_err(invalid_options)?;
    let summary = aggregate(&snapshot).map_err(invalid_options)?;
    let ranked = ranked_walls(&summary, spot, Some(0.2)).map_err(invalid_options)?;
    let max_pain = match max_pain(&snapshot).map_err(invalid_options)? {
        MaxPain::Strike(strike) => Pain::Strike(strike),
        MaxPain::Empty => Pain::Empty,
        MaxPain::MixedExpiry => Pain::MixedExpiry,
        MaxPain::ZeroOpenInterest => Pain::ZeroOpenInterest,
    };
    let convert = |s: calculus::options::StrikeExposure| Strike {
        strike: s.strike,
        call: s.call,
        put: s.put,
    };
    Ok(Json(ExposureResponse {
        signed: summary.totals.signed,
        absolute: summary.totals.absolute,
        strikes: summary.strikes.into_iter().map(convert).collect(),
        walls: Walls {
            calls: ranked.calls.into_iter().map(convert).collect(),
            puts: ranked.puts.into_iter().map(convert).collect(),
        },
        max_pain,
    }))
}

fn invalid_options(_: calculus::options::OptionsError) -> (StatusCode, Json<ErrorBody>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(ErrorBody {
            code: "invalid_options",
            message: "The options input cannot be calculated.",
        }),
    )
}
