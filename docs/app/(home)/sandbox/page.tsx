import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Sandbox',
  description: 'Try claudio in the browser. The sandbox is being built.',
};

// A placeholder until the in-browser sandbox exists, so the hero's link never lands on a 404.
export default function SandboxPage() {
  return (
    <main className="flex flex-1 flex-col px-4 pt-4 pb-4 md:px-6 md:pb-6">
      <section className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col justify-end gap-8 rounded-2xl bg-fd-card px-6 py-14 md:px-12 md:py-20">
        <h1 className="text-[clamp(2.25rem,4.2vw,4rem)] font-medium leading-[1.02] tracking-[-0.035em] text-fd-foreground">
          The sandbox is being built
        </h1>
        <p className="max-w-[34rem] text-lg leading-relaxed text-fd-foreground">
          Soon you will try claudio here, in the browser. Until then, the docs show how to install it and talk to it.
        </p>
        <div className="flex flex-wrap gap-4">
          <Link
            href="/docs/guide/getting-started"
            className="press inline-flex justify-center rounded-full bg-brand px-5 py-3 font-medium tracking-tight text-brand-foreground hover:bg-brand-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring"
          >
            Install claudio
          </Link>
          <Link
            href="/docs"
            className="press inline-flex justify-center rounded-full bg-fd-secondary px-5 py-3 font-medium tracking-tight text-fd-secondary-foreground hover:bg-fd-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring"
          >
            Read the docs
          </Link>
        </div>
      </section>
    </main>
  );
}
