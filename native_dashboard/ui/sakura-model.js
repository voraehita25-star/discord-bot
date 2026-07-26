/**
 * 디스코드 봇 대시보드 — sakura petal, as an actual 3D model.
 *
 * WHAT CHANGED AND WHY
 * --------------------
 * Every earlier version of this effect drew a FLAT SVG cut-out and rotated it
 * in 3D with a CSS transform. That is a sprite, not a model, and it has a hard
 * ceiling: a flat sheet has one normal over its whole area, so it can only ever
 * be uniformly lit. Shading that does not vary ACROSS a shape is the thing the
 * eye reads as "paper" — no amount of gradient work fixes it, because the
 * gradient is painted into the texture and therefore turns with the petal
 * instead of staying put under a light.
 *
 * So the petal is now a real parametric surface, tessellated, with per-fragment
 * normals and lighting:
 *
 *     P(u, v)     u ∈ [0,1] base → tip,  v ∈ [-1,1] left edge → right edge
 *
 * carrying three independent deformations, each varied per petal so no two are
 * the same object:
 *
 *     CUP    the blade curls along its width, deepening toward the tip. This is
 *            the one that matters most: it is what makes the surface catch
 *            light along a bright crescent down one flank and fall into shadow
 *            on the other, and it moves as the petal turns because it is
 *            geometry, not paint.
 *     TWIST  the cross-section rotates progressively from base to tip, so a
 *            petal shows its face at one end and its edge at the other.
 *     BEND   the whole blade arcs back along its length.
 *
 * Normals come from the surface itself (finite differences of P in the vertex
 * shader), so they stay correct through all three deformations and through the
 * tumble — no hand-authored normal map, nothing to keep in sync.
 *
 * The outline is CARVED IN THE FRAGMENT SHADER rather than modelled: the mesh
 * is a plain (u,v) grid, and the tip's round shoulders and the signature notch
 * come from an analytic mask on v. That keeps the silhouette resolution-
 * independent and antialiased at any size — at 8px the old triangulated tip
 * notch would have been one jagged pixel.
 *
 * RENDERING. WebGL2, one instanced draw call per depth layer. Two canvases,
 * because the field straddles the UI: the far half renders behind `.app` and is
 * occluded by the panels, the near half passes in front. That occlusion is the
 * parallax cue, so it is worth the second context — the geometry is ~500
 * triangles and the whole field is under 40 petals.
 *
 * This module owns NO motion. It is handed a list of petal states each frame
 * and draws them; the aerodynamics live in app.ts exactly as before.
 */
/** Petals at or above this depth render IN FRONT of the deck. */
const NEAR_CUT = 0.52;
/** Mesh density. The silhouette is shader-carved, so this only has to be fine
 *  enough to resolve the CURVATURE. Normals are per-vertex and interpolated,
 *  so a coarse grid across a strongly cupped blade shows as faceting bands
 *  down its length — 12 across was visibly striped, 20 is not. At ~1k
 *  triangles a petal and under 40 petals this is still nothing. */
