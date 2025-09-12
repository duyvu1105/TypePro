
import { SDKClasses, SDKFunctions, projectDefined, ImportInfo, minimumSimilarityStandard, minimumSimilarityStandard2 } from "../Util/typedefined"
import fs from 'fs';
import { areFilePathsEqual, getAfterFirstEqual } from "../Util/tools"
import { CalculationBM25Sim, wordSimilarity } from "../Similarity/SimilarityCalculation"
import path from 'path';
import { join } from "path"

var ignoreFunction: string[] = []
export class ProjectDataLoader {
    private projectFunctionDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectFunctions.json')
    private projectClassDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectClasses.json')
    choiceNumber = 5;
    MinimumThreshold = 0.5;
    functions: SDKFunctions[] = [];
    classes: SDKClasses[] = [];
    projectFunctions: projectDefined[] = [];
    projectClasses: projectDefined[] = [];

    constructor() {
        this.projectFunctions = this.parseProjectDefined(this.projectFunctionDefineds)
        this.projectClasses = this.parseProjectDefined(this.projectClassDefineds)
        ignoreFunction.forEach(item => { this.delFunction(item) })
    }
    public reLoadProjectData() {
        this.projectFunctions = this.parseProjectDefined(this.projectFunctionDefineds)
        this.projectClasses = this.parseProjectDefined(this.projectClassDefineds)
    }
    parseSDKFunction(): SDKFunctions[] {
        let filePath = "./data/sdkFunctions_new.json"
        const absolutePath = path.resolve(__dirname, filePath);

        try {
            const rawData = fs.readFileSync(absolutePath, 'utf-8');
            const parsedData: SDKFunctions[] = JSON.parse(rawData);
            if (!Array.isArray(parsedData)) {
                throw new Error("Invalid JSON format: expected array");
            }

            parsedData.forEach(item => {
                if (!('name' in item) || typeof item.name !== 'string') {
                    throw new Error("Missing required field: name");
                }
            });

            return parsedData;
        } catch (error) {
            console.error(`Error parsing JSON at ${absolutePath}:`);
            if (error instanceof SyntaxError) {
                throw new Error("Invalid JSON syntax");
            }
            throw error;
        }
    }
    parseSDKClass(): SDKClasses[] {
        let filePath = "./data/sdkClasses_new.json"
        const absolutePath = path.resolve(__dirname, filePath);

        try {
            const rawData = fs.readFileSync(absolutePath, 'utf-8');
            const parsedData: SDKClasses[] = JSON.parse(rawData);

            if (!Array.isArray(parsedData)) {
                throw new Error("Invalid JSON format: expected array");
            }

            parsedData.forEach(item => {
                if (!('name' in item) || typeof item.name !== 'string') {
                    throw new Error("Missing required field: name");
                }

            });

            return parsedData;
        } catch (error) {
            console.error(`Error parsing JSON at ${absolutePath}:`);
            if (error instanceof SyntaxError) {
                throw new Error("Invalid JSON syntax");
            }
            throw error;
        }
    }
    parseProjectDefined(filePath: string): projectDefined[] {

        const absolutePath = path.resolve(__dirname, filePath);
        try {

            const rawData = fs.readFileSync(absolutePath, 'utf-8');
            const parsedData: projectDefined[] = JSON.parse(rawData);

            if (!Array.isArray(parsedData)) {
                throw new Error("Invalid JSON format: expected array");
            }

            return parsedData;
        } catch (error) {
            console.error(`Error parsing JSON at ${absolutePath}:`);
            if (error instanceof SyntaxError) {
                throw new Error("Invalid JSON syntax");
            }
            throw error;
        }
    }

    public targetFileData(filePath: string, generationCode: string) {
        let findAns = new Set();
        for (const c of this.classes) {
            if (c.file == filePath) {
                //console.log(`${c.name}:${codeSimilarity(totalCode, c.srcCode)}`)
                //let score = CalculationSeqSim(totalCode, c.srcCode)
                let score2 = CalculationBM25Sim(generationCode, c.srcCode)
                if (!c.srcCode.includes("enum") && score2 > minimumSimilarityStandard2) {
                    findAns.add(c.srcCode)
                }
            }
        }
        return findAns
    }

