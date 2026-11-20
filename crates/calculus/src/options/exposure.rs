use super::{OptionContract, OptionKind, OptionsError, Valuation};

/// Signed USD delta-notional change for a one-percent underlying move.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Exposure {
    /// The contract is at or past expiry at valuation time.
    Expired,
    /// A live contract's signed contribution; zero OI produces zero.
    Live(f64),
}

/// Calculate zero-rate Black–Scholes gamma exposure.
pub fn exposure(contract: &OptionContract, valuation: Valuation) -> Result<Exposure, OptionsError> {
    if contract.expiry <= valuation.time {
        return Ok(Exposure::Expired);
    }
    let seconds = i128::from(contract.expiry) - i128::from(valuation.time);
    let years = seconds as f64 / (365.0 * 86_400.0);
    let volatility = contract.iv * years.sqrt();
    if !volatility.is_finite() || volatility == 0.0 {
        return Err(OptionsError::Arithmetic);
    }
    let d1 = (valuation.spot.ln() - contract.strike.ln()) / volatility + volatility / 2.0;
    let amount = (-d1 * d1 / 2.0).exp() / volatility / (2.0 * std::f64::consts::PI).sqrt()
        * contract.open_interest
        * contract.multiplier
        * valuation.spot
        * 0.01;
    if !amount.is_finite() {
        return Err(OptionsError::Arithmetic);
    }
    Ok(Exposure::Live(match contract.kind {
        OptionKind::Call => amount,
        OptionKind::Put => -amount,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn at_money_exposure_and_side() {
        let valuation = Valuation::new(100.0, 0).unwrap();
        let call =
            OptionContract::new(OptionKind::Call, 100.0, 31_536_000, 0.5, 10.0, 2.0).unwrap();
        let put = OptionContract::new(OptionKind::Put, 100.0, 31_536_000, 0.5, 10.0, 2.0).unwrap();
        let expected = 15.466724672113973;
        let Exposure::Live(value) = exposure(&call, valuation).unwrap() else {
            panic!("live")
        };
        assert!((value - expected).abs() < 1e-12);
        assert_eq!(exposure(&put, valuation), Ok(Exposure::Live(-value)));
        assert_eq!(
            exposure(&call, Valuation::new(100.0, 31_536_000).unwrap()),
            Ok(Exposure::Expired)
        );
    }

    #[test]
    fn invalid_and_zero_inputs_are_distinct() {
        assert_eq!(Valuation::new(f64::NAN, 0), Err(OptionsError::InvalidInput));
        for bad in [0.0, -1.0, f64::INFINITY, f64::NAN] {
            assert_eq!(
                OptionContract::new(OptionKind::Call, bad, 1, 0.5, 1.0, 1.0),
                Err(OptionsError::InvalidInput)
            );
            assert_eq!(
                OptionContract::new(OptionKind::Call, 1.0, 1, bad, 1.0, 1.0),
                Err(OptionsError::InvalidInput)
            );
            assert_eq!(
                OptionContract::new(OptionKind::Call, 1.0, 1, 0.5, 1.0, bad),
                Err(OptionsError::InvalidInput)
            );
        }
        let zero = OptionContract::new(OptionKind::Call, 100.0, 1, 0.5, 0.0, 1.0).unwrap();
        assert_eq!(
            exposure(&zero, Valuation::new(100.0, 0).unwrap()),
            Ok(Exposure::Live(0.0))
        );
        let huge =
            OptionContract::new(OptionKind::Call, 100.0, 31_536_000, 0.5, f64::MAX, 2.0).unwrap();
        assert_eq!(
            exposure(&huge, Valuation::new(100.0, 0).unwrap()),
            Err(OptionsError::Arithmetic)
        );
    }
}
