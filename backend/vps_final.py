"""Verification finale courte."""
import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from vps_config import REMOTE_DIR, ssh_connect

def run(client, cmd, timeout=20):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return (out + err).strip()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

print("=== Conteneurs ===")
print(run(client, f"cd {REMOTE_DIR} && docker compose ps"))

print("\n=== Backend /v1/health ===")
print(run(client, "curl -sf http://localhost:8000/v1/health || echo 'pas pret'"))

print("\n=== nginx:8080 frontend ===")
print(run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:8080/"))

print("\n=== nginx:8080/api/v1/health ===")
print(run(client, "curl -sf http://localhost:8080/api/v1/health || echo 'pas pret'"))

print("\n=== Compte admin (login) ===")
admin_cmd = (
    "docker compose exec -T backend python -c \""
    "import asyncio, sys, os; os.chdir('/app'); sys.path.insert(0,'/app');"
    "from db.database import AsyncSessionLocal;"
    "from db.models import UserModel;"
    "from sqlalchemy import select;"
    "async def f():"
    "    async with AsyncSessionLocal() as s:"
    "        r = await s.execute(select(UserModel));"
    "        for u in r.scalars(): print(u.email, u.role, u.is_active);"
    "asyncio.run(f())"
    "\""
)
print(run(client, f"cd {REMOTE_DIR} && {admin_cmd}", timeout=20))

client.close()
