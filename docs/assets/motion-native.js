(() => {
  'use strict';
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      observer.unobserve(entry.target);
      entry.target.animate?.([{ opacity: .65, transform: 'translateY(12px)' }, { opacity: 1, transform: 'translateY(0)' }],
        { duration: 350, easing: 'cubic-bezier(.2,.6,.3,1)' });
    });
  }, { threshold: .08 });
  document.querySelectorAll('.practice-card,.price-card,.quick-service,.about-intro').forEach(element => observer.observe(element));
})();
