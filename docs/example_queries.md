# Example Queries

This document shows representative questions the system can answer, the kind of Cypher the generator should produce, and what the resulting answer would look like after Step 6 formats Neo4j rows into plain English.

## Category 1: Customer queries

### 1. Customers in a region
**Natural language question**

Which customers are in the West region?

**Representative Cypher**
```cypher
MATCH (c:Customer)
WHERE c.region = 'West'
RETURN c.id, c.name, c.region
ORDER BY c.name
LIMIT 50
```

**What the answer would look like**

Northwind Traders, Alpine Supply, and Horizon Retail are in the West region. The response lists up to 50 matching customers and keeps the answer grounded to the returned records only.

### 2. Orders for a specific customer
**Natural language question**

What orders has customer CUST-001 placed?

**Representative Cypher**
```cypher
MATCH (c:Customer {id: 'CUST-001'})-[:PLACED]->(o:Order)
RETURN c.name, o.id, o.date, o.status, o.total_amount
ORDER BY o.date DESC
LIMIT 50
```

**What the answer would look like**

Customer CUST-001 has placed recent orders such as ORD-041 and ORD-037. The answer would mention the order dates, current statuses, and total amounts that came back from Neo4j.

## Category 2: Order flow queries

### 3. Full journey of an order
**Natural language question**

Trace the full journey of order ORD-001.

**Representative Cypher**
```cypher
MATCH (o:Order {id: 'ORD-001'})-[:FULFILLED_BY]->(d:Delivery)-[:BILLED_AS]->(i:Invoice)-[:SETTLED_BY]->(p:Payment)
RETURN o.id, o.status, d.id, d.status, i.id, i.status, p.id, p.method, p.amount
LIMIT 50
```

**What the answer would look like**

Order ORD-001 was fulfilled by delivery DEL-009, billed as invoice INV-014, and settled by payment PAY-003. The answer would also call out the delivery status, invoice status, payment method, and payment amount if those fields were returned.

### 4. Open orders
**Natural language question**

Which orders are still open?

**Representative Cypher**
```cypher
MATCH (o:Order)
WHERE o.status = 'OPEN'
RETURN o.id, o.date, o.status, o.total_amount
ORDER BY o.date DESC
LIMIT 50
```

**What the answer would look like**

The system found a set of open orders and would summarize the newest ones first. A typical answer would mention several order IDs together with their dates and total amounts.

### 5. Products in an order
**Natural language question**

What products are contained in order ORD-014?

**Representative Cypher**
```cypher
MATCH (o:Order {id: 'ORD-014'})-[:CONTAINS]->(p:Product)
RETURN o.id, p.id, p.name, p.category, p.unit_price
ORDER BY p.name
LIMIT 50
```

**What the answer would look like**

Order ORD-014 contains products such as PROD-022 and PROD-041. The answer would list the product names, categories, and unit prices exactly as they were returned from the graph.

## Category 3: Invoice and payment queries

### 6. Unpaid invoices
**Natural language question**

Show invoices that have not been paid.

**Representative Cypher**
```cypher
MATCH (i:Invoice)
WHERE NOT (i)-[:SETTLED_BY]->(:Payment)
RETURN i.id, i.date, i.amount, i.status
ORDER BY i.date DESC
LIMIT 50
```

**What the answer would look like**

Invoices INV-018 and INV-021 are still unpaid, with amounts of 980.00 and 410.00 respectively. The answer would use the exact IDs, dates, statuses, and amounts from the query result.

### 7. Payments linked to an invoice
**Natural language question**

What payment settled invoice INV-001?

**Representative Cypher**
```cypher
MATCH (i:Invoice {id: 'INV-001'})-[:SETTLED_BY]->(p:Payment)
RETURN i.id, p.id, p.date, p.amount, p.method
LIMIT 50
```

**What the answer would look like**

Invoice INV-001 was settled by payment PAY-004. The answer would mention the payment date, amount, and method if those values were present in the returned row set.

## Category 4: Broken flow detection

### 8. Orders missing deliveries
**Natural language question**

Which orders do not have a delivery yet?

**Representative Cypher**
```cypher
MATCH (o:Order)
WHERE NOT (o)-[:FULFILLED_BY]->(:Delivery)
RETURN o.id, o.date, o.status
ORDER BY o.date DESC
LIMIT 50
```

**What the answer would look like**

Orders ORD-055 and ORD-061 do not currently have linked deliveries. The answer would summarize the missing-fulfillment records and mention the order dates and statuses returned by Neo4j.

### 9. Deliveries missing invoices
**Natural language question**

Which deliveries were created but never billed?

**Representative Cypher**
```cypher
MATCH (d:Delivery)
WHERE NOT (d)-[:BILLED_AS]->(:Invoice)
RETURN d.id, d.date, d.status
ORDER BY d.date DESC
LIMIT 50
```

**What the answer would look like**

Deliveries DEL-017 and DEL-025 have no linked invoices yet. The formatted answer would highlight that those deliveries remain incomplete in the order-to-cash chain.

## Category 5: Aggregation queries

### 10. Top customers by order count
**Natural language question**

Which customers placed the most orders?

**Representative Cypher**
```cypher
MATCH (c:Customer)-[:PLACED]->(o:Order)
RETURN c.name, count(o) AS order_count
ORDER BY order_count DESC
LIMIT 50
```

**What the answer would look like**

Northwind Traders placed the most orders, followed by Alpine Supply and Delta Wholesale. The answer would call out the leading customers and their exact order counts from the aggregation result.

