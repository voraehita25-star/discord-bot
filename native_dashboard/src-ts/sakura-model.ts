/**
 * 디스코드 봇 대시보드 — sakura, as an actual 3D model.
 *
 * WHY A MODEL AND NOT A SPRITE
 * ----------------------------
 * Every version of this effect before this one drew a FLAT SVG cut-out and
 * rotated it in 3D with a CSS transform. That is a sprite, and it has a ceiling
 * no amount of art can lift: a flat sheet has one normal over its whole area,
 * so it can only ever be uniformly lit, and shading that does not vary ACROSS a
 * shape is exactly what the eye reads as paper. Worse, a painted gradient turns
 * WITH the shape — the highlight is stuck to the texture instead of staying put
 * under a light, which is the tell even when the drawing is good.
 *
 * So a petal is a real parametric surface, tessellated, with per-fragment
 * normals and lighting:
 *
 *     P(u, v)     u ∈ [0,1] base → tip,  v ∈ [-1,1] left edge → right edge
 *
 * Normals come from the surface itself (finite differences of P in the vertex
 * shader), so they stay correct through every deformation and through the
 * tumble — no hand-authored normal map, nothing to keep in sync.
 *
 * The outline is CARVED IN THE FRAGMENT SHADER rather than modelled: the mesh
 * is a plain (u,v) grid, and the round tip and the signature notch come from an
 * analytic mask on v. That keeps the silhouette resolution-independent and
 * antialiased at any size — at 8px a triangulated notch would be one jagged
 * pixel — and, more usefully, it makes the OUTLINE a per-instance parameter.
 *
 * WHAT VARIES PER PETAL
 * ---------------------
 * Everything that distinguishes one blossom from another, because a field where
 * every petal is the same object with a different rotation reads as wallpaper:
 *
 *     form.neck    how far down the blade the taper runs — a narrow-necked
 *                  petal and a broad-shouldered one are different flowers
 *     form.dome    how round the tip is, from nearly square to a full arc
 *     form.notch   the depth of the cleft, from a hint to a deep split
 *     shape.cup    curl across the width. The one that earns its keep: it puts
 *                  a bright crescent down one flank and shadow on the other,
 *                  and because it is geometry rather than paint that highlight
 *                  SLIDES ACROSS the blade as the petal turns.
 *     shape.twist  the cross-section rotates base → tip, so one end shows its
 *                  face while the other shows its edge
 *     shape.bend   a lengthwise arc
 *     shape.pivot  where the petal turns about — 0 for a loose petal (its own
 *                  middle), -0.52 for a blossom lobe, which puts the BASE at
 *                  the origin so five of them can share a centre
 *     colour       body colour and a separate base tint, which is how the warm
 *                  throat of a flower and the cool rim of a single petal come
 *                  out of one shader
 *
 * WHOLE BLOSSOMS. A flower is five lobe instances sharing one centre, one
 * tumble and one fall — see the emitter in app.ts. The only thing this file has
 * to provide for that is `pivot`, and the fact that a lobe's base tint bleeds
 * into the middle where the five meet, which is the flower's throat.
 *
 * RENDERING. WebGL2, one instanced draw call per depth layer. Two canvases,
 * because the field straddles the UI: the far half renders behind `.app` and is
 * occluded by the panels, the near half passes in front. That occlusion is the
 * parallax cue, so it is worth the second context — the geometry is ~1k
 * triangles and the whole field is under 40 bodies.
 *
 * This module owns NO motion. It is handed a list of instances each frame and
 * draws them; the aerodynamics live in app.ts.
 */

/** One drawn instance for a single frame. Positions are CSS px, top-left origin. */
export interface PetalDraw {
    x: number;
    y: number;
    /** px. Independent axes so each petal has its own aspect — the old sprite
     *  varied its silhouette by mirroring, which a real surface cannot do
     *  without inverting its own normals. */
    sizeX: number;
    sizeY: number;
    /** in-plane rotation, radians */
    angle: number;
    /** unit axis (in the screen plane) the blade tumbles about */
    axisX: number;
    axisY: number;
    /** tumble angle about that axis, radians */
    tumble: number;

