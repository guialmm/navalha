"use client";

export type EstadoOrbe = "parado" | "conectando" | "ouvindo" | "pensando" | "falando";

const ROTULO: Record<EstadoOrbe, string> = {
  parado: "Pronta para atender",
  conectando: "Chamando…",
  ouvindo: "Ouvindo você",
  pensando: "Consultando a agenda…",
  falando: "Falando",
};

/**
 * A circle that breathes while idle, ripples with the customer's voice and
 * swells with the receptionist's. `nivel` is the loudest of the two, 0..1.
 */
export function Orbe({ estado, nivel, nivelCliente }: { estado: EstadoOrbe; nivel: number; nivelCliente: number }) {
  const escala = estado === "falando" ? 1 + Math.min(nivel, 1) * 0.35 : 1;
  const ondas = estado === "ouvindo" && nivelCliente > 0.04;

  return (
    <div className="flex flex-col items-center gap-6" role="status" aria-live="polite">
      <div className="relative grid size-56 place-items-center sm:size-64">
        {/* Ripples while the customer talks */}
        {ondas &&
          [0, 0.4, 0.8].map((atraso) => (
            <span
              key={atraso}
              className="absolute inset-6 rounded-full border-2 border-accent"
              style={{ animation: `onda 1.2s ease-out ${atraso}s infinite` }}
            />
          ))}
        {/* Spinning arc while connecting or thinking */}
        {(estado === "conectando" || estado === "pensando") && (
          <span
            className="absolute inset-2 rounded-full border-2 border-transparent border-t-accent"
            style={{ animation: `girar ${estado === "pensando" ? 0.9 : 1.6}s linear infinite` }}
          />
        )}
        <div
          className="size-40 rounded-full shadow-[0_20px_60px_-15px_rgba(164,71,31,0.55)] transition-transform duration-100 ease-out sm:size-44"
          style={{
            transform: `scale(${escala})`,
            background:
              "radial-gradient(circle at 35% 30%, #e9a37c 0%, #c4612f 38%, #a4471f 62%, #5e2810 100%)",
            animation: estado === "parado" || estado === "ouvindo" ? "respirar 4s ease-in-out infinite" : undefined,
          }}
        />
      </div>
      <p className="text-sm font-medium text-text-dim">{ROTULO[estado]}</p>
    </div>
  );
}
