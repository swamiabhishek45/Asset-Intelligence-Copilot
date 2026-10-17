import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Variable Inter (no fixed weights), so the theme's in-between Medium (560)
// renders as set.
const inter = Inter({
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FlytBase Asset Copilot",
  description: "Generative UI copilot for oilfield asset intelligence (OpenUI + FastAPI backend)",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="light" suppressHydrationWarning>
      <body className={`${inter.className} min-h-full bg-background text-foreground antialiased`}>
        {children}
      </body>
    </html>
  );
}
