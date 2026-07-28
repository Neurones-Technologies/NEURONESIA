"""Exploration du VPS 2 (Odoo) avant déploiement."""
import paramiko

HOST = "20.61.192.225"
USER = "adm_odoo"
PASS = "adm@Odoo#Pass"

def run(client, cmd, sudo=False):
    if sudo:
        cmd = f"echo '{PASS}' | sudo -S {cmd} 2>/dev/null"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out + err

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)
print("[OK] Connecte au VPS2", HOST)

sections = [
    ("OS", "cat /etc/os-release | head -6"),
    ("CPU/RAM", "nproc && free -h | head -3"),
    ("Disques", "df -h"),
    ("Docker", "docker ps -a 2>/dev/null || sudo docker ps -a 2>/dev/null || echo 'docker non installe'"),
    ("Docker Compose", "docker compose version 2>/dev/null || echo 'compose non installe'"),
    ("Ports actifs", "ss -tlnp | grep LISTEN"),
    ("Apps /var/www", "ls /var/www/ 2>/dev/null || echo 'vide'"),
    ("Apps /opt", "ls /opt/ 2>/dev/null || echo 'vide'"),
    ("Odoo", "sudo systemctl status odoo 2>/dev/null | head -10 || ps aux | grep odoo | grep -v grep | head -5"),
    ("Services actifs", "systemctl list-units --type=service --state=running 2>/dev/null | grep -v systemd | head -20"),
    ("GPU/CPU info", "lscpu | grep -E 'Model name|CPU|Core|Thread' | head -10"),
    ("RAM details", "cat /proc/meminfo | head -5"),
]

for title, cmd in sections:
    print(f"\n{'='*40}")
    print(f"  {title}")
    print(f"{'='*40}")
    result = run(client, cmd)
    print(result.strip() if result.strip() else "(vide)")

client.close()
print("\n[DONE]")
