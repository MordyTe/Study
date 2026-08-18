import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The venue and data-source adapters run server-side only. Nothing in this
  // project should ever ship a credential to the browser, and there are no
  // credentials to ship: see src/lib/polymarket/allowlist.ts.
  serverExternalPackages: ['@anthropic-ai/sdk'],
};

export default nextConfig;
