"""The CFO agent: one core that runs every AI job, and the jobs themselves.

`core` runs a job given its prompt, the tools it may use and the output it
should produce; `tools` holds the local tools; `jobs/` holds the jobs.
"""
from agent.jobs.chat import run_turn

__all__ = ["run_turn"]
