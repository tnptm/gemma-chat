const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
export default {
  poweredByHeader: false,
  compress: false, // gzip would buffer the streamed model output
  experimental: { proxyTimeout: 300_000 },
  // Same-origin proxy: the browser only ever talks to Next, so httpOnly cookies
  // work without CORS and the Django port never has to be exposed.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "same-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};
