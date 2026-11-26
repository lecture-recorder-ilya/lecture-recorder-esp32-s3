"use strict";

(() => {
  const scenes = [...document.querySelectorAll("[data-scene]")];
  if (!scenes.length || !("IntersectionObserver" in window)) return;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const shown = new Set();
  const canvas = document.querySelector("#sound-ribbon");
  const context = canvas?.getContext("2d");
  const source = document.querySelector(".source-panel");
  let measureFrame = 0, ribbonFrame = 0, lastTick = 0;
  let visible = false, phase = 0, blend = 0, width = 0, height = 0, lineColor;

  function position() {
    measureFrame = 0;
    if (document.hidden) return;
    for (const scene of shown) {
      const box = scene.getBoundingClientRect();
      const distance = reduced.matches ? 0 : Math.min(1, Math.max(-1, (innerHeight - 2 * box.top - box.height) / (innerHeight + box.height)));
      scene.style.setProperty("--scene-shift", (distance * 45).toFixed(2) + "px");
      scene.style.setProperty("--heading-shift", (distance * -11).toFixed(2) + "px");
      scene.style.setProperty("--scene-scale", (1.10 + distance * .055).toFixed(3));
    }
  }
  function measure() {
    if (shown.size && !measureFrame && !document.hidden) measureFrame = requestAnimationFrame(position);
  }
  const sections = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) shown.add(entry.target); else shown.delete(entry.target);
    }
    measure();
  });
  const reveal = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      reveal.unobserve(entry.target);
      if (!reduced.matches) entry.target.animate([
        {opacity: .65, transform: "translateY(18px)"},
        {opacity: 1, transform: "translateY(0)"}
      ], {duration: 530, easing: "cubic-bezier(.18,.75,.18,1)"});
    }
  }, {threshold: .12});
  for (const scene of scenes) sections.observe(scene);
  for (const item of document.querySelectorAll(".section-copy,.source-panel,.reading-paper,.personal-inner,.platforms li")) reveal.observe(item);

  function resize() {
    if (!context) return;
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    const ratio = Math.min(1.5, devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(width * ratio));
    canvas.height = Math.max(1, Math.round(height * ratio));
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    lineColor = context.createLinearGradient(0, height, width, 0);
    lineColor.addColorStop(0, "#8d8277"); lineColor.addColorStop(.30, "#c6b4a3");
    lineColor.addColorStop(.62, "#f0e9d8"); lineColor.addColorStop(.81, "#ffac91"); lineColor.addColorStop(1, "#b8a79d");
    requestRibbon();
  }
  function drawRibbon(now) {
    ribbonFrame = 0;
    if (!visible || document.hidden || !context || !width) { lastTick = 0; return; }
    if (lastTick && now - lastTick < 1000 / 25 && !reduced.matches) { requestRibbon(); return; }
    const delta = lastTick ? Math.min(.12, (now - lastTick) / 1000) : 0;
    lastTick = now;
    const target = source.dataset.mode === "device" ? 1 : source.dataset.mode === "file" ? 2 : 0;
    blend = reduced.matches ? target : blend + (target - blend) * (1 - Math.exp(-delta * 6));
    phase = reduced.matches ? 0 : (phase + delta * .57) % (Math.PI * 2);
    context.clearRect(0, 0, width, height);
    context.strokeStyle = lineColor;
    const count = width < 430 ? 27 : 42;
    const samples = Math.ceil(width / 8);
    for (let row = 0; row < count; row++) {
      const z = row / (count - 1);
      context.globalAlpha = .17 + .55 * Math.sin(Math.PI * z) ** 1.2;
      context.lineWidth = .66 + .38 * z;
      context.beginPath();
      for (let column = 0; column <= samples; column++) {
        const u = column / samples;
        const arch = .34 + .66 * Math.sin(Math.PI * u);
        const wave = Math.sin(u * (7.1 + blend * .65) + z * 2.2 - phase);
        const fold = Math.sin(u * 11.3 - z * 2.6 + phase * 2) * .30;
        const y = height * (.54 + .19 * arch * (wave + fold) + (z - .5) * (.23 + .13 * Math.cos(u * 7 - phase)));
        if (!column) context.moveTo(0, y); else context.lineTo(u * width, y);
      }
      context.stroke();
    }
    context.globalAlpha = 1;
    if (!reduced.matches) requestRibbon();
  }
  function requestRibbon() {
    if (visible && !document.hidden && !ribbonFrame) ribbonFrame = requestAnimationFrame(drawRibbon);
  }
  function sync() {
    cancelAnimationFrame(ribbonFrame);
    ribbonFrame = 0; lastTick = 0;
    measure(); requestRibbon();
  }
  if (canvas && context) {
    new ResizeObserver(resize).observe(canvas);
    new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      source.classList.toggle("in-view", visible);
      sync();
    }).observe(canvas);
    new MutationObserver(requestRibbon).observe(source, {attributes: true, attributeFilter: ["data-mode"]});
  }
  window.addEventListener("scroll", measure, {passive: true});
  window.addEventListener("resize", measure, {passive: true});
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", sync);
})();
