import { Sidebar } from "./Sidebar";
import React from "react";

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-full bg-background overflow-hidden font-sans">
      <Sidebar />
      <main className="flex-1 h-full overflow-y-auto w-full">
        {children}
      </main>
    </div>
  );
}
