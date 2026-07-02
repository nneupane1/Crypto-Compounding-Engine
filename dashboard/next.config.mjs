const dashboardApiUrl = (
  process.env.DASHBOARD_API_URL
  ?? process.env.NEXT_PUBLIC_DASHBOARD_API_URL
  ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    optimizePackageImports: ["lucide-react"]
  },
  async rewrites() {
    return [
      {
        source: "/dashboard-api/:path*",
        destination: `${dashboardApiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
