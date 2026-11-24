//! Historical single-leg Snapshot tunnel execution with legacy floating-point fills.
use super::ExecutionError;
use crate::accounts::Side;

const FUNDING_INTERVAL_US: i64 = 8 * 60 * 60 * 1_000_000;

/// A completed candle and the signal available at its opening quote.
pub struct TunnelBar {
    pub time_us: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub entry: Option<Side>,
    pub target_ceiling: Option<f64>,
    pub ends_session: bool,
}

/// Risk and funding settings for the calculator's single funded position.
pub struct TunnelRisk {
    pub fee_pct: f64,
    pub stop_loss_pct: f64,
    pub take_profit_pct: f64,
    pub minimum_order: f64,
    pub slippage_bps: f64,
    pub funding_pct: f64,
    pub allow_reentry: bool,
}

#[derive(Clone, Copy)]
enum Close {
    Stop,
    Target,
    Session,
    Strategy,
}

impl Close {
    fn label(self) -> &'static str {
        match self {
            Self::Stop => "Stop loss",
            Self::Target => "Take profit",
            Self::Session => "End of scheduled session",
            Self::Strategy => "End of strategy",
        }
    }
}

struct Fill {
    price: f64,
    reason: Close,
}

struct Position {
    side: Side,
    index: usize,
    price: f64,
    capital: f64,
    quantity: f64,
    target: Option<f64>,
    funding: f64,
}

/// Account equity and signed quantity after one bar.
pub struct TunnelMark {
    pub equity: f64,
    pub quantity: f64,
}

/// Realized amounts, with indices into the original candle sequence.
pub struct TunnelTrade {
    pub capital: f64,
    pub side: Side,
    pub entry: usize,
    pub exit: usize,
    pub entry_price: f64,
    pub exit_price: f64,
    pub quantity: f64,
    pub pnl: f64,
    pub return_pct: f64,
    pub reason: &'static str,
}

/// Ordered execution results for the calculator.
pub struct TunnelRun {
    pub marks: Vec<TunnelMark>,
    pub trades: Vec<TunnelTrade>,
}

fn sign(side: Side) -> f64 {
    match side {
        Side::Long => 1.0,
        Side::Short => -1.0,
    }
}

impl Position {
    fn enter(bar: &TunnelBar, index: usize, capital: f64, risk: &TunnelRisk) -> Option<Self> {
        let side = bar.entry?;
        let price = bar.open * (1.0 + sign(side) * risk.slippage_bps / 10_000.0);
        let mut target = bar.target_ceiling.filter(|_| side == Side::Long);
        if let Some(ceiling) = &mut target {
            if risk.take_profit_pct > 0.0 {
                *ceiling = ceiling.min(price * (1.0 + risk.take_profit_pct / 100.0));
            }
            let net = *ceiling * (1.0 - risk.slippage_bps / 10_000.0);
            if net * (1.0 - risk.fee_pct / 100.0).powi(2) <= price {
                return None;
            }
        }
        Some(Self {
            side,
            index,
            price,
            capital,
            quantity: (capital - capital * risk.fee_pct / 100.0) / price,
            target,
            funding: 0.0,
        })
    }

    fn protect(&self, open: f64, high: f64, low: f64, risk: &TunnelRisk) -> Option<Fill> {
        let long = self.side == Side::Long;
        let direction = sign(self.side);
        let stop = self.price * (1.0 - direction * risk.stop_loss_pct / 100.0);
        if risk.stop_loss_pct > 0.0 && (if long { low <= stop } else { high >= stop }) {
            return Some(Fill {
                price: if long { stop.min(open) } else { stop.max(open) },
                reason: Close::Stop,
            });
        }
        if self.target.is_none() && risk.take_profit_pct <= 0.0 {
            return None;
        }
        let target = self
            .target
            .unwrap_or_else(|| self.price * (1.0 + direction * risk.take_profit_pct / 100.0));
        let touched = if long { high >= target } else { low <= target };
        touched.then(|| Fill {
            price: self.target.unwrap_or_else(|| {
                if long {
                    target.max(open)
                } else {
                    target.min(open)
                }
            }),
            reason: Close::Target,
        })
    }

