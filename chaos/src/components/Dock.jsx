'use client';

import { motion, useMotionValue, useSpring, useTransform, AnimatePresence } from 'motion/react';
import { Children, cloneElement, useEffect, useMemo, useRef, useState, isValidElement } from 'react';

import './Dock.css';

function DockItem({
  children,
  className = '',
  onClick,
  mouseX,
  mouseY,
  spring,
  distance,
  magnification,
  baseItemSize,
  label,
  description,
  direction = 'horizontal',
  showLabelOnRight = false
}) {
  const ref = useRef(null);
  const isHovered = useMotionValue(0);
  const isVertical = direction === 'vertical';

  const mouseDistance = useTransform(isVertical ? mouseY : mouseX, val => {
    const rect = ref.current?.getBoundingClientRect() ?? {
      x: 0,
      y: 0,
      width: baseItemSize,
      height: baseItemSize
    };
    return isVertical
      ? val - rect.y - baseItemSize / 2
      : val - rect.x - baseItemSize / 2;
  });

  const targetSize = useTransform(mouseDistance, [-distance, 0, distance], [baseItemSize, magnification, baseItemSize]);
  const size = useSpring(targetSize, spring);

  const handleKeyDown = e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick?.();
    }
  };

  return (
    <motion.div
      ref={ref}
      style={showLabelOnRight ? { height: size, width: '100%' } : { width: size, height: size }}
      onHoverStart={() => isHovered.set(1)}
      onHoverEnd={() => isHovered.set(0)}
      onFocus={() => isHovered.set(1)}
      onBlur={() => isHovered.set(0)}
      onClick={onClick}
      className={`dock-item ${isVertical ? 'dock-item-vertical' : ''} ${showLabelOnRight ? 'dock-item-row' : ''} ${className}`}
      tabIndex={0}
      role="button"
      aria-haspopup="true"
      aria-label={label}
      onKeyDown={handleKeyDown}
    >
      {Children.map(children, child =>
        isValidElement(child) ? cloneElement(child, { isHovered, direction, showLabelOnRight, label, description }) : child
      )}
      {showLabelOnRight && (
        <span className="dock-row-title">{label}</span>
      )}
    </motion.div>
  );
}

function DockLabel({ children, className = '', ...rest }) {
  const { isHovered, direction, description } = rest;
  const isVertical = direction === 'vertical';
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (!isHovered) return;
    const unsubscribe = isHovered.on('change', latest => {
      setIsVisible(latest === 1);
    });
    return () => unsubscribe();
  }, [isHovered]);

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={isVertical ? { opacity: 0, x: -8, y: '-50%' } : { opacity: 0, y: 0, x: '-50%' }}
          animate={isVertical ? { opacity: 1, x: 0, y: '-50%' } : { opacity: 1, y: -10, x: '-50%' }}
          exit={isVertical ? { opacity: 0, x: -6, y: '-50%' } : { opacity: 0, y: 0, x: '-50%' }}
          transition={{ duration: 0.16 }}
          className={`dock-label ${isVertical ? 'dock-label-vertical' : ''} ${className}`}
          role="tooltip"
        >
          <div style={{ fontWeight: '700', color: '#fff', fontSize: '11px', marginBottom: description ? '2px' : '0' }}>
            {children}
          </div>
          {description && (
            <div style={{ fontSize: '10px', color: '#94a3b8', fontWeight: '400', maxWidth: '210px', lineHeight: '1.4' }}>
              {description}
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function DockIcon({ children, className = '' }) {
  return <div className={`dock-icon ${className}`}>{children}</div>;
}

export default function Dock({
  items,
  className = '',
  spring = { mass: 0.1, stiffness: 150, damping: 12 },
  magnification = 70,
  distance = 200,
  panelHeight = 68,
  dockHeight = 256,
  baseItemSize = 50,
  direction = 'horizontal',
  showLabelOnRight = false
}) {
  const mouseX = useMotionValue(Infinity);
  const mouseY = useMotionValue(Infinity);
  const isHovered = useMotionValue(0);
  const isVertical = direction === 'vertical';

  const maxHeight = useMemo(
    () => Math.max(dockHeight, magnification + magnification / 2 + 4),
    [magnification, dockHeight]
  );
  const heightRow = useTransform(isHovered, [0, 1], [panelHeight, maxHeight]);
  const height = useSpring(heightRow, spring);

  return (
    <motion.div
      style={isVertical ? { scrollbarWidth: 'none', width: '100%' } : { height, scrollbarWidth: 'none' }}
      className={`dock-outer ${isVertical ? 'dock-outer-vertical' : ''}`}
    >
      <motion.div
        onMouseMove={e => {
          isHovered.set(1);
          mouseX.set(e.clientX ?? e.pageX);
          mouseY.set(e.clientY ?? e.pageY);
        }}
        onMouseLeave={() => {
          isHovered.set(0);
          mouseX.set(Infinity);
          mouseY.set(Infinity);
        }}
        className={`dock-panel ${isVertical ? 'dock-panel-vertical' : ''} ${showLabelOnRight ? 'dock-panel-row' : ''} ${className}`}
        style={isVertical ? undefined : { height: panelHeight }}
        role="toolbar"
        aria-label="Application dock"
      >
        {items.map((item, index) => (
          <DockItem
            key={index}
            onClick={item.onClick}
            className={item.className}
            mouseX={mouseX}
            mouseY={mouseY}
            spring={spring}
            distance={distance}
            magnification={magnification}
            baseItemSize={baseItemSize}
            label={item.label}
            description={item.description}
            direction={direction}
            showLabelOnRight={showLabelOnRight}
          >
            <DockIcon>{item.icon}</DockIcon>
            <DockLabel>{item.label}</DockLabel>
          </DockItem>
        ))}
      </motion.div>
    </motion.div>
  );
}
