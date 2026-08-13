"""File d'alertes du cockpit commercial — §1 et §5 du compte-rendu DC.

« L'outil doit être capable d'identifier automatiquement les moments de pic
d'activité chez un compte et de déclencher une alerte proactive auprès du
commercial. »

Ce que ce module fait et ne fait pas, sans ambiguïté :

- IL DÉRIVE, il n'invente pas. Aucune heuristique nouvelle ici : chaque alerte
  est la mise en file d'un signal déjà calculé ailleurs (pic de commande, compte
  décroché, échéance dépassée, dossier incomplet à la signature). Un signal qui
  n'a pas de calcul en amont n'a pas d'alerte.
- IL S'ARRÊTE À L'APPLICATION. Aucun canal sortant n'existe : ni e-mail, ni
  notification mobile, ni SMS. « Déclencher une alerte auprès du commercial »
  s'entend donc, en l'état, comme « l'afficher quand il ouvre le cockpit ».
  Ouvrir un canal externe est un chantier distinct, et le prétendre fait ici
  serait un mensonge par omission.
- IL COMPTE LE BRUIT. Le DC redoute explicitement le volume (« combien d'alertes
  par semaine avant que cela devienne du bruit que l'on ignore »). Le retour porte
  donc le total AVANT plafonnement, et les alertes écartées restent écartées.

La clé d'alerte est DÉTERMINISTE : c'est ce qui permet de reconnaître la même
alerte d'un jour sur l'autre, donc de dire son âge, donc de l'écarter durablement.
Un identifiant aléatoire ferait réapparaître chaque matin une alerte déjà traitée.
"""
from __future__ import annotations

from datetime import date

SEVERITES_ORDRE = {"critique": 0, "attention": 1, "info": 2}

TYPES = {
    "pic_activite": "Pic d'activité",
    "compte_decroche": "Compte qui décroche",
    "opportunite_echue": "Échéance dépassée",
    "dossier_incomplet": "Dossier incomplet à la signature",
}


