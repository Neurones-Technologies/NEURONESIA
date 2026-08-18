import { getRelationCommerciale } from "@/lib/api/daf";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, StatTile, Tile } from "@/components/ui/bento";
import { Narr, Note, Section } from "@/components/ui/primitives";
import { SourceNote, sourceKick } from "@/components/views/vision/dc/source";

/** Situation des factures du DG.
 *
 * Miroir de l'écran Relation commerciale du DAF, réduit à ce qui se décide au
 * niveau DG : le stock échu des deux côtés. Même endpoint, mêmes chiffres — et
 * le même socle que l'élément de débrief « Factures échues »
 * (uc_daf.situation_factures). */
export async function DgFactures() {
  // `relation` est null si le module `tresorerie` est refusé au rôle (403 absorbé).
  const relation = await getRelationCommerciale(undefined, 8);

  const balance = relation?.balance_agee ?? null;
  const detteFournisseur = relation?.dpo ?? null;
  const cycleCash = relation?.cycle_cash ?? null;
  const payeurs = relation?.mauvais_payeurs ?? null;
  const nbEchuesClient = (balance?.tranches ?? [])
    .filter((t) => t.code !== "non_echu")
    .reduce((s, t) => s + (t.nb_factures ?? 0), 0);
  const tranche90Client = balance?.tranches.find((t) => t.code === "90_plus") ?? null;
  // Le comptage fournisseur n'a de sens qu'en régime mesuré : le gabarit posé
  // n'a pas de factures (nb_factures null sur ses tranches).
  const nbEchuesFournisseur =
    detteFournisseur && detteFournisseur.source === "reel"
      ? detteFournisseur.tranches
          .filter((t) => t.code !== "non_echu")
          .reduce((s, t) => s + (t.nb_factures ?? 0), 0)
      : null;
  const maxEchuPayeur = Math.max(...(payeurs?.clients ?? []).map((p) => p.encours_echu_xof), 0);

  return (
    <Section
      id="factures"
      title="Factures"
      subtitle="Créances clients et dettes fournisseurs — le stock échu à assainir"
    >
      {relation && balance && detteFournisseur && cycleCash ? (
        <Bento>
          <StatTile
            span={4}
            fill
            rang="principal"
            label="Créances clients échues"
            aide="Ce que vos clients vous doivent au-delà de l'échéance, sur le reste dû réel (les factures annulées ne comptent pas). C'est de la trésorerie déjà gagnée mais pas encaissée."
            value={formatMFcfa(relation.dso.encours_echu_xof)}
            unit="M FCFA"
            reading={
              `${formatNumber(nbEchuesClient)} factures échues` +
              (tranche90Client
                ? ` · ${formatPct(tranche90Client.part_pct, 0)} % de l'encours au-delà de 90 jours`
                : "")
            }
            readingVariant={tranche90Client && tranche90Client.part_pct > 50 ? "neg" : "wat"}
            detail={{
              kicker: "Indicateur · créances clients",
              title: "Créances échues non réglées",
              tag: tranche90Client && tranche90Client.part_pct > 50 ? "assainissement requis" : "à recouvrer",
              tagVariant: tranche90Client && tranche90Client.part_pct > 50 ? "r" : "w",
              body: [
                `Sur ${formatMFcfa(relation.dso.encours_xof)} M FCFA d'encours client ouvert, ${formatMFcfa(relation.dso.encours_echu_xof)} M FCFA ont dépassé leur échéance, portés par ${formatNumber(nbEchuesClient)} factures.`,
                tranche90Client
                  ? `${formatMFcfa(tranche90Client.montant_xof)} M FCFA ont plus de 90 jours de retard : au-delà de ce seuil, le recouvrement amiable a rarement encore prise — c'est la tranche qui détermine le besoin de provision.`
                  : "",
                balance.note,
              ].filter(Boolean),
              kv: [
                ["Encours ouvert", `${formatMFcfa(relation.dso.encours_xof)} M FCFA`],
                ["Dont échu", `${formatMFcfa(relation.dso.encours_echu_xof)} M FCFA`],
                [
                  "Dont plus de 90 jours",
                  tranche90Client ? `${formatMFcfa(tranche90Client.montant_xof)} M FCFA` : "—",
                ],
                ["Taux de recouvrement", `${formatPct(relation.dso.taux_recouvrement_pct, 0)} %`],
              ],
            }}
          />
          <StatTile
            span={4}
            fill
            label="Dette fournisseurs échue"
            aide="Ce que vous devez à vos fournisseurs au-delà de l'échéance, mesuré sur les factures fournisseurs synchronisées depuis Odoo."
            value={formatMFcfa(detteFournisseur.dette_echue_xof)}
            unit="M FCFA"
            reading={
              detteFournisseur.source === "reel"
                ? `${formatNumber(nbEchuesFournisseur ?? 0)} factures échues sur ${formatNumber(detteFournisseur.nb_factures_fournisseurs)} synchronisées`
                : "dette posée — factures fournisseurs non synchronisées"
            }
            readingVariant={detteFournisseur.source === "reel" ? undefined : "wat"}
            detail={{
              kicker: "Indicateur · dettes fournisseurs",
              title: "Dette fournisseur échue",
              tag: detteFournisseur.source === "reel" ? "mesurée" : "posée",
              tagVariant: detteFournisseur.source === "reel" ? "w" : "n",
              body: [
                `${formatMFcfa(detteFournisseur.dette_xof)} M FCFA de dette fournisseur ouverte, dont ${formatMFcfa(detteFournisseur.dette_echue_xof)} M FCFA au-delà de l'échéance.`,
                detteFournisseur.note,
              ],
              kv: [
                ["Dette ouverte", `${formatMFcfa(detteFournisseur.dette_xof)} M FCFA`],
                ["Dont échue", `${formatMFcfa(detteFournisseur.dette_echue_xof)} M FCFA`],
                ["Factures synchronisées", formatNumber(detteFournisseur.nb_factures_fournisseurs)],
                [
                  "Retard moyen constaté",
                  detteFournisseur.retard_moyen_jours != null
                    ? `${formatPct(detteFournisseur.retard_moyen_jours, 0)} j`
                    : "—",
                ],
              ],
            }}
          />
          <StatTile
            span={4}
            fill
            signeNeutre
            label="Cycle de cash"
            aide="L'écart entre le moment où vos clients vous payent (DSO) et celui où vous payez vos fournisseurs (DPO). Payer avant d'être payé oblige à financer la différence."
            value={cycleCash.ecart_jours !== null ? formatPct(cycleCash.ecart_jours, 0) : "—"}
            unit="jours d'écart DSO / DPO"
            reading={`DSO ${formatPct(cycleCash.dso_jours, 0)} j · DPO ${formatPct(cycleCash.dpo_jours, 0)} j`}
            detail={{
              kicker: "Indicateur · cycle de cash",
              title: "DSO contre DPO",
              tag: cycleCash.source === "reel" ? "mesuré" : "partiellement posé",
              tagVariant: cycleCash.source === "reel" ? "w" : "n",
              body: [cycleCash.lecture, cycleCash.fiabilite].filter(Boolean),
              kv: [
                ["Délai d'encaissement client (DSO)", `${formatPct(cycleCash.dso_jours, 0)} j`],
                ["Délai de paiement fournisseur (DPO)", `${formatPct(cycleCash.dpo_jours, 0)} j`],
              ],
            }}
          />

          <Tile
            span={6}
            title="Balance âgée des créances"
            kick={`${formatMFcfa(balance.total_xof)} M FCFA d'encours`}
            aide="Ce qu'on vous doit, rangé par ancienneté du retard. Plus une créance est ancienne, moins elle a de chances d'être encaissée."
          >
            <Bars
              rows={balance.tranches.map((t) => ({
                name: t.libelle,
                sub: `${formatNumber(t.nb_factures ?? 0)} facture(s) · ${formatPct(t.part_pct, 1)} % de l'encours`,
                value: `${formatMFcfa(t.montant_xof)} M`,
                pct: t.part_pct,
                variant:
                  t.code === "90_plus" ? ("r" as const) : t.code === "non_echu" ? ("s" as const) : ("w" as const),
              }))}
            />
            {tranche90Client && tranche90Client.part_pct > 50 && (
              <Note accent style={{ marginTop: 14 }}>
                {formatPct(tranche90Client.part_pct, 0)} % de l&apos;encours client dépasse 90 jours de
                retard, soit {formatMFcfa(tranche90Client.montant_xof)} M FCFA sur{" "}
                {formatNumber(tranche90Client.nb_factures ?? 0)} factures. À ce niveau, le sujet
                n&apos;est plus le délai de paiement mais l&apos;assainissement du poste client.
              </Note>
            )}
          </Tile>

          <Tile
            span={6}
            title="Dette fournisseurs par ancienneté"
            kick={sourceKick(detteFournisseur.source, `${formatMFcfa(detteFournisseur.dette_xof)} M FCFA`)}
            aide="Ce que vous devez à vos fournisseurs, rangé par ancienneté du retard — mesuré sur les factures fournisseurs synchronisées depuis Odoo."
          >
            <Bars
              rows={detteFournisseur.tranches.map((t) => ({
                name: t.libelle,
                sub:
                  t.nb_factures !== null
                    ? `${formatNumber(t.nb_factures)} facture(s) · ${formatPct(t.part_pct, 1)} %`
                    : `${formatPct(t.part_pct, 1)} % de la dette posée`,
                value: `${formatMFcfa(t.montant_xof)} M`,
                pct: t.part_pct,
                variant:
                  t.code === "90_plus" ? ("r" as const) : t.code === "non_echu" ? ("s" as const) : ("w" as const),
              }))}
            />
            <SourceNote
              source={detteFournisseur.source}
              raison={detteFournisseur.raison}
              avertissement={detteFournisseur.avertissement}
            />
          </Tile>

          {payeurs && payeurs.clients.length > 0 && (
            <Tile
              span={12}
              title="Mauvais payeurs"
              kick={`${formatNumber(payeurs.totaux.nb_clients_a_risque)} client(s) à risque · ${formatMFcfa(payeurs.totaux.encours_echu_total_xof)} M FCFA échus`}
              aide="Les clients classés par risque de paiement : leur comportement passé, leur retard courant et le poids de leur encours échu — pas seulement le montant."
            >
              <Bars
                replierApres={5}
                nom="clients"
                rows={payeurs.clients.slice(0, 8).map((p) => ({
                  name: p.client,
                  sub: `retard courant ${formatNumber(p.retard_courant_max_jours)} j · ${formatNumber(p.nb_factures_ouvertes)} facture(s) ouverte(s) · indice ${formatNumber(p.indice_risque)}`,
                  value: `${formatMFcfa(p.encours_echu_xof)} M`,
                  pct: maxEchuPayeur ? (p.encours_echu_xof / maxEchuPayeur) * 100 : 0,
                  variant: p.statut === "contentieux" ? ("r" as const) : ("w" as const),
                }))}
              />
              <Note style={{ marginTop: 14 }}>{payeurs.note}</Note>
            </Tile>
          )}
        </Bento>
      ) : (
        <Bento>
          <Tile span={12} quiet title="Factures">
            <Narr>
              La situation des factures n&apos;est pas accessible depuis ce profil, ou le backend ne
              l&apos;expose pas encore — rechargez la page après redémarrage du serveur.
            </Narr>
          </Tile>
        </Bento>
      )}
    </Section>
  );
}
