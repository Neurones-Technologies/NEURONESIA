import logging
import re
from datetime import datetime

from core.ports.llm_gateway import LLMGateway
from core.ports.crm_repository import CRMRepository
from core.domain.query import UserQuery, QueryResult, QueryIntent, ConversationTurn
from core.domain.document import Source
from core.services.rag_engine import RAGEngine
from config.settings import settings

logger = logging.getLogger(__name__)

_INTENT_CATEGORIES = ["rag", "local_db", "hybrid"]

_FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "jan": 1, "fév": 2, "fev": 2, "avr": 4,
    "juil": 7, "aoû": 8, "sep": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}

# Mots qui délimitent la fin d'un nom de client dans une question française
_CLIENT_NAME_STOP = (
    r"(?=\s*(?:\?|$|combien|quel|quell?e?s?|en\s+20\d\d|depuis|entre"
    r"|pour\s+(?:l[ae]?s?\s|quel)|a-t-il|avons|font|fait|donne|liste|affiche|montrez?))"
)

# Mots-clés orientés données CRM/ventes
_CRM_KEYWORDS = re.compile(
    r'\b(achat|achats|commande|commandes|bon\s+de\s+commande|bdc|bons\s+de\s+commande'
    r'|vente|ventes|facture|factures|facturation|contrat|contrats|historique\s+(?:de\s+)?(?:ventes?|commandes?|client)'
    r'|chiffre\s+d.affaires|\bca\b|montant|paiement|pay[eé]|impay[eé]|revenue'
    r'|combien\s+de\s+clients|combien\s+(?:avons|de\s+commandes?)'
    r'|FP/\d{4}/|d[eé]pense|d[eé]penses|top\s+clients?|meilleurs\s+clients?'
    r'|derni[eè]re\s+(?:commande|facture)|factures?\s+(?:en\s+attente|impay[eé]e?s?)'
    r'|ont\s+(?:pass[eé]|fait|r[eé]alis[eé])\s+(?:des\s+)?(?:achat|commande|vente)'
    r'|(?:le\s+|la\s+|un\s+|notre\s+)?commercial\b|responsable\s+(?:de\s+|du\s+)?(?:compte|client)'
    r'|chef\s+de\s+projet|gestionnaire|qui\s+(?:g[eè]re|s\'occupe|est\s+(?:en\s+charge|responsable))'
    r'|client\s+(?:cl[eé]|vip|strat[eé]gique)|fiche\s+client|donn[eé]es?\s+client'
    r'|article|articles|produit|produits|ligne\s+de\s+commande|lignes?\s+de\s+commande'
    r'|prestation|prestations|qu[\'e]\w*\s+(?:ont|a-t-il|ils?)\s+command[eé]'
    r'|dossier|num[eé]ro\s+de\s+dossier|r[eé]f[eé]rence\s+(?:dossier|commande))\b',
    re.IGNORECASE,
)

# Mots-clés orientés documents GED
_RAG_KEYWORDS = re.compile(
    r'\b(document|procédure|cv\b|curriculum|offre\s+technique|pv\s+de\s+recette|pv\b'
    r'|compte.rendu|fiche\s+technique|modèle|template|guide|manuel|norme|certification'
    r'|ged\b|dossier\s+technique|cahier\s+(?:de\s+)?(?:charges?|spec)|appel\s+d.offres?)\b',
    re.IGNORECASE,
)

_CLASSIFIER_SYSTEM = """Tu es un classificateur d'intention pour un assistant IA d'entreprise.
Analyse la question et réponds UNIQUEMENT avec l'une de ces catégories :

- local_db : question sur des données clients, ventes, commandes, achats, factures, contrats, CA, statistiques commerciales, bons de commande. Inclut TOUJOURS les questions avec des dates ("en octobre", "en 2024", "cette année").
- rag : question sur des documents internes (procédures, CVs, offres techniques, PVs de recette, comptes-rendus, fiches techniques, GED).
- hybrid : question nécessitant EXPLICITEMENT les deux sources (ex : "trouve le CV de l'ingénieur qui a travaillé avec le client X").

RÈGLE PRIORITAIRE : si la question mentionne achats, ventes, commandes, clients, factures, ou argent → réponds local_db.

Réponds avec un seul mot."""


def _classify_intent_rules(text: str) -> str | None:
    """Classification rapide par règles avant d'appeler le LLM."""
    has_crm = bool(_CRM_KEYWORDS.search(text))
    has_rag = bool(_RAG_KEYWORDS.search(text))
    if has_crm and not has_rag:
        return "local_db"
    if has_rag and not has_crm:
        return "rag"
    if has_crm and has_rag:
        return "hybrid"
    return None


