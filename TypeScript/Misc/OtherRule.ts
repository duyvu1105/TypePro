import {
    SyntaxKind, VariableDeclaration, NewExpression, ClassDeclaration,
    FunctionDeclaration, MethodDeclaration, ParameterDeclaration, Node, Expression
} from "ts-morph";
import { FUNCTION_KINDS } from "../Util/typedefined"
import { fixType, fixExtraMask , getFileName} from "../Util/tools"
import { ProjectDataLoader } from "../DataLoader/ProjectDataLoader"
import { Logger, LogLevel } from "../Util/logMethods"
import path from 'path';
import fs from 'fs';
const logger = new Logger({
    level: LogLevel.DEBUG,
    format: "{time} [{level}] ▶ {message}",
});

const bundleDataPath = "./data/bundleData.json";
const usefulSymbol = ["=", ":", "(", ">", "<"]
const ignoreFunction = ["log", "get", "set", "add", "remove", "push", "pop", "shift", "unshift", "slice", "splice", "sort", "reverse", "map", "filter", "reduce", "find", "findIndex", "every", "some", "forEach", "includes", "join", "split", "toUpperCase", "toLowerCase", "trim", "trimStart", "trimEnd"]
interface functionData {
    name: string,
    srcCode: string,
}
function parsedexData(filePath: string): functionData[] {

    const absolutePath = path.resolve(__dirname, filePath);
    try {

        const rawData = fs.readFileSync(absolutePath, 'utf-8');
        const parsedData: functionData[] = JSON.parse(rawData);

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
function isUsefulSlice(slice: string) {
    for (const s of usefulSymbol) {
        if (slice.includes(s)) {
            return true;
        }
    }
    return false;
}

function inferExprType(expr: Expression): string {
    const kind = expr.getKind();

    if (
        kind === SyntaxKind.StringLiteral ||
        kind === SyntaxKind.NumericLiteral ||
        kind === SyntaxKind.TrueKeyword ||
        kind === SyntaxKind.FalseKeyword ||
        kind === SyntaxKind.NullKeyword
    ) {
        if (kind === SyntaxKind.StringLiteral) return "string";
        if (kind === SyntaxKind.NumericLiteral) return "number";
        if (kind === SyntaxKind.TrueKeyword || kind === SyntaxKind.FalseKeyword)
            return "boolean";
        if (kind === SyntaxKind.NullKeyword) return "null";
    }

    if (Node.isArrayLiteralExpression(expr)) return "Array";
    if (Node.isObjectLiteralExpression(expr)) return "Object";

    if (Node.isCallExpression(expr)) {
        const fn = expr.getExpression();
        let name: string | undefined;
        if (Node.isIdentifier(fn)) {
            name = fn.getText();
        } else if (Node.isPropertyAccessExpression(fn)) {
            name = fn.getName();
        }
        if (name) {
            const sf = expr.getSourceFile();
            if (sf.getClass(name)) {
                return `class ${name}`;
            } else {
                return `The return of ${name} or class ${name}`;
            }
        }
    }

    if (Node.isBinaryExpression(expr)) {
        const op = expr.getOperatorToken().getKind();
        if (
            op === SyntaxKind.PlusToken ||
            op === SyntaxKind.MinusToken ||
            op === SyntaxKind.AsteriskToken ||
            op === SyntaxKind.SlashToken
        ) {
            return inferExprType(expr.getLeft());
        }
    }

    return "any";
}


function inferVariableDeclarationType(
    varDecl: VariableDeclaration
): string {

    const init = varDecl.getInitializer();
    if (init) {
        return inferExprType(init);
    }

    return "any";
}

export function getEnclosingContext(
    node:
        | ParameterDeclaration
        | FunctionDeclaration
        | MethodDeclaration
): ClassDeclaration | FunctionDeclaration | MethodDeclaration | undefined {

    if (Node.isParameterDeclaration(node)) {
        const asMethod = node.getFirstAncestorByKind(SyntaxKind.MethodDeclaration);
        if (asMethod) return asMethod;

        const asFunction = node.getFirstAncestorByKind(
            SyntaxKind.FunctionDeclaration
        );
        return asFunction ?? undefined;
    }
}
export function AnalysizerRule(CODE: Set<any>, node: any, interfaceData: any[] = [], importInfos: any[] = [], needFindType: Set<string> = new Set(),filePath:string = "") {
    let projectDataLoader = new ProjectDataLoader()
    let result = new Set()
    let totalCode = ""
    let belongClassName = ""
    let fixDecNode = ""

    if(filePath != ""){
        totalCode = `this is a snippet from the file ${getFileName(filePath)}\n`
    }
    let asyncRule = "This is an async declared function, and its return value must be in the Promise<...> format.\n"
    let propsPrompt = `This parameter may be of type ThemedStyledProps or PropsWithChildren, only one of these two can be selected`
    if (node.getKind() === SyntaxKind.VariableDeclaration) {
        let initType = inferVariableDeclarationType(node)
        let init = node.getInitializer()
        fixDecNode = node.getParent()?.getText()
    }
    else if(node.getKind() === SyntaxKind.Parameter){
        let includesStyle = false;
    }
    if (node.getKind() === SyntaxKind.MethodDeclaration || (node.getKind() === SyntaxKind.Parameter && node.getParent().getKind() === SyntaxKind.MethodDeclaration)) {
        let belongClass = getEnclosingContext(node);
        let funcName = node.getKind() === SyntaxKind.MethodDeclaration ? node.getName() : node.getParent().getName()
        if (belongClass != undefined) {
            let bName = belongClass.getName()
            if (bName != undefined) {
                belongClassName = bName
            }
            let belongWhatClass = `This function ${funcName} is a method in class ${belongClass.getName()}`
            totalCode = totalCode + belongWhatClass + "\n"
        }
        else {
            logger.info(`belongClass is undefined`)
        }
    }
    if (true) { 
        importInfos.forEach(item => totalCode = totalCode + item.getText() + "\n")
    }
    // if (needFindFunction.size > 0) {
    //     let dexData = parsedexData(bundleDataPath)
    //     for (const funcName of needFindFunction) {
    //         if (ignoreFunction.includes(funcName)) continue;
    //         let tempList = dexData.filter(item => item.name === funcName);
    //         tempList.forEach(item => {
    //             // totalCode = totalCode + item.srcCode + "\n"
    //         })
    //     }

    // }
    if(node.getKind() === SyntaxKind.VariableDeclaration||node.getKind() === SyntaxKind.Parameter){
        
        let targetName = node.getName()
        // logger.debug(`file recomend:${filePath} ${targetName}`)
        let fileRecomData = projectDataLoader.targetFileDataByName(filePath, targetName)
        fileRecomData.forEach(item=>{
            totalCode = totalCode + item + "\n"
        })
    }
    if (needFindType.size > 0) {
        for (const t of needFindType) {
            if (t.startsWith("string") || t.startsWith("number") || t.startsWith("boolean")) {
                continue
            }
            let needAddType = projectDataLoader.GetClassByType(t)
            needAddType.forEach((item: any) => totalCode = totalCode + item + "\n")
        }
    }
    if (node.getKind() === SyntaxKind.VariableDeclaration && node.getText().includes("{")) {
        interfaceData.forEach(item => totalCode = totalCode + item.getText() + "\n")
    }
    if (node.getKind() === SyntaxKind.VariableDeclaration) { 
        const varDecl = node as VariableDeclaration;
        const initializer = varDecl.getInitializer();
        if (initializer) {
            if (initializer.getKind() === SyntaxKind.NewExpression) {
                const newExpr = initializer as NewExpression;
                const className = newExpr.getExpression().getText();
                let ans = projectDataLoader.GetClassByName(className);
                ans.forEach(Item => { totalCode = totalCode + Item + "\n" })
            }
        }
    }

    for (const slice of CODE) {
        if (slice.length < 6 && !isUsefulSlice(slice)) {
            continue
        }
        if(fixDecNode!="" && slice == node.getText()){
            totalCode = totalCode + fixDecNode + "\n"
            continue
        }
        totalCode = totalCode + slice + "\n"
    }
    if (FUNCTION_KINDS.includes(node.getKind()) && (node.getText().startsWith("async ")||
        node.getText().startsWith("export async ")||node.getText().startsWith("public async ")
        ||node.getText().startsWith("private async ")
        )) {
        totalCode = asyncRule + totalCode
    }
    totalCode = fixType(totalCode)
    if (node.getKind() === SyntaxKind.Parameter) {
        // totalCode = fixExtraMask(node.getName() ,totalCode)
    }
    if (belongClassName != "") {
        totalCode = totalCode.replace(/this\./g, `${belongClassName}.`)
        totalCode = totalCode.replace(/ this\;/g, ` ${belongClassName}.`)
    }
    // logger.info(`length of totalCode:${totalCode.length}`)
    // todo if totalCode vary long, how to reduce its length?
    return totalCode
}