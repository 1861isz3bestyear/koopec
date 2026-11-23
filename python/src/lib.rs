use calculus::options::{
    IdentifiedContract, OptionContract, OptionKind, OptionSnapshot, OptionsError, Valuation,
    aggregate,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

type Contract = (String, String, f64, i64, f64, f64, f64);
type Strike = (f64, f64, f64);

fn invalid(error: OptionsError) -> PyErr {
    PyValueError::new_err(format!("Invalid options input: {error:?}"))
}

#[pyfunction]
fn strike_exposures(
    observed_at: i64,
    available_at: i64,
    valued_at: i64,
    spot: f64,
    contracts: Vec<Contract>,
) -> PyResult<Vec<Strike>> {
    if contracts.len() > 10_000 {
        return Err(PyValueError::new_err("Too many option contracts"));
    }
    let contracts = contracts
        .into_iter()
        .map(|(id, kind, strike, expiry, iv, interest, multiplier)| {
            let kind = match kind.as_str() {
                "call" => OptionKind::Call,
                "put" => OptionKind::Put,
                _ => return Err(PyValueError::new_err("Invalid option kind")),
            };
            let contract = OptionContract::new(kind, strike, expiry, iv, interest, multiplier)
                .map_err(invalid)?;
            IdentifiedContract::new(id, contract).map_err(invalid)
        })
        .collect::<PyResult<Vec<_>>>()?;
    let valuation = Valuation::new(spot, valued_at).map_err(invalid)?;
    let snapshot = OptionSnapshot::new(observed_at, available_at, valuation, contracts)
        .and_then(|snapshot| snapshot.revalue(valuation))
        .map_err(invalid)?;
    let summary = aggregate(&snapshot).map_err(invalid)?;
    Ok(summary
        .strikes
        .into_iter()
        .map(|level| (level.strike, level.call, level.put))
        .collect())
}

#[pymodule]
fn koopec_calculus(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(strike_exposures, module)?)
}
