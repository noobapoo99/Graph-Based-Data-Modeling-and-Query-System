"""Defines the canonical graph schema exposed to the LLM and API."""

SCHEMA = {
    "nodes": [
        "Customer",
        "Order",
        "Product",
        "Delivery",
        "Invoice",
        "Payment",
        "JournalEntry",
    ],
    "relationships": [
        "PLACED",
        "CONTAINS",
        "FULFILLED_BY",
        "BILLED_AS",
        "SETTLED_BY",
        "RECORDED_IN",
    ],
    "properties": {
        "Customer": ["id", "name", "region"],
        "Order": ["id", "date", "status", "total_amount"],
        "Product": ["id", "name", "category", "unit_price"],
        "Delivery": ["id", "date", "status"],
        "Invoice": ["id", "date", "amount", "status"],
        "Payment": ["id", "date", "amount", "method"],
        "JournalEntry": ["id", "date", "debit", "credit"],
    },
}
