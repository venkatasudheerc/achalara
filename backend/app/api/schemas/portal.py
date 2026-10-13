"""Client portal schemas. Percentages are decimal fractions (0.05 = 5%)."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class PortalViewerResponse(BaseModel):
    client_id: str
    name: str
    preview: bool  # an advisor looking at this client's portal


class PortalSleeve(BaseModel):
    sleeve_id: str
    strategy_id: str
    strategy_name: str


class PortalAccount(BaseModel):
    id: str
    client_id: str  # the owner; not the viewer when ``shared``
    name: str
    number_last4: Optional[str] = None
    shared: bool
    sleeves: List[PortalSleeve] = []


class PortalAccountsResponse(BaseModel):
    viewer: PortalViewerResponse
    accounts: List[PortalAccount]


class RowPlace(BaseModel):
    """Where a row sits: its account, and the strategy it is held under."""

    account_id: str
    account_name: str
    shared: bool
    sleeve_id: str
    strategy_id: str
    strategy_name: str


class PortalPosition(RowPlace):
    symbol: str
    security_type: str  # stock | etf | option | other
    quantity: float
    avg_cost: Optional[float] = None  # per share; None when the cost is not known
    multiplier: int = 1  # shares per unit of quantity: 100 for an option contract
    price: Optional[float] = None  # None when there is no price (options)
    # live: the market's current price. custodian: its last reported price,
    # kept where there is no live quote. None with no price at all.
    price_source: Optional[str] = None
    # Since the previous close, when the price is live.
    day_change: Optional[float] = None
    day_change_pct: Optional[float] = None
    cost_basis: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_gain: Optional[float] = None
    unrealized_gain_pct: Optional[float] = None
    is_short: bool


class OptionsCombined(BaseModel):
    """The custodian's value for the options listed without a price, together."""

    count: int
    market_value: float
    cost_basis: float  # premiums; negative for options written
    unrealized_gain: float


class AccountBalance(BaseModel):
    """What an account holds beyond its priced holdings, as the custodian
    last reported it. Holdings plus these is the custodian's account total."""

    account_id: str
    as_of: date
    cash_value: Optional[float] = None  # negative when money is borrowed
    # The custodian's value for the account's options together; None with none.
    options_value: Optional[float] = None
    # What those options cost (negative for premiums received), from the trade
    # history; value less this is their unrealised gain. None when not known.
    options_cost: Optional[float] = None


class PortalPositionsResponse(BaseModel):
    as_of: Optional[date] = None  # the custodian's holdings: quantity and cost
    # When the live prices shown were fetched; None when none are live.
    live_prices_at: Optional[datetime] = None
    count: int
    unpriced_count: int  # listed without a price of their own
    total_market_value: float
    total_cost_basis: float
    total_unrealized_gain: float
    total_unrealized_gain_pct: Optional[float] = None
    # Counted in the totals above when present.
    options: Optional[OptionsCombined] = None
    # Cash and options by account; not part of the totals above.
    account_balances: List[AccountBalance] = []
    positions: List[PortalPosition]


class PortalTrade(RowPlace):
    id: str
    trade_date: date
    symbol: str
    action: str  # BUY | SELL
    # assigned | expired when the row is an option ending that way, at no price
    event: Optional[str] = None
    security_type: str
    quantity: float
    price: float  # per share, also for an option
    multiplier: int = 1  # shares per unit of quantity: 100 for an option contract
    amount: float  # quantity x price x multiplier
    commission: float


class TradesAccount(BaseModel):
    """One account's share of the trades the filters match."""

    account_id: str
    account_name: str
    shared: bool
    total: int
    bought: float
    sold: float


class PortalTradesResponse(BaseModel):
    total: int
    skip: int
    limit: int
    bought: float
    sold: float
    net_invested: float
    # Each account with a matching trade, whatever page ``trades`` is on.
    accounts: List[TradesAccount] = []
    trades: List[PortalTrade]


class ActivityRow(RowPlace):
    """One thing that happened: a trade, or cash that moved."""

    id: str
    date: date
    # trade | deposit | withdrawal | transfer | dividend | interest |
    # margin_interest | fee | withholding | other
    kind: str
    label: str  # the row in a word or two: Bought, Deposit, Transfer in
    detail: Optional[str] = None  # the custodian's description, tidied
    symbol: Optional[str] = None
    # The rest describe a trade and are empty on a cash row.
    action: Optional[str] = None
    event: Optional[str] = None
    security_type: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    multiplier: Optional[int] = None
    # A trade's value, unsigned. A cash row's amount, signed: money arriving
    # in the account is positive.
    amount: float


