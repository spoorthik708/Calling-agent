import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "YAVURA | Enterprise AI Conversational Agents",
  description: "Enterprise SaaS platform for deploying verified, real-time AI conversational voice agents.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
