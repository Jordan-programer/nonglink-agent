"use client";

import React, { useState, useEffect, useRef } from "react";
import { useApp } from "@/context/AppContext";

export default function GravadorVoz({ onCancel, onSendVoice, onUnsupportedOrDenied }) {
  const { t } = useApp();
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState([0.25, 0.4, 0.6, 0.35, 0.5, 0.3, 0.45, 0.25]);

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const animFrameRef = useRef(null);
  const chunksRef = useRef([]);
  const shouldSendRef = useRef(false);

  const cleanupMedia = () => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(() => {});
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    let mounted = true;
    let timer = null;

    async function startRecording() {
      if (
        typeof window === "undefined" ||
        !navigator.mediaDevices ||
        !navigator.mediaDevices.getUserMedia ||
        typeof window.MediaRecorder === "undefined"
      ) {
        onUnsupportedOrDenied?.();
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!mounted) {
          stream.getTracks().forEach((tr) => tr.stop());
          return;
        }
        streamRef.current = stream;

        const recorder = new MediaRecorder(stream);
        mediaRecorderRef.current = recorder;
        chunksRef.current = [];

        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) {
            chunksRef.current.push(e.data);
          }
        };

        recorder.onstop = () => {
          const mimeType = recorder.mimeType || "audio/webm";
          const blob = new Blob(chunksRef.current, { type: mimeType });
          cleanupMedia();
          if (shouldSendRef.current && blob.size > 0) {
            const ext = mimeType.includes("ogg")
              ? "ogg"
              : mimeType.includes("mp4")
              ? "m4a"
              : "webm";
            const file = new File([blob], `voz.${ext}`, { type: mimeType });
            onSendVoice?.(file);
          }
        };

        recorder.start();

        // Timer
        timer = setInterval(() => {
          setSeconds((s) => s + 1);
        }, 1000);

        // Audio level analyser
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) {
          const audioCtx = new AudioCtx();
          audioContextRef.current = audioCtx;
          const source = audioCtx.createMediaStreamSource(stream);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 32;
          source.connect(analyser);
          const dataArray = new Uint8Array(analyser.frequencyBinCount);

          const updateMeter = () => {
            if (!mounted) return;
            analyser.getByteFrequencyData(dataArray);
            const nextLevels = Array.from({ length: 8 }, (_, idx) => {
              const val = dataArray[idx] || 0;
              return Math.max(0.18, Math.min(1, val / 220));
            });
            setLevels(nextLevels);
            animFrameRef.current = requestAnimationFrame(updateMeter);
          };
          animFrameRef.current = requestAnimationFrame(updateMeter);
        }
      } catch {
        cleanupMedia();
        if (mounted) {
          onUnsupportedOrDenied?.();
        }
      }
    }

    startRecording();

    return () => {
      mounted = false;
      if (timer) clearInterval(timer);
      if (
        mediaRecorderRef.current &&
        mediaRecorderRef.current.state !== "inactive"
      ) {
        try {
          mediaRecorderRef.current.stop();
        } catch {
          // ignore
        }
      }
      cleanupMedia();
    };
  }, []);

  const handleCancel = () => {
    shouldSendRef.current = false;
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    } else {
      cleanupMedia();
    }
    onCancel?.();
  };

  const handleStopAndSend = () => {
    shouldSendRef.current = true;
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    } else {
      cleanupMedia();
      onCancel?.();
    }
  };

  const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      {/* Animated sound level + timer */}
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full bg-accent animate-pulse"
          aria-hidden="true"
        />
        <div
          className="flex h-6 items-center gap-1"
          aria-hidden="true"
        >
          {levels.map((lvl, idx) => (
            <span
              key={idx}
              style={{ height: `${Math.round(lvl * 22)}px` }}
              className="w-1 rounded-full bg-accent transition-all duration-75"
            />
          ))}
        </div>
        <span className="tabular-nums text-sm font-medium text-text">
          {mins}:{secs}
        </span>
      </div>

      {/* Cancel and Stop & Send buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleCancel}
          className="rounded-btn border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text hover:bg-sidebar-hover transition-ui"
        >
          {t.cancel}
        </button>
        <button
          type="button"
          onClick={handleStopAndSend}
          className="rounded-btn bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover transition-ui"
        >
          {t.stopAndSend}
        </button>
      </div>
    </div>
  );
}
