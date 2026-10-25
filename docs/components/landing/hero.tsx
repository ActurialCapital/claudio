'use client';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Broadcast } from './broadcast';

// fumadocs.dev's hero, shader for shader: a grain gradient across the card and a 4x4-dithered shape.
// claudio's one change: the dithered sphere is still at rest and turns only while claudio is speaking.
const GrainGradient = dynamic(() => import('@paper-design/shaders-react').then((m) => m.GrainGradient), { ssr: false });
const Dithering = dynamic(() => import('@paper-design/shaders-react').then((m) => m.Dithering), { ssr: false });

function useDark() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains('dark'));
    read();
    const watch = new MutationObserver(read);
    watch.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => watch.disconnect();
  }, []);
  return dark;
}

const pill =
  'press inline-flex justify-center rounded-full px-5 py-3 font-medium tracking-tight max-sm:text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring';

export function Hero() {
  const dark = useDark();
  const [sound, setSound] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [still, setStill] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const onSpeaking = useCallback((on: boolean) => setSpeaking(on), []);

  useEffect(() => setStill(window.matchMedia('(prefers-reduced-motion: reduce)').matches), []);

  const toggleSound = () => {
    if (!audio.current) audio.current = new Audio();
    const el = audio.current;
    if (!sound) {
      // unlock playback inside the click, so the replay's clips may play on their own
      el.src = '/audio/handoff.mp3';
      el.volume = 0;
      el.play()
        .then(() => {
          el.pause();
          el.volume = 1;
        })
        .catch(() => {});
    } else el.pause();
    setSound(!sound);
  };

  return (
    <div className="hero-recede relative mx-auto flex w-full max-w-[1400px] flex-col overflow-hidden rounded-2xl border bg-origin-border md:h-[70vh] md:max-h-[900px] md:min-h-[680px] md:flex-row">
      <GrainGradient
        className="absolute inset-0 animate-fd-fade-in duration-800"
        colors={dark ? ['#39BE1C', '#9c2f05', '#7A2A0000'] : ['#fcfc51', '#ffa057', '#7A2A0020']}
        colorBack="#00000000"
        softness={1}
        intensity={0.9}
        noise={0.5}
        speed={still ? 0 : 1}
        shape="corners"
        minPixelRatio={1}
        maxPixelCount={2073600}
      />
      <Dithering
        width={720}
        height={720}
        colorBack="#00000000"
        colorFront={dark ? '#DF3F00' : '#fa8023'}
        shape="sphere"
        type="4x4"
        scale={0.5}
        size={3}
        speed={speaking && !still ? 0.5 : 0}
        frame={600000}
        className="absolute animate-fd-fade-in duration-400 max-lg:bottom-[-50%] max-lg:left-[-200px] lg:right-0 lg:top-[-5%]"
        minPixelRatio={1}
      />
      {/* the text layer spans the card above the replay: only its own parts take the pointer */}
      <div className="z-2 flex flex-col px-6 md:pointer-events-none md:size-full md:p-12 md:*:pointer-events-auto">
        <h1 className="mt-16 mb-10 text-4xl font-medium leading-tighter md:mt-20 xl:text-5xl">
          Talk, and your
          <br />
          sessions <span className="text-brand">work</span>.
        </h1>
        <div className="flex w-fit flex-row flex-wrap items-center justify-center gap-4">
          <Link href="/docs/guide/getting-started" className={`${pill} bg-brand text-brand-foreground hover:bg-brand-200`}>
            Install claudio
          </Link>
          <Link href="/sandbox" className={`${pill} border bg-fd-secondary text-fd-secondary-foreground hover:bg-fd-accent`}>
            Open the sandbox
          </Link>
        </div>
      </div>
      {/* after the text in the DOM, so the keyboard reaches the two buttons before the replay */}
      <Broadcast
        sound={sound}
        audio={audio}
        onSpeaking={onSpeaking}
        onToggleSound={toggleSound}
        className="relative z-1 order-2 mt-10 -mb-4 ml-6 -mr-[30%] h-[300px] md:absolute md:order-none md:m-0 md:h-auto md:bottom-[-1rem] md:left-[20%] md:right-12 md:top-[360px] lg:top-[460px]"
      />
    </div>
  );
}
