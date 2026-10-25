import defaultMdxComponents from 'fumadocs-ui/mdx';
import { Step, Steps } from 'fumadocs-ui/components/steps';
import { Tab, Tabs } from 'fumadocs-ui/components/tabs';
import { Accordion, Accordions } from 'fumadocs-ui/components/accordion';
import type { ComponentProps } from 'react';
import type { MDXComponents } from 'mdx/types';
import { Commands, Hooks, Settings, Voices } from './reference';
import { Transcript } from './transcript';

// a class each, so app/global.css can give them tone surfaces instead of outlines
function DocsTabs({ className, ...props }: ComponentProps<typeof Tabs>) {
  return <Tabs className={`docs-tabs ${className ?? ''}`} {...props} />;
}

function DocsAccordions({ className, ...props }: ComponentProps<typeof Accordions>) {
  return <Accordions className={`docs-accordions ${typeof className === 'string' ? className : ''}`} {...props} />;
}

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Step,
    Steps,
    Tab,
    Tabs: DocsTabs,
    Accordion,
    Accordions: DocsAccordions,
    Settings,
    Commands,
    Voices,
    Hooks,
    Transcript,
    ...components,
  } satisfies MDXComponents;
}

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