const U_SEGS = 26;
const V_SEGS = 20;
/** Floats per instance, must match the attribute layout below. */
const INSTANCE_FLOATS = 16;
const VERT = `#version 300 es
precision highp float;

in vec2 aUV;              // u ∈ [0,1] base→tip, v ∈ [-1,1] across

in vec2 aPos;             // screen px
in vec2 aScale;           // px, per axis
in float aAngle;          // in-plane rotation, radians
in vec3 aTumble;          // axis.x, axis.y, angle
in vec3 aShape;           // cup, twist, bend
in vec4 aColor;           // rgb + alpha

uniform vec2 uViewport;   // CSS px
uniform float uPersp;     // perspective focal distance, px

out vec2 vUV;
out vec3 vNormal;
out vec4 vColor;

// ---------------------------------------------------------------------------
// THE MODEL. Everything about the petal's form is this one function.
// ---------------------------------------------------------------------------
// Half-width profile: zero at the base (it tapers to the point where it met the
// flower), widest around u≈0.9, easing back in as it approaches the tip. The
// tip itself is not closed here — the round end and its notch are cut out of
// the sheet in the fragment shader, which needs material to cut from.
//
// The exponents matter more than they look. The first cut used pow(…, 2.4)
// on the growth term, which puts the blade at 44% of full width by a TENTH of
// its length — the base did not taper, it just started, and the result read as
// a shield or a tooth rather than a petal. 1.5 spreads the taper over the whole
// lower half, which is where a real petal's narrow neck lives.
float halfWidth(float u) {
    float grow = pow(1.0 - pow(1.0 - u, 1.5), 0.85);
    float ease = 1.0 - 0.16 * pow(u, 3.0);
    return grow * ease;
}

vec3 surface(vec2 uv, vec3 shape) {
    float u = uv.x;
    float v = uv.y;

    float x = v * halfWidth(u) * 0.46;
    // Tip toward -y: screen y runs down, and the notched end is the one that
    // should lead. The weathervane term in the sim rotates the whole petal to
    // its heading anyway, so this only sets which end that alignment points.
    float y = 0.52 - u;

    // Cup — the blade curls along its width. Held flat at the base (where a
    // real petal is stiffened by its attachment) and opening out toward the
    // tip. The -0.34 keeps the mid-line near z=0 so the cup does not also
    // translate the petal.
    float cup = shape.x * smoothstep(0.0, 0.42, u);
    float z = -cup * (v * v - 0.34);

    // Bend — the whole blade arcs back along its length.
    z += shape.z * (u * u - 0.30);

    // Twist — the cross-section rotates as it runs out to the tip, so one end
    // shows its face while the other shows its edge.
    float t = shape.y * (u - 0.25);
    float c = cos(t);
    float s = sin(t);
    return vec3(x * c - z * s, y, x * s + z * c);
}

vec3 rodrigues(vec3 p, vec3 axis, float c, float s) {
    return p * c + cross(axis, p) * s + axis * dot(axis, p) * (1.0 - c);
}

void main() {
    vUV = aUV;
    vColor = aColor;

    vec3 P = surface(aUV, aShape);
    // Normals from the surface itself. Finite differences rather than an
    // analytic derivative: the three deformations compose, and a hand-derived
    // gradient would be one more thing to keep in sync with the model above.
    float e = 0.004;
    vec3 Pu = surface(aUV + vec2(e, 0.0), aShape);
    vec3 Pv = surface(aUV + vec2(0.0, e), aShape);
    vec3 N = normalize(cross(Pu - P, Pv - P));

    // Tumble about an axis lying in the screen plane.
    vec3 axis = normalize(vec3(aTumble.xy, 0.0));
    float ct = cos(aTumble.z);
    float st = sin(aTumble.z);
    P = rodrigues(P, axis, ct, st);
    N = rodrigues(N, axis, ct, st);

    // In-plane rotation.
    float ca = cos(aAngle);
    float sa = sin(aAngle);
    P.xy = vec2(P.x * ca - P.y * sa, P.x * sa + P.y * ca);
    N.xy = vec2(N.x * ca - N.y * sa, N.x * sa + N.y * ca);

    vNormal = N;

    // To screen px, then a mild perspective divide about the viewport centre so
    // a petal passing near the camera foreshortens the way the CSS
    // perspective() used to.
    vec3 W = vec3(P.xy * aScale + aPos, P.z * (aScale.x + aScale.y) * 0.5);
    float w = uPersp / max(1.0, uPersp - W.z);
    vec2 sp = (W.xy - uViewport * 0.5) * w + uViewport * 0.5;

    vec2 ndc = (sp / uViewport) * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
}`;
const FRAG = `#version 300 es
precision highp float;

in vec2 vUV;
in vec3 vNormal;
in vec4 vColor;

uniform vec3 uLight;

out vec4 fragColor;

void main() {
    float u = vUV.x;
    float v = vUV.y;

    // ---- silhouette -------------------------------------------------------
    // The sides are the mesh boundary (|v| = 1) because the vertex shader
    // already scaled x by the width profile; only the tip has to be cut. Its
    // outline is a round dome with the sakura notch bitten out of the middle:
    // two shoulders either side of a nick about a tenth of the length deep.
    // Both edges are feathered by one derivative-width, which is what keeps an
    // 8px petal from having a staircase for a rim.
    //
    // The dome follows a circle rather than a parabola — a quadratic that only
    // fell 0.16 over the full half-width left the end almost square, and a flat
    // top is the other half of why the first cut looked like a shield.
    float dome  = 0.40 * (1.0 - sqrt(max(0.0, 1.0 - v * v)));
    float notch = 0.10 * exp(-(v * v) / 0.06);
    float uMax = 1.0 - dome - notch;

    float fu = fwidth(u) * 1.2 + 1e-5;
    float fv = fwidth(v) * 1.2 + 1e-5;
    float mask = (1.0 - smoothstep(uMax - fu, uMax, u))
               * (1.0 - smoothstep(1.0 - fv, 1.0, abs(v)))
               * smoothstep(0.0, 0.035, u);
    if (mask <= 0.001) discard;

    // ---- lighting ---------------------------------------------------------
    // Shade whichever face is toward the viewer. A petal is a membrane: you see
    // its underside as often as its face, and the underside is not black — it
    // is lit by what comes THROUGH the blade, which is dimmer, warmer and more
    // saturated than the front. Modelling that transmitted term is most of what
    // separates a translucent petal from a painted chip of plastic.
    vec3 N = normalize(vNormal);
    bool back = N.z < 0.0;
    vec3 n = back ? -N : N;

    float lam = max(dot(n, uLight), 0.0);
    float trans = pow(max(dot(-n, uLight), 0.0), 1.7);

    // Near-white at the rim, holding colour at the base — real sakura do this,
    // and it is the value shift that makes the tip read as thin.
    vec3 tinted = mix(vColor.rgb, vec3(1.0), smoothstep(0.40, 1.0, u) * 0.42);

    // Ambient carries more than a physical renderer would give it. A shaded
    // surface averages a good deal darker than the flat sprite this replaced,
    // and at 7-17px over a near-black deck the difference between "subtle" and
    // "invisible" is small — the field has to still read as blossom.
    vec3 lit = tinted * (0.62 + 0.58 * lam);
    // A petal is thin enough to be lit from behind, and the underside of a real
    // one glows rather than going to shadow. Weighted up on the back face,
    // which is the half the first cut rendered as near-black leather.
    lit += vColor.rgb * trans * (back ? 0.85 : 0.40);
    // A soft sheen where the curl turns the surface into the light, and a rim
    // term where it turns away from the viewer — the two cues that say "curved"
    // rather than "tilted".
    lit += vec3(1.0) * pow(lam, 20.0) * 0.30;
    lit += tinted * pow(1.0 - abs(N.z), 3.0) * 0.22;

    // Edge-on is nearly nothing: a membrane seen along its own plane has almost
    // no cross-section. Per-fragment, so the CURLED parts of a petal stay solid
    // while its flat parts thin out — a whole-sprite fade could never do that.
    float facing = abs(N.z);
    float alpha = vColor.a * mask * mix(0.58, 1.0, facing);

    fragColor = vec4(lit, alpha);
}`;
function compile(gl, type, src) {
    const sh = gl.createShader(type);
    if (!sh)
        return null;
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.warn('[sakura] shader compile failed:', gl.getShaderInfoLog(sh));
        gl.deleteShader(sh);
        return null;
    }
    return sh;
}
/**
 * One canvas + context + program + buffers. Instantiated twice (far / near) so
 * the field can straddle the UI.
 */
