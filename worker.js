function jsonResponse(payload, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("content-type", "application/json");
  headers.set("cache-control", "no-store");
  return new Response(JSON.stringify(payload), { ...init, headers });
}

function textResponse(text, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("content-type", "text/plain");
  headers.set("cache-control", "no-store");
  return new Response(text, { ...init, headers });
}

function withCors(response, env) {
  const origin = env.CMS_ALLOWED_ORIGIN || "*";
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", origin);
  headers.set("access-control-allow-methods", "GET,POST,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,authorization");
  headers.set("access-control-max-age", "86400");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function sanitizeDevice(input) {
  if (!input) {
    return null;
  }
  const trimmed = String(input).trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(trimmed)) {
    return null;
  }
  return trimmed;
}

function sanitizeFilename(input) {
  if (!input) {
    return null;
  }
  const name = String(input).split("/").pop().split("\\").pop().trim();
  if (!name) {
    return null;
  }
  if (!/^[A-Za-z0-9._-]{1,128}$/.test(name)) {
    return null;
  }
  const lowered = name.toLowerCase();
  const allowed = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"];
  if (!allowed.some((ext) => lowered.endsWith(ext))) {
    return null;
  }
  return name;
}

function scanKey(device) {
  return `device:${device}`;
}

function cmsSettingsKey(device) {
  return `cms:settings:${device}`;
}

function cmsImagesKey(device) {
  return `cms:images:${device}`;
}

function cmsImageKey(device, name) {
  return `cms:image:${device}:${name}`;
}

function cmsSessionKey(token) {
  return `cms:session:${token}`;
}

function parseJsonOrNull(text) {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function getCmsState(env, device) {
  const settingsRaw = await env.SCANS.get(cmsSettingsKey(device));
  const imagesRaw = await env.SCANS.get(cmsImagesKey(device));

  const settingsParsed = parseJsonOrNull(settingsRaw) || {};
  const imagesParsed = parseJsonOrNull(imagesRaw);

  const settings = {
    website_url:
      typeof settingsParsed.website_url === "string" && settingsParsed.website_url.trim()
        ? settingsParsed.website_url
        : "https://example.com",
    slide_seconds:
      Number.isFinite(Number(settingsParsed.slide_seconds))
        ? Math.max(1, Number(settingsParsed.slide_seconds))
        : 5,
    rev: Number.isFinite(Number(settingsParsed.rev))
      ? Number(settingsParsed.rev)
      : 0,
  };

  const images = Array.isArray(imagesParsed)
    ? imagesParsed.filter(
        (item) =>
          item &&
          typeof item.name === "string" &&
          sanitizeFilename(item.name) &&
          typeof item.contentType === "string"
      )
    : [];

  return { settings, images };
}

async function saveCmsState(env, device, settings, images) {
  await env.SCANS.put(cmsSettingsKey(device), JSON.stringify(settings));
  await env.SCANS.put(cmsImagesKey(device), JSON.stringify(images));
}

async function checkCmsAuth(request, env) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.startsWith("Bearer ")) {
    return false;
  }
  const token = auth.slice(7).trim();
  if (!token) {
    return false;
  }
  const session = await env.SCANS.get(cmsSessionKey(token));
  return Boolean(session);
}

function contentTypeForName(name) {
  const lowered = name.toLowerCase();
  if (lowered.endsWith(".png")) return "image/png";
  if (lowered.endsWith(".jpg") || lowered.endsWith(".jpeg")) return "image/jpeg";
  if (lowered.endsWith(".gif")) return "image/gif";
  if (lowered.endsWith(".bmp")) return "image/bmp";
  if (lowered.endsWith(".webp")) return "image/webp";
  return "application/octet-stream";
}

