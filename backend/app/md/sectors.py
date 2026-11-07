"""The 11 GICS sectors, and how each source's words map onto them."""
from typing import Optional

# code, name, display order
SECTORS = [
    ("COM", "Communication Services", 1),
    ("CD", "Consumer Discretionary", 2),
    ("CS", "Consumer Staples", 3),
    ("EN", "Energy", 4),
    ("FIN", "Financials", 5),
    ("HC", "Health Care", 6),
    ("IND", "Industrials", 7),
    ("IT", "Information Technology", 8),
    ("MAT", "Materials", 9),
    ("RE", "Real Estate", 10),
    ("UT", "Utilities", 11),
]

# The sector column of iShares holdings files (official GICS, slightly shortened).
_ISHARES = {
    "communication": "COM",
    "communication services": "COM",
    "consumer discretionary": "CD",
    "consumer staples": "CS",
    "energy": "EN",
    "financials": "FIN",
    "health care": "HC",
    "industrials": "IND",
    "information technology": "IT",
    "materials": "MAT",
    "real estate": "RE",
    "utilities": "UT",
}


def ishares_sector(name: Optional[str]) -> Optional[str]:
    return _ISHARES.get((name or "").strip().lower())


# SEC SIC codes to GICS sectors: a coarse fallback for companies that are in no
# index file and have no Webull industry. Ranges are inclusive; the first match
# wins, so the narrow exceptions come before the broad groups.
_SIC_RANGES = [
    (2830, 2836, "HC"),  # drugs
    (3570, 3579, "IT"),  # computers
    (3630, 3639, "CD"),  # household appliances
    (3710, 3716, "CD"),  # motor vehicles
    (3840, 3851, "HC"),  # medical instruments
    (5400, 5499, "CS"),  # food stores
    (5912, 5912, "CS"),  # drug stores
    (6798, 6798, "RE"),  # REITs
    (7370, 7379, "IT"),  # software and IT services
    (100, 999, "CS"),  # agriculture
    (1000, 1099, "MAT"),  # metal mining
    (1200, 1399, "EN"),  # coal, oil and gas
    (1400, 1499, "MAT"),  # other mining
    (1500, 1799, "IND"),  # construction
    (2000, 2199, "CS"),  # food, tobacco
    (2200, 2399, "CD"),  # textiles, apparel
    (2400, 2499, "MAT"),  # lumber
    (2500, 2599, "CD"),  # furniture
    (2600, 2699, "MAT"),  # paper
    (2700, 2799, "COM"),  # publishing
    (2800, 2899, "MAT"),  # chemicals
    (2900, 2999, "EN"),  # petroleum refining
    (3000, 3099, "MAT"),  # rubber, plastics
    (3100, 3199, "CD"),  # leather
    (3200, 3399, "MAT"),  # stone, glass, metals
    (3400, 3599, "IND"),  # fabricated metal, machinery
    (3600, 3699, "IT"),  # electronic equipment
    (3700, 3799, "IND"),  # transport equipment
    (3800, 3899, "IT"),  # instruments
    (3900, 3999, "CD"),  # other manufacturing
    (4000, 4799, "IND"),  # transportation
    (4800, 4899, "COM"),  # communications
    (4900, 4999, "UT"),  # utilities
    (5000, 5099, "IND"),  # wholesale, durable
    (5100, 5199, "CS"),  # wholesale, non-durable
    (5200, 5999, "CD"),  # retail
    (6000, 6499, "FIN"),  # banks, credit, brokers, insurance
    (6500, 6599, "RE"),  # real estate
    (6700, 6799, "FIN"),  # holding and investment companies
    (7000, 7099, "CD"),  # hotels
    (7200, 7299, "CD"),  # personal services
    (7300, 7399, "IND"),  # business services
    (7500, 7599, "CD"),  # auto services
    (7800, 7999, "COM"),  # entertainment
    (8000, 8099, "HC"),  # health services
    (8200, 8299, "CD"),  # education
    (8700, 8799, "IND"),  # engineering, management
]


def sic_sector(sic: Optional[str]) -> Optional[str]:
    try:
        code = int(sic or "")
    except ValueError:
        return None
    for low, high, sector in _SIC_RANGES:
        if low <= code <= high:
            return sector
    return None
