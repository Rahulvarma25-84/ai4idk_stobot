import { useState, useEffect, useCallback } from "react";

const BASE = "/api";

export function useFetch(path, deps = []) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(BASE + path);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { load(); }, [load, ...deps]);

  return { data, loading, error, refetch: load };
}

export const api = {
  get:    (path)         => fetch(BASE + path).then(r => r.json()),
  post:   (path, body)   => fetch(BASE + path, { method: "POST",   headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  patch:  (path, body)   => fetch(BASE + path, { method: "PATCH",  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  delete: (path)         => fetch(BASE + path, { method: "DELETE" }).then(r => r.json()),
};
