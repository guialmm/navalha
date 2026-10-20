"use client";

import { useEffect, useState } from "react";

type Agendamento = {
  id: number;
  inicio: string;
  cliente: string;
  telefone: string;
  servico: string;
  barbeiro: string;
  pela_recepcionista: boolean;
};

type ResumoConversa = {
  id: string;
  canal: string;
  iniciada_em: string;
  duracao_s: number | null;
  latencia_media_ms: number | null;
  custo_usd: number;
  falas: number;
  agendou: boolean;
};

type Resumo = {
  ligacoes: number;
  agendamentos_pela_ia: number;
  latencia_media_ms: number | null;
  custo_medio_usd: number | null;
};

type Mensagem = {
  papel: "cliente" | "agente" | "ferramenta";
  texto: string;
  ferramenta: string | null;
  latencia_ms: number | null;
  interrompida: boolean;
};
type Conversa = ResumoConversa & { tokens: number; mensagens: Mensagem[] };

const dia = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "2-digit" });
const hora = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const quando = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function duracao(s: number | null, inicio: string) {
  // A call the worker never closed (it was restarted mid-call) is not "ongoing" forever.
  if (s == null) return Date.now() - new Date(inicio).getTime() > 3_600_000 ? "sem encerramento" : "em andamento";
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}min ${s % 60}s`;
}

const decimal = (n: number, casas: number) =>
  n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const segundos = (ms: number | null) => (ms == null ? "—" : `${decimal(ms / 1000, 1)} s`);
const dolares = (v: number) => `US$ ${decimal(v, 3)}`;

export default function Painel() {
  const [agenda, setAgenda] = useState<Agendamento[] | null>(null);
  const [conversas, setConversas] = useState<ResumoConversa[] | null>(null);
  const [aberta, setAberta] = useState<Conversa | null>(null);
  const [resumo, setResumo] = useState<Resumo | null>(null);

  // Polls so a call made in another tab shows up while you watch.
  useEffect(() => {
    function carregar() {
      fetch("/api/agenda?dias=7").then((r) => r.json()).then(setAgenda).catch(() => setAgenda([]));
      fetch("/api/conversas?limite=10").then((r) => r.json()).then(setConversas).catch(() => setConversas([]));
      fetch("/api/resumo").then((r) => r.json()).then(setResumo).catch(() => {});
    }
    carregar();
    const id = setInterval(carregar, 15_000);
    return () => clearInterval(id);
  }, []);

  async function abrir(id: string) {
    setAberta(await (await fetch(`/api/conversas/${id}`)).json());
  }

  const porDia = new Map<string, Agendamento[]>();
  for (const a of agenda ?? []) {
    const chave = dia.format(new Date(a.inicio));
    porDia.set(chave, [...(porDia.get(chave) ?? []), a]);
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-text-muted">Barbearia Navalha</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-[-0.035em]">Painel</h1>
        </div>
        <p className="inline-flex items-center gap-2 text-xs text-text-muted">
          <span className="size-1.5 animate-pulse rounded-full bg-ok" /> atualiza sozinho a cada 15 s
        </p>
      </div>

      <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border lg:grid-cols-4">
        {[
          ["Ligações atendidas", resumo ? String(resumo.ligacoes) : "—"],
          ["Agendamentos pela IA", resumo ? String(resumo.agendamentos_pela_ia) : "—"],
          ["Tempo de resposta médio", resumo ? segundos(resumo.latencia_media_ms) : "—"],
          ["Custo médio por ligação*", resumo?.custo_medio_usd != null ? dolares(resumo.custo_medio_usd) : "—"],
        ].map(([rotulo, valor]) => (
          <div key={rotulo} className="bg-bg-elev px-5 py-4">
            <dt className="text-xs text-text-muted">{rotulo}</dt>
            <dd className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{valor}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[11px] text-text-muted">* no plano pago do Gemini; a demo roda no gratuito.</p>

      <div className="mt-10 grid gap-10 lg:grid-cols-2">
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">Agenda dos próximos 7 dias</h2>
          {agenda === null && <p className="mt-4 text-text-muted">Carregando…</p>}
          {agenda?.length === 0 && <p className="mt-4 text-text-muted">Nenhum horário marcado.</p>}
          <div className="mt-4 space-y-6">
            {[...porDia].map(([d, itens]) => (
              <div key={d}>
                <h3 className="text-sm font-semibold capitalize">{d}</h3>
                <ul className="mt-2 divide-y divide-border rounded-2xl border border-border bg-bg-elev">
                  {itens.map((a) => (
                    <li key={a.id} className="flex items-center gap-4 px-4 py-3">
                      <span className="w-12 font-mono text-sm">{hora.format(new Date(a.inicio))}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{a.cliente}</span>
                        <span className="block text-xs text-text-muted">
                          {a.servico} · {a.barbeiro} · {a.telefone}
                        </span>
                      </span>
                      {a.pela_recepcionista && (
                        <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">IA</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">Ligações recentes</h2>
          {conversas === null && <p className="mt-4 text-text-muted">Carregando…</p>}
          {conversas?.length === 0 && <p className="mt-4 text-text-muted">Nenhuma ligação ainda.</p>}
          <ul className="mt-4 space-y-2">
            {conversas?.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => abrir(c.id)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition hover:border-border-strong ${
                    aberta?.id === c.id ? "border-ink bg-bg-elev" : "border-border bg-bg-elev"
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-medium">{quando.format(new Date(c.iniciada_em))}</span>
                    <span className="text-xs text-text-muted">{c.canal === "voz" ? "voz" : "texto"}</span>
                  </span>
                  <span className="mt-1 flex flex-wrap gap-x-4 text-xs text-text-dim">
                    <span>{duracao(c.duracao_s, c.iniciada_em)}</span>
                    <span>{c.falas} {c.falas === 1 ? "fala" : "falas"}</span>
                    <span>resposta média {segundos(c.latencia_media_ms)}</span>
                    <span>{dolares(c.custo_usd)}</span>
                    {c.agendou && <span className="font-medium text-ok">agendou</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {aberta && (
            <div className="animate-surgir mt-6 rounded-2xl border border-border bg-bg-elev p-5">
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold">Transcrição</h3>
                <span className="text-xs text-text-muted">
                  {aberta.tokens.toLocaleString("pt-BR")} tokens · custo no plano pago {dolares(aberta.custo_usd)}
                </span>
              </div>
              <ol className="mt-4 space-y-2.5">
                {aberta.mensagens.map((m, i) =>
                  m.papel === "ferramenta" ? (
                    <li key={i} className="text-center font-mono text-[11px] text-text-muted">
                      ⚙ {m.ferramenta}: {m.texto}
                    </li>
                  ) : (
                    <li key={i} className={`flex ${m.papel === "cliente" ? "justify-end" : ""}`}>
                      <p
                        className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                          m.papel === "cliente" ? "bg-ink text-bg" : "bg-surface"
                        }`}
                      >
                        {m.texto}
                        {m.interrompida && <span className="ml-1 text-[10px] text-text-muted">· cortada pelo cliente</span>}
                        {m.latencia_ms != null && (
                          <span className="ml-2 text-[10px] text-text-muted">{segundos(m.latencia_ms)}</span>
                        )}
                      </p>
                    </li>
                  ),
                )}
              </ol>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
