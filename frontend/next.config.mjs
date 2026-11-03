/** @type {import('next').NextConfig} */
if (process.env.NODE_ENV === "production") {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl || !apiUrl.trim()) {
    throw new Error(
      "NEXT_PUBLIC_API_URL não pode estar vazio em produção (NODE_ENV=production). O build foi interrompido."
    );
  }
  const isLocal =
    apiUrl.includes("localhost") ||
    apiUrl.includes("127.0.0.1") ||
    apiUrl.includes("0.0.0.0");
  if (isLocal) {
    throw new Error(
      `NEXT_PUBLIC_API_URL não pode ter valor local em produção (NODE_ENV=production): ${apiUrl}`
    );
  }
}

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
};

export default nextConfig;
