/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable React Strict Mode
  reactStrictMode: true,
  
  // Image optimization
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'surveyfieldwork.com',
      },
      {
        protocol: 'https',
        hostname: '*.surveyfieldwork.com',
      },
      {
        protocol: 'http',
        hostname: 'localhost',
      },
    ],
    // Supported formats
    formats: ['image/avif', 'image/webp'],
  },
  
  // Environment variables exposed to browser
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL || 'https://surveyfieldwork.com',
  },
  
  // Trailing slashes for URLs
  trailingSlash: false,
  
  // Powered by header (security)
  poweredByHeader: false,
  
  // Compression
  compress: true,
  
  // Headers for security and caching
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
        ],
      },
      {
        // Cache static assets
        source: '/assets/(.*)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
        ],
      },
    ]
  },
  
  // Redirects (if needed)
  async redirects() {
    return [
      // Example: redirect old WordPress URLs if needed
      // {
      //   source: '/wp-content/:path*',
      //   destination: '/assets/:path*',
      //   permanent: true,
      // },
    ]
  },
}

module.exports = nextConfig
