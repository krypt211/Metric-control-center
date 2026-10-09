export const dynamic = "force-dynamic";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Advertising Control Center",
  description: "Сводка рекламы из собственной базы данных",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
