use super::{OptionKind, OptionSnapshot, OptionsError};

/// Max-pain result and reason for absence.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MaxPain {
    Strike(f64),
    Empty,
    MixedExpiry,
    ZeroOpenInterest,
}

/// Minimize linear intrinsic payout over observed strikes; lower strikes win ties.
pub fn max_pain(snapshot: &OptionSnapshot) -> Result<MaxPain, OptionsError> {
    let Some(first) = snapshot.contracts.first() else {
        return Ok(MaxPain::Empty);
    };
    if snapshot
        .contracts
        .iter()
        .any(|c| c.contract.expiry != first.contract.expiry)
    {
        return Ok(MaxPain::MixedExpiry);
    }
    if snapshot
        .contracts
        .iter()
        .all(|c| c.contract.open_interest == 0.0)
    {
        return Ok(MaxPain::ZeroOpenInterest);
    }
    let mut strikes: Vec<_> = snapshot
        .contracts
        .iter()
        .map(|c| c.contract.strike)
        .collect();
    strikes.sort_by(f64::total_cmp);
    strikes.dedup();
    let mut best = (strikes[0], f64::INFINITY);
    for strike in strikes {
        let mut payout = 0.0;
        for item in &snapshot.contracts {
            let c = &item.contract;
            let intrinsic = match c.kind {
                OptionKind::Call => (strike - c.strike).max(0.0),
                OptionKind::Put => (c.strike - strike).max(0.0),
            };
            payout += intrinsic * c.open_interest * c.multiplier;
            if !payout.is_finite() {
                return Err(OptionsError::Arithmetic);
            }
        }
        if payout < best.1 {
            best = (strike, payout);
        }
    }
    Ok(MaxPain::Strike(best.0))
}