    fn settle(self, fill: Fill, index: usize, risk: &TunnelRisk) -> (f64, TunnelTrade) {
        let price = fill.price * (1.0 - sign(self.side) * risk.slippage_bps / 10_000.0);
        let exposure = self.quantity * price;
        let exit_fee = exposure * risk.fee_pct / 100.0;
        let (cash, pnl) = match self.side {
            Side::Long => {
                let cash = exposure - exit_fee - self.funding;
                (cash, cash - self.capital)
            }
            Side::Short => {
                let pnl = self.quantity * (self.price - price)
                    - self.capital * risk.fee_pct / 100.0
                    - exit_fee
                    - self.funding;
                (self.capital + pnl, pnl)
            }
        };
        (
            cash,
            TunnelTrade {
                capital: self.capital,
                side: self.side,
                entry: self.index,
                exit: index,
                entry_price: self.price,
                exit_price: price,
                quantity: self.quantity,
                pnl,
                return_pct: pnl / self.capital * 100.0,
                reason: fill.reason.label(),
            },
        )
    }

    fn mark(&self, price: f64, risk: &TunnelRisk) -> TunnelMark {
        let equity = match self.side {
            Side::Long => self.quantity * price - self.funding,
            Side::Short => {
                self.capital * (1.0 - risk.fee_pct / 100.0) + self.quantity * (self.price - price)
                    - self.funding
            }
        };
        TunnelMark {
            equity,
            quantity: sign(self.side) * self.quantity,
        }
    }
}

struct Account {
    cash: f64,
    position: Option<Position>,
    trades: Vec<TunnelTrade>,
}

impl Account {
    fn close(&mut self, fill: Option<Fill>, index: usize, risk: &TunnelRisk) {
        if let Some(fill) = fill
            && let Some(position) = self.position.take()
        {
            let (cash, trade) = position.settle(fill, index, risk);
            self.cash = cash;
            self.trades.push(trade);
        }
    }
}

