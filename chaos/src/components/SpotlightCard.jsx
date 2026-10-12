import React, { useRef, useImperativeHandle, forwardRef } from 'react';
import './SpotlightCard.css';

const SpotlightCard = forwardRef(({ 
  children, 
  className = '', 
  spotlightColor = 'rgba(99, 102, 241, 0.25)',
  style = {},
  ...props
}, ref) => {
  const divRef = useRef(null);
  useImperativeHandle(ref, () => divRef.current);

  const handleMouseMove = e => {
    if (!divRef.current) return;
    const rect = divRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    divRef.current.style.setProperty('--mouse-x', `${x}px`);
    divRef.current.style.setProperty('--mouse-y', `${y}px`);
    divRef.current.style.setProperty('--spotlight-color', spotlightColor);
  };

  return (
    <div 
      ref={divRef} 
      onMouseMove={handleMouseMove} 
      className={`card-spotlight ${className}`}
      style={style}
      {...props}
    >
      {children}
    </div>
  );
});

export default SpotlightCard;
