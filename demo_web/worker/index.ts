/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

interface Env {
  ASSETS: Fetcher;
  GENERATED_IMAGES: R2Bucket;
  DB: D1Database;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

const GENERATED_IMAGE_PREFIX = "generated-images/";
const MAX_GENERATED_IMAGE_BYTES = 15 * 1024 * 1024;
const IMAGE_CONTENT_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function imageExtension(contentType: string): string {
  if (contentType === "image/png") return "png";
  if (contentType === "image/webp") return "webp";
  return "jpg";
}

async function handleGeneratedImages(request: Request, env: Env, url: URL): Promise<Response> {
  if (url.pathname === "/api/generated-images/status") {
    return json({ available: Boolean(env.GENERATED_IMAGES), provider: "cloudflare-r2" });
  }
  if (request.method === "POST" && url.pathname === "/api/generated-images") {
    const origin = request.headers.get("Origin");
    if (origin && origin !== url.origin) return json({ detail: "只允许当前站点上传图片" }, 403);
    const contentType = (request.headers.get("Content-Type") || "").split(";", 1)[0].toLowerCase();
    if (!IMAGE_CONTENT_TYPES.has(contentType)) return json({ detail: "仅支持 PNG、JPEG 或 WebP" }, 415);
    const declaredSize = Number(request.headers.get("Content-Length") || 0);
    if (declaredSize > MAX_GENERATED_IMAGE_BYTES) return json({ detail: "单张图片不得超过 15MB" }, 413);
    const bytes = await request.arrayBuffer();
    if (!bytes.byteLength || bytes.byteLength > MAX_GENERATED_IMAGE_BYTES) return json({ detail: "图片为空或超过 15MB" }, 413);
    const key = `${GENERATED_IMAGE_PREFIX}${Date.now()}-${crypto.randomUUID()}.${imageExtension(contentType)}`;
    await env.GENERATED_IMAGES.put(key, bytes, {
      httpMetadata: { contentType, cacheControl: "public, max-age=31536000, immutable" },
      customMetadata: { source: "short-drama-reference-frame" },
    });
    return json({
      status: "uploaded",
      provider: "cloudflare-r2",
      key,
      url: `${url.origin}/api/generated-images/${encodeURIComponent(key)}`,
    });
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/generated-images/")) {
    const key = decodeURIComponent(url.pathname.slice("/api/generated-images/".length));
    if (!key.startsWith(GENERATED_IMAGE_PREFIX) || key.includes("..")) return json({ detail: "图片路径无效" }, 400);
    const object = await env.GENERATED_IMAGES.get(key);
    if (!object) return json({ detail: "图片不存在" }, 404);
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("ETag", object.httpEtag);
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
    return new Response(object.body, { headers });
  }
  return json({ detail: "接口不存在" }, 404);
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/generated-images")) {
      return handleGeneratedImages(request, env, url);
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

export default worker;
