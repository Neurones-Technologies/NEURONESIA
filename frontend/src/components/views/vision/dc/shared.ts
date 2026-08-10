// Couleur par segment de dormance : rouge sur ce qui ne commande plus depuis plus
// d'un an, orange sur le décrochage récent (encore récupérable), neutre sur l'actif
// et les prospects — un prospect n'est pas une alerte.
export const DORMANCE_VARIANT: Record<string, "r" | "w" | "s" | undefined> = {
  actif: undefined,
  ralentit: "w",
  dormant: "r",
  perdu: "r",
  prospect: "s",
};

export const DORMANCE_TAG: Record<string, "r" | "w" | "s" | "a" | "n"> = {
  actif: "s",
  ralentit: "w",
  dormant: "r",
  perdu: "r",
  prospect: "n",
};
