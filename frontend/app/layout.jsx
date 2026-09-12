import './globals.css';
import {UI_BUILD_ID} from '../lib/release.mjs';
import './desk.css';
export const metadata = {
  title: 'SignalDesk | 가격과 투자 체크 포인트',
  other: {'signaldesk-build': UI_BUILD_ID},
  description: 'Local source-linked forward catalyst and risk research, with daily-price context and historical anomaly analysis.',
};
export default function RootLayout({ children }) {
  return <html lang="ko"><body data-signaldesk-build={UI_BUILD_ID}>{children}</body></html>;
}
