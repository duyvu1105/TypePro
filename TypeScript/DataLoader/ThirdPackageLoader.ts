import {ThirdPackageInfo,minimumSimilarityStandard,minimumSimilarityStandard2 } from "../Util/typedefined"
import {  CalculationBM25Sim, wordSimilarity } from "../Similarity/SimilarityCalculation"
import * as fs from 'fs-extra';
import { join } from 'path';
import { Project, SyntaxKind } from 'ts-morph';


export interface APIFunction { name: string; signature: string; docs?: string; }
export interface APIType { name: string; kind: 'class' | 'interface' | 'type'; fields?: any[]; docs?: string; }
export interface PackageAPI { package: string; version: string; api: Array<APIFunction | APIType>; }

/**
 * Data structures matching the JSON summary format:
 */

export class ThirdPackageLoader {
    private packageDataList: ThirdPackageInfo[] = [];
    private filePath: string = "";
    private filePackageList: any[] = [];
    private importInfos: any = [];
    // private dataPath = '../KnowledgeBase/npm_api_summary.json';
    private dataPath = join(__dirname, '..', 'KnowledgeBase', 'npm_api_summary.json');
    constructor(importInfo: any) {
        this.importInfos = importInfo;
        this.loadPackageList()
    }
    public parseSummary(packageList: string[]): ThirdPackageInfo[] {
        let jsonPath = this.dataPath;
        if (!fs.pathExistsSync(jsonPath)) {
            throw new Error(`JSON file not found: ${jsonPath}`);
        }
        const data = fs.readJsonSync(jsonPath) as ThirdPackageInfo[];
        let fixData: ThirdPackageInfo[] = []
        for (const i of data) {
            if (packageList.includes(i.packageName)) {
                fixData.push(i)
            }
        }
        return fixData;
    }
    private loadPackageList() {
        // const project = new Project()
        // const sourceFile = project.addSourceFileAtPath(this.filePath);
        var importInfos = this.importInfos;
        const imports = importInfos.map((importDecl: any) => ({
            modulePath: importDecl.getModuleSpecifier().getLiteralValue(),
            defaultImport: importDecl.getDefaultImport()?.getText(),
            namedImports: importDecl.getNamedImports().map((spec: any) => ({
                name: spec.getName(),
                alias: spec.getAliasNode()?.getText()
            })),
            namespaceImport: importDecl.getNamespaceImport()?.getText(),
            isTypeOnly: importDecl.isTypeOnly(),
            rawText: importDecl.getText() 
        }));
        this.filePackageList = imports;
        let packageList: string[] = [];
        packageList.push("typescript-stdlib")
        imports.forEach((item: any) => {
            packageList.push(item.modulePath);
        })
        let temp = this.parseSummary(packageList)
        this.packageDataList = temp;
    }
    public getFunctionByName(functionName: string): string[] {
        let ans: string[] = []
        if(functionName.includes(".")){
            functionName = functionName.split(".").slice(-1)[0];
        }
        for (const data of this.packageDataList) {
            for (const fd of data.functions) {
                if (fd.name == functionName && !ans.includes(fd.signature)) {
                    ans.push(fd.signature)
                }
            }
        }
        return ans;
    }
    public getRecomendType(CODE: string, justSim1:boolean = false, justSim2:boolean = false) {
        let res:string[] = [];
        if(CODE.startsWith("{")){
            for (const p of this.packageDataList) {
                for (const c of p.classes){
                    let score2 = CalculationBM25Sim(CODE, c.signature)
                    if(score2>minimumSimilarityStandard2&&!c.signature.includes("enum")){
                        res.push(c.signature)
                    }
                }
                for (const c of p.interfaces){
                    let score2 = CalculationBM25Sim(CODE, c.signature)
                    if(score2>minimumSimilarityStandard2&&!c.signature.includes("enum")){
                        res.push(c.signature)
                    }
                }
                for (const c of p.types){
                    let score2 = CalculationBM25Sim(CODE, c.code)
                    if(score2>minimumSimilarityStandard2){
                        res.push(c.code)
                    }
                }
            }
        }
        else{ 
            for (const p of this.packageDataList) {
                for (const c of p.classes){
                    let score2 = wordSimilarity(CODE.toLowerCase(), c.name.toLowerCase())
                    if(score2>minimumSimilarityStandard&&!c.signature.includes("enum")){
                        res.push(c.signature)
                    }
                }
                for (const c of p.interfaces){
                    let score2 = wordSimilarity(CODE.toLowerCase(), c.name.toLowerCase())
                    if(score2>minimumSimilarityStandard&&!c.signature.includes("enum")){
                        res.push(c.signature)
                    }
                }
                for (const c of p.types){
                    let score2 = wordSimilarity(CODE.toLowerCase(), c.name.toLowerCase())
                    if(score2>minimumSimilarityStandard){
                        res.push(c.code)
                    }
                }
            }
        }
        return res
    }
}
export function loadParsedSummary(jsonPath: string): ThirdPackageInfo[] {
    if (!fs.pathExistsSync(jsonPath)) {
        throw new Error(`JSON file not found: ${jsonPath}`);
    }
    const data = fs.readJsonSync(jsonPath) as ThirdPackageInfo[];
    return data;
}
function main() {
    let filePath = ""
    const project = new Project()
    const sourceFile = project.addSourceFileAtPath(filePath);
    let importInfos = sourceFile.getDescendantsOfKind(SyntaxKind.ImportDeclaration);
    let tpLoader = new ThirdPackageLoader(importInfos);
    let fRes = tpLoader.getFunctionByName("")
    console.log(fRes)
}
// main()