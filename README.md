# Graph Query System

## Overview
Graph Query System is a full-stack application for asking natural-language questions about business process data stored in Neo4j. The backend uses an LLM as a translator, not as a source of truth: it converts a user question into safe Cypher, runs that query against the graph, and only then formats the returned rows into plain-English output. A guarded six-step pipeline, Redis caching, regex validation, provider fallback, and timeouts keep the query path deterministic and operationally safe. The React frontend pairs a force-directed graph view with a chat panel so users can both inspect the live graph and ask questions against it.

## Architecture diagram
```text
+---------------------------+
| Browser                   |
| React + Vite frontend     |
| - Graph view              |
| - Chat panel              |
| - Broken-flow badge       |
+-------------+-------------+
              |
              | POST /api/query
              v
+-------------+-------------+
| FastAPI                   |
| /api/query                |
+-------------+-------------+
              |
              v
  +---------------------------------------------------------------+
  | 6-Step Query Pipeline                                         |
  |                                                               |
  | 1. Query Classifier   ---> Groq / Gemini                      |
  | 2. Cache Check        ---> Redis                              |
  | 3. Cypher Generator   ---> Groq / Gemini                      |
  | 4. Regex Validator    ---> blocked keywords + schema whitelist|
  | 5. DB Executor        ---> Neo4j                              |
  | 6. Response Formatter ---> Groq / Gemini (DB rows only)       |
  +---------------------------------------------------------------+
              |
              v
+-------------+-------------+
| QueryResponse             |
| answer, cypher,           |
| explanation, latency_ms,  |
| step_failed               |
+---------------------------+

Other browser reads:
  GET /api/graph        -> FastAPI -> Neo4j
  GET /api/broken-flows -> FastAPI -> Neo4j
  GET /api/health       -> FastAPI -> Neo4j + Groq/Gemini
  GET /api/schema       -> FastAPI -> in-process schema object
```

## Quick start
```bash
git clone <your-repo-url>
cd "Graph-Based Data Modeling and Query System"
cp .env.example .env
```

Fill in `GROQ_API_KEY` and `GEMINI_API_KEY` in `.env`, then start the stack:

```bash
docker-compose up
```

