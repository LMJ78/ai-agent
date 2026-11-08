import { useEffect, useState } from "react";
import { getToken } from "./api";

/** 图片接口需要 Bearer，不能用普通 <img src>，先 fetch 成 blob URL。 */
export function useAuthedImage(path: string | null | undefined): string {
  const [src, setSrc] = useState("");

  useEffect(() => {
    if (!path) {
      setSrc("");
      return;
    }
    let objectUrl = "";
    let cancelled = false;
    const controller = new AbortController();

    fetch(path, {
      headers: { Authorization: `Bearer ${getToken()}` },
      signal: controller.signal
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setSrc("");
      });

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  return src;
}