    // ---- form -------------------------------------------------------------
    /** curl across the width; sign picks which flank rolls toward the viewer */
    cup: number;
    /** progressive twist, base → tip */
    twist: number;
    /** lengthwise arc */
    bend: number;
    /** local-y shift applied BEFORE rotation: 0 = turn about the middle,
     *  -0.52 = turn about the base (blossom lobes) */
    pivot: number;
    /** taper exponent, ~1.15 (long narrow neck) … ~2.1 (broad shoulders) */
    neck: number;
    /** tip roundness, ~0.12 (nearly square) … ~0.52 (full arc) */
    dome: number;
    /** notch depth, 0 (none) … ~0.17 (deeply cleft) */
    notch: number;

    // ---- colour -----------------------------------------------------------
    /** body colour, 0..1 */
    r: number;
    g: number;
    b: number;
    /** colour at the base — the flower's throat, or a deeper flush on a single
     *  petal. Blended out by ~40% of the blade's length. */
    baseR: number;
    baseG: number;
    baseB: number;
    alpha: number;
    /** 0 far … 1 near — decides which canvas draws it and the draw order */
    depth: number;
}

/** Petals at or above this depth render IN FRONT of the deck. */
const NEAR_CUT = 0.52;

/** Mesh density. The silhouette is shader-carved, so this only has to be fine
 *  enough to resolve the CURVATURE. Normals are per-vertex and interpolated,
 *  so a coarse grid across a strongly cupped blade shows as faceting bands
 *  down its length — 12 across was visibly striped, 20 is not. At ~1k
 *  triangles a petal and under 200 instances this is still nothing. */
const U_SEGS = 26;
const V_SEGS = 20;

/** Floats per instance; must match the attribute layout in the constructor. */
const INSTANCE_FLOATS = 24;

