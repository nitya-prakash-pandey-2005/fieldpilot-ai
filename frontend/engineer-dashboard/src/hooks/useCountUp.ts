import { useState, useEffect } from 'react';

export const useCountUp = (target: number, duration = 1500) => {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let start = Date.now();
    const timer = setInterval(() => {
      const elapsed = Date.now() - start;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutExpo
      const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      setCount(Math.floor(eased * target));
      if (progress === 1) clearInterval(timer);
    }, 16);

    return () => clearInterval(timer);
  }, [target, duration]);

  return count;
};
