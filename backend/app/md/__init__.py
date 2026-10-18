"""Market data (the ``md`` schema): securities, index membership, and later
prices, classification and fundamentals.

Reference data that belongs to no client. Its jobs run in their own worker
process (``python -m app.md.worker``), never in the web process.
"""