    public parseImportInfo(data: any[], totalCode: string) {
        const imports = data.map(importDecl => ({
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

        let toFindNames = new Set();
        for (const f of imports) {
            for (const i of f.namedImports) {
                toFindNames.add(i.name);
            }
            if (f.defaultImport != undefined) {
                toFindNames.add(f.defaultImport);
            }
        }
        interface possibilityData {
            code: string,
            Score: number,
        }
        let tempList: possibilityData[] = []

        for (const c of this.classes) {
            if (toFindNames.has(c.namespace) || c.isComponent) {
                //console.log(`${c.name}:${codeSimilarity(totalCode, c.srcCode)}`)
                //let score = CalculationSeqSim(totalCode, c.srcCode)
                let score2 = CalculationBM25Sim(totalCode, c.srcCode)
                if (!c.srcCode.includes("enum") && score2 > minimumSimilarityStandard2) {
                    tempList.push({
                        code: c.srcCode,
                        Score: score2
                    })
                }
            }
        }
        for (const c of this.projectClasses) {
            let score = CalculationBM25Sim(totalCode, c.sourceCode)
            if (!c.sourceCode.includes("enum") && score > minimumSimilarityStandard2) {
                tempList.push({
                    code: c.sourceCode,
                    Score: score
                })
            }
        }
        tempList.sort((a, b) => b.Score - a.Score)
        let ans = tempList.slice(0, Math.min(this.choiceNumber, tempList.length))
        if (ans.length > 0 && ans[0].Score < this.MinimumThreshold) {
            ans = []
        }

        return ans
    }

    public findFunction(funNode: any) {

        var res = new Set();
        let expression = funNode.getExpression();
        let funcName = expression.getText();
        if (funcName.includes(".")) {
            let tempData = funcName.split(".")
            let name1 = tempData[1]
            let name2 = tempData[0]

            let res1 = this.functions.find(n => n.namespace == name2 && n.name == name1);
            if (res1) {
                res.add(res1.srcCode);
            }
            let res2 = this.functions.find(n => n.name === name1 && n.class === name2);
            if (res2) {
                res.add(res2.srcCode)
            }
        }
        else {
            // todo
        }
        return res;
    }

    analysizerImportInfo(importInfos: any[]) {
        const imports: ImportInfo[] = [];

        importInfos.forEach((decl: any) => {
            const moduleSpecifier = decl.getModuleSpecifierValue();
            const namedImports = decl.getNamedImports();
            const defaultImport = decl.getDefaultImport();
            const namespaceImport = decl.getNamespaceImport();
            const startLine = decl.getStartLineNumber();

            if (namedImports.length > 0) {
                const names = namedImports.map((i: any) => i.getName());
                const aliases = namedImports.map((i: any) => i.getAliasNode()?.getText() ?? null);
                imports.push({
                    type: "import",
                    module: moduleSpecifier,
                    names,
                    aliases,
                    startLine,
                });
            }

            if (defaultImport) {
                imports.push({
                    type: "import",
                    module: moduleSpecifier,
                    names: ["default"],
                    aliases: [defaultImport.getText()],
                    isDefault: true,
                    startLine,
                });
            }

            if (namespaceImport) {
                imports.push({
                    type: "import",
                    module: moduleSpecifier,
                    names: ["*"],
                    aliases: [namespaceImport.getText()],
                    isNamespace: true,
                    startLine,
                });
            }
        });

        return imports;
    }
    public findFileClass(varName: string, filePath: string, importInfos: any) {
        for (const cls of this.projectClasses) {
            if (cls.filePath != filePath && cls.filePath.replace("\\", "/") != filePath && cls.filePath.replace("/", "\\") != filePath) {
                continue;
            }
            if (varName.toLowerCase() == cls.name.toLowerCase() || wordSimilarity(varName.toLowerCase(), cls.name.toLowerCase()) > minimumSimilarityStandard) {
                return cls.sourceCode
            }
        }
        let data = this.analysizerImportInfo(importInfos)
        let may_be_names: any[] = []
        for (const i of data) {
            if (i.names[0] == "default") {
                may_be_names = [...may_be_names, ...i.aliases]
            }
            else {
                may_be_names = [...may_be_names, ...i.names]
            }
        }
        for (const cls of this.projectClasses) {
            if (!may_be_names.includes(cls.name)) {
                continue;
            }
            if (varName.toLowerCase() == cls.name.toLowerCase() || wordSimilarity(varName.toLowerCase(), cls.name.toLowerCase()) > minimumSimilarityStandard) {
                return cls.sourceCode
            }
        }
        return ""
    }

    public findWordSimilarity(CODE: string, predict: string) {

        let ans: string[] = []
        for (const pc of this.projectClasses) {

            let wordSim = wordSimilarity(predict.toLowerCase(), pc.name.toLowerCase())

            let srcCode = pc.sourceCode;
            if (srcCode.endsWith(";")) {
                srcCode = srcCode.slice(0, -1)
            }
            if (srcCode.startsWith("type ") || srcCode.startsWith("export type")) {
                srcCode = getAfterFirstEqual(srcCode)
            }
            if (wordSim == 1) {
                ans.push(pc.sourceCode)
                return ans
            }
            else if (wordSim > minimumSimilarityStandard) {
                ans.push(pc.sourceCode)
            }
            else if (CalculationBM25Sim(predict, srcCode) > minimumSimilarityStandard2) {
                ans.push(pc.sourceCode)
            }
        }
        return ans
    }
    public findProjectDefined(funcNode: any) {
        var res = new Set();
        let expression = funcNode.getExpression();
        let funcName = expression.getText();
        let isGetFuncdefined = false;
        for (const f of this.projectFunctions) {
            if (f.name == funcName) {
                res.add(f.sourceCode)
                isGetFuncdefined = true;
            }
        }
        if (!isGetFuncdefined && funcName.includes(".")) {
            let sFuncname = funcName.split(".");
            for (const f of this.projectFunctions) {
                if (f.name.includes(".")) {
                    let temp = f.name.split(".")[1];
                    if (temp == sFuncname[sFuncname.length - 1]) {
                        res.add(f.sourceCode);
                    }
                }
                else if (sFuncname[sFuncname.length - 1] == f.name) {
                    res.add(f.sourceCode);
                }
            }

        }
        return res;
    }
    public delFunction(functionName: string) {
        console.log(`del function name:${functionName}`)
        this.projectFunctions = this.projectFunctions.filter(item => {
            item.name != functionName
        })
    }

    public GetClassByName(name: string) {
        let ans = new Set()
        for (const c of this.projectClasses) {
            if (c.name == name) {
                ans.add(c.sourceCode)
            }
        }
        return ans
    }
    public GetClassByType(name: string) {
        let ans = new Set()
        for (const c of this.projectClasses) {
            if (c.name == name || name.startsWith(c.name)) {
                ans.add(c.sourceCode)
            }
        }
        return ans
    }
    public targetFileDataByName(filePath: string, name: string) {
        let ans = new Set()
        for (const c of this.projectClasses) {
            if (areFilePathsEqual(c.filePath, filePath)) {
                if (wordSimilarity(c.name.toLowerCase(), name.toLowerCase()) > minimumSimilarityStandard - 0.05) {
                    ans.add(c.sourceCode)
                }
            }
        }
        return ans
    }
    public GetFunctionsByName(name: string) {
        if (this.projectFunctions.length == 0) {
            this.projectFunctions = this.parseProjectDefined(this.projectFunctionDefineds)
        }
        let allFunctions: string[] = []
        for (const f of this.projectFunctions) {
            if (f.name == name) {
                allFunctions.push(f.sourceCode)
            }
        }
        return allFunctions
    }
}