async function handleCmsLogin(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }

  const username = typeof body.username === "string" ? body.username : "";
  const password = typeof body.password === "string" ? body.password : "";

  const expectedUser = env.CMS_USERNAME || "admin";
  const expectedPass = env.CMS_PASSWORD || "change-this-password";

  if (username !== expectedUser || password !== expectedPass) {
    return jsonResponse({ error: "invalid_credentials" }, { status: 401 });
  }

  const token = crypto.randomUUID();
  const ttl = Number.parseInt(env.CMS_SESSION_TTL_SECONDS || "43200", 10);
  const effectiveTtl = Number.isFinite(ttl) && ttl > 0 ? ttl : 43200;

  await env.SCANS.put(cmsSessionKey(token), "1", { expirationTtl: effectiveTtl });

  return jsonResponse({ token, expiresInSeconds: effectiveTtl });
}

async function handleCmsState(request, env, device) {
  const authed = await checkCmsAuth(request, env);
  if (!authed) {
    return jsonResponse({ error: "unauthorized" }, { status: 401 });
  }

  const state = await getCmsState(env, device);
  return jsonResponse({
    device,
    website_url: state.settings.website_url,
    slide_seconds: state.settings.slide_seconds,
    rev: state.settings.rev,
    images: state.images,
  });
}

async function handleCmsSettings(request, env, device) {
  const authed = await checkCmsAuth(request, env);
  if (!authed) {
    return jsonResponse({ error: "unauthorized" }, { status: 401 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }

  const websiteUrl = typeof body.website_url === "string" ? body.website_url.trim() : "";
  const slideSeconds = Number(body.slide_seconds);

  if (!websiteUrl) {
    return jsonResponse({ error: "missing_website_url" }, { status: 400 });
  }
  if (!Number.isFinite(slideSeconds) || slideSeconds <= 0) {
    return jsonResponse({ error: "invalid_slide_seconds" }, { status: 400 });
  }

  const state = await getCmsState(env, device);
  const nextSettings = {
    website_url: websiteUrl,
    slide_seconds: Math.max(1, Math.round(slideSeconds)),
    rev: state.settings.rev + 1,
  };

  await saveCmsState(env, device, nextSettings, state.images);
  return jsonResponse({ ok: true, rev: nextSettings.rev });
}

async function handleCmsUpload(request, env, device) {
  const authed = await checkCmsAuth(request, env);
  if (!authed) {
    return jsonResponse({ error: "unauthorized" }, { status: 401 });
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return jsonResponse({ error: "invalid_form_data" }, { status: 400 });
  }

  const files = form.getAll("images");
  if (!files.length) {
    return jsonResponse({ error: "no_files" }, { status: 400 });
  }

  const state = await getCmsState(env, device);
  const imageMap = new Map(state.images.map((item) => [item.name, item]));
  let uploaded = 0;

  for (const file of files) {
    if (!file || typeof file.name !== "string") {
      continue;
    }
    const safeName = sanitizeFilename(file.name);
    if (!safeName) {
      continue;
    }

    const bytes = await file.arrayBuffer();
    const contentType = file.type || contentTypeForName(safeName);
    await env.SCANS.put(cmsImageKey(device, safeName), bytes, {
      metadata: { contentType },
    });
    imageMap.set(safeName, { name: safeName, contentType });
    uploaded += 1;
  }

  if (!uploaded) {
    return jsonResponse({ error: "no_valid_files" }, { status: 400 });
  }

  const nextImages = Array.from(imageMap.values()).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  const nextSettings = {
    ...state.settings,
    rev: state.settings.rev + 1,
  };

  await saveCmsState(env, device, nextSettings, nextImages);
  return jsonResponse({ ok: true, uploaded, rev: nextSettings.rev });
}

async function handleCmsDelete(request, env, device) {
  const authed = await checkCmsAuth(request, env);
  if (!authed) {
    return jsonResponse({ error: "unauthorized" }, { status: 401 });
  }

  let filename = "";
  const contentType = request.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const body = await request.json();
      filename = body.filename || "";
    } catch {
      return jsonResponse({ error: "invalid_json" }, { status: 400 });
    }
  } else {
    const form = await request.formData();
    filename = form.get("filename") || "";
  }

  const safeName = sanitizeFilename(filename);
  if (!safeName) {
    return jsonResponse({ error: "invalid_filename" }, { status: 400 });
  }

  const state = await getCmsState(env, device);
  const nextImages = state.images.filter((item) => item.name !== safeName);
  if (nextImages.length === state.images.length) {
    return jsonResponse({ error: "not_found" }, { status: 404 });
  }

  await env.SCANS.delete(cmsImageKey(device, safeName));
  const nextSettings = {
    ...state.settings,
    rev: state.settings.rev + 1,
  };
  await saveCmsState(env, device, nextSettings, nextImages);

  return jsonResponse({ ok: true, rev: nextSettings.rev });
}

