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
  // The LLM might output things like (Evidence ID: 1234-5678) or Source: xyz, Evidence ID: 1234
  const processedAnswer = useMemo(() => {
    // Regex matches "Evidence ID: <uuid>" or just "(Evidence ID: <uuid>)"
    // and captures the UUID.
    return answer.replace(
      /\(?\s*(?:Source:[^,]+,\s*.*?|)Evidence ID:\s*([a-fA-F0-9-]+)\s*\)?/gi,
      (match, id) => {
        return `[Citation](#evidence-${id.toLowerCase()})`;
      }
    );
  }, [answer]);

  // A helper function to scroll to the evidence card and flash it
  const scrollToEvidence = (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    if (onCitationClick) {
      onCitationClick();
    }
    // Need a slight delay to allow React to render the evidence tab if it was hidden
    setTimeout(() => {
      const el = document.getElementById(`evidence-${id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-4', 'ring-brand-400', 'ring-opacity-50', 'transition-all', 'duration-500');
        setTimeout(() => {
          el.classList.remove('ring-4', 'ring-brand-400', 'ring-opacity-50');
        }, 1500);
      } else {
        console.warn(`Evidence card ${id} not found in DOM`);
      }
    }, 100);
  };

  return (
    <div className="prose prose-sm prose-slate max-w-none">
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
                className="rounded-md !my-4 !text-[13px]"
                {...props}
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            ) : (
              <code className="bg-slate-100 text-brand-700 px-1 py-0.5 rounded text-[13px]" {...props}>
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
                  className="inline-flex items-center justify-center px-1.5 py-0.5 ml-1 text-[10px] font-bold text-white bg-brand-500 hover:bg-brand-600 rounded cursor-pointer no-underline align-baseline shadow-sm transition-colors"
                  title="Click to view evidence"
                >
                  {children === 'Citation' ? '📑' : children}
                </button>
              );
            }
            return <a href={href} className="text-brand-600 hover:underline" {...props}>{children}</a>;
          },
          table({ node, ...props }) {
            return (
              <div className="overflow-x-auto my-4">
                <table className="min-w-full divide-y divide-slate-300 border border-slate-200 rounded-lg overflow-hidden" {...props} />
              </div>
            );
          },
          th({ node, ...props }) {
            return <th className="bg-slate-50 px-3 py-2 text-left text-xs font-semibold text-slate-900" {...props} />;
          },
          td({ node, ...props }) {
            return <td className="whitespace-nowrap px-3 py-2 text-sm text-slate-500 border-t border-slate-200" {...props} />;
          }
        }}
      >
        {processedAnswer}
      </ReactMarkdown>
    </div>
  );
}
