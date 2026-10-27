"use client";

import React, { useState, useRef, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import GravadorVoz from "./GravadorVoz";

export default function CaixaTexto({
  value,
  onChange,
  onSend,
  onSendVoice,
  disabled = false,
  autoFocusTrigger = 0,
}) {
  const { t } = useApp();

  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [micAvailable, setMicAvailable] = useState(true);
  const [micErrorMessage, setMicErrorMessage] = useState("");

  const textareaRef = useRef(null);
  const attachContainerRef = useRef(null);
  const attachBtnRef = useRef(null);
  const attachMenuRef = useRef(null);
  const cameraInputRef = useRef(null);
  const galleryInputRef = useRef(null);

  // Auto-focus when "Novo chat" is clicked or component mounts on empty chat
  useEffect(() => {
    if (!isRecording && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [autoFocusTrigger, isRecording]);

  // Adjust textarea height up to 8 lines (~192px)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const maxHeight = 24 * 8; // 8 lines
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [value]);

  // Cleanup preview object URL
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  // Close attach menu on outside click
  useEffect(() => {
    if (!attachMenuOpen) return;
    function handleOutside(e) {
      if (
        attachContainerRef.current &&
        !attachContainerRef.current.contains(e.target)
      ) {
        setAttachMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [attachMenuOpen]);

  useEffect(() => {
    if (attachMenuOpen && attachMenuRef.current) {
      const first = attachMenuRef.current.querySelector('[role="menuitem"]');
      first?.focus();
    }
  }, [attachMenuOpen]);

  const handleAttachKeyDown = (e) => {
    if (!attachMenuOpen) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setAttachMenuOpen(false);
      attachBtnRef.current?.focus();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = attachMenuRef.current?.querySelectorAll('[role="menuitem"]');
      if (!items || items.length === 0) return;
      const arr = Array.from(items);
      const idx = arr.indexOf(document.activeElement);
      const next =
        e.key === "ArrowDown"
          ? (idx + 1) % arr.length
          : (idx - 1 + arr.length) % arr.length;
      arr[next]?.focus();
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    e.target.value = "";
  };

  const handleRemovePhoto = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(null);
    setPreviewUrl("");
  };

  const canSend =
    !disabled && (Boolean(value && value.trim().length > 0) || Boolean(selectedFile));

  const handleSubmit = () => {
    if (!canSend) return;
    const textToSend = (value || "").trim();
    const fileToSend = selectedFile;
    handleRemovePhoto();
    onSend?.({ text: textToSend, photoFile: fileToSend });
  };

  const handleStartVoice = () => {
    if (
      typeof window === "undefined" ||
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia ||
      typeof window.MediaRecorder === "undefined"
    ) {
      setMicAvailable(false);
      setMicErrorMessage(t.micError);
      return;
    }
    setMicErrorMessage("");
    setIsRecording(true);
  };

  return (
    <div className="w-full">
      <div className="rounded-textbox border border-border bg-surface shadow-soft focus-within:border-accent transition-ui">
        {isRecording ? (
          <GravadorVoz
            onCancel={() => setIsRecording(false)}
            onSendVoice={(audioFile) => {
              setIsRecording(false);
              onSendVoice?.(audioFile);
            }}
            onUnsupportedOrDenied={() => {
              setIsRecording(false);
              setMicAvailable(false);
              setMicErrorMessage(t.micError);
            }}
          />
        ) : (
          <>
            {/* Selected photo thumbnail inside box above text field */}
            {selectedFile && previewUrl && (
              <div className="flex items-center gap-3 px-4 pt-3">
                <div className="relative flex items-center gap-2 rounded-item border border-border bg-bg p-1.5">
                  <img
                    src={previewUrl}
                    alt={t.photoAttached}
                    className="h-14 w-14 rounded-[6px] object-cover"
                  />
                  <button
                    type="button"
                    onClick={handleRemovePhoto}
                    className="rounded-btn border border-border bg-surface px-2.5 py-1 text-xs font-medium text-text hover:bg-sidebar-hover transition-ui"
                  >
                    {t.removePhoto}
                  </button>
                </div>
              </div>
            )}

            {/* Textarea */}
            <div className="px-4 pt-3 pb-1">
              <textarea
                ref={textareaRef}
                rows={1}
                value={value}
                onChange={(e) => onChange?.(e.target.value)}
                placeholder={t.inputPlaceholder}
                aria-label={t.inputPlaceholder}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
                className="w-full resize-none bg-transparent text-[16px] leading-6 text-text placeholder:text-text-secondary focus:outline-none max-h-48 overflow-y-auto"
              />
            </div>

            {/* Bottom bar inside textbox */}
            <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
              <div className="flex items-center gap-1.5">
                {/* Hidden file inputs */}
                <input
                  ref={cameraInputRef}
                  type="file"
                  accept="image/*"
                  capture="environment"
                  onChange={handleFileChange}
                  className="hidden"
                  tabIndex={-1}
                />
                <input
                  ref={galleryInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  className="hidden"
                  tabIndex={-1}
                />

                {/* "+" Anexar button and menu */}
                <div
                  ref={attachContainerRef}
                  onKeyDown={handleAttachKeyDown}
                  className="relative"
                >
                  <button
                    ref={attachBtnRef}
                    type="button"
                    aria-label={t.attach}
                    aria-haspopup="menu"
                    aria-expanded={attachMenuOpen}
                    onClick={() => setAttachMenuOpen((prev) => !prev)}
                    className="flex h-9 w-9 items-center justify-center rounded-btn border border-border text-text hover:bg-sidebar-hover transition-ui"
                  >
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </button>

                  {attachMenuOpen && (
                    <div
                      ref={attachMenuRef}
                      role="menu"
                      aria-label={t.attach}
                      className="absolute bottom-full left-0 mb-2 w-44 rounded-item border border-border bg-surface p-1 shadow-menu z-40"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setAttachMenuOpen(false);
                          cameraInputRef.current?.click();
                        }}
                        className="flex w-full items-center gap-2 rounded-item px-2.5 py-2 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
                      >
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                          <circle cx="12" cy="13" r="4" />
                        </svg>
                        <span>{t.takePhoto}</span>
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setAttachMenuOpen(false);
                          galleryInputRef.current?.click();
                        }}
                        className="flex w-full items-center gap-2 rounded-item px-2.5 py-2 text-left text-sm text-text hover:bg-sidebar-hover transition-ui"
                      >
                        <svg
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                          <circle cx="8.5" cy="8.5" r="1.5" />
                          <polyline points="21 15 16 10 5 21" />
                        </svg>
                        <span>{t.choosePhoto}</span>
                      </button>
                    </div>
                  )}
                </div>

                {/* "Falar" button (hidden if mic unsupported/denied) */}
                {micAvailable && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={handleStartVoice}
                    className="flex h-9 items-center gap-1.5 rounded-btn border border-border px-3 text-sm font-medium text-text hover:bg-sidebar-hover disabled:opacity-50 transition-ui"
                  >
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                      <line x1="12" y1="19" x2="12" y2="23" />
                      <line x1="8" y1="23" x2="16" y2="23" />
                    </svg>
                    <span>{t.speak}</span>
                  </button>
                )}
              </div>

              {/* Send button (circle with up arrow) */}
              <button
                type="button"
                aria-label={t.send}
                disabled={!canSend}
                onClick={handleSubmit}
                className={`flex h-9 w-9 items-center justify-center rounded-full transition-ui ${
                  canSend
                    ? "bg-accent text-white hover:bg-accent-hover cursor-pointer"
                    : "bg-border text-text-secondary cursor-not-allowed opacity-60"
                }`}
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5 12 12 5 19 12" />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      {/* Microphone error notice if permission denied / unsupported */}
      {micErrorMessage && (
        <p role="alert" className="mt-1.5 text-center text-xs text-error">
          {micErrorMessage}
        </p>
      )}

      {/* Disclaimer line below textbox */}
      <p className="mt-2 text-center text-xs text-text-secondary">
        {t.disclaimer}
      </p>
    </div>
  );
}
