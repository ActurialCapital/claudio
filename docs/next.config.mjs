import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  // lets two builds run side by side (NEXT_DIST_DIR=.next-a); Vercel uses the default
  distDir: process.env.NEXT_DIST_DIR || '.next',
};

export default withMDX(config);
