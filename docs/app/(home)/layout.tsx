import { HomeLayout } from 'fumadocs-ui/layouts/home';
import { Navbar } from '@/components/landing/navbar';
import { baseOptions } from '@/lib/layout.shared';
import './landing.css';

// The landing keeps Fumadocs' home layout but draws its own bar: every link in view at every width, no menu.
export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <HomeLayout {...baseOptions()} links={[{ text: 'Docs', url: '/docs' }]} slots={{ header: Navbar }}>
      {children}
    </HomeLayout>
  );
}
