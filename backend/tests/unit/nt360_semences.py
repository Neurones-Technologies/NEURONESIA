"""Semences de test : depuis la bascule, les lecteurs de commandes lisent
v_sale_orders (nt360 fait foi), plus sale_orders. Un test qui sème des
SaleOrderModel doit donc aussi semer leur pendant nt360 et créer les vues.
"""
from db.models import Nt360CommandeModel, SaleOrderModel
from db.views import create_views


def avec_nt360(objets: list) -> list:
    """Ajoute, pour chaque commande Odoo valide, la commande nt360 équivalente
    (même N° FP, montant, client, commercial, date). Les devis et annulées n'ont
    pas de pendant : nt360 ne publie que des commandes valides."""
    commandes = [
        Nt360CommandeModel(
            fp=o.name, cas=o.amount, client=o.client_name or "", am=o.salesperson_name or "",
            date_commande=o.date_order.date() if o.date_order else None,
            year_po=o.date_order.year if o.date_order else None, raw={},
        )
        for o in objets
        if isinstance(o, SaleOrderModel) and (o.state or "sale") in ("sale", "done")
    ]
    return [*objets, *commandes]


__all__ = ["avec_nt360", "create_views"]
