"use client";

import React, { useState } from "react";
import { useApp } from "@/context/AppContext";
import Talao from "./Talao";
import ProvaDeFoto from "./ProvaDeFoto";

/**
 * Simple, safe Markdown renderer for agent responses:
 * Supports bold (**text**), bullet lists (- or *), numbered lists (1.), and markdown tables (| a | b |).
 */
function renderInlineMarkdown(text) {
  if (!text) return null;
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

function SimpleMarkdown({ content }) {
  if (!content) return null;
  const lines = String(content).split(/\r?\n/);
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    // Table detection
    if (
      line.trim().startsWith("|") &&
      i + 1 < lines.length &&
      /^\s*\|[\s\-:|]+\|\s*$/.test(lines[i + 1])
    ) {
      const headerCells = line
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((c) => c.trim());
      i += 2; // skip header and separator
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const rowCells = lines[i]
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => c.trim());
        rows.push(rowCells);
        i++;
      }
      blocks.push(
        <table key={`tbl-${i}`}>
          <thead>
            <tr>
              {headerCells.map((hc, idx) => (
                <th key={idx}>{renderInlineMarkdown(hc)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, rIdx) => (
              <tr key={rIdx}>
                {r.map((cell, cIdx) => (
                  <td key={cIdx}>{renderInlineMarkdown(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
      continue;
    }

    // Unordered list
    if (/^\s*[-*•]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={`ul-${i}`}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={`ol-${i}`}>
          {items.map((item, idx) => (
            <li key={idx}>{renderInlineMarkdown(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // Regular paragraph
    const paraLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("|") &&
      !/^\s*[-*•]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={`p-${i}`}>
        {paraLines.map((pl, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <br />}
            {renderInlineMarkdown(pl)}
          </React.Fragment>
        ))}
      </p>
    );
  }

  return <div className="agent-prose">{blocks}</div>;
}

export default function Mensagem({ mensagem, onConfirmAction }) {
  const { t } = useApp();
  const [copied, setCopied] = useState(false);

  const isUser = mensagem.papel === "utilizador";

  const handleCopy = async () => {
    if (!mensagem.texto) return;
    try {
      await navigator.clipboard.writeText(mensagem.texto);
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      // Fallback copy
    }
  };

  if (isUser) {
    return (
      <div className="flex w-full justify-end">
        <div className="max-w-[80%] rounded-user bg-user-block px-4 py-3 font-sans text-[16px] leading-relaxed text-text">
          {mensagem.anexo_json && (
            <ProvaDeFoto anexoJson={mensagem.anexo_json} />
          )}
          {mensagem.texto && (
            <div className="whitespace-pre-wrap break-words max-w-[70ch]">
              {mensagem.texto}
            </div>
          )}
        </div>
      </div>
    );
  }

  const hasTalao =
    Boolean(mensagem.accao_json) ||
    mensagem.estado_accao === "pendente" ||
    mensagem.estado_accao === "confirmada" ||
    mensagem.estado_accao === "cancelada";

  return (
    <div className="flex w-full flex-col items-start">
      <div className="w-full max-w-[72ch]">
        {/* Photo proof if agent message includes anexo_json */}
        {mensagem.anexo_json && (
          <ProvaDeFoto anexoJson={mensagem.anexo_json} />
        )}

        {/* Agent response text in Newsreader 17px / 1.65 line-height */}
        {mensagem.texto && <SimpleMarkdown content={mensagem.texto} />}

        {/* Stamped or pending Talão */}
        {hasTalao && (
          <Talao
            accaoJson={mensagem.accao_json || {}}
            estadoAccao={mensagem.estado_accao || "pendente"}
            resultadoId={mensagem.resultado_id}
            onConfirm={onConfirmAction}
          />
        )}

        {/* Copy button below agent response */}
        {mensagem.texto && (
          <div className="mt-1.5 flex items-center gap-2">
            <button
              type="button"
              aria-label={t.copy}
              onClick={handleCopy}
              className="flex items-center gap-1.5 rounded-item px-2 py-1 text-xs text-text-secondary hover:bg-sidebar-hover hover:text-text transition-ui"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              {copied && (
                <span className="font-medium text-text">{t.copied}</span>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
