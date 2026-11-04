import { useEffect, useState } from "react";

export function useCountdown(
  receivedAt: number | null,
  seconds: number | null
) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (receivedAt === null || seconds === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [receivedAt, seconds]);

  if (receivedAt === null || seconds === null) return null;
  return Math.max(0, Math.floor(seconds - (now - receivedAt) / 1000));
}
