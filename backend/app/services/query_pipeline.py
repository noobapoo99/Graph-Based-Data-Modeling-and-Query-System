"""Runs the six-step question-to-Cypher pipeline for database-grounded answers."""

from __future__ import annotations

import asyncio
import json
import re
import time

from app.database.neo4j_client import run_query
from app.database.schema import SCHEMA
from app.models import QueryRequest, QueryResponse
from app.services.llm_client import call_llm
from app.services.memory import get_history_text, save_turn
from app.services.semantic_search import resolve_entity
from app.utils.cache import get_cached, set_cache
from app.utils.logger import generate_request_id, log


CLASSIFIER_SYSTEM_PROMPT = """
You are a query classifier for a business data system.
The system contains data about: orders, deliveries, invoices,
payments, customers, and products.

Classify the user's question as exactly ONE of:
- BUSINESS    → question is about the above data
- IRRELEVANT  → anything else

Reply with ONLY the single word: BUSINESS or IRRELEVANT
No explanation. No punctuation. Nothing else.
""".strip()

FORMATTER_SYSTEM_PROMPT = """
You are a business analyst assistant.
Instructions:
- Summarize the data in 2-4 clear sentences
- Use specific numbers and names from the data
- Do NOT add information not present in the data
- Do NOT say "based on the data" — just answer directly
- If data is empty, say: "No matching records were found."
""".strip()

BLOCKED_PATTERNS = [
    r"\bCREATE\b",
    r"\bMERGE\b",
    r"\bSET\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bREMOVE\b",
    r"\bCALL\b",
    r"\bFOREACH\b",
    r"\bLOAD\b",
]


# Creates a uniform failure response because every exit path should return the same API contract instead of raising.
def _build_response(
    answer: str,
    started_at: float,
    cypher: str | None = None,
    explanation: str | None = None,
    step_failed: str | None = None,
) -> QueryResponse:
    latency_ms = int((time.time() - started_at) * 1000)
    return QueryResponse(
        answer=answer,
        cypher=cypher,
        explanation=explanation,
        latency_ms=latency_ms,
        step_failed=step_failed,
    )


# Builds prompt-friendly schema text because the generator should see one stable schema description every time.
def _schema_text() -> str:
    return json.dumps(SCHEMA, indent=2)


# Extracts lightweight semantic hints because mapping vague business words to schema labels improves follow-up query quality.
def _semantic_hints(query: str) -> str:
    hints: list[str] = []
    candidates = {query.strip()}
    candidates.update(re.findall(r"[A-Za-z]{4,}", query))

    for candidate in candidates:
        resolved = resolve_entity(candidate)
        if resolved:
            hints.append(f"{candidate} -> {resolved}")

    if not hints:
        return "No semantic hints."

    return "\n".join(sorted(set(hints))[:5])


# Formats the classifier user message because follow-up questions depend on both recent history and the current question.
def _classifier_user_message(query: str, history_text: str) -> str:
    return (
        f"Conversation history:\n{history_text}\n\n"
        f"Semantic hints:\n{_semantic_hints(query)}\n\n"
        f"User question:\n{query}"
    )


# Normalizes raw LLM output because providers sometimes wrap otherwise valid Cypher in code fences or extra whitespace.
def _normalize_generated_cypher(raw_output: str) -> str:
    cleaned = raw_output.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip().rstrip(";").strip()
    return cleaned


# Enforces the result limit because Stage 1 must cap record volume even if the model forgets the prompt rule.
def _force_limit_50(cypher: str) -> str:
    if cypher == "INVALID_QUERY":
        return cypher

    if re.search(r"\bLIMIT\s+\d+\b", cypher, flags=re.IGNORECASE):
        return re.sub(r"\bLIMIT\s+\d+\b", "LIMIT 50", cypher, flags=re.IGNORECASE)

    return f"{cypher} LIMIT 50"


# Builds the generator prompt because the LLM must translate only within the allowed schema and Cypher subset.
def _generator_system_prompt(history_text: str) -> str:
    return f"""
You convert business questions into safe read-only Cypher for Neo4j.

Schema:
{_schema_text()}

Recent conversation history:
{history_text}

STRICT RULES:
1. Return ONLY raw Cypher. No markdown, no backticks.
2. Query MUST start with MATCH
3. Only use: MATCH, WHERE, WITH, RETURN, ORDER BY, LIMIT
4. NEVER use: CREATE, MERGE, SET, DELETE, DROP, REMOVE, CALL
5. Always add LIMIT 50
6. Only use labels/properties from the schema
7. If unanswerable -> return exactly: INVALID_QUERY

Few-shot examples:
Q: Which customers placed the most orders?
A: MATCH (c:Customer)-[:PLACED]->(o:Order)
   RETURN c.name, count(o) AS order_count
   ORDER BY order_count DESC LIMIT 10

Q: Show invoices that have not been paid
A: MATCH (i:Invoice)
   WHERE NOT (i)-[:SETTLED_BY]->(:Payment)
   RETURN i.id, i.date, i.amount, i.status LIMIT 50

Q: Trace the full journey of order ORD-001
A: MATCH path = (o:Order {{id: 'ORD-001'}})-[:FULFILLED_BY]->
   (d:Delivery)-[:BILLED_AS]->(i:Invoice)-[:SETTLED_BY]->(p:Payment)
   RETURN o.id, d.id, i.id, p.id

Q: What is the capital of France?
A: INVALID_QUERY
""".strip()


