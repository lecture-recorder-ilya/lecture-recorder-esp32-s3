"use strict";

(() => {
  const canvas = document.querySelector("#device-model");
  if (!canvas) return;
  const context = canvas.getContext("2d", { alpha: true });
  if (!context) return;

  const width = 53.5, height = 85, thickness = 4, radius = 3.2;
  const backZ = -thickness / 2, frontZ = thickness / 2;
  const bevel = .30, closureZ = backZ + .8;
  const controlY = height / 2 - 9;
  const camera = height * 2.95;
  const turn = Math.PI * 2;
  const homeAngle = -.48;
  const stage = canvas.closest(".model-stage");
  const sequence = canvas.closest(".model-sequence");
  const pin = canvas.closest(".model-pin");
  const angleLabel = document.querySelector("#model-angle");
  const motion = document.querySelector("#model-motion");
  const views = [...document.querySelectorAll("[data-model-view]")];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let centerY = 0;
  let yaw = homeAngle, destination = null, rotating = !reduced.matches;
  let motionRequested = true, inView = false, dragging = null, frame = 0, lastFrame = 0;
  let progress = null, scrollTarget = null, scrollOffset = 0, measureFrame = 0;
  let beforeSequence = true, holdingView = false, holdScrollY = 0, pageScrolled = false;
  let targetZoom = 0, zoom = 0;
  let viewWidth = 0, viewHeight = 0, scale = 0, density = 1;
  let sinYaw, cosYaw, sinTilt, cosTilt;
  const roll = -.15, sinRoll = Math.sin(roll), cosRoll = Math.cos(roll);

  function texture(w, h, paint) {
    const image = document.createElement("canvas");
    image.width = w; image.height = h;
    paint(image.getContext("2d"), w, h);
    return image;
  }

  function roundedPath(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function rounded(ctx, x, y, w, h, r, fill) {
    roundedPath(ctx, x, y, w, h, r);
    ctx.fillStyle = fill;
    ctx.fill();
  }

  const graphite = texture(448, 712, (ctx, w, h) => {
    const finish = ctx.createLinearGradient(w * .03, 0, w * .86, h);
    finish.addColorStop(0, "#36383a");
    finish.addColorStop(.32, "#2c2e30");
    finish.addColorStop(.74, "#232527");
    finish.addColorStop(1, "#1c1e20");
    ctx.fillStyle = finish; ctx.fillRect(0, 0, w, h);
    let seed = 287;
    const pixels = ctx.getImageData(0, 0, w, h);
    for (let i = 0; i < pixels.data.length; i += 4) {
      seed = (1664525 * seed + 1013904223) >>> 0;
      const grain = (seed / 4294967296 - .5) * 5;
      for (let channel = 0; channel < 3; channel++) pixels.data[i + channel] += grain;
    }
    ctx.putImageData(pixels, 0, 0);
  });

  const glass = texture(352, 172, (ctx, w, h) => {
    const surface = ctx.createLinearGradient(0, 0, w * .8, h);
    surface.addColorStop(0, "#282d31"); surface.addColorStop(.32, "#15191b"); surface.addColorStop(1, "#0b0e10");
    ctx.fillStyle = surface; ctx.fillRect(0, 0, w, h);
    rounded(ctx, 26, 26, 300, 120, 20, "#0d1113");
    ctx.fillStyle = "#cbebed"; ctx.font = '500 71px "SFMono-Regular", Menlo, monospace';
    ctx.fillText("00:00", 38, 109);
    ctx.strokeStyle = "#a1bdc2"; ctx.lineWidth = 2.5;
    ctx.strokeRect(273, 47, 32, 14); ctx.fillStyle = "#a1bdc2";
    ctx.fillRect(307, 51, 3, 6); ctx.fillRect(277, 51, 23, 6);
    for (const [i, length] of [5, 10, 17, 25, 18, 10, 6].entries()) {
      rounded(ctx, 272 + i * 5, 102 - length / 2, 2.7, length, 1.35, "#9ab6bb");
    }
  });

  const keyTexture = texture(96, 96, (ctx, w, h) => {
    const finish = ctx.createLinearGradient(0, 0, w, h);
    finish.addColorStop(0, "#292c2f"); finish.addColorStop(.45, "#1d2022"); finish.addColorStop(1, "#151719");
    ctx.fillStyle = finish; ctx.fillRect(0, 0, w, h);
  });

  const shadow = texture(256, 128, (ctx, w, h) => {
    ctx.translate(w / 2, h / 2); ctx.scale(w / 2, h / 2);
    const falloff = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    falloff.addColorStop(0, "rgba(0,3,6,.98)");
    falloff.addColorStop(.3, "rgba(0,3,6,.75)");
    falloff.addColorStop(.66, "rgba(0,3,6,.25)");
    falloff.addColorStop(1, "rgba(0,3,6,0)");
    ctx.fillStyle = falloff; ctx.fillRect(-1, -1, 2, 2);
  });

  function outline(w, h, r, z, x = 0, y = 0) {
    const points = [];
    const corners = [
      [w / 2 - r, h / 2 - r], [-w / 2 + r, h / 2 - r],
      [-w / 2 + r, -h / 2 + r], [w / 2 - r, -h / 2 + r]
    ];
    for (let corner = 0; corner < 4; corner++) {
      for (let step = 0; step <= 7; step++) {
        const angle = (corner + step / 7) * Math.PI / 2;
        points.push([x + corners[corner][0] + Math.cos(angle) * r,
                     y + corners[corner][1] + Math.sin(angle) * r, z]);
      }
    }
    return points;
  }

  function solid(w, h, r, x, y, layers, top, bottom) {
    const rings = layers.map(([z, inset]) =>
      outline(w - 2 * inset, h - 2 * inset, Math.min(r - inset, (w - 2 * inset) / 2, (h - 2 * inset) / 2), z, x, y));
    const sides = [];
    for (let j = 0; j < rings.length - 1; j++) {
      const ring = rings[j], next = rings[j + 1];
      const dz = layers[j + 1][0] - layers[j][0];
      const slope = (layers[j + 1][1] - layers[j][1]) / dz;
      for (let i = 0; i < ring.length; i++) {
        const k = (i + 1) % ring.length;
        const dx = ring[k][0] - ring[i][0], dy = ring[k][1] - ring[i][1];
        const length = Math.hypot(dx, dy);
        if (length < .0001) continue;
        const norm = Math.hypot(1, slope);
        sides.push({
          corners: [ring[i], ring[k], next[k], next[i]],
          normal: [dy / length / norm, -dx / length / norm, slope / norm],
          tone: layers[j][2]
        });
      }
    }
    function face(index, color, reverse) {
      const [z, inset] = layers[index];
      return { ring: rings[index], color, reverse, z, x, y, w: w - 2 * inset, h: h - 2 * inset };
    }
    return { sides, top: face(rings.length - 1, top, false), bottom: face(0, bottom, true) };
  }

  const body = solid(width, height, radius, 0, 0, [
    [backZ, bevel, 51], [backZ + bevel, 0, 37], [closureZ - .025, 0, 19],
    [closureZ + .025, 0, 42], [frontZ - bevel, 0, 69], [frontZ, bevel, 42]
  ], graphite, graphite);

  function plate(w, h, r, x, y, z, color) {
    return { ring: outline(w, h, r, z, x, y), color, reverse: false, z, x, y, w, h };
  }

  const displayRecess = plate(18, 9, 1.6, -9, controlY, frontZ, "#101315");
  const windowInsert = plate(17.6, 8.6, 1.4, -9, controlY, frontZ, glass);
  const keyOpening = plate(5, 5, 2.5, 14, controlY, frontZ, "#0e1011");
  const button = solid(4.4, 4.4, 2.2, 14, controlY, [
    [frontZ - .25, .04, 23], [frontZ - .11, 0, 27], [frontZ - .025, 0, 40], [frontZ, .025, 32]
  ], keyTexture, "#222426");
  const microphoneChannels = [-9, -6.5].map(x => {
    const z = backZ + 2.3;
    return Array.from({ length: 24 }, (_, i) => [
      x + .6 * Math.cos(i * turn / 24), height / 2, z + .6 * Math.sin(i * turn / 24)
    ]);
  });

  function rotate(x, y, z) {
    const dx = x * cosYaw + z * sinYaw, dz = -x * sinYaw + z * cosYaw;
    const dy = y * cosTilt - dz * sinTilt;
    return [dx * cosRoll - dy * sinRoll, dx * sinRoll + dy * cosRoll, y * sinTilt + dz * cosTilt];
  }

  function project(point) {
    const [x, y, z] = rotate(...point);
    const factor = scale * camera / (camera - z);
    return [viewWidth / 2 + x * factor, centerY - y * factor];
  }

  function path(points) {
    context.beginPath(); context.moveTo(...points[0]);
    for (let i = 1; i < points.length; i++) context.lineTo(...points[i]);
    context.closePath();
  }

  function material(normal, base) {
    const [x, y, z] = normal;
    const key = Math.max(0, -.59 * x + .65 * y + .48 * z);
    const reflection = Math.max(0, -.74 * x + .15 * y + .66 * z);
    const edge = Math.max(0, .84 * x + .39 * y + .37 * z);
    const light = base * (.55 + .60 * key) + 71 * reflection ** 14 + 83 * edge ** 14;
    return 'rgb(' + [light * .99, light, light * 1.05].map(Math.round).join(',') + ')';
  }

  function mapTexture(face) {
    const image = face.color;
    const columns = 5, rows = 7;
    const cw = image.width / columns, ch = image.height / rows;
    const sign = face.reverse ? -1 : 1;
    function at(i, j) {
      return project([face.x + (i / columns - .5) * face.w * sign,
                      face.y + (.5 - j / rows) * face.h, face.z]);
    }
    let line = Array.from({ length: columns + 1 }, (_, i) => at(i, 0));
    for (let j = 0; j < rows; j++) {
      const next = Array.from({ length: columns + 1 }, (_, i) => at(i, j + 1));
      for (let i = 0; i < columns; i++) {
        const a = line[i], b = line[i + 1], c = next[i];
        context.save();
        context.transform((b[0] - a[0]) / cw, (b[1] - a[1]) / cw, (c[0] - a[0]) / ch, (c[1] - a[1]) / ch, a[0], a[1]);
        const sourceWidth = Math.min(cw + 1.5, image.width - i * cw);
        const sourceHeight = Math.min(ch + 1.5, image.height - j * ch);
        context.drawImage(image, i * cw, j * ch, sourceWidth, sourceHeight, 0, 0, sourceWidth, sourceHeight);
        context.restore();
      }
      line = next;
    }
  }

  function drawFace(face) {
    const normal = rotate(0, 0, face.reverse ? -1 : 1);
    const center = rotate(face.x, face.y, face.z);
    if (normal[2] * (camera - center[2]) - normal[0] * center[0] - normal[1] * center[1] <= 0) return;
    path(face.ring.map(project));
    if (typeof face.color === "string") {
      context.fillStyle = face.color; context.fill();
      return;
    }
    context.save(); context.clip();
    context.fillStyle = "#292a2d"; context.fill();
    mapTexture(face);
    if (face.color === graphite) {
      const x = viewWidth / 2 - scale * width * (1.16 + normal[0] * 1.48);
      const softbox = context.createLinearGradient(x, viewHeight * .18, x + scale * width * 1.55, viewHeight * .64);
      softbox.addColorStop(0, "rgba(217,230,233,0)");
      softbox.addColorStop(.32, "rgba(210,230,242,.23)");
      softbox.addColorStop(.54, "rgba(210,230,242,.065)");
      softbox.addColorStop(1, "rgba(217,230,233,0)");
      context.fillStyle = softbox;
      context.fillRect(0, 0, viewWidth, viewHeight);
    } else if (face.color === glass) {
      const middle = project([face.x, face.y, face.z]);
      const spread = scale * face.w;
      const glint = context.createLinearGradient(middle[0] - spread * (.6 + sinYaw), middle[1] - spread * .4,
                                                 middle[0] + spread * (.6 - sinYaw), middle[1] + spread * .4);
      glint.addColorStop(0, "rgba(190,219,228,0)");
      glint.addColorStop(.42, "rgba(190,219,228,.04)");
      glint.addColorStop(.52, "rgba(215,234,241,.25)");
      glint.addColorStop(.64, "rgba(190,219,228,0)");
      context.fillStyle = glint; context.fillRect(0, 0, viewWidth, viewHeight);
    }
    context.restore();
  }

  function drawPart(part) {
    for (const side of part.sides) {
      const normal = rotate(...side.normal), pos = rotate(...side.corners[0]);
      if (normal[2] * (camera - pos[2]) - normal[0] * pos[0] - normal[1] * pos[1] <= 0) continue;
      path(side.corners.map(project));
      context.fillStyle = material(normal, side.tone);
      context.strokeStyle = context.fillStyle; context.lineWidth = .4;
      context.fill(); context.stroke();
    }
    drawFace(part.bottom); drawFace(part.top);
  }

  function drawMicrophones() {
    const normal = rotate(0, 1, 0);
    const center = rotate(0, height / 2, 0);
    if (normal[2] * (camera - center[2]) - normal[0] * center[0] - normal[1] * center[1] <= 0) return;
    for (const channel of microphoneChannels) {
      path(channel.map(project));
      context.fillStyle = "#080a0b"; context.fill();
    }
  }

  function drawShadow() {
    const base = project([0, -height / 2, 0]);
    const breadth = scale * width * (.35 + .7 * Math.abs(cosYaw));
    const ground = Math.min(viewHeight * .93, base[1] + viewHeight * .048);
    context.save();
    context.globalAlpha = .87 * (1 - zoom);
    context.translate(base[0] + sinYaw * scale * 4, ground);
    context.rotate(-.08 + sinYaw * .06);
    context.drawImage(shadow, -breadth * .84, -scale * 3.6, breadth * 2.1, scale * 7.2);
    context.drawImage(shadow, -breadth * .48, -scale * 1.9, breadth * 1.13, scale * 3.8);
    context.restore();
  }

  function draw() {
    const box = canvas.getBoundingClientRect();
    viewWidth = box.width; viewHeight = box.height;
    if (!viewWidth || !viewHeight) return;
    density = Math.min(window.devicePixelRatio || 1, 1.8);
    const pixelWidth = Math.round(viewWidth * density), pixelHeight = Math.round(viewHeight * density);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth; canvas.height = pixelHeight;
    }
    context.setTransform(density, 0, 0, density, 0, 0);
    context.clearRect(0, 0, viewWidth, viewHeight);
    const edge = Math.sin(yaw);
    const tilt = .18 + .07 * edge + .16 * zoom;
    scale = Math.min(viewHeight * .75 / height, viewWidth * .77 / (width + height * .13));
    scale *= (1 + .035 * Math.abs(edge)) * (1 + 1.18 * zoom);
    centerY = viewHeight * (.48 + .38 * zoom);
    sinYaw = edge; cosYaw = Math.cos(yaw);
    sinTilt = Math.sin(tilt); cosTilt = Math.cos(tilt);
    drawShadow();
    drawPart(body); drawMicrophones();
    if (cosYaw * cosTilt > .013) {
      drawFace(displayRecess); drawFace(windowInsert); drawFace(keyOpening); drawPart(button);
    }
    const facing = Math.cos(yaw);
    const label = zoom > .65 ? "Дисплей и кнопка" : Math.abs(facing) < .4 ? "Торец" : facing > 0 ? "Лицевая сторона" : "Спинка";
    if (angleLabel && angleLabel.textContent !== label) angleLabel.textContent = label;
    if (stage && stage.dataset.rendered !== "true") {
      stage.dataset.rendered = "true";
      requestMeasure();
    }
  }

  function angleAt(fraction) {
    return Math.PI * fraction + homeAngle * Math.max(0, 1 - 2 * fraction) ** 2;
  }

  function measureSequence(force = false, fromScroll = false) {
    if (!sequence || !pin || !inView || document.hidden) return;
    const style = getComputedStyle(pin);
    const distance = sequence.offsetHeight - pin.offsetHeight;
    const sticky = style.position === "sticky" && distance > 1;
    const raw = sticky ? (parseFloat(style.top) - sequence.getBoundingClientRect().top) / distance : 0;
    const next = Math.max(0, Math.min(1, raw));
    const previous = progress;
    const wasBefore = beforeSequence;
    beforeSequence = raw < 0 || !sticky;
    if (next !== previous) {
      progress = next;
      sequence.style.setProperty("--model-progress", String(Number(next.toFixed(4))));
    }
    if (!rotating || dragging?.active) return;
    if (holdingView) {
      if (!fromScroll || !sticky || next === previous || raw < 0 || raw > 1 || Math.abs(window.scrollY - holdScrollY) < 1) return;
      holdingView = false;
      destination = null; leaveDetail(); clearViews();
      scrollOffset = Math.round((yaw - angleAt(next)) / turn) * turn;
      scrollTarget = scrollOffset + angleAt(next);
      requestDraw();
      return;
    }
    if (!sticky) {
      if (scrollTarget !== null) { scrollTarget = null; requestDraw(); }
      return;
    }
    if (!force && next === previous && wasBefore === beforeSequence) return;
    if (next === 0 && scrollTarget === null && !(previous > 0)) return;
    if (scrollTarget === null) scrollOffset = Math.round((yaw - angleAt(previous ?? 0)) / turn) * turn;
    scrollTarget = scrollOffset + angleAt(next);
    requestDraw();
  }

  function requestMeasure() {
    if (sequence && inView && !document.hidden && !measureFrame) {
      measureFrame = requestAnimationFrame(() => {
        measureFrame = 0;
        const fromScroll = pageScrolled;
        pageScrolled = false;
        measureSequence(false, fromScroll);
      });
    }
  }

  function requestDraw() {
    if (inView && !document.hidden && !frame) frame = requestAnimationFrame(loop);
  }

  function loop(now) {
    frame = 0;
    if (!inView || document.hidden) { lastFrame = 0; return; }
    if (lastFrame && now - lastFrame < 1000 / 30 - 1) { requestDraw(); return; }
    const elapsed = lastFrame ? Math.min((now - lastFrame) / 1000, .12) : 1 / 30;
    lastFrame = now;
    const target = destination ?? scrollTarget;
    if (target !== null) {
      const delta = target - yaw;
      if (Math.abs(delta) < .002 || reduced.matches) {
        yaw = target;
        destination = null;
        if (beforeSequence) scrollTarget = null;
      } else {
        yaw += delta * (1 - Math.exp(-elapsed * (scrollTarget === null ? 9 : 16)));
      }
    } else if (rotating && !holdingView && !dragging) {
      yaw = (yaw + elapsed * .25) % turn;
    }
    zoom += (targetZoom - zoom) * (1 - Math.exp(-elapsed * 8));
    if (reduced.matches || Math.abs(targetZoom - zoom) < .001) zoom = targetZoom;
    draw();
    const needsRotation = rotating && !holdingView && !dragging && (scrollTarget === null || yaw !== scrollTarget);
    if (needsRotation || destination !== null || zoom !== targetZoom) requestDraw();
    else lastFrame = 0;
  }

  function refresh() {
    if (inView && !document.hidden) {
      requestDraw();
    } else {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(measureFrame);
      frame = 0; measureFrame = 0; lastFrame = 0;
    }
  }

  function updateControls() {
    if (!motion) return;
    motion.setAttribute("aria-pressed", String(rotating));
    motion.disabled = reduced.matches;
    const label = reduced.matches ? "Вращение отключено в настройках системы" : rotating ? "Остановить вращение" : "Включить вращение";
    motion.setAttribute("aria-label", label);
    (motion.querySelector("[data-motion-label]") || motion).textContent = label;
  }

  function leaveDetail() { targetZoom = 0; if (reduced.matches) zoom = 0; }
  function clearViews() { views.forEach(view => view.setAttribute("aria-pressed", "false")); }
  function holdView() {
    holdingView = true;
    holdScrollY = window.scrollY;
    destination = null; scrollTarget = null;
    leaveDetail();
  }
  function manual(amount) {
    holdView(); clearViews(); yaw += amount; refresh();
  }

  motion?.addEventListener("click", () => {
    if (reduced.matches) return;
    motionRequested = !rotating;
    rotating = motionRequested;
    destination = null; scrollTarget = null;
    if (rotating) {
      holdingView = false;
      leaveDetail(); clearViews(); measureSequence(true);
    } else {
      holdingView = true;
      holdScrollY = window.scrollY;
      targetZoom = zoom;
    }
    updateControls(); refresh();
  });
  views.forEach(view => view.addEventListener("click", () => {
    const target = { front: 0, side: Math.PI / 2, back: Math.PI, detail: -.20 }[view.dataset.modelView];
    if (target === undefined) return;
    holdView();
    targetZoom = view.dataset.modelView === "detail" ? 1 : 0;
    if (reduced.matches) zoom = targetZoom;
    views.forEach(other => other.setAttribute("aria-pressed", String(other === view)));
    destination = yaw + Math.atan2(Math.sin(target - yaw), Math.cos(target - yaw));
    if (reduced.matches) { yaw = destination; destination = null; }
    refresh();
  }));
  canvas.style.touchAction = "pan-y pinch-zoom";
  canvas.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    dragging = { id: event.pointerId, x: event.clientX, y: event.clientY, angle: yaw, active: false };
  });
  canvas.addEventListener("pointermove", event => {
    if (!dragging || dragging.id !== event.pointerId) return;
    const dx = event.clientX - dragging.x, dy = event.clientY - dragging.y;
    if (!dragging.active && Math.abs(dx) < 4) return;
    if (!dragging.active && Math.abs(dy) > Math.abs(dx)) { dragging = null; refresh(); return; }
    if (!dragging.active) {
      dragging.active = true; holdView(); clearViews(); canvas.setPointerCapture(event.pointerId);
    }
    yaw = dragging.angle + dx * turn / Math.max(280, Math.min(viewWidth, 880));
    refresh();
  });
  function finishDrag() { if (dragging) { dragging = null; refresh(); } }
  canvas.addEventListener("pointerup", finishDrag);
  canvas.addEventListener("pointercancel", finishDrag);
  canvas.addEventListener("lostpointercapture", finishDrag);
  canvas.addEventListener("pointerleave", () => { if (!dragging?.active) finishDrag(); });
  canvas.addEventListener("keydown", event => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault(); manual(event.key === "ArrowRight" ? .18 : -.18);
    } else if (event.key === "Home") {
      event.preventDefault(); manual(homeAngle - yaw);
    } else if (event.key === " " && motion) {
      event.preventDefault(); motion.click();
    }
  });
  reduced.addEventListener("change", () => {
    rotating = motionRequested && !reduced.matches;
    scrollTarget = null;
    if (reduced.matches) {
      if (destination !== null) yaw = destination;
      destination = null;
      zoom = targetZoom;
    }
    measureSequence(true); updateControls(); refresh();
  });
  window.addEventListener("scroll", () => {
    if (!inView || document.hidden) return;
    pageScrolled = true;
    requestMeasure();
  }, { passive: true });
  document.addEventListener("visibilitychange", () => { requestMeasure(); refresh(); });
  new IntersectionObserver(entries => {
    inView = entries[0].isIntersecting;
    requestMeasure(); refresh();
  }).observe(canvas);
  const sizes = new ResizeObserver(() => { requestMeasure(); refresh(); });
  sizes.observe(canvas);
  if (sequence && pin) { sizes.observe(sequence); sizes.observe(pin); }
  updateControls();
})();
