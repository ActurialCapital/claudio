import { RootProvider } from 'fumadocs-ui/provider/next';
import type { Metadata } from 'next';
import './global.css';
import { Geist, JetBrains_Mono } from 'next/font/google';

const sans = Geist({ subsets: ['latin'], variable: '--ff-sans' });
const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--ff-mono' });

const site = process.env.VERCEL_PROJECT_PRODUCTION_URL;

export const metadata: Metadata = {
  metadataBase: new URL(site ? `https://${site}` : 'http://localhost:3000'),
  title: { default: 'claudio', template: '%s · claudio' },
  description: 'A voice in front of your Claude Code sessions. You talk; it answers, or hands the work to a session and tells you when it is done.',
  icons: { icon: '/img/sun.svg' },
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="flex flex-col min-h-screen font-sans">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