def _extract_month_year(text: str) -> tuple[int | None, int | None]:
    """Extrait (mois, année) d'un texte français."""
    year: int | None = None
    if re.search(r"cette\s+ann[eé]e", text, re.IGNORECASE):
        year = datetime.now().year
    elif re.search(r"l[''']ann[eé]e\s+derni[eè]re", text, re.IGNORECASE):
        year = datetime.now().year - 1
    else:
        m = re.search(r'\b(20\d{2})\b', text)
        if m:
            year = int(m.group(1))

    month: int | None = None
    for name, num in _FRENCH_MONTHS.items():
        if re.search(rf'\b{re.escape(name)}\b', text, re.IGNORECASE):
            month = num
            break

    return month, year


def _extract_order_ref(text: str) -> str | None:
    m = re.search(r'\b(FP/\d{4}/\d+)\b', text, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _regex_extract_client(text: str) -> str:
    """Extraction rapide par regex — pas d'appel API."""
    q = text.strip()

    # 1. "du client X", "pour le client X", "client X", "pour X"
    m = re.search(
        r"(?:du\s+client|pour\s+le\s+client|pour\s+la\s+client|le\s+client|client|pour)\s+"
        r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s'\-&\.]{0,50}?)" + _CLIENT_NAME_STOP,
        q, re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip().rstrip("?.,").strip()
        if 2 < len(name) <= 60:
            return name

    # 2. "historique/factures/ventes de X"
    m = re.search(
        r"(?:historique|factures?|ventes?|commandes?|bons?\s+de\s+commande)\s+"
        r"(?:de\s+|d[eu]\s+)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s'\-&\.]{0,50}?)" + _CLIENT_NAME_STOP,
        q, re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip().rstrip("?.,").strip()
        if 2 < len(name) <= 60:
            return name

    # 3. Séquence tout en majuscules (ex : "VERSUS BANK", "MTN CI")
    m = re.search(r"\b([A-Z][A-Z0-9\s&'\-\.]{2,40}?)(?:\s*\?|$|\s+(?:combien|quel|en\s+20\d\d))", q)
    if m:
        name = m.group(1).strip()
        if len(name) > 2:
            return name

    return ""


class QueryDispatcher:
    """
    Route chaque question vers la bonne source de données :
    - RAG (documents GED)
    - LocalDB (miroir Odoo SQLite)
    - Hybrid (les deux)
    """

    def __init__(self, llm: LLMGateway, rag_engine: RAGEngine, crm_repo: CRMRepository):
        self._llm = llm
        self._rag_engine = rag_engine
        self._crm_repo = crm_repo

    async def dispatch(self, query: UserQuery) -> QueryResult:
        recent_history = self._format_history(query.history[-3:]) if query.history else ""
        full_context = f"{recent_history}\nQuestion actuelle : {query.text}".strip() if recent_history else query.text

        # 1. Règles rapides d'abord
        intent_str = _classify_intent_rules(query.text)

        # 2. LLM si les règles n'ont pas tranché
        if intent_str is None:
            intent_str = await self._llm.classify(full_context, _INTENT_CATEGORIES)

        intent = QueryIntent(intent_str)
        logger.debug("Intent classifié : %s pour '%s'", intent, query.text[:60])

        sources: list[Source] = []
        crm_context = ""

        if intent in (QueryIntent.RAG, QueryIntent.HYBRID):
            sources = await self._rag_engine.search(query.text)

        if intent in (QueryIntent.LOCAL_DB, QueryIntent.HYBRID):
            crm_context = await self._build_crm_context(full_context)

        answer = await self._generate_answer(query, sources, crm_context, intent)
        return QueryResult(answer=answer, intent=intent, sources=sources)

    async def _build_crm_context(self, question: str) -> str:
        # Extraire la question courante (sans l'historique)
        q = question.split("Question actuelle :")[-1].strip()

        # 1. Lookup par référence BDC (FP/YYYY/NNNNN)
        ref = _extract_order_ref(q)
        if ref:
            return await self._get_order_by_ref(ref)

        # 2. Chercher un nom de client
        client_name = await self._extract_client_name(question)

        # 3. Extraction mois/année pour filtrer les stats ou les commandes
        month, year = _extract_month_year(q)

        # 4. Pas de client → stats agrégées (globales ou par période)
        if not client_name:
            if month and year:
                return await self._get_month_stats(month, year)
            if year:
                return await self._get_year_stats(year)
            return await self._get_aggregate_stats()

        # 5. Client trouvé → données détaillées
        client = await self._crm_repo.get_client(client_name)
        if not client:
            # Suggérer des clients proches
            suggestions = await self._crm_repo.search_clients(client_name.split()[0])
            if suggestions:
                names = ", ".join(c.name for c in suggestions[:5])
                return f"Client '{client_name}' introuvable. Clients similaires : {names}"
            return f"Aucun client trouvé pour '{client_name}'."

        sale_orders = await self._crm_repo.get_sale_orders(client.client_id, year=year)
        # Filtre mois en mémoire si nécessaire
        if month and year and sale_orders:
            sale_orders = [
                o for o in sale_orders
                if self._order_matches_month(o.get("date_order", ""), month)
            ]

        invoices = await self._crm_repo.get_invoices(client.client_id)
        contracts = await self._crm_repo.get_contracts(client.client_id)
        projects = await self._crm_repo.get_projects(client.client_id)

        lines = [f"Client : {client.name}"]

        if sale_orders:
            total_ventes = sum(o["amount"] for o in sale_orders)
            period_label = f" ({_month_name(month)} {year})" if month and year else (f" ({year})" if year else "")
            lines.append(
                f"\nBons de commande{period_label} : {len(sale_orders)} | Total : {total_ventes:,.0f} {sale_orders[0]['currency']}"
            )
            lines.append("Détail (10 derniers) :")
            for o in sale_orders[:10]:
                detail = f"  - {o['name']} | {o['date_order']} | {o['amount']:,.0f} {o['currency']} | {o['state']}"
                if o.get("salesperson"):
                    detail += f" | Commercial : {o['salesperson']}"
                if o.get("dossier"):
                    detail += f" | Dossier : {o['dossier']}"
                lines.append(detail)
                if o.get("lines"):
                    articles = " ; ".join(
                        f"{l['product']} (x{l['qty']:g}, {l['subtotal']:,.0f} XOF)"
                        for l in o["lines"][:5]
                        if l.get("product")
                    )
                    if articles:
                        lines.append(f"      Articles : {articles}")
        elif year or month:
            period_label = f"{_month_name(month)} {year}" if month and year else str(year or "")
            lines.append(f"\nAucun bon de commande trouvé pour {period_label}.")

        if invoices:
            paid = [i for i in invoices if i.status.value == "paid"]
            pending = [i for i in invoices if i.status.value == "pending"]
            total_facture = sum(i.amount for i in invoices)
            lines.append(
                f"\nFactures : {len(invoices)} total ({len(paid)} payées, {len(pending)} en attente) | {total_facture:,.0f} XOF"
            )

        if contracts:
            lines.append(f"\nContrats : {len(contracts)}")
            for c in contracts[:3]:
                lines.append(f"  - {c.title} | expire {c.end_date.strftime('%d/%m/%Y')} | {c.value:,.0f} {c.currency}")

        if projects:
            lines.append(f"\nProjets : {len(projects)}")
            for p in projects[:3]:
                lines.append(f"  - {p.title}")

        return "\n".join(lines)

    @staticmethod
    def _order_matches_month(date_str: str, month: int) -> bool:
        """Vérifie si une date au format dd/mm/yyyy correspond au mois donné."""
        parts = date_str.split("/")
        if len(parts) == 3:
            try:
                return int(parts[1]) == month
            except ValueError:
                pass
        return True  # Si on ne peut pas parser, on garde

    async def _get_month_stats(self, month: int, year: int) -> str:
        try:
            stats = await self._crm_repo.get_month_stats(year, month)
            revenue_m = stats["revenue_xof"] / 1_000_000
            month_label = _month_name(month)
            return (
                f"Statistiques {month_label} {year} (miroir Odoo) :\n"
                f"- Clients ayant passé commande : {stats['clients_with_orders']:,}\n"
                f"- Bons de commande : {stats['orders_count']:,}\n"
                f"- Chiffre d'affaires : {revenue_m:.1f} M XOF\n"
            )
        except Exception as e:
            logger.warning("Impossible de récupérer les stats du mois : %s", e)
            return ""

    async def _get_year_stats(self, year: int) -> str:
        try:
            stats = await self._crm_repo.get_year_stats(year)
            revenue_m = stats["revenue_xof"] / 1_000_000
            return (
                f"Statistiques {year} (miroir Odoo) :\n"
                f"- Clients ayant passé commande : {stats['clients_with_orders']:,}\n"
                f"- Bons de commande : {stats['orders_count']:,}\n"
                f"- Chiffre d'affaires : {revenue_m:.1f} M XOF\n"
            )
        except Exception as e:
            logger.warning("Impossible de récupérer les stats de l'année : %s", e)
            return ""

    async def _get_order_by_ref(self, ref: str) -> str:
        order = await self._crm_repo.get_order_by_ref(ref)
        if not order:
            return f"Bon de commande {ref} introuvable dans la base locale."
        parts = [
            f"Bon de commande {order['name']} :",
            f"- Client : {order['client_name']}",
            f"- Montant : {order['amount']:,.0f} {order['currency']}",
            f"- Date : {order['date_order']}",
            f"- État : {order['state']}",
        ]
        if order.get("salesperson"):
            parts.append(f"- Commercial : {order['salesperson']}")
        if order.get("dossier"):
            parts.append(f"- Dossier : {order['dossier']}")
        if order.get("lines"):
            parts.append("- Articles :")
            for l in order["lines"][:15]:
                if l.get("product"):
                    parts.append(f"    • {l['product']} | Qté : {l['qty']:g} | {l['subtotal']:,.0f} XOF")
        return "\n".join(parts)

    async def _get_aggregate_stats(self) -> str:
        try:
            stats = await self._crm_repo.get_aggregate_stats()
            revenue_b = stats["total_revenue_xof"] / 1_000_000_000
            return (
                f"Statistiques globales Neurones Technologies (miroir Odoo) :\n"
                f"- Clients actifs : {stats['clients']:,}\n"
                f"- Factures : {stats['invoices']:,} (dont {stats['invoices_paid']:,} payées)\n"
                f"- Bons de commande : {stats['sale_orders']:,}\n"
                f"- Chiffre d'affaires total : {revenue_b:.1f} Mds XOF\n"
            )
        except Exception as e:
            logger.warning("Impossible de récupérer les stats globales : %s", e)
            return ""

    async def _extract_client_name(self, context: str) -> str:
        q = context.split("Question actuelle :")[-1].strip()

        # 1. Regex rapide
        name = _regex_extract_client(q)
        if name:
            return name

        # 2. LLM fallback
        try:
            result = await self._llm.extract(
                prompt=(
                    "Dans la phrase suivante, quel est le NOM PROPRE du client ou de l'entreprise ?\n"
                    "Réponds avec UNIQUEMENT le nom (1 à 5 mots max), rien d'autre.\n"
                    "Si aucun nom propre de client n'est mentionné, réponds : AUCUN"
                ),
                text=q,
                max_tokens=15,
            )
            name = result.strip().split("\n")[0].strip("\"'.,")
            if name.upper() not in ("AUCUN", "", "CLIENT"):
                return name
        except Exception as e:
            logger.warning("LLM extraction failed: %s", e)

        return ""

    async def _generate_answer(
        self,
        query: UserQuery,
        sources: list[Source],
        crm_context: str,
        intent: QueryIntent,
    ) -> str:
        history = self._format_history(query.history)
        rag_context = await self._rag_engine.build_context(sources, max_tokens=settings.max_context_tokens) if sources else ""

        context_block = ""
        if rag_context:
            context_block += f"\n\n## Documents de référence\n{rag_context}"
        if crm_context:
            context_block += f"\n\n## Données client (Odoo)\n{crm_context}"

        system = (
            "Tu es l'assistant IA interne de Neurones Technologies. "
            "Tu réponds en français, de façon précise et professionnelle. "
            "Tu cites tes sources entre crochets (ex: [Offre-SGBCI-2024.docx]) UNIQUEMENT si des documents de référence sont fournis. "
            "Si tu ne trouves pas l'information, dis-le clairement."
        )
        user = f"{history}\n\nQuestion : {query.text}{context_block}"

        return await self._llm.generate(system=system, user=user, max_tokens=1500)

    def _format_history(self, history: list[ConversationTurn]) -> str:
        if not history:
            return ""
        recent = history[-settings.max_history_turns:]
        lines = []
        for turn in recent:
            prefix = "Utilisateur" if turn.role == "user" else "Assistant"
            lines.append(f"{prefix}: {turn.content}")
        return "\n".join(lines)


def _month_name(month: int | None) -> str:
    names = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
    }
    return names.get(month or 0, "")
