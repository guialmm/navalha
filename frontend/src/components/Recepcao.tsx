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

const STATUS: Record<EstadoOrbe, string> = {
  parado: "Recepção disponível",
  conectando: "Chamando a recepção",
  ouvindo: "Ouvindo",
  pensando: "Consultando a agenda",
  falando: "Falando",
};

export function Recepcao() {
  const [ligacao, setLigacao] = useState<Ligacao | null>(null);
  const [chamando, setChamando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Hanging up while the receptionist is mid-sentence cuts her transcript stream,
  // and livekit-client rejects that stream with nobody left to catch it. Expected,
  // harmless, and not worth a red error in the console.
  useEffect(() => {
    function ignorarFimDeStream(evento: PromiseRejectionEvent) {
      if (evento.reason?.name === "DataStreamError") evento.preventDefault();
    }
    window.addEventListener("unhandledrejection", ignorarFimDeStream);
    return () => window.removeEventListener("unhandledrejection", ignorarFimDeStream);
  }, []);

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

  return (
    <div className="palco relative flex min-h-[calc(100svh-4rem)] flex-col items-center px-4 pb-10 pt-10 sm:pt-14">
      <p className="text-xs font-medium uppercase tracking-[0.18em] text-text-muted">Barbearia Navalha · Recepção</p>
      {/* During a call the stage belongs to the orb, the captions and the controls. */}
      {!ligacao && (
        <>
          <h1 className="mt-3 max-w-3xl text-balance text-center text-4xl font-semibold tracking-[-0.035em] sm:text-[3.25rem] sm:leading-[1.05]">
            Marque seu horário <span className="texto-cromo">conversando</span>.
          </h1>
          <p className="mt-4 max-w-md text-balance text-center text-text-dim">
            A recepcionista é uma IA. Ela consulta a agenda, oferece horários e confirma tudo com você, por voz.
          </p>
        </>
      )}

      {ligacao ? (
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
          className="flex w-full flex-col items-center"
        >
          <Chamada />
          <RoomAudioRenderer />
        </LiveKitRoom>
      ) : (
        <Espera chamando={chamando} ligar={ligar} />
      )}

      {erro && (
        <p role="alert" className="mt-4 rounded-full bg-danger/10 px-4 py-1.5 text-sm text-danger">
          {erro}
        </p>
      )}
    </div>
  );
}

function Espera({ chamando, ligar }: { chamando: boolean; ligar: () => void }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setI((n) => (n + 1) % SUGESTOES.length), 3600);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <div className="mt-8">
        <Orbe estado={chamando ? "conectando" : "parado"} nivel={0} nivelCliente={0} />
      </div>
      <Status estado={chamando ? "conectando" : "parado"} />

      <button
        onClick={ligar}
        disabled={chamando}
        className="group mt-8 inline-flex items-center gap-3 rounded-full bg-ink py-3 pl-3 pr-6 font-medium text-bg shadow-[0_10px_40px_-12px_rgba(201,206,216,0.25)] transition hover:-translate-y-0.5 hover:shadow-[0_16px_48px_-14px_rgba(201,206,216,0.35)] active:translate-y-0 disabled:opacity-70"
      >
        <span className="cromo grid size-9 place-items-center rounded-full text-bg shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] transition group-hover:scale-105">
          <IconeTelefone />
        </span>
        {chamando ? "Chamando…" : "Ligar para a recepção"}
      </button>

      <p className="mt-6 h-6 text-sm text-text-muted">
        Experimente: <span key={i} className="animate-surgir inline-block text-text-dim">“{SUGESTOES[i]}”</span>
      </p>
    </>
  );
}

function Status({ estado }: { estado: EstadoOrbe }) {
  const ativo = estado !== "parado";
  return (
    <p className="mt-2 inline-flex items-center gap-2 text-sm font-medium text-text-dim" role="status">
      <span className={`size-1.5 rounded-full ${ativo ? "animate-pulse bg-accent" : "bg-ok"}`} />
      {STATUS[estado]}
    </p>
  );
}

