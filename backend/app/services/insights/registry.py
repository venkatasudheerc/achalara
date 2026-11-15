"""The one list of rules. Add a rule here, never in a route or on a screen."""
from app.services.insights.rules.balance import AssetsAndOwed
from app.services.insights.rules.cards import CardDueSoon, CardOverdue, CardsOwedOfLimits
from app.services.insights.rules.cash import IdleCash
from app.services.insights.rules.markets import CashAndMarket
from app.services.insights.rules.connections import (
    AccountsWaiting, ConsentEnding, LoginNeedsSignIn, RecordIncomplete,
)
from app.services.insights.rules.investments import (
    CarriedLosses, Concentration, OptionsExpiring, TurningLongTerm,
)

RULES = [
    LoginNeedsSignIn(), RecordIncomplete(), CardOverdue(), CardDueSoon(), ConsentEnding(),
    AccountsWaiting(), IdleCash(),
    CashAndMarket(), Concentration(), AssetsAndOwed(), CardsOwedOfLimits(), OptionsExpiring(),
    TurningLongTerm(), CarriedLosses(),
]
