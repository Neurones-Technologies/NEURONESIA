"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Btn } from "@/components/ui/primitives";
import { ChartBlock } from "@/components/copilot/ChartBlock";
import { splitMessage } from "@/components/copilot/chart-spec";
import { ConversationList, SessionSummary } from "@/components/copilot/ConversationList";
import { useSidebarPref } from "@/components/copilot/useSidebarPref";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls: string[];
}

type SseEvent =
  | { type: "token"; content: string }
  | { type: "tool_call"; tool: string; label: string }
  | { type: "sources"; sources: unknown[] }
  | { type: "done"; intent: string };

function newSessionId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

/** Session expirée : le proxy relaie le 401 du backend. Le pointeur de
 * conversation doit alors être conservé — l'utilisateur retrouvera son fil après
 * s'être reconnecté. */
class AuthExpiredError extends Error {
  constructor() {
    super("Session expirée — reconnectez-vous pour retrouver vos conversations.");
  }
}

/** Fil réellement absent côté backend (purge à 30 jours, suppression depuis un
 * autre onglet). Seul ce cas justifie d'oublier le pointeur localStorage. */
class HistoryGoneError extends Error {
  constructor() {
    super("Conversation introuvable");
  }
}

/** Liste des conversations du profil. L'historique est un confort : en cas
 * d'échec on renvoie la liste vide plutôt que de bloquer la page. */
async function fetchSessions(profile: string): Promise<SessionSummary[]> {
  const res = await fetch(`/api/chat/sessions?profile=${encodeURIComponent(profile)}`);
  if (!res.ok) return [];
  const data = (await res.json()) as { sessions?: SessionSummary[] };
  return data.sessions ?? [];
}

