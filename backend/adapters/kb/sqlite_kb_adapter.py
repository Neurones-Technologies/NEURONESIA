"""
SQLiteKBAdapter — persistance des faits structurés dans les tables `kb_*`.

Idempotent par `doc_id` : chaque écriture supprime d'abord les lignes existantes
(tête + enfants) du document, puis réinsère. Ré-ingérer le même document (même
hash → de toute façon court-circuité en amont, mais aussi en cas de `force`)
ne crée donc aucun doublon.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, select

from core.domain.document import DocumentType
from core.ports.kb_repository import KBRepository
from core.services.structured_extractor import ExtractionResult
from db.database import AsyncSessionLocal
from db import models as m

logger = logging.getLogger(__name__)


def _montant(value):
    """Optional[Montant] → (valeur, devise) ou (None, None)."""
    if value is None:
        return None, None
    return value.valeur, value.devise


# Tables enfants à purger par doc_id, regroupées par table de tête.
_CHILDREN = {
    m.KBCvModel: [m.KBCvExperienceModel, m.KBCvCertificationModel],
    m.KBAoModel: [m.KBAoExigenceModel, m.KBAoReferenceDemandeeModel],
    m.KBCompteRenduModel: [m.KBCrActionModel],
    m.KBPvRecetteModel: [m.KBPvReserveModel],
    m.KBCertificationModel: [],
    m.KBAttestationModel: [],
}


class SQLiteKBAdapter(KBRepository):

    async def save_extraction(
        self,
        *,
        doc_id: str,
        doc_type: DocumentType,
        fichier_source: str,
        hash_sha256: str,
        result: ExtractionResult,
        page: int | None = None,
    ) -> None:
        common = dict(
            doc_id=doc_id,
            doc_type=doc_type.value,
            fichier_source=fichier_source,
            page=page,
            hash_sha256=hash_sha256,
            date_ingestion=datetime.utcnow(),
            score_confiance=result.score_confiance,
            revue_humaine=result.revue_humaine,
        )
        async with AsyncSessionLocal() as session:
            await self._purge(session, doc_id)
            self._build_rows(session, doc_id, doc_type, common, result)
            await session.commit()
        logger.info(
            "KB — %s persisté (doc_id=%s, confiance=%.2f%s)",
            doc_type.value, doc_id, result.score_confiance,
            ", REVUE" if result.revue_humaine else "",
        )

    async def delete_by_doc_id(self, doc_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await self._purge(session, doc_id)
            await session.commit()

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _purge(session, doc_id: str) -> None:
        for head, children in _CHILDREN.items():
            for child in children:
                await session.execute(delete(child).where(child.doc_id == doc_id))
            await session.execute(delete(head).where(head.doc_id == doc_id))

    def _build_rows(self, session, doc_id, doc_type, common, result: ExtractionResult) -> None:
        p = result.payload
        builder = {
            DocumentType.CV: self._cv,
            DocumentType.AO: self._ao,
            DocumentType.COMPTE_RENDU: self._cr,
            DocumentType.CERTIFICATION: self._certif,
            DocumentType.PV_RECETTE: self._pv,
            DocumentType.ABE: self._abe,
        }.get(doc_type)
        if builder:
            builder(session, doc_id, common, p)

    def _cv(self, session, doc_id, common, p):
        session.add(m.KBCvModel(
            **common,
            nom_complet=p.personne.nom_complet,
            titre_poste=p.personne.titre_poste,
            annees_experience=p.personne.annees_experience_total,
            localisation=p.personne.localisation,
            langues=[l.model_dump() for l in p.langues],
            competences=[c.model_dump() for c in p.competences],
            formations=[f.model_dump() for f in p.formations],
            secteurs_expertise=list(p.secteurs_expertise),
        ))
        for e in p.experiences:
            session.add(m.KBCvExperienceModel(
                doc_id=doc_id, intitule_projet=e.intitule_projet, client=e.client,
                role=e.role, secteur=e.secteur, date_debut=e.date_debut,
                date_fin=e.date_fin, en_cours=e.en_cours, description_courte=e.description_courte,
            ))
        for c in p.certifications_citees:
            session.add(m.KBCvCertificationModel(
                doc_id=doc_id, intitule=c.intitule, organisme=c.organisme, annee=c.annee,
            ))

    def _ao(self, session, doc_id, common, p):
        budget_v, budget_d = _montant(p.budget_estime)
        session.add(m.KBAoModel(
            **common,
            reference=p.reference, intitule=p.intitule, maitre_ouvrage=p.maitre_ouvrage,
            date_publication=p.date_publication, date_limite_remise=p.date_limite_remise,
            budget_valeur=budget_v, budget_devise=budget_d,
            type_marche=p.type_marche, duree_execution=p.duree_execution,
            lots=[l.model_dump(mode="json") for l in p.lots],
            certifications_exigees=list(p.certifications_exigees),
            criteres_evaluation=[c.model_dump() for c in p.criteres_evaluation],
        ))
        for ex in p.exigences_obligatoires:
            session.add(m.KBAoExigenceModel(
                doc_id=doc_id, categorie=ex.categorie, libelle=ex.libelle, obligatoire=ex.obligatoire,
            ))
        for r in p.references_demandees:
            mv, md = _montant(r.montant_min)
            session.add(m.KBAoReferenceDemandeeModel(
                doc_id=doc_id, description=r.description, nombre_min=r.nombre_min,
                montant_min_valeur=mv, montant_min_devise=md, periode=r.periode,
            ))

    def _cr(self, session, doc_id, common, p):
        session.add(m.KBCompteRenduModel(
            **common,
            date_reunion=p.date_reunion, objet=p.objet, projet_associe=p.projet_associe,
            lieu=p.lieu,
            participants=[x.model_dump() for x in p.participants],
            decisions=list(p.decisions),
            points_abordes=list(p.points_abordes),
        ))
        for a in p.actions:
            session.add(m.KBCrActionModel(
                doc_id=doc_id, libelle=a.libelle, responsable=a.responsable,
                echeance=a.echeance, statut=a.statut,
            ))

    def _certif(self, session, doc_id, common, p):
        session.add(m.KBCertificationModel(
            **common,
            titulaire=p.titulaire, intitule=p.intitule, organisme_emetteur=p.organisme_emetteur,
            numero_identifiant=p.numero_identifiant, date_emission=p.date_emission,
            date_expiration=p.date_expiration, statut=p.statut, domaine=p.domaine,
        ))

    def _pv(self, session, doc_id, common, p):
        session.add(m.KBPvRecetteModel(
            **common,
            reference=p.reference, projet_associe=p.projet_associe, client=p.client,
            date=p.date, type_recette=p.type_recette, statut_global=p.statut_global,
            livrables=[l.model_dump() for l in p.livrables],
            signataires=[s.model_dump() for s in p.signataires],
        ))
        for r in p.reserves:
            session.add(m.KBPvReserveModel(
                doc_id=doc_id, description=r.description, criticite=r.criticite,
                statut=r.statut, date_levee=r.date_levee,
            ))

    def _abe(self, session, doc_id, common, p):
        montant_v, montant_d = _montant(p.montant)
        session.add(m.KBAttestationModel(
            **common,
            reference=p.reference, emetteur_client=p.emetteur_client, projet_marche=p.projet_marche,
            montant_valeur=montant_v, montant_devise=montant_d,
            date_debut=p.date_debut, date_fin=p.date_fin, duree_mois=p.duree_mois,
            niveau_appreciation=p.niveau_appreciation, secteur=p.secteur,
            perimetre_prestations=list(p.perimetre_prestations),
            signataire=p.signataire.model_dump() if p.signataire else {},
        ))

    # ════════════════════════════════════════════════════════════════════════
    # Résolution d'entités (Phase 2)
    # ════════════════════════════════════════════════════════════════════════

    _ACTIVE_STATUS = ("confirmed", "auto")

    # Tables de tête par type — pour le backfill.
    _HEADS = {
        DocumentType.CV: m.KBCvModel,
        DocumentType.AO: m.KBAoModel,
        DocumentType.COMPTE_RENDU: m.KBCompteRenduModel,
        DocumentType.CERTIFICATION: m.KBCertificationModel,
        DocumentType.PV_RECETTE: m.KBPvRecetteModel,
        DocumentType.ABE: m.KBAttestationModel,
    }

    async def resolve_document(self, doc_id: str, doc_type: DocumentType, resolver) -> None:
        handler = {
            DocumentType.CV: self._resolve_cv,
            DocumentType.AO: self._resolve_ao,
            DocumentType.COMPTE_RENDU: self._resolve_cr,
            DocumentType.CERTIFICATION: self._resolve_certif,
            DocumentType.PV_RECETTE: self._resolve_pv,
            DocumentType.ABE: self._resolve_abe,
        }.get(doc_type)
        if handler is None:
            return
        async with AsyncSessionLocal() as session:
            await handler(session, resolver, doc_id)
            await session.commit()

    async def resolve_all(self, resolver) -> int:
        targets: list[tuple[str, DocumentType]] = []
        async with AsyncSessionLocal() as session:
            for doc_type, head in self._HEADS.items():
                ids = (await session.execute(select(head.doc_id))).scalars().all()
                targets.extend((doc_id, doc_type) for doc_id in ids)
        for doc_id, doc_type in targets:
            await self.resolve_document(doc_id, doc_type, resolver)
        return len(targets)

    async def list_pending(self, entity_type: str | None = None) -> list[dict]:
        async with AsyncSessionLocal() as session:
            q = select(m.KBAliasModel).where(m.KBAliasModel.status == "pending")
            if entity_type:
                q = q.where(m.KBAliasModel.entity_type == entity_type)
            rows = (await session.execute(q)).scalars().all()
            return [
                {"id": r.id, "entity_type": r.entity_type, "alias_raw": r.alias_raw,
                 "alias_norm": r.alias_norm, "suggested_entity_id": r.entity_id,
                 "score": r.score, "source_doc_id": r.source_doc_id}
                for r in rows
            ]

    async def confirm_alias(self, alias_id: int, entity_id: str | None = None) -> None:
        async with AsyncSessionLocal() as session:
            alias = await session.get(m.KBAliasModel, alias_id)
            if alias is None:
                return
            if entity_id is not None:
                alias.entity_id = entity_id
            alias.status = "confirmed"
            alias.score = 1.0
            await session.commit()

    # ── Chargement des candidats ─────────────────────────────────────────────

    async def _load_candidates(self, session, entity_type: str):
        """client/personne → [(alias_norm, entity_id)] ; projet → [(alias_norm, entity_id, client_id)]."""
        if entity_type == "projet":
            rows = (await session.execute(
                select(m.KBAliasModel.alias_norm, m.KBAliasModel.entity_id, m.KBProjetModel.client_id)
                .join(m.KBProjetModel, m.KBProjetModel.id == m.KBAliasModel.entity_id)
                .where(m.KBAliasModel.entity_type == "projet",
                       m.KBAliasModel.status.in_(self._ACTIVE_STATUS))
            )).all()
            return [(a, e, c) for a, e, c in rows]
        rows = (await session.execute(
            select(m.KBAliasModel.alias_norm, m.KBAliasModel.entity_id)
            .where(m.KBAliasModel.entity_type == entity_type,
                   m.KBAliasModel.status.in_(self._ACTIVE_STATUS))
        )).all()
        return [(a, e) for a, e in rows]

    # ── Décision + application (création / lien / pending) ───────────────────

    async def _resolve_label(
        self, session, resolver, entity_type, raw_label, cands,
        *, source_doc_id, client_id=None, create_attrs=None,
    ) -> str | None:
        norm = resolver.normalize(entity_type, raw_label)
        if not norm:
            return None

        if entity_type == "projet":
            pool = [(a, e) for (a, e, c) in cands if client_id is None or c in (None, client_id)]
        else:
            pool = list(cands)

        known_norms = {c[0] for c in cands}
        decision = resolver.decide(entity_type, norm, pool)

        if decision.action == "link":
            if norm not in known_norms:
                session.add(m.KBAliasModel(
                    entity_type=entity_type, alias_norm=norm, alias_raw=str(raw_label),
                    entity_id=decision.entity_id, status="auto",
                    score=decision.score, source_doc_id=source_doc_id,
                ))
                self._cache_append(cands, entity_type, norm, decision.entity_id, client_id)
            return decision.entity_id

        if decision.action == "pending":
            session.add(m.KBAliasModel(
                entity_type=entity_type, alias_norm=norm, alias_raw=str(raw_label),
                entity_id=decision.entity_id, status="pending",
                score=decision.score, source_doc_id=source_doc_id,
            ))
            return None  # non lié tant que non validé par un humain

        # action == "new"
        eid = self._create_entity(session, entity_type, raw_label, norm, client_id, create_attrs)
        self._cache_append(cands, entity_type, norm, eid, client_id)
        return eid

    @staticmethod
    def _cache_append(cands, entity_type, norm, eid, client_id):
        cands.append((norm, eid, client_id) if entity_type == "projet" else (norm, eid))

    def _create_entity(self, session, entity_type, raw_label, norm, client_id, attrs) -> str:
        attrs = attrs or {}
        eid = f"{entity_type[:3]}_{uuid.uuid4().hex[:12]}"
        if entity_type == "client":
            session.add(m.KBClientModel(id=eid, raison_sociale=str(raw_label),
                                        secteur=attrs.get("secteur"), pays=attrs.get("pays")))
        elif entity_type == "personne":
            session.add(m.KBPersonneModel(id=eid, nom_complet=str(raw_label)))
        elif entity_type == "projet":
            session.add(m.KBProjetModel(
                id=eid, intitule=str(raw_label), client_id=client_id,
                secteur=attrs.get("secteur"),
                montant_valeur=attrs.get("montant_valeur"), montant_devise=attrs.get("montant_devise"),
                date_debut=attrs.get("date_debut"), date_fin=attrs.get("date_fin"),
            ))
        # Auto-alias canonique (clé de recherche de l'entité).
        session.add(m.KBAliasModel(
            entity_type=entity_type, alias_norm=norm, alias_raw=str(raw_label),
            entity_id=eid, status="confirmed", score=1.0, source_doc_id=None,
        ))
        return eid

    # ── Handlers par type ────────────────────────────────────────────────────

    async def _resolve_abe(self, session, resolver, doc_id):
        head = await session.get(m.KBAttestationModel, doc_id)
        if head is None:
            return
        client_id = None
        if head.emetteur_client:
            cands = await self._load_candidates(session, "client")
            client_id = await self._resolve_label(
                session, resolver, "client", head.emetteur_client, cands,
                source_doc_id=doc_id, create_attrs={"secteur": head.secteur})
            head.client_ref_id = client_id
        if head.projet_marche:
            cands = await self._load_candidates(session, "projet")
            head.projet_ref_id = await self._resolve_label(
                session, resolver, "projet", head.projet_marche, cands,
                source_doc_id=doc_id, client_id=client_id,
                create_attrs={"secteur": head.secteur, "montant_valeur": head.montant_valeur,
                              "montant_devise": head.montant_devise,
                              "date_debut": head.date_debut, "date_fin": head.date_fin})

    async def _resolve_ao(self, session, resolver, doc_id):
        head = await session.get(m.KBAoModel, doc_id)
        if head is None:
            return
        client_id = None
        if head.maitre_ouvrage:
            cands = await self._load_candidates(session, "client")
            client_id = await self._resolve_label(
                session, resolver, "client", head.maitre_ouvrage, cands, source_doc_id=doc_id)
            head.client_ref_id = client_id
        if head.intitule:
            cands = await self._load_candidates(session, "projet")
            head.projet_ref_id = await self._resolve_label(
                session, resolver, "projet", head.intitule, cands,
                source_doc_id=doc_id, client_id=client_id,
                create_attrs={"montant_valeur": head.budget_valeur, "montant_devise": head.budget_devise})

    async def _resolve_pv(self, session, resolver, doc_id):
        head = await session.get(m.KBPvRecetteModel, doc_id)
        if head is None:
            return
        client_id = None
        if head.client:
            cands = await self._load_candidates(session, "client")
            client_id = await self._resolve_label(
                session, resolver, "client", head.client, cands, source_doc_id=doc_id)
            head.client_ref_id = client_id
        if head.projet_associe:
            cands = await self._load_candidates(session, "projet")
            head.projet_ref_id = await self._resolve_label(
                session, resolver, "projet", head.projet_associe, cands,
                source_doc_id=doc_id, client_id=client_id)

    async def _resolve_cr(self, session, resolver, doc_id):
        head = await session.get(m.KBCompteRenduModel, doc_id)
        if head is None or not head.projet_associe:
            return
        cands = await self._load_candidates(session, "projet")
        head.projet_ref_id = await self._resolve_label(
            session, resolver, "projet", head.projet_associe, cands, source_doc_id=doc_id)

    async def _resolve_certif(self, session, resolver, doc_id):
        head = await session.get(m.KBCertificationModel, doc_id)
        if head is None or not head.titulaire:
            return
        cands = await self._load_candidates(session, "personne")
        head.personne_ref_id = await self._resolve_label(
            session, resolver, "personne", head.titulaire, cands, source_doc_id=doc_id)

    async def _resolve_cv(self, session, resolver, doc_id):
        head = await session.get(m.KBCvModel, doc_id)
        if head is None:
            return
        if head.nom_complet:
            cands = await self._load_candidates(session, "personne")
            head.personne_ref_id = await self._resolve_label(
                session, resolver, "personne", head.nom_complet, cands, source_doc_id=doc_id)

        exps = (await session.execute(
            select(m.KBCvExperienceModel).where(m.KBCvExperienceModel.doc_id == doc_id)
        )).scalars().all()
        if not exps:
            return
        client_cands = await self._load_candidates(session, "client")
        projet_cands = await self._load_candidates(session, "projet")
        for e in exps:
            client_id = None
            if e.client:
                client_id = await self._resolve_label(
                    session, resolver, "client", e.client, client_cands, source_doc_id=doc_id)
            if e.intitule_projet:
                e.projet_ref_id = await self._resolve_label(
                    session, resolver, "projet", e.intitule_projet, projet_cands,
                    source_doc_id=doc_id, client_id=client_id,
                    create_attrs={"secteur": e.secteur, "date_debut": e.date_debut, "date_fin": e.date_fin})