# Classifies the user question because irrelevant requests should be rejected before they touch the cache, LLM query generator, or database.
async def query_classifier(query: str, history_text: str, request_id: str) -> str:
    user_message = _classifier_user_message(query, history_text)
    log("pipeline.step1.classifier.input", request_id, query=query, history=history_text)
    result = await asyncio.to_thread(
        call_llm,
        CLASSIFIER_SYSTEM_PROMPT,
        user_message,
        request_id,
    )
    classification = result.strip().upper()
    log("pipeline.step1.classifier.output", request_id, classification=classification)
    return classification


# Checks Redis because repeated identical questions should skip expensive LLM and database work whenever the context matches.
async def cache_check(query: str, history_text: str, request_id: str) -> dict | None:
    log("pipeline.step2.cache.input", request_id, query=query, history=history_text)
    cached_response = await asyncio.to_thread(get_cached, query, history_text)
    log("pipeline.step2.cache.output", request_id, cache_hit=bool(cached_response))
    return cached_response


# Generates Cypher because the database can only answer the question after the natural-language request is translated safely.
async def cypher_generator(query: str, history_text: str, request_id: str) -> str:
    user_message = (
        f"User question:\n{query}\n\n"
        f"Semantic hints:\n{_semantic_hints(query)}\n\n"
        "Return the safest valid Cypher query for this question."
    )
    log("pipeline.step3.generator.input", request_id, query=query, history=history_text)
    raw_output = await asyncio.to_thread(
        call_llm,
        _generator_system_prompt(history_text),
        user_message,
        request_id,
    )
    normalized_output = _force_limit_50(_normalize_generated_cypher(raw_output))
    log(
        "pipeline.step3.generator.output",
        request_id,
        raw_output=raw_output,
        normalized_output=normalized_output,
    )
    return normalized_output


# Validates generated Cypher because the safety gate must be deterministic and must not depend on another LLM call.
def cypher_validator(cypher: str, request_id: str) -> tuple[bool, str]:
    log("pipeline.step4.validator.input", request_id, cypher=cypher)

    if cypher == "INVALID_QUERY":
        reason = "The question could not be mapped to the business schema."
        log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
        return False, reason

    if not re.match(r"^\s*MATCH\b", cypher, flags=re.IGNORECASE):
        reason = "Cypher must start with MATCH."
        log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
        return False, reason

    if ";" in cypher:
        reason = "Cypher must be a single statement."
        log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
        return False, reason

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cypher, flags=re.IGNORECASE):
            reason = f"Cypher contains blocked pattern: {pattern}"
            log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
            return False, reason

    node_labels = re.findall(r"\([^)]+:([A-Za-z][A-Za-z0-9_]*)", cypher)
    for label in node_labels:
        if label not in SCHEMA["nodes"]:
            reason = f"Unknown node label: {label}"
            log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
            return False, reason

    relationship_types = re.findall(r"\[[^\]]*:([A-Za-z][A-Za-z0-9_]*)", cypher)
    for relationship_type in relationship_types:
        if relationship_type not in SCHEMA["relationships"]:
            reason = f"Unknown relationship type: {relationship_type}"
            log("pipeline.step4.validator.output", request_id, valid=False, reason=reason)
            return False, reason

    log("pipeline.step4.validator.output", request_id, valid=True, reason="ok")
    return True, "ok"


# Executes the validated Cypher because only real database rows are allowed to ground the final answer.
async def database_executor(cypher: str, request_id: str) -> tuple[list[dict] | None, str | None]:
    log("pipeline.step5.executor.input", request_id, cypher=cypher)
    last_error: Exception | None = None

    for attempt in range(1, 3):
        try:
            rows = await asyncio.to_thread(run_query, cypher, None, 10)
            log(
                "pipeline.step5.executor.output",
                request_id,
                attempt=attempt,
                row_count=len(rows),
            )
            return rows, None
        except Exception as exc:
            last_error = exc
            log(
                "pipeline.step5.executor.retry",
                request_id,
                attempt=attempt,
                error=str(exc),
            )
            if attempt < 2:
                await asyncio.sleep(0.25)

    return None, f"Database execution failed: {last_error}"


