import { projectDefined, useDefined } from "../Util/typedefined"
import fs from 'fs';
import path from 'path';
import { join } from "path";
import { Dirent, Stats, writeFileSync } from "fs";
import { Project, SyntaxKind, PropertyDeclaration,Node,VariableDeclaration,ArrowFunction } from "ts-morph"
import { fixType, delyinhao } from "../Util/tools"
import { Logger } from "../Util/logMethods";
const TARGET_KINDS = [SyntaxKind.ClassDeclaration, SyntaxKind.InterfaceDeclaration]

var projectFunctions: projectDefined[] = [];
var projectClasses: projectDefined[] = [];
const projectFunctionDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectFunctions.json')
const projectClassDefineds = join(__dirname, '..', 'KnowledgeBase', 'ProjectClasses.json')
function writeSourceCodeToFile(
    filename: string,
    dataList: projectDefined[]
): void {
    try {
        const jsonString = JSON.stringify(dataList, null, 2);
        writeFileSync(filename, jsonString, 'utf8');
    } catch (error: any) {
    }
}
function stripQuotes(str: string): string {
    if (
        (str.startsWith('"') && str.endsWith('"')) ||
        (str.startsWith("'") && str.endsWith("'"))
    ) {
        return str.slice(1, -1);
    }
    return str;
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
function dealwithFDefined(node: any, sourceFile: any, filePath: string) {
    let name = node.getName();
    let tempNode = node
    if (tempNode) {
        while (tempNode && tempNode.getKind() != SyntaxKind.ModuleDeclaration) {
            tempNode = tempNode.getParent()
        }
        if (tempNode && tempNode.getKind() === SyntaxKind.ModuleDeclaration) {
            name = stripQuotes(tempNode.getName()) + "." + name
        }
    }
    let params = node.getParameters().map((item: any) => {
        let pType = fixType(item.getType().getText(sourceFile))
        let pName = item.getName()
        if (pType == "any") {
            return `${pName}`
        }
        return `${pName}:${pType}`
    })
    let returnType = fixType(node.getReturnType().getText(sourceFile))
    let totalCode = ""
    if (returnType != "any" && returnType != "unknown") {
        totalCode = `${name}(${params.join(', ')}): ${returnType}`
    }
    else {
        totalCode = node.getText()
    }
    if (node.getKind() === SyntaxKind.FunctionDeclaration) {
        totalCode = "function " + totalCode
    } else {
        while (node && node.getKind() != SyntaxKind.ClassDeclaration) {
            node = node.getParent()
        }
        if (node) {
            totalCode = node.getName() + "." + totalCode
        }
    }
    let tempData: projectDefined = {
        name: name,
        sourceCode: totalCode,
        filePath: filePath
    }
    if(name!=undefined){
        projectFunctions.push(tempData)
    }
}
function fixClassCode(classDecl: any, sourceFile: any) {

    const props = classDecl.getProperties();

    const className = classDecl.getName()!;

    const writer = sourceFile.getProject().createWriter();

    writer.write(`class ${className} {`).newLine();

    props.forEach((prop: PropertyDeclaration) => {

        const isStatic = prop.isStatic();
        const name = prop.getName();
        let typeText: string;
        if (prop.getTypeNode()) {
            typeText = prop.getTypeNode()!.getText();
        } else {
            typeText = prop.getType().getText();
        }
        const line = `${isStatic ? "static " : ""}${name}: ${typeText};`;
        writer.write("    " + line).newLine();
    });

    writer.write("}").newLine();

    const resultCode = writer.toString();
    return resultCode
}
function dealValArrowFuncation(filePath: string) {

    const result: VariableDeclaration[] = [];
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(filePath);

    sourceFile.getVariableStatements().forEach((varStmt) => {
        if (!varStmt.isExported()) return; 

        varStmt.getDeclarations().forEach((decl) => {
            const init = decl.getInitializer();

            if (init && Node.isArrowFunction(init)) {
                result.push(decl);
            }
        });
    });
    for(const vA of result){
        console.log(vA.getText())
    }

}
export function extractExportedArrows(
    filePath:string
  ) {
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(filePath);
    sourceFile.getVariableStatements().forEach((varStmt) => {
      if (!varStmt.isExported()) return;
  
      varStmt.getDeclarations().forEach((decl) => {
        const init = decl.getInitializer();
        if (!init || !Node.isArrowFunction(init)) return;
  
        const arrow = init as ArrowFunction;
        const name = decl.getName();

        const sourceCode = arrow.getText();

        const paramsText = arrow
          .getParameters()
          .map((p:any) => p.getText())
          .join(", ");
        const returnType = arrow.getReturnTypeNode();
        const returnText = returnType
          ? returnType.getText()
          : 
            arrow
              .getType()
              .getCallSignatures()[0]
              .getReturnType()
              .getText();
        const signature = `(${paramsText}) => ${returnText}`;
        let tempData: projectDefined = {
            name: name,
            sourceCode: name+ " = " +sourceCode,
            filePath: filePath
        }
        console.log(`test function name:${name}`)
        if(name!=undefined){
            projectFunctions.push(tempData)
        }
      });
    });
  }
function ParseEachFile(filePath: string) {

    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(filePath);
    let classDefined = sourceFile.getDescendantsOfKind(SyntaxKind.ClassDeclaration)
    for (const classNode of classDefined) {
        let tCode = fixClassCode(classNode, sourceFile)
        let className = classNode.getName()
        if (className != undefined) {
            let tempData: projectDefined = {
                name: className,
                sourceCode: tCode,
                filePath: filePath
            }
            projectClasses.push(tempData)
        }
    }
    let interfaceDefined = sourceFile.getDescendantsOfKind(SyntaxKind.InterfaceDeclaration)
    for (const interfaceNode of interfaceDefined) {
        let tCode = interfaceNode.getText()
        let interfaceName = interfaceNode.getName()
        if (interfaceName != undefined) {
            let tempData: projectDefined = {
                name: interfaceName,
                sourceCode: tCode,
                filePath: filePath
            }
            projectClasses.push(tempData)
        }
    }
    let typeDeined = sourceFile.getDescendantsOfKind(SyntaxKind.TypeAliasDeclaration)
    for (const typeNode of typeDeined) {
        let tCode = typeNode.getText()
        let typeName = typeNode.getName()
        if (typeName != undefined) {
            let tempData: projectDefined = {
                name: typeName,
                sourceCode: tCode,
                filePath: filePath
            }
            projectClasses.push(tempData)
        }
    }
    let functionDefineds = sourceFile.getDescendantsOfKind(SyntaxKind.FunctionDeclaration)
    let methods = sourceFile.getDescendantsOfKind(SyntaxKind.MethodDeclaration)
    extractExportedArrows(filePath)
    functionDefineds.forEach(item => dealwithFDefined(item, sourceFile, filePath))
    methods.forEach(item => dealwithFDefined(item, sourceFile, filePath))
}
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
writeSourceCodeToFile(projectClassDefineds, projectClasses)
writeSourceCodeToFile(projectFunctionDefineds, projectFunctions)