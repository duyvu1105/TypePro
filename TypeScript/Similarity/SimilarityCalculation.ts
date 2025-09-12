// import * as stringSimilarity from 'string-similarity';
import test from "node:test";
import { bm25SimilarityBetweenTwoTexts } from "./BM25"
import stringSimilarity from "string-similarity";
export function codeSimilarity(
  codeA: string,
  codeB: string,
  method: 'levenshtein' | 'jaccard' | 'tfidf' | 'combined' = 'combined'
): number {
  const preprocess = (code: string): string[] => {
    return code
      .toLowerCase()
      .replace(/(\/\/.*|\/\*[\s\S]*?\*\/)/g, '')
      .match(/[a-z_$][a-z0-9_$]*|[^\s]/gi) || []
        .filter(token => !/[{}()$$$$;,]/.test(token)); 
  };

  switch (method) {
    case 'levenshtein':
      const maxLen = Math.max(codeA.length, codeB.length);
      if (maxLen === 0) return 1;
      const matrix = Array.from({ length: codeA.length + 1 }, (_, i) =>
        Array.from({ length: codeB.length + 1 }, (_, j) =>
          i === 0 ? j : j === 0 ? i : 0
        )
      );
      for (let i = 1; i <= codeA.length; i++) {
        for (let j = 1; j <= codeB.length; j++) {
          const cost = codeA[i - 1] === codeB[j - 1] ? 0 : 1;
          matrix[i][j] = Math.min(
            matrix[i - 1][j] + 1,
            matrix[i][j - 1] + 1,
            matrix[i - 1][j - 1] + cost
          );
        }
      }
      return 1 - matrix[codeA.length][codeB.length] / maxLen;

    case 'jaccard':
      const setA = new Set(preprocess(codeA));
      const setB = new Set(preprocess(codeB));
      const intersection = [...setA].filter(x => setB.has(x)).length;
      const union = setA.size + setB.size - intersection;
      return union === 0 ? 0 : intersection / union;

    case 'tfidf':
      const buildVector = (tokens: string[], vocab: string[]): number[] =>
        vocab.map(word => tokens.filter(t => t === word).length);

      const tokensA = preprocess(codeA);
      const tokensB = preprocess(codeB);
      const vocab = [...new Set([...tokensA, ...tokensB])];
      const vecA = buildVector(tokensA, vocab);
      const vecB = buildVector(tokensB, vocab);

      const dotProduct = vecA.reduce((sum, a, i) => sum + a * vecB[i], 0);
      const normA = Math.sqrt(vecA.reduce((sum, a) => sum + a ** 2, 0));
      const normB = Math.sqrt(vecB.reduce((sum, b) => sum + b ** 2, 0));
      return (dotProduct / (normA * normB || 1) + 1) / 2; 

    default:
      const weights = { levenshtein: 0.4, jaccard: 0.3, tfidf: 0.3 };
      return [
        codeSimilarity(codeA, codeB, 'levenshtein') * weights.levenshtein,
        codeSimilarity(codeA, codeB, 'jaccard') * weights.jaccard,
        codeSimilarity(codeA, codeB, 'tfidf') * weights.tfidf
      ].reduce((a, b) => a + b);
  }
}



export function wordSimilarity(a: string, b: string): number {
  let ans = stringSimilarity.compareTwoStrings(a.toLowerCase(), b.toLowerCase());
  return ans
}

export function CalculationSeqSim(text1: string, text2: string) {
  return 0.1
}

export function CalculationBM25Sim(text1: string, text2: string) {
  text1 = text1.replace(/\?/g,"")
  text2 = text2.replace(/\?/g,"")
  text1 = text1.replace(/\r\n/g,"")
  text2 = text2.replace(/\r\n/g,"")
  text1 = text1.replace(/\(/g,"( ").replace(/\)/g," )")
  text2 = text2.replace(/\(/g,"( ").replace(/\)/g," )")
  text1 = text1.replace(/\</g,"< ").replace(/\>/g," >")
  text2 = text2.replace(/\</g,"< ").replace(/\>/g," >")
  text1 = text1.replace("{","")
  text2 = text2.replace("}","")
  text1 = text1.replace("(","")
  text2 = text2.replace(")","")
  let bm25Ans = bm25SimilarityBetweenTwoTexts(text1, text2)
  if(text1.length>5*text2.length||text2.length>5*text1.length){ 
    bm25Ans =bm25Ans/5
  }
  return bm25Ans
}
function main()
{
  let code2 = ``
  let code1 = ``
}


