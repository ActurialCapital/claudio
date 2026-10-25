'use client';
import Link from 'next/link';
import type { ComponentProps } from 'react';
import { FullSearchTrigger, SearchTrigger } from 'fumadocs-ui/layouts/shared/slots/search-trigger';
import { ThemeSwitch } from 'fumadocs-ui/layouts/shared/slots/theme-switch';
import { SunMark } from '@/components/sun-mark';

const repo = 'https://github.com/ActurialCapital/claudio';
const ring = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring';

// The landing's bar: the wordmark, Docs, search, the theme and GitHub, all in view at every width, no menu.
// Same height and ground as the docs bar, sticky under the phone's safe area.
export function Navbar({ className = '', ...props }: ComponentProps<'header'>) {
  return (
    <header
      id="nd-nav"
      {...props}
      className={`sticky top-[env(safe-area-inset-top,0px)] z-40 h-14 border-b bg-fd-background/80 backdrop-blur-lg ${className}`} /* taste-skill-ignore: matches the docs bar, as the user asked */
    >
      <nav aria-label="Main" className="mx-auto flex h-full max-w-(--fd-layout-width) items-center gap-1 px-4">
        <Link href="/" className={`press mr-auto flex items-center gap-2 rounded-md text-[15px] text-fd-foreground ${ring}`}>
          <SunMark size={22} />
          <span className="font-mono font-medium tracking-[-0.02em]">claudio</span> {/* taste-skill-ignore: the wordmark */}
        </Link>
        <Link href="/docs" className={`rounded-md px-2 py-2 text-sm text-fd-muted-foreground transition-colors hover:text-fd-foreground ${ring}`}>
          Docs
        </Link>
        <FullSearchTrigger hideIfDisabled className="ms-2 w-[220px] rounded-full ps-2.5 max-lg:hidden" />
        <SearchTrigger hideIfDisabled className="p-2 lg:hidden" />
        <ThemeSwitch className="ms-1 max-[359px]:hidden" />
        <a
          href={repo}
          aria-label="GitHub"
          className={`grid size-9 place-items-center rounded-md text-fd-muted-foreground transition-colors hover:bg-fd-accent hover:text-fd-foreground ${ring}`}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden>
            <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.34-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.7 5.4-5.27 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
          </svg>
        </a>
      </nav>
    </header>
  );
}
