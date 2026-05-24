# Sandbox And Live Runners

## Current Scope

`make sandbox` is the operator menu for Nautilus sandbox runners. It is for
testing a strategy against live data feeds with sandbox execution, not for
sending real Polymarket orders.

The BTC snapshot model bundle is published as an archived example. It is useful
for studying the live wiring, feature construction, model serialization, and
strategy guards, but it is not a current trading recommendation or a maintained
profitability claim.

The broader `private/` research archive is also published for study. That does
not make every archived strategy a live strategy. The live/sandbox surface is
still limited to tracked files under `live/`, and currently only the BTC
snapshot model bundle has live sandbox wiring.

Real Polymarket live trading support is planned later. Keep that path separate
from sandbox until account credentials, order permissions, kill switches,
position limits, and operational checks are explicit.

## Directory Contract

- `strategies/` contains reusable strategy implementations.
- `strategies/private/` contains historical strategy modules that were once
  local-only. They remain in this namespace for import compatibility while
  being tracked as archived examples.
- `prediction_market_extensions/live/` contains shared live/sandbox helper
  code that is safe to ship with the framework.
- `live/` contains local sandbox and future live runner entrypoints.

Live runner and scaffold files can be tracked when they are safe to publish.
Selected public model profiles can also be tracked under `live/models/`.
Diagnostics and settlement ledgers using the standard
`*_diagnostics.json`/`*_settlements.json` suffixes, logs, `.env` files, and
machine-specific runtime files remain ignored by `live/.gitignore`.

Do not put private model weights, private research notes, or deployment secrets
in `prediction_market_extensions/live/`. That package is shared helper code
only. If a runner needs a model that is not intended for publication, reference
the ignored local path and keep the model file out of git.

## Sandbox Runner Contract

Sandbox runners are flat files under `live/`:

```text
live/my_strategy_sandbox.py
```

Each runner should expose:

```python
def run() -> None:
    ...
```

The runner is responsible for:

- importing the strategy implementation from `strategies/` or
  `strategies/private/`
- building the Nautilus `ImportableStrategyConfig`
- injecting local parameters and model artifact paths
- selecting the live data feeds and market universe
- calling shared helpers from `prediction_market_extensions/live/`

This mirrors the backtest runner model: runner files are the explicit operating
surface, while shared mechanics stay in extension modules.

## Shared Live Helpers

Reusable helper code belongs in `prediction_market_extensions/live/`.

Current helper responsibilities include:

- Polymarket BTC 5m slug and instrument loading
- external BTC market-data instrument defaults
- Nautilus sandbox node config construction
- sandbox execution client factory registration
- live BTC trade and L2 book feature buffering for strategies that need recent
  BTC momentum, volume, volatility, or book-depth features
- public Polymarket CLOB settlement polling for sandbox portfolio accounting
- rolling BTC 5m market discovery and pruning
- BTC market-data freshness checks so live strategies can fail closed when the
  external reference-price or book feed is stale

These helpers must remain parameter-free. They can accept strategy configs and
runtime options from a local runner, but they should not embed private
thresholds, coefficients, model paths, or sizing rules.

## BTC 5m Sandbox Plumbing

The BTC 5m sandbox flow is split between public-safe plumbing and strategy
assets. The archived BTC snapshot strategy is tracked, but the same boundary
still applies to unpublished local strategies.

The public-safe path is:

1. `make sandbox` starts `main.py --mode sandbox`.
2. The menu discovers flat runner files under `live/`.
3. A runner such as `live/btc_snapshot_model_sandbox.py` builds a Nautilus
   `ImportableStrategyConfig` and passes it into the shared sandbox helpers.
4. `prediction_market_extensions/live/btc_5m.py` builds the rolling BTC 5m
   Polymarket event-slug horizon, loads the initial UP/DOWN instrument IDs, and
   exposes an importable slug builder for provider refreshes.
