"""
Application-level singletons.

Keeping them here prevents circular imports:
  main.py     → imports harness from here
  api/agent.py → imports harness from here
Neither imports from the other.
"""
from backend.agent.harness import AgentHarness
from backend.ws import connection_manager

# One harness instance for the entire application lifetime.
# main.py calls harness.resume_crashed_jobs() on startup.
# api/agent.py calls harness.run_job() to start/resume jobs.
harness = AgentHarness(connection_manager=connection_manager)