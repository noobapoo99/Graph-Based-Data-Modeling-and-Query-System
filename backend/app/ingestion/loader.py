"""Loads business data into Neo4j from Stage 1 CSV files or the repository's SAP JSONL fallback."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.database.neo4j_client import _run_write_query, create_indexes
from app.utils.logger import log


EXPECTED_CSV_FILES = [
    "customers.csv",
    "orders.csv",
    "products.csv",
    "deliveries.csv",
    "invoices.csv",
    "payments.csv",
    "journal_entries.csv",
]
BATCH_SIZE = 250


# Returns a consistent zero-count payload because callers should not need special handling when no source data is available.
def _empty_counts() -> dict[str, int]:
    return {
        "customers": 0,
        "orders": 0,
        "products": 0,
        "deliveries": 0,
        "invoices": 0,
        "payments": 0,
        "journal_entries": 0,
        "placed_relationships": 0,
        "contains_relationships": 0,
        "fulfilled_relationships": 0,
        "billed_relationships": 0,
        "settled_relationships": 0,
        "recorded_relationships": 0,
    }


# Normalizes arbitrary values into strings because Neo4j node identifiers and relationship endpoints must stay type-stable.
def _stringify(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value).strip()


# Parses numeric values because CSV and JSONL business data often store amounts as strings.
def _parse_float(value: Any) -> float:
    text = _stringify(value)
    if not text:
        return 0.0

    try:
        return float(text.replace(",", ""))
    except ValueError:
        return 0.0


# Extracts a simple date string because date-only values are easier to query and display than full timestamps.
def _parse_date(value: Any) -> str | None:
    text = _stringify(value)
    if not text:
        return None
    return text[:10]


# Returns the first populated column because real-world data files often vary in naming across sources.
def _choose_value(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = _stringify(row.get(key))
        if value:
            return value
    return default


# Splits multi-value reference columns because some CSVs encode several related IDs in one field.
def _split_related_ids(value: Any) -> list[str]:
    text = _stringify(value)
    if not text:
        return []

    normalized = text
    for separator in ["|", ";"]:
        normalized = normalized.replace(separator, ",")

    return [part.strip() for part in normalized.split(",") if part.strip()]


# Breaks large write payloads into batches because Neo4j performs better with moderate UNWIND sizes than one giant transaction.
def _chunk_rows(rows: list[dict[str, Any]], batch_size: int = BATCH_SIZE) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), batch_size):
        yield rows[index : index + batch_size]


# Reads one CSV file because Stage 1 ingestion is defined around explicit entity CSVs in a data directory.
def _read_csv_rows(file_path: Path) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []

    dataframe = pd.read_csv(file_path, dtype=str).fillna("")
    return dataframe.to_dict(orient="records")


# Reads every JSONL file from one folder because the current repository stores fallback demo data as partitioned JSONL extracts.
def _read_jsonl_folder(folder_path: Path) -> list[dict[str, Any]]:
    if not folder_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for file_path in sorted(folder_path.glob("*.jsonl")):
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


# Deduplicates and validates relationship endpoints because missing node IDs should not create partial graph edges.
def _filter_relationships(
    rows: list[dict[str, str]],
    source_ids: set[str],
    target_ids: set[str],
) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for row in rows:
        source = _stringify(row.get("source"))
        target = _stringify(row.get("target"))
        pair = (source, target)
        if not source or not target or pair in seen_pairs:
            continue
        if source not in source_ids or target not in target_ids:
            continue
        seen_pairs.add(pair)
        filtered.append({"source": source, "target": target})

    return filtered


# Upserts nodes with MERGE because Stage 1 ingestion must be idempotent across repeated local and container runs.
def _upsert_nodes(label: str, rows: list[dict[str, Any]], request_id: str) -> None:
    if not rows:
        return

    cypher = f"""
    UNWIND $rows AS row
    MERGE (n:{label} {{id: row.id}})
    SET n += row
    """

    for batch in _chunk_rows(rows):
        _run_write_query(cypher, {"rows": batch}, timeout=60)

    log("loader.nodes_upserted", request_id, label=label, count=len(rows))


# Upserts relationships with MERGE because repeated loads must not duplicate edges between the same business entities.
def _upsert_relationships(
    source_label: str,
    relationship_type: str,
    target_label: str,
    rows: list[dict[str, str]],
    request_id: str,
) -> None:
    if not rows:
        return

    cypher = f"""
    UNWIND $rows AS row
    MATCH (source:{source_label} {{id: row.source}})
    MATCH (target:{target_label} {{id: row.target}})
    MERGE (source)-[:{relationship_type}]->(target)
    """

    for batch in _chunk_rows(rows):
        _run_write_query(cypher, {"rows": batch}, timeout=60)

    log(
        "loader.relationships_upserted",
        request_id,
        relationship_type=relationship_type,
        count=len(rows),
    )


# Logs skipped rows because ingestion should be transparent when bad source rows are dropped for missing primary keys.
def _log_skipped(entity: str, request_id: str, skipped_rows: int) -> None:
    log("loader.skipped_rows", request_id, entity=entity, skipped_rows=skipped_rows)


# Loads Customer nodes from customers.csv because customer master data anchors order-to-cash flows.
def load_customers(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "customers.csv")
    nodes: list[dict[str, Any]] = []
    skipped_rows = 0

    for row in rows:
        customer_id = _choose_value(row, ["id", "customer_id", "customerId"])
        if not customer_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": customer_id,
                "name": _choose_value(row, ["name", "customer_name", "customerName"]),
                "region": _choose_value(row, ["region", "customer_region", "customerRegion"]),
            }
        )

    _log_skipped("customers", request_id, skipped_rows)
    return {"nodes": nodes}


# Loads Order nodes and Customer-to-Order links from orders.csv because orders connect customer demand to the downstream flow.
def load_orders(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "orders.csv")
    nodes: list[dict[str, Any]] = []
    placed_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        order_id = _choose_value(row, ["id", "order_id", "orderId"])
        if not order_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": order_id,
                "date": _parse_date(_choose_value(row, ["date", "order_date", "orderDate"])),
                "status": _choose_value(row, ["status", "order_status", "orderStatus"]),
                "total_amount": round(
                    _parse_float(_choose_value(row, ["total_amount", "amount", "totalAmount"])),
                    2,
                ),
            }
        )

        customer_id = _choose_value(
            row,
            ["customer_id", "customerId", "customer", "customer_ref"],
        )
        if customer_id:
            placed_relationships.append({"source": customer_id, "target": order_id})

    _log_skipped("orders", request_id, skipped_rows)
    return {"nodes": nodes, "placed_relationships": placed_relationships}


# Loads Product nodes and Order-to-Product links from products.csv because products let users ask what each order contains.
def load_products(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "products.csv")
    nodes: list[dict[str, Any]] = []
    contains_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        product_id = _choose_value(row, ["id", "product_id", "productId"])
        if not product_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": product_id,
                "name": _choose_value(row, ["name", "product_name", "productName"]),
                "category": _choose_value(row, ["category", "product_category", "productCategory"]),
                "unit_price": round(
                    _parse_float(_choose_value(row, ["unit_price", "price", "unitPrice"])),
                    2,
                ),
            }
        )

        related_order_ids = _split_related_ids(
            _choose_value(
                row,
                ["order_id", "order_ids", "orderId", "sales_order", "salesOrder"],
            )
        )
        for order_id in related_order_ids:
            contains_relationships.append({"source": order_id, "target": product_id})

    _log_skipped("products", request_id, skipped_rows)
    return {"nodes": nodes, "contains_relationships": contains_relationships}


# Loads Delivery nodes and Order-to-Delivery links from deliveries.csv because fulfillment is a core business flow stage.
def load_deliveries(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "deliveries.csv")
    nodes: list[dict[str, Any]] = []
    fulfilled_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        delivery_id = _choose_value(row, ["id", "delivery_id", "deliveryId"])
        if not delivery_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": delivery_id,
                "date": _parse_date(_choose_value(row, ["date", "delivery_date", "deliveryDate"])),
                "status": _choose_value(row, ["status", "delivery_status", "deliveryStatus"]),
            }
        )

        related_order_ids = _split_related_ids(
            _choose_value(row, ["order_id", "order_ids", "orderId", "source_order_id"])
        )
        for order_id in related_order_ids:
            fulfilled_relationships.append({"source": order_id, "target": delivery_id})

    _log_skipped("deliveries", request_id, skipped_rows)
    return {"nodes": nodes, "fulfilled_relationships": fulfilled_relationships}


# Loads Invoice nodes and Delivery-to-Invoice links from invoices.csv because invoices represent the billing stage of the flow.
def load_invoices(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "invoices.csv")
    nodes: list[dict[str, Any]] = []
    billed_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        invoice_id = _choose_value(row, ["id", "invoice_id", "invoiceId"])
        if not invoice_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": invoice_id,
                "date": _parse_date(_choose_value(row, ["date", "invoice_date", "invoiceDate"])),
                "amount": round(
                    _parse_float(_choose_value(row, ["amount", "invoice_amount", "invoiceAmount"])),
                    2,
                ),
                "status": _choose_value(row, ["status", "invoice_status", "invoiceStatus"]),
            }
        )

        related_delivery_ids = _split_related_ids(
            _choose_value(row, ["delivery_id", "delivery_ids", "deliveryId", "source_delivery_id"])
        )
        for delivery_id in related_delivery_ids:
            billed_relationships.append({"source": delivery_id, "target": invoice_id})

    _log_skipped("invoices", request_id, skipped_rows)
    return {"nodes": nodes, "billed_relationships": billed_relationships}


# Loads Payment nodes and Invoice-to-Payment links from payments.csv because payment completion is needed for broken-flow detection.
def load_payments(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "payments.csv")
    nodes: list[dict[str, Any]] = []
    settled_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        payment_id = _choose_value(row, ["id", "payment_id", "paymentId"])
        if not payment_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": payment_id,
                "date": _parse_date(_choose_value(row, ["date", "payment_date", "paymentDate"])),
                "amount": round(
                    _parse_float(_choose_value(row, ["amount", "payment_amount", "paymentAmount"])),
                    2,
                ),
                "method": _choose_value(row, ["method", "payment_method", "paymentMethod"]),
            }
        )

        related_invoice_ids = _split_related_ids(
            _choose_value(row, ["invoice_id", "invoice_ids", "invoiceId", "source_invoice_id"])
        )
        for invoice_id in related_invoice_ids:
            settled_relationships.append({"source": invoice_id, "target": payment_id})

    _log_skipped("payments", request_id, skipped_rows)
    return {"nodes": nodes, "settled_relationships": settled_relationships}


# Loads JournalEntry nodes and Invoice-to-JournalEntry links because the graph must support accounting traceability.
def load_journal_entries(data_dir: Path, request_id: str) -> dict[str, Any]:
    rows = _read_csv_rows(data_dir / "journal_entries.csv")
    nodes: list[dict[str, Any]] = []
    recorded_relationships: list[dict[str, str]] = []
    skipped_rows = 0

    for row in rows:
        journal_id = _choose_value(row, ["id", "journal_entry_id", "journalEntryId"])
        if not journal_id:
            skipped_rows += 1
            continue

        nodes.append(
            {
                "id": journal_id,
                "date": _parse_date(
                    _choose_value(row, ["date", "journal_date", "journalDate", "posting_date"])
                ),
                "debit": round(
                    _parse_float(_choose_value(row, ["debit", "debit_amount", "debitAmount"])),
                    2,
                ),
                "credit": round(
                    _parse_float(_choose_value(row, ["credit", "credit_amount", "creditAmount"])),
                    2,
                ),
            }
        )

        related_invoice_ids = _split_related_ids(
            _choose_value(row, ["invoice_id", "invoice_ids", "invoiceId", "source_invoice_id"])
        )
        for invoice_id in related_invoice_ids:
            recorded_relationships.append({"source": invoice_id, "target": journal_id})

    _log_skipped("journal_entries", request_id, skipped_rows)
    return {"nodes": nodes, "recorded_relationships": recorded_relationships}


# Normalizes SAP order status because the raw JSONL extract uses system codes that are not friendly for querying.
def _normalize_order_status(row: dict[str, Any]) -> str:
    if _choose_value(row, ["deliveryBlockReason", "headerBillingBlockReason"]):
        return "BLOCKED"
    if row.get("overallDeliveryStatus") == "C" and row.get("overallOrdReltdBillgStatus") == "C":
        return "COMPLETED"
    if row.get("overallOrdReltdBillgStatus") == "C":
        return "BILLED"
    if row.get("overallDeliveryStatus") == "C":
        return "DELIVERED"
    if row.get("overallDeliveryStatus") == "B":
        return "PARTIALLY_DELIVERED"
    return "OPEN"


# Normalizes SAP delivery status because the graph should expose operator-friendly state instead of source-specific codes.
def _normalize_delivery_status(row: dict[str, Any]) -> str:
    if row.get("overallGoodsMovementStatus") == "C":
        return "COMPLETED"
    if row.get("overallGoodsMovementStatus") == "B":
        return "IN_TRANSIT"
    if row.get("overallPickingStatus") == "C":
        return "PICKED"
    return "PENDING"


# Builds approximate product prices because the raw product master fallback data does not contain ready-to-query unit prices.
def _build_unit_price_map(
    order_items: list[dict[str, Any]],
    billing_items: list[dict[str, Any]],
) -> dict[str, float]:
    price_samples: dict[str, list[float]] = defaultdict(list)

    for row in order_items:
        product_id = _choose_value(row, ["material"])
        quantity = _parse_float(row.get("requestedQuantity"))
        amount = _parse_float(row.get("netAmount"))
        if product_id and quantity > 0 and amount > 0:
            price_samples[product_id].append(round(amount / quantity, 2))

    for row in billing_items:
        product_id = _choose_value(row, ["material"])
        quantity = _parse_float(row.get("billingQuantity"))
        amount = _parse_float(row.get("netAmount"))
        if product_id and quantity > 0 and amount > 0 and product_id not in price_samples:
            price_samples[product_id].append(round(amount / quantity, 2))

    return {
        product_id: round(sum(values) / len(values), 2)
        for product_id, values in price_samples.items()
        if values
    }


# Builds fallback Payment nodes because the SAP AR extract groups settlement information across multiple accounting rows.
def _build_jsonl_payment_nodes(payment_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    grouped: dict[str, dict[str, Any]] = {}
    invoice_to_payment: dict[str, str] = {}

    for row in payment_rows:
        payment_id = _choose_value(row, ["clearingAccountingDocument"])
        accounting_document = _choose_value(row, ["accountingDocument"])
        if not payment_id or payment_id == "0":
            continue

        group = grouped.setdefault(
            payment_id,
            {
                "dates": [],
                "positive_total": 0.0,
                "negative_total": 0.0,
                "methods": set(),
            },
        )

        amount = _parse_float(row.get("amountInTransactionCurrency"))
        group["dates"].append(_parse_date(row.get("clearingDate") or row.get("postingDate")))
        group["methods"].add(_choose_value(row, ["financialAccountType"], default="UNKNOWN"))
        if amount < 0:
            group["negative_total"] += abs(amount)
        else:
            group["positive_total"] += amount

        if accounting_document and accounting_document != payment_id:
            invoice_to_payment[accounting_document] = payment_id

    nodes: list[dict[str, Any]] = []
    for payment_id, group in grouped.items():
        amount = group["negative_total"] or group["positive_total"]
        nodes.append(
            {
                "id": payment_id,
                "date": next((date for date in group["dates"] if date), None),
                "amount": round(amount, 2),
                "method": sorted(group["methods"])[0] if group["methods"] else "UNKNOWN",
            }
        )

    return nodes, invoice_to_payment


# Builds fallback JournalEntry nodes because accounting documents can span several raw line items in the SAP extract.
def _build_jsonl_journal_nodes(journal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in journal_rows:
        journal_id = _choose_value(row, ["accountingDocument"])
        if not journal_id:
            continue

        group = grouped.setdefault(
            journal_id,
            {
                "date": _parse_date(row.get("postingDate") or row.get("documentDate")),
                "debit": 0.0,
                "credit": 0.0,
            },
        )

        amount = _parse_float(row.get("amountInTransactionCurrency"))
        if amount >= 0:
            group["debit"] += amount
        else:
            group["credit"] += abs(amount)

    return [
        {
            "id": journal_id,
            "date": payload["date"],
            "debit": round(payload["debit"], 2),
            "credit": round(payload["credit"], 2),
        }
        for journal_id, payload in grouped.items()
    ]


# Loads the current repository's JSONL fallback because `docker-compose up` should work even before Stage 1 CSV files exist.
def _load_from_jsonl(data_dir: Path, request_id: str) -> dict[str, int]:
    business_partners = _read_jsonl_folder(data_dir / "business_partners")
    addresses = _read_jsonl_folder(data_dir / "business_partner_addresses")
    order_headers = _read_jsonl_folder(data_dir / "sales_order_headers")
    order_items = _read_jsonl_folder(data_dir / "sales_order_items")
    delivery_headers = _read_jsonl_folder(data_dir / "outbound_delivery_headers")
    delivery_items = _read_jsonl_folder(data_dir / "outbound_delivery_items")
    billing_headers = _read_jsonl_folder(data_dir / "billing_document_headers")
    billing_items = _read_jsonl_folder(data_dir / "billing_document_items")
    payment_rows = _read_jsonl_folder(data_dir / "payments_accounts_receivable")
    journal_rows = _read_jsonl_folder(data_dir / "journal_entry_items_accounts_receivable")
    product_rows = _read_jsonl_folder(data_dir / "products")
    description_rows = _read_jsonl_folder(data_dir / "product_descriptions")

    address_by_partner = {
        _choose_value(row, ["businessPartner"]): row
        for row in addresses
        if _choose_value(row, ["businessPartner"])
    }
    description_by_product = {
        _choose_value(row, ["product"]): row
        for row in description_rows
        if _choose_value(row, ["product"]) and _choose_value(row, ["language"], default="EN").upper() == "EN"
    }
    unit_prices = _build_unit_price_map(order_items, billing_items)
    payment_nodes, invoice_to_payment = _build_jsonl_payment_nodes(payment_rows)
    journal_nodes = _build_jsonl_journal_nodes(journal_rows)

    customers: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    invoices: list[dict[str, Any]] = []

    placed_relationships: list[dict[str, str]] = []
    contains_relationships: list[dict[str, str]] = []
    fulfilled_relationships: list[dict[str, str]] = []
    billed_relationships: list[dict[str, str]] = []
    settled_relationships: list[dict[str, str]] = []
    recorded_relationships: list[dict[str, str]] = []

    for row in business_partners:
        customer_id = _choose_value(row, ["customer", "businessPartner"])
        if not customer_id:
            continue

        address = address_by_partner.get(customer_id, {})
        customers.append(
            {
                "id": customer_id,
                "name": _choose_value(
                    row,
                    ["businessPartnerFullName", "organizationBpName1", "businessPartnerName"],
                    default=customer_id,
                ),
                "region": _choose_value(address, ["region", "country"], default="UNKNOWN"),
            }
        )

    for row in order_headers:
        order_id = _choose_value(row, ["salesOrder"])
        if not order_id:
            continue

        orders.append(
            {
                "id": order_id,
                "date": _parse_date(row.get("creationDate")),
                "status": _normalize_order_status(row),
                "total_amount": round(_parse_float(row.get("totalNetAmount")), 2),
            }
        )

        customer_id = _choose_value(row, ["soldToParty"])
        if customer_id:
            placed_relationships.append({"source": customer_id, "target": order_id})

    for row in product_rows:
        product_id = _choose_value(row, ["product"])
        if not product_id:
            continue

        description = description_by_product.get(product_id, {})
        products.append(
            {
                "id": product_id,
                "name": _choose_value(
                    description,
                    ["productDescription"],
                    default=_choose_value(row, ["productOldId"], default=product_id),
                ),
                "category": _choose_value(row, ["productGroup", "productType"], default="UNCATEGORIZED"),
                "unit_price": round(unit_prices.get(product_id, 0.0), 2),
            }
        )

    for row in order_items:
        order_id = _choose_value(row, ["salesOrder"])
        product_id = _choose_value(row, ["material"])
        if order_id and product_id:
            contains_relationships.append({"source": order_id, "target": product_id})

    for row in delivery_headers:
        delivery_id = _choose_value(row, ["deliveryDocument"])
        if not delivery_id:
            continue

        deliveries.append(
            {
                "id": delivery_id,
                "date": _parse_date(row.get("actualGoodsMovementDate") or row.get("creationDate")),
                "status": _normalize_delivery_status(row),
            }
        )

    for row in delivery_items:
        order_id = _choose_value(row, ["referenceSdDocument"])
        delivery_id = _choose_value(row, ["deliveryDocument"])
        if order_id and delivery_id:
            fulfilled_relationships.append({"source": order_id, "target": delivery_id})

    for row in billing_headers:
        invoice_id = _choose_value(row, ["billingDocument"])
        if not invoice_id:
            continue

        accounting_document = _choose_value(row, ["accountingDocument"])
        status = "CANCELLED" if row.get("billingDocumentIsCancelled") else "OPEN"
        if status != "CANCELLED" and accounting_document in invoice_to_payment:
            status = "PAID"

        invoices.append(
            {
                "id": invoice_id,
                "date": _parse_date(row.get("billingDocumentDate") or row.get("creationDate")),
                "amount": round(_parse_float(row.get("totalNetAmount")), 2),
                "status": status,
            }
        )

        payment_id = invoice_to_payment.get(accounting_document)
        if payment_id:
            settled_relationships.append({"source": invoice_id, "target": payment_id})

        if accounting_document:
            recorded_relationships.append({"source": invoice_id, "target": accounting_document})

    for row in billing_items:
        delivery_id = _choose_value(row, ["referenceSdDocument"])
        invoice_id = _choose_value(row, ["billingDocument"])
        if delivery_id and invoice_id:
            billed_relationships.append({"source": delivery_id, "target": invoice_id})

    customer_ids = {row["id"] for row in customers}
    order_ids = {row["id"] for row in orders}
    product_ids = {row["id"] for row in products}
    delivery_ids = {row["id"] for row in deliveries}
    invoice_ids = {row["id"] for row in invoices}
    payment_ids = {row["id"] for row in payment_nodes}
    journal_ids = {row["id"] for row in journal_nodes}

    placed_relationships = _filter_relationships(placed_relationships, customer_ids, order_ids)
    contains_relationships = _filter_relationships(contains_relationships, order_ids, product_ids)
    fulfilled_relationships = _filter_relationships(fulfilled_relationships, order_ids, delivery_ids)
    billed_relationships = _filter_relationships(billed_relationships, delivery_ids, invoice_ids)
    settled_relationships = _filter_relationships(settled_relationships, invoice_ids, payment_ids)
    recorded_relationships = _filter_relationships(recorded_relationships, invoice_ids, journal_ids)

    _upsert_nodes("Customer", customers, request_id)
    _upsert_nodes("Order", orders, request_id)
    _upsert_nodes("Product", products, request_id)
    _upsert_nodes("Delivery", deliveries, request_id)
    _upsert_nodes("Invoice", invoices, request_id)
    _upsert_nodes("Payment", payment_nodes, request_id)
    _upsert_nodes("JournalEntry", journal_nodes, request_id)

    _upsert_relationships("Customer", "PLACED", "Order", placed_relationships, request_id)
    _upsert_relationships("Order", "CONTAINS", "Product", contains_relationships, request_id)
    _upsert_relationships("Order", "FULFILLED_BY", "Delivery", fulfilled_relationships, request_id)
    _upsert_relationships("Delivery", "BILLED_AS", "Invoice", billed_relationships, request_id)
    _upsert_relationships("Invoice", "SETTLED_BY", "Payment", settled_relationships, request_id)
    _upsert_relationships("Invoice", "RECORDED_IN", "JournalEntry", recorded_relationships, request_id)

    counts = {
        "customers": len(customers),
        "orders": len(orders),
        "products": len(products),
        "deliveries": len(deliveries),
        "invoices": len(invoices),
        "payments": len(payment_nodes),
        "journal_entries": len(journal_nodes),
        "placed_relationships": len(placed_relationships),
        "contains_relationships": len(contains_relationships),
        "fulfilled_relationships": len(fulfilled_relationships),
        "billed_relationships": len(billed_relationships),
        "settled_relationships": len(settled_relationships),
        "recorded_relationships": len(recorded_relationships),
    }
    log("loader.complete", request_id, source="jsonl", **counts)
    return counts


# Loads the Stage 1 CSV graph because this is the primary ingestion contract for the production-ready backend.
def _load_from_csv(data_dir: Path, request_id: str) -> dict[str, int]:
    customers_payload = load_customers(data_dir, request_id)
    orders_payload = load_orders(data_dir, request_id)
    products_payload = load_products(data_dir, request_id)
    deliveries_payload = load_deliveries(data_dir, request_id)
    invoices_payload = load_invoices(data_dir, request_id)
    payments_payload = load_payments(data_dir, request_id)
    journals_payload = load_journal_entries(data_dir, request_id)

    customer_nodes = customers_payload["nodes"]
    order_nodes = orders_payload["nodes"]
    product_nodes = products_payload["nodes"]
    delivery_nodes = deliveries_payload["nodes"]
    invoice_nodes = invoices_payload["nodes"]
    payment_nodes = payments_payload["nodes"]
    journal_nodes = journals_payload["nodes"]

    customer_ids = {row["id"] for row in customer_nodes}
    order_ids = {row["id"] for row in order_nodes}
    product_ids = {row["id"] for row in product_nodes}
    delivery_ids = {row["id"] for row in delivery_nodes}
    invoice_ids = {row["id"] for row in invoice_nodes}
    payment_ids = {row["id"] for row in payment_nodes}
    journal_ids = {row["id"] for row in journal_nodes}

    placed_relationships = _filter_relationships(
        orders_payload["placed_relationships"],
        customer_ids,
        order_ids,
    )
    contains_relationships = _filter_relationships(
        products_payload["contains_relationships"],
        order_ids,
        product_ids,
    )
    fulfilled_relationships = _filter_relationships(
        deliveries_payload["fulfilled_relationships"],
        order_ids,
        delivery_ids,
    )
    billed_relationships = _filter_relationships(
        invoices_payload["billed_relationships"],
        delivery_ids,
        invoice_ids,
    )
    settled_relationships = _filter_relationships(
        payments_payload["settled_relationships"],
        invoice_ids,
        payment_ids,
    )
    recorded_relationships = _filter_relationships(
        journals_payload["recorded_relationships"],
        invoice_ids,
        journal_ids,
    )

    _upsert_nodes("Customer", customer_nodes, request_id)
    _upsert_nodes("Order", order_nodes, request_id)
    _upsert_nodes("Product", product_nodes, request_id)
    _upsert_nodes("Delivery", delivery_nodes, request_id)
    _upsert_nodes("Invoice", invoice_nodes, request_id)
    _upsert_nodes("Payment", payment_nodes, request_id)
    _upsert_nodes("JournalEntry", journal_nodes, request_id)

    _upsert_relationships("Customer", "PLACED", "Order", placed_relationships, request_id)
    _upsert_relationships("Order", "CONTAINS", "Product", contains_relationships, request_id)
    _upsert_relationships("Order", "FULFILLED_BY", "Delivery", fulfilled_relationships, request_id)
    _upsert_relationships("Delivery", "BILLED_AS", "Invoice", billed_relationships, request_id)
    _upsert_relationships("Invoice", "SETTLED_BY", "Payment", settled_relationships, request_id)
    _upsert_relationships("Invoice", "RECORDED_IN", "JournalEntry", recorded_relationships, request_id)

    counts = {
        "customers": len(customer_nodes),
        "orders": len(order_nodes),
        "products": len(product_nodes),
        "deliveries": len(delivery_nodes),
        "invoices": len(invoice_nodes),
        "payments": len(payment_nodes),
        "journal_entries": len(journal_nodes),
        "placed_relationships": len(placed_relationships),
        "contains_relationships": len(contains_relationships),
        "fulfilled_relationships": len(fulfilled_relationships),
        "billed_relationships": len(billed_relationships),
        "settled_relationships": len(settled_relationships),
        "recorded_relationships": len(recorded_relationships),
    }
    log("loader.complete", request_id, source="csv", **counts)
    return counts


# Detects whether CSV data is available because the loader should prefer the Stage 1 contract when those files exist.
def _csv_source_available(data_dir: Path) -> bool:
    return any((data_dir / file_name).exists() for file_name in EXPECTED_CSV_FILES)


# Detects whether SAP JSONL fallback data is available because local demos should still work in the current repository layout.
def _jsonl_source_available(data_dir: Path) -> bool:
    return (data_dir / "sales_order_headers").exists()


# Returns the default CSV directory because callers should not need to hardcode file-system layout knowledge.
def _default_csv_dir() -> Path:
    configured = os.environ.get("DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "data"


# Returns the default JSONL fallback directory because the repo already ships demo data under sap-o2c-data.
def _default_jsonl_dir() -> Path:
    configured = os.environ.get("SAP_DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "sap-o2c-data"


# Loads all data from the best available source because startup should work with either the new CSV contract or the existing demo dataset.
def load_all(
    request_id: str = "loader",
    csv_data_dir: Path | None = None,
    jsonl_data_dir: Path | None = None,
) -> dict[str, int]:
    csv_dir = csv_data_dir or _default_csv_dir()
    jsonl_dir = jsonl_data_dir or _default_jsonl_dir()

    log("loader.start", request_id, csv_dir=str(csv_dir), jsonl_dir=str(jsonl_dir))
    create_indexes()

    if _csv_source_available(csv_dir):
        return _load_from_csv(csv_dir, request_id)

    if _jsonl_source_available(jsonl_dir):
        return _load_from_jsonl(jsonl_dir, request_id)

    counts = _empty_counts()
    log("loader.no_source_found", request_id, **counts)
    return counts


# Supports `python -m app.ingestion.loader` because local operators may want to seed Aura outside the running API.
if __name__ == "__main__":
    print(json.dumps(load_all("loader-cli"), indent=2))