/** Everything that needs the room: orb levels, captions, call controls. */
function Chamada() {
  const { state, audioTrack } = useVoiceAssistant();
  const { localParticipant, microphoneTrack, isMicrophoneEnabled } = useLocalParticipant();
  const room = useRoomContext();
  const nivelAgente = useTrackVolume(audioTrack);
  const nivelCliente = useTrackVolume(microphoneTrack?.track as LocalAudioTrack | undefined);
  const [transcricaoAberta, setTranscricaoAberta] = useState(false);
  // Subscribed once, from the first second of the call: a hook mounted later (the
  // drawer) would only see lines spoken after it opened.
  const transcricoes = useTranscriptions();
  const meuId = localParticipant.identity;

  const estado: EstadoOrbe =
    state === "speaking" ? "falando" : state === "thinking" ? "pensando" : state === "listening" ? "ouvindo" : "conectando";

  return (
    <>
      <div className="mt-4">
        <Orbe estado={estado} nivel={nivelAgente * 3} nivelCliente={isMicrophoneEnabled ? nivelCliente : 0} />
      </div>
      <Status estado={estado} />
      <Legendas transcricoes={transcricoes} meuId={meuId} />

      <div className="mt-6 flex items-center gap-2 rounded-full border border-border bg-bg-elev/80 p-2 shadow-[0_20px_40px_-20px_rgba(0,0,0,0.8)] backdrop-blur">
        <BotaoRedondo
          rotulo={isMicrophoneEnabled ? "Silenciar microfone" : "Ativar microfone"}
          ativo={!isMicrophoneEnabled}
          onClick={() => localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled)}
        >
          {isMicrophoneEnabled ? <IconeMicrofone /> : <IconeMicrofoneMudo />}
        </BotaoRedondo>
        <Cronometro />
        <BotaoRedondo rotulo="Ver transcrição" ativo={transcricaoAberta} onClick={() => setTranscricaoAberta((v) => !v)}>
          <IconeTexto />
        </BotaoRedondo>
        <button
          onClick={() => room.disconnect()}
          aria-label="Desligar"
          title="Desligar"
          className="grid size-11 place-items-center rounded-full bg-danger text-white transition hover:brightness-110 active:scale-95"
        >
          <IconeTelefone desligar />
        </button>
      </div>

      {transcricaoAberta && (
        <Transcricao transcricoes={transcricoes} meuId={meuId} fechar={() => setTranscricaoAberta(false)} />
      )}
    </>
  );
}

function BotaoRedondo(props: { rotulo: string; ativo: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={props.onClick}
      aria-label={props.rotulo}
      aria-pressed={props.ativo}
      title={props.rotulo}
      className={`grid size-11 place-items-center rounded-full transition active:scale-95 ${
        props.ativo ? "bg-ink text-bg" : "text-text-dim hover:bg-surface hover:text-text"
      }`}
    >
      {props.children}
    </button>
  );
}

function Cronometro() {
  const [segundos, setSegundos] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSegundos((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const mm = String(Math.floor(segundos / 60)).padStart(2, "0");
  const ss = String(segundos % 60).padStart(2, "0");
  return (
    <span className="min-w-14 text-center font-mono text-sm tabular-nums text-text-dim">
      {mm}:{ss}
    </span>
  );
}

/** Live captions: the line being spoken now, the previous one fading above it. */
type Falas = { transcricoes: ReturnType<typeof useTranscriptions>; meuId: string };

function Legendas({ transcricoes, meuId }: Falas) {
  const ultimas = transcricoes.slice(-2);

  return (
    <div className="mt-5 flex h-40 w-full max-w-2xl flex-col justify-end gap-2 text-center" aria-live="polite">
      {ultimas.length === 0 && <p className="text-text-muted">Pode falar quando ela atender.</p>}
      {ultimas.map((t, i) => {
        const cliente = t.participantInfo.identity === meuId;
        const atual = i === ultimas.length - 1;
        return (
          <p
            key={t.streamInfo.id}
            className={`animate-surgir text-balance transition-all duration-300 ${
              atual ? "line-clamp-4 text-lg leading-snug text-text sm:text-[1.35rem]" : "line-clamp-1 text-sm text-text-muted"
            }`}
          >
            <span
              className={`mr-2 align-middle text-[11px] font-semibold uppercase tracking-[0.14em] ${
                cliente ? "text-text-muted" : "text-accent"
              }`}
            >
              {cliente ? "Você" : "Recepção"}
            </span>
            {t.text}
          </p>
        );
      })}
    </div>
  );
}

function Transcricao({ transcricoes, meuId, fechar }: Falas & { fechar: () => void }) {
  const fim = useRef<HTMLDivElement>(null);
  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcricoes.length]);

  return (
    <aside className="animate-gaveta fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l border-border bg-bg-elev shadow-2xl">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="font-semibold">Transcrição</h2>
        <button onClick={fechar} aria-label="Fechar transcrição" className="rounded-full p-2 text-text-dim hover:bg-surface">
          <IconeFechar />
        </button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-5">
        {transcricoes.map((t) => {
          const cliente = t.participantInfo.identity === meuId;
          return (
            <div key={t.streamInfo.id} className={`flex ${cliente ? "justify-end" : ""}`}>
              <p
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-snug ${
                  cliente ? "rounded-br-md bg-ink text-bg" : "rounded-bl-md bg-surface"
                }`}
              >
                {t.text}
              </p>
            </div>
          );
        })}
        <div ref={fim} />
      </div>
    </aside>
  );
}

// Icons: 1.75px strokes, drawn to sit with Inter Tight's weight.
const tracos = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function IconeTelefone({ desligar = false }: { desligar?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className={`size-[18px] ${desligar ? "rotate-[135deg]" : ""}`} {...tracos}>
      <path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
    </svg>
  );
}

function IconeMicrofone() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" {...tracos}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

function IconeMicrofoneMudo() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" {...tracos}>
      <path d="M15 9.5V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 4.6 2.5M5 11a7 7 0 0 0 11.5 5.4M19 11a7 7 0 0 1-.7 3M12 18v3M3 3l18 18" />
    </svg>
  );
}

function IconeTexto() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" {...tracos}>
      <path d="M4 6h16M4 12h10M4 18h13" />
    </svg>
  );
}

function IconeFechar() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" {...tracos}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}
