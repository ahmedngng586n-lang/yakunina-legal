'use strict';
document.addEventListener('DOMContentLoaded',()=>{
  if(!window.gsap)return;
  if(window.ScrollTrigger)gsap.registerPlugin(ScrollTrigger);
  const mm=gsap.matchMedia();
  mm.add('(prefers-reduced-motion: no-preference)',()=>{
    const tl=gsap.timeline({defaults:{ease:'power3.out'}});
    tl.from('.hero-line>*',{yPercent:110,rotation:2,duration:1.05,stagger:.14,clearProps:'transform'},.12)
      .from('.hero-copy>.eyebrow',{opacity:0,y:16,duration:.6},0)
      .from('.hero-description,.hero-actions,.hero-note',{opacity:0,y:24,duration:.7,stagger:.12},.58)
      .from('.hero-visual',{clipPath:'inset(12% 8% 12% 8%)',opacity:0,duration:1.25,clearProps:'clipPath,opacity'},.2)
      .from('.hero-visual>img',{scale:1.14,duration:1.8,clearProps:'transform'},.2)
      .from('.experience-badge',{y:38,opacity:0,rotation:-5,duration:.85,clearProps:'transform,opacity'},.85);
    const groups=document.querySelectorAll('.section-heading,.practice-grid,.price-grid,.steps,.about-intro,.about-details,.faq-list,.contact-copy,.contact-card');
    const revealed=new Set();
    const observer=new IntersectionObserver(entries=>{
      for(const entry of entries){if(!entry.isIntersecting)continue;observer.unobserve(entry.target);
        const items=entry.target.matches('.practice-grid,.price-grid,.steps')?[...entry.target.children]:[entry.target];
        items.forEach(item=>revealed.add(item));
        gsap.from(items,{y:42,opacity:0,duration:.85,stagger:.12,ease:'power3.out',clearProps:'transform,opacity'});
      }
    },{threshold:.12});groups.forEach(el=>observer.observe(el));
    if(window.ScrollTrigger&&matchMedia('(min-width: 900px)').matches){gsap.to('.hero-visual',{yPercent:4,ease:'none',scrollTrigger:{trigger:'.hero',start:'top top',end:'bottom top',scrub:1}});}
    const onChange=()=>window.ScrollTrigger?.refresh(); document.querySelectorAll('details').forEach(el=>el.addEventListener('toggle',onChange));
    return()=>{observer.disconnect();const items=[...revealed];gsap.killTweensOf(items);gsap.set(items,{clearProps:'transform,opacity'});document.querySelectorAll('details').forEach(el=>el.removeEventListener('toggle',onChange));};
  });
});
