# Architecture Decisions

## ADR-001: Neo4j over PostgreSQL

### Context
The system answers multi-hop operational questions about order-to-cash data: which customer placed an order, which delivery fulfilled it, which invoice billed it, which payment settled it, and which journal entry recorded it. Those questions are relationship-heavy by nature, and the frontend also renders the same data as an explorable graph.

### Decision
Use Neo4j as the system of record for the business graph instead of PostgreSQL. Model the domain as labeled nodes and explicit relationships so the query pipeline can translate user questions into traversal-oriented Cypher rather than join-heavy SQL.

### Consequences
- This makes journey tracing and missing-link detection natural to express and easy for the LLM to target.
- It keeps the prompt schema compact: labels, relationship types, and node properties are easier to expose safely than a large relational model with many joins.
- It aligns directly with the Stage 2 graph visualization, which can render nodes and edges without an extra transformation layer.
- The cost is operational and organizational: Neo4j is a specialized datastore, the team must know Cypher, and reporting patterns that are trivial in SQL may require a different mindset or additional query tuning.

## ADR-002: LLM as translator, not answerer

### Context
The project goal is to let users ask natural-language questions while still guaranteeing that answers come from business data, not from model memory. Without a hard boundary, the model could hallucinate facts, summarize beyond the returned rows, or answer irrelevant questions from prior world knowledge.

### Decision
Use the LLM only for controlled translation tasks:
- classify whether a question belongs to the business domain
- generate read-only Cypher against the known schema
- format actual Neo4j rows into plain English

The model never becomes the authoritative data source.

### Consequences
- This preserves grounding: every successful answer is anchored to database results.
- It makes the system easier to audit because the returned Cypher and explanation are visible in the response and UI.
- It constrains prompting cleanly: Step 6 only sees the user question and database rows.
- The cost is extra complexity compared with a single free-form chat completion. The system needs multiple prompts, a validator, a query executor, and careful error handling to keep that boundary intact.

## ADR-003: Regex validation before every DB call

### Context
The Cypher generator is model-driven, which means it can produce malformed, unsupported, or unsafe output. The database execution layer therefore needs a deterministic safety gate before running any generated query.

### Decision
Validate every generated Cypher string with pure regex and schema checks before sending it to Neo4j. Reject anything that does not start with `MATCH`, contains blocked patterns such as `CREATE` or `DELETE`, includes unknown labels, or uses unknown relationship types.

### Consequences
- This creates a fast, explainable, non-LLM guardrail directly in the execution path.
- It prevents write operations, unsupported clauses, and schema drift from reaching Neo4j.
- It keeps the rules simple to test and inspect in code reviews.
- The tradeoff is that regex validation is intentionally conservative. It is not a full Cypher parser, so the system limits the supported query surface to keep the validator trustworthy.

## ADR-004: Redis over in-memory cache

### Context
The system benefits from caching repeated natural-language queries, especially when the same business questions are asked often. A naive in-memory cache would be easy to add, but it would disappear on restart and would not work across multiple backend instances.

### Decision
Use Redis as the query-response cache with hash-based keys and a one-hour TTL. Include conversational context in the cache key so follow-up questions do not reuse results from a different session history.

### Consequences
- Cache entries survive backend restarts as long as Redis remains up.
- The design is immediately more production-ready for multi-instance deployments than a process-local dictionary.
- Failures degrade safely because cache read and write errors are treated as non-fatal.
- The cost is another infrastructure dependency to operate, monitor, and secure, plus slightly more complexity around connection settings and runtime availability.

## ADR-005: Provider fallback for LLM reliability

### Context
The query pipeline depends on an external LLM for classification, Cypher generation, response formatting, and health checks. If a single provider becomes unavailable, the whole request path would fail even though the rest of the system is healthy.

### Decision
Use Groq as the primary provider and Gemini as the automatic fallback, with all calls funneled through a single client abstraction that applies the same timeout, logging, and deterministic generation settings.

### Consequences
- The system can continue serving requests during single-provider outages or intermittent API failures.
- Operational logs stay consistent because the same wrapper records provider success and failure across the stack.
- The health endpoint can test real reachability instead of assuming that one configured provider is always up.
- The cost is extra provider-specific code, more environment configuration, and some behavioral variation between providers even under the same prompting strategy.

