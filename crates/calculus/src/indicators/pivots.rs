use super::IndicatorError;

/// Whether to compare OI momentum or raw base-asset open interest.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Comparison {
    Momentum,
    OpenInterest,
}
/// High or low price swing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PivotKind {
    High,
    Low,
}
/// A validated observation with ready OI momentum.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PivotPoint {
    pub(crate) time: i64,
    pub(crate) available: i64,
    pub(crate) price: f64,
    pub(crate) oi: f64,
    pub(crate) momentum: f64,
}
impl PivotPoint {
    pub fn new(
        time: i64,
        available: i64,
        price: f64,
        oi: f64,
        momentum: f64,
    ) -> Result<Self, IndicatorError> {
        if available < time
            || !price.is_finite()
            || price <= 0.0
            || !oi.is_finite()
            || oi <= 0.0
            || !momentum.is_finite()
        {
            return Err(IndicatorError::InvalidInput);
        }
        Ok(Self {
            time,
            available,
            price,
            oi,
            momentum,
        })
    }
}
/// A confirmed price swing and its matched oscillator extreme.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Pivot {
    pub kind: PivotKind,
    pub pivot_at: i64,
    pub available_at: i64,
    pub price: f64,
    pub value: f64,
}
/// A directional swing comparison.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwingRelation {
    Agreement,
    Divergence,
}
/// Detect a strict, prominent swing in five chronological ready points.
pub fn detect_pivot(
    points: &[PivotPoint; 5],
    mode: Comparison,
    min_swing_percent: f64,
) -> Result<Option<Pivot>, IndicatorError> {
    if !min_swing_percent.is_finite()
        || min_swing_percent < 0.0
        || points.windows(2).any(|p| p[0].time >= p[1].time)
    {
        return Err(IndicatorError::InvalidInput);
    }
    let center = points[2].price;
    let neighbors = [
        points[0].price,
        points[1].price,
        points[3].price,
        points[4].price,
    ];
    let kind = if neighbors.iter().all(|x| center > *x) {
        PivotKind::High
    } else if neighbors.iter().all(|x| center < *x) {
        PivotKind::Low
    } else {
        return Ok(None);
    };
    let left = [points[0].price, points[1].price];
    let right = [points[3].price, points[4].price];
    let excursion = match kind {
        PivotKind::High => (center - left[0].min(left[1])).min(center - right[0].min(right[1])),
        PivotKind::Low => (left[0].max(left[1]) - center).min(right[0].max(right[1]) - center),
    };
    if excursion / center * 100.0 < min_swing_percent {
        return Ok(None);
    }
    let value = |i: usize| match mode {
        Comparison::Momentum => points[i].momentum,
        Comparison::OpenInterest => points[i].oi,
    };
    let mut chosen = 2;
    for i in [1, 3] {
        if match kind {
            PivotKind::High => value(i) > value(chosen),
            PivotKind::Low => value(i) < value(chosen),
        } {
            chosen = i;
        }
    }
    if mode == Comparison::OpenInterest {
        let strict = match kind {
            PivotKind::High => {
                value(chosen) > value(chosen - 1) && value(chosen) > value(chosen + 1)
            }
            PivotKind::Low => {
                value(chosen) < value(chosen - 1) && value(chosen) < value(chosen + 1)
            }
        };
        if !strict {
            return Ok(None);
        }
    }
    let available_at = points
        .iter()
        .map(|p| p.available)
        .max()
        .ok_or(IndicatorError::Arithmetic)?;
    Ok(Some(Pivot {
        kind,
        pivot_at: points[2].time,
        available_at,
        price: center,
        value: value(chosen),
    }))
}
/// Compare same-kind swings. No signal is produced for insignificant changes.
pub fn compare_pivots(
    previous: Pivot,
    current: Pivot,
    mode: Comparison,
    min_swing_percent: f64,
    min_oi_change: f64,
) -> Result<Option<SwingRelation>, IndicatorError> {
    if previous.kind != current.kind
        || previous.pivot_at >= current.pivot_at
        || !min_swing_percent.is_finite()
        || min_swing_percent < 0.0
        || !min_oi_change.is_finite()
        || min_oi_change < 0.0
        || !previous.price.is_finite()
        || previous.price <= 0.0
        || !current.price.is_finite()
        || current.price <= 0.0
        || !previous.value.is_finite()
        || !current.value.is_finite()
        || (mode == Comparison::OpenInterest && (previous.value <= 0.0 || current.value <= 0.0))
    {
        return Err(IndicatorError::InvalidInput);
    }
    let price_change = (current.price / previous.price - 1.0) * 100.0;
    let change = match mode {
        Comparison::Momentum => current.value - previous.value,
        Comparison::OpenInterest => (current.value / previous.value - 1.0) * 100.0,
    };
    if !price_change.is_finite() || !change.is_finite() {
        return Err(IndicatorError::Arithmetic);
    }
    let outward = match current.kind {
        PivotKind::High => price_change > 0.0,
        PivotKind::Low => price_change < 0.0,
    };
    if !outward
        || price_change.abs() < min_swing_percent
        || change == 0.0
        || change.abs() < min_oi_change
    {
        return Ok(None);
    }
    let agrees = match current.kind {
        PivotKind::High => change > 0.0,
        PivotKind::Low => change < 0.0,
    };
    Ok(Some(if agrees {
        SwingRelation::Agreement
    } else {
        SwingRelation::Divergence
    }))
}
