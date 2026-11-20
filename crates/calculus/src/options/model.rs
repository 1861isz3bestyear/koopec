use super::OptionsError;

/// Option side under the calls-positive, puts-negative GEX convention.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionKind {
    Call,
    Put,
}

/// Validated linear option; open interest is a contract count.
#[derive(Debug, Clone, PartialEq)]
pub struct OptionContract {
    pub(crate) kind: OptionKind,
    pub(crate) strike: f64,
    pub(crate) expiry: i64,
    pub(crate) iv: f64,
    pub(crate) open_interest: f64,
    pub(crate) multiplier: f64,
}

impl OptionContract {
    /// Construct a contract with IV as a fraction and expiry in Unix seconds.
    pub fn new(
        kind: OptionKind,
        strike: f64,
        expiry: i64,
        iv: f64,
        open_interest: f64,
        multiplier: f64,
    ) -> Result<Self, OptionsError> {
        if ![strike, iv, multiplier]
            .into_iter()
            .all(|v| v.is_finite() && v > 0.0)
            || !open_interest.is_finite()
            || open_interest < 0.0
        {
            return Err(OptionsError::InvalidInput);
        }
        Ok(Self {
            kind,
            strike,
            expiry,
            iv,
            open_interest,
            multiplier,
        })
    }
}

/// Spot and explicit valuation time in Unix seconds.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Valuation {
    pub(crate) spot: f64,
    pub(crate) time: i64,
}

impl Valuation {
    /// Reject nonpositive and nonfinite prices.
    pub fn new(spot: f64, time: i64) -> Result<Self, OptionsError> {
        if !spot.is_finite() || spot <= 0.0 {
            return Err(OptionsError::InvalidInput);
        }
        Ok(Self { spot, time })
    }
}

/// A contract with a unique caller-supplied source and instrument identity.
#[derive(Debug, Clone, PartialEq)]
pub struct IdentifiedContract {
    pub(crate) identity: String,
    pub(crate) contract: OptionContract,
}

impl IdentifiedContract {
    /// Construct an identified contract. Identities must not be empty.
    pub fn new(identity: String, contract: OptionContract) -> Result<Self, OptionsError> {
        if identity.trim().is_empty() {
            return Err(OptionsError::InvalidInput);
        }
        Ok(Self { identity, contract })
    }
}

/// A chain with explicit observation, availability and valuation times.
#[derive(Debug, Clone, PartialEq)]
pub struct OptionSnapshot {
    pub(crate) observed_at: i64,
    pub(crate) available_at: i64,
    pub(crate) valuation: Valuation,
    pub(crate) contracts: Vec<IdentifiedContract>,
}

impl OptionSnapshot {
    /// Sort by identity and reject duplicate identities and unavailable data.
    pub fn new(
        observed_at: i64,
        available_at: i64,
        valuation: Valuation,
        mut contracts: Vec<IdentifiedContract>,
    ) -> Result<Self, OptionsError> {
        if available_at < observed_at || valuation.time < available_at {
            return Err(OptionsError::InvalidInput);
        }
        contracts.sort_by(|a, b| a.identity.cmp(&b.identity));
        if contracts
            .windows(2)
            .any(|pair| pair[0].identity == pair[1].identity)
        {
            return Err(OptionsError::InvalidInput);
        }
        Ok(Self {
            observed_at,
            available_at,
            valuation,
            contracts,
        })
    }

    /// Revalue at a later cutoff, preserving provenance and dropping expired contracts.
    pub fn revalue(&self, valuation: Valuation) -> Result<Self, OptionsError> {
        if valuation.time < self.available_at || valuation.time < self.valuation.time {
            return Err(OptionsError::InvalidInput);
        }
        let mut snapshot = self.clone();
        snapshot.valuation = valuation;
        snapshot
            .contracts
            .retain(|c| c.contract.expiry > valuation.time);
        Ok(snapshot)
    }

    /// The original observation time in Unix seconds.
    pub fn observed_at(&self) -> i64 {
        self.observed_at
    }
    /// The time the snapshot became available in Unix seconds.
    pub fn available_at(&self) -> i64 {
        self.available_at
    }
    /// The number of retained contracts.
    pub fn len(&self) -> usize {
        self.contracts.len()
    }
    /// Whether the snapshot has no contracts.
    pub fn is_empty(&self) -> bool {
        self.contracts.is_empty()
    }
}
