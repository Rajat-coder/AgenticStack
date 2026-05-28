import asyncio
from backend.agent.search import find_similar_jobs, format_similar_jobs_for_context

async def test():
    ticket_text = "Add Proper logger.error Handling in All APIs"
    
    print("Searching for similar jobs...")
    similar = await find_similar_jobs(ticket_text)
    
    print(f"Found {len(similar)} similar jobs\n")
    for job in similar:
        print(f"  ticket_id  : {job['ticket_id']}")
        print(f"  title      : {job['ticket_title']}")
        print(f"  distance   : {job['distance']}")
        print(f"  similarity : {round((1 - job['distance']) * 100)}%")
        print()

    print("=" * 60)
    print("What planner sees:")
    print("=" * 60)
    print(format_similar_jobs_for_context(similar))

asyncio.run(test())