# Formats database rows into plain English because users need a readable answer that still stays grounded in returned records only.
async def response_formatter(
    query: str,
    rows: list[dict],
    request_id: str,
) -> tuple[str | None, str | None]:
    log("pipeline.step6.formatter.input", request_id, row_count=len(rows))

    if not rows:
        answer = "No matching records were found."
        log("pipeline.step6.formatter.output", request_id, answer=answer)
        return answer, None

    user_message = (
        f"User question:\n{query}\n\n"
        f"Database rows:\n{json.dumps(rows, default=str, indent=2)}"
    )

    try:
        answer = await asyncio.to_thread(
            call_llm,
            FORMATTER_SYSTEM_PROMPT,
            user_message,
            request_id,
        )
        log("pipeline.step6.formatter.output", request_id, answer=answer)
        return answer.strip(), None
    except Exception as exc:
        log("pipeline.step6.formatter.error", request_id, error=str(exc))
        return None, str(exc)


# Runs the pipeline with a caller-provided request ID because API routes should share one correlation ID across route and pipeline logs.
async def run_pipeline_with_request_id(req: QueryRequest, request_id: str) -> QueryResponse:
    started_at = time.time()
    history_text = get_history_text(req.session_id)
    final_response: QueryResponse | None = None

    try:
        async with asyncio.timeout(15):
            classification = await query_classifier(req.query, history_text, request_id)
            if classification != "BUSINESS":
                final_response = _build_response(
                    answer="I can only answer questions about customers, orders, products, deliveries, invoices, payments, and journal entries.",
                    started_at=started_at,
                    explanation="The classifier marked this question as IRRELEVANT.",
                    step_failed="query_classifier",
                )
                return final_response

            cached_response = await cache_check(req.query, history_text, request_id)
            if cached_response:
                final_response = _build_response(
                    answer=cached_response["answer"],
                    started_at=started_at,
                    cypher=cached_response.get("cypher"),
                    explanation="Returned from cache.",
                )
                return final_response

            cypher = await cypher_generator(req.query, history_text, request_id)
            is_valid, validation_reason = cypher_validator(cypher, request_id)
            if not is_valid:
                final_response = _build_response(
                    answer="I could not turn that question into a safe database query.",
                    started_at=started_at,
                    cypher=cypher if cypher != "INVALID_QUERY" else None,
                    explanation=validation_reason,
                    step_failed="cypher_validator",
                )
                return final_response

            rows, execution_error = await database_executor(cypher, request_id)
            if execution_error:
                final_response = _build_response(
                    answer="I could not retrieve data from the database right now.",
                    started_at=started_at,
                    cypher=cypher,
                    explanation="The query was validated, but database execution failed.",
                    step_failed="database_executor",
                )
                return final_response

            answer, formatter_error = await response_formatter(req.query, rows or [], request_id)
            if formatter_error or not answer:
                final_response = _build_response(
                    answer="I found matching records, but I could not format them into a response right now.",
                    started_at=started_at,
                    cypher=cypher,
                    explanation="The database query succeeded, but response formatting failed.",
                    step_failed="response_formatter",
                )
                return final_response

            final_response = _build_response(
                answer=answer,
                started_at=started_at,
                cypher=cypher,
                explanation=f"The answer was generated from {len(rows or [])} database row(s).",
            )

            await asyncio.to_thread(
                set_cache,
                req.query,
                {
                    "answer": final_response.answer,
                    "cypher": final_response.cypher,
                    "explanation": final_response.explanation,
                },
                history_text,
            )
            return final_response
    except TimeoutError:
        final_response = _build_response(
            answer="The request took too long to complete.",
            started_at=started_at,
            explanation="The pipeline exceeded the 15 second request budget.",
            step_failed="query_pipeline",
        )
        return final_response
    except Exception as exc:
        log("pipeline.unhandled_error", request_id, error=str(exc))
        final_response = _build_response(
            answer="An unexpected error prevented the request from completing.",
            started_at=started_at,
            explanation="The pipeline caught an unexpected internal error.",
            step_failed="query_pipeline",
        )
        return final_response
    finally:
        if final_response is not None:
            save_turn(req.session_id, req.query, final_response.answer)


# Runs the full six-step pipeline because the API needs one simple public entry point for query requests.
async def run_pipeline(req: QueryRequest) -> QueryResponse:
    return await run_pipeline_with_request_id(req, generate_request_id())
