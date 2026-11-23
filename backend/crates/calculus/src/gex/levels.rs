use super::{Exposure, exposure};
use crate::options::{OptionKind, OptionSnapshot, OptionsError};

/// Side contributions for a single strike, in USD per 1% move.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StrikeExposure {
    pub strike: f64,
    pub call: f64,
    pub put: f64,
}
/// Distinct signed and unsigned sums.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ExposureTotals {
    pub signed: f64,
    pub absolute: f64,
}
/// Strike exposures and totals, accumulated in sorted identity order.
#[derive(Debug, Clone, PartialEq)]
pub struct ExposureSummary {
    pub strikes: Vec<StrikeExposure>,
    pub totals: ExposureTotals,
}

/// Calculate exposures deterministically; overflow is an error.
pub fn aggregate(snapshot: &OptionSnapshot) -> Result<ExposureSummary, OptionsError> {
    let mut strikes: Vec<StrikeExposure> = Vec::new();
    let mut totals = ExposureTotals {
        signed: 0.0,
        absolute: 0.0,
    };
    for item in &snapshot.contracts {
        let Exposure::Live(value) = exposure(&item.contract, snapshot.valuation)? else {
            continue;
        };
        let strike = item.contract.strike;
        let index = match strikes.binary_search_by(|x| x.strike.total_cmp(&strike)) {
            Ok(index) => index,
            Err(index) => {
                strikes.insert(
                    index,
                    StrikeExposure {
                        strike,
                        call: 0.0,
                        put: 0.0,
                    },
                );
                index
            }
        };
        match item.contract.kind {
            OptionKind::Call => strikes[index].call += value,
            OptionKind::Put => strikes[index].put += value,
        }
        totals.signed += value;
        totals.absolute += value.abs();
        if !totals.signed.is_finite()
            || !totals.absolute.is_finite()
            || !strikes[index].call.is_finite()
            || !strikes[index].put.is_finite()
        {
            return Err(OptionsError::Arithmetic);
        }
    }
    Ok(ExposureSummary { strikes, totals })
}

/// Independent ranked walls, up to two on each side.
#[derive(Debug, Clone, PartialEq)]
pub struct RankedWalls {
    pub calls: Vec<StrikeExposure>,
    pub puts: Vec<StrikeExposure>,
}
/// Rank by side magnitude, breaking ties by lower strike. A range is an inclusive fractional distance from spot.
pub fn ranked_walls(
    summary: &ExposureSummary,
    spot: f64,
    range: Option<f64>,
) -> Result<RankedWalls, OptionsError> {
    if !spot.is_finite()
        || spot <= 0.0
        || range.is_some_and(|r| !r.is_finite() || r <= 0.0 || r >= 1.0)
    {
        return Err(OptionsError::InvalidInput);
    }
    let eligible = |x: &&StrikeExposure| {
        range.is_none_or(|r| x.strike >= spot * (1.0 - r) && x.strike <= spot * (1.0 + r))
    };
    let mut calls: Vec<_> = summary
        .strikes
        .iter()
        .filter(eligible)
        .filter(|x| x.call > 0.0)
        .copied()
        .collect();
    let mut puts: Vec<_> = summary
        .strikes
        .iter()
        .filter(eligible)
        .filter(|x| x.put < 0.0)
        .copied()
        .collect();
    calls.sort_by(|a, b| {
        b.call
            .total_cmp(&a.call)
            .then(a.strike.total_cmp(&b.strike))
    });
    puts.sort_by(|a, b| a.put.total_cmp(&b.put).then(a.strike.total_cmp(&b.strike)));
    calls.truncate(2);
    puts.truncate(2);
    Ok(RankedWalls { calls, puts })
}
