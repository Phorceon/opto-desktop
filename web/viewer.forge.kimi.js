import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export function forgeUrls(id) {
  return { scene: `/out/forge/${id}/scene.json`, glb: `/out/forge/${id}/model.glb` };
}

function cloneForgeMaterial(source) {
  if (source.isMeshStandardMaterial) return source.clone();

  const material = new THREE.MeshStandardMaterial({
    color: source.color ? source.color.clone() : new THREE.Color(0xffffff),
    metalness: source.metalness ?? 0,
    roughness: source.roughness ?? 0.5,
    emissive: source.emissive ? source.emissive.clone() : new THREE.Color(0),
    emissiveIntensity: source.emissiveIntensity ?? 1
  });
  const properties = [
    'map', 'lightMap', 'aoMap', 'emissiveMap', 'bumpMap', 'normalMap',
    'displacementMap', 'roughnessMap', 'metalnessMap', 'alphaMap', 'envMap',
    'normalScale', 'bumpScale', 'displacementScale', 'displacementBias',
    'aoMapIntensity', 'lightMapIntensity', 'envMapIntensity'
  ];
  for (const property of properties) {
    if (source[property] !== undefined) material[property] = source[property];
  }
  material.name = source.name;
  material.opacity = source.opacity;
  material.transparent = source.transparent;
  material.alphaTest = source.alphaTest;
  material.depthTest = source.depthTest;
  material.depthWrite = source.depthWrite;
  material.blending = source.blending;
  material.vertexColors = source.vertexColors;
  material.toneMapped = source.toneMapped;
  return material;
}

