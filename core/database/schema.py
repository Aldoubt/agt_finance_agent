"""Database schema definition.

The schema follows the purchase relationship graph:
Document -> Order -> Item -> Invoice/Payment/Photo

The first implementation keeps the model lightweight and can later
be migrated to SQLAlchemy.
"""

TABLES = {
    "documents": [
        "id",
        "path",
        "document_type",
        "confidence",
    ],
    "orders": [
        "id",
        "platform",
        "merchant",
        "order_time",
        "amount",
    ],
    "items": [
        "id",
        "name",
        "quantity",
        "amount",
    ],
    "invoices": [
        "id",
        "invoice_no",
        "supplier",
        "amount",
    ],
    "payments": [
        "id",
        "payment_time",
        "amount",
        "platform",
    ],
    "relations": [
        "source_id",
        "target_id",
        "relation_type",
        "confidence",
    ],
}
