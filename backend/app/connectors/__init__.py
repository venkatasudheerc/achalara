"""Bridge — the connector layer.

Brings trade and position data into Achalara from any source (CSV, Google
Sheets, Webull, and future brokers). See ``CONNECTORS.md`` for the rules.

The one rule: nothing outside this package may import a vendor SDK or know a
vendor's name. Everything crossing the boundary speaks the normalized types in
``connectors.models``.
"""