class PetalLayer {
    canvas;
    gl;
    program;
    vao;
    instanceBuf;
    indexCount;
    uViewport;
    uPersp;
    uLight;
    data;
    capacity = 0;
    ok = false;
    constructor(zIndex) {
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'sakura-gl';
        this.canvas.setAttribute('aria-hidden', 'true');
        this.canvas.style.cssText =
            `position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:${zIndex}`;
        const gl = this.canvas.getContext('webgl2', {
            alpha: true,
            antialias: true,
            premultipliedAlpha: false,
            depth: false,
            stencil: false,
            powerPreference: 'low-power',
        });
        if (!gl) {
            // Caller checks .ok; these are only assigned to satisfy the type.
            this.gl = null;
            this.program = null;
            this.vao = null;
            this.instanceBuf = null;
            this.indexCount = 0;
            this.uViewport = null;
            this.uPersp = null;
            this.uLight = null;
            this.data = new Float32Array(0);
            return;
        }
        this.gl = gl;
        const vs = compile(gl, gl.VERTEX_SHADER, VERT);
        const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
        const prog = gl.createProgram();
        if (!vs || !fs || !prog) {
            this.program = null;
            this.vao = null;
            this.instanceBuf = null;
            this.indexCount = 0;
            this.uViewport = null;
            this.uPersp = null;
            this.uLight = null;
            this.data = new Float32Array(0);
            return;
        }
        gl.attachShader(prog, vs);
        gl.attachShader(prog, fs);
        gl.linkProgram(prog);
        gl.deleteShader(vs);
        gl.deleteShader(fs);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
            console.warn('[sakura] program link failed:', gl.getProgramInfoLog(prog));
            this.program = null;
            this.vao = null;
            this.instanceBuf = null;
            this.indexCount = 0;
            this.uViewport = null;
            this.uPersp = null;
            this.uLight = null;
            this.data = new Float32Array(0);
            return;
        }
        this.program = prog;
        // ---- static mesh: a (u,v) grid -----------------------------------
        const verts = [];
        for (let j = 0; j <= V_SEGS; j++) {
            const v = (j / V_SEGS) * 2 - 1;
            for (let i = 0; i <= U_SEGS; i++) {
                verts.push(i / U_SEGS, v);
            }
        }
        const idx = [];
        const row = U_SEGS + 1;
        for (let j = 0; j < V_SEGS; j++) {
            for (let i = 0; i < U_SEGS; i++) {
                const a = j * row + i;
                idx.push(a, a + 1, a + row, a + 1, a + row + 1, a + row);
            }
        }
        this.indexCount = idx.length;
        const vao = gl.createVertexArray();
        const vbo = gl.createBuffer();
        const ibo = gl.createBuffer();
        const inst = gl.createBuffer();
        if (!vao || !vbo || !ibo || !inst) {
            this.vao = null;
            this.instanceBuf = null;
            this.uViewport = null;
            this.uPersp = null;
            this.uLight = null;
            this.data = new Float32Array(0);
            return;
        }
        this.vao = vao;
        this.instanceBuf = inst;
        gl.bindVertexArray(vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);
        const aUV = gl.getAttribLocation(prog, 'aUV');
        gl.enableVertexAttribArray(aUV);
        gl.vertexAttribPointer(aUV, 2, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
        gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW);
        // ---- per-instance attributes --------------------------------------
        // Interleaved, 16 floats: pos(2) scale(2) angle(1) tumble(3) shape(3)
        // color(4) = 15, padded to 16 so the stride stays a tidy 64 bytes.
        gl.bindBuffer(gl.ARRAY_BUFFER, inst);
        const stride = INSTANCE_FLOATS * 4;
        const attrs = [
            ['aPos', 2, 0],
            ['aScale', 2, 2],
            ['aAngle', 1, 4],
            ['aTumble', 3, 5],
            ['aShape', 3, 8],
            ['aColor', 4, 11],
        ];
        for (const [name, count, offsetFloats] of attrs) {
            const loc = gl.getAttribLocation(prog, name);
            if (loc < 0)
                continue;
            gl.enableVertexAttribArray(loc);
            gl.vertexAttribPointer(loc, count, gl.FLOAT, false, stride, offsetFloats * 4);
            gl.vertexAttribDivisor(loc, 1);
        }
        gl.bindVertexArray(null);
        this.uViewport = gl.getUniformLocation(prog, 'uViewport');
        this.uPersp = gl.getUniformLocation(prog, 'uPersp');
        this.uLight = gl.getUniformLocation(prog, 'uLight');
        gl.disable(gl.DEPTH_TEST);
        gl.enable(gl.BLEND);
        gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        this.data = new Float32Array(0);
        this.ok = true;
    }
    resize(cssW, cssH, dpr) {
        if (!this.ok)
            return;
        const w = Math.max(1, Math.round(cssW * dpr));
        const h = Math.max(1, Math.round(cssH * dpr));
        if (this.canvas.width !== w || this.canvas.height !== h) {
            this.canvas.width = w;
            this.canvas.height = h;
        }
        this.gl.viewport(0, 0, w, h);
    }
    /** `petals` must already be sorted back-to-front. */
    draw(petals, cssW, cssH, light) {
        if (!this.ok)
            return;
        const gl = this.gl;
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        if (petals.length === 0)
            return;
        if (this.capacity < petals.length) {
            this.capacity = Math.max(8, petals.length * 2);
            this.data = new Float32Array(this.capacity * INSTANCE_FLOATS);
            gl.bindBuffer(gl.ARRAY_BUFFER, this.instanceBuf);
            gl.bufferData(gl.ARRAY_BUFFER, this.data.byteLength, gl.DYNAMIC_DRAW);
        }
        const d = this.data;
        for (let i = 0; i < petals.length; i++) {
            const p = petals[i];
            const o = i * INSTANCE_FLOATS;
            d[o] = p.x;
            d[o + 1] = p.y;
            d[o + 2] = p.sizeX;
            d[o + 3] = p.sizeY;
            d[o + 4] = p.angle;
            d[o + 5] = p.axisX;
            d[o + 6] = p.axisY;
            d[o + 7] = p.tumble;
            d[o + 8] = p.cup;
            d[o + 9] = p.twist;
            d[o + 10] = p.bend;
            d[o + 11] = p.r;
            d[o + 12] = p.g;
            d[o + 13] = p.b;
            d[o + 14] = p.alpha;
        }
        gl.useProgram(this.program);
        gl.bindVertexArray(this.vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.instanceBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, d, 0, petals.length * INSTANCE_FLOATS);
        gl.uniform2f(this.uViewport, cssW, cssH);
        gl.uniform1f(this.uPersp, 620);
        gl.uniform3f(this.uLight, light[0], light[1], light[2]);
        gl.drawElementsInstanced(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_SHORT, 0, petals.length);
        gl.bindVertexArray(null);
    }
    dispose() {
        if (this.ok) {
            this.gl.getExtension('WEBGL_lose_context')?.loseContext();
        }
        this.canvas.remove();
        this.ok = false;
    }
}
/**
 * The field's renderer: two layers, and the sort/partition that feeds them.
 */
