import type { Metadata } from "next";
import { Inter_Tight } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const interTight = Inter_Tight({ variable: "--font-inter-tight", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Barbearia Navalha · Recepção por voz",
  description: "Recepcionista virtual que marca, remarca e cancela horários conversando.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${interTight.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-border/60 bg-bg/70 backdrop-blur-md">
          <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
            <Link href="/" className="text-lg font-extrabold tracking-tight">
              navalha<span className="text-accent">.</span>
            </Link>
            <div className="flex items-center gap-1 text-sm">
              <Link href="/" className="rounded-full px-3 py-1.5 text-text-dim transition hover:bg-surface hover:text-text">
                Recepção
              </Link>
              <Link href="/painel" className="rounded-full px-3 py-1.5 text-text-dim transition hover:bg-surface hover:text-text">
                Painel
              </Link>
              <a
                href="https://github.com/guialmm/navalha"
                className="ml-2 rounded-full border border-border-strong px-3 py-1.5 text-text-dim transition hover:border-ink hover:text-text"
              >
                Código
              </a>
            </div>
          </nav>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="py-6 text-center text-xs text-text-muted">
          Projeto de portfólio · barbearia fictícia · LiveKit + Gemini Live
        </footer>
      </body>
    </html>
  );
}
