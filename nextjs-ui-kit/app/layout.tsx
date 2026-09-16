import type { Metadata } from "next";
import "../styles/app.css";
import { Shell } from "../components/Shell";
import { ToastProvider } from "../components/Toasts";
import { THEME_INIT } from "../lib/theme";

export const metadata: Metadata = {
  title: "Your App",
  icons: { icon: "/next-media-logo.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the inline script may set data-theme before React hydrates
    <html lang="en" data-theme="" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <ToastProvider>
          {/* Pass the real user from your session; omit `user` on public pages. */}
          <Shell user={{ name: "admin", role: "Owner" }}>{children}</Shell>
        </ToastProvider>
      </body>
    </html>
  );
}