export class SakuraRenderer {
    far;
    near;
    farList = [];
    nearList = [];
    cssW = 0;
    cssH = 0;
    ok;
    /** Cheap probe so callers can fall back before building anything. */
    static isSupported() {
        try {
            const c = document.createElement('canvas');
            return !!c.getContext('webgl2');
        }
        catch {
            return false;
        }
    }
    constructor(container) {
        // z-index 0 sits behind `.app` (z-index 1) and is occluded by the
        // panels; z-index 2 passes in front. That occlusion IS the parallax.
        this.far = new PetalLayer(0);
        this.near = new PetalLayer(2);
        this.ok = this.far.ok && this.near.ok;
        if (!this.ok) {
            this.far.dispose();
            this.near.dispose();
            return;
        }
        container.appendChild(this.far.canvas);
        container.appendChild(this.near.canvas);
    }
    resize(cssW, cssH) {
        if (!this.ok)
            return;
        this.cssW = cssW;
        this.cssH = cssH;
        // Cap the device ratio: the field is decorative and a 3× buffer on a
        // 4K panel costs far more than it shows.
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        this.far.resize(cssW, cssH, dpr);
        this.near.resize(cssW, cssH, dpr);
    }
    render(petals, light) {
        if (!this.ok)
            return;
        this.farList.length = 0;
        this.nearList.length = 0;
        for (const p of petals) {
            (p.depth > NEAR_CUT ? this.nearList : this.farList).push(p);
        }
        // Back to front within each layer: these are blended, so order decides
        // what shows through what.
        this.farList.sort((a, b) => a.depth - b.depth);
        this.nearList.sort((a, b) => a.depth - b.depth);
        this.far.draw(this.farList, this.cssW, this.cssH, light);
        this.near.draw(this.nearList, this.cssW, this.cssH, light);
    }
    dispose() {
        this.far.dispose();
        this.near.dispose();
    }
}
//# sourceMappingURL=sakura-model.js.map