async function fetchHistory(sessionId: string, profile: string): Promise<ChatMessage[]> {
  const res = await fetch(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}?profile=${encodeURIComponent(profile)}`
  );
  // Un 401 (cookie expiré pendant que l'onglet était en arrière-plan) et un 502
  // (backend momentanément injoignable) ne disent RIEN sur l'existence du fil :
  // les confondre avec une purge faisait perdre le pointeur d'une conversation
  // encore en base, définitivement.
  if (res.status === 401) throw new AuthExpiredError();
  if (res.status === 404) throw new HistoryGoneError();
  if (!res.ok) throw new Error("Reprise impossible — réessayez dans un instant.");
  // Le backend répond 200 + messages vides pour un fil purgé (et pour un profil
  // non reconnu) ; le proxy marque ce cas d'en-tête, seule façon de le
  // distinguer d'une conversation réellement vide.
  if (res.headers.get("x-history-empty") === "1") throw new HistoryGoneError();
  const data = (await res.json()) as { messages: { role: "user" | "assistant"; content: string }[] };
  // Les outils appelés ne sont pas persistés (seul le texte des tours l'est) :
  // une conversation reprise n'affiche donc pas la trace « Analyse SQL… ».
  return data.messages.map((m) => ({ role: m.role, content: m.content, toolCalls: [] }));
}

export function ChatBox({
  profile,
  initialSessions,
  placeholder,
  suggested,
  avatar = "MOI",
}: {
  profile: string;
  initialSessions: SessionSummary[];
  placeholder: string;
  suggested: string[];
  avatar?: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>(initialSessions);
  const [sessionId, setSessionId] = useState("");
  const router = useRouter();
  const searchParams = useSearchParams();

  // Le fil défile dans son propre cadre (la saisie reste ancrée en bas) : il
  // faut donc suivre le flux nous-mêmes. `stickToBottom` retient si l'on était
  // collé au bas AVANT l'arrivée des nouveaux jetons — sans quoi on arracherait
  // la lecture de quelqu'un remonté dans la conversation.
  const threadRef = useRef<HTMLDivElement>(null);
  const threadInnerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // Miroirs de `busy` et `sessionId` pour l'écouteur de resynchronisation plus
  // bas : abonné une seule fois, il capturerait sinon les valeurs du premier
  // rendu et rechargerait par-dessus une réponse en cours de streaming.
  const busyRef = useRef(busy);
  const sessionIdRef = useRef(sessionId);
  useEffect(() => {
    busyRef.current = busy;
    sessionIdRef.current = sessionId;
  }, [busy, sessionId]);

  useEffect(() => {
    const box = threadRef.current;
    const content = threadInnerRef.current;
    if (!box || !content) return;
    const follow = () => {
      if (stickToBottom.current) box.scrollTop = box.scrollHeight;
    };
    follow();
    // Le contenu grandit APRÈS ce rendu — rendu du markdown à l'ouverture d'une
    // conversation, jetons qui arrivent en flux — donc on suit sa hauteur au
    // lieu de ne recaler qu'une fois.
    const observer = new ResizeObserver(follow);
    observer.observe(content);
    return () => observer.disconnect();
  }, [messages]);

  function onThreadScroll() {
    const el = threadRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  // L'historique est cloisonné par profil : la conversation en cours d'un DG ne
  // doit pas être reprise en entrant dans le Copilote côté commercial.
  const storageKey = `copilot:session:${profile}`;
  const [sidebarOpen, toggleSidebar] = useSidebarPref(`copilot:sidebar:${profile}`);

  function refreshSessions() {
    fetchSessions(profile)
      .then(setSessions)
      .catch(() => {});
  }

  function openSession(id: string) {
    if (busy) return;
    setError(null);
    stickToBottom.current = true;
    fetchHistory(id, profile)
      .then((history) => {
        setMessages(history);
        setSessionId(id);
        localStorage.setItem(storageKey, id);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Reprise impossible");
        // On n'oublie le pointeur que si le fil a VRAIMENT disparu (purge à 30
        // jours, suppression depuis un autre onglet). Le purger sur un 401 ou
        // une panne réseau perdait l'accès à une conversation encore en base.
        if (err instanceof HistoryGoneError) localStorage.removeItem(storageKey);
        // Cookie expiré : le layout redirige déjà vers /login au prochain rendu
        // serveur, mais le cache routeur peut le différer d'une minute. On le
        // provoque ici, sinon la vue reste sur un message sans issue.
        if (err instanceof AuthExpiredError) router.replace("/login");
      });
  }

  function deleteSession(id: string) {
    // Retrait optimiste : la ligne disparaît tout de suite, on ne remet la main
    // sur l'état réel (via un refresh) que si le backend refuse.
    setSessions((prev) => prev.filter((s) => s.session_id !== id));
    if (id === sessionId) {
      setSessionId("");
      setMessages([]);
      localStorage.removeItem(storageKey);
    }
    fetch(`/api/chat/sessions/${encodeURIComponent(id)}?profile=${encodeURIComponent(profile)}`, {
      method: "DELETE",
    })
      .then((res) => {
        if (!res.ok) throw new Error("Suppression impossible");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Suppression impossible");
        refreshSessions();
      });
  }

  function startNewConversation() {
    setMessages([]);
    setError(null);
    stickToBottom.current = true;
    setSessionId("");
    localStorage.removeItem(storageKey);
  }

  async function send(text: string, forcedSessionId?: string) {
    const question = text.trim();
    if (!question || busy) return;
    setError(null);
    setBusy(true);
    setInput("");
    stickToBottom.current = true;

    // L'identifiant n'est créé qu'au premier message : ouvrir la page ne doit
    // pas semer une conversation vide dans l'historique.
    const activeId = forcedSessionId || sessionId || newSessionId();
    if (activeId !== sessionId) setSessionId(activeId);
    localStorage.setItem(storageKey, activeId);

    const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: question, toolCalls: [] }, { role: "assistant", content: "", toolCalls: [] }]);

    try {
      const formData = new FormData();
      formData.set("text", question);
      formData.set("session_id", activeId);
      formData.set("history", JSON.stringify(history));
      formData.set("profile", profile);

      const res = await fetch("/api/chat/query", { method: "POST", body: formData });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Échec de la requête");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          let event: SseEvent;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }
          applyEvent(event);
        }
      }
      // Le backend n'écrit les deux tours qu'à la toute fin du flux : rafraîchir
      // plus tôt ferait apparaître une conversation sans titre.
      refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setBusy(false);
    }
  }

  function applyEvent(event: SseEvent) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (!last || last.role !== "assistant") return prev;
      if (event.type === "token") {
        next[next.length - 1] = { ...last, content: last.content + event.content };
      } else if (event.type === "tool_call") {
        next[next.length - 1] = { ...last, toolCalls: [...last.toolCalls, event.label] };
      }
      return next;
    });
  }

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) {
      // Question posée depuis une autre vue : elle ouvre un fil neuf plutôt que
      // de s'ajouter à la conversation reprise au chargement.
      // `send` pose bien du state de façon synchrone (busy, champ vidé), mais
      // c'est une action déclenchée une fois au montage par un paramètre d'URL,
      // pas une synchronisation d'état dérivé — le rendu en cascade que la règle
      // cherche à éviter se limite ici au premier affichage du fil.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      send(q, newSessionId());
      router.replace(window.location.pathname);
      return;
    }

    // `initialSessions` vient du rendu serveur, qui retombe sur une liste vide
    // si le backend a bronché (CopilotView.loadSessions). Cet instantané est
    // ensuite resservi 60 s par le cache routeur : sans ce rattrapage, l'échec
    // d'une seule requête vidait la barre latérale de façon persistante, alors
    // que les conversations étaient bien en base.
    if (initialSessions.length === 0) refreshSessions();

    // Reprise du fil en cours après un simple rafraîchissement de page.
    const stored = localStorage.getItem(storageKey);
    if (stored) openSession(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Resynchronisation au retour sur la vue.
  //
  // `staleTimes.dynamic` (next.config.ts) fait resservir le payload RSC déjà
  // reçu pendant 60 s : revenir sur le Copilote ne rejoue NI le rendu serveur
  // qui peuple `initialSessions` (CopilotView), NI l'effet de montage ci-dessus.
  // La barre latérale restait donc figée sur l'instantané du premier rendu —
  // vide si l'historique avait échoué à ce moment-là — et le fil courant
  // disparaissait de l'écran alors qu'il était toujours en base.
  //
  // On se raccroche à `visibilitychange` (retour d'onglet) et `pageshow` (retour
  // arrière, restauration bfcache) plutôt qu'au montage : ce sont précisément
  // les transitions que le cache routeur rend silencieuses.
  useEffect(() => {
    const resync = () => {
      if (document.visibilityState !== "visible") return;
      // Un flux SSE en cours écrit dans `messages` : le recharger le tronquerait.
      if (busyRef.current) return;
      refreshSessions();
      const stored = localStorage.getItem(storageKey);
      // Fil déjà à l'écran, ou aucun fil repris : rien à recharger. On évite
      // ainsi de réécraser un brouillon de conversation neuve non encore envoyée.
      if (!stored || stored === sessionIdRef.current) return;
      openSession(stored);
    };
    document.addEventListener("visibilitychange", resync);
    window.addEventListener("pageshow", resync);
    return () => {
      document.removeEventListener("visibilitychange", resync);
      window.removeEventListener("pageshow", resync);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  return (
    <div className={`cop-wrap${sidebarOpen ? "" : " cop-wrap--closed"}`}>
      {sidebarOpen && (
        <ConversationList
          sessions={sessions}
          activeId={sessionId}
          onSelect={openSession}
          onDelete={deleteSession}
          onNew={startNewConversation}
        />
      )}

      <div className="cop-main">
        <div className="cop-bar">
          <button
            className="cop-toggle"
            type="button"
            onClick={toggleSidebar}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen
              ? "‹ Masquer l'historique"
              : `› Historique${sessions.length ? ` (${sessions.length})` : ""}`}
          </button>
          {/* Historique replié : sans ce raccourci, repartir de zéro obligerait
              à rouvrir le panneau pour atteindre son « + Nouvelle ». */}
          {!sidebarOpen && (
            <button className="cop-new" type="button" onClick={startNewConversation}>
              + Nouvelle
            </button>
          )}
        </div>

        {/* Le fil occupe le haut de la vue ; la barre de saisie et ses
            suggestions restent en bas, au plus près de la dernière réponse. */}
        {messages.length > 0 && (
          <div className="cop-thread" ref={threadRef} onScroll={onThreadScroll}>
            <div className="cop-thread-in" ref={threadInnerRef}>
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div className="bq" key={i}>
                  <span className="bq-av">{avatar}</span>
                  <p>{m.content}</p>
                </div>
              ) : (
                <div className="ba" key={i}>
                  <div className="ba-k">
                    <i />
                    Réponse · sourcée sur le miroir Odoo
                  </div>
                  {m.toolCalls.length > 0 && (
                    <p className="foot-n" style={{ marginTop: 0, marginBottom: 16 }}>
                      {m.toolCalls.join(" · ")}
                    </p>
                  )}
                  {m.content ? (
                    <div className="ba-md">
                      {/* Le message est découpé AVANT le markdown : les blocs
                          ```chart deviennent des graphiques, le reste passe par
                          ReactMarkdown. Sans ce découpage, react-markdown rend le
                          bloc en `<pre>` et le lecteur voit la spec JSON brute
                          (cf. components/copilot/chart-spec.ts). */}
                      {splitMessage(m.content).map((seg, s) =>
                        seg.kind === "chart" ? (
                          <ChartBlock key={s} source={seg.source} complete={seg.complete} />
                        ) : (
                          <ReactMarkdown key={s} remarkPlugins={[remarkGfm]}>
                            {seg.text}
                          </ReactMarkdown>
                        )
                      )}
                    </div>
                  ) : (
                    busy && i === messages.length - 1 && <p>…</p>
                  )}
                </div>
              )
            )}
            </div>
          </div>
        )}

        {/* Bloc de saisie ancré en bas du volet : il ne défile pas avec le fil.
            Repartir de zéro passe par le « + Nouvelle » de l'historique — pas
            de bouton intercalé ici, qui éloignerait la saisie du fil. */}
        <div className="cop-compose">
          {error && (
            <p className="note" style={{ borderLeftColor: "var(--alert)", color: "var(--alert)" }}>
              {error}
            </p>
          )}

          {messages.length === 0 && (
            <div className="chips">
              {suggested.map((q) => (
                <button key={q} className="chip-q" onClick={() => send(q)} disabled={busy}>
                  {q}
                </button>
              ))}
            </div>
          )}

          <form
            className="ask ask--bottom"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              type="text"
              placeholder={placeholder}
              aria-label="Question libre"
              value={input}
              disabled={busy}
              onChange={(e) => setInput(e.target.value)}
            />
            <Btn primary type="submit" disabled={busy}>
              {busy ? "…" : "Interroger"}
            </Btn>
          </form>
        </div>
      </div>
    </div>
  );
}
