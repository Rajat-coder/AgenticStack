import logging

import openai
from sqlalchemy import select, text

from backend.config import settings
from backend.db.models import Job, JobEmbedding
from backend.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Function 1 — embed_text()
#
# What: converts any text → list of 1536 numbers
# Why:  numbers that represent meaning — similar text = similar numbers
# When: called before storing AND before searching
# ------------------------------------------------------------------

async def embed_text(text: str) -> list[float]:
    """
    Call OpenAI embedding model → get 1536 numbers back.
    
    text-embedding-3-small:
    - Cheap: $0.00002 per 1000 tokens (almost free)
    - Fast: returns in ~200ms
    - Good quality: 1536 dimensions captures meaning well
    - Always returns exactly 1536 numbers regardless of input length
    """
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    # response.data[0].embedding is the list of 1536 floats
    return response.data[0].embedding

async def store_job_embedding(job: Job, plan_summary: str) -> None:
    """
    Build a text summary of this job and store its vector.
    
    We combine ticket title + description + plan summary into one string.
    Why combine? Because when searching, we want to find jobs that are
    similar in BOTH what was asked AND how we solved it.
    
    Example content stored:
        "Ticket: Restrict Notes Character Limit
         Description: Users can enter unlimited text in notes field
         Plan: Add field_validator in schemas for 150 char limit"
    """
    # Build the text we will embed
    # This is also what gets shown to the planner as a "past example"
    import json
    plan_data = json.loads(job.plan) if job.plan else {}

    files_modified = "\n".join(f"  - {f}" for f in plan_data.get("files_to_modify", []))
    files_created  = "\n".join(f"  - {f}" for f in plan_data.get("files_to_create", []))
    steps          = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan_data.get("steps", [])))
    content = f"""Ticket: {job.ticket_title}
        Ticket ID: {job.ticket_id}
        Plan Summary: {plan_summary}
        Files Modified:
        {files_modified if files_modified else "  none"}
        Files Created:
        {files_created if files_created else "  none"}
        Steps Taken:
        {steps if steps else "  none"}"""

    logger.info("Embedding job %s for vector search", job.ticket_id)

    # Convert text → 1536 numbers
    vector = await embed_text(content)

    # Save to DB — both the text (for display) and the vector (for search)
    async with AsyncSessionFactory() as db:
        embedding = JobEmbedding(
            job_id=job.id,
            content=content,
            embedding=vector,       # PostgreSQL stores this as vector(1536) column
        )
        db.add(embedding)
        await db.commit()

    logger.info("Stored embedding for job %s", job.ticket_id)