Open the app at [http://localhost:5173](http://localhost:5173).

Notes:
- The backend starts on `http://localhost:8000`.
- Neo4j Browser is available at [http://localhost:7474](http://localhost:7474).
- The loader prefers `./data` CSV files when present and falls back to the bundled `./sap-o2c-data` dataset.

## Environment variables
Only `GROQ_API_KEY` and `GEMINI_API_KEY` must be filled manually for the default Docker Compose quick start. The remaining values are either provided by Compose, included in `.env.example`, or used as optional overrides for local and production deployments.

| Variable | Used by | Required for quick start | Default / Compose value | Description |
| --- | --- | --- | --- | --- |
| `GROQ_API_KEY` | Backend | Yes | none | API key for the primary LLM provider used in classification, Cypher generation, formatting, and health checks. |
| `GEMINI_API_KEY` | Backend | Yes | none | API key for the fallback LLM provider used when Groq fails. |
| `NEO4J_URI` | Backend | No | `bolt://neo4j:7687` in Compose, `bolt://localhost:7687` in `.env.example` | Neo4j Bolt connection string. |
| `NEO4J_USER` | Backend | No | `neo4j` | Username for the Neo4j instance. |
| `NEO4J_PASSWORD` | Backend | No | `password123` | Password for the Neo4j instance. |
| `NEO4J_DATABASE` | Backend | No | `neo4j` | Optional database name override; the code defaults to Neo4j's standard database. |
| `REDIS_HOST` | Backend | No | `redis` in Compose, `localhost` in `.env.example` | Redis host used by the query cache. |
| `REDIS_PORT` | Backend | No | `6379` | Redis port used by the query cache. |
| `REDIS_DB` | Backend | No | `0` | Optional Redis logical database index. |
| `DATA_DIR` | Backend | No | `/workspace/data` in Compose, `./data` in `.env.example` | Preferred CSV ingestion directory for Stage 1 data loading. |
| `SAP_DATA_DIR` | Backend | No | `/workspace/sap-o2c-data` in Compose, `./sap-o2c-data` in `.env.example` | JSONL fallback ingestion directory when CSV files are absent. |
| `VITE_API_URL` | Frontend | No | `http://localhost:8000` in Compose | Absolute backend URL used by production-style frontend builds outside Vite dev proxy mode. |
| `VITE_PROXY_TARGET` | Frontend / Vite | No | `http://backend:8000` in Compose, `http://localhost:8000` by default in Vite config | Backend target for Vite's `/api` dev proxy. |

## API reference

### `POST /api/query`
Submit a natural-language question to the six-step query pipeline.

Request body:
```json
{
  "query": "Show invoices that have not been paid",
  "session_id": "5af8a4f5-1bf7-4c52-88a2-3b7dbde2a25b"
}
```

Success response:
```json
{
  "answer": "Invoices INV-003 and INV-018 are still open and have no linked payments.",
  "cypher": "MATCH (i:Invoice) WHERE NOT (i)-[:SETTLED_BY]->(:Payment) RETURN i.id, i.date, i.amount, i.status LIMIT 50",
  "explanation": "The answer was generated from 2 database row(s).",
  "latency_ms": 187,
  "step_failed": null
}
```

Notes:
- `session_id` drives the last-five-turn conversation memory.
- `step_failed` is set when the pipeline safely rejects or fails a step, for example `query_classifier`, `cypher_validator`, `database_executor`, `response_formatter`, or `query_pipeline`.

### `GET /api/health`
Check whether Neo4j and at least one LLM provider are reachable.

Response:
```json
{
  "status": "healthy",
  "neo4j": "ok",
  "llm": "ok"
}
```

Behavior:
- Returns HTTP `200` when both Neo4j and the LLM health probe succeed.
- Returns HTTP `503` when either dependency is unreachable.

### `GET /api/graph`
Fetch a graph snapshot for the frontend visualization.

Actual response shape:
```json
{
  "nodes": [
    {
      "id": "CUST-001",
      "labels": ["Customer"],
      "properties": {
        "id": "CUST-001",
        "name": "Northwind Traders",
        "region": "West"
      }
    }
  ],
  "edges": [
    {
      "id": "4:abc123",
      "type": "PLACED",
      "source": "CUST-001",
      "target": "ORD-009"
    }
  ]
}
```

Notes:
- The endpoint is backed by fixed, read-only Cypher.
- The current implementation returns up to `500` nodes and `1000` edges.
- The frontend normalizes `labels[0]` and `properties` into its display model.

### `GET /api/broken-flows`
Return prebuilt diagnostics for incomplete order-to-cash chains.

Response:
```json
{
  "broken_flow_count": 3,
  "details": {
    "orders_without_delivery": [
      {
        "order_id": "ORD-010",
        "date": "2025-11-19",
        "status": "OPEN"
      }
    ],
    "deliveries_without_invoice": [],
    "invoices_without_payment": [
      {
        "invoice_id": "INV-014",
        "date": "2025-11-21",
        "amount": 980.0,
        "status": "OPEN"
      },
      {
        "invoice_id": "INV-019",
        "date": "2025-11-23",
        "amount": 410.0,
        "status": "OPEN"
      }
    ]
  }
}
```

### `GET /api/schema`
Return the canonical schema exposed to the LLM and used for validation.

Response shape:
```json
{
  "nodes": [
    "Customer",
    "Order",
    "Product",
    "Delivery",
    "Invoice",
    "Payment",
    "JournalEntry"
  ],
  "relationships": [
    "PLACED",
    "CONTAINS",
    "FULFILLED_BY",
    "BILLED_AS",
    "SETTLED_BY",
    "RECORDED_IN"
  ],
  "properties": {
    "Customer": ["id", "name", "region"],
    "Order": ["id", "date", "status", "total_amount"],
    "Product": ["id", "name", "category", "unit_price"],
    "Delivery": ["id", "date", "status"],
    "Invoice": ["id", "date", "amount", "status"],
    "Payment": ["id", "date", "amount", "method"],
    "JournalEntry": ["id", "date", "debit", "credit"]
  }
}
```

## Example queries
The system is designed to answer questions like:

1. Which customers placed the most orders?
2. Trace the full journey of order `ORD-001`.
3. Show invoices that have not been paid.
4. Which deliveries do not have an invoice yet?
5. What products are contained in order `ORD-014`?

Additional reference examples live in [docs/example_queries.md](docs/example_queries.md).

## Why Neo4j over PostgreSQL
This project models an order-to-cash process that is naturally expressed as a chain of connected business entities: `Customer -> Order -> Delivery -> Invoice -> Payment -> JournalEntry`. In a relational database, questions like "trace the full journey of order ORD-001" or "show invoices missing payments but linked to delivered orders" require multi-table joins that become increasingly awkward as the number of hops grows. Neo4j makes those traversals first-class. The query generator can target a small, explicit graph schema, and the executor can follow relationships directly instead of building wide join plans for every multi-step question.

Neo4j is also a better fit for the user experience this system exposes. The frontend includes a live graph visualization, the API provides graph snapshots, and the LLM prompt strategy works best when the domain is described in terms of labels and edges rather than many relational tables and foreign keys. PostgreSQL could absolutely store the same business facts, but the combination of graph-native traversal, simpler prompt grounding, and direct graph visualization gives Neo4j a cleaner end-to-end architecture for this particular application.

## LLM prompting strategy
### Why `temperature=0`
The LLM is being used as a translator, not a creative writer. Query classification and Cypher generation need repeatable behavior, especially when the same question is asked multiple times and the cache expects deterministic responses. Setting `temperature=0` reduces variability, makes logs easier to compare, and lowers the chance of the model producing stylistic but unsafe query variations.

### Why the schema is injected dynamically
The Cypher generator prompt includes the current `SCHEMA` object directly from the backend. That keeps the prompt anchored to the real labels, relationships, and properties the validator will allow. It also means the prompt stays aligned with the codebase instead of drifting into stale documentation or hand-maintained examples.

### Why few-shot examples are included
The generator prompt includes concrete examples for ranking, missing-payment detection, journey tracing, and explicit invalidation of irrelevant questions. Those examples narrow the output format, reinforce the allowed Cypher subset, and reduce the odds that the model invents clauses or labels outside the supported graph schema.

### Why the LLM only sees DB results in Step 6
Step 6 is intentionally isolated from the rest of the world. The formatter receives only the user question and the rows returned by Neo4j, not external documents, not unverified background knowledge, and not a free-form instruction to answer however it wants. That design is the core grounding guarantee of the system: the model can phrase the answer, but it cannot fabricate data that never came back from the database.

## Guardrails implementation
### 1. Query classifier (Step 1)
Every request starts with a binary classifier prompt that returns only `BUSINESS` or `IRRELEVANT`. This prevents off-topic questions from reaching the Cypher generator and gives the system an explicit, low-cost gate before any database work happens.

### 2. Regex validator (Step 4)
Generated Cypher is never executed directly. The validator enforces that a query starts with `MATCH`, rejects semicolons and blocked write-oriented patterns such as `CREATE`, `MERGE`, `SET`, `DELETE`, `DROP`, `REMOVE`, `CALL`, `FOREACH`, and `LOAD`, and only then allows execution to continue.

### 3. Schema whitelist enforcement
The validator also checks every discovered node label and relationship type against the canonical schema. Even if the LLM tried to invent a label, traverse an unknown edge, or leak into a raw source-specific structure, the query would fail before it ever reached Neo4j.

### 4. Timeout layers (Step 5)
The pipeline wraps the full request in `asyncio.timeout(15)`, while Neo4j queries run with an inner database timeout of `10` seconds and up to two execution attempts. That combination protects both the request lifecycle and the database itself: slow requests are bounded globally, and individual DB calls cannot run indefinitely.

### 5. Rate limiting
All public API routes are guarded by `slowapi` with a `10 requests/minute per IP` limit. This is a practical operational safeguard for both the LLM providers and the backend, and it helps reduce accidental abuse, runaway browser retries, and noisy health-check storms.

## Tradeoffs
1. **Conversation memory is process-local.** The last five turns are stored in an in-memory Python dictionary, which is simple and fast for a single instance but does not survive restarts and does not synchronize across multiple backend replicas.
2. **Provider fallback improves uptime but adds variability.** Groq is the primary provider and Gemini is the fallback, which increases reliability, but different providers can still have different latency profiles and subtle formatting differences even at `temperature=0`.
3. **Regex validation is pragmatic, not a full parser.** It is fast, deterministic, and easy to audit, but it is still less expressive than a true Cypher parser or policy engine. That means the supported query subset is intentionally conservative.
4. **Semantic search depends on local model availability.** The sentence-transformer path improves vocabulary matching, but the code uses `local_files_only=True`, so environments without the cached model simply skip that hinting layer instead of downloading weights at runtime.

