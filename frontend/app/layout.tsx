import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atlas AI - Repository Knowledge Platform",
  description: "Repository understanding and change-impact analysis with knowledge graphs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
