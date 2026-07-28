"""
Trois taches independantes sur le VPS :
1. Sync Odoo
2. Rebuild frontend avec URL IP
3. Verification finale
"""
import paramiko, time, sys, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

from vps_config import VPS_HOST, REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent

def run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
sftp = client.open_sftp()

# ─── 1. Ecrire le script de sync sur le VPS ──────────────────────────────
sync_script = b"""#!/bin/bash
cd /opt/neurones-ia
echo "[$(date)] Demarrage sync Odoo..."
docker compose exec -T backend python -c "
import asyncio, sys, os
os.chdir('/app')
sys.path.insert(0, '/app')
from jobs.odoo_sync_job import run_odoo_sync
asyncio.run(run_odoo_sync(force_full=True))
print('Sync Odoo termine!')
" 2>&1
echo "[$(date)] Script termine."
"""
sftp.open("/tmp/do_sync.sh", "wb").write(sync_script)
run(client, "chmod +x /tmp/do_sync.sh")
print("[1] Script sync ecrit sur VPS")

# ─── 2. Ecrire le script de rebuild frontend ─────────────────────────────
rebuild_script = b"""#!/bin/bash
cd /opt/neurones-ia
echo "[$(date)] Rebuild frontend..."
docker compose build --no-cache frontend 2>&1 | tail -5
echo "[$(date)] Redemarrage frontend..."
docker compose up -d frontend 2>&1
echo "[$(date)] Done."
"""
sftp.open("/tmp/do_rebuild.sh", "wb").write(rebuild_script)
run(client, "chmod +x /tmp/do_rebuild.sh")
print("[2] Script rebuild ecrit sur VPS")

# ─── 3. Lancer les deux en arriere-plan ──────────────────────────────────
run(client, "nohup bash /tmp/do_sync.sh > /tmp/sync.log 2>&1 &", timeout=5)
print("[3] Sync Odoo lance en arriere-plan")

run(client, "nohup bash /tmp/do_rebuild.sh > /tmp/rebuild.log 2>&1 &", timeout=5)
print("[4] Rebuild frontend lance en arriere-plan")

# ─── 4. Monitoring ────────────────────────────────────────────────────────
print("[5] Monitoring (max 10 min)...")
for i in range(60):
    time.sleep(10)
    elapsed = (i+1)*10

    # Sync status
    sync_tail, _ = run(client, "tail -1 /tmp/sync.log 2>/dev/null || echo '...'")
    sync_done_count, _ = run(client, "grep -c 'Script termine\\|Sync Odoo termine' /tmp/sync.log 2>/dev/null || echo 0")
    sync_done = int(sync_done_count) > 0

    # Rebuild status
    rebuild_tail, _ = run(client, "tail -1 /tmp/rebuild.log 2>/dev/null || echo '...'")
    rebuild_done_count, _ = run(client, "grep -c 'Done\\.' /tmp/rebuild.log 2>/dev/null || echo 0")
    rebuild_done = int(rebuild_done_count) > 0

    sync_icon = "OK" if sync_done else "..."
    rebuild_icon = "OK" if rebuild_done else "..."

    print(f"  t={elapsed:3d}s | sync:{sync_icon} {sync_tail[:50]} | rebuild:{rebuild_icon} {rebuild_tail[:40]}")

    if sync_done and rebuild_done:
        print("  Les deux taches sont terminees!")
        break

# ─── 5. Verification finale ───────────────────────────────────────────────
print("\n[6] Sync log (fin):")
out, _ = run(client, "tail -20 /tmp/sync.log 2>/dev/null")
print(out[:1000])

print("\n[7] Rebuild log (fin):")
out, _ = run(client, "tail -10 /tmp/rebuild.log 2>/dev/null")
print(out[:500])

print("\n[8] Etat conteneurs:")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out)

print("\n[9] Tests finaux:")
h1, _ = run(client, "curl -sf http://localhost:8000/v1/health | head -c 80")
print(f"   Backend /v1/health: {h1}")
h2, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:8080/")
print(f"   http://localhost:8080 (frontend via nginx): {h2}")
h3, _ = run(client, "curl -sf http://localhost:8080/api/v1/health | head -c 80")
print(f"   http://localhost:8080/api/v1/health: {h3}")

sftp.close()
client.close()
print("\n=== DONE ===")
print(f"URL de test: http://{VPS_HOST}:8080")
