import React, { useEffect, useRef, useState, useMemo } from 'react';

/**
 * AutoBlurText: Recursively transforms text nodes into staggered blurred letters.
 * Optimized for butter-smooth 60-120fps rendering:
 * - Memoizes the transformed tree (zero garbage collection during scroll)
 * - Keeps DOM nodes mounted and toggles CSS animation classes
 * - Hardware-accelerated GPU translate3d with no permanent will-change memory leak
 *
 * Strictly ignores:
 * - IDE code editor (.ide-code-block)
 * - IDE terminal (.ide-terminal-container)
 * - SVG elements (<svg>, <text>, <circle>, etc.)
 * - Form controls (<input>, <textarea>, <select>, <option>)
 */
export default function AutoBlurText({ children, resetKey, className = '', style = {} }) {
  const containerRef = useRef(null);
  const [inView, setInView] = useState(() => {
    if (typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      return true;
    }
    return false;
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      setInView(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
        } else {
          setInView(false);
        }
      },
      { threshold: 0.02, rootMargin: '60px' }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [resetKey]);

  function process(node, keyPrefix = 'b') {
    if (node === null || node === undefined || typeof node === 'boolean') {
      return node;
    }

    // Convert strings and numbers to letter-by-letter blurred spans
    if (typeof node === 'string' || typeof node === 'number') {
      const text = String(node);
      if (!text.trim()) {
        return node;
      }

      const chars = text.split('');
      return (
        <span key={keyPrefix} className="blur-text-flow" style={{ display: 'inline' }}>
          {chars.map((char, i) => {
            if (char === ' ') {
              return (
                <span key={`${keyPrefix}-c-${i}`} className="blur-space">
                  {' '}
                </span>
              );
            }
            // Snappy, silky 14ms stagger, capped at 480ms
            const delay = Math.min(i * 14, 480);
            return (
              <span
                key={`${keyPrefix}-c-${i}`}
                className="blur-char"
                style={{
                  animationDelay: `${delay}ms`
                }}
              >
                {char}
              </span>
            );
          })}
        </span>
      );
    }

    // Array of nodes
    if (Array.isArray(node)) {
      return node.map((child, idx) => process(child, `${keyPrefix}-${idx}`));
    }

    // React elements
    if (React.isValidElement(node)) {
      const { type, props } = node;

      // Skip SVGs and form controls where HTML spans are invalid
      if (
        type === 'svg' ||
        type === 'path' ||
        type === 'circle' ||
        type === 'text' ||
        type === 'line' ||
        type === 'select' ||
        type === 'option' ||
        type === 'input' ||
        type === 'textarea'
      ) {
        return node;
      }

      // Skip already processed nodes
      if (
        props?.className &&
        typeof props.className === 'string' &&
        (props.className.includes('blur-text-flow') ||
          props.className.includes('blur-char'))
      ) {
        return node;
      }

      // Skip IDE code block and terminal container
      if (
        props?.className &&
        typeof props.className === 'string' &&
        (props.className.includes('ide-code-block') ||
          props.className.includes('ide-terminal-container') ||
          props.className.includes('no-blur-anim'))
      ) {
        return node;
      }

      // Process children recursively
      if (props && props.children) {
        return React.cloneElement(node, {
          ...props,
          children: React.Children.map(props.children, (child, idx) =>
            process(child, `${keyPrefix}-${idx}`)
          )
        });
      }
    }

    return node;
  }

  // Memoize the transformed tree once - prevents re-traversing during scrolling
  const processedChildren = useMemo(() => {
    return process(children);
  }, [children]);

  return (
    <div
      ref={containerRef}
      key={resetKey}
      className={`auto-blur-wrapper ${inView ? 'in-view' : 'out-of-view'} ${className}`}
      style={{ width: '100%', ...style }}
    >
      {processedChildren}
    </div>
  );
}
