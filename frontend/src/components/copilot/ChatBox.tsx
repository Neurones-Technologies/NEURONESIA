"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Acts, Btn } from "@/components/ui/primitives";

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

export function ChatBox({
  placeholder,
  suggested,
  avatar = "MOI",
}: {
  placeholder: string;
  suggested: string[];
  avatar?: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<string>("");
  const router = useRouter();
  const searchParams = useSearchParams();
  useEffect(() => {
    sessionId.current = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2);
  }, []);

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) {
      send(q);
      router.replace(window.location.pathname);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setError(null);
    setBusy(true);
    setInput("");

    const history = messages.slice(-6).map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: question, toolCalls: [] }, { role: "assistant", content: "", toolCalls: [] }]);

    try {
      const formData = new FormData();
      formData.set("text", question);
      formData.set("session_id", sessionId.current);
      formData.set("history", JSON.stringify(history));

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

  return (
    <div>
      <form
        className="ask"
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

      {messages.length === 0 && (
        <div className="chips" style={{ marginBottom: 18 }}>
          {suggested.map((q) => (
            <button key={q} className="chip-q" onClick={() => send(q)} disabled={busy}>
              {q}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="note" style={{ borderLeftColor: "var(--alert)", color: "var(--alert)" }}>
          {error}
        </p>
      )}

      {messages.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
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
                {(m.content || (busy && i === messages.length - 1 ? "…" : ""))
                  .split(/\n\s*\n/)
                  .filter((p) => p.trim() || m.content === "")
                  .map((para, j) => (
                    <p key={j}>{para.trim()}</p>
                  ))}
              </div>
            )
          )}
        </div>
      )}

      {messages.length > 0 && (
        <Acts>
          <Btn
            onClick={() => {
              setMessages([]);
              setError(null);
            }}
          >
            Nouvelle conversation
          </Btn>
        </Acts>
      )}
    </div>
  );
}