async function handleCmsPublic(requestUrl, env, device) {
  const state = await getCmsState(env, device);
  const images = state.images.map((item) => ({
    name: item.name,
    contentType: item.contentType,
    url: `${requestUrl.origin}/cms/image?device=${encodeURIComponent(device)}&name=${encodeURIComponent(item.name)}`,
  }));

  return jsonResponse({
    device,
    website_url: state.settings.website_url,
    slide_seconds: state.settings.slide_seconds,
    rev: state.settings.rev,
    images,
  });
}

async function handleCmsImage(requestUrl, env, device) {
  const safeName = sanitizeFilename(requestUrl.searchParams.get("name"));
  if (!safeName) {
    return jsonResponse({ error: "invalid_filename" }, { status: 400 });
  }

  const result = await env.SCANS.getWithMetadata(cmsImageKey(device, safeName), {
    type: "arrayBuffer",
  });

  if (!result || !result.value) {
    return jsonResponse({ error: "not_found" }, { status: 404 });
  }

  const contentType =
    (result.metadata && result.metadata.contentType) || contentTypeForName(safeName);

  return new Response(result.value, {
    status: 200,
    headers: {
      "content-type": contentType,
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "OPTIONS") {
      return withCors(new Response(null, { status: 204 }), env);
    }

    if (path === "/") {
      return withCors(textResponse("ok"), env);
    }

    if (path === "/cms/login" && request.method === "POST") {
      return withCors(await handleCmsLogin(request, env), env);
    }

    const device = sanitizeDevice(url.searchParams.get("device"));

    if (path === "/scan") {
      if (!device) {
        return withCors(jsonResponse({ error: "missing_device" }, { status: 400 }), env);
      }
      await env.SCANS.put(scanKey(device), String(Date.now()));
      return withCors(textResponse("ok"), env);
    }

    if (path === "/poll") {
      if (!device) {
        return withCors(jsonResponse({ error: "missing_device" }, { status: 400 }), env);
      }
      const last = await env.SCANS.get(scanKey(device));
      return withCors(
        jsonResponse({
          device,
          lastScanMs: last ? Number(last) : null,
        }),
        env
      );
    }

    if (!device) {
      return withCors(jsonResponse({ error: "missing_device" }, { status: 400 }), env);
    }

    if (path === "/cms/state" && request.method === "GET") {
      return withCors(await handleCmsState(request, env, device), env);
    }

    if (path === "/cms/settings" && request.method === "POST") {
      return withCors(await handleCmsSettings(request, env, device), env);
    }

    if (path === "/cms/upload" && request.method === "POST") {
      return withCors(await handleCmsUpload(request, env, device), env);
    }

    if (path === "/cms/delete" && request.method === "POST") {
      return withCors(await handleCmsDelete(request, env, device), env);
    }

    if (path === "/cms/public" && request.method === "GET") {
      return withCors(await handleCmsPublic(url, env, device), env);
    }

    if (path === "/cms/image" && request.method === "GET") {
      return withCors(await handleCmsImage(url, env, device), env);
    }

    return withCors(textResponse("not found", { status: 404 }), env);
  },
};
