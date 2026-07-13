/** @type {import('next').NextConfig} */
const nextConfig = {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: `https://afeabfb9ab01c5.lhr.life/api/:path*`,
        },
      ]
    },
}

export default nextConfig;
