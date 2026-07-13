/** @type {import('next').NextConfig} */
const nextConfig = {
  // Generates a framework-free site in `out/`, suitable for GitHub Pages.
  // The dashboard already falls back to its demo data when no API is available.
  output: 'export',
  trailingSlash: true,
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  images: {
    unoptimized: true,
  },
}

export default nextConfig;
