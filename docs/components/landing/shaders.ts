'use client';
import dynamic from 'next/dynamic';

// The paper shaders the landing uses, loaded only in the browser (they draw to WebGL).
export const GrainGradient = dynamic(() => import('@paper-design/shaders-react').then((m) => m.GrainGradient), { ssr: false });
export const Dithering = dynamic(() => import('@paper-design/shaders-react').then((m) => m.Dithering), { ssr: false });
