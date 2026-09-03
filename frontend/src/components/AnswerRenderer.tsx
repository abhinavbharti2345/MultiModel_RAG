import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface Props {
  answer: string;
  onCitationClick?: () => void;
}

export function AnswerRenderer({ answer, onCitationClick }: Props) {
  // Pre-process the answer to convert citations into markdown links.
  const processedAnswer = useMemo(() => {
    return answer.replace(
      /\(?\s*(?:Source:[^,]+,\s*.*?|)Evidence ID:\s*([a-fA-F0-9-]+)\s*\)?/gi,
      (match, id) => {
        return `[Citation](#evidence-${id.toLowerCase()})`;
      }
    );
  }, [answer]);

  const scrollToEvidence = (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    if (onCitationClick) {
      onCitationClick();
    }
    setTimeout(() => {
      const el = document.getElementById(`evidence-${id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('border-indigo-500', 'bg-indigo-950/20');
        setTimeout(() => {
          el.classList.remove('border-indigo-500', 'bg-indigo-950/20');
        }, 1500);
      } else {
        console.warn(`Evidence card ${id} not found in DOM`);
      }
    }, 100);
  };

  return (
    <div className="prose-answer text-xs text-zinc-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            return !inline && match ? (
              <SyntaxHighlighter
                style={vscDarkPlus}
                language={match[1]}
                PreTag="div"
                className="rounded-md !my-4 !text-[11px] border border-zinc-700/50"
                {...props}
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            ) : (
              <code className="bg-zinc-800 text-zinc-300 border border-zinc-700 px-1 py-0.5 rounded text-[11px]" {...props}>
                {children}
              </code>
            );
          },
          a({ node, href, children, ...props }) {
            if (href?.startsWith('#evidence-')) {
              const evidenceId = href.replace('#evidence-', '');
              return (
                <button
                  onClick={(e) => scrollToEvidence(evidenceId, e)}
                  className="inline-flex items-center justify-center px-1.5 py-0.5 mx-1 text-[9px] font-bold text-white bg-indigo-600 hover:bg-indigo-500 rounded cursor-pointer transition-colors translate-y-[-2px]"
                  title="Click to view evidence"
                >
                  {children === 'Citation' ? '📑 Source' : children}
                </button>
              );
            }
            return <a href={href} className="text-indigo-400 hover:text-indigo-300 hover:underline" {...props}>{children}</a>;
          },
          table({ node, ...props }) {
            return (
              <div className="overflow-x-auto my-3">
                <table className="min-w-full divide-y divide-zinc-700 border border-zinc-800 rounded overflow-hidden" {...props} />
              </div>
            );
          },
          th({ node, ...props }) {
            return <th className="bg-zinc-900 px-3 py-2 text-left text-xs font-semibold text-zinc-300" {...props} />;
          },
          td({ node, ...props }) {
            return <td className="whitespace-nowrap px-3 py-2 text-[11px] text-zinc-400 border-t border-zinc-800" {...props} />;
          }
        }}
      >
        {processedAnswer}
      </ReactMarkdown>
    </div>
  );
}
