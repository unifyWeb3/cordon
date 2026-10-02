"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [q] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { refetchInterval: 4000, staleTime: 1500, retry: 1 },
        },
      })
  );
  return <QueryClientProvider client={q}>{children}</QueryClientProvider>;
}