5. `prediction_market_extensions/live/sandbox.py` builds the Nautilus sandbox
   node with public Polymarket market data, external Binance BTC trade and L2
   book feeds, optional extra Binance spot book feeds, and Nautilus sandbox
   execution.
6. Strategy code receives live Polymarket order-book deltas plus external
   Binance trade ticks and book deltas through Nautilus, then emits sandbox
   orders through Nautilus risk/execution.

The BTC 5m hooks are rolling, not fixed. On each Polymarket instrument refresh,
the slug builder returns the current upcoming market window. The public
instrument provider loads those markets, keeps only the current slug set, and
prunes stale instruments outside that set. The strategy then scans Nautilus'
cache for newly loaded BTC 5m instruments, subscribes the new UP/DOWN order
books, and can unsubscribe/prune expired markets after its configured retention
window.

This bounds the framework-level provider list, strategy subscriptions, and local
book maps. Nautilus may still retain some cache or sandbox-exchange metadata for
instruments seen during the process lifetime, so very long unattended sandbox
runs should watch memory, restart on a planned cadence if needed, and confirm
shutdown logs show expired books being cleaned up.

Settlement is separate from Nautilus' simulated exchange. The strategy can poll
public Polymarket CLOB market state after market expiry, record whether the
held token won, apply synthetic settlement fills to the sandbox position state,
and write a local sandbox settlement ledger. That ledger is local accounting,
not a real account ledger, and is ignored by `live/.gitignore`.

Long-running sandbox strategies should emit operational proof-of-life logs even
when they do not trade. The BTC snapshot sandbox emits `SANDBOX_MODEL_HEARTBEAT`
on a configurable interval and `SANDBOX_EVAL_SKIP` or `SANDBOX_EVAL_SIGNAL` at
model evaluation points. This makes it clear whether the node is merely
connected, actively receiving BTC ticks, and actually evaluating the current 5m
market.

Strategies should also guard against stale reference data. A connected reference
websocket is not enough proof that BTC features are fresh; the runner can pass a
maximum BTC feature age so strategy code skips entries when recent BTC trade
ticks are missing. The example runner defaults this to 30 seconds, which keeps
the guard meaningful while avoiding false blocks from normal public-feed
cadence.

## Example BTC Snapshot Runner

`live/btc_snapshot_model_sandbox.py` is the generic runner for the archived BTC
snapshot model bundle. It shows how the public-safe plumbing, model profile, and
strategy implementation fit together:

- it selects the BTC 5m market horizon;
- it sets environment values used by the importable BTC 5m slug builder;
- it resolves the model path from `LIVE_BTC_SNAPSHOT_MODEL_PATH` or a default
  tracked profile under `live/models/`;
- it builds a strategy config that injects instrument IDs, the external BTC
  trade instrument, optional extra spot feature instruments, local runtime
  options, and the model path;
- it calls `build_polymarket_binance_sandbox_config()` and
  `build_polymarket_binance_sandbox_node()`;
- it supports dry-run/build-only validation and a `--run` path for starting the
  Nautilus node.

The default model path is:

```text
live/models/btc_snapshot_model_s204_btc_l2_full_mar1_may9.json
```

That profile, plus several earlier or cross-asset variants under `live/models/`,
are summary JSONs produced by
`backtests/private/telonex_btc_5m_snapshot_model_research.py`. They include the
serialized logistic coefficients, feature columns, and research metrics needed
to score rows. Live policy knobs such as edge threshold, snapshot seconds,
spread limits, and sizing still come from the runner config and environment.
Selecting a different `LIVE_BTC_SNAPSHOT_MODEL_PATH` without matching those
runtime knobs can mismatch the JSON's recorded best policy. The referenced
dataset and policy CSV paths are provenance fields only and are not shipped as a
reproducibility bundle.

