"""Script temporaire : resync complet pour peupler amount_residual."""
import asyncio
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs.odoo_sync_job import run_odoo_sync

asyncio.run(run_odoo_sync(force_full=True))
print("Resync terminé.")
