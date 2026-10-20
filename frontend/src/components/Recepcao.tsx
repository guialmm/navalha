"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  useLocalParticipant,
  useRoomContext,
  useTrackVolume,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import type { LocalAudioTrack } from "livekit-client";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { type EstadoOrbe, Orbe } from "./Orbe";

type Ligacao = { url: string; token: string; sala: string };

const SUGESTOES = [
  "Quero cortar o cabelo sábado de manhã",
  "Tem horário com o Diego na quarta à tarde?",
  "Preciso remarcar meu horário",
  "Quanto custa corte e barba?",
];

export function Recepcao() {
  const [ligacao, setLigacao] = useState<Ligacao | null>(null);
  const [chamando, setChamando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function ligar() {
    setErro(null);
    setChamando(true);
    try {
      const r = await fetch("/api/ligacao", { method: "POST" });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? "Não foi possível ligar agora.");
      setLigacao(await r.json());
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ligar agora.");
      setChamando(false);
    }
  }

  function encerrar() {
    setLigacao(null);
    setChamando(false);
  }

  if (!ligacao) {
    return (
      <Layout
        erro={erro}
        palco={
          <>
            <Orbe estado={chamando ? "conectando" : "parado"} nivel={0} nivelCliente={0} />
            <button
              onClick={ligar}
              disabled={chamando}
              className="mt-6 rounded-full bg-ink px-7 py-3 font-semibold text-bg transition hover:bg-accent disabled:opacity-60"
            >
              {chamando ? "Chamando…" : "Ligar para a recepção"}
            </button>
          </>
        }
        lateral={<Sugestoes />}
      />
    );
  }

  return (
    <LiveKitRoom
      serverUrl={ligacao.url}
      token={ligacao.token}
      connect
      audio
      video={false}
      onDisconnected={encerrar}
      // The first error explains what happened; the disconnect that follows it doesn't.
      onError={() => setErro((atual) => atual ?? "A ligação caiu. Tente de novo.")}
      onMediaDeviceFailure={() => {
        setErro("Precisamos do microfone para a ligação. Libere o acesso no navegador.");
        encerrar();
      }}
    >
      <Layout erro={erro} palco={<Chamada />} lateral={<Transcricao />} />
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}

function Layout({ palco, lateral, erro }: { palco: ReactNode; lateral: ReactNode; erro: string | null }) {
  return (
    <div className="mx-auto grid max-w-5xl gap-10 px-4 py-12 sm:px-6 lg:grid-cols-2 lg:items-start">
      <section className="flex flex-col items-center text-center lg:sticky lg:top-12">
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">Barbearia Navalha</h1>
        <p className="mt-2 max-w-sm text-text-dim">
          Fale com a recepção para marcar, remarcar ou cancelar um horário. Ela é uma IA e atende por voz.
        </p>
        <div className="mt-10 flex flex-col items-center">{palco}</div>
        {erro && <p className="mt-4 text-sm text-danger">{erro}</p>}
      </section>
      <section>{lateral}</section>
    </div>
  );
}

function Sugestoes() {
  return (
    <div className="rounded-2xl border border-border bg-bg-elev p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">Experimente dizer</h2>
      <ul className="mt-4 space-y-3">
        {SUGESTOES.map((s) => (
          <li key={s} className="rounded-xl bg-surface px-4 py-3 text-text-dim">“{s}”</li>
        ))}
      </ul>
      <p className="mt-6 text-xs leading-relaxed text-text-muted">
        A agenda é de demonstração e os horários são fictícios. Se você disser um telefone, ele aparece
        mascarado no painel. Cada ligação usa a cota gratuita do Gemini, por isso há um limite de
        ligações seguidas.
      </p>
    </div>
  );
}

/** Maps the agent's state and both voices to the orb. */
function Chamada() {
  const { state, audioTrack } = useVoiceAssistant();
  const { microphoneTrack } = useLocalParticipant();
  const room = useRoomContext();
  const nivelAgente = useTrackVolume(audioTrack);
  const nivelCliente = useTrackVolume(microphoneTrack?.track as LocalAudioTrack | undefined);

  const estado: EstadoOrbe =
    state === "speaking" ? "falando" : state === "thinking" ? "pensando" : state === "listening" ? "ouvindo" : "conectando";

  return (
    <>
      <Orbe estado={estado} nivel={nivelAgente * 3} nivelCliente={nivelCliente} />
      <button
        onClick={() => room.disconnect()}
        className="mt-6 rounded-full border border-danger px-7 py-3 font-semibold text-danger transition hover:bg-danger hover:text-white"
      >
        Desligar
      </button>
    </>
  );
}

function Transcricao() {
  const transcricoes = useTranscriptions();
  const { localParticipant } = useLocalParticipant();
  const fim = useRef<HTMLDivElement>(null);
  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcricoes.length]);

  return (
    <div className="rounded-2xl border border-border bg-bg-elev p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">Transcrição ao vivo</h2>
      <div className="mt-4 max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        {transcricoes.length === 0 && <p className="text-text-muted">A conversa aparece aqui.</p>}
        {transcricoes.map((t) => {
          const cliente = t.participantInfo.identity === localParticipant.identity;
          return (
            <div key={t.streamInfo.id} className={`animate-surgir flex ${cliente ? "justify-end" : ""}`}>
              <p
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-snug ${
                  cliente ? "bg-ink text-bg" : "bg-surface text-text"
                }`}
              >
                {t.text}
              </p>
            </div>
          );
        })}
        <div ref={fim} />
      </div>
    </div>
  );
}