By default, the example runner sets `heartbeat_log_seconds` from
`LIVE_BTC_HEARTBEAT_LOG_SECONDS`, defaulting to five minutes. Set that
environment variable lower while debugging startup, or higher if a production
sandbox log is too chatty.

The example runner also exposes operational switches for the live data path:

- `LIVE_BTC_MAX_FEATURE_AGE_SECONDS` controls how stale BTC trade-derived
  features may be before the strategy should skip an entry; the default
  is 30 seconds.
- `LIVE_BTC_DAILY_STOP_LOSS` passes a sandbox daily loss limit into strategies
  that support one. For the archived BTC snapshot strategy this guard uses
  settled daily PnL, so unsettled open positions do not trip it.
- `LIVE_BTC_DATA_SOURCE` or `--btc-data-source` selects the Binance BTC feed.
  Supported values are `binance-us` and `binance-global`; the example runner
  defaults to `binance-global` so live BTC features match the Telonex Binance
  data used for the archived model.
- `LIVE_BTC_BINANCE_GLOBAL=1` or `--binance-global` remains as a compatibility
  alias for `--btc-data-source binance-global`.
- `LIVE_BTC_EXTRA_SPOT_INSTRUMENT_IDS` or `--extra-spot-instrument-ids` can
  provide comma-separated Binance spot instruments such as
  `ETHUSDT.BINANCE,SOLUSDT.BINANCE`. If unset, the runner inspects the
  model columns and auto-subscribes matching spot instruments for prefixes such
  as `eth_` and `sol_`.

`live/btc_eth_sol_snapshot_model_sandbox.py` is a convenience wrapper for the
archived BTC 5m ETH/SOL profile. It points the base runner at the ETH/SOL model
artifact, sets `LIVE_BTC_SNAPSHOT_EDGE=0.08`, and subscribes
`ETHUSDT.BINANCE` and `SOLUSDT.BINANCE` alongside BTC. Run it directly the same
way as the generic runner:

```bash
uv run python live/btc_eth_sol_snapshot_model_sandbox.py --run
```

The wrapper uses `os.environ.setdefault()`, so existing environment variables
still override its model path, edge, or extra spot instrument defaults.

The BTC snapshot runners are useful public examples of sandbox wiring and model
strategy mechanics. They are not proof that the strategy still works. Market
structure, public feed behavior, Polymarket constraints, and model relevance can
all drift. Treat `--build-only` as a wiring check and `--run` as a sandbox-only
experiment.

## Archived Strategy Boundary

The `private/` directory name is historical. Tracked modules there are public
source now, but they are still archived research code rather than promoted
framework defaults.

The BTC snapshot model is the only archived private strategy connected to live
sandbox runners. Its strategy, model summary JSONs, and research scripts are
tracked so readers can inspect a complete historical example of:

- Polymarket BTC 5m market discovery;
- external BTC and optional cross-asset spot feature buffering;
- L2 book imbalance and microprice features;
- stale-data, spread, size, settled daily-loss, and settlement guards;
- sandbox market-order submission through Nautilus;
- model evaluation and diagnostics logging.

The archived bundle is still not a public reproducibility package. Retraining
the JSON profiles requires local Telonex Polymarket book snapshots and Telonex
Binance spot parquet files that are not included in the repository. The research
runner will fail closed when those local caches are missing rather than silently
fabricating training rows. The live strategy also imports the archived research
module at runtime for the logistic model type, feature constants, and prediction
helper, so that file is part of the live sandbox dependency surface as well as
the retraining story.

`strategies/private/passive_pair_accumulation.py` is also tracked, but it is not
connected to any live runner. It belongs to the archived Telonex BTC 5m
backtest/search stack. The strategy posts passive paired bids on complementary
YES/NO books when the combined maker cost is below settlement value, holds
matched shares, and exits unmatched surplus after its completion timeout.

Do not include in git:

- unrelated model weights or serialized model profiles;
- private optimizer sweeps, validation reports, or iteration history unless
  they are deliberately curated source files;
