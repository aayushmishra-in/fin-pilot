import process from "node:process";
import { URL } from "node:url";

const apiOrigin = process.env.FINPILOT_API_ORIGIN;
const isVercelBuild = process.env.VERCEL === "1";

if (isVercelBuild && !apiOrigin) {
  throw new Error("Set FINPILOT_API_ORIGIN to the deployed FinPilot API origin.");
}

const rewrites = [];

if (apiOrigin) {
  const parsedApiOrigin = new URL(apiOrigin);
  if (parsedApiOrigin.pathname !== "/" || parsedApiOrigin.search || parsedApiOrigin.hash) {
    throw new Error("FINPILOT_API_ORIGIN must contain only the API host origin.");
  }
  if (isVercelBuild && parsedApiOrigin.protocol !== "https:") {
    throw new Error("FINPILOT_API_ORIGIN must use HTTPS on Vercel.");
  }
  rewrites.push({
    source: "/api/:path*",
    destination: `${parsedApiOrigin.origin}/api/:path*`,
  });
}

rewrites.push({ source: "/(.*)", destination: "/index.html" });

export const config = {
  buildCommand: "npm run build",
  installCommand: "npm ci",
  outputDirectory: "dist",
  rewrites,
};
