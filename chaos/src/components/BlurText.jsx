import React, { useEffect, useRef, useState, useMemo } from 'react';
import { motion } from 'motion/react';

const buildKeyframes = (from, steps) => {
  const keys = new Set([...Object.keys(from), ...steps.flatMap(s => Object.keys(s))]);
  const keyframes = {};
  keys.forEach(k => {
    keyframes[k] = [from[k], ...steps.map(s => s[k])];
  });
  return keyframes;
};

export default function BlurText({
  text = '',
  children,
  delay = 20,
  className = '',
  style = {},
  as = 'h1',
  animateBy = 'letters',
  direction = 'top',
  threshold = 0.05,
  rootMargin = '40px',
  animationFrom,
  animationTo,
  easing = t => t,
  onAnimationComplete,
  stepDuration = 0.22,
  repeatOnView = false
}) {
  const content = text || (typeof children === 'string' ? children : '');
  const strText = String(content ?? '');
  const [inView, setInView] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          if (!repeatOnView) {
            observer.unobserve(ref.current);
          }
        } else if (repeatOnView) {
          setInView(false);
        }
      },
      { threshold, rootMargin }
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [threshold, rootMargin, repeatOnView]);

  const defaultFrom = useMemo(
    () =>
      direction === 'top'
        ? { filter: 'blur(10px)', opacity: 0, y: -18 }
        : { filter: 'blur(10px)', opacity: 0, y: 18 },
    [direction]
  );

  const defaultTo = useMemo(
    () => [
      {
        filter: 'blur(3px)',
        opacity: 0.7,
        y: direction === 'top' ? 2 : -2
      },
      { filter: 'blur(0px)', opacity: 1, y: 0 }
    ],
    [direction]
  );

  const fromSnapshot = animationFrom ?? defaultFrom;
  const toSnapshots = animationTo ?? defaultTo;

  const stepCount = toSnapshots.length + 1;
  const totalDuration = stepDuration * (stepCount - 1);
  const times = Array.from({ length: stepCount }, (_, i) => (stepCount === 1 ? 0 : i / (stepCount - 1)));
  const animateKeyframes = buildKeyframes(fromSnapshot, toSnapshots);

  const Component = as;
  const words = useMemo(() => strText.split(' '), [strText]);

  let globalCharIdx = 0;

  return (
    <Component
      ref={ref}
      className={`blur-text-anim ${className}`}
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'baseline',
        rowGap: '2px',
        columnGap: '0px',
        ...(style?.textAlign === 'center' ? { justifyContent: 'center' } : {}),
        ...style
      }}
    >
      {animateBy === 'words' ? (
        words.map((word, wordIdx) => {
          const spanTransition = {
            duration: totalDuration,
            times,
            delay: (wordIdx * delay) / 1000,
            ease: easing
          };
          return (
            <React.Fragment key={wordIdx}>
              <motion.span
                className="inline-block"
                initial={fromSnapshot}
                animate={inView ? animateKeyframes : fromSnapshot}
                transition={spanTransition}
                style={{ display: 'inline-block' }}
              >
                {word}
              </motion.span>
              {wordIdx < words.length - 1 && (
                <span style={{ display: 'inline-block' }}>&nbsp;</span>
              )}
            </React.Fragment>
          );
        })
      ) : (
        words.map((word, wordIdx) => {
          return (
            <React.Fragment key={wordIdx}>
              <span style={{ display: 'inline-block', whiteSpace: 'nowrap' }}>
                {word.split('').map((char, charIdx) => {
                  const currentIdx = globalCharIdx++;
                  const spanTransition = {
                    duration: totalDuration,
                    times,
                    delay: (currentIdx * delay) / 1000,
                    ease: easing
                  };
                  return (
                    <motion.span
                      className="inline-block"
                      key={charIdx}
                      initial={fromSnapshot}
                      animate={inView ? animateKeyframes : fromSnapshot}
                      transition={spanTransition}
                      onAnimationComplete={
                        wordIdx === words.length - 1 && charIdx === word.length - 1
                          ? onAnimationComplete
                          : undefined
                      }
                      style={{ display: 'inline-block' }}
                    >
                      {char}
                    </motion.span>
                  );
                })}
              </span>
              {wordIdx < words.length - 1 && (
                <span style={{ display: 'inline-block' }}>&nbsp;</span>
              )}
            </React.Fragment>
          );
        })
      )}
    </Component>
  );
}
