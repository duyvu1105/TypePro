
import { projectDefined, useDefined } from "../Util/typedefined"
import fs from 'fs';
import path from 'path';
import { join } from "path";
import { Dirent, Stats, writeFileSync } from "fs";
import { Project, SyntaxKind } from "ts-morph"

var projectFunctions: projectDefined[] = [];
var projectClasses: projectDefined[] = [];
const projectFunctionDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectFunctions.json')
const projectClassDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectClasses.json')
var totalCallData: useDefined[] = []
var totalClassData: useDefined[] = []
const useFunctionPath = join(__dirname, '..', 'KnowledgeBase', 'useFunction.json')
const useClassPath = join(__dirname, '..', 'KnowledgeBase', 'useClass.json')

function writeSourceCodeToFile(
    filename: string,
    dataList: useDefined[]
): void {
    try {
        const jsonString = JSON.stringify(dataList, null, 2);
        writeFileSync(filename, jsonString, 'utf8');
    } catch (error: any) {
        console.error('error:', error.message);
    }
}
function parseProjectDefined(filePath: string): projectDefined[] {
    const absolutePath = path.resolve(__dirname, filePath);
    try {
        const rawData = fs.readFileSync(absolutePath, 'utf-8');
        const parsedData: projectDefined[] = JSON.parse(rawData);
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
function getAllFiles(dirPath: string, fileList: string[] = []): string[] {
    const files: string[] = fs.readdirSync(dirPath);

    files.forEach(file => {
        const fullPath: string = path.join(dirPath, file);
        const stat: Stats = fs.statSync(fullPath);

        if (stat.isDirectory()) {
            getAllFiles(fullPath, fileList);
        } else {
            if (fullPath.endsWith(".ts")||fullPath.endsWith(".tsx")) {
                fileList.push(fullPath);
            }
        }
    });

    return fileList;
}
function isProjectFunction(funcName: string) {
    for (const func of projectFunctions) {
        if (func.name === funcName) {
            return true;
        }
        if (funcName.includes(".") && func.name.includes(".")) {
            if (funcName.split(".").slice(-1)[0] == func.name.split(".").slice(-1)[0]) {
                return true;
            }
        }
        else if (func.name.includes(".")) {
            if (funcName == func.name.split(".").slice(-1)[0]) {
                return true;
            }
        }
    }
    return false;
}
function getFunctionDefinedFile(funcName: string){
    for (const func of projectFunctions) {
        if (func.name === funcName) {
            return func.filePath;
        }
        if (funcName.includes(".") && func.name.includes(".")) {
            if (funcName.split(".").slice(-1)[0] == func.name.split(".").slice(-1)[0]) {
                return func.filePath;
            }
        }
        else if (func.name.includes(".")) {
            if (funcName == func.name.split(".").slice(-1)[0]) {
                return func.filePath;
            }
        }
    }
}
function isProjectClass(className: string) {
    for (const cls of projectClasses) {
        if (cls.name === className) {
            return true;
        }
    }
    return false;
}
function ParseEachFile(filePath: string) {
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(filePath);
    let CallExpressions = sourceFile.getDescendantsOfKind(SyntaxKind.CallExpression)
    for (const call of CallExpressions) {
        let callName = call.getExpression().getText()
        if (isProjectFunction(callName)) {
            let funcFile = getFunctionDefinedFile(callName)
            let callParent = call.getParent()

            // let slicedCode = callParent && callParent.getKind() === SyntaxKind.VariableDeclaration ? callParent.getText() : call.getText()
            let slicedCode = call.getText()
            let tempCallData: useDefined = {
                name: callName,
                useCode: slicedCode,
                file: filePath
            }
            totalCallData.push(tempCallData)
            if(funcFile!=filePath){
                console.log(funcFile)
                console.log(tempCallData)
            }
        }
    }

    let newExpressions = sourceFile.getDescendantsOfKind(SyntaxKind.NewExpression)
    for (const newExp of newExpressions) {
        let className = newExp.getExpression().getText()
        if (isProjectClass(className)) {
            // let slicedCode = Slicing(newExp.getText())
            let slicedCode = newExp.getText()
            let tempCallData: useDefined = {
                name: className,
                useCode: slicedCode,
                file: filePath
            }
            totalClassData.push(tempCallData)
        }
    }
}

projectFunctions = parseProjectDefined(projectFunctionDefineds)
projectClasses = parseProjectDefined(projectClassDefineds)

var testPath = ""
const args = process.argv.slice(2);
if (args.length == 0) {
    console.log("Incorrect project address entered.")
}
else {
    testPath = args[0]
}
let allFiles = getAllFiles(testPath)
for (const file of allFiles) {
    ParseEachFile(file)
}

writeSourceCodeToFile(useFunctionPath, totalCallData)
writeSourceCodeToFile(useClassPath, totalClassData)