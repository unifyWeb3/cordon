import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adjudicated emergency pause",
  description:
    "Anyone can propose a freeze on a DeFi protocol. Nobody performs one unilaterally. A wrong freeze lifts itself.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div style={{ maxWidth: 980, margin: "0 auto", padding: "28px 20px 80px" }}>
          {children}
        </div>
      </body>
    </html>
  );
}