def build_alertes(
    pics: dict,
    dormance: dict,
    qualite: dict,
    today: date | None = None,
    limit: int = 25,
    montant_plancher_xof: int = 30_000_000,
) -> dict:
    """Assemble la file d'alertes à partir des signaux déjà calculés.

    `montant_plancher_xof` filtre les alertes de dossier : sous ce montant, une
    échéance dépassée est une correction de saisie, pas un sujet de direction
    commerciale. Le plancher est celui du seuil de traçage du cycle de vie, pour
    que « ce qui alerte » et « ce qui est tracé » désignent le même périmètre.
    """
    jour = today or date.today()
    alertes: list[dict] = []

    for p in pics.get("pics", []):
        alertes.append({
            "alert_key": f"pic:{p.get('client_id')}:{p.get('mois')}",
            "alert_type": "pic_activite",
            "severity": "attention",
            "subject_ref": p.get("client_id") or "",
            "subject_label": p.get("compte") or "",
            "salesperson_id": None,
            "commercial": p.get("commercial") or "",
            "montant_xof": p.get("montant_xof", 0),
            "titre": f"{p.get('compte')} commande {p.get('intensite')} × sa médiane",
            "detail": (
                f"{p.get('montant_xof', 0) // 1_000_000} M FCFA commandés sur {p.get('mois')} "
                f"({p.get('nb_commandes_mois')} commande(s)), contre une médiane mensuelle de "
                f"{p.get('mediane_mensuelle_xof', 0) // 1_000_000} M FCFA sur {p.get('nb_mois_historique')} mois."
            ),
            "action": "Reprendre contact pendant la fenêtre : un compte qui accélère est un compte qui arbitre.",
            "payload": {"mois": p.get("mois"), "intensite": p.get("intensite")},
        })

    for c in dormance.get("decrochages", []):
        impaye = c.get("alerte_impaye", False)
        alertes.append({
            "alert_key": f"decroche:{c.get('client_id') or c.get('compte')}",
            "alert_type": "compte_decroche",
            "severity": "critique" if impaye else "attention",
            "subject_ref": c.get("client_id") or "",
            "subject_label": c.get("compte") or "",
            "salesperson_id": None,
            "commercial": c.get("commercial") or "",
            "montant_xof": c.get("ca_total_xof", 0),
            "titre": f"{c.get('compte')} — {c.get('mois_silence')} mois sans commande",
            "detail": (
                f"Dernière commande le {c.get('derniere_commande')}. "
                f"{c.get('ca_total_xof', 0) // 1_000_000} M FCFA de CA historique sur "
                f"{c.get('nb_commandes')} commandes."
                + (
                    f" Ce compte porte {c.get('impaye_xof', 0) // 1_000_000} M FCFA d'impayé échu : "
                    "la relance se coordonne avec la Direction Financière."
                    if impaye else ""
                )
            ),
            "action": (
                "Relance à préparer avec la Direction Financière (impayé échu)."
                if impaye else "Relance commerciale à programmer."
            ),
            "payload": {"mois_silence": c.get("mois_silence"), "impaye": impaye},
        })

    # Les échéances dépassées viennent du panier « à requalifier », trié par
    # montant : ce qui fausse le forecast, c'est le poids de l'affaire.
    for o in qualite.get("a_requalifier", []):
        if o.get("montant_xof", 0) < montant_plancher_xof:
            continue
        alertes.append({
            "alert_key": f"echue:{o.get('opp_id')}",
            "alert_type": "opportunite_echue",
            "severity": "attention",
            "subject_ref": str(o.get("opp_id") or ""),
            "subject_label": o.get("name") or "",
            "salesperson_id": None,
            "commercial": o.get("commercial") or "",
            "montant_xof": o.get("montant_xof", 0),
            "titre": f"{o.get('name')} — échéance à requalifier",
            "detail": (
                f"{o.get('client')} · {o.get('stage')} · {o.get('montant_xof', 0) // 1_000_000} M FCFA, "
                f"échéance dépassée de {o.get('jours_de_retard')} jour(s). L'affaire reste ouverte alors que "
                "sa date de clôture est passée : elle continue de peser dans le forecast tant qu'elle n'est "
                "pas requalifiée."
            ),
            "action": "Faire réviser la date ou clore l'affaire dans l'ERP.",
            "payload": {"jours_de_retard": o.get("jours_de_retard")},
        })

    for o in qualite.get("a_closer", []):
        if not o.get("prioritaire") or o.get("montant_xof", 0) < montant_plancher_xof:
            continue
        alertes.append({
            "alert_key": f"incomplet:{o.get('opp_id')}",
            "alert_type": "dossier_incomplet",
            "severity": "critique",
            "subject_ref": str(o.get("opp_id") or ""),
            "subject_label": o.get("name") or "",
            "salesperson_id": None,
            "commercial": o.get("commercial") or "",
            "montant_xof": o.get("montant_xof", 0),
            "titre": f"{o.get('name')} — à signer avec un dossier incomplet",
            "detail": (
                f"{o.get('client')} · {o.get('stage')} · {o.get('montant_xof', 0) // 1_000_000} M FCFA, "
                f"échéance dans {o.get('jours_avant_echeance')} jour(s). Manque : "
                + ", ".join(o.get("defauts_libelles", []) or ["—"]) + "."
            ),
            "action": "Compléter le dossier avant la revue de signature.",
            "payload": {"defauts": o.get("defauts", [])},
        })

    alertes.sort(key=lambda a: (SEVERITES_ORDRE.get(a["severity"], 9), -a["montant_xof"]))

    par_type: dict[str, int] = {}
    for a in alertes:
        par_type[a["alert_type"]] = par_type.get(a["alert_type"], 0) + 1

    return {
        "as_of": jour.isoformat(),
        "alertes": alertes[:limit],
        "totaux": {
            "nb_total": len(alertes),
            "nb_affichees": min(limit, len(alertes)),
            "nb_critiques": sum(1 for a in alertes if a["severity"] == "critique"),
            "par_type": [
                {"type": t, "libelle": TYPES.get(t, t), "nb": n}
                for t, n in sorted(par_type.items(), key=lambda kv: -kv[1])
            ],
        },
        "diffusion": {
            "canal": "application uniquement",
            "limite": (
                "Aucun canal sortant n'existe : ni e-mail, ni notification mobile, ni SMS. Une alerte ne "
                "peut s'afficher que dans le cockpit, à l'ouverture. Ouvrir un canal externe est un "
                "chantier technique distinct."
            ),
        },
        "note": (
            "Chaque alerte est la mise en file d'un signal déjà calculé (pic de commande, décrochage, "
            "échéance dépassée, dossier incomplet) — aucune heuristique propre à ce module. Le plancher de "
            f"{montant_plancher_xof // 1_000_000} M FCFA sur les alertes de dossier aligne le périmètre des "
            "alertes sur celui du traçage du cycle de vie."
        ),
    }
