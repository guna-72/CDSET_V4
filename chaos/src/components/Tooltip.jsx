import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import './Tooltip.css';

export default function Tooltip({ children, title = '', text = '', position = 'top', delay = 120, style = {}, className = '' }) {
  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0, transform: 'translate(-50%, -100%)' });
  const tooltipRef = useRef(null);
  const wrapperRef = useRef(null);
  const timeoutRef = useRef(null);

  const updatePosition = () => {
    const el = wrapperRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const gap = 12;
    const margin = 10;
    // Measure the actual rendered tooltip when available. The previous
    // implementation estimated width from the viewport, which made
    // right-edge tooltips appear half outside the browser window.
    const tip = tooltipRef.current;
    const width = tip?.getBoundingClientRect().width || Math.min(320, Math.max(180, window.innerWidth * 0.28));
    const height = tip?.getBoundingClientRect().height || 90;
    let top = r.top + r.height / 2;
    let left = r.left + r.width / 2;
    let transform = 'translate(-50%, -50%)';
    if (position === 'right') { left = r.right + gap; transform = 'translateY(-50%)'; }
    else if (position === 'left') { left = r.left - gap; transform = 'translate(-100%, -50%)'; }
    else if (position === 'bottom') { top = r.bottom + gap; transform = 'translateX(-50%)'; }
    else { top = r.top - gap; transform = 'translate(-50%, -100%)'; }

    if (position === 'right' && left + width > window.innerWidth - margin) { left = r.left - gap; transform = 'translate(-100%, -50%)'; }
    if (position === 'left' && left - width < margin) { left = r.right + gap; transform = 'translateY(-50%)'; }
    if (position === 'top' && top - height < margin) { top = r.bottom + gap; transform = 'translateX(-50%)'; }
    if (position === 'bottom' && top + height > window.innerHeight - margin) { top = r.top - gap; transform = 'translate(-50%, -100%)'; }

    if (transform.includes('translateX(-50%)') || transform.includes('translate(-50%')) {
      left = Math.max(margin + width / 2, Math.min(left, window.innerWidth - margin - width / 2));
    } else {
      left = Math.max(margin, Math.min(left, window.innerWidth - margin));
    }
    if (transform.includes('translateY(-50%)')) {
      top = Math.max(margin + height / 2, Math.min(top, window.innerHeight - margin - height / 2));
    } else if (transform.includes('translate(-100%')) {
      top = Math.max(margin + height / 2, Math.min(top, window.innerHeight - margin - height / 2));
    } else if (transform.includes('translate(-50%, -100%)')) {
      top = Math.max(margin + height, Math.min(top, window.innerHeight));
    } else {
      top = Math.max(margin, Math.min(top, window.innerHeight - margin));
    }
    setCoords({ top, left, transform });
  };

  const show = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => { updatePosition(); setIsOpen(true); }, delay);
  };
  const hide = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setIsOpen(false);
  };

  useEffect(() => {
    if (!isOpen) return;
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => { window.removeEventListener('resize', updatePosition); window.removeEventListener('scroll', updatePosition, true); };
  }, [isOpen, position]);

  useEffect(() => () => timeoutRef.current && clearTimeout(timeoutRef.current), []);

  return <div ref={wrapperRef} className={`tooltip-wrapper ${className}`} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} style={{ position: 'relative', display: 'inline-flex', ...style }}>
    {children}
    <AnimatePresence>
      {isOpen && (title || text) && typeof document !== 'undefined' && createPortal(
        <motion.div ref={tooltipRef}
          initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          transition={{ duration: 0.14, ease: 'easeOut' }} className="custom-tooltip custom-tooltip--fixed" role="tooltip"
          style={{ top: coords.top, left: coords.left, transform: coords.transform }}>
          {title && <div className="tooltip-title">{title}</div>}
          {text && <div className="tooltip-text">{text}</div>}
        </motion.div>,
        document.body
      )}
    </AnimatePresence>
  </div>;
}
