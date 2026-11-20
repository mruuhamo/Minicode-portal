import { useEffect, useRef } from "react";
import type { PlayerProps } from "./types";

export function Html5Player({ src, seek, title }: PlayerProps & { src: string }) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const apply = () => {
      video.currentTime = seek.seconds;
      if (seek.nonce > 0) void video.play?.()?.catch(() => undefined); // autoplay can be blocked; the user presses play
    };
    if (video.readyState >= 1) {
      apply();
      return;
    }
    video.addEventListener("loadedmetadata", apply, { once: true });
    return () => video.removeEventListener("loadedmetadata", apply);
  }, [seek.seconds, seek.nonce, src]);

  return (
    <div className="mcl-player mcl-player--html5">
      <video ref={ref} src={src} controls preload="metadata" aria-label={title}>
        <track kind="captions" />
      </video>
    </div>
  );
}
