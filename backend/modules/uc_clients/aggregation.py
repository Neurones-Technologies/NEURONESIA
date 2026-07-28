"""Détection de signaux déterministes sur le portefeuille clients réel (table
dossiers) — mêmes heuristiques que l'ancienne analyse manuelle des fixtures
(backlog disproportionné, reste à encaisser élevé, volume de dossiers atypique),
désormais calculées sur les vrais agrégats, jamais inventées.
"""
from __future__ import annotations

_BACKLOG_RATIO_ALERTE = 0.5       # backlog > 50% du CA cumulé = à signaler
_RESTE_A_ENCAISSER_SEUIL_XOF = 50_000_000
_NB_DOSSIERS_DENSE = 30
_NB_DOSSIERS_RARE = 3
_CA_ELEVE_XOF = 200_000_000


def _m(xof: float) -> int:
    return round(xof / 1_000_000)


def detect_signals(client: dict) -> list[str]:
    """Constats factuels sur un client du portefeuille, dérivés uniquement de
    ses agrégats réels (jamais de texte inventé)."""
    signals: list[str] = []
    ca = client["ca_total_xof"]
    backlog = client["backlog_xof"]
    reste = client["reste_a_encaisser_xof"]
    nb = client["nb_dossiers"]

    if backlog < 0:
        signals.append(
            f"Backlog négatif ({_m(backlog)} M FCFA) — facturation possiblement en avance sur la livraison."
        )
    elif ca > 0 and backlog > ca * _BACKLOG_RATIO_ALERTE:
        signals.append(
            f"Backlog élevé ({_m(backlog)} M FCFA) rapporté au CA cumulé ({_m(ca)} M FCFA) — à vérifier avec la Direction Financière."
        )

    if reste >= _RESTE_A_ENCAISSER_SEUIL_XOF:
        signals.append(f"Reste à encaisser significatif ({_m(reste)} M FCFA) — à prioriser dans les relances.")

    if nb >= _NB_DOSSIERS_DENSE:
        signals.append(f"{nb} dossiers sur la période — un des comptes les plus actifs du portefeuille.")
    elif nb <= _NB_DOSSIERS_RARE and ca >= _CA_ELEVE_XOF:
        signals.append(
            f"Seulement {nb} dossier(s) pour {_m(ca)} M FCFA de CA cumulé — probablement un ou deux projets de grande taille."
        )

    return signals
