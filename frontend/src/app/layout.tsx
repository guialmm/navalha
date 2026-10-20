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
        <header className="border-b border-border">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-4 sm:px-6">
            <Link href="/" className="text-lg font-extrabold tracking-tight">
              navalha<span className="text-accent">.</span>
            </Link>
            <Link href="/" className="text-sm text-text-dim hover:text-text">Recepção</Link>
            <Link href="/painel" className="text-sm text-text-dim hover:text-text">Painel</Link>
          </nav>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-border py-6 text-center text-xs text-text-muted">
          Projeto de portfólio · barbearia fictícia · LiveKit + Gemini Live
        </footer>
      </body>
    </html>
  );
}
