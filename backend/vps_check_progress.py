"""Verifie l'avancement du sync et du rebuild sur le VPS."""
import paramiko, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from vps_config import REMOTE_DIR, ssh_connect

def run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

print("=== SYNC ODOO (log complet) ===")
out, _ = run(client, "cat /tmp/sync.log 2>/dev/null || echo 'log absent'")
print(out[:3000])

print("\n=== REBUILD FRONTEND (log tail) ===")
out, _ = run(client, "tail -20 /tmp/rebuild.log 2>/dev/null || echo 'log absent'")
print(out)

print("\n=== ETAT CONTENEURS ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out)

print("\n=== TESTS FINAUX ===")
h1, _ = run(client, "curl -sf http://localhost:8000/v1/health")
print(f"Backend /v1/health: {h1}")

h2, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:8080/")
print(f"nginx:8080 -> frontend: {h2}")

h3, _ = run(client, "curl -sf http://localhost:8080/api/v1/health")
print(f"nginx:8080/api/v1/health: {h3}")

# Stats SQLite
print("\n=== BASE SQLITE (stats apres sync) ===")
stats_cmd = (
    "docker compose exec -T backend python -c \""
    "import sqlite3; "
    "conn=sqlite3.connect('/app/data/local_db/neurones.db'); "
    "cur=conn.cursor(); "
    "cur.execute(\\\"SELECT name FROM sqlite_master WHERE type='table'\\\"); "
    "tables=cur.fetchall(); "
    "print('Tables:', [t[0] for t in tables]); "
    "[print(t[0]+':', cur.execute('SELECT COUNT(*) FROM '+t[0]).fetchone()[0], 'rows') for t in tables]; "
    "conn.close() "
    "\""
)
out, _ = run(client, f"cd {REMOTE_DIR} && {stats_cmd}", timeout=30)
print(out[:1000])

client.close()
print("\nVerification terminee.")
