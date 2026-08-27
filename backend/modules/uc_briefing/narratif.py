"""Rédaction du briefing quotidien par Claude, à partir des faits déjà calculés
par facts.py (jamais recalculés ni inventés par le LLM). Repli déterministe
(les faits bruts, en liste) si Claude échoue — jamais de briefing vide.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Puces et numérotation en début de ligne uniquement — la numérotation exige un
# séparateur (« 1. » / « 2) ») pour ne pas confondre avec un montant de tête.
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-•*–—]+\s*|\d{1,2}[.)]\s+)")

ROLE_LABELS = {
    "dg": "la Direction Générale",
    "dir_commercial": "la Direction Commerciale",
    "dir_financier": "la Direction Financière",
    "dir_operations": "la Direction des Opérations",
    "commercial": "un commercial du terrain",
}

# Ce sur quoi CE rôle précis rend des comptes — sans ce filtre, le LLM produit
# le même résumé générique pour tout le monde (cause principale du narratif
# jugé « lapidaire, non contextuel » : un fait sans le rattacher à la décision
# que ce rôle doit prendre n'a pas de valeur ajoutée).
ROLE_FOCUS = {
    "dg": (
        "l'arbitrage et l'atterrissage de l'exercice : les comptes nommés dont le rythme de commande "
        "décroche et ce que leur silence coûte à date, la position nette de trésorerie (fournisseurs à "
        "payer contre clients à encaisser, l'entreprise payant ses achats avant d'être payée), la "
        "concentration du portefeuille, et les dossiers qu'aucune direction ne peut trancher seule"
    ),
    "dir_commercial": (
        "la fiabilité du forecast, les opportunités qui glissent ou perdent leur sponsor, et la couverture "
        "de l'équipe commerciale par rapport aux objectifs"
    ),
    "dir_financier": (
        "l'encaissement à venir, les comptes dont le comportement de paiement se dégrade, et la marge réelle "
        "par rapport à la marge annoncée en début de dossier"
    ),
    "dir_operations": (
        "le backlog qui ne se facture pas au rythme prévu, les fournisseurs qui mettent les projets en retard, "
        "et la visibilité de charge par practice"
    ),
    "commercial": (
        "les ruptures de rythme sur ses propres comptes, les renouvellements et échéances à venir sur son "
        "portefeuille, et les actions concrètes à mener cette semaine"
    ),
}

# Le briefing long. La structure suit celle de la trame quotidienne : le chiffre
# et son mouvement, puis les exceptions, puis ce qu'on fait aujourd'hui. Elle a
# remplacé un plan libre en trois temps (« le fait le plus significatif », « un
# second fait qui le nuance », « une recommandation ») qui laissait au modèle le
# soin de décider ce qui était significatif — c'est-à-dire l'essentiel.
_SYSTEM_TEMPLATE = (
    "Tu es l'assistant de direction d'une entreprise ivoirienne d'intégration informatique "
    "(S2I). Tu rédiges le briefing quotidien pour {role_label}, dont le pilotage porte sur "
    "{role_focus}. Tu écris à partir de faits déjà calculés et vérifiés — jamais inventés, "
    "jamais recalculés — mais ton travail est de les RELIER et de dire ce qu'ils signifient "
    "pour CE rôle précis, pas de les paraphraser.\n\n"
    "Les faits te sont donnés RANGÉS EN TROIS BLOCS, dans l'ordre de lecture voulu. Cet ordre "
    "n'est pas indicatif : il vient des questions que ce rôle se pose chaque matin, et tu ne "
    "le réorganises pas.\n\n"
    "Structure attendue, sans titres ni markdown, un paragraphe par bloc :\n"
    "1. LES CHIFFRES — où en est-on, et surtout ce qui a bougé. Une variation citée sans son "
    "point de comparaison ne vaut rien : reprends toujours celui qui accompagne le fait.\n"
    "2. LES EXCEPTIONS — ce qui sort de l'ordinaire et pourquoi c'est un problème maintenant. "
    "Nomme les comptes, les dossiers et les dates que les faits nomment.\n"
    "3. LES DÉCISIONS DU JOUR — au plus trois, concrètes, datées, et chacune rattachée à un "
    "fait cité plus haut. Si les faits n'en portent aucune, dis-le au lieu d'en inventer.\n\n"
    "QUATRE PHRASES AU PLUS PAR PARAGRAPHE. Le plan en trois blocs, laissé sans borne, a "
    "produit une analyse coupée au milieu d'une phrase pour les cinq rôles : une analyse "
    "tronquée ne se lit pas, et rien dans la page ne signale au lecteur qu'elle est "
    "incomplète.\n\n"
    "Ton direct, factuel, sans emphase artificielle. Chaque phrase contient soit un chiffre "
    "soit une action — jamais une phrase de transition vide. Quand un fait porte une réserve "
    "(« les avoirs ne sont pas déduits », « le retard est sous-estimé »), tu la reprends : un "
    "chiffre publié sans sa réserve est plus dangereux qu'un chiffre absent."
)


# Résumé de tête de cockpit : 5 lignes, une idée par ligne. C'est ce que le
# lecteur voit avant tout le reste ; l'analyse complète reste disponible plus
# bas dans la vue, donc ici on cherche la densité, pas l'exhaustivité.
#
# CE MODÈLE NE CHOISIT PLUS CE QU'IL RACONTE. La consigne d'origine — « exactement
# 5 lignes, de ce qui engage le plus à ce qui engage le moins » — lui demandait de
# classer lui-même une liste de faits dont rien ne disait l'importance relative.
# Résultat observé sur le cockpit commercial : trois des cinq lignes portaient sur
# des agrégats hors trame (le lead le plus chaud, la concentration des pertes)
# pendant que « combien j'ai commandé hier » et « qu'est-ce qui dort » restaient
# à quai. La hiérarchie vit désormais dans le catalogue (uc_briefing.preferences),
# les faits arrivent déjà classés, et le modèle les REFORMULE dans l'ordre reçu.
_SYSTEM_RESUME = (
    "Tu es l'assistant de direction d'une entreprise ivoirienne d'intégration informatique "
    "(S2I). Tu résumes la situation du jour pour {role_label}, dont le pilotage porte sur "
    "{role_focus}.\n\n"
    "Les faits te sont donnés DÉJÀ CLASSÉS par ordre d'importance pour ce rôle. Tu ne "
    "choisis pas lesquels retenir et tu ne changes pas leur ordre : tu les reformules.\n\n"
    "Contraintes STRICTES :\n"
    "- UNE LIGNE PAR FAIT FOURNI, dans l'ordre où ils arrivent, sans en écarter aucun et "
    "sans en ajouter.\n"
    "- Une seule idée par ligne, une phrase complète, 20 mots maximum.\n"
    "- Chaque ligne contient un chiffre issu du fait correspondant, ou l'action qu'il porte. "
    "Jamais de phrase de transition, jamais de généralité.\n"
    "- Pas de puce, pas de tiret, pas de numéro en début de ligne, pas de markdown, pas de "
    "titre.\n"
    "- N'invente aucun chiffre : utilise uniquement ceux du fait que tu reformules, sans les "
    "recalculer.\n"
    "- Quand un fait nomme un compte, une date ou un nombre de jours, reprends-les tels "
    "quels : un compte nommé et daté vaut mieux qu'un total anonyme.\n"
    "- Un pourcentage ne se cite qu'accompagné de son point de comparaison fourni dans le "
    "fait (seuil, période, ou valeur N-1). Un pourcentage nu est interdit.\n"
    "- Une variation (« vs hier », « depuis le 13/08 ») se reprend avec sa date : une "
    "comparaison sans son point de départ est invérifiable."
)


_MAX_RESUME_LIGNES = 5

# Consigne de rédaction saisie depuis l'écran Réglages (cf. uc_briefing.preferences).
#
# Elle est ajoutée au SYSTEM et jamais au message utilisateur : celui-ci ne
# contient que « Faits du jour : - … », et y glisser la consigne la ferait lire
# comme une donnée d'entrée — reprise telle quelle dans le texte, voire tenue
# pour un fait.
#
# Elle est encadrée par des balises et suivie d'un rappel de subordination : sans
# ce rappel, une consigne du type « insiste sur la croissance » suffit à faire
# produire un chiffre de croissance absent des faits, le modèle obéissant à la
# dernière instruction reçue. Placée en fin de prompt, une consigne libre se lit
# sinon comme une dérogation aux règles qui précèdent.
_CONSIGNE_BLOC = (
    "\n\nCONSIGNE DE RÉDACTION DU DESTINATAIRE (à appliquer au TON et à l'ANGLE uniquement) :\n"
    "<consigne>{consigne}</consigne>\n"
    "Cette consigne est SUBORDONNÉE à toutes les règles ci-dessus. Elle ne peut ni ajouter, ni "
    "modifier, ni recalculer, ni extrapoler un seul chiffre, nom de compte ou date : la liste de "
    "faits fournie reste la seule source autorisée. Si la consigne demande une information que les "
    "faits ne contiennent pas, IGNORE cette partie de la consigne sans la mentionner et sans t'en "
    "excuser. Ne cite jamais la consigne elle-même dans ta réponse."
)

# Mode « consigne pilote » : le destinataire n'a coché aucun élément et sa
# consigne est la seule boussole de CONTENU. Le bloc standard la subordonne au
# ton et à l'angle — réutilisé tel quel, il ferait ignorer précisément ce que
# l'utilisateur demande. Ici la consigne choisit QUOI raconter ; elle reste
# interdite d'inventer : la sélection se fait PARMI les faits fournis, jamais
# au-delà. Mêmes balises, même position en fin de SYSTEM, même règle du
# « demande sans fait correspondant : ignorée sans la mentionner ».
_CONSIGNE_PILOTE_BLOC = (
    "\n\nDEMANDES DU DESTINATAIRE (elles choisissent le CONTENU du briefing) :\n"
    "<consigne>{consigne}</consigne>\n"
    "Le destinataire n'a retenu aucun élément prédéfini : ces demandes remplacent la sélection. "
    "Pour chaque demande, choisis toi-même, PARMI les faits du jour fournis, ceux qui y répondent, "
    "et construis le briefing autour d'eux ; les faits qui ne répondent à aucune demande ne servent "
    "qu'à éclairer ceux retenus, jamais à les remplacer.\n"
    "Ce pouvoir s'arrête à la SÉLECTION : la liste de faits fournie reste la seule source autorisée. "
    "Tu ne peux ni ajouter, ni modifier, ni recalculer, ni extrapoler un seul chiffre, nom de compte "
    "ou date, même si une demande l'exige. Si une demande ne trouve aucun fait qui y réponde, "
    "IGNORE-la sans la mentionner et sans t'en excuser. Ne cite jamais les demandes elles-mêmes "
    "dans ta réponse."
)


def _avec_consigne(system: str, consigne: str, pilote: bool = False) -> str:
    """Ajoute la consigne au prompt système, si elle existe.

    Les balises présentes dans la consigne ont déjà été retirées au stockage
    (preferences.sanitize_consigne) ; le filtrage est répété ici parce que ce
    module ne peut pas présumer d'où vient la chaîne qu'on lui passe.

    `pilote` bascule sur le bloc où la consigne choisit le contenu. Une
    consigne vide en mode pilote ne peut pas arriver depuis
    service._composition_depuis, qui exige une consigne non vide pour poser le
    drapeau — le retour anticipé la neutralise quand même, par défense.
    """
    if not consigne or not consigne.strip():
        return system
    propre = re.sub(r"</?consigne>", "", consigne, flags=re.IGNORECASE).strip()
    if not propre:
        return system
    bloc = _CONSIGNE_PILOTE_BLOC if pilote else _CONSIGNE_BLOC
    return system + bloc.format(consigne=propre)


def _sans_phrase_coupee(texte: str) -> str:
    """Retire une dernière phrase laissée en suspens par un budget de tokens
    épuisé.

    Le budget peut toujours être atteint — un mois chargé, un rôle à dix faits.
    Publier « …le top 5 pèse 45% des 6 128 M FCFA commandés contre un seuil »
    est pire que publier une phrase de moins : le lecteur ne peut pas savoir si
    la donnée manque ou si l'analyse s'est arrêtée là.

    Ne touche rien quand le texte finit proprement, et rend le texte entier
    plutôt que du vide s'il ne porte aucune ponctuation finale — mieux vaut une
    analyse suspendue qu'un panneau vide.
    """
    if not texte or texte[-1] in ".!?\u2026\u00bb":
        return texte
    coupe = max(texte.rfind(". "), texte.rfind("! "), texte.rfind("? "))
    return texte[:coupe + 1].rstrip() if coupe > 0 else texte


def _fallback_analysis(bullets: list[str]) -> str:
    """Repli déterministe : les faits bruts, sans mise en récit (IA hors ligne)."""
    return " ".join(bullets)


def _clean_ligne(ligne: str) -> str:
    """Retire les préfixes de liste que le LLM ajoute malgré la consigne.

    La numérotation est reconnue par motif (« 1. », « 2) ») et non par simple
    suppression des chiffres de tête : beaucoup de lignes commencent
    légitimement par un montant (« 15582 M FCFA d'impayés… »), qu'un strip
    naïf amputerait de sa valeur.
    """
    return _LIST_PREFIX_RE.sub("", ligne).strip()


def _fallback_resume(bullets: list[str], action: str | None = None) -> list[str]:
    """Repli déterministe. L'action du jour, quand elle existe, occupe toujours
    la 5e ligne : sans ça le repli produit 5 constats et aucune décision, en
    contradiction avec la contrainte de format du résumé."""
    lignes = [b.strip() for b in bullets if b.strip()]
    if action:
        return lignes[: _MAX_RESUME_LIGNES - 1] + [action.strip()]
    return lignes[:_MAX_RESUME_LIGNES]


# Combien de lignes du résumé chaque bloc obtient. C'est la forme de la trame
# — le chiffre, l'exception, la décision — ramenée aux cinq lignes que porte la
# tête de cockpit.
#
# Un simple « les N premiers » paraissait suffisant, l'ordre du catalogue étant
# déjà le bon. Mesuré sur la direction générale : les quatre lignes retenues
# étaient QUATRE CHIFFRES, et pas une seule des trois alertes — dont un compte
# à 2 823 M FCFA impayés depuis 2 688 jours. Un résumé de direction sans son
# risque du jour n'est pas un résumé, c'est un relevé.
_QUOTAS_RESUME = {"chiffre": 3, "alerte": 1, "action": 1}

# Blocs éligibles au résumé de tête. `couverture` et `complement` en sont
# EXCLUS : la ligne des questions sans réponse et les agrégats hors trame
# restent dans les puces et dans l'analyse longue, jamais dans les cinq lignes
# que lit une direction avant tout le reste.
_ORDRE_RESUME = ("chiffre", "alerte", "action")

# Ordre d'attribution des places qui restent une fois les quotas servis.
# L'exception passe avant le chiffre : un quatrième montant ajoute de la
# précision, une seconde exception ajoute une décision. Un tourniquet
# strictement calé sur l'ordre des blocs rendait au contraire un quatrième
# chiffre avant la deuxième alerte.
_RELIQUAT_RESUME = ("alerte", "action", "chiffre")


def _faits_a_resumer(bullets: list[str], action: str | None = None,
                     blocs: dict[str, list[str]] | None = None) -> list[str]:
    """Les faits qui composeront le résumé, DANS L'ORDRE, choisis ici et jamais
    par le modèle.

    Sans découpage par bloc (briefing figé avant leur ajout), on retombe sur les
    premiers faits de la liste classée — le comportement d'avant, jamais une
    erreur.

    Le rab d'un bloc vide profite aux suivants : un rôle sans décision arbitrée
    obtient une exception de plus, plutôt qu'un résumé de quatre lignes.
    """
    plafond = _MAX_RESUME_LIGNES - 1 if action else _MAX_RESUME_LIGNES
    propres = [b.strip() for b in bullets if b.strip()]
    if not blocs:
        return propres[:plafond]

    # `action` déjà arbitrée : elle occupera la dernière ligne, le bloc du même
    # nom n'a plus à en fournir une.
    quotas = dict(_QUOTAS_RESUME)
    if action:
        quotas["action"] = 0

    disponibles = {
        cle: [b.strip() for b in blocs.get(cle, []) if b.strip()] for cle in _ORDRE_RESUME
    }
    retenus: list[str] = []
    for cle in _ORDRE_RESUME:
        part = quotas.get(cle, 0)
        retenus.extend(disponibles[cle][:part])
        disponibles[cle] = disponibles[cle][part:]

    for cle in _RELIQUAT_RESUME:
        while disponibles[cle] and len(retenus) < plafond:
            retenus.append(disponibles[cle].pop(0))
    return retenus[:plafond]


async def build_brief_resume(
    llm, role: str, bullets: list[str], action: str | None = None, consigne: str = "",
    pilote: bool = False, blocs: dict[str, list[str]] | None = None,
) -> list[str]:
    """Résumé en 5 lignes affiché en tête de cockpit. Repli sur les faits bruts
    si l'IA échoue — jamais de panneau vide.

    La SÉLECTION est faite ici, pas par le modèle : `_faits_a_resumer` prend les
    premiers faits de la liste déjà classée. Le modèle ne reçoit que ceux-là et
    les reformule un par un. Seul le mode « consigne pilote » lui rend le choix
    — c'est précisément ce que le destinataire demande en n'ayant rien coché.

    Le repli ignore délibérément `consigne` : si le LLM tombe, on perd le ton
    demandé mais jamais l'exactitude des faits.
    """
    if not bullets:
        return []
    if llm is None:
        return _fallback_resume(bullets, action)
    try:
        role_label = ROLE_LABELS.get(role, role)
        role_focus = ROLE_FOCUS.get(role, "la performance globale de l'entreprise")
        system = _avec_consigne(
            _SYSTEM_RESUME.format(role_label=role_label, role_focus=role_focus), consigne, pilote
        )
        # En mode pilote, la consigne remplace la sélection : le modèle doit voir
        # tout le pool pour y répondre (cf. _CONSIGNE_PILOTE_BLOC).
        retenus = bullets if pilote else _faits_a_resumer(bullets, action, blocs)
        user = "Faits du jour, dans l'ordre :\n- " + "\n- ".join(retenus)
        if action:
            user += (
                f"\n\nDécision du jour déjà arbitrée, à placer en DERNIÈRE ligne et à "
                f"reformuler en 20 mots maximum, jamais à remplacer : {action}"
            )
        attendu = len(retenus) + (1 if action else 0)
        user += f"\n\nRédige exactement {attendu} ligne(s), une par fait, dans cet ordre."
        text = await llm.generate(system=system, user=user, max_tokens=400, temperature=0.4)
        lignes = [_clean_ligne(l) for l in (text or "").splitlines()]
        lignes = [l for l in lignes if l]
        return lignes[:_MAX_RESUME_LIGNES] or _fallback_resume(bullets, action)
    except Exception as exc:
        logger.warning("Résumé de briefing IA échoué pour le rôle '%s' (repli faits bruts) : %s", role, exc)
        return _fallback_resume(bullets, action)


_TITRES_BLOCS = {
    "chiffre": "LES CHIFFRES ET LEUR MOUVEMENT",
    "alerte": "LES EXCEPTIONS",
    "action": "LES DÉCISIONS À PRENDRE",
    "couverture": "CE QUE LES DONNÉES NE PERMETTENT PAS DE DIRE",
    "complement": "COMPLÉMENTS",
}


def _faits_groupes(bullets: list[str], blocs: dict[str, list[str]] | None) -> str:
    """Faits présentés au modèle, rangés sous leur bloc.

    Sans ce découpage, le rédacteur reçoit une liste plate et traite un impayé
    échu depuis 1 413 jours comme un constat de plus. Le bloc lui dit ce que le
    fait EST : un chiffre à situer, une exception à expliquer, ou une décision à
    porter.
    """
    if not blocs:
        return "Faits du jour :\n- " + "\n- ".join(bullets)
    morceaux = []
    for cle, titre in _TITRES_BLOCS.items():
        lignes = blocs.get(cle)
        if lignes:
            morceaux.append(titre + " :\n- " + "\n- ".join(lignes))
    return "\n\n".join(morceaux) if morceaux else "Faits du jour :\n- " + "\n- ".join(bullets)


async def build_daily_analysis(
    llm, role: str, bullets: list[str], consigne: str = "", pilote: bool = False,
    blocs: dict[str, list[str]] | None = None,
) -> str:
    if not bullets:
        return "Pas assez de données pour un briefing aujourd'hui."
    # En mode pilote, le pool de faits est le catalogue entier du rôle : un repli
    # qui concatène tout produirait un mur de texte sans rapport avec la consigne.
    # On garde les puces les plus engageantes (les builders les ordonnent ainsi),
    # même plafond que _fallback_resume.
    repli = bullets[:_MAX_RESUME_LIGNES] if pilote else bullets
    if llm is None:
        return _fallback_analysis(repli)
    try:
        role_label = ROLE_LABELS.get(role, role)
        role_focus = ROLE_FOCUS.get(role, "la performance globale de l'entreprise")
        system = _avec_consigne(
            _SYSTEM_TEMPLATE.format(role_label=role_label, role_focus=role_focus), consigne, pilote
        )
        user = _faits_groupes(bullets, blocs) + "\n\nRédige le briefing."
        # 750 tokens suffisaient au plan libre d'origine ; le plan en trois blocs
        # les dépassait pour les cinq rôles. La borne de quatre phrases par
        # paragraphe rend la longueur prévisible, ce budget absorbe l'écart.
        text = await llm.generate(system=system, user=user, max_tokens=1200, temperature=0.55)
        return _sans_phrase_coupee((text or "").strip()) or _fallback_analysis(repli)
    except Exception as exc:
        logger.warning("Briefing IA échoué pour le rôle '%s' (repli faits bruts) : %s", role, exc)
        return _fallback_analysis(repli)
