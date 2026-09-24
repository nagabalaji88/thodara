export type ApiError = Error & { status?: number };

function readCookie(name: string): string | undefined {
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(`${name}=`));
  return item ? decodeURIComponent(item.slice(name.length + 1)) : undefined;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = readCookie("thodara_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, method, headers, credentials: "include" });
  } catch {
    throw Object.assign(new Error("The service could not be reached. Check your connection and try again."), { status: 0 });
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong. Please try again.";
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return body as T;
}

