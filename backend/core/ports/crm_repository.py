from abc import ABC, abstractmethod
from typing import Optional

from core.domain.client import Client, Contract, Invoice, Project


class CRMRepository(ABC):
    """
    Interface pour les données CRM (clients, contrats, factures, projets).
    Implémentée par LocalCRMAdapter (SQLite miroir) par défaut.
    OdooAdapter disponible pour les cas nécessitant des données temps-réel.
    """

    @abstractmethod
    async def get_client(self, name_or_id: str) -> Optional[Client]:
        """Récupère un client par nom ou identifiant."""

    @abstractmethod
    async def search_clients(self, query: str) -> list[Client]:
        """Recherche des clients par nom partiel."""

    @abstractmethod
    async def get_contracts(self, client_id: str) -> list[Contract]:
        """Retourne tous les contrats d'un client."""

    @abstractmethod
    async def get_expiring_contracts(self, days_threshold: int = 60) -> list[Contract]:
        """Retourne les contrats expirant dans les N prochains jours."""

    @abstractmethod
    async def get_invoices(self, client_id: str) -> list[Invoice]:
        """Retourne toutes les factures d'un client."""

    @abstractmethod
    async def get_projects(self, client_id: str) -> list[Project]:
        """Retourne l'historique des projets d'un client."""

    @abstractmethod
    async def get_sale_orders(self, client_id: str, year: int | None = None) -> list[dict]:
        """Retourne les bons de commande d'un client, optionnellement filtrés par année."""

    @abstractmethod
    async def get_aggregate_stats(self) -> dict:
        """Retourne les compteurs globaux : clients, factures, bons de commande."""

    @abstractmethod
    async def get_year_stats(self, year: int) -> dict:
        """Statistiques pour une année donnée : clients actifs, nombre BDC, CA."""

    @abstractmethod
    async def get_month_stats(self, year: int, month: int) -> dict:
        """Statistiques pour un mois donné : clients actifs, nombre BDC, CA."""

    @abstractmethod
    async def get_clients_by_month(self, year: int, limit: int = 10) -> dict[int, list[dict]]:
        """Pour chaque mois de l'année, les N clients ayant le plus commandé
        (par nombre de commandes). Retourne {mois: [{client, nb_commandes, ca_xof}, ...]}."""

    @abstractmethod
    async def get_order_by_ref(self, ref: str) -> dict | None:
        """Cherche un bon de commande par référence (ex: FP/2026/12576)."""

    @abstractmethod
    async def get_recent_orders(self, limit: int = 5, year: int | None = None) -> list[dict]:
        """Retourne les N derniers bons de commande (tous clients), triés par date desc."""

    @abstractmethod
    async def get_top_clients(self, limit: int = 5, year: int | None = None) -> list[dict]:
        """Retourne les N clients avec le plus grand CA, optionnellement filtré par année."""

    @abstractmethod
    async def get_unpaid_invoices(self, limit: int = 10) -> list[dict]:
        """Retourne les factures non payées les plus anciennes (par échéance)."""

    @abstractmethod
    async def get_unpaid_exposure(self) -> dict:
        """Exposition totale aux impayés : résumé global + retard >90j + top débiteurs."""

    @abstractmethod
    async def get_pipeline_stats(self) -> dict:
        """Statistiques du pipeline commercial : total pondéré, par stade, par commercial."""

    @abstractmethod
    async def get_hot_leads(self, limit: int = 10) -> list[dict]:
        """Leads les plus chauds triés par expected_revenue × probability."""

    @abstractmethod
    async def get_revenue_by_salesperson(self, year: int | None = None, quarter: int | None = None) -> list[dict]:
        """CA et métriques par commercial. Retourne [{salesperson, ca_total, nb_commandes, nb_clients, panier_moyen}]."""

    @abstractmethod
    async def score_client_risk(self, client_id: str | None = None, limit: int = 20) -> list[dict]:
        """Score de risque par client (0-100). Composite : retard paiement + impayés + inactivité."""

    @abstractmethod
    async def get_revenue_by_sector(self, year: int | None = None, limit: int = 20) -> list[dict]:
        """CA agrégé par secteur d'activité du client. Retourne [{secteur, ca_total, nb_clients, nb_commandes}]."""

    @abstractmethod
    async def get_quarterly_forecast(self, year: int | None = None) -> dict:
        """Prévision CA fin de trimestre via tendance mensuelle. Retourne optimiste/réaliste/pessimiste."""

    @abstractmethod
    async def get_lost_deals(self, limit: int = 20) -> dict:
        """Opportunités perdues (historique) : top N + agrégats par client et par commercial."""

    @abstractmethod
    async def get_order_lines(self, limit: int = 20000) -> list[dict]:
        """Lignes de commande réelles (sale_orders non annulées), pour analyses
        transversales par produit/catégorie (montée en valeur)."""

    @abstractmethod
    async def get_top_suppliers(self, limit: int = 20) -> list[dict]:
        """Fournisseurs réels (purchase_orders) : montant commandé, nb commandes,
        première/dernière commande, montant moyen, engagement sur les 12
        derniers mois glissants, détail des commandes récentes. Pas de dette
        (factures fournisseurs non synchronisées depuis Odoo)."""

    @abstractmethod
    async def get_supplier_intelligence(self, limit: int = 20) -> list[dict]:
        """5 indicateurs différenciants par fournisseur (crédit/consommation, cash
        prévisionnel 30/60/90j, marge de sous-traitance par mission liée, fiabilité
        de paiement réelle, risque de rupture proxy) — cf. LocalCRMAdapter pour le
        détail du calcul. Nécessite les factures fournisseurs (supplier_invoices) et
        le lien achat→dossier (purchase_orders.dossier_id), synchronisés depuis ce soir."""

    @abstractmethod
    async def get_client_portfolio(self, limit: int = 50, clients: list[str] | None = None) -> list[dict]:
        """Portefeuille clients réel (table dossiers) : CA, backlog, reste à
        encaisser, nb dossiers, enrichi du secteur/contact quand disponibles.

        `clients` (noms exacts) remplace le top `limit` par CA par la liste
        demandée — un compte hors du top CA reste alors visible."""

    @abstractmethod
    async def get_cross_sell_opportunities(self, product_anchor: str, product_target: str | None = None, limit: int = 20) -> list[dict]:
        """Clients ayant acheté product_anchor mais pas product_target — opportunités cross-sell."""

    @abstractmethod
    async def search_orders_by_product(self, product_query: str, year: int | None = None) -> list[dict]:
        """Retourne les commandes contenant un produit correspondant à la recherche."""

    @abstractmethod
    async def get_revenue_by_product(self, year: int | None = None, limit: int = 30) -> list[dict]:
        """Agrège le CA par nom de produit. Retourne [{product, total_revenue, order_count, qty_total}]."""

    @abstractmethod
    async def get_client_retention(self, year: int | None = None) -> dict:
        """Calcule rétention, churn et nouveaux clients entre year-1 et year."""

    @abstractmethod
    async def get_dossier(self, ref: str) -> dict | None:
        """Récupère un dossier par sa ref DC/YYYY/XXXX ou par ref BDC FP/YYYY/XXXXX."""

    @abstractmethod
    async def get_dossiers_by_client(self, client_name: str, year: int | None = None) -> list[dict]:
        """Tous les dossiers d'un client (recherche partielle)."""

    @abstractmethod
    async def get_margin_stats(self, year: int | None = None) -> dict:
        """Statistiques globales de marge : CA, dépenses, marges, encaissements."""

    @abstractmethod
    async def get_top_margin_dossiers(self, limit: int = 10, year: int | None = None,
                                      metric: str = "marge_provisoire") -> list[dict]:
        """Top dossiers par marge ou par CA."""

    @abstractmethod
    async def sync_from_odoo(self) -> dict:
        """
        Synchronise les données depuis Odoo vers le miroir local.
        Retourne un résumé : {clients: N, contracts: N, invoices: N, projects: N}
        """
