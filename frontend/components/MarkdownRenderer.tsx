// components/MarkdownRenderer.tsx
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownRendererProps {
  markdown: string;
}

/**
 * A component to render Markdown text as formatted HTML.
 * @param {MarkdownRendererProps} props - The component props.
 * @param {string} props.markdown - The raw Markdown string to render.
 */
const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ markdown }) => {
  return (
    //<div className="markdown-content" dangerouslySetInnerHTML={{ __html: markdown }} />
    // Use dangerouslySetInnerHTML to inject the generated HTML string into the DOM.
    // remarkGfm plugin enables support for tables, strikethrough, etc.
    <div className="prose prose-sm md:prose-base">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;
