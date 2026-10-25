import Link from 'next/link';
import { Hero } from '@/components/landing/hero';
import { Needs } from '@/components/landing/needs';
import { Reveal } from '@/components/landing/reveal';
import { Say } from '@/components/landing/say';
import { Stages } from '@/components/landing/stages';
import { Traits } from '@/components/landing/traits';
import { SunMark } from '@/components/sun-mark';
import { gitConfig } from '@/lib/shared';

const repo = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;

const sectionGap = 'mt-24 md:mt-40 lg:mt-48';

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col px-4 pt-4 text-landing-foreground md:px-6">
      <Reveal />
      <Hero />

      {/* one turn, stage by stage: the path lights up in step with the window that plays it */}
      <div className={`w-full ${sectionGap}`}>
        <Stages />
      </div>

      {/* what you say, and what it does with it */}
      <div className={`w-full ${sectionGap}`}>
        <Say />
      </div>

      {/* why it feels like talking: four traits, each shown by the transcript it leaves */}
      <div className={`w-full ${sectionGap}`}>
        <Traits />
      </div>

      {/* what it takes, and the first screen you will see: the doctor's check, lit like the hero */}
      <div className={`w-full ${sectionGap}`}>
        <Needs />
      </div>

      {/* the close: one quiet row on the page ground, set apart by space */}
      <footer className="mx-auto mt-16 mb-4 flex w-full max-w-[1400px] items-center gap-5 rounded-2xl bg-fd-card px-5 py-6 text-sm text-fd-foreground md:mt-24 md:mb-6 md:gap-8 md:px-12 md:py-8">
        {/* a band of its own one tone up from the page, so the page visibly ends here */}
        <Link
          href="/"
          className="press mr-auto flex items-center gap-2 rounded-md text-fd-foreground focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-fd-ring"
        >
          <SunMark size={20} />
          <span className="font-mono font-medium tracking-[-0.02em]">claudio</span> {/* taste-skill-ignore: the wordmark, in the brand mono face */}
        </Link>
        <Link className="foot-link" href="/docs">
          Docs
        </Link>
        <a className="foot-link" href={repo}>
          GitHub
        </a>
        <span className="text-fd-muted-foreground">MIT licence</span>
      </footer>
    </main>
  );
}