/// Execute funding, gap protection, entries, intrabar protection and liquidation in order.
pub fn simulate_tunnel(
    bars: &[TunnelBar],
    capital: f64,
    risk: &TunnelRisk,
) -> Result<TunnelRun, ExecutionError> {
    let mut account = Account {
        cash: capital,
        position: None,
        trades: Vec::new(),
    };
    let mut marks = Vec::with_capacity(bars.len());
    for (index, bar) in bars.iter().enumerate() {
        let was_open = account.position.is_some();
        if let Some(position) = &mut account.position {
            let boundaries = bar.time_us.div_euclid(FUNDING_INTERVAL_US)
                - bars[index - 1].time_us.div_euclid(FUNDING_INTERVAL_US);
            position.funding +=
                sign(position.side) * position.quantity * bar.open * risk.funding_pct / 100.0
                    * boundaries as f64;
        }
        let gap = account
            .position
            .as_ref()
            .and_then(|p| p.protect(bar.open, bar.open, bar.open, risk));
        account.close(gap, index, risk);
        if !was_open
            && (risk.allow_reentry || account.trades.is_empty())
            && account.cash > 0.0
            && account.cash >= risk.minimum_order
        {
            account.position = Position::enter(bar, index, account.cash, risk);
        }
        let intrabar = account
            .position
            .as_ref()
            .and_then(|p| p.protect(bar.open, bar.high, bar.low, risk));
        account.close(intrabar, index, risk);
        if bar.ends_session || index + 1 == bars.len() {
            let reason = if bar.ends_session {
                Close::Session
            } else {
                Close::Strategy
            };
            account.close(
                Some(Fill {
                    price: bar.close,
                    reason,
                }),
                index,
                risk,
            );
        }
        let mark = account.position.as_ref().map_or(
            TunnelMark {
                equity: account.cash,
                quantity: 0.0,
            },
            |position| position.mark(bar.close, risk),
        );
        if !mark.equity.is_finite() || !mark.quantity.is_finite() {
            return Err(ExecutionError::Arithmetic);
        }
        marks.push(mark);
    }
    Ok(TunnelRun {
        marks,
        trades: account.trades,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn risk() -> TunnelRisk {
        TunnelRisk {
            fee_pct: 0.0,
            stop_loss_pct: 5.0,
            take_profit_pct: 10.0,
            minimum_order: 0.0,
            slippage_bps: 0.0,
            funding_pct: 0.0,
            allow_reentry: false,
        }
    }

    fn bar(time_us: i64, open: f64, close: f64, entry: Option<Side>) -> TunnelBar {
        TunnelBar {
            time_us,
            open,
            high: open.max(close),
            low: open.min(close),
            close,
            entry,
            target_ceiling: None,
            ends_session: false,
        }
    }

    #[test]
    fn charges_both_fees_and_signed_funding_at_the_boundary() {
        let risk = TunnelRisk {
            fee_pct: 1.0,
            funding_pct: 1.0,
            ..risk()
        };
        for (side, expected) in [(Side::Long, 9.404), (Side::Short, -49.996)] {
            let bars = [
                bar(FUNDING_INTERVAL_US - 1, 100.0, 100.0, Some(side)),
                bar(FUNDING_INTERVAL_US, 100.0, 104.0, None),
            ];
            let run = simulate_tunnel(&bars, 1000.0, &risk).unwrap();
            assert!((run.marks[0].quantity - sign(side) * 9.9).abs() < 1e-9);
            assert_eq!(run.trades[0].reason, "End of strategy");
            assert!((run.trades[0].pnl - expected).abs() < 1e-9);
            assert_eq!(run.marks[1].quantity, 0.0);
        }
    }

    #[test]
    fn prioritizes_stop_over_target_and_honors_session_and_reentry() {
        let mut first = bar(0, 100.0, 100.0, Some(Side::Long));
        first.high = 120.0;
        first.low = 90.0;
        let mut session = bar(1, 100.0, 101.0, Some(Side::Short));
        session.ends_session = true;
        let bars = [first, session, bar(2, 100.0, 100.0, None)];
        let run = simulate_tunnel(&bars, 1000.0, &risk()).unwrap();
        assert_eq!(run.trades.len(), 1);
        assert_eq!(run.trades[0].reason, "Stop loss");
        assert_eq!(run.trades[0].exit_price, 95.0);

        let risk = TunnelRisk {
            allow_reentry: true,
            ..risk()
        };
        let run = simulate_tunnel(&bars, 1000.0, &risk).unwrap();
        assert_eq!(run.trades.len(), 2);
        assert_eq!(run.trades[1].reason, "End of scheduled session");
        assert_eq!(run.trades[1].exit_price, 101.0);
    }

    #[test]
    fn gap_cannot_reopen_and_explicit_target_cannot_fill_above_cap() {
        let mut first = bar(0, 100.0, 100.0, Some(Side::Long));
        first.target_ceiling = Some(103.0);
        let risk = TunnelRisk {
            allow_reentry: true,
            ..risk()
        };
        let run = simulate_tunnel(
            &[first, bar(1, 108.0, 108.0, Some(Side::Long))],
            1000.0,
            &risk,
        )
        .unwrap();
        assert_eq!(run.trades.len(), 1);
        assert_eq!(run.trades[0].reason, "Take profit");
        assert_eq!(run.trades[0].exit_price, 103.0);
    }

    #[test]
    fn rejects_a_cap_that_cannot_cover_round_trip_costs() {
        let mut first = bar(0, 100.0, 100.0, Some(Side::Long));
        first.target_ceiling = Some(101.0);
        let risk = TunnelRisk {
            fee_pct: 1.0,
            ..risk()
        };
        let run = simulate_tunnel(&[first], 1000.0, &risk).unwrap();
        assert!(run.trades.is_empty());
        assert_eq!(run.marks[0].equity, 1000.0);
    }
}
