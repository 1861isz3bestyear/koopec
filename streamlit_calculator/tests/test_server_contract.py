# Copyright 2026 anchored-vwam-backtest contributors
"""Check the cross-project contract in an interpreter without shared imports."""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from paper_trading_bot.config import SERVER_CONFIG_DIRECTORY, PaperBotConfig
from shared.hedge_strategy import HEDGE_MODE
from shared.validation import json_object, object_list

pytestmark = pytest.mark.contract
SERVER_ROOT = (
    Path(__file__).resolve().parents[3] / "paper" / "server_bot" / "server_bot"
)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Capture an isolated interpreter result."""

    returncode: int
    stdout: str
    stderr: str


async def _run_python_async(
    code: str, arguments: list[str], *, cwd: Path
) -> ProcessResult:
    """Run trusted contract code in an isolated interpreter.

    Returns:
        The interpreter result.

    """
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        *arguments,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    return ProcessResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode(),
        stderr=stderr.decode(),
    )


def run_python(code: str, *arguments: str, cwd: Path) -> ProcessResult:
    """Run trusted contract code synchronously.

    Returns:
        The interpreter result.

    """
    return asyncio.run(_run_python_async(code, list(arguments), cwd=cwd))


@pytest.mark.parametrize(
    ("trend", "side"), [(True, "Long"), (True, "Short"), (False, "Both")]
)
@pytest.mark.parametrize("close_sigma", [0, 2])
def test_export_is_accepted_by_server_and_signal_engine_matches(
    *, tmp_path: Path, trend: bool, side: str, close_sigma: int
) -> None:
    # A standalone checkout can run the other test levels without the server
    # tree.
    """Verify export is accepted by server and signal engine matches."""
    if not SERVER_ROOT.is_dir():
        pytest.skip(
            "server sibling project is required for cross-project contract"
            " tests"
        )
    config = PaperBotConfig(
        strategy_mode="VWAP band mean reversion",
        timeframe="1m",
        trend=trend,
        open_order_vwap_sigma=1,
        close_order_vwap_sigma=close_sigma,
        initial_capital=1000,
        stop_loss_pct=0.4,
        allow_immediate_reentry=True,
        vwap_anchor_reset_weeks=2,
        data_source="Bybit REST",
        ticker="XRP_USDT",
    )
    path = config.save_server("server_config", tmp_path)
    code = """
import json,sys
from pathlib import Path
import pandas as pd
from reference_bot.config import PaperBotConfig
from shared.indicators import add_launch_weekly_anchored_vwap
from shared.strategy import backtest
cfg=PaperBotConfig.load(Path(sys.argv[1]))
df=pd.DataFrame(dict(
 time=pd.date_range('2026-01-01',periods=4,freq='min',tz='UTC'),
 open=[100,100,102,98],high=[100,101,102,98],low=[100,100,102,98],
 close=[100,101,102,98],volume=10))
start=pd.to_datetime(df["time"],utc=True).iloc[0]
end=pd.to_datetime(df["time"],utc=True).iloc[-1]
data=add_launch_weekly_anchored_vwap(
 df,start,cfg.vwap_anchor_reset_weeks)
eq,trades=backtest(
 data,start,strategy_end_at=end,initial_capital=cfg.initial_capital,
 fee_pct=.1,stop_loss_pct=cfg.stop_loss_pct,take_profit_pct=cfg.take_profit_pct,
 allow_reentry=cfg.allow_immediate_reentry,strategy_mode=cfg.strategy_mode,
 band_sigma=cfg.open_order_vwap_sigma,
 exit_band_sigma=cfg.close_order_vwap_sigma,trend_mode=cfg.trend,
 open_position_side=cfg.open_position_side)
encoded=[dict(t.__dict__,entry_time=str(t.entry_time),
 exit_time=str(t.exit_time)) for t in trades]
print(json.dumps({'equity':eq["equity"].astype(float).tolist(),
 'trades':encoded}))
