"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [q] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // These records are immutable once finalized. The old 4s poll generated ~45
            // reads/minute against a documented 30/min shared budget -- which is what made
            // /case/[caseId] intermittently 404 for cases that exist. Only an in-flight
            // transaction needs fast polling, and it drives its own timer in the page.
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      })
  );
  return <QueryClientProvider client={q}>{children}</QueryClientProvider>;
}
