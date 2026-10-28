import "./globals.css";
import { AppProvider } from "@/context/AppContext";
import BarraLateral from "@/components/BarraLateral";
import ModalAuth from "@/components/ModalAuth";
import DefinicoesDialog from "@/components/DefinicoesDialog";

export const metadata = {
  title: "NongLink",
  description:
    "Assistente para agricultores de Angola, RDC e Congo: cálculo de colheita, anúncios de venda e agendamento de regas.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }) {
  return (
    <html lang="pt" suppressHydrationWarning>
      <head>
        <link rel="stylesheet" href="/styles.css" />
      </head>
      <body>
        <AppProvider>
          <div className="safe-area-layout flex w-full overflow-hidden bg-bg text-text">
            <BarraLateral />
            <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
              {children}
            </main>
          </div>
          <ModalAuth />
          <DefinicoesDialog />
        </AppProvider>
      </body>
    </html>
  );
}
