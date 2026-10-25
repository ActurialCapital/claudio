import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { SunMark } from '@/components/sun-mark';
import { gitConfig } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <span className="flex items-center gap-2">
          <SunMark size={22} />
          <span className="font-mono font-medium tracking-[-0.02em]">claudio</span>
        </span>
      ),
    },
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
}
