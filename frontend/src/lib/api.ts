"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d: { msg?: string }) => (d.msg ?? "").replace(/^Value error, /, "")).join(". ");
  }
  return fallback;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; file?: File } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: options.method ?? (options.body === undefined && !options.file ? "GET" : "POST"),
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.file ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("NULL's API can't be reached.", 0);
  }
  if (response.status === 401 && !path.startsWith("/auth/")) {
    window.location.assign("/login");
    throw new ApiError("Your session has ended.", 401);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const fallback = response.status >= 500 ? "NULL's API can't be reached." : `Request failed (${response.status})`;
    throw new ApiError(messageFrom(payload?.detail, fallback), response.status);
  }
  return response.json() as Promise<T>;
}

/** Fetches a resource, optionally polling until `pollWhile` returns false. */
export function useApi<T>(path: string | null, pollWhile?: (data: T) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const pollRef = useRef(pollWhile);
  pollRef.current = pollWhile;

  const load = useCallback(async () => {
    if (!path) return null;
    try {
      const result = await api<T>(path);
      setData(result);
      setError(null);
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong");
      return null;
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      const result = await load();
      if (!cancelled && result && pollRef.current?.(result)) timer = setTimeout(tick, 900);
    }
    setLoading(path !== null);
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [load, path]);

  return { data, error, loading, reload: load, setData };
}
