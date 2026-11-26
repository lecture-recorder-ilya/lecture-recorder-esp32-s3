"use strict";

(() => {
  const canvas = document.querySelector("#device-model");
  if (!canvas) return;
  const stage = canvas.closest(".model-stage");
  const sequence = canvas.closest(".model-sequence");
  const pin = canvas.closest(".model-pin");
  const angleLabel = document.querySelector("#model-angle");
  const motion = document.querySelector("#model-motion");
  const views = [...document.querySelectorAll("[data-model-view]")];
  const poster = stage.querySelector(".model-poster");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const angles = {front: "Лицевая сторона", side: "Торец", back: "Обратная сторона", detail: "Входы микрофонов"};
  const photos = {front: "zu-case-front.webp", side: "zu-case-side.webp", back: "zu-case-back.webp", detail: "zu-case-detail.webp"};
  const turn = Math.PI * 2, homeAngle = -.52;
  let yaw = homeAngle, destination = null, rotating = !reduced.matches;
  let motionRequested = true, inView = false, dragging = null, frame = 0, lastFrame = 0;
  let progress = null, scrollTarget = null, scrollOffset = 0, measureFrame = 0;
  let beforeSequence = true, holdingView = false, holdScrollY = 0, pageScrolled = false;
  let targetZoom = 0, zoom = 0, viewWidth = 0, renderer;

  function showStatic(view = "front") {
    stage.dataset.rendered = "static";
    poster.src = new URL("assets/" + photos[view], document.baseURI).href;
    poster.alt = "Корпус «зу». " + angles[view];
    angleLabel.textContent = angles[view];
    canvas.tabIndex = -1;
    motion.hidden = true;
    for (const button of views) button.setAttribute("aria-pressed", String(button.dataset.modelView === view));
  }

  const vertexSource = `
    attribute vec3 aPosition, aNormal;
    uniform mat3 uRotation;
    uniform vec2 uProjection;
    uniform float uLift;
    uniform vec3 uCenter;
    varying vec3 vPosition, vNormal, vLocal;
    void main() {
      vLocal = aPosition * 1000. - uCenter;
      vPosition = uRotation * vLocal;
      vNormal = uRotation * aNormal;
      float perspective = 155. / (155. - vPosition.z);
      gl_Position = vec4(vPosition.xy * uProjection * perspective + vec2(0.,uLift), -vPosition.z / 120., 1.);
    }`;
  const fragmentSource = `
    precision highp float;
    varying vec3 vPosition, vNormal, vLocal;
    uniform vec3 uColor;
    uniform vec3 uFinish;
    float panel(vec3 reflection, vec3 direction, float tightness) {
      return pow(max(dot(reflection,normalize(direction)),0.),tightness);
    }
    vec3 studio(vec3 r, float rough) {
      float key = panel(r,vec3(-.68,.78,.72),mix(22.,4.,rough));
      float strip = exp(-abs(r.x+.26+.27*r.y)*mix(34.,8.,rough)) *
                    smoothstep(-.65,-.12,r.y) * smoothstep(-.20,.43,r.z);
      float rim = panel(r,vec3(.87,-.08,.14),mix(46.,6.,rough));
      return vec3(.18,.21,.24) + vec3(3.5,3.12,2.64)*key + vec3(2.0,1.94,1.72)*strip + vec3(1.85,2.12,2.35)*rim;
    }
    void main() {
      vec3 n = normalize(vNormal);
      vec3 eye = normalize(vec3(0.,0.,155.) - vPosition);
      if (dot(n,eye) < 0.) n = -n;
      vec3 r = reflect(-eye,n);
      float metal = uFinish.x, rough = uFinish.y;
      float key = max(dot(n,normalize(vec3(-.63,.75,1.))),0.);
      float fill = max(dot(n,normalize(vec3(.84,.12,.64))),0.);
      float fresnel = pow(1.-max(dot(n,eye),0.),5.);
      vec3 base = uColor;
      if (uFinish.z > 1.5 && uFinish.z < 2.5) {
        float grain = sin(vLocal.x * 38. + vLocal.y * 26.) * sin(vLocal.y * 43. - vLocal.x * 12.);
        base *= 1. + grain*.10;
      }
      vec3 diffuse = base * (.39 + .86*key + .32*fill) * (1.-metal*.56);
      vec3 f0 = mix(vec3(.025),base,metal);
      vec3 spec = studio(r,rough) * (f0 + (1.-f0)*fresnel*.64);
      if (uFinish.z > .5 && uFinish.z < 1.5) {
        float band = smoothstep(-.75,.7,r.x*.8+r.y+.03*vLocal.x);
        spec += vec3(.014,.018,.019) * band;
      }
      if (uFinish.z > 2.5) {
        float distanceToLight = length((vPosition.xy - vec2(-22.,38.)) / vec2(76.,96.));
        diffuse *= mix(.66,1.14,1. - smoothstep(.05,1.23,distanceToLight));
        spec += vec3(.034,.030,.026)*pow(1.-max(dot(n,eye),0.),2.);
      }
      vec3 lit = diffuse + spec;
      lit = lit / (1. + .43*lit);
      gl_FragColor = vec4(pow(clamp(lit,0.,1.),vec3(1./2.2)),1.);
    }`;

  function shader(gl, type, code) {
    const result = gl.createShader(type);
    gl.shaderSource(result, code);
    gl.compileShader(result);
    if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) throw Error("Ошибка шейдера");
    return result;
  }

  function loadScene(gl, bytes) {
    const data = new DataView(bytes);
    if (data.getUint32(0,true) !== 0x46546c67 || data.getUint32(4,true) !== 2) throw Error("Формат модели");
    const textLength = data.getUint32(12,true);
    const scene = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes,20,textLength)));
    const binary = 28 + textLength;
    const program = gl.createProgram();
    gl.attachShader(program, shader(gl,gl.VERTEX_SHADER,vertexSource));
    gl.attachShader(program, shader(gl,gl.FRAGMENT_SHADER,fragmentSource));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw Error("Ошибка программы");
    gl.useProgram(program);
    const attributes = Object.fromEntries(["aPosition","aNormal"].map(k=>[k,gl.getAttribLocation(program,k)]));
    const u = Object.fromEntries(["uRotation","uProjection","uLift","uCenter","uColor","uFinish"].map(k=>[k,gl.getUniformLocation(program,k)]));
    const buffers = scene.bufferViews.map(view=>{
      const handle = gl.createBuffer();
      gl.bindBuffer(view.target,handle);
      gl.bufferData(view.target,new Uint8Array(bytes,binary + (view.byteOffset || 0),view.byteLength),gl.STATIC_DRAW);
      return handle;
    });
    const surfaces = scene.meshes.flatMap(mesh=>mesh.primitives.map(p=>{
      const material = scene.materials[p.material], pbr = material.pbrMetallicRoughness;
      const kind = material.name === "Поляризатор" ? 1 : material.name === "Лента" ? 2 : material.name.startsWith("Графит") ? 3 : 0;
      return {p: scene.accessors[p.attributes.POSITION], n:scene.accessors[p.attributes.NORMAL], i:scene.accessors[p.indices],
        pigment:pbr.baseColorFactor.slice(0,3), finish:[pbr.metallicFactor,pbr.roughnessFactor,kind]};
    }));
    const low = [0,1,2].map(axis=>Math.min(...surfaces.map(s=>s.p.min[axis])) * 1000);
    const high = [0,1,2].map(axis=>Math.max(...surfaces.map(s=>s.p.max[axis])) * 1000);
    gl.uniform3fv(u.uCenter,low.map((v,i)=>(v+high[i])/2));
    const modelHeight = high[1] - low[1], modelWidth = high[0] - low[0];
    if (surfaces.some(s=>s.i.componentType===gl.UNSIGNED_INT) && !gl.getExtension("OES_element_index_uint")) throw Error("Индексы модели");
    gl.enable(gl.DEPTH_TEST);
    gl.enableVertexAttribArray(attributes.aPosition);
    gl.enableVertexAttribArray(attributes.aNormal);
    gl.clearColor(0,0,0,0);
    return function render(yaw,zoom,width,height,density) {
      const w = Math.max(1,Math.round(width*density)), h = Math.max(1,Math.round(height*density));
      if (canvas.width!==w || canvas.height!==h) { canvas.width=w; canvas.height=h; }
      gl.viewport(0,0,w,h);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const scale = Math.min(height*.78/modelHeight,width*.76/modelWidth) * (1 + .82*zoom);
      const tilt = -.23 - .07*Math.sin(yaw) - .12*zoom, roll = -.20 + .08*zoom;
      const ca=Math.cos(yaw), sa=Math.sin(yaw), cb=Math.cos(tilt), sb=Math.sin(tilt), cc=Math.cos(roll), sc=Math.sin(roll);
      gl.uniformMatrix3fv(u.uRotation,false,[
        cc*ca-sc*sb*sa, sc*ca+cc*sb*sa,-cb*sa,
        -sc*cb,cc*cb,sb,
        cc*sa+sc*sb*ca,sc*sa-cc*sb*ca,cb*ca
      ]);
      gl.uniform2f(u.uProjection,2*scale/width,2*scale/height);
      gl.uniform1f(u.uLift,.02-zoom*.83);
      for (const s of surfaces) {
        gl.bindBuffer(gl.ARRAY_BUFFER,buffers[s.p.bufferView]);
        gl.vertexAttribPointer(attributes.aPosition,3,s.p.componentType,s.p.normalized || false,scene.bufferViews[s.p.bufferView].byteStride || 0,s.p.byteOffset || 0);
        gl.bindBuffer(gl.ARRAY_BUFFER,buffers[s.n.bufferView]);
        gl.vertexAttribPointer(attributes.aNormal,3,s.n.componentType,s.n.normalized || false,scene.bufferViews[s.n.bufferView].byteStride || 0,s.n.byteOffset || 0);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,buffers[s.i.bufferView]);
        gl.uniform3fv(u.uColor,s.pigment);
        gl.uniform3fv(u.uFinish,s.finish);
        gl.drawElements(gl.TRIANGLES,s.i.count,s.i.componentType,s.i.byteOffset || 0);
      }
    };
  }

  async function init() {
    const gl = canvas.getContext("webgl",{alpha:true,antialias:true,powerPreference:"low-power",premultipliedAlpha:false});
    if (!gl || location.protocol === "file:") { showStatic(); return; }
    const response = await fetch("assets/zu-case.glb");
    if (!response.ok) throw Error("Модель недоступна");
    const bytes = await response.arrayBuffer();
    renderer = loadScene(gl,bytes);
    canvas.tabIndex=0;
    motion.hidden=false;
    stage.removeAttribute("data-rendered");
    canvas.addEventListener("webglcontextlost",e=>{
      e.preventDefault();
      renderer=null;
      cancelAnimationFrame(frame);
      frame=0;
      showStatic();
    },{once:true});
    canvas.addEventListener("webglcontextrestored",()=>{ init().catch(()=>showStatic()); },{once:true});
    updateControls();
    refresh();
  }

  function draw() {
    if (!renderer) return;
    const box = canvas.getBoundingClientRect();
    viewWidth=box.width;
    if (!viewWidth || !box.height) return;
    renderer(yaw,zoom,viewWidth,box.height,Math.min(devicePixelRatio || 1,1.7));
    const facing=Math.cos(yaw);
    const caption = zoom>.65 ? angles.detail : Math.abs(facing)<.4 ? angles.side : facing>0 ? angles.front : angles.back;
    if (angleLabel.textContent!==caption) angleLabel.textContent=caption;
    if (stage.dataset.rendered !== "true") { stage.dataset.rendered="true"; requestMeasure(); }
  }

  function angleAt(fraction) {
    return turn * fraction + homeAngle * Math.max(0, 1 - 2 * fraction) ** 2;
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
    if (renderer && inView && !document.hidden && !frame) frame = requestAnimationFrame(loop);
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
    if (!renderer) { showStatic(view.dataset.modelView); return; }
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
  init().catch(() => showStatic());
})();