class ActivityFigures(BaseModel):
    total: int  # rows matched
    trades: int
    bought: float
    sold: float
    money_in: float  # deposits and transfers in
    money_out: float  # withdrawals and transfers out, as a positive figure
    income: float  # dividends and interest
    charges: float  # margin interest, fees and tax withheld, positive


class ActivityAccount(ActivityFigures):
    account_id: str
    account_name: str
    shared: bool


class PortalActivityResponse(ActivityFigures):
    skip: int
    limit: int
    net_invested: float
    # Each account with a matching row, whatever page ``rows`` is on.
    accounts: List[ActivityAccount] = []
    rows: List[ActivityRow]


class PortalClosedLot(RowPlace):
    symbol: str
    security_type: str
    # assigned | expired for an option that ended that way. An assigned option
    # shows no gain: its premium is carried by the shares that changed hands.
    # marked: an index option still open at a year end, valued on that day.
    event: Optional[str] = None
    opened_at: Optional[date] = None
    closed_at: date
    days_held: Optional[int] = None
    # short (a year or less) | long | mixed: an index option, whose gain is
    # 60% long-term and 40% short-term whatever the time held.
    term: str
    quantity: Optional[float] = None
    multiplier: int = 1  # shares per unit of quantity: 100 for an option contract
    entry_price: Optional[float] = None  # per share, net of commission
    exit_price: Optional[float] = None
    # As the brokerage reports the lot. ``cost`` includes any earlier loss a
    # wash sale carried into these shares; ``disallowed_loss`` is the part of
    # this lot's loss carried into the shares that replaced it.
    cost: float
    proceeds: float
    disallowed_loss: float = 0
    short_term_gain: float = 0
    long_term_gain: float = 0
    realized_gain: float  # proceeds less cost, plus the disallowed loss
    realized_gain_pct: Optional[float] = None
    # wash | mark | unmarked | index_option | written_option
    adjustments: List[str] = []


class GainFigures(BaseModel):
    """Capital gains, and the income received, over one slice of the dates.
    ``realized`` is short-term plus long-term; income is never part of it."""

    count: int  # closed lots
    short_term: float
    long_term: float
    realized: float
    disallowed_loss: float
    dividends: float
    interest: float  # received
    margin_interest: float = 0  # paid on money borrowed; negative


class GainPeriod(GainFigures):
    period_start: date
    period_end: date


class GainSleeve(GainFigures):
    sleeve_id: str
    strategy_id: str
    strategy_name: str


class GainAccount(GainFigures):
    account_id: str
    account_name: str
    shared: bool
    sleeves: List[GainSleeve]


class PortalRealizedResponse(BaseModel):
    count: int
    net_realized: float
    short_term: float
    long_term: float
    gains: float
    losses: float
    cost: float = 0
    proceeds: float = 0
    disallowed_loss: float = 0
    # Received over the same dates; follows the dates, account and strategy
    # filters only. Not part of ``net_realized``.
    dividends: float = 0
    interest: float = 0
    margin_interest: float = 0  # paid on money borrowed; negative
    years: List[int]
    periods: List[GainPeriod] = []  # by month or quarter, newest first
    accounts: List[GainAccount] = []
    positions: List[PortalClosedLot]


class MonthFigure(BaseModel):
    year: int
    month: int
    twr_pct: Optional[float] = None


class PortalSummary(BaseModel):
    start: date
    end: date
    opening_value: float
    closing_value: float
    cash_value: Optional[float] = None
    net_flow: float
    gain: float
    twr_pct: Optional[float] = None
    mwr_pct: Optional[float] = None  # None for a single strategy
    benchmark_return_pct: Optional[float] = None
    # Set when the benchmark's price history starts after the window does:
    # its return (and the excess) is then measured from this date.
    benchmark_from: Optional[date] = None
    excess_return_pct: Optional[float] = None
    is_provisional: bool
    best_month: Optional[MonthFigure] = None
    worst_month: Optional[MonthFigure] = None
    months_up: int = 0
    months_total: int = 0


class CumulativePoint(BaseModel):
    date: date
    twr: Optional[float] = None
    mwr: Optional[float] = None
    benchmark: Optional[float] = None
    value: Optional[float] = None  # what it was worth that day


class PortalMonth(MonthFigure):
    is_provisional: bool


