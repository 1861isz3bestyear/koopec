# Copyright 2026 anchored-vwam-backtest contributors
"""Verify independent side ranks within the current spot price range."""

import math
from dataclasses import replace

import pytest
from shared.option_levels import OptionLevelRange
from shared.tunnel import TunnelSettings
from snapshot_tunnel.options_model import (
    Exposure,
    parse_snapshots,
    ranked_walls,
    strike_exposures,
)
from snapshot_tunnel.tunnel_flow import TunnelFlow

from gui_calculator.options_gex import EXAMPLE
from gui_calculator.ranked_levels import ranked_price_columns
from gui_calculator.tunnel_replay import replay_tunnel


@pytest.mark.parametrize("put_scale", [0.1, 100.0])
def test_ranks_are_independent_of_net_gex_sign(put_scale: float) -> None:
    """Keep side magnitude ranks even when calls lie below put strikes."""
    levels = (
        Exposure(strike=90, call=10, put=-1 * put_scale),
        Exposure(strike=100, call=10, put=-2 * put_scale),
        Exposure(strike=110, call=1, put=-20 * put_scale),
        Exposure(strike=120, call=0, put=-10 * put_scale),
    )
    assert (sum(level.net for level in levels) > 0) == (put_scale < 1)
    assert ranked_price_columns(ranked_walls(levels, spot=100)) == {
        "options_call_1": 90,
        "options_call_2": 100,
        "options_put_1": 110,
        "options_put_2": 120,
    }


def test_missing_ranks_do_not_borrow_opposite_side_prices() -> None:
    """A single call does not fabricate a second call or any put."""
    prices = ranked_price_columns(
        ranked_walls((Exposure(strike=100, call=1, put=0),), spot=100)
    )
    assert prices.pop("options_call_1") == pytest.approx(100)
    assert all(math.isnan(price) for price in prices.values())
    assert all(
        math.isnan(price)
        for price in ranked_price_columns(ranked_walls((), spot=100)).values()
    )


@pytest.mark.parametrize("put_scale", [0.01, 100.0])
def test_replay_keeps_four_observed_ranks_for_both_regimes(
    put_scale: float,
) -> None:
    """Expose the same ranks as the profile without backdating receipts."""
    import pandas as pd

    first = parse_snapshots(EXAMPLE)[0]
    snapshot = replace(
        first,
        options=tuple(
            (
                replace(option, open_interest=option.open_interest * put_scale)
                if option.side == "put"
                else option
            )
            for option in first.options
        ),
    )
    times = pd.to_datetime([
        snapshot.timestamp - pd.Timedelta(minutes=1),
        snapshot.timestamp,
    ])
    data = pd.DataFrame({
        "time": times,
        "open": snapshot.spot,
        "high": snapshot.spot,
        "low": snapshot.spot,
        "close": snapshot.spot,
        "volume": 1.0,
    })
    result = replay_tunnel(
        data,
        (snapshot,),
        settings=TunnelSettings(use_book=False, votes=0),
        flow=TunnelFlow(),
    )
    expected = ranked_price_columns(
        ranked_walls(strike_exposures(snapshot), spot=snapshot.spot)
    )
    for column, price in expected.items():
        assert math.isnan(float(str(result.loc[0, column])))
        assert float(str(result.loc[1, column])) == pytest.approx(price)


@pytest.mark.parametrize("spot", [100.0, 1000.0])
def test_walls_rank_only_strikes_within_twenty_percent(spot: float) -> None:
    """Reject dominant distant strikes and include both range boundaries."""
    from snapshot_tunnel.options_model import wall_tunnel

    levels = (
        Exposure(strike=spot * 0.799, call=1000, put=-1000),
        Exposure(strike=spot * 0.8, call=10, put=0),
        Exposure(strike=spot, call=1, put=-1),
        Exposure(strike=spot * 1.2, call=0, put=-10),
        Exposure(strike=spot * 1.201, call=2000, put=-2000),
    )
    ranks = ranked_walls(levels, spot=spot)
    assert tuple(level.strike for level in ranks.calls) == (spot * 0.8, spot)
    assert tuple(level.strike for level in ranks.puts) == (spot * 1.2, spot)
    tunnel = wall_tunnel(levels, spot=spot)
    assert tunnel is not None
    assert (tunnel.put, tunnel.call) == (spot * 0.8, spot * 1.2)
    distant = (levels[0], levels[-1])
    assert ranked_walls(distant, spot=spot).calls == ()
    assert ranked_walls(distant, spot=spot).puts == ()
    assert wall_tunnel(distant, spot=spot) is None


@pytest.mark.parametrize(
    ("level_range", "expected"),
    [
        (OptionLevelRange(distance=0.1), (100,)),
        (OptionLevelRange(distance=0.3), (125, 100)),
        (OptionLevelRange(enabled=False, distance=0.1), (150, 125)),
    ],
)
def test_custom_range_filters_before_ranking(
    level_range: OptionLevelRange, expected: tuple[int, ...]
) -> None:
    """Wider or disabled limits expose the actual dominant distant strikes."""
    levels = tuple(
        Exposure(strike=strike, call=index, put=-index)
        for index, strike in enumerate((100, 125, 150), start=1)
    )
    ranks = ranked_walls(levels, spot=100, level_range=level_range)
    assert tuple(level.strike for level in ranks.calls) == expected
    assert tuple(level.strike for level in ranks.puts) == expected


@pytest.mark.parametrize("enabled", [False, True])
def test_replay_and_observed_history_share_custom_range(
    *, enabled: bool
) -> None:
    """Keep execution ranks and receipt-time chart ranks on the chosen range."""
    import pandas as pd

    from gui_calculator.observed_history import observation_history

    snapshot = parse_snapshots(EXAMPLE)[0]
    level_range = OptionLevelRange(enabled=enabled, distance=0.0001)
    data = pd.DataFrame({
        "time": [snapshot.timestamp],
        "open": [snapshot.spot],
        "high": [snapshot.spot],
        "low": [snapshot.spot],
        "close": [snapshot.spot],
        "volume": [1.0],
    })
    replay = replay_tunnel(
        data,
        (snapshot,),
        settings=TunnelSettings(
            level_range=level_range, use_book=False, votes=0
        ),
        flow=TunnelFlow(),
    )
    observed = observation_history((snapshot,), level_range=level_range)
    for column in ("options_call_1", "options_put_1"):
        if enabled:
            assert replay[column].isna().all()
            assert observed[column].isna().all()
        else:
            assert replay[column].iloc[0] == observed[column].iloc[0]
    assert observed["options_gex"].iloc[0] == pytest.approx(
        sum(level.net for level in strike_exposures(snapshot))
    )
