import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAKSI — witness-validated secret sharing",
  description:
    "Split a master key across custodians with perfect secrecy, catch and name any custodian who lies, and let an AI agent use the key without the LLM ever seeing it.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#edf1ea" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Schibsted+Grotesk:wght@400;500;600;700;800&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
