import { Project, SyntaxKind, Node, CallExpression } from "ts-morph"
import fs from "fs";
import path from 'path';
import {join} from "path"
import { FunctionCallData,useDefined } from "../Util/typedefined"
// import { SlicingParams } from "./SlicingMethod"
import {TSSlicer} from "./SlicingClass"
const maxUseFind = 4;

export function getAllFunction(path: any) {
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(path);

    const functions = sourceFile.getFunctions();
    const classMethods = sourceFile.getClasses().flatMap(c => c.getMethods());
    const arrowFunctions = sourceFile.getVariableDeclarations()
        .map(d => d.getInitializer())
        .filter(i => i?.isKind(SyntaxKind.ArrowFunction))
        .map(a => a?.asKind(SyntaxKind.ArrowFunction));

    const allFunctions = [...functions, ...classMethods, ...arrowFunctions];

    var ans: any[] = [];
    allFunctions.forEach(func => {
        const name = func?.getSymbol()?.getName() || "Anonymous";
        const params = func?.getParameters().map(p => `${p.getName()}: ${p.getType().getText()}`);
        let returnTypeNode = func?.getReturnTypeNode();
        let returnType = "any";
        if (returnTypeNode) {
            returnType = returnTypeNode.getText();
        }
        if (returnType != "any") {
            ans.push(`function ${name}(${params?.join(", ")}) : ${returnType} |||${name}`)
        }
        else {
            ans.push(`function ${name}(${params?.join(", ")}) |||${name}`)
        }
    });
    return ans
}

function dealWithFCall(data:useDefined){
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(data.file);
    let callExpressiones = sourceFile.getDescendantsOfKind(SyntaxKind.CallExpression)
    for(const c of callExpressiones){
        if(c.getText() == data.useCode){
            let slicer = new TSSlicer(data.file)
            let ans = slicer.SlicingParams(c, data.name)
            return ans
        }
    }
}
export function fileCallExpression(funcName: string, sourcePath:string) {
    let ans= new Set();
    // const callExpressionPath = './data/useFunction.json';
    let callExpressionPath = join(__dirname, '..', 'KnowledgeBase', 'useFunction.json'); 
    let callData = parseFunctionData(callExpressionPath);
    let readFiles:string[] = []
    readFiles.push(sourcePath);
    let count = 0
    callData.forEach(item => {
        if(item.name == funcName && count< maxUseFind){
            count +=1;
            ans.add(dealWithFCall(item))
        }
        else if( item.name.includes(".")){
            let tempName = item.name.split(".")
            if(tempName[tempName.length-1] == funcName && count< maxUseFind){
                count +=1
                ans.add(dealWithFCall(item))
            }
        }
    });
    return ans
}

export function parseFunctionData(filePath: string): useDefined[] {

    const absolutePath = path.resolve(__dirname, filePath);

    try {
        const rawData = fs.readFileSync(absolutePath, 'utf-8');
        const parsedData: useDefined[] = JSON.parse(rawData);

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
export function SlicingByCall(data: FunctionCallData) {
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(data.file);
    let allCallExpression = sourceFile.getDescendantsOfKind(SyntaxKind.CallExpression);
    var ans:string[] = []
    allCallExpression.forEach(item=>{
        const expression = item.getExpression();
        let functionName = "";
        if (expression.isKind(SyntaxKind.Identifier)) {
            functionName = expression.getText(); 
        } else if (expression.isKind(SyntaxKind.PropertyAccessExpression)) {
            functionName = expression.getText(); 
        } else {
            functionName = "Anonymous"; 
        }
        if(functionName == data.name){
            let slicer = new TSSlicer(data.file);
            let res = slicer.SlicingParams(item);
            
            ans.push(res);
        }
    })
    return ans;
}

