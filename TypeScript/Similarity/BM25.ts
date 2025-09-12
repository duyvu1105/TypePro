import { text } from "stream/consumers";
export type NormalizeMethod = 's_over_splusc' | 'one_minus_exp' | 'sigmoid';

export function bm25SimilarityBetweenTwoTexts(
  textA: string,
  textB: string,
  k1: number = 1.5,
  b: number = 0.75,
  // optional normalization options:
  options?: {
    method?: NormalizeMethod; // default 's_over_splusc'
    // for s/(s+c)
    c?: number;
    alpha?: number;
    sigmoidA?: number; // slope
    sigmoidB?: number; // intercept
    returnRawScore?: boolean;
  }
): number {
  function tokenize(text: string): string[] {
    return text
      .toLowerCase()
      .split(/\s+/)
      .filter((tok) => tok.length > 0);
  }

  const tokensA = tokenize(textA);
  const tokensB = tokenize(textB);
  type TFMap = Map<string, number>;
  function buildTF(tokens: string[]): TFMap {
    const map = new Map<string, number>();
    for (const w of tokens) {
      map.set(w, (map.get(w) || 0) + 1);
    }
    return map;
  }

  const tfA = buildTF(tokensA);
  const tfB = buildTF(tokensB);
  const lenA = tokensA.length;
  const lenB = tokensB.length;
  const df: Map<string, number> = new Map();
  function accumulateDF(tfMap: TFMap) {
    for (const term of tfMap.keys()) {
      df.set(term, (df.get(term) || 0) + 1);
    }
  }
  accumulateDF(tfA);
  accumulateDF(tfB);

  const avgdl = (lenA + lenB) / 2;
  function idf(term: string): number {
    const N = 2;
    const n = df.get(term) || 0;
    // same smoothing as original code
    return Math.log((N - n + 0.5) / (n + 0.5) + 1);
  }

  let rawScore = 0;
  for (const [term, freqA] of tfA.entries()) {
    const f_q_D = tfB.get(term) || 0;
    if (f_q_D === 0) {
      continue;
    }
    const termIDF = idf(term);
    const numerator = f_q_D * (k1 + 1);
    const denominator = f_q_D + k1 * (1 - b + (b * lenB) / avgdl);
    rawScore += termIDF * (numerator / denominator);
  }

  // if user explicitly wants raw score, return it
  if (options?.returnRawScore) return rawScore;

  // normalization step
  const method = options?.method ?? 's_over_splusc';
  const eps = 1e-12;

  if (rawScore <= 0) return 0;

  if (method === 's_over_splusc') {
    const c = options?.c ?? 1; // default c = 1
    return rawScore / (rawScore + c + eps);
  } else if (method === 'one_minus_exp') {
    // default alpha = 1 / avgdl (heuristic)
    const alpha = options?.alpha ?? (avgdl > 0 ? 1 / avgdl : 1);
    return 1 - Math.exp(-alpha * rawScore);
  } else if (method === 'sigmoid') {
    // sigmoid: sigma(a * s + b), then remap so that s=0 -> 0, s->+inf -> 1
    const a = options?.sigmoidA ?? (avgdl > 0 ? 1 / avgdl : 1);
    const bSig = options?.sigmoidB ?? 0;
    const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));
    const sVal = sigmoid(a * rawScore + bSig);
    const s0 = sigmoid(bSig); // sigmoid at score=0
    // map [s0, 1) -> [0,1) by (s - s0) / (1 - s0)
    return (sVal - s0) / (1 - s0 + eps);
  } else {
    // fallback to s/(s+c)
    const c = options?.c ?? 1;
    return rawScore / (rawScore + c + eps);
  }
}

function main(){
  let code2 = ``
  let code1 = ``
  console.log(bm25SimilarityBetweenTwoTexts(code1, code2))
}
// main()
  
  