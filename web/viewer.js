import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const MAX_PART_LABELS = 9;

// Cross-section "cap": back faces of clipped, opaque materials are painted a flat, faintly hatched
// colour while the cut is active, so the section reads like a technical cutaway instead of a hollow shell.
const CAP_GLSL = `
  if (!gl_FrontFacing && optoCapOn > 0.5 && gl_FragColor.a > 0.97) {
    float optoHatch = step(0.62, fract((gl_FragCoord.x + gl_FragCoord.y) / 9.0));
    gl_FragColor.rgb = optoCapColor * (1.0 - 0.13 * optoHatch);
  }
`;

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
  // the user grabbed the model: stop spinning so it stays where they put it
  controls.addEventListener('start', () => { controls.autoRotate = false; });

  renderer.toneMappingExposure = 1.05;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const roomEnvironment = new RoomEnvironment();
  const environmentTarget = pmrem.fromScene(roomEnvironment, 0.04);
  roomEnvironment.traverse(object => {
    if (object.geometry) object.geometry.dispose();
    if (object.material) object.material.dispose();
  });
  pmrem.dispose();
  scene.environment = environmentTarget.texture;
  scene.environmentIntensity = 0.42;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a4250, 0.85));
  const key = new THREE.DirectionalLight(0xfff6ea, 2.7);
  key.position.set(5, 8, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9fc6ff, 0.8);
  fill.position.set(-6, 2, -4);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xcfe3ff, 0.6);
  rim.position.set(-2, 5, -8);
  scene.add(rim);
  const capUniform = { value: 0 };

  function installCap(material) {
    if (!material || material.userData.optoCap || !('color' in material)) return;
    material.userData.optoCap = true;
    const capColor = new THREE.Color();
    material.userData.optoCapColor = capColor;
    refreshCapColor(material);
    material.onBeforeCompile = shader => {
      shader.uniforms.optoCapOn = capUniform;
      shader.uniforms.optoCapColor = { value: capColor };
      shader.fragmentShader = 'uniform float optoCapOn;\nuniform vec3 optoCapColor;\n' +
        shader.fragmentShader.replace('#include <dithering_fragment>', '#include <dithering_fragment>\n' + CAP_GLSL);
    };
    material.needsUpdate = true;
  }

  function refreshCapColor(material) {
    const capColor = material.userData.optoCapColor;
    if (!capColor) return;
    // Output (sRGB) space: a darkened, slightly desaturated version of the surface colour.
    const base = material.color.clone().convertLinearToSRGB();
    const slate = new THREE.Color(0.17, 0.19, 0.23);
    capColor.copy(base).multiplyScalar(0.58).lerp(slate, 0.3);
  }

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
  const anchorVector = new THREE.Vector3();
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
  let fitDistance = 12;
  let snapCamera = false;
  let labelsDirty = true;
  const screenRect = { x0: 0, y0: 0, x1: 0, y1: 0 };

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
    if (!data.internal) installCap(material);
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

  function baseMatrixOf(mesh, target = tempMatrix) {
    return target.compose(mesh.userData.basePosition, mesh.quaternion, mesh.userData.baseScale || unitScale);
  }

  // Bounds are cached per part (from geometry bounding boxes and the meshes' rest transforms) so the
  // render loop never walks heavy geometry. Recomputed only when parts change or explode/cut changes.
  function updateBounds() {
    const bounds = new THREE.Box3();
    let any = false;
    for (const record of parts.values()) {
      record.baseBox = record.baseBox || new THREE.Box3();
      record.baseBox.makeEmpty();
      for (const mesh of record.meshes) {
        const geometry = mesh.geometry;
        if (!geometry.boundingBox) geometry.computeBoundingBox();
        if (!geometry.boundingBox || geometry.boundingBox.isEmpty()) continue;
        tempBox.copy(geometry.boundingBox).applyMatrix4(baseMatrixOf(mesh));
        record.baseBox.union(tempBox);
        any = true;
      }
      bounds.union(record.baseBox);
    }
    if (!any) bounds.set(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
    sceneBox.copy(bounds);
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    sceneCenter.copy(sphere.center);
    sceneRadius = Math.max(0.5, sphere.radius);

    let totalVertices = 0;
    for (const record of parts.values()) {
      for (const mesh of record.meshes) totalVertices += mesh.geometry.getAttribute('position')?.count || 0;
    }
    const sampleStride = Math.max(1, Math.ceil(totalVertices / 3000));
    for (const record of parts.values()) {
      for (const mesh of record.meshes) {
        const geometry = mesh.geometry;
        if (!geometry.boundingBox) continue;
        const center = geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(baseMatrixOf(mesh));
        const direction = center.sub(sceneCenter);
        if (direction.lengthSq() < 1e-10) {
          direction.copy(mesh.userData.basePosition).sub(sceneCenter);
        }
        if (direction.lengthSq() < 1e-10) direction.set(0, 0, 0);
        else direction.normalize();
        mesh.userData.explodeDirection.copy(direction);
      }
      if (record.anchorDirty !== false || record.sampleStride !== sampleStride) computeAnchors(record, sampleStride);
    }
    if (!cutOn && !cutTween) clipPlane.constant = unclippedConstant();
    applyExplode(explodeValue);
    requestFraming();
  }

  // A label anchor is a real vertex of the part (closest to the part's box centre), so the leader dot
  // sits on the surface instead of in the middle of a hollow shell. A second anchor restricted to the
  // kept side of the cross-section is used while the cut is on.
  function computeAnchors(record, sampleStride = 1) {
    const center = record.baseBox && !record.baseBox.isEmpty()
      ? record.baseBox.getCenter(new THREE.Vector3()) : new THREE.Vector3();
    const keepNormal = clipPlane.normal;
    const margin = 0.01 * sceneRadius;
    let best = null, bestDistance = Infinity, keep = null, keepDistance = Infinity;
    const matrix = new THREE.Matrix4();
    const point = new THREE.Vector3();
    const local = new THREE.Vector3();
    const total = record.meshes.reduce((sum, mesh) => sum + (mesh.geometry.getAttribute('position')?.count || 0), 0);
    const stride = Math.max(1, Math.ceil(total / 6000));
    // Sparse vertex subsample (local coordinates) per mesh: used for tight framing and for the
    // label obstacle region, at a fixed budget for the whole model.
    record.samples = record.meshes.map(mesh => {
      const position = mesh.geometry.getAttribute('position');
      if (!position) return new Float32Array(0);
      const offset = 0;
      const count = Math.max(0, Math.ceil((position.count - offset) / sampleStride));
      const out = new Float32Array(count * 3);
      for (let i = 0, v = offset; v < position.count; v += sampleStride, i++) {
        out[i * 3] = position.getX(v); out[i * 3 + 1] = position.getY(v); out[i * 3 + 2] = position.getZ(v);
      }
      return out;
    });
    record.sampleStride = sampleStride;
    record.meshes.forEach((mesh, index) => {
      const position = mesh.geometry.getAttribute('position');
      if (!position) return;
      baseMatrixOf(mesh, matrix);
      for (let v = 0; v < position.count; v += stride) {
        local.fromBufferAttribute(position, v);
        point.copy(local).applyMatrix4(matrix);
        const distance = point.distanceToSquared(center);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = { mesh: index, local: local.clone() };
        }
        if (distance < keepDistance && keepNormal.dot(point) >= margin) {
          keepDistance = distance;
          keep = { mesh: index, local: local.clone() };
        }
      }
    });
    record.anchor = best;
    record.anchorKeep = keep || best;
    record.anchorDirty = false;
  }

  // World-space sample points (rest pose, plus the exploded pose when exploding) used to fit the camera.
  function framingPoints() {
    const out = [];
    const reach = Math.max(explodeTarget, explodeValue);
    const distances = reach > 0 ? [0, reach * 0.55 * sceneRadius] : [0];
    const matrix = new THREE.Matrix4();
    const point = new THREE.Vector3();
    for (const record of parts.values()) {
      record.meshes.forEach((mesh, index) => {
        const samples = record.samples?.[index];
        if (!samples || !samples.length) return;
        for (const distance of distances) {
          tempVector.copy(mesh.userData.basePosition).addScaledVector(mesh.userData.explodeDirection, distance);
          matrix.compose(tempVector, mesh.quaternion, mesh.userData.baseScale || unitScale);
          for (let i = 0; i < samples.length; i += 3) {
            point.set(samples[i], samples[i + 1], samples[i + 2]).applyMatrix4(matrix);
            out.push(point.x, point.y, point.z);
          }
        }
      });
    }
    if (!out.length) {
      for (let i = 0; i < 8; i++) {
        out.push(i & 1 ? sceneBox.max.x : sceneBox.min.x, i & 2 ? sceneBox.max.y : sceneBox.min.y, i & 4 ? sceneBox.max.z : sceneBox.min.z);
      }
    }
    return out;
  }

  function safeArea() {
    const x0 = Math.min(safe.left, width * 0.4), x1 = Math.max(x0 + 40, width - Math.min(safe.right, width * 0.4));
    const y0 = Math.min(safe.top, height * 0.45), y1 = Math.max(y0 + 40, height - Math.min(safe.bottom, height * 0.45));
    return { x0, y0, x1, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w: x1 - x0, h: y1 - y0 };
  }

  // The projection centre is moved to the middle of the safe area (inside the insets), so orbiting
  // keeps the model centred in the visible region rather than in the raw canvas.
  function applyViewOffset() {
    const area = safeArea();
    camera.setViewOffset(width, height, width / 2 - area.cx, height / 2 - area.cy, width, height);
  }

  function elevationOf(direction) {
    return Math.asin(THREE.MathUtils.clamp(direction.y / (direction.length() || 1), -0.99, 0.99));
  }

  function directionAt(azimuth, elevation, target = new THREE.Vector3()) {
    return target.set(Math.cos(elevation) * Math.sin(azimuth), Math.sin(elevation), Math.cos(elevation) * Math.cos(azimuth));
  }

  function requestFraming() {
    if (!autoFrame || parts.size === 0) return;
    // Opto: fit the scene's bounding box as seen from the camera direction (not its bounding sphere) inside
    // the safe area minus a margin reserved for labels. Auto-rotate orbits about +Y, so the fit is the worst
    // case over all azimuths: the model can never rotate out of frame.
    const area = safeArea();
    const padX = THREE.MathUtils.clamp(area.w * 0.09, 36, 120);
    const padY = THREE.MathUtils.clamp(area.h * 0.075, 18, 56);
    const halfW = Math.max(30, area.w / 2 - padX);
    const halfH = Math.max(30, area.h / 2 - padY);
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const tanH = tanV * (width / height);
    const kx = (width / 2) / (tanH * halfW);
    const ky = (height / 2) / (tanV * halfH);
    const points = framingPoints();
    const center = sceneCenter;
    const elevation = elevationOf(cameraDirection);
    const baseAzimuth = Math.atan2(cameraDirection.x, cameraDirection.z);
    const samples = controls.autoRotate ? 24 : 1;
    const dir = new THREE.Vector3();
    const right = new THREE.Vector3();
    const camUp = new THREE.Vector3();
    const worldUp = new THREE.Vector3(0, 1, 0);
    const corner = new THREE.Vector3();
    let distance = 0.5;
    for (let k = 0; k < samples; k++) {
      directionAt(baseAzimuth + (k * Math.PI * 2) / samples, elevation, dir);
      right.crossVectors(worldUp, dir).normalize();
      camUp.crossVectors(dir, right).normalize();
      for (let i = 0; i < points.length; i += 3) {
        corner.set(points[i] - center.x, points[i + 1] - center.y, points[i + 2] - center.z);
        const depth = corner.dot(dir);
        distance = Math.max(distance,
          depth + Math.abs(corner.dot(right)) * kx,
          depth + Math.abs(corner.dot(camUp)) * ky);
      }
    }
    fitDistance = Math.min(distance, camera.far * 0.45);
    desiredCamera.copy(cameraDirection).normalize().multiplyScalar(fitDistance).add(center);
    framing = true;
  }

  // Jump straight to the framed pose (used once a whole scene is loaded, so headless snapshots and slow
  // devices never catch the camera mid-flight).
  function snapToFrame() {
    if (!autoFrame || parts.size === 0) return;
    requestFraming();
    camera.position.copy(desiredCamera);
    controls.target.copy(sceneCenter);
    controls.update();
    framing = false;
    labelsDirty = true;
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
        position: 'absolute', transform: 'translate(-50%, -50%)', visibility: 'hidden',
        fontSize: '10.5px', fontWeight: '500', padding: '1px 6px', borderWidth: '1px',
        borderRadius: '9px', boxShadow: 'none', letterSpacing: '0.01em',
        background: 'rgba(10,14,20,.62)', borderColor: `#${color.getHexString()}88`
      });
      labelsDiv.appendChild(chip);
    }
    arrows.push({ group, material, geometries: [shaft.geometry, head.geometry], chip,
      text: data.label || '', midpoint: from.clone().lerp(to, 0.6), w: 0, h: 0, pos: null });
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
    labels.push({ part: data.part, chip, line, circle, order: labels.length, w: 0, h: 0, pos: null });
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
    if (autoFrame) requestFraming();
    if (explodeTween) tweens.delete(explodeTween);
    const start = explodeValue;
    explodeTween = addTween(500, value => {
      applyExplode(THREE.MathUtils.lerp(start, explodeTarget, value));
    }, smooth, () => {
      explodeTween = null;
      if (autoFrame) requestFraming();
    });
  }

  function setCut(on) {
    if (disposed) return;
    on = Boolean(on);
    if (on === cutOn && !cutTween) return;
    if (cutTween) tweens.delete(cutTween);
    cutOn = on;
    labelsDirty = true;
    if (on) capUniform.value = 1;
    const target = on ? 0 : unclippedConstant();
    if (on) clipPlane.constant = unclippedConstant();
    const start = clipPlane.constant;
    cutTween = addTween(600, value => {
      clipPlane.constant = THREE.MathUtils.lerp(start, target, value);
    }, smooth, () => {
      clipPlane.constant = target;
      cutTween = null;
      if (!cutOn) capUniform.value = 0;
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

  function overlaps(a, b, gap = 6) {
    return a.x < b.x + b.w + gap && a.x + a.w + gap > b.x &&
      a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;
  }

  function segmentsCross(a, b, c, d) {
    const cross = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
    const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
  }

  function hideLabel(label) {
    label.chip.style.visibility = 'hidden';
    label.line.style.display = 'none';
    label.circle.style.display = 'none';
    label.pos = null;
  }

  function measure(item) {
    if (!item.w || !item.h) {
      item.w = item.chip.offsetWidth || 0;
      item.h = item.chip.offsetHeight || 0;
    }
    return { w: item.w || 80, h: item.h || 24 };
  }

  // Screen-space bounding rectangle of the whole model, from the cached vertex subsample.
  const screenMatrix = new THREE.Matrix4();
  const viewProjection = new THREE.Matrix4();
  const samplePoint = new THREE.Vector3();
  function modelScreenRect() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    for (const record of parts.values()) {
      if (!record.samples) continue;
      record.meshes.forEach((mesh, index) => {
        const samples = record.samples[index];
        if (!samples || !samples.length || mesh.scale.x < 1e-6) return;
        screenMatrix.multiplyMatrices(viewProjection, mesh.matrixWorld);
        for (let i = 0; i < samples.length; i += 3) {
          samplePoint.set(samples[i], samples[i + 1], samples[i + 2]).applyMatrix4(screenMatrix);
          if (samplePoint.z > 1 || samplePoint.z < -1) continue;
          const x = (samplePoint.x * 0.5 + 0.5) * width, y = (-samplePoint.y * 0.5 + 0.5) * height;
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
      });
    }
    if (!isFinite(x0)) return null;
    return { x0, y0, x1, y1 };
  }

  function anchorScreen(record) {
    const anchor = (cutOn || cutTween) && !record.data.internal ? record.anchorKeep : record.anchor;
    if (!anchor) return null;
    const mesh = record.meshes[anchor.mesh];
    if (!mesh) return null;
    return project(anchorVector.copy(anchor.local).applyMatrix4(mesh.matrixWorld));
  }

  function leaderEnd(rect, anchor) {
    return {
      x: Math.max(rect.x, Math.min(anchor.x, rect.x + rect.w)),
      y: Math.max(rect.y, Math.min(anchor.y, rect.y + rect.h))
    };
  }

  // Swap pairs of chips whose leader lines cross, when the swap is legal (fits, no new overlaps).
  function untangle(entries, placed, fits) {
    for (let pass = 0; pass < 2; pass++) {
      let changed = false;
      for (let i = 0; i < entries.length; i++) {
        for (let j = i + 1; j < entries.length; j++) {
          const a = entries[i], b = entries[j];
          if (!segmentsCross(a.anchor, a.best.end, b.anchor, b.best.end)) continue;
          const ra = { x: b.best.cx - a.w / 2, y: b.best.cy - a.h / 2, w: a.w, h: a.h };
          const rb = { x: a.best.cx - b.w / 2, y: a.best.cy - b.h / 2, w: b.w, h: b.h };
          if (!fits(ra) || !fits(rb) || overlaps(ra, rb, 6)) continue;
          const clash = rect => placed.some(other => other !== a.best.placedRect && other !== b.best.placedRect &&
            other.dot !== a.label && other.dot !== b.label && overlaps(rect, other, other.dot ? 2 : 6));
          if (clash(ra) || clash(rb)) continue;
          const ea = leaderEnd(ra, a.anchor), eb = leaderEnd(rb, b.anchor);
          if (segmentsCross(a.anchor, ea, b.anchor, eb)) continue;
          Object.assign(a.best.placedRect, ra);
          Object.assign(b.best.placedRect, rb);
          const acx = a.best.cx, acy = a.best.cy;
          a.best = { ...a.best, rect: ra, cx: b.best.cx, cy: b.best.cy, end: ea };
          b.best = { ...b.best, rect: rb, cx: acx, cy: acy, end: eb };
          changed = true;
        }
      }
      if (!changed) break;
    }
  }

  // Boundary labelling: chips sit just outside the model's projected bounding rectangle, on the side
  // facing their anchor, chosen greedily by cost (leader length + direction + leader crossings +
  // hysteresis). Falls back to free space near the anchor when there is no room outside.
  function updateLabels() {
    camera.updateMatrixWorld();
    const area = safeArea();
    const active = highlightIds !== null;
    const model = modelScreenRect();
    const gap = 12;
    const placed = [];
    const leaders = [];
    const entries = [];

    for (const label of labels) {
      const record = parts.get(label.part);
      const screen = record && record.meshes.length ? anchorScreen(record) : null;
      if (!screen || screen.behind || !isFinite(screen.x) || !isFinite(screen.y)) {
        hideLabel(label);
        continue;
      }
      const focused = active && highlightIds.has(label.part);
      entries.push({ label, anchor: screen, focused, ...measure(label) });
    }
    entries.sort((a, b) => (b.focused - a.focused) || (a.label.order - b.label.order));
    for (const entry of entries.slice(MAX_PART_LABELS)) hideLabel(entry.label);
    const shown = entries.slice(0, MAX_PART_LABELS);
    for (const entry of shown) {
      placed.push({ x: entry.anchor.x - 4, y: entry.anchor.y - 4, w: 8, h: 8, dot: entry.label });
    }

    const center = model ? { x: (model.x0 + model.x1) / 2, y: (model.y0 + model.y1) / 2 } : { x: area.cx, y: area.cy };
    // Process around the model by angle (starting at the top), focused labels first.
    shown.forEach(entry => {
      entry.angle = Math.atan2(entry.anchor.y - center.y, entry.anchor.x - center.x);
    });
    shown.sort((a, b) => (b.focused - a.focused) || (((a.angle + Math.PI * 2.5) % (Math.PI * 2)) - ((b.angle + Math.PI * 2.5) % (Math.PI * 2))));

    const fits = rect => rect.x >= area.x0 && rect.y >= area.y0 && rect.x + rect.w <= area.x1 && rect.y + rect.h <= area.y1;

    for (const entry of shown) {
      const { w, h, anchor, label } = entry;
      let ax = anchor.x - center.x, ay = anchor.y - center.y;
      const al = Math.hypot(ax, ay);
      if (al > 1e-3) { ax /= al; ay /= al; } else { ax = 0; ay = -1; }
      let best = null;
      let bestCost = Infinity;
      const consider = (cx, cy, penalty) => {
        const rect = { x: cx - w / 2, y: cy - h / 2, w, h };
        if (!fits(rect)) return;
        const lx = Math.max(rect.x, Math.min(anchor.x, rect.x + rect.w));
        const ly = Math.max(rect.y, Math.min(anchor.y, rect.y + rect.h));
        let cost = penalty + Math.hypot(lx - anchor.x, ly - anchor.y);
        let dx = cx - center.x, dy = cy - center.y;
        const dl = Math.hypot(dx, dy) || 1;
        cost += (1 - (dx * ax + dy * ay) / dl) * 70;
        if (label.pos) cost += 0.25 * Math.hypot(cx - label.pos.x, cy - label.pos.y);
        if (cost >= bestCost) return;
        for (const other of placed) {
          if (other.dot === label) continue;
          if (overlaps(rect, other, other.dot ? 2 : 6)) return;
        }
        const end = { x: lx, y: ly };
        for (const leader of leaders) {
          if (segmentsCross(anchor, end, leader.a, leader.b)) cost += 90;
        }
        if (cost < bestCost) { bestCost = cost; best = { rect, cx, cy, end }; }
      };

      if (model) {
        for (const ring of [0, 24, 52, 90]) {
          const x0 = model.x0 - gap - w / 2 - ring, x1 = model.x1 + gap + w / 2 + ring;
          const y0 = model.y0 - gap - h / 2 - ring, y1 = model.y1 + gap + h / 2 + ring;
          const penalty = ring * 1.2;
          const step = 9;
          for (let x = x0; x <= x1; x += step) { consider(x, y0, penalty); consider(x, y1, penalty); }
          for (let y = y0; y <= y1; y += step) { consider(x0, y, penalty); consider(x1, y, penalty); }
          if (best) break;
        }
      }
      if (!best) {
        // No room outside the silhouette: free space around the anchor, heavily penalised.
        for (const radius of [34, 60, 95, 140]) {
          for (let k = 0; k < 16; k++) {
            const t = (k / 16) * Math.PI * 2;
            consider(anchor.x + Math.cos(t) * (radius + w / 2), anchor.y + Math.sin(t) * (radius + h / 2), 300 + radius);
          }
          if (best) break;
        }
      }
      if (!best) { hideLabel(label); continue; }
      placed.push({ ...best.rect, owner: label });
      leaders.push({ a: anchor, b: best.end, entry });
      entry.best = best;
      best.placedRect = placed[placed.length - 1];
    }

    untangle(shown.filter(entry => entry.best), placed, fits);

    for (const entry of shown) {
      const { label, anchor, best } = entry;
      if (!best) continue;
      // Light smoothing so chips glide instead of popping while the camera orbits.
      if (label.pos && !labelsDirty && Math.hypot(best.cx - label.pos.x, best.cy - label.pos.y) < 220) {
        label.pos.x += (best.cx - label.pos.x) * 0.35;
        label.pos.y += (best.cy - label.pos.y) * 0.35;
      } else {
        label.pos = { x: best.cx, y: best.cy };
      }
      const rx = label.pos.x - entry.w / 2, ry = label.pos.y - entry.h / 2;
      label.chip.style.visibility = 'visible';
      label.line.style.display = '';
      label.circle.style.display = '';
      const opacity = active && !highlightIds.has(label.part) ? 0.25 : 1;
      label.chip.style.opacity = String(opacity);
      label.line.style.opacity = String(opacity);
      label.circle.style.opacity = String(opacity);
      label.chip.style.left = `${label.pos.x}px`;
      label.chip.style.top = `${label.pos.y}px`;
      const endX = Math.max(rx, Math.min(anchor.x, rx + entry.w));
      const endY = Math.max(ry, Math.min(anchor.y, ry + entry.h));
      label.line.setAttribute('x1', anchor.x);
      label.line.setAttribute('y1', anchor.y);
      label.line.setAttribute('x2', endX);
      label.line.setAttribute('y2', endY);
      label.circle.setAttribute('cx', anchor.x);
      label.circle.setAttribute('cy', anchor.y);
    }

    // Arrow chips: lowest priority, small, never on top of part labels; duplicates shown once.
    const shownText = new Set();
    const arrowOpacity = Math.max(0, 1 - explodeValue);
    for (const arrow of arrows) {
      if (!arrow.chip) continue;
      const hide = () => { arrow.chip.style.visibility = 'hidden'; arrow.pos = null; };
      if (arrowOpacity <= 0.001 || shownText.has(arrow.text)) { hide(); continue; }
      const screen = project(arrow.midpoint);
      if (screen.behind || !isFinite(screen.x)) { hide(); continue; }
      const { w, h } = measure(arrow);
      let spot = null;
      for (const [ox, oy] of [[0, 0], [0, -16], [0, 16], [w * 0.6, 0], [-w * 0.6, 0], [0, -30], [0, 30]]) {
        const rect = { x: screen.x + ox - w / 2, y: screen.y + oy - h / 2, w, h };
        if (!fits(rect)) continue;
        if (placed.some(other => overlaps(rect, other, other.dot ? 1 : 5))) continue;
        spot = rect;
        break;
      }
      if (!spot) { hide(); continue; }
      placed.push(spot);
      shownText.add(arrow.text);
      arrow.chip.style.visibility = 'visible';
      arrow.chip.style.opacity = String(arrowOpacity * (active ? 0.45 : 0.9));
      arrow.chip.style.left = `${spot.x + w / 2}px`;
      arrow.chip.style.top = `${spot.y + h / 2}px`;
    }
    labelsDirty = false;
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
    capUniform.value = 0;
    labelsDirty = true;
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
    snapToFrame();
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
        if (!record.data.internal) {
          material.clippingPlanes = [clipPlane];
          installCap(material);
        }

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

    snapToFrame();
    forgeRecords.forEach((record, index) => {
      const last = index === forgeRecords.length - 1;
      addTween(280, value => {
        const scale = 0.001 + 0.999 * value;
        for (const mesh of record.meshes) {
          mesh.scale.copy(mesh.userData.baseScale).multiplyScalar(scale);
        }
      }, easeOutBack, last ? () => {
        // Re-frame once the scale-in settles (bounds are rest-pose based, so this is a cheap no-op
        // unless something changed meanwhile, e.g. a resize during load).
        if (!disposed) requestFraming();
      } : null, index * 35);
    });
  }

  function resize() {
    const rect = container.getBoundingClientRect();
    width = Math.max(1, Math.round(rect.width || container.clientWidth || 1));
    height = Math.max(1, Math.round(rect.height || container.clientHeight || 1));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    applyViewOffset();
    camera.updateProjectionMatrix();
    for (const item of [...labels, ...arrows]) { item.w = 0; item.h = 0; }
    labelsDirty = true;
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
      // Ease towards the fitted distance/elevation while keeping the current (auto-rotating) azimuth.
      tempVector.copy(camera.position).sub(controls.target);
      const azimuth = Math.atan2(tempVector.x, tempVector.z);
      directionAt(azimuth, elevationOf(cameraDirection), desiredCamera).multiplyScalar(fitDistance).add(sceneCenter);
      camera.position.lerp(desiredCamera, 0.08);
      controls.target.lerp(sceneCenter, 0.08);
      if (camera.position.distanceToSquared(desiredCamera) < 0.00002 &&
          controls.target.distanceToSquared(sceneCenter) < 0.00002) {
        framing = false;
      }
    }
    controls.update();
    updateEmissive(now);
    scene.updateMatrixWorld();
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
    environmentTarget.dispose();
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
