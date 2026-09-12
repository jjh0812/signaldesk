/** Static frontend, served by FastAPI on the same localhost port. */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  poweredByHeader: false,
  reactStrictMode: true,
  images: { unoptimized: true },
};
export default nextConfig;