export function createViewer(container, { onPartClick, onHover, insets = {} } = {}) {
  const safe = { top: insets.top ?? 8, bottom: insets.bottom ?? 8, left: insets.left ?? 8, right: insets.right ?? 8 };
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.localClippingEnabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const canvas = renderer.domElement;
  Object.assign(canvas.style, {
    position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block'
  });
  container.appendChild(canvas);

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'opto-leaders');
  Object.assign(svg.style, {
    position: 'absolute', inset: '0', width: '100%', height: '100%',
    pointerEvents: 'none', overflow: 'visible'
  });
  container.appendChild(svg);

  const labelsDiv = document.createElement('div');
  labelsDiv.className = 'opto-labels';
  Object.assign(labelsDiv.style, {
    position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'visible'
  });
  container.appendChild(labelsDiv);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 2000);
  const defaultCamera = new THREE.Vector3(6, 4, 7).normalize();
  camera.position.copy(defaultCamera).multiplyScalar(12);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.8;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a4250, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(5, 8, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9fc6ff, 0.8);
  fill.position.set(-6, 2, -4);
  scene.add(fill);

  const parts = new Map();
  const pickMeshes = [];
  const arrows = [];
  const labels = [];
  const beats = [];
  const tweens = new Set();
  const forgeGroups = new Set();
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 2);
  const sceneCenter = new THREE.Vector3();
  const desiredCamera = new THREE.Vector3();
  const cameraDirection = defaultCamera.clone();
  const unitScale = new THREE.Vector3(1, 1, 1);
  const tempMatrix = new THREE.Matrix4();
  const tempBox = new THREE.Box3();
  const tempVector = new THREE.Vector3();
  let sceneRadius = 2;
  const sceneBox = new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  let meta = freshMeta();
  let width = 1;
  let height = 1;
  let autoFrame = true;
  let framing = false;
  let cutOn = false;
  let cutTween = null;
  let explodeTween = null;
  let explodeTarget = 0;
  let explodeValue = 0;
  let highlightIds = null;
  let hoveredId = null;
  let pointerStart = null;
  let dragged = false;
  let running = true;
  let disposed = false;
  let raf = 0;

  function freshMeta() {
    return {
      title: '', subtitle: '', cut: { axis: 'z', keep: 'neg' }, camera: [6, 4, 7]
    };
  }

  function vector(a, fallback = 0) {
    return new THREE.Vector3(
      Number(a?.[0] ?? fallback), Number(a?.[1] ?? fallback), Number(a?.[2] ?? fallback)
    );
  }

  function geometryFor(part) {
    const s = part.size;
    let geometry;
    switch (part.shape) {
      case 'wedge': {
        const [w, h, d] = s;
        const shape = new THREE.Shape();
        shape.moveTo(-w / 2, -h / 2);
        shape.lineTo(w / 2, -h / 2);
        shape.lineTo(-w / 2, h / 2);
        shape.closePath();
        geometry = new THREE.ExtrudeGeometry(shape, { depth: d, bevelEnabled: false });
        geometry.translate(0, 0, -d / 2);
        break;
      }
      case 'cylinder':
        geometry = new THREE.CylinderGeometry(s[0], s[1], s[2], 40);
        break;
      case 'cone':
        geometry = new THREE.ConeGeometry(s[0], s[1], 40);
        break;
      case 'sphere':
        geometry = new THREE.SphereGeometry(s[0], 40, 24);
        break;
      case 'ellipsoid':
        geometry = new THREE.SphereGeometry(1, 40, 24);
        geometry.scale(s[0], s[1], s[2]);
        break;
      case 'capsule':
        geometry = new THREE.CapsuleGeometry(s[0], s[1], 8, 24);
        break;
      case 'torus':
        geometry = new THREE.TorusGeometry(s[0], s[1], 20, 64);
        geometry.rotateX(Math.PI / 2);
        break;
      case 'tube': {
        const [ro, ri, h] = s;
        const profile = [
          new THREE.Vector2(ri, -h / 2), new THREE.Vector2(ro, -h / 2),
          new THREE.Vector2(ro, h / 2), new THREE.Vector2(ri, h / 2),
          new THREE.Vector2(ri, -h / 2)
        ];
        geometry = new THREE.LatheGeometry(profile, 48);
        break;
      }
      case 'panel': {
        // Opto: any flat outline, extruded along local z and centred
        const pts = part.points || [];
        const shape = new THREE.Shape();
        pts.forEach(([x, y], i) => (i ? shape.lineTo(x, y) : shape.moveTo(x, y)));
        shape.closePath();
        const t = s[0] || 0.08;
        geometry = new THREE.ExtrudeGeometry(shape, { depth: t, bevelEnabled: false });
        geometry.translate(0, 0, -t / 2);
        break;
      }
      case 'lathe': {
        // Opto: profile [[r,y],...] revolved about local y
        const prof = (part.points || []).map(([r, y]) => new THREE.Vector2(Math.max(0, r), y));
        geometry = new THREE.LatheGeometry(prof, 48);
        break;
      }
      default:
        geometry = new THREE.BoxGeometry(s[0], s[1], s[2]);
    }
    geometry.computeBoundingBox();
    return geometry;
  }

  function easeOutBack(x) {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
  }

  function smooth(x) {
    return x * x * (3 - 2 * x);
  }

  function addTween(duration, update, ease = x => x, complete = null, delay = 0) {
    const tween = { start: performance.now(), duration, update, ease, complete, delay };
    tweens.add(tween);
    return tween;
  }

  function runTweens(now) {
    for (const tween of [...tweens]) {
      const progress = tween.duration <= 0
        ? (now >= tween.start + tween.delay ? 1 : 0)
        : Math.max(0, Math.min(1, (now - tween.start - tween.delay) / tween.duration));
      tween.update(tween.ease(progress), progress);
      if (progress === 1) {
        tweens.delete(tween);
        if (tween.complete) tween.complete();
      }
    }
  }

  function configurePlane() {
    clipPlane.normal.set(0, 0, 0);
    clipPlane.normal[meta.cut.axis] = 1;
    if (meta.cut.keep === 'neg') clipPlane.normal.negate();
    if (!cutOn && !cutTween) clipPlane.constant = unclippedConstant();
  }

  function unclippedConstant() {
    return sceneRadius + Math.abs(sceneCenter.dot(clipPlane.normal)) + 0.01;
  }

  function disposePart(record) {
    const geometries = new Set(record.geometries || []);
    const materials = new Set(record.materials || []);
    const edgeGeometries = new Set(record.edgeGeometries || []);
    const edgeMaterials = new Set(record.edgeMaterials || []);

    for (const mesh of record.meshes) {
      mesh.removeFromParent();
      if (mesh.geometry) geometries.add(mesh.geometry);
    }
    if (record.geometry) geometries.add(record.geometry);
    if (record.material) materials.add(record.material);
    if (record.edgeGeometry) edgeGeometries.add(record.edgeGeometry);
    if (record.edgeMaterial) edgeMaterials.add(record.edgeMaterial);

    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    for (const geometry of edgeGeometries) geometry.dispose();
    for (const material of edgeMaterials) material.dispose();
  }

  function addPart(data) {
    if (parts.has(data.id)) {
      const old = parts.get(data.id);
      disposePart(old);
      parts.delete(data.id);
      for (let i = pickMeshes.length - 1; i >= 0; i--) {
        if (pickMeshes[i].userData.partId === data.id) pickMeshes.splice(i, 1);
      }
    }

    const geometry = geometryFor(data);
    const opacity = data.opacity ?? 1;
    const color = new THREE.Color(data.color);
    const baseEmissive = data.internal ? color.clone().multiplyScalar(0.08) : new THREE.Color(0);
    const materialOptions = {
      color, metalness: 0.25, roughness: 0.55,
      transparent: opacity < 1, opacity, side: THREE.DoubleSide,
      emissive: baseEmissive.clone()
    };
    const edgeOptions = { color: 0x1b1f24, transparent: true, opacity: 0.35 };
    if (!data.internal) {
      materialOptions.clippingPlanes = [clipPlane];
      edgeOptions.clippingPlanes = [clipPlane];
    }
    const material = new THREE.MeshStandardMaterial(materialOptions);
    const edgeGeometry = new THREE.EdgesGeometry(geometry, 30);
    const edgeMaterial = new THREE.LineBasicMaterial(edgeOptions);
    const record = {
      data,
      geometry,
      geometries: [geometry],
      material,
      materials: [material],
      edgeGeometry,
      edgeGeometries: [edgeGeometry],
      edgeMaterial,
      edgeMaterials: [edgeMaterial],
      color,
      baseEmissive,
      baseEmissives: [baseEmissive],
      baseOpacity: opacity,
      baseOpacities: [opacity],
      baseTransparents: [opacity < 1],
      meshes: []
    };
    const repeat = data.repeat || { n: 1, step: [0, 0, 0], turn: [0, 0, 0] };
    const count = Math.max(1, repeat.n || 1);
    const rad = Math.PI / 180;

    for (let i = 0; i < count; i++) {
      const mesh = new THREE.Mesh(geometry, material);
      const base = new THREE.Vector3(
        data.pos[0] + (repeat.step?.[0] || 0) * i,
        data.pos[1] + (repeat.step?.[1] || 0) * i,
        data.pos[2] + (repeat.step?.[2] || 0) * i
      );
      mesh.rotation.set(
        (data.rot[0] + (repeat.turn?.[0] || 0) * i) * rad,
        (data.rot[1] + (repeat.turn?.[1] || 0) * i) * rad,
        (data.rot[2] + (repeat.turn?.[2] || 0) * i) * rad,
        'XYZ'
      );
      if (repeat.around) {
        // radial repeat (Opto schema): spin copy i by 360*i/n about `around` through `pivot`
        const axis = new THREE.Vector3(repeat.around === 'x' ? 1 : 0, repeat.around === 'y' ? 1 : 0,
          repeat.around === 'z' ? 1 : 0);
        const q = new THREE.Quaternion().setFromAxisAngle(axis, (2 * Math.PI * i) / count);
        const pivot = vector(repeat.pivot || data.pos);
        base.sub(pivot).applyQuaternion(q).add(pivot);
        mesh.quaternion.premultiply(q);
      }
      mesh.position.copy(base);
      mesh.scale.setScalar(0.001);
      mesh.userData.partId = data.id;
      mesh.userData.basePosition = base;
      mesh.userData.baseScale = new THREE.Vector3(1, 1, 1);
      mesh.userData.explodeDirection = new THREE.Vector3();
      const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
      mesh.add(edges);
      scene.add(mesh);
      record.meshes.push(mesh);
      pickMeshes.push(mesh);
    }
    parts.set(data.id, record);
    addTween(280, value => {
      const scale = 0.001 + 0.999 * value;
      for (const mesh of record.meshes) {
        mesh.scale.copy(mesh.userData.baseScale).multiplyScalar(scale);
      }
    }, easeOutBack);
    updateBounds();
    applyHighlightStyles();
  }

  function updateBounds() {
    const bounds = new THREE.Box3();
    let any = false;
    for (const record of parts.values()) {
      for (const mesh of record.meshes) {
        const geometry = mesh.geometry;
        if (!geometry.boundingBox) geometry.computeBoundingBox();
        if (!geometry.boundingBox) continue;
        tempMatrix.compose(
          mesh.userData.basePosition,
          mesh.quaternion,
          mesh.userData.baseScale || unitScale
        );
        tempBox.copy(geometry.boundingBox).applyMatrix4(tempMatrix);
        bounds.union(tempBox);
        any = true;
      }
    }
    if (!any) bounds.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
    sceneBox.copy(bounds);
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    sceneCenter.copy(sphere.center);
    sceneRadius = Math.max(0.5, sphere.radius);

    for (const record of parts.values()) {
      for (const mesh of record.meshes) {
        const geometry = mesh.geometry;
        if (!geometry.boundingBox) continue;
        const localCenter = geometry.boundingBox.getCenter(new THREE.Vector3());
        tempMatrix.compose(
          mesh.userData.basePosition,
          mesh.quaternion,
          mesh.userData.baseScale || unitScale
        );
        const center = localCenter.applyMatrix4(tempMatrix);
        const direction = center.sub(sceneCenter);
        if (direction.lengthSq() < 1e-10) {
          direction.copy(mesh.userData.basePosition).sub(sceneCenter);
        }
        if (direction.lengthSq() < 1e-10) direction.set(0, 0, 0);
        else direction.normalize();
        mesh.userData.explodeDirection.copy(direction);
      }
    }
    if (!cutOn && !cutTween) clipPlane.constant = unclippedConstant();
    applyExplode(explodeValue);
    requestFraming();
  }

  function requestFraming() {
    if (!autoFrame || parts.size === 0) return;
    // Opto: fit the scene's bounding box as seen from the camera direction, not its bounding sphere,
    // so long thin objects (rockets, aircraft) fill the view instead of sitting small in the middle.
    const vertical = THREE.MathUtils.degToRad(camera.fov / 2);
    const tanV = Math.tan(vertical);
    const tanH = tanV * camera.aspect;
    const fill = 0.78;
    const dir = cameraDirection.clone().normalize();
    const up = Math.abs(dir.y) > 0.98 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(up, dir).normalize();
    const camUp = new THREE.Vector3().crossVectors(dir, right).normalize();
    let distance = 1;
    const b = sceneBox;
    for (let i = 0; i < 8; i++) {
      const c = new THREE.Vector3(i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y, i & 4 ? b.max.z : b.min.z).sub(sceneCenter);
      const depth = c.dot(dir);
      distance = Math.max(distance,
        depth + Math.abs(c.dot(right)) / (tanH * fill),
        depth + Math.abs(c.dot(camUp)) / (tanV * fill));
    }
    desiredCamera.copy(dir).multiplyScalar(distance).add(sceneCenter);
    framing = true;
  }

  function addArrow(data) {
    const from = vector(data.from);
    const to = vector(data.to);
    const delta = to.clone().sub(from);
    const length = delta.length();
    const direction = delta.normalize();
    const color = new THREE.Color(data.color);
    const material = new THREE.MeshStandardMaterial({
      color, emissive: color.clone().multiplyScalar(0.35),
      metalness: 0.25, roughness: 0.55, transparent: true, opacity: 1 - explodeValue
    });
    const shaftLength = Math.max(0.01, length - 0.32);
    const shaft = new THREE.Mesh(
      new THREE.CylinderGeometry(0.045, 0.045, shaftLength, 24), material
    );
    shaft.position.copy(from).addScaledVector(direction, shaftLength / 2);
    shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.32, 24), material);
    head.position.copy(to).addScaledVector(direction, -0.16);
    head.quaternion.copy(shaft.quaternion);
    const group = new THREE.Group();
    group.add(shaft, head);
    group.visible = explodeValue < 0.999;
    scene.add(group);

    let chip = null;
    if (data.label) {
      chip = document.createElement('div');
      chip.className = 'opto-chip opto-arrow-chip';
      chip.textContent = data.label;
      Object.assign(chip.style, {
        position: 'absolute', transform: 'translate(-50%, -50%)', visibility: 'hidden'
      });
      labelsDiv.appendChild(chip);
    }
    arrows.push({ group, material, geometries: [shaft.geometry, head.geometry], chip,
      midpoint: from.clone().lerp(to, 0.72) });
  }

  function svgElement(name) {
    return document.createElementNS('http://www.w3.org/2000/svg', name);
  }

  function addLabel(data) {
    const chip = document.createElement('div');
    const allowed = ['yellow', 'pink', 'green', 'blue', 'orange', 'purple'];
    const color = allowed.includes(data.color) ? data.color : 'yellow';
    chip.className = `opto-chip opto-${color}`;
    chip.textContent = data.text;
    Object.assign(chip.style, {
      position: 'absolute', transform: 'translate(-50%, -50%)', visibility: 'hidden'
    });
    labelsDiv.appendChild(chip);
    const line = svgElement('line');
    line.setAttribute('stroke', '#1b1f24');
    line.setAttribute('stroke-width', '1.5');
    const circle = svgElement('circle');
    circle.setAttribute('r', '3.5');
    circle.setAttribute('stroke', '#1b1f24');
    circle.setAttribute('stroke-width', '1.5');
    circle.setAttribute('fill', '#ffffff');
    svg.append(line, circle);
    labels.push({ part: data.part, chip, line, circle });
  }

  function applyHighlightStyles() {
    const active = highlightIds !== null;
    for (const [id, record] of parts) {
      const dimmed = active && !highlightIds.has(id);
      for (let i = 0; i < record.materials.length; i++) {
        const material = record.materials[i];
        const baseOpacity = record.baseOpacities[i];
        const transparent = record.baseTransparents[i] || baseOpacity < 1 || dimmed;
        if (material.transparent !== transparent) {
          material.transparent = transparent;
          material.needsUpdate = true;
        }
        material.opacity = dimmed ? 0.18 : baseOpacity;
      }
      for (const edgeMaterial of record.edgeMaterials) {
        edgeMaterial.opacity = dimmed ? 0.35 * 0.18 : 0.35;
      }
    }
  }

  function highlight(ids) {
    highlightIds = ids === null ? null : new Set(ids);
    applyHighlightStyles();
  }

  function applyExplode(value) {
    explodeValue = value;
    const distance = value * 0.55 * sceneRadius;
    for (const record of parts.values()) {
      for (const mesh of record.meshes) {
        mesh.position.copy(mesh.userData.basePosition)
          .addScaledVector(mesh.userData.explodeDirection, distance);
      }
    }
    for (const arrow of arrows) {
      arrow.material.opacity = Math.max(0, 1 - value);
      arrow.group.visible = value < 0.999;
    }
  }

  function setExplode(t) {
    if (disposed) return;
    const target = Math.max(0, Math.min(1, Number(t) || 0));
    explodeTarget = target;
    if (explodeTween) tweens.delete(explodeTween);
    const start = explodeValue;
    explodeTween = addTween(500, value => {
      applyExplode(THREE.MathUtils.lerp(start, explodeTarget, value));
    }, smooth, () => { explodeTween = null; });
  }

  function setCut(on) {
    if (disposed) return;
    on = Boolean(on);
    if (on === cutOn && !cutTween) return;
    if (cutTween) tweens.delete(cutTween);
    cutOn = on;
    const target = on ? 0 : unclippedConstant();
    if (on) clipPlane.constant = unclippedConstant();
    const start = clipPlane.constant;
    cutTween = addTween(600, value => {
      clipPlane.constant = THREE.MathUtils.lerp(start, target, value);
    }, smooth, () => {
      clipPlane.constant = target;
      cutTween = null;
    });
  }

  function project(world) {
    tempVector.copy(world).applyMatrix4(camera.matrixWorldInverse);
    const behind = tempVector.z >= 0;
    const projected = world.clone().project(camera);
    return {
      x: (projected.x * 0.5 + 0.5) * width,
      y: (-projected.y * 0.5 + 0.5) * height,
      behind
    };
  }

  function overlaps(a, b) {
    const gap = 8;
    return a.x < b.x + b.w + gap && a.x + a.w + gap > b.x &&
      a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;
  }

  function hideLabel(label) {
    label.chip.style.visibility = 'hidden';
    label.line.style.display = 'none';
    label.circle.style.display = 'none';
  }

  function updateLabels() {
    camera.updateMatrixWorld();
    const centerScreen = project(sceneCenter);
    const visible = [];
    const active = highlightIds !== null;

    for (const label of labels) {
      const record = parts.get(label.part);
      if (!record || !record.meshes.length) {
        hideLabel(label);
        continue;
      }
      const box = new THREE.Box3().setFromObject(record.meshes[0]);
      const anchor = new THREE.Vector3(
        (box.min.x + box.max.x) / 2, box.max.y, (box.min.z + box.max.z) / 2
      );
      const screen = project(anchor);
      if (screen.behind) {
        hideLabel(label);
        continue;
      }
      label.chip.style.visibility = 'visible';
      label.line.style.display = '';
      label.circle.style.display = '';
      const opacity = active && !highlightIds.has(label.part) ? 0.25 : 1;
      label.chip.style.opacity = String(opacity);
      label.line.style.opacity = String(opacity);
      label.circle.style.opacity = String(opacity);
      const dx = screen.x - centerScreen.x;
      const dy = screen.y - centerScreen.y;
      visible.push({
        label, anchor: screen, dx, dy, length: Math.hypot(dx, dy),
        angle: Math.atan2(dy, dx), w: label.chip.offsetWidth || 80,
        h: label.chip.offsetHeight || 28
      });
    }

    visible.forEach((entry, i) => {
      if (entry.length < 0.001) {
        entry.angle = -Math.PI / 2 + i * Math.PI * 2 / Math.max(1, visible.length);
        entry.dx = Math.cos(entry.angle);
        entry.dy = Math.sin(entry.angle);
      } else {
        entry.dx /= entry.length;
        entry.dy /= entry.length;
      }
    });
    visible.sort((a, b) => a.angle - b.angle);
    const placed = [];
    for (const arrow of arrows) {
      if (!arrow.chip || explodeValue > 0.999) continue;
      const sc = project(arrow.midpoint);
      if (sc.behind) continue;
      const w = arrow.chip.offsetWidth || 70, h = arrow.chip.offsetHeight || 24;
      placed.push({ x: sc.x - w / 2, y: sc.y - h / 2, w, h });
    }

    for (const entry of visible) {
      let rect;
      let found = false;
      for (let step = 0; step <= 6 && !found; step++) {
       for (const turn of [0, 0.42, -0.42, 0.85, -0.85]) {
        const distance = 56 + 22 * step;
        const ca = Math.cos(turn), sa = Math.sin(turn);
        const ddx = entry.dx * ca - entry.dy * sa, ddy = entry.dx * sa + entry.dy * ca;
        // keep chips fully on screen (Opto fix)
        const x = Math.min(width - entry.w / 2 - safe.right, Math.max(entry.w / 2 + safe.left, entry.anchor.x + ddx * distance));
        const y = Math.min(height - entry.h / 2 - safe.bottom, Math.max(entry.h / 2 + safe.top, entry.anchor.y + ddy * distance));
        const cand = { x: x - entry.w / 2, y: y - entry.h / 2, w: entry.w, h: entry.h, cx: x, cy: y };
        if (!rect) rect = cand;
        if (!placed.some(other => overlaps(cand, other))) { rect = cand; found = true; break; }
       }
      }
      placed.push(rect);
      placed.push({ x: entry.anchor.x - 5, y: entry.anchor.y - 5, w: 10, h: 10 });
      entry.label.chip.style.left = `${rect.cx}px`;
      entry.label.chip.style.top = `${rect.cy}px`;
      const endX = Math.max(rect.x, Math.min(entry.anchor.x, rect.x + rect.w));
      const endY = Math.max(rect.y, Math.min(entry.anchor.y, rect.y + rect.h));
      const line = entry.label.line;
      line.setAttribute('x1', entry.anchor.x);
      line.setAttribute('y1', entry.anchor.y);
      line.setAttribute('x2', endX);
      line.setAttribute('y2', endY);
      const circle = entry.label.circle;
      circle.setAttribute('cx', entry.anchor.x);
      circle.setAttribute('cy', entry.anchor.y);
    }

    for (const arrow of arrows) {
      if (!arrow.chip) continue;
      const screen = project(arrow.midpoint);
      const opacity = Math.max(0, 1 - explodeValue);
      arrow.chip.style.visibility = screen.behind || opacity <= 0.001 ? 'hidden' : 'visible';
      arrow.chip.style.opacity = String(opacity);
      arrow.chip.style.left = `${screen.x}px`;
      arrow.chip.style.top = `${screen.y}px`;
    }
  }

  function updateEmissive(now) {
    const pulse = 0.16 + 0.16 * (0.5 + 0.5 * Math.sin(now * 0.006));
    for (const [id, record] of parts) {
      for (let i = 0; i < record.materials.length; i++) {
        const material = record.materials[i];
        if (highlightIds !== null && highlightIds.has(id)) {
          material.emissive.copy(record.color).multiplyScalar(pulse);
        } else if (id === hoveredId) {
          material.emissive.setHex(0x334455);
        } else {
          material.emissive.copy(record.baseEmissives[i]);
        }
      }
    }
  }

  function partAt(event) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pickMeshes, false);
    if (!hits.length) return null;
    return parts.get(hits[0].object.userData.partId)?.data || null;
  }

  function setHovered(part) {
    const id = part?.id || null;
    if (id === hoveredId) return;
    hoveredId = id;
    canvas.style.cursor = id ? 'pointer' : '';
    if (onHover) onHover(part);
  }

  function stopAutomaticCamera() {
    autoFrame = false;
    framing = false;
    controls.autoRotate = false;
  }

  function onPointerDown(event) {
    stopAutomaticCamera();
    pointerStart = { x: event.clientX, y: event.clientY };
    dragged = false;
  }

  function onPointerMove(event) {
    if (pointerStart && Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) >= 5) {
      dragged = true;
    }
    setHovered(partAt(event));
  }

  function onClick(event) {
    const moved = pointerStart ?
      Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) : 0;
    pointerStart = null;
    if (dragged || moved >= 5) {
      dragged = false;
      return;
    }
    dragged = false;
    const part = partAt(event);
    if (part && onPartClick) onPartClick(part, { x: event.clientX, y: event.clientY });
  }

  function onPointerLeave() {
    setHovered(null);
  }

  function reset() {
    tweens.clear();
    cutTween = null;
    explodeTween = null;
    for (const record of parts.values()) disposePart(record);
    parts.clear();
    for (const group of forgeGroups) scene.remove(group);
    forgeGroups.clear();
    pickMeshes.length = 0;
    for (const arrow of arrows) {
      scene.remove(arrow.group);
      for (const geometry of arrow.geometries) geometry.dispose();
      arrow.material.dispose();
    }
    arrows.length = 0;
    labels.length = 0;
    beats.length = 0;
    labelsDiv.replaceChildren();
    svg.replaceChildren();
    meta = freshMeta();
    cutOn = false;
    explodeTarget = 0;
    explodeValue = 0;
    highlightIds = null;
    hoveredId = null;
    dragged = false;
    pointerStart = null;
    canvas.style.cursor = '';
    sceneCenter.set(0, 0, 0);
    sceneRadius = 2;
    cameraDirection.copy(defaultCamera);
    configurePlane();
    clipPlane.constant = unclippedConstant();
    autoFrame = true;
    framing = false;
    controls.autoRotate = true;
    controls.target.set(0, 0, 0);
    camera.position.copy(defaultCamera).multiplyScalar(12);
    controls.update();
  }

  function apply(item) {
    if (disposed || !item) return;
    switch (item.t) {
      case 'meta':
        meta = {
          title: item.title || '', subtitle: item.subtitle || '',
          cut: item.cut || { axis: 'z', keep: 'neg' },
          camera: item.camera || [6, 4, 7]
        };
        cameraDirection.copy(vector(meta.camera, 1));
        if (cameraDirection.lengthSq() < 1e-8) cameraDirection.copy(defaultCamera);
        else cameraDirection.normalize();
        configurePlane();
        requestFraming();
        break;
      case 'part':
        addPart(item);
        break;
      case 'arrow':
        addArrow(item);
        break;
      case 'label':
        addLabel(item);
        break;
      case 'beat':
        beats.push(item);
        break;
    }
  }

  function load(sceneData) {
    reset();
    apply({ t: 'meta', title: sceneData.title, subtitle: sceneData.subtitle,
      cut: sceneData.cut, camera: sceneData.camera });
    for (const part of sceneData.parts || []) apply({ t: 'part', ...part });
    for (const arrow of sceneData.arrows || []) apply({ t: 'arrow', ...arrow });
    for (const label of sceneData.labels || []) apply({ t: 'label', ...label });
    for (const beat of sceneData.beats || []) apply({ t: 'beat', ...beat });
  }

  async function loadForge(sceneData, glbUrl) {
    reset();
    apply({
      t: 'meta',
      title: sceneData.title,
      subtitle: sceneData.subtitle,
      cut: sceneData.cut,
      camera: sceneData.camera || [6, 4, 7]
    });

    const gltf = await new GLTFLoader().loadAsync(glbUrl);
    gltf.scene.updateMatrixWorld(true);

    const meshEntries = [];
    gltf.scene.traverse(object => {
      if (!object.isMesh) return;
      let partId = '_structure';
      let node = object;
      while (node) {
        if (node.userData && node.userData.opto_part !== undefined) {
          partId = String(node.userData.opto_part);
          break;
        }
        node = node.parent;
      }
      meshEntries.push({ mesh: object, partId, worldMatrix: object.matrixWorld.clone() });
    });

    const forgeGroup = new THREE.Group();
    forgeGroup.name = 'opto-forge';
    scene.add(forgeGroup);
    forgeGroups.add(forgeGroup);

    const definitions = new Map();
    for (const part of sceneData.parts || []) definitions.set(part.id, part);
    const forgeRecords = [];

    for (const { mesh, partId, worldMatrix } of meshEntries) {
      let record = parts.get(partId);
      if (!record) {
        const definition = definitions.get(partId) || {
          id: '_structure', name: 'Structure', internal: false
        };
        const data = { ...definition, id: partId };
        record = {
          data,
          geometry: mesh.geometry,
          geometries: [],
          material: null,
          materials: [],
          edgeGeometry: null,
          edgeGeometries: [],
          edgeMaterial: null,
          edgeMaterials: [],
          color: null,
          baseEmissive: null,
          baseEmissives: [],
          baseOpacity: 1,
          baseOpacities: [],
          baseTransparents: [],
          meshes: []
        };
        parts.set(partId, record);
        forgeRecords.push(record);
      }

      const worldPosition = new THREE.Vector3();
      const worldQuaternion = new THREE.Quaternion();
      const worldScale = new THREE.Vector3();
      worldMatrix.decompose(worldPosition, worldQuaternion, worldScale);

      mesh.clear();
      forgeGroup.add(mesh);
      mesh.position.copy(worldPosition);
      mesh.quaternion.copy(worldQuaternion);
      mesh.scale.copy(worldScale).multiplyScalar(0.001);
      mesh.userData.partId = partId;
      mesh.userData.basePosition = worldPosition;
      mesh.userData.baseScale = worldScale;
      mesh.userData.explodeDirection = new THREE.Vector3();

      if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
      record.meshes.push(mesh);
      record.geometries.push(mesh.geometry);

      const materialWasArray = Array.isArray(mesh.material);
      const sourceMaterials = materialWasArray ? mesh.material : [mesh.material];
      const materials = sourceMaterials.map(cloneForgeMaterial);
      mesh.material = materialWasArray ? materials : materials[0];

      for (const material of materials) {
        material.side = THREE.DoubleSide;
        if (!record.data.internal) material.clippingPlanes = [clipPlane];

        const baseOpacity = material.opacity ?? 1;
        const baseTransparent = Boolean(material.transparent);
        const baseEmissive = material.emissive.clone();
        record.materials.push(material);
        record.baseOpacities.push(baseOpacity);
        record.baseTransparents.push(baseTransparent);
        record.baseEmissives.push(baseEmissive);

        if (record.material === null) {
          record.material = material;
          record.baseOpacity = baseOpacity;
          record.baseEmissive = baseEmissive;
          record.color = record.data.color !== undefined
            ? new THREE.Color(record.data.color)
            : material.color.clone();
        }
      }

      const position = mesh.geometry.getAttribute('position');
      if (position) {
        const triangleCount = mesh.geometry.index
          ? mesh.geometry.index.count / 3
          : position.count / 3;
        if (triangleCount <= 60000) {
          const edgeGeometry = new THREE.EdgesGeometry(mesh.geometry, 30);
          const edgeOptions = { color: 0x1b1f24, transparent: true, opacity: 0.35 };
          if (!record.data.internal) edgeOptions.clippingPlanes = [clipPlane];
          const edgeMaterial = new THREE.LineBasicMaterial(edgeOptions);
          const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
          mesh.add(edges);
          record.edgeGeometries.push(edgeGeometry);
          record.edgeMaterials.push(edgeMaterial);
          if (record.edgeGeometry === null) {
            record.edgeGeometry = edgeGeometry;
            record.edgeMaterial = edgeMaterial;
          }
        }
      }

      if (partId !== '_structure') pickMeshes.push(mesh);
    }

    forgeGroup.updateMatrixWorld(true);
    updateBounds();
    applyHighlightStyles();

    for (const arrow of sceneData.arrows || []) apply({ t: 'arrow', ...arrow });
    for (const label of sceneData.labels || []) {
      if (label.part !== '_structure') apply({ t: 'label', ...label });
    }
    for (const beat of sceneData.beats || []) apply({ t: 'beat', ...beat });

    forgeRecords.forEach((record, index) => {
      addTween(280, value => {
        const scale = 0.001 + 0.999 * value;
        for (const mesh of record.meshes) {
          mesh.scale.copy(mesh.userData.baseScale).multiplyScalar(scale);
        }
      }, easeOutBack, null, index * 35);
    });
  }

  function resize() {
    const rect = container.getBoundingClientRect();
    width = Math.max(1, Math.round(rect.width || container.clientWidth || 1));
    height = Math.max(1, Math.round(rect.height || container.clientHeight || 1));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    requestFraming();
  }

  function frame(now) {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    runTweens(now);
    if (autoFrame && framing) {
      camera.position.lerp(desiredCamera, 0.08);
      controls.target.lerp(sceneCenter, 0.08);
      if (camera.position.distanceToSquared(desiredCamera) < 0.00002 &&
          controls.target.distanceToSquared(sceneCenter) < 0.00002) {
        framing = false;
      }
    }
    controls.update();
    updateEmissive(now);
    updateLabels();
    renderer.render(scene, camera);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    running = false;
    cancelAnimationFrame(raf);
    reset();
    resizeObserver.disconnect();
    controls.removeEventListener('start', stopAutomaticCamera);
    canvas.removeEventListener('pointerdown', onPointerDown);
    canvas.removeEventListener('pointermove', onPointerMove);
    canvas.removeEventListener('pointerleave', onPointerLeave);
    canvas.removeEventListener('click', onClick);
    controls.dispose();
    renderer.dispose();
    canvas.remove();
    svg.remove();
    labelsDiv.remove();
  }

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  controls.addEventListener('start', stopAutomaticCamera);
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerleave', onPointerLeave);
  canvas.addEventListener('click', onClick);
  resize();
  reset();
  raf = requestAnimationFrame(frame);

  return {
    reset,
    apply,
    load,
    loadForge,
    setCut,
    setExplode,
    highlight,
    getPart(id) { return parts.get(id)?.data; },
    dispose
  };
}