async def find_similar_jobs(ticket_text: str, limit: int = 3) -> list[dict]:
    """
    Hybrid search — vector similarity + keyword search, combined via RRF.

    Why hybrid?
    - Vector search: finds semantically similar jobs ("user can't login" = "authentication error")
    - Keyword search: finds exact term matches ("logger.error", specific class names)
    - RRF: merges both ranked lists — rewards jobs that appear high in BOTH

    Steps:
    1. Embed new ticket text → vector
    2. Run vector search → ranked list by cosine distance
    3. Run keyword search → ranked list by text match score
    4. Merge both lists using RRF formula
    5. Return top results with similarity score
    """
    if not settings.openai_api_key:
        logger.warning("No OpenAI key — skipping similar job search")
        return []

    # Step 1 — embed the new ticket
    query_vector = await embed_text(ticket_text)
    vector_str = "[" + ",".join(str(x) for x in query_vector) + "]"

    # Clean query for PostgreSQL full-text search
    # plainto_tsquery handles plain text — no special formatting needed
    # "Add logger.error Handling" → 'add' & 'logger.error' & 'handling'
    clean_query = " ".join(
        word for word in ticket_text.split()
        if len(word) > 2  # skip very short words like "in", "at"
    )

    async with AsyncSessionFactory() as db:
        result = await db.execute(
            text("""
                WITH vector_search AS (
                    -- Search by meaning (cosine distance)
                    -- Lower distance = more similar
                    SELECT
                        je.job_id,
                        je.content,
                        je.embedding <=> CAST(:vector AS vector) AS distance,
                        ROW_NUMBER() OVER (
                            ORDER BY je.embedding <=> CAST(:vector AS vector)
                        ) AS vector_rank
                    FROM job_embeddings je
                    LIMIT 20
                ),
                keyword_search AS (
                    -- Search by exact words (full-text search)
                    -- Higher ts_rank = better keyword match
                    SELECT
                        je.job_id,
                        je.content,
                        ROW_NUMBER() OVER (
                            ORDER BY ts_rank(
                                to_tsvector('english', je.content),
                                plainto_tsquery('english', :query)
                            ) DESC
                        ) AS keyword_rank
                    FROM job_embeddings je
                    WHERE to_tsvector('english', je.content) 
                          @@ plainto_tsquery('english', :query)
                    LIMIT 20
                ),
                rrf_scores AS (
                    -- RRF formula: 1/(60 + rank)
                    -- 60 is a standard constant that prevents high scores for low ranks
                    -- COALESCE handles jobs that appear in only one list (score 0 for missing)
                    SELECT
                        COALESCE(v.job_id, k.job_id)   AS job_id,
                        COALESCE(v.content, k.content)  AS content,
                        COALESCE(v.distance, 1.0)       AS distance,
                        COALESCE(1.0 / (60 + v.vector_rank),  0) +
                        COALESCE(1.0 / (60 + k.keyword_rank), 0) AS rrf_score
                    FROM vector_search v
                    FULL OUTER JOIN keyword_search k ON v.job_id = k.job_id
                )
                SELECT
                    r.job_id,
                    r.content,
                    r.distance,
                    r.rrf_score,
                    j.ticket_id,
                    j.ticket_title
                FROM rrf_scores r
                JOIN jobs j ON j.id = r.job_id
                ORDER BY r.rrf_score DESC
                LIMIT :limit
            """),
            {"vector": vector_str, "query": clean_query, "limit": limit}
        )
        rows = result.fetchall()

    # Filter out results that are too different (distance > 0.7)
    # These are not useful examples even if keyword matched
    similar = []
    for row in rows:
        if row.distance < 0.7:
            similar.append({
                "ticket_id":    row.ticket_id,
                "ticket_title": row.ticket_title,
                "content":      row.content,
                "distance":     round(row.distance, 3),
                "rrf_score":    round(row.rrf_score, 4),
            })

    logger.info(
        "Hybrid search found %d similar jobs (from %d candidates)",
        len(similar), len(rows)
    )
    return similar


def format_similar_jobs_for_context(similar_jobs: list[dict]) -> str:
    """
    Convert list of similar jobs into a formatted string.
    
    This string gets injected at the top of the planner's user message.
    The planner reads it as "here's how we solved similar problems before."
    
    Example output:
        ## Similar Past Jobs — Learn From These Examples
        
        ### Example 1 (similarity: 92%)
        AMARA-2542: Restrict Notes Character Limit
        ---
        Ticket: Restrict Notes Character Limit
        Plan Summary: Add field_validator in schemas...
    """
    if not similar_jobs:
        return ""

    lines = ["## Similar Past Jobs — Learn From These Examples\n"]

    for i, job in enumerate(similar_jobs, 1):
        # Convert distance to similarity percentage
        # distance 0.0 = 100% similar, distance 0.5 = 50% similar
        similarity_pct = round((1 - job["distance"]) * 100)

        lines.append(f"### Example {i} (similarity: {similarity_pct}%)")
        lines.append(f"{job['ticket_id']}: {job['ticket_title']}")
        lines.append("---")
        lines.append(job["content"])
        lines.append("")  # blank line between examples

    lines.append(
        "Use these examples to inform your plan. "
        "Follow the same patterns and file choices where relevant.\n"
    )

    return "\n".join(lines)