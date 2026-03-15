import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Bonat Brain',
  description: 'AI-powered business intelligence for Bonat merchants',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