class PortalYear(BaseModel):
    year: int
    twr_pct: Optional[float] = None
    is_provisional: bool


class PortalPeriod(BaseModel):
    period_start: date
    period_end: date
    opening_value: float
    closing_value: float
    net_flow: float
    gain: float
    twr_pct: Optional[float] = None
    twr_ytd_pct: Optional[float] = None
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None
    is_provisional: bool


class BenchmarkChoice(BaseModel):
    code: str
    name: str
    # A fund's closes include its dividends; an index level leaves them out.
    includes_dividends: bool


class PortalPerformanceResponse(BaseModel):
    first_date: Optional[date] = None
    as_of: Optional[date] = None
    includes_cash: bool
    # The benchmark compared with, and those that may be chosen.
    benchmark: str
    benchmarks: List[BenchmarkChoice] = []
    grain: str
    summary: Optional[PortalSummary] = None
    series: List[CumulativePoint]
    months: List[PortalMonth]
    years: List[PortalYear]
    periods: List[PortalPeriod]


class OverviewSleeve(PortalSleeve):
    value: Optional[float] = None
    twr_pct: Optional[float] = None
    gain: Optional[float] = None


class OverviewAccount(BaseModel):
    id: str
    client_id: str
    name: str
    number_last4: Optional[str] = None
    shared: bool
    value: Optional[float] = None
    cash: Optional[float] = None
    twr_pct: Optional[float] = None  # year to date
    gain: Optional[float] = None  # year to date
    sleeves: List[OverviewSleeve]


class ValuePoint(BaseModel):
    date: date
    value: float


class ActivityItem(BaseModel):
    date: date
    kind: str  # BUY | SELL | DIVIDEND | INTEREST | FEE | WITHHOLDING
    symbol: Optional[str] = None
    quantity: Optional[float] = None
    amount: float
    account_name: str


class HomeHolding(BaseModel):
    symbol: str
    value: float
    day_change: Optional[float] = None  # today's move in dollars
    day_change_pct: Optional[float] = None
    share: Optional[float] = None  # of the total value, cash included


class HomeAllocation(BaseModel):
    kind: str  # stock | etf | option | other | cash
    value: float
    share: Optional[float] = None


class ExpiringOption(BaseModel):
    symbol: str
    account_name: str
    underlying: str
    kind: str  # put | call
    strike: float
    expiry: date
    days: int
    contracts: float
    written: bool
    underlying_price: Optional[float] = None
    # Positive when the shares are above the strike; None with no live price.
    above_strike_pct: Optional[float] = None


class TurningLongTerm(BaseModel):
    symbol: str
    date: date  # when its oldest short-term shares pass one year held


class PortalHomeResponse(BaseModel):
    """The home page. Value and the day's change are at live prices; the
    year's figures run through ``record_through``, the custodian's last day."""

    as_of: Optional[date] = None  # the custodian's holdings
    live_prices_at: Optional[datetime] = None
    record_through: Optional[date] = None
    is_provisional: bool
    total_value: float
    day_change: Optional[float] = None
    day_change_pct: Optional[float] = None
    ytd_twr_pct: Optional[float] = None
    benchmark: str
    benchmark_ytd_pct: Optional[float] = None
    excess_ytd_pct: Optional[float] = None
    # Over the whole record, which starts on ``first_date``.
    first_date: Optional[date] = None
    since_start_twr_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None  # largest fall from a high; negative
    allocation: List[HomeAllocation]
    cash_value: Optional[float] = None
    income_ytd: float  # dividends and interest
    realized_ytd: float
    realized_short_ytd: float
    realized_long_ytd: float
    added_ytd: Optional[float] = None  # deposits less withdrawals
    holdings_count: int
    top_holdings: List[HomeHolding]
    # The holdings that moved the total most today, in dollars; up to three each.
    movers_up: List[HomeHolding] = []
    movers_down: List[HomeHolding] = []
    expiring_options: List[ExpiringOption]
    carried_losses: float  # wash-sale losses in the cost of shares still held
    turning_long_term: List[TurningLongTerm]
    concentrated: List[HomeHolding]


class PortalOverviewResponse(BaseModel):
    as_of: Optional[date] = None
    includes_cash: bool
    total_value: Optional[float] = None
    cash_value: Optional[float] = None
    ytd_twr_pct: Optional[float] = None
    ytd_gain: Optional[float] = None
    ytd_realized: float
    is_provisional: bool
    accounts: List[OverviewAccount]
    timeseries: List[ValuePoint]
    recent: List[ActivityItem]
