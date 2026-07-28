"""
Script de copie des fichiers ABE / PV-recette / _Autres vers la GED.
Usage : python scripts/copy_ged_abe.py
Doit tourner depuis D:/Neurones-IA/backend
"""

import sys
import shutil
import requests
from pathlib import Path
from collections import defaultdict

# ── Chemins ──────────────────────────────────────────────────────────────────
SOURCE_ROOT = Path(r"D:\Neurones-IA\OneDrive_2026-05-19\Attestation de Bonne Execution")
GED_ROOT    = Path(r"D:\Neurones-IA\data\ged")

# ── Extensions autorisées ─────────────────────────────────────────────────────
ALLOWED_EXT = {".pdf", ".docx", ".doc"}

# ── Mapping source → destination (relatif à SOURCE_ROOT et GED_ROOT) ──────────
MAPPINGS = [
    # ABE
    (r"ABE - Attestation de Bonne Execution\01 - Securite",             "abe/securite"),
    (r"ABE - Attestation de Bonne Execution\02 - Reseaux",              "abe/reseaux"),
    (r"ABE - Attestation de Bonne Execution\03 - Serveurs et Datacenter","abe/serveurs-datacenter"),
    (r"ABE - Attestation de Bonne Execution\04 - Cloud et Virtualisation","abe/cloud-virtualisation"),
    (r"ABE - Attestation de Bonne Execution\05 - Visioconference et Telephonie","abe/visio-telephonie"),
    (r"ABE - Attestation de Bonne Execution\06 - Backup et Supervision", "abe/backup-supervision"),
    (r"ABE - Attestation de Bonne Execution\07 - Audit et Conseil",      "abe/audit-conseil"),
    (r"ABE - Attestation de Bonne Execution\08 - Autres",                "abe/autres"),
    # PV-recette
    (r"PO + PV-BL - Equivalence ABE\01 - Securite",                     "pv-recette/securite"),
    (r"PO + PV-BL - Equivalence ABE\02 - Reseaux",                      "pv-recette/reseaux"),
    (r"PO + PV-BL - Equivalence ABE\03 - Serveurs et Datacenter",        "pv-recette/serveurs-datacenter"),
    (r"PO + PV-BL - Equivalence ABE\04 - Cloud et Virtualisation",       "pv-recette/cloud-virtualisation"),
    (r"PO + PV-BL - Equivalence ABE\05 - Visioconference et Telephonie", "pv-recette/visio-telephonie"),
    (r"PO + PV-BL - Equivalence ABE\06 - Backup et Supervision",         "pv-recette/backup-supervision"),
    (r"PO + PV-BL - Equivalence ABE\07 - Audit et Conseil",              "pv-recette/audit-conseil"),
    # _Autres
    (r"_Autres\01 - CV et Certifications",                               "cvs"),
    (r"_Autres\02 - Marches Similaires (References)",                    "marches-similaires"),
]

# ─────────────────────────────────────────────────────────────────────────────

def collect_files(src_dir: Path):
    """Retourne tous les fichiers récursivement depuis src_dir."""
    if not src_dir.exists():
        return []
    return [f for f in src_dir.rglob("*") if f.is_file()]


def copy_mapping(src_rel: str, dst_rel: str, stats: dict):
    src_dir = SOURCE_ROOT / src_rel
    dst_dir = GED_ROOT   / dst_rel

    # Créer la destination
    dst_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(src_dir)
    if not files:
        print(f"  [VIDE] {src_rel}")
        return

    for src_file in files:
        ext = src_file.suffix.lower()
        if ext not in ALLOWED_EXT:
            stats["ignored"] += 1
            stats["ignored_files"].append(str(src_file.name))
            continue

        dst_file = dst_dir / src_file.name
        if dst_file.exists():
            stats["skipped"] += 1
            stats["skipped_by"][dst_rel] += 1
            continue

        shutil.copy2(src_file, dst_file)
        stats["copied"] += 1
        stats["copied_by"][dst_rel] += 1


def trigger_reindex(token: str) -> dict:
    url = "http://localhost:8000/v1/ged/reindex"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(url, headers=headers, timeout=30)
        return {"status_code": resp.status_code, "body": resp.text[:500]}
    except requests.exceptions.ConnectionError as e:
        return {"status_code": None, "body": f"ConnectionError: {e}"}
    except Exception as e:
        return {"status_code": None, "body": f"Error: {e}"}


def main():
    # ── Token JWT ──
    sys.path.insert(0, str(Path(__file__).parent.parent))  # D:/Neurones-IA/backend
    from adapters.auth.jwt_adapter import create_access_token
    token = create_access_token(1, "dtraore@neuronestech.com", "admin")

    # ── Copie ──
    stats = {
        "copied": 0,
        "skipped": 0,
        "ignored": 0,
        "ignored_files": [],
        "copied_by": defaultdict(int),
        "skipped_by": defaultdict(int),
    }

    print("=" * 60)
    print("COPIE GED — ABE / PV-recette / _Autres")
    print("=" * 60)

    for src_rel, dst_rel in MAPPINGS:
        src_path = SOURCE_ROOT / src_rel
        present = src_path.exists()
        print(f"\n[{'OK' if present else 'ABSENT'}] {src_rel}")
        print(f"       -> {dst_rel}")
        if present:
            copy_mapping(src_rel, dst_rel, stats)

    # ── Résumé ──
    print("\n" + "=" * 60)
    print("RESUME GLOBAL")
    print("=" * 60)
    print(f"  Fichiers copiés  : {stats['copied']}")
    print(f"  Skippés (existe) : {stats['skipped']}")
    print(f"  Ignorés (format) : {stats['ignored']}")

    if stats["copied_by"]:
        print("\n  Détail copiés par catégorie :")
        for cat, n in sorted(stats["copied_by"].items()):
            print(f"    {cat:<40} {n} fichier(s)")

    if stats["skipped_by"]:
        print("\n  Détail skippés par catégorie :")
        for cat, n in sorted(stats["skipped_by"].items()):
            print(f"    {cat:<40} {n} fichier(s)")

    # ── Réindex ──
    print("\n" + "=" * 60)
    print("DECLENCHEMENT REINDEX GED")
    print("=" * 60)
    result = trigger_reindex(token)
    if result["status_code"] is not None:
        print(f"  HTTP {result['status_code']}")
        print(f"  Réponse : {result['body']}")
    else:
        print(f"  ERREUR : {result['body']}")

    print("\nTerminé.")


if __name__ == "__main__":
    main()
