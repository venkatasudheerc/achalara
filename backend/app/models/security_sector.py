"""The sector of each symbol the app holds, copied from market data"""
from sqlalchemy import Column, DateTime, String

from app.models.base import BaseModel


class SecuritySector(BaseModel):
    """A held symbol's sector and name, as market data last said them.

    The portal's sector view reads this copy and never market data itself, so
    it works whether or not market data can be reached (``md`` shares no tables
    with the app). The daily job ``sector_copy`` fills it through
    ``app.md.read``. A symbol market data has no sector for keeps a row with
    no ``sector_code``, so "not classified" is known rather than assumed. It
    names a symbol, never a client or an account.
    """

    __tablename__ = "security_sectors"

    symbol = Column(String(30), primary_key=True)  # the app's spelling
    # stock | etf | adr | fund | preferred | other; empty when market data does not know it
    kind = Column(String(20))
    sector_code = Column(String(4))  # IT, HC, FIN, ...
    sector_name = Column(String(40))
    # The security's name as market data has it (SEC style); None while it has none.
    name = Column(String(200))
    refreshed_at = Column(DateTime(timezone=True), nullable=False)
