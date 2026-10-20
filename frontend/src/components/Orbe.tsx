"use client";

import { useEffect, useRef, useState } from "react";

export type EstadoOrbe = "parado" | "conectando" | "ouvindo" | "pensando" | "falando";

type Props = {
  estado: EstadoOrbe;
  /** Receptionist's voice, 0..1 */
  nivel: number;
  /** Customer's voice, 0..1 */
  nivelCliente: number;
  tamanho?: number;
};

// Chrome, like the razor: cool silvers and graphite drifting inside the sphere.
const MANCHAS = [
  { cor: "248, 250, 252", raio: 0.6, vel: 0.13, fase: 0.0, orbita: 0.34 }, // mirror white
  { cor: "186, 192, 202", raio: 0.66, vel: 0.17, fase: 2.1, orbita: 0.36 }, // silver
  { cor: "118, 124, 136", raio: 0.62, vel: 0.11, fase: 4.0, orbita: 0.42 }, // steel
  { cor: "226, 230, 236", raio: 0.38, vel: 0.21, fase: 3.3, orbita: 0.3 }, // highlight
  { cor: "40, 44, 52", raio: 0.55, vel: 0.15, fase: 1.2, orbita: 0.44 }, // graphite
];

// How lively each state is: drift speed and how much the voice level moves things.
const RITMO: Record<EstadoOrbe, { velocidade: number; saturacao: number }> = {
  parado: { velocidade: 0.35, saturacao: 1.2 },
  conectando: { velocidade: 0.9, saturacao: 0.7 },
  ouvindo: { velocidade: 0.5, saturacao: 1.2 },
  pensando: { velocidade: 1.8, saturacao: 1.1 },
  falando: { velocidade: 1.1, saturacao: 1.35 },
};

/**
 * A living sphere drawn on canvas. Blurred pigments orbit inside a circle;
 * the receptionist's voice swells it, the customer's voice ripples its rim.
 * Values arrive as props but are read from refs inside one rAF loop, so the
 * animation never waits for React.
 */
