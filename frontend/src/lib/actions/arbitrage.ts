"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api/client";

export async function createDecisionAction(formData: FormData) {
  const profile = String(formData.get("profile") ?? "");
  const payload = {
    title: String(formData.get("title") ?? ""),
    context: String(formData.get("context") ?? ""),
    subject_ref: String(formData.get("subject_ref") ?? ""),
    subject_label: String(formData.get("subject_label") ?? ""),
    enjeu_xof: Number(formData.get("enjeu_xof") ?? 0),
    mandat_role: String(formData.get("mandat_role") ?? ""),
    profils_impliques: String(formData.get("profils_impliques") ?? "").split(",").filter(Boolean),
    option_retenue: String(formData.get("option_retenue") ?? ""),
  };

  if (!payload.title) return;

  await apiFetch("/v1/arbitrage/decisions", {
    method: "POST",
    body: JSON.stringify(payload),
    allowForbidden: true,
  });

  if (profile) revalidatePath(`/${profile}/arbitrage`);
}

export async function markReviewedAction(formData: FormData) {
  const profile = String(formData.get("profile") ?? "");
  const id = formData.get("decision_id");
  if (!id) return;

  await apiFetch(`/v1/arbitrage/decisions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: "tranchee",
      review_date: new Date().toISOString(),
      review_verdict: String(formData.get("review_verdict") ?? "confirme"),
    }),
    allowForbidden: true,
  });

  if (profile) revalidatePath(`/${profile}/arbitrage`);
}
