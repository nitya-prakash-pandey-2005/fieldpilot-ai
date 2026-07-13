import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "FieldPilot AI",
  description: "Construction intelligence command center",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
      <html
        lang="en"
        className="h-full antialiased"
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-300">
        <Providers>
          <div className="flex w-full min-h-screen h-screen overflow-hidden">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden bg-[var(--bg-base)] relative">
              <Header />
              <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 relative z-10">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