export function Orbe({ estado, nivel, nivelCliente, tamanho: maximo = 340 }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  // Fits narrow phones: never wider than the screen minus the page gutters.
  const [tamanho, setTamanho] = useState(maximo);
  useEffect(() => {
    const ajustar = () => setTamanho(Math.min(maximo, window.innerWidth - 48));
    ajustar();
    window.addEventListener("resize", ajustar);
    return () => window.removeEventListener("resize", ajustar);
  }, [maximo]);
  const alvo = useRef({ estado, nivel, nivelCliente });

  useEffect(() => {
    alvo.current = { estado, nivel, nivelCliente };
  }, [estado, nivel, nivelCliente]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    el.width = tamanho * dpr;
    el.height = tamanho * dpr;
    ctx.scale(dpr, dpr);

    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const r0 = tamanho * 0.36;
    const c = tamanho / 2;
    let t = 0;
    let agente = 0;
    let cliente = 0;
    let velocidade = RITMO.parado.velocidade;
    let ultimo = performance.now();
    let quadro = 0;

    function desenhar(agora: number) {
      const dt = Math.min((agora - ultimo) / 1000, 0.05);
      ultimo = agora;
      const { estado: e, nivel: n, nivelCliente: nc } = alvo.current;
      const ritmo = RITMO[e];
      // Ease toward targets: snappy attack, slower release, like a VU meter.
      const alvoAgente = e === "falando" ? Math.min(n, 1) : 0;
      agente += (alvoAgente - agente) * (alvoAgente > agente ? 0.35 : 0.08);
      const alvoCliente = e === "ouvindo" ? Math.min(nc * 2.5, 1) : 0;
      cliente += (alvoCliente - cliente) * (alvoCliente > cliente ? 0.3 : 0.07);
      velocidade += (ritmo.velocidade - velocidade) * 0.04;
      t += dt * (velocidade + agente * 2.2) * (reduzido ? 0 : 1);

      const respiro = reduzido ? 0 : Math.sin(agora / 1600) * 0.012;
      const r = r0 * (1 + respiro + agente * 0.16);

      ctx!.clearRect(0, 0, tamanho, tamanho);

      // Soft halo behind the sphere
      // Ends inside the canvas so it never shows a square edge.
      const halo = ctx!.createRadialGradient(c, c, r * 0.8, c, c, tamanho / 2);
      halo.addColorStop(0, `rgba(210, 216, 226, ${0.14 + agente * 0.28})`);
      halo.addColorStop(1, "rgba(210, 216, 226, 0)");
      ctx!.fillStyle = halo;
      ctx!.beginPath();
      ctx!.arc(c, c, tamanho / 2, 0, Math.PI * 2);
      ctx!.fill();

      // Customer's voice: a rim that wobbles outward
      if (cliente > 0.02) {
        ctx!.beginPath();
        for (let i = 0; i <= 64; i++) {
          const a = (i / 64) * Math.PI * 2;
          // Two slow, low harmonics: a breathing ripple rather than a scribble.
          const onda = Math.sin(a * 3 + t * 4) * 0.6 + Math.sin(a * 5 - t * 3) * 0.4;
          const rr = r * (1.07 + cliente * 0.08) + onda * cliente * r * 0.03;
          const x = c + Math.cos(a) * rr;
          const y = c + Math.sin(a) * rr;
          if (i === 0) ctx!.moveTo(x, y);
          else ctx!.lineTo(x, y);
        }
        ctx!.strokeStyle = `rgba(220, 226, 236, ${0.18 + cliente * 0.4})`;
        ctx!.lineWidth = 2;
        ctx!.stroke();
      }

      // The sphere: pigments clipped to a circle
      ctx!.save();
      ctx!.beginPath();
      ctx!.arc(c, c, r, 0, Math.PI * 2);
      ctx!.clip();
      ctx!.fillStyle = "#3c4048";
      ctx!.fillRect(0, 0, tamanho, tamanho);
      ctx!.filter = `blur(${tamanho * 0.07}px) saturate(${ritmo.saturacao})`;
      for (const m of MANCHAS) {
        const ang = t * m.vel * 6 + m.fase;
        const x = c + Math.cos(ang) * r * m.orbita + Math.sin(ang * 1.7) * r * 0.12;
        const y = c + Math.sin(ang * 0.8) * r * m.orbita;
        const raio = r * m.raio * (1 + agente * 0.25);
        const g = ctx!.createRadialGradient(x, y, 0, x, y, raio);
        g.addColorStop(0, `rgba(${m.cor}, 0.95)`);
        g.addColorStop(1, `rgba(${m.cor}, 0)`);
        ctx!.fillStyle = g;
        ctx!.beginPath();
        ctx!.arc(x, y, raio, 0, Math.PI * 2);
        ctx!.fill();
      }
      ctx!.filter = "none";
      // Glassy light from the top-left and shade at the bottom
      // Polished metal: a tight highlight up top, a deep falloff toward the rim.
      const luz = ctx!.createRadialGradient(c - r * 0.3, c - r * 0.42, 0, c, c, r * 1.02);
      luz.addColorStop(0, "rgba(255, 252, 240, 0.7)");
      luz.addColorStop(0.22, "rgba(255, 248, 230, 0.12)");
      luz.addColorStop(0.62, "rgba(0, 0, 0, 0)");
      luz.addColorStop(1, "rgba(8, 4, 1, 0.62)");
      ctx!.fillStyle = luz;
      ctx!.fillRect(0, 0, tamanho, tamanho);
      ctx!.restore();

      quadro = requestAnimationFrame(desenhar);
    }
    quadro = requestAnimationFrame(desenhar);
    return () => cancelAnimationFrame(quadro);
  }, [tamanho]);

  return <canvas ref={canvas} style={{ width: tamanho, height: tamanho }} aria-hidden className="select-none" />;
}