- local model profiles that were not intentionally published;
- Telonex-derived datasets or generated research artifacts;
- `.env`, logs, diagnostics, sandbox settlement ledgers, or account credentials.

Keep unpublished artifacts under ignored paths such as `output/`, local model
directories, or another local storage path. Public helpers should describe
interfaces and operational mechanics, not silently embed unpublished edge.

## Model And Parameter Placement

Open-source-safe runner parameters can live in a tracked file under `live/`.
Published archival model profiles can live under `live/models/`. Private model
weights and private research artifacts should stay under ignored paths such as:

```text
live/models/local-*.json
output/
~/.cache/nautilus_trader/
```

A local runner can inject tracked operating parameters and ignored model paths
into the strategy config:

```python
STRATEGY_PARAMETERS = {
    "parameter_name": ...,
    "model_path": "live/models/my_private_model.json",
}
```

That local runner can then inject those values into the strategy config:

```python
ImportableStrategyConfig(
    strategy_path="strategies.private.my_strategy:MyStrategy",
    config_path="strategies.private.my_strategy:MyStrategyConfig",
    config={
        **STRATEGY_PARAMETERS,
        "instrument_ids": [...],
    },
)
```

Use `.env` for secrets and machine-specific operational switches. Do not rely
on `.env` as the only source of structured strategy parameters unless that is
intentional for the deployment.

Large diagnostics should be opt-in. For example, the BTC snapshot sandbox runner
only writes its evaluation/order/fill diagnostics when
`LIVE_BTC_SNAPSHOT_DIAGNOSTICS_PATH` is set. Use the standard
`*_diagnostics.json` and `*_settlements.json` suffixes for local artifact paths,
or add any custom names to `.gitignore` before running.

## Running Sandbox

Open the sandbox menu:

```bash
make sandbox
```

Equivalent direct command:

```bash
uv run python main.py --mode sandbox
```

The menu discovers flat Python and notebook files under `live/`. Runtime files
matching the standard diagnostics and settlement suffixes are ignored. Published
model profiles under `live/models/` can be inspected or selected with
`LIVE_BTC_SNAPSHOT_MODEL_PATH`.

Direct runner execution is still useful while developing a sandbox runner:

```bash
uv run python live/my_strategy_sandbox.py
```

Local runners may choose to make direct execution a dry-run and reserve actual
node startup for `make sandbox` or a `--run` flag.

Sandbox runners that subscribe to a fixed set of upcoming markets should load a
large enough horizon for the planned session. For BTC 5m runners,
`LIVE_BTC_5M_MARKET_COUNT=36` covers about three hours of forward market
discovery while rolling refresh keeps advancing the window. Increase or reduce
that value based on the forward horizon a strategy needs to see at startup.

## Public Polymarket Data

The sandbox helper uses public Polymarket CLOB market-data access. Nautilus
1.226's upstream Polymarket data factory constructs an authenticated CLOB
client, but the framework sandbox helper registers a public-data factory so
`make sandbox` does not require Polymarket API credentials for market-data-only
paper trading.

The sandbox runner still uses Nautilus sandbox execution, so selected
strategies paper trade unless you intentionally add a separate real
live-trading command later.

## Path To Live Polymarket Trading

Future real live trading should reuse the same structure:

- `make sandbox` remains sandbox-only.
- A separate command should be added for real live trading when it is ready.
- Public-safe live runner scaffolds can live under `live/`.
- Shared Polymarket adapter helpers should remain under
  `prediction_market_extensions/live/`.
- Private keys, account identifiers, unpublished model parameters, and
  deployment-specific risk limits should stay out of tracked helper code.
- Real Polymarket order routing will require authenticated Polymarket
  credentials and should not reuse the unauthenticated sandbox data factory for
  execution.

Before enabling real order routing, require explicit checks for account
balances, market permissions, max order size, max daily loss, stale data,
position limits, and emergency shutdown behavior.
