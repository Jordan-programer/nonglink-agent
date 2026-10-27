"use client";

import React from "react";
import Link from "next/link";
import { useApp } from "@/context/AppContext";

export default function NotFound() {
  const { t } = useApp();

  return (
    <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
      <h1 className="mb-3 font-serif text-2xl font-medium text-text">
        {t.brand}
      </h1>
      <Link
        href="/"
        className="rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover transition-ui"
      >
        {t.newChat}
      </Link>
    </div>
  );
}
