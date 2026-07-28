"""
Upload config IP, rebuild frontend avec IP, sync Odoo, tout en parallele.
"""
import paramiko, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

from vps_config import VPS_HOST, REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent

def run(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
sftp = client.open_sftp()

# ─── 1. Upload fichiers mis à jour ─────────────────────────────────────────
print("[1] Upload fichiers mis a jour...")
files = [
    (PROJECT_ROOT / "docker-compose.yml",        f"{REMOTE_DIR}/docker-compose.yml"),
    (PROJECT_ROOT / ".env.prod",                  f"{REMOTE_DIR}/.env.prod"),
    (PROJECT_ROOT / "nginx.neurones-ia.conf",     "/etc/nginx/sites-available/neurones-ia"),
]
for local, remote in files:
    with open(local, "rb") as f:
        sftp.putfo(f, remote)
    print(f"   {local.name} -> {remote}")

# ─── 2. Recharger nginx avec le port 8080 ──────────────────────────────────
print("[2] Reload nginx (ajout port 8080)...")
out, rc = run(client, "nginx -t 2>&1")
print(f"   nginx -t: {'OK' if rc == 0 else 'ERREUR: ' + out[:200]}")
if rc == 0:
    run(client, "systemctl reload nginx")
    print("   nginx reloaded")

# ─── 3. Lancer sync Odoo en arriere-plan ──────────────────────────────────
print("[3] Lancement sync Odoo en arriere-plan...")
run(client,
    f"cd {REMOTE_DIR} && "
    f"docker compose exec -T backend python -c \""
    f"import asyncio,sys; sys.path.insert(0,'.'); "
    f"from jobs.odoo_sync_job import run_odoo_sync; "
    f"asyncio.run(run_odoo_sync(force_full=True))"
    f"\" > /tmp/odoo_sync.log 2>&1 &",
    timeout=10)
print("   Sync lance -> /tmp/odoo_sync.log")

# ─── 4. Rebuild frontend avec URL IP ──────────────────────────────────────
print(f"[4] Lancement rebuild frontend (URL: http://{VPS_HOST}:8080/api/v1)...")
run(client,
    f"cd {REMOTE_DIR} && "
    f"nohup docker compose build frontend > /tmp/frontend_rebuild.log 2>&1 &",
    timeout=10)
print("   Build lance en arriere-plan -> /tmp/frontend_rebuild.log")

# ─── 5. Monitoring ─────────────────────────────────────────────────────────
print("[5] Monitoring build + sync (max 8 min)...")
for i in range(48):
    time.sleep(10)
    elapsed = (i+1)*10

    # Etat du build frontend
    nb_build, _ = run(client, "pgrep -c -f 'docker compose build' 2>/dev/null || echo 0")
    build_done = nb_build.strip() == "0"

    # Derniere ligne du build log
    tail_build, _ = run(client, "tail -1 /tmp/frontend_rebuild.log 2>/dev/null || echo '...'")

    # Etat du sync
    tail_sync, _ = run(client, "tail -1 /tmp/odoo_sync.log 2>/dev/null || echo '...'")

    build_status = "DONE" if build_done else "building"
    print(f"  t={elapsed}s | build:{build_status} | sync: {tail_sync[:60]}")
    print(f"              | {tail_build[:80]}")

    if build_done and elapsed > 30:
        print("  Build termine!")
        break

# ─── 6. Demarrer le nouveau frontend ──────────────────────────────────────
print("[6] Redemarrage frontend avec nouvelle image...")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose up -d frontend", timeout=30)
print(out[:200])

time.sleep(20)

# ─── 7. Etat final ─────────────────────────────────────────────────────────
print("[7] Etat final:")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out)

print("[8] Tests:")
h1, _ = run(client, "curl -sf http://localhost:8000/v1/health | head -c 100")
print(f"   Backend: {h1}")
h2, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:8080/")
print(f"   Nginx:8080 -> frontend: {h2}")
h3, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:8080/api/v1/health")
print(f"   Nginx:8080 -> /api/v1/health: {h3}")

print("\n[9] Sync Odoo (log tail):")
out, _ = run(client, "tail -15 /tmp/odoo_sync.log 2>/dev/null || echo 'sync en cours ou pas encore demarre'")
print(out)

sftp.close()
client.close()
print("\n=== DONE ===")
print(f"Application accessible sur: http://{VPS_HOST}:8080")