"""
    # Set the requested side in the exported contract, including serialized
    # defaults.
    exported = json_object(path.read_text())
    exported["open_position_side"] = side
    _ = path.write_text(json.dumps(exported))
    server = run_python(
        code,
        str(path),
        cwd=SERVER_ROOT,
    )
    assert server.returncode == 0, server.stderr
    local_code = code.replace(
        "from reference_bot.config", "from paper_trading_bot.config"
    ).replace(
        "cfg=PaperBotConfig.load(Path(sys.argv[1]))",
        "cfg=PaperBotConfig(**{k:v for k,v in"
        " json.load(open(sys.argv[1])).items() if k in"
        " PaperBotConfig.__dataclass_fields__})",
    )
    local = run_python(
        local_code,
        str(path),
        cwd=Path(__file__).resolve().parents[1],
    )
    assert local.returncode == 0, local.stderr
    assert json.loads(server.stdout) == json.loads(local.stdout)
    expected_count = 4
    assert (
        len(object_list(json_object(server.stdout)["equity"])) == expected_count
    )


@pytest.mark.parametrize(
    ("sigma", "basis"), [(1.2, "Position"), (4.25, "Deposit")]
)
def test_zero_hedge_export_preserves_risk_settings(
    tmp_path: Path, sigma: float, basis: str
) -> None:
    """Verify zero hedge export preserves risk without signed legacy legs.

    legs.
    """
    if not SERVER_ROOT.is_dir():
        pytest.skip("server sibling required")
    cfg = PaperBotConfig(
        strategy_mode=HEDGE_MODE,
        timeframe="1m",
        trend=True,
        open_order_vwap_sigma=0,
        close_order_vwap_sigma=sigma,
        initial_capital=100,
        stop_loss_pct=1,
        allow_immediate_reentry=False,
        vwap_anchor_reset_weeks=2,
        ticker="XRP_USDT",
        open_position_side="Both",
        stop_loss_basis=basis,
    )
    exported = json_object(cfg.to_server_json())
    assert "open_sigma_1" not in exported
    path = tmp_path / "hedge.json"
    _ = path.write_text(json.dumps(exported))
    code = (
        "from pathlib import Path; import sys; from reference_bot.config import"
        " PaperBotConfig;"
        " print(PaperBotConfig.load(Path(sys.argv[1])).to_json())"
    )
    result = run_python(
        code,
        str(path),
        cwd=SERVER_ROOT,
    )
    assert result.returncode == 0, result.stderr
    loaded = json_object(result.stdout)
    assert loaded == exported


def test_named_config_does_not_overwrite_or_escape_directory(
    tmp_path: Path,
) -> None:
    """Verify named config does not overwrite or escape directory."""
    cfg = PaperBotConfig(
        strategy_mode="VWAP band mean reversion",
        timeframe="1m",
        trend=False,
        open_order_vwap_sigma=1,
        close_order_vwap_sigma=0,
        initial_capital=100,
        stop_loss_pct=0,
        allow_immediate_reentry=False,
        vwap_anchor_reset_weeks=1,
    )
    destination = cfg.save_server("btc.json", tmp_path / "configs")
    original = destination.read_text()
    with pytest.raises(FileExistsError):
        _ = cfg.save_server("btc", destination.parent)
    assert destination.read_text() == original
    absolute_name = str(Path("/", "tmp", "config"))
    for name in ["../escape", "", absolute_name, "with spaces", ".hidden"]:
        with pytest.raises(ValueError, match="letters, numbers"):
            _ = cfg.save_server(name, destination.parent)


@pytest.mark.parametrize("leverage", [2, 100])
def test_leverage_export_preserves_settings_in_both_server_bots(
    tmp_path: Path, leverage: int
) -> None:
    """Verify leverage export preserves settings in both server bots."""
    if not SERVER_ROOT.is_dir():
        pytest.skip(
            "server sibling project is required for cross-project contract"
            " tests"
        )
    cfg = PaperBotConfig(
        strategy_mode="VWAP band mean reversion",
        timeframe="1m",
        trend=True,
        open_order_vwap_sigma=1,
        close_order_vwap_sigma=2,
        initial_capital=1000,
        stop_loss_pct=0.4,
        allow_immediate_reentry=True,
        vwap_anchor_reset_weeks=2,
        data_source="Bybit REST",
        ticker="BTC_USDT",
        leverage=leverage,
        slippage_bps=3.5,
    )
    path = cfg.save_server("leveraged", tmp_path)
    code = """
import json,sys
from pathlib import Path
from reference_bot.config import PaperBotConfig as Reference
from live_paper_bot.config import PaperBotConfig as Live
for cls in [Reference,Live]:
    cfg=cls.load(Path(sys.argv[1]))
    assert cfg.leverage==int(sys.argv[2])
    assert cfg.slippage_bps==3.5
print('ok')
"""
    result = run_python(
        code,
        str(path),
        str(leverage),
        cwd=SERVER_ROOT,
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError, match="Lima server export"):
        _ = cfg.to_json()


def test_named_exports_target_server_config_directory() -> None:
    """Keep calculator exports available to the deployable server."""
    assert SERVER_CONFIG_DIRECTORY == SERVER_ROOT / "configs"
