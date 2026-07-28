"""
Endpoint d'interrogation directe des données Odoo (miroir SQLite).
Fonctionne SANS clé Anthropic — pure logique Python + SQLite.
"""
import re
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import asyncio

router = APIRouter(prefix="/crm", tags=["crm"])


class CRMQuery(BaseModel):
    question: str


def _extract_client_name(question: str) -> str:
    """
    Extraction rule-based du nom client depuis la question.
    """
    q = question.strip()

    # Pattern 1 : "client X", "pour X", "du client X"
    m = re.search(r"(?:du\s+client|pour\s+le\s+client|pour\s+la\s+client|client|pour)\s+(.+?)(?:\s*\?|$)", q, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip("?").strip()
        if len(name) > 2:
            return name

    # Pattern 2 : "historique de X", "factures de X", "ventes de X"
    m = re.search(r"(?:historique|factures?|ventes?|commandes?|bons?\s+de\s+commande)\s+(?:de\s+|d[eu]\s+)?(.+?)(?:\s*\?|$)", q, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip("?").strip()
        if len(name) > 2:
            return name

    # Fallback : dernier segment en majuscules (ex: "VERSUS BANK", "DISTRIMAT")
    # Cherche une séquence de mots qui commencent par une majuscule à la fin de la phrase
    m = re.search(r"([A-Z][A-Z0-9\s\'\-&\.]{2,}?)(?:\s*\?|$)", q)
    if m:
        name = m.group(1).strip().rstrip("?").strip()
        if len(name) > 2:
            return name

    # Dernier mot significatif en majuscule
    words = q.split()
    caps = [w.strip("?.,") for w in words if len(w) > 3 and w[0].isupper() and w not in
            {"Quel", "Quels", "Quelle", "Quelles", "Est", "Sont", "Avons", "Montrez",
             "Donne", "Affiche", "Liste", "Historique", "Ventes", "Factures", "Client"}]
    return caps[-1] if caps else ""


def _format_response(client_name: str, client_row, sales, invoices) -> str:
    if not client_row:
        return (
            f"Aucun client trouvé pour **{client_name}** dans la base locale.\n\n"
            f"*Conseil : vérifiez l'orthographe ou relancez `python scripts/run_sync.py` "
            f"pour mettre à jour les données Odoo.*"
        )

    cid, name, sector, email = client_row
    lines = [f"## {name}\n"]

    if sector:
        lines.append(f"**Secteur :** {sector}")
    if email:
        lines.append(f"**Contact :** {email}")

    # Ventes
    if sales:
        total = sum(r[2] for r in sales)
        currency = sales[0][3] if sales else "XOF"
        lines.append(f"\n### Bons de commande ({len(sales)} au total)")
        lines.append(f"**Volume total : {total:,.0f} {currency}**\n")
        lines.append("| Référence | Date | Montant | Statut |")
        lines.append("|-----------|------|---------|--------|")
        for ref, date, amount, cur, state in sales[:15]:
            d = str(date)[:10] if date else "—"
            state_fr = {"sale": "Confirmé", "done": "Terminé", "draft": "Brouillon", "cancel": "Annulé"}.get(state, state)
            lines.append(f"| {ref} | {d} | {amount:,.0f} {cur} | {state_fr} |")
        if len(sales) > 15:
            lines.append(f"\n*… et {len(sales) - 15} bons de commande supplémentaires.*")
    else:
        lines.append("\n*Aucun bon de commande trouvé pour ce client.*")

    # Factures
    if invoices:
        total_fact = sum(r[1] for r in invoices)
        paid = sum(1 for r in invoices if r[3] == "paid")
        pending = sum(1 for r in invoices if r[3] == "pending")
        lines.append(f"\n### Factures ({len(invoices)} au total — {total_fact:,.0f} XOF)")
        lines.append(f"- Payées : **{paid}**")
        lines.append(f"- En attente : **{pending}**")
    else:
        lines.append("\n*Aucune facture trouvée pour ce client.*")

    lines.append("\n---")
    lines.append("*Source : miroir SQLite local (données Odoo)*")
    return "\n".join(lines)


async def _query_db(question: str):
    """Recherche dans SQLite sans LLM."""
    import aiosqlite
    from config.settings import settings

    client_name = _extract_client_name(question)
    if not client_name:
        yield {"type": "token", "content": "Je n'ai pas pu identifier de nom de client dans votre question. "
               "Essayez par exemple : *\"Historique du client VERSUS BANK\"*"}
        yield {"type": "done", "intent": "local_db", "sources": []}
        return

    async with aiosqlite.connect(settings.local_db_path) as db:
        db.row_factory = aiosqlite.Row

        # Recherche client (LIKE fuzzy)
        search = f"%{client_name}%"
        async with db.execute(
            "SELECT client_id, name, sector, contact_email FROM clients WHERE name LIKE ? LIMIT 1",
            (search,)
        ) as cur:
            client_row = await cur.fetchone()

        # Si pas trouvé, essayer avec chaque mot
        if not client_row:
            for word in client_name.split():
                if len(word) > 3:
                    async with db.execute(
                        "SELECT client_id, name, sector, contact_email FROM clients WHERE name LIKE ? LIMIT 1",
                        (f"%{word}%",)
                    ) as cur:
                        client_row = await cur.fetchone()
                    if client_row:
                        break

        sales, invoices = [], []
        if client_row:
            cid = client_row["client_id"]
            async with db.execute(
                "SELECT name, date_order, amount, currency, state FROM sale_orders "
                "WHERE client_id = ? ORDER BY date_order DESC LIMIT 50",
                (cid,)
            ) as cur:
                sales = await cur.fetchall()
                sales = [tuple(r) for r in sales]

            async with db.execute(
                "SELECT invoice_id, amount, currency, status FROM invoices "
                "WHERE client_id = ? ORDER BY due_date DESC LIMIT 50",
                (cid,)
            ) as cur:
                invoices = await cur.fetchall()
                invoices = [tuple(r) for r in invoices]

        response = _format_response(
            client_name,
            tuple(client_row) if client_row else None,
            sales,
            invoices,
        )

    # Streamer le résultat token par token (mots)
    words = response.split(" ")
    for i, word in enumerate(words):
        await asyncio.sleep(0.01)
        yield {"type": "token", "content": word + (" " if i < len(words) - 1 else "")}

    yield {"type": "done", "intent": "local_db", "sources": []}


@router.post("/query")
async def crm_query(body: CRMQuery):
    """
    Interroge le miroir SQLite Odoo sans clé LLM.
    Retourne un stream SSE identique au endpoint /chat/query.
    """
    async def event_stream():
        async for chunk in _query_db(body.question):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/client/{name}")
async def get_client(name: str):
    """Lookup direct d'un client par nom (JSON brut)."""
    import aiosqlite
    from config.settings import settings

    async with aiosqlite.connect(settings.local_db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT client_id, name, sector, contact_email FROM clients WHERE name LIKE ? LIMIT 5",
            (f"%{name}%",)
        ) as cur:
            clients = [dict(r) for r in await cur.fetchall()]

        if not clients:
            return {"clients": [], "message": f"Aucun client trouvé pour '{name}'"}

        result = []
        for c in clients:
            cid = c["client_id"]

            async with db.execute(
                "SELECT name, date_order, amount, currency, state FROM sale_orders "
                "WHERE client_id = ? ORDER BY date_order DESC LIMIT 20",
                (cid,)
            ) as cur:
                sales = [dict(r) for r in await cur.fetchall()]

            async with db.execute(
                "SELECT invoice_id, amount, currency, status FROM invoices "
                "WHERE client_id = ? ORDER BY due_date DESC LIMIT 20",
                (cid,)
            ) as cur:
                invoices = [dict(r) for r in await cur.fetchall()]

            result.append({**c, "sale_orders": sales, "invoices": invoices})

        return {"clients": result}
