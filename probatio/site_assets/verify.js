/* PROBATIO browser verifier.
 * A second implementation, in JavaScript, of the stabilizer-code and Golomb-ruler
 * checkers, plus SHA-256 and hash-chain auditing. It shares no code with the
 * Python checkers; it implements the same published method so a reader can
 * re-check any certificate without installing anything.
 */
const ProbatioVerify = (() => {
  "use strict";

  // ---------- SHA-256 (WebCrypto when available, small fallback otherwise) ----------
  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);

  function sha256Fallback(bytes) {
    const l = bytes.length, bitLen = l * 8;
    const padded = new Uint8Array(((l + 9 + 63) >> 6) << 6);
    padded.set(bytes); padded[l] = 0x80;
    const dv = new DataView(padded.buffer);
    dv.setUint32(padded.length - 4, bitLen >>> 0);
    dv.setUint32(padded.length - 8, Math.floor(bitLen / 2 ** 32));
    const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
    const W = new Uint32Array(64);
    const r = (x, n) => (x >>> n) | (x << (32 - n));
    for (let o = 0; o < padded.length; o += 64) {
      for (let i = 0; i < 16; i++) W[i] = dv.getUint32(o + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = r(W[i-15], 7) ^ r(W[i-15], 18) ^ (W[i-15] >>> 3);
        const s1 = r(W[i-2], 17) ^ r(W[i-2], 19) ^ (W[i-2] >>> 10);
        W[i] = (W[i-16] + s0 + W[i-7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) >>> 0;
        const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
    }
    return Array.from(H, x => x.toString(16).padStart(8, "0")).join("");
  }

  async function sha256Hex(text) {
    const bytes = new TextEncoder().encode(text);
    const subtle = typeof crypto !== "undefined" && crypto.subtle;
    if (subtle) {
      try {
        const buf = await subtle.digest("SHA-256", bytes);
        return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, "0")).join("");
      } catch (_) { /* fall through */ }
    }
    return sha256Fallback(bytes);
  }

  // ---------- Stabilizer codes ----------
  const BITS = { I: [0, 0], X: [1, 0], Z: [0, 1], Y: [1, 1] };
  const popParity = (x) => { let p = 0; while (x) { x &= x - 1; p ^= 1; } return p; };

  function cyclicShifts(seed) {
    const n = seed.length, out = [];
    for (let i = 0; i < n; i++) out.push(seed.slice(n - i) + seed.slice(0, n - i));
    return out;
  }

  function toXZ(p) {
    let x = 0n, z = 0n;
    for (let i = 0; i < p.length; i++) {
      const [bx, bz] = BITS[p[i]];
      if (bx) x |= 1n << BigInt(i);
      if (bz) z |= 1n << BigInt(i);
    }
    return [x, z];
  }

  function bitLength(v) { return v === 0n ? 0 : v.toString(2).length; }

  function reduce(v, basis) {
    while (v) {
      const piv = bitLength(v) - 1;
      if (basis.has(piv)) v ^= basis.get(piv); else return v;
    }
    return 0n;
  }

  function analyseCode(gens, maxWeight) {
    if (!gens.length) throw new Error("no generators");
    const n = gens[0].length;
    if (n < 1 || n > 30) throw new Error("browser verifier supports 1 ≤ n ≤ 30");
    for (const g of gens) {
      if (g.length !== n) throw new Error("generators have different lengths");
      for (const c of g) if (!(c in BITS)) throw new Error(`invalid character "${c}" in ${g}`);
    }
    const xz = gens.map(toXZ);
    const anti = (a, b) => {
      let v = (a[0] & b[1]) ^ (a[1] & b[0]), p = 0;
      while (v) { v &= v - 1n; p ^= 1; }
      return p;
    };
    for (let i = 0; i < xz.length; i++)
      for (let j = i + 1; j < xz.length; j++)
        if (anti(xz[i], xz[j])) throw new Error(`generators ${i} and ${j} anticommute`);

    const N = BigInt(n);
    const basis = new Map();
    for (const [x, z] of xz) {
      let v = reduce((x << N) | z, basis);
      if (v) {
        const piv = bitLength(v) - 1;
        for (const [p, b] of basis) if ((b >> BigInt(piv)) & 1n) basis.set(p, b ^ v);
        basis.set(piv, v);
      }
    }
    const rank = basis.size, k = n - rank;
    const mask = (1n << N) - 1n;
    const stab = [...basis.values()].map(v => [v >> N, v & mask]);

    const singles = [[1, 0], [0, 1], [1, 1]];
    const syn = [];
    for (let q = 0; q < n; q++) {
      syn.push(singles.map(([bx, bz]) => {
        let s = 0;
        stab.forEach(([gx, gz], j) => {
          const gxq = Number((gx >> BigInt(q)) & 1n), gzq = Number((gz >> BigInt(q)) & 1n);
          if ((bx & gzq) ^ (bz & gxq)) s |= 1 << j;
        });
        return s;
      }));
    }

    const cap = Math.min(maxWeight || n, n);
    let examined = 0;
    const support = [], types = [];
    let found = null;

    function witness() {
      const ch = Array(n).fill("I");
      support.forEach((q, i) => { ch[q] = "XZY"[types[i]]; });
      return ch.join("");
    }
    function isLogical() {
      if (k === 0) return true;
      let x = 0n, z = 0n;
      support.forEach((q, i) => {
        const [bx, bz] = singles[types[i]];
        if (bx) x |= 1n << BigInt(q);
        if (bz) z |= 1n << BigInt(q);
      });
      return reduce((x << N) | z, basis) !== 0n;
    }
    // Enumerate weight-w Paulis: positions in increasing order, each with type X/Z/Y.
    function search(w, start, s) {
      if (support.length === w) {
        examined++;
        if (s === 0 && isLogical()) { found = witness(); return true; }
        return false;
      }
      for (let q = start; q <= n - (w - support.length); q++) {
        support.push(q);
        for (let t = 0; t < 3; t++) {
          types.push(t);
          if (search(w, q + 1, s ^ syn[q][t])) return true;
          types.pop();
        }
        support.pop();
      }
      return false;
    }
    for (let w = 1; w <= cap; w++) {
      if (search(w, 0, 0)) return { n, k, d: w, d_lower: null, min_weight_witness: found, operators_examined: examined };
    }
    return { n, k, d: null, d_lower: cap + 1, min_weight_witness: null, operators_examined: examined };
  }

  function checkStabilizer(problem, cand) {
    const params = problem.params || {}, steps = [];
    const gens = cand.generators;
    if (!Array.isArray(gens)) return { valid: false, reason: "candidate has no generator list", steps };
    if (params.family === "cyclic") {
      const expect = cyclicShifts(cand.seed || "");
      if (expect.length !== gens.length || expect.some((g, i) => g !== gens[i]))
        return { valid: false, reason: "generators are not the cyclic shifts of the seed", steps };
      steps.push(`Family: the ${gens.length} generators are exactly the cyclic shifts of ${cand.seed}`);
    }
    let r;
    try { r = analyseCode(gens, params.max_weight); }
    catch (e) { return { valid: false, reason: e.message, steps }; }
    steps.push(`All ${gens.length} generators pairwise commute`);
    steps.push(`Rank over GF(2) is ${r.n - r.k}, so the code encodes k = ${r.k} logical qubit${r.k === 1 ? "" : "s"}`);
    if (r.d !== null) {
      steps.push(`Searched every Pauli operator of weight below ${r.d}: none is a logical operator`);
      steps.push(`Found a logical operator of weight ${r.d}: ${r.min_weight_witness}, so d = ${r.d}`);
    }
    if (params.n !== undefined && r.n !== params.n) return { valid: false, reason: `n = ${r.n}, problem requires ${params.n}`, score: r, steps };
    if (params.k !== undefined && r.k !== params.k) return { valid: false, reason: `k = ${r.k}, problem requires ${params.k}`, score: r, steps };
    return { valid: true, score: r, steps };
  }

  // ---------- Golomb rulers ----------
  function checkGolomb(problem, cand) {
    const steps = [], marks = cand.marks, want = (problem.params || {}).marks;
    if (!Array.isArray(marks) || !marks.every(Number.isInteger)) return { valid: false, reason: "marks must be integers", steps };
    if (want !== undefined && marks.length !== want) return { valid: false, reason: `${marks.length} marks given, problem requires ${want}`, steps };
    const m = [...marks].sort((a, b) => a - b);
    if (new Set(m).size !== m.length) return { valid: false, reason: "duplicate marks", steps };
    if (m[0] !== 0) return { valid: false, reason: "ruler must start at 0", steps };
    const seen = new Map();
    for (let i = 0; i < m.length; i++) for (let j = i + 1; j < m.length; j++) {
      const d = m[j] - m[i];
      if (seen.has(d)) return { valid: false, reason: `difference ${d} occurs twice (${seen.get(d)} and ${m[j]}−${m[i]})`, steps };
      seen.set(d, `${m[j]}−${m[i]}`);
    }
    steps.push(`${m.length} marks give ${seen.size} pairwise differences`);
    steps.push(`All ${seen.size} differences are distinct`);
    steps.push(`Length is ${m[m.length - 1]}`);
    return { valid: true, score: { marks: m.length, length: m[m.length - 1] }, steps, differences: [...seen.keys()].sort((a, b) => a - b) };
  }

  // ---------- Cap sets in F_3^n ----------
  function checkCapSet(problem, cand) {
    const n = (problem.params || {}).n, pts = cand.points, steps = [];
    if (!Array.isArray(pts) || !pts.length) return { valid: false, reason: "no points", steps };
    for (const p of pts) if (typeof p !== "string" || p.length !== n || /[^012]/.test(p))
      return { valid: false, reason: `point ${p} is not a length-${n} string over 0,1,2`, steps };
    const set = new Set(pts);
    if (set.size !== pts.length) return { valid: false, reason: "duplicate points", steps };
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      let c = "";
      for (let t = 0; t < n; t++) c += String((6 - (+pts[i][t]) - (+pts[j][t])) % 3);
      if (set.has(c)) return { valid: false, reason: `${pts[i]}, ${pts[j]} and ${c} lie on a line`, steps };
    }
    const pairs = pts.length * (pts.length - 1) / 2;
    steps.push(`${pts.length} distinct points in F₃^${n}`);
    steps.push(`For all ${pairs.toLocaleString("en-US")} pairs, the third point on their line is not in the set`);
    steps.push(`Cap set of size ${pts.length}`);
    return { valid: true, score: { n, size: pts.length }, steps };
  }

  // ---------- Binary linear codes ----------
  function checkLinearCode(problem, cand) {
    const params = problem.params || {}, rows = cand.generator, steps = [];
    if (!Array.isArray(rows) || !rows.length) return { valid: false, reason: "no generator rows", steps };
    const n = rows[0].length, k = rows.length;
    if (rows.some(r => r.length !== n || /[^01]/.test(r))) return { valid: false, reason: "rows must be equal-length bit strings", steps };
    if (k > 20 || n > 128) return { valid: false, reason: "browser verifier supports k ≤ 20, n ≤ 128", steps };
    if ((params.n !== undefined && params.n !== n) || (params.k !== undefined && params.k !== k))
      return { valid: false, reason: `code is [${n},${k}], problem requires [${params.n},${params.k}]`, steps };
    const W = Math.ceil(n / 32);
    const vec = rows.map(r => { const v = new Uint32Array(W); for (let j = 0; j < n; j++) if (r[j] === "1") v[j >>> 5] |= (1 << (j & 31)) >>> 0; return v; });
    // rank over GF(2)
    const m = vec.map(v => Uint32Array.from(v));
    let rank = 0;
    for (let c = 0; c < n && rank < k; c++) {
      const w = c >>> 5, b = (1 << (c & 31)) >>> 0;
      let p = -1; for (let i = rank; i < k; i++) if (m[i][w] & b) { p = i; break; }
      if (p < 0) continue;
      [m[p], m[rank]] = [m[rank], m[p]];
      for (let i = 0; i < k; i++) if (i !== rank && (m[i][w] & b)) for (let t = 0; t < W; t++) m[i][t] ^= m[rank][t];
      rank++;
    }
    if (rank !== k) return { valid: false, reason: `rows are dependent: rank ${rank} < k = ${k}`, steps };
    const pc = (x) => { x = x - ((x >>> 1) & 0x55555555); x = (x & 0x33333333) + ((x >>> 2) & 0x33333333); return (((x + (x >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24; };
    const cur = new Uint32Array(W), dist = new Array(n + 1).fill(0);
    const total = 2 ** k;
    for (let g = 1; g < total; g++) {
      let bit = 0; while (!((g >>> bit) & 1)) bit++;      // Gray code: flip one row
      const row = vec[bit];
      let w = 0;
      for (let t = 0; t < W; t++) { cur[t] ^= row[t]; w += pc(cur[t]); }
      dist[w]++;
    }
    let d = 1; while (d <= n && dist[d] === 0) d++;
    steps.push(`Generator matrix ${k} × ${n} has rank ${k} over GF(2), so the code has exactly 2^${k} codewords`);
    steps.push(`Enumerated all ${(total - 1).toLocaleString("en-US")} nonzero codewords (Gray code order)`);
    steps.push(`Minimum weight ${d}, attained by ${dist[d]} codewords: a [${n},${k},${d}] code`);
    return { valid: true, score: { n, k, d, A_d: dist[d] }, steps, distribution: dist };
  }

  // ---------- Point spreading (exact rationals) ----------
  const bgcd = (a, b) => { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b) [a, b] = [b, a % b]; return a; };
  function parseRational(s) {
    if (typeof s !== "string") throw new Error("coordinate must be a string");
    s = s.trim();
    let num, den;
    if (s.includes("/")) { const [a, b] = s.split("/"); num = BigInt(a.trim()); den = BigInt(b.trim()); }
    else {
      const m = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(s);
      if (!m || (m[2] === "" && (m[3] || "") === "")) throw new Error(`bad number ${s}`);
      const frac = m[3] || "";
      num = BigInt((m[1] || "") + (m[2] || "0") + frac); den = 10n ** BigInt(frac.length);
    }
    if (den === 0n) throw new Error("zero denominator");
    if (den < 0n) { num = -num; den = -den; }
    const g = bgcd(num, den) || 1n;
    return [num / g, den / g];
  }
  function checkPointSpread(problem, cand) {
    const want = (problem.params || {}).n, pts = cand.points, steps = [];
    if (!Array.isArray(pts) || pts.some(p => !Array.isArray(p) || p.length !== 2)) return { valid: false, reason: "points must be [x, y] pairs", steps };
    if (want !== undefined && pts.length !== want) return { valid: false, reason: `${pts.length} points given, problem requires ${want}`, steps };
    let P;
    try { P = pts.map(([x, y]) => [parseRational(x), parseRational(y)]); } catch (e) { return { valid: false, reason: e.message, steps }; }
    for (let i = 0; i < P.length; i++) for (const [a, b] of P[i]) if (a < 0n || a > b) return { valid: false, reason: `point ${i} lies outside the unit square`, steps };
    let best = null, pair = [0, 0];
    for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
      const [[xa, xb], [ya, yb]] = P[i], [[xc, xd], [yc, yd]] = P[j];
      const dxn = xa * xd - xc * xb, dxd = xb * xd, dyn = ya * yd - yc * yb, dyd = yb * yd;
      const num = dxn * dxn * dyd * dyd + dyn * dyn * dxd * dxd, den = dxd * dxd * dyd * dyd;
      if (best === null || num * best[1] < best[0] * den) { best = [num, den]; pair = [i, j]; }
    }
    if (!best || best[0] === 0n) return { valid: false, reason: "two points coincide", steps };
    const g = bgcd(best[0], best[1]); const sq = [best[0] / g, best[1] / g];
    const md = Math.sqrt(Number(sq[0]) / Number(sq[1]));
    steps.push(`${P.length} points, all inside [0,1]² (exact rational check)`);
    steps.push(`Smallest distance is between points ${pair[0]} and ${pair[1]}; its square is ${sq[1] === 1n ? sq[0] : sq[0] + "/" + sq[1]} exactly`);
    steps.push(`Minimum distance ${md.toFixed(9)}: equal circles of radius ${(md / (2 * (1 + md))).toFixed(9)} fit in a unit square`);
    return { valid: true, score: { n: P.length, min_distance: Math.round(md * 1e12) / 1e12, min_dist_sq: sq[1] === 1n ? String(sq[0]) : `${sq[0]}/${sq[1]}` }, steps, pair };
  }

  function check(problem, cand) {
    if (problem.checker === "stabilizer_code") return checkStabilizer(problem, cand);
    if (problem.checker === "golomb_ruler") return checkGolomb(problem, cand);
    if (problem.checker === "cap_set") return checkCapSet(problem, cand);
    if (problem.checker === "linear_code") return checkLinearCode(problem, cand);
    if (problem.checker === "point_spread") return checkPointSpread(problem, cand);
    return { valid: false, reason: `no browser checker for ${problem.checker}`, steps: [] };
  }

  // ---------- Step-by-step traces for the live proof view ----------
  // traceCode yields every step of the distance search so a page can animate it.
  // It recomputes everything itself; the final event must agree with analyseCode.
  function binom(n, k) { let r = 1; for (let i = 1; i <= k; i++) r = r * (n - k + i) / i; return Math.round(r); }

  function* traceCode(gens) {
    const n = gens[0].length, m = gens.length, N = BigInt(n);
    const xz = gens.map(toXZ);
    const basis = new Map();
    for (const [x, z] of xz) {
      let v = reduce((x << N) | z, basis);
      if (v) {
        const piv = bitLength(v) - 1;
        for (const [p, b] of basis) if ((b >> BigInt(piv)) & 1n) basis.set(p, b ^ v);
        basis.set(piv, v);
      }
    }
    const k = n - basis.size;
    yield { type: "setup", n, m, k, rank: basis.size };
    // syndrome bits against the ORIGINAL generators g0..g(m-1), as drawn on the page
    const singles = [[1, 0], [0, 1], [1, 1]];
    const syn = [];
    for (let q = 0; q < n; q++) syn.push(singles.map(([bx, bz]) => {
      let s = 0;
      gens.forEach((g, j) => { const [gx, gz] = BITS[g[q]]; if ((bx & gz) ^ (bz & gx)) s |= 1 << j; });
      return s;
    }));
    let examined = 0;
    for (let w = 1; w <= n; w++) {
      const total = binom(n, w) * 3 ** w;
      yield { type: "weight-start", w, total };
      let count = 0;
      const support = [], types = [];
      const stack = [];
      // iterative enumeration (generators cannot yield from nested closures)
      function* rec(start, s) {
        if (support.length === w) {
          count++; examined++;
          let undetected = s === 0, logical = false;
          if (undetected) {
            if (k === 0) logical = true;
            else {
              let x = 0n, z = 0n;
              support.forEach((q, i) => { const [bx, bz] = singles[types[i]]; if (bx) x |= 1n << BigInt(q); if (bz) z |= 1n << BigInt(q); });
              logical = reduce((x << N) | z, basis) !== 0n;
            }
          }
          yield { type: "op", w, support: support.slice(), types: types.slice(), syndrome: s, undetected, logical, count, total, examined };
          return logical;
        }
        for (let q = start; q <= n - (w - support.length); q++) {
          support.push(q);
          for (let t = 0; t < 3; t++) {
            types.push(t);
            if (yield* rec(q + 1, s ^ syn[q][t])) return true;
            types.pop();
          }
          support.pop();
        }
        return false;
      }
      const hit = yield* rec(0, 0);
      if (hit) {
        const ch = Array(n).fill("I");
        support.forEach((q, i) => { ch[q] = "XZY"[types[i]]; });
        yield { type: "found", w, witness: ch.join(""), examined };
        return;
      }
      yield { type: "weight-done", w, count };
    }
  }

  function* traceGolomb(marks) {
    const m = [...marks].sort((a, b) => a - b), seen = new Map();
    yield { type: "setup", marks: m, length: m[m.length - 1] };
    for (let i = 0; i < m.length; i++) for (let j = i + 1; j < m.length; j++) {
      const d = m[j] - m[i], clash = seen.has(d);
      yield { type: "pair", a: m[i], b: m[j], d, clash, prior: seen.get(d) || null, count: seen.size + 1 };
      if (clash) { yield { type: "fail", d }; return; }
      seen.set(d, [m[i], m[j]]);
    }
    yield { type: "done", count: seen.size };
  }


  // Binary symplectic matrix [X | Z] and a step-by-step GF(2) row reduction.
  function symplecticMatrix(gens) {
    const n = gens[0].length;
    return gens.map(g => {
      const row = new Array(2 * n).fill(0);
      for (let i = 0; i < n; i++) { const [bx, bz] = BITS[g[i]]; row[i] = bx; row[n + i] = bz; }
      return row;
    });
  }
  function* traceRank(gens) {
    const M = symplecticMatrix(gens), rows = M.length, cols = M[0].length;
    yield { type: "matrix", M: M.map(r => r.slice()) };
    let r = 0;
    for (let c = 0; c < cols && r < rows; c++) {
      let piv = -1;
      for (let i = r; i < rows; i++) if (M[i][c]) { piv = i; break; }
      if (piv < 0) continue;
      if (piv !== r) { [M[piv], M[r]] = [M[r], M[piv]]; yield { type: "swap", a: r, b: piv, col: c }; }
      yield { type: "pivot", row: r, col: c };
      for (let i = 0; i < rows; i++) if (i !== r && M[i][c]) {
        for (let j = 0; j < cols; j++) M[i][j] ^= M[r][j];
        yield { type: "xor", target: i, source: r, col: c, rowData: M[i].slice() };
      }
      r++;
    }
    yield { type: "done", rank: r, zeroRows: rows - r };
  }
  function commutationMatrix(gens) {
    const xz = gens.map(toXZ);
    return xz.map(a => xz.map(b => {
      let v = (a[0] & b[1]) ^ (a[1] & b[0]), p = 0;
      while (v) { v &= v - 1n; p ^= 1; }
      return p;
    }));
  }

  // ---------- Ledger ----------
  async function auditChain(entries) {
    const problems = [];
    let prev = "0".repeat(64);
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i], core = JSON.parse(e.core);
      if (core.seq !== i) problems.push(`entry ${i}: sequence number out of order`);
      if (core.prev !== prev) problems.push(`entry ${i}: does not link to the previous entry`);
      if (await sha256Hex(e.core) !== e.hash) problems.push(`entry ${i}: content does not match its hash`);
      prev = e.hash;
    }
    return problems;
  }

  return { sha256Hex, sha256Fallback, cyclicShifts, analyseCode, check, checkStabilizer, checkGolomb, auditChain, traceCode, traceGolomb, binom, traceRank, symplecticMatrix, commutationMatrix, checkCapSet, checkLinearCode, checkPointSpread };
})();
if (typeof module !== "undefined") module.exports = ProbatioVerify;
