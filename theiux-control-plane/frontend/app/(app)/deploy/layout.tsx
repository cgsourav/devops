import { Suspense, type ReactNode } from 'react'

export default function DeployLayout({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="container">Loading…</div>}>{children}</Suspense>
}