const VERT = `#version 300 es
precision highp float;

in vec2 aUV;              // u ∈ [0,1] base→tip, v ∈ [-1,1] across

in vec2 aPos;             // screen px
in vec2 aScale;           // px, per axis
in float aAngle;          // in-plane rotation, radians
in vec3 aTumble;          // axis.x, axis.y, angle
in vec4 aShape;           // cup, twist, bend, pivot
in vec3 aForm;            // neck, dome, notch
in vec4 aColor;           // body rgb + alpha
in vec3 aBase;            // base/throat rgb

uniform vec2 uViewport;   // CSS px
uniform float uPersp;     // perspective focal distance, px

out vec2 vUV;
out vec3 vNormal;
out vec4 vColor;
out vec3 vBase;
out vec2 vForm;           // dome, notch — the fragment shader carves with these

// ---------------------------------------------------------------------------
// THE MODEL. Everything about the petal's form is these two functions.
// ---------------------------------------------------------------------------
// Half-width profile: zero at the base (it tapers to the point where it met the
// flower), widest near the tip, easing back in as it approaches it. The tip
// itself is not closed here — the round end and its notch are cut out of the
// sheet in the fragment shader, which needs material to cut from.
//
// The neck exponent does more work than it looks. At 2.4 the blade
// is at 44% of full width by a TENTH of its length: the base does not taper, it
// just starts, and the shape reads as a shield. Around 1.2-1.5 the taper is
// spread over the whole lower half, where a real petal's narrow neck lives. It
// varies per petal because that neck is most of what tells two cultivars apart.
float halfWidth(float u, float neck) {
    float grow = pow(1.0 - pow(1.0 - u, neck), 0.85);
    float ease = 1.0 - 0.16 * pow(u, 3.0);
    return grow * ease;
}

vec3 surface(vec2 uv, vec4 shape, float neck) {
    float u = uv.x;
    float v = uv.y;

    float x = v * halfWidth(u, neck) * 0.46;
    // Tip toward -y: screen y runs down, and the notched end should lead. The
    // pivot then decides what the petal turns about — its middle, or its base.
    float y = 0.52 - u + shape.w;

    // Cup — the blade curls along its width. Held flat at the base (where a
    // real petal is stiffened by its attachment) and opening out toward the
    // tip. The -0.34 keeps the mid-line near z=0 so the cup does not also
    // translate the petal.
    float cup = shape.x * smoothstep(0.0, 0.42, u);
    float z = -cup * (v * v - 0.34);

    // Bend — the whole blade arcs back along its length.
    z += shape.z * (u * u - 0.30);

    // A real petal is not a machined surface. One low-frequency ripple across
    // the blade, strongest where it is widest, keeps the highlight from being
    // a single clean band.
    z += cup * 0.10 * sin(v * 3.4) * smoothstep(0.25, 0.85, u);

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
    vBase = aBase;
    vForm = aForm.yz;

    vec3 P = surface(aUV, aShape, aForm.x);
    // Normals from the surface itself. Finite differences rather than an
    // analytic derivative: the deformations compose, and a hand-derived
    // gradient would be one more thing to keep in sync with the model above.
    float e = 0.004;
    vec3 Pu = surface(aUV + vec2(e, 0.0), aShape, aForm.x);
    vec3 Pv = surface(aUV + vec2(0.0, e), aShape, aForm.x);
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
    // a petal passing near the camera foreshortens.
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
in vec3 vBase;
in vec2 vForm;            // dome, notch

uniform vec3 uLight;
/* Ambient floor — the fraction of the body colour a petal keeps when its normal
   faces AWAY from the key light. It has to be per-theme, because the canvas it
   blends onto is the other half of the equation: on the midnight deck a petal is
   source-over-composited onto near-black, so every unit of value the shading
   takes off is a unit the blend takes off again, and a floor tuned for paper
   lands the result on grey. On dawn paper the opposite holds — value is what
   makes a petal DISAPPEAR. See AMBIENT_NIGHT / AMBIENT_DAWN in app.ts. */
uniform float uAmbient;

out vec4 fragColor;

void main() {
    float u = vUV.x;
    float v = vUV.y;

    // ---- silhouette -------------------------------------------------------
    // The sides are the mesh boundary (|v| = 1) because the vertex shader
    // already scaled x by the width profile; only the tip has to be cut. Its
    // outline is a round dome with the sakura notch bitten out of the middle:
    // two shoulders either side of a nick. Both are per-instance, because the
    // depth of that cleft and the roundness of that end are what make one
    // blossom a different flower from the next.
    //
    // The dome follows a circle rather than a parabola — a quadratic that fell
    // only 0.16 over the half-width left the end almost square, which is half
    // of why an early cut looked like a shield.
    //
    // Both edges are feathered by one derivative-width, which is what keeps an
    // 8px petal from having a staircase for a rim.
    float dome  = vForm.x * (1.0 - sqrt(max(0.0, 1.0 - v * v)));
    float notch = vForm.y * exp(-(v * v) / 0.06);
    float uMax = 1.0 - dome - notch;

    float fu = fwidth(u) * 1.2 + 1e-5;
    float fv = fwidth(v) * 1.2 + 1e-5;
    float tipMask  = 1.0 - smoothstep(uMax - fu, uMax, u);
    float sideMask = 1.0 - smoothstep(1.0 - fv, 1.0, abs(v));
    float mask = tipMask * sideMask * smoothstep(0.0, 0.035, u);
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

    // Colour runs warm at the base (the flower's throat, or a deeper flush on a
    // loose petal) and near-white at the rim — real sakura do this, and it is
    // the value shift that makes the tip read as thin.
    vec3 body = mix(vBase, vColor.rgb, smoothstep(0.0, 0.42, u));
    /* 0.40 of the way to PURE WHITE bleached the outer half of every blade: by
       the rim the petal had lost most of its chroma, and what the compositor
       then thinned against the night canvas was a grey. Real sakura go pale at
       the rim, not colourless — 0.24 reads as thin membrane and still arrives
       pink. Lower in both themes: on paper the extra chroma is what separates a
       petal from the page. */
    vec3 tinted = mix(body, vec3(1.0), smoothstep(0.42, 1.0, u) * 0.24);

    // Veins fan from the base. Because v is normalised across the width, a line
    // at constant v already spreads as the blade widens, which is exactly how
    // real venation runs — no extra maths needed. Kept very quiet: at 7-17px
    // this is texture, not pattern.
    float vein = 0.5 + 0.5 * cos(v * 6.5 * 3.14159265);
    float veinMask = smoothstep(0.10, 0.38, u) * (1.0 - smoothstep(0.72, 1.0, u));
    tinted *= 1.0 - 0.06 * vein * veinMask;

    /* Floor + slope always sum to 1.0, so a fully-lit fragment is the body
       colour itself whatever the floor is set to; only the unlit side moves. */
    vec3 lit = tinted * (uAmbient + (1.0 - uAmbient) * lam);
    // A petal is thin enough to be lit from behind, and the underside of a real
    // one glows rather than going to shadow.
    lit += vColor.rgb * trans * (back ? 0.85 : 0.40);
    // A soft sheen where the curl turns the surface into the light, and a rim
    // term where it turns away from the viewer — the two cues that say "curved"
    // rather than "tilted".
    lit += vec3(1.0) * pow(lam, 20.0) * 0.30;
    lit += tinted * pow(1.0 - abs(N.z), 3.0) * 0.22;

    // The last millimetre of a petal is thin enough to glow on its own. This is
    // the one detail that still reads at 8px, because it traces the outline.
    float edge = min(1.0 - abs(v), max(0.0, uMax - u) * 2.2);
    lit += vColor.rgb * (1.0 - smoothstep(0.0, 0.20, edge)) * 0.22;

    // Edge-on is nearly nothing: a membrane seen along its own plane has almost
    // no cross-section. Per-fragment, so the CURLED parts of a petal stay solid
    // while its flat parts thin out — a whole-sprite fade could never do that.
    float facing = abs(N.z);
    float alpha = vColor.a * mask * mix(0.58, 1.0, facing);

    fragColor = vec4(lit, alpha);
}`;

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
    const sh = gl.createShader(type);
    if (!sh) return null;
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
    readonly canvas: HTMLCanvasElement;
    private gl!: WebGL2RenderingContext;
    private program!: WebGLProgram;
    private vao!: WebGLVertexArrayObject;
    private instanceBuf!: WebGLBuffer;
    private indexCount = 0;
    private uViewport: WebGLUniformLocation | null = null;
    private uPersp: WebGLUniformLocation | null = null;
    private uLight: WebGLUniformLocation | null = null;
    private uAmbient: WebGLUniformLocation | null = null;
    private data = new Float32Array(0);
    private capacity = 0;
    ok = false;

    constructor(zIndex: number) {
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
        if (!gl) return;
        this.gl = gl;

        const vs = compile(gl, gl.VERTEX_SHADER, VERT);
        const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
        const prog = gl.createProgram();
        if (!vs || !fs || !prog) return;
        gl.attachShader(prog, vs);
        gl.attachShader(prog, fs);
        gl.linkProgram(prog);
        gl.deleteShader(vs);
        gl.deleteShader(fs);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
            console.warn('[sakura] program link failed:', gl.getProgramInfoLog(prog));
            return;
        }
        this.program = prog;

        // ---- static mesh: a (u,v) grid -----------------------------------
        const verts: number[] = [];
        for (let j = 0; j <= V_SEGS; j++) {
            const v = (j / V_SEGS) * 2 - 1;
            for (let i = 0; i <= U_SEGS; i++) {
                verts.push(i / U_SEGS, v);
            }
        }
        const idx: number[] = [];
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
        if (!vao || !vbo || !ibo || !inst) return;
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
        // Interleaved, 24 floats: pos(2) scale(2) angle(1) tumble(3) shape(4)
        // form(3) color(4) base(3) = 22, padded to 24 for a 96-byte stride.
        gl.bindBuffer(gl.ARRAY_BUFFER, inst);
        const stride = INSTANCE_FLOATS * 4;
        const attrs: Array<[string, number, number]> = [
            ['aPos', 2, 0],
            ['aScale', 2, 2],
            ['aAngle', 1, 4],
            ['aTumble', 3, 5],
            ['aShape', 4, 8],
            ['aForm', 3, 12],
            ['aColor', 4, 15],
            ['aBase', 3, 19],
        ];
        for (const [name, count, offsetFloats] of attrs) {
            const loc = gl.getAttribLocation(prog, name);
            if (loc < 0) continue;
            gl.enableVertexAttribArray(loc);
            gl.vertexAttribPointer(loc, count, gl.FLOAT, false, stride, offsetFloats * 4);
            gl.vertexAttribDivisor(loc, 1);
        }
        gl.bindVertexArray(null);

        this.uViewport = gl.getUniformLocation(prog, 'uViewport');
        this.uPersp = gl.getUniformLocation(prog, 'uPersp');
        this.uLight = gl.getUniformLocation(prog, 'uLight');
        this.uAmbient = gl.getUniformLocation(prog, 'uAmbient');

        gl.disable(gl.DEPTH_TEST);
        gl.enable(gl.BLEND);
        gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

        this.ok = true;
    }

    resize(cssW: number, cssH: number, dpr: number): void {
        if (!this.ok) return;
        const w = Math.max(1, Math.round(cssW * dpr));
        const h = Math.max(1, Math.round(cssH * dpr));
        if (this.canvas.width !== w || this.canvas.height !== h) {
            this.canvas.width = w;
            this.canvas.height = h;
        }
        this.gl.viewport(0, 0, w, h);
    }

    /** `list` must already be sorted back-to-front. */
    draw(
        list: PetalDraw[],
        cssW: number,
        cssH: number,
        light: [number, number, number],
        ambient: number,
    ): void {
        if (!this.ok) return;
        const gl = this.gl;
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        if (list.length === 0) return;

        if (this.capacity < list.length) {
            this.capacity = Math.max(16, list.length * 2);
            this.data = new Float32Array(this.capacity * INSTANCE_FLOATS);
            gl.bindBuffer(gl.ARRAY_BUFFER, this.instanceBuf);
            gl.bufferData(gl.ARRAY_BUFFER, this.data.byteLength, gl.DYNAMIC_DRAW);
        }

        const d = this.data;
        for (let i = 0; i < list.length; i++) {
            const p = list[i];
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
            d[o + 11] = p.pivot;
            d[o + 12] = p.neck;
            d[o + 13] = p.dome;
            d[o + 14] = p.notch;
            d[o + 15] = p.r;
            d[o + 16] = p.g;
            d[o + 17] = p.b;
            d[o + 18] = p.alpha;
            d[o + 19] = p.baseR;
            d[o + 20] = p.baseG;
            d[o + 21] = p.baseB;
        }

        gl.useProgram(this.program);
        gl.bindVertexArray(this.vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.instanceBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, d, 0, list.length * INSTANCE_FLOATS);
        gl.uniform2f(this.uViewport, cssW, cssH);
        gl.uniform1f(this.uPersp, 620);
        gl.uniform3f(this.uLight, light[0], light[1], light[2]);
        gl.uniform1f(this.uAmbient, ambient);
        gl.drawElementsInstanced(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_SHORT, 0, list.length);
        gl.bindVertexArray(null);
    }

    dispose(): void {
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
    private far: PetalLayer;
    private near: PetalLayer;
    private farList: PetalDraw[] = [];
    private nearList: PetalDraw[] = [];
    private cssW = 0;
    private cssH = 0;
    readonly ok: boolean;

    /** Cheap probe so callers can fall back before building anything. */
    static isSupported(): boolean {
        try {
            const c = document.createElement('canvas');
            return !!c.getContext('webgl2');
        } catch {
            return false;
        }
    }

    constructor(container: HTMLElement) {
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

    resize(cssW: number, cssH: number): void {
        if (!this.ok) return;
        this.cssW = cssW;
        this.cssH = cssH;
        // Cap the device ratio: the field is decorative and a 3× buffer on a
        // 4K panel costs far more than it shows.
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        this.far.resize(cssW, cssH, dpr);
        this.near.resize(cssW, cssH, dpr);
    }

    render(list: PetalDraw[], light: [number, number, number], ambient: number): void {
        if (!this.ok) return;
        this.farList.length = 0;
        this.nearList.length = 0;
        for (const p of list) {
            (p.depth > NEAR_CUT ? this.nearList : this.farList).push(p);
        }
        // Back to front within each layer: these are blended, so order decides
        // what shows through what.
        this.farList.sort((a, b) => a.depth - b.depth);
        this.nearList.sort((a, b) => a.depth - b.depth);
        this.far.draw(this.farList, this.cssW, this.cssH, light, ambient);
        this.near.draw(this.nearList, this.cssW, this.cssH, light, ambient);
    }

    dispose(): void {
        this.far.dispose();
        this.near.dispose();
    }
}
