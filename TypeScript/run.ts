import { readFileSync, Stats, writeFileSync } from 'fs';
import fs from 'fs';
import path from 'path';
import { DataSetData, CodeData, DataType, OutputData, SlicedData } from "./Util/typedefined"
import { Logger, LogLevel } from "./Util/logMethods"
import { Project, SyntaxKind, FunctionDeclaration, MethodDeclaration } from "ts-morph"
// import { Slicing } from "./SlicingMethod"
import { TSSlicer } from "./Slicing/SlicingClass"
import { LLMAgent } from './LLMAgent';
import { execSync } from 'child_process';

const logger = new Logger({
    level: LogLevel.DEBUG,
    format: "{time} [{level}] ▶ {message}",
});

interface OutputData2{
    filePath: string,
    name: string|undefined,
    dataType: string,
    InferenceType: string,
    SlicingCode: string,
    TypeRanking:string[],
}
function writeDataToFile(
    filename: string,
    dataList: OutputData2[]
): void {
    try {
        const jsonString = JSON.stringify(dataList, null, 2);
        writeFileSync(filename, jsonString, 'utf8');
        console.log(`Project definition data has been successfully written. ${filename}`);
    } catch (error: any) {
        console.error('An error occurred while writing to the file:', error.message);
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
            if (fullPath.endsWith(".ts") || fullPath.endsWith(".tsx")) {
                fileList.push(fullPath); 
            }
        }
    });

    return fileList;

}
function runSyncCommand(command: string): string {
    try {
        const output = execSync(command, { encoding: 'utf-8' });
        console.log('Synchronous output:', output);
        return output;
    } catch (error) {
        console.error('Synchronous execution failed:', error);
        return '';
    }
}

async function generationType(CODE: string, typePrompt: string[], filePath: string) {
    let LLMA = new LLMAgent();
    LLMA.setFilePath(filePath)
    let prediction = await LLMA.GenerationType(CODE, typePrompt);
    return prediction
}
async function main() {
    var ProjectPath = ""
    const args = process.argv.slice(2);
    var outputPath = ""
    if (args.length < 2) {
        console.error("Error: Required parameter missing. Please provide the project path.");
        process.exit(1);
    }else {
        ProjectPath = args[0]
        outputPath = args[1]
    }
    let AllData = getAllFiles(ProjectPath);
    var totalOutputDatas: OutputData2[] = [];
    if (ProjectPath!="") {
        logger.info(`start load project Data:${ProjectPath}`)
        runSyncCommand("python ./Scripts/run.py " + ProjectPath)
        await new Promise(res => setTimeout(res, 100));
    }
    let countTest = 0;
    for (const filePath of AllData) {
        const project = new Project();
        const sourceFile = project.addSourceFileAtPath(filePath);
        let varNodes = sourceFile.getDescendantsOfKind(SyntaxKind.VariableDeclaration);
        let Slicer = new TSSlicer(filePath);
        
        for (const varNode of varNodes) {
            let sourceType = ""
            let typeNode = varNode.getTypeNode()
            countTest+=1
            if (typeNode) {
                continue
            }else{
                sourceType = "any"
            }
            try {
                let saInferType = varNode.getType()
                if(saInferType.getText()!="any"){
                    let tempOutData: OutputData2 = {
                        filePath: filePath,
                        name: varNode.getName(),
                        dataType: "var",
                        InferenceType: saInferType.getText(),
                        SlicingCode: "static analysize result",
                        TypeRanking: []
                    }
                    totalOutputDatas.push(tempOutData)
                }
                else{
                    varNode.setType("mask")
                let CodeData: CodeData = {
                    node: varNode,
                    type: "",
                    filePath: filePath,
                    dataType: DataType.Var,
                }
                let slicing_ans = Slicer.Slicing(CodeData)
                let sliciedCode = slicing_ans.code.replace(": mask", ": <mask>")
                // logger.info(sliciedCode)
                varNode.setType(sourceType)
                if(slicing_ans.typeRecommended.length>0){
                    console.log(slicing_ans.typeRecommended)
                    logger.debug(sliciedCode)
                }
                let Ans = await generationType(sliciedCode, slicing_ans.typeRecommended, filePath)
                let tempOutData: OutputData2 = {
                    filePath: filePath,
                    name: varNode.getName(),
                    dataType: "var",
                    InferenceType: Ans,
                    SlicingCode: sliciedCode,
                    TypeRanking: slicing_ans.typeRecommended
                }
                totalOutputDatas.push(tempOutData)
                }
            }
            catch (e) {
                //logger.error(`set type error:${e}`)
                varNode.setType("")
            }
        }
        let functionNodes = sourceFile.getDescendantsOfKind(SyntaxKind.FunctionDeclaration);
        for(const functionNode of functionNodes){
            let sourceType = ""
            let typeNode = functionNode.getReturnTypeNode()
            try{
                let saInferType = functionNode.getReturnType();
                if(saInferType.getText()!="any"){
                    let tempOutData: OutputData2 = {
                        filePath: filePath,
                        name: functionNode.getName(),
                        dataType: "par",
                        InferenceType: saInferType.getText(),
                        SlicingCode: "static analysize result",
                        TypeRanking: []
                    }
                    totalOutputDatas.push(tempOutData)
                }
                else{
                    functionNode.setReturnType("mask")
                    let CodeData: CodeData = {
                        node: functionNode,
                        type: "",
                        filePath: filePath,
                        dataType: DataType.Function,
                    }
                    let slicing_ans = Slicer.Slicing(CodeData)
                    let sliciedCode = slicing_ans.code.replace(": mask",": <mask>")
                    // logger.info(sliciedCode)
                    functionNode.setReturnType(sourceType)
                    let Ans = await generationType(sliciedCode, slicing_ans.typeRecommended, filePath)
                    let tempOutData: OutputData2 = {
                        filePath: filePath,
                        name: functionNode.getName(),
                        dataType: "Ret",
                        InferenceType: Ans,
                        SlicingCode: sliciedCode,
                        TypeRanking: slicing_ans.typeRecommended
                    }
                    totalOutputDatas.push(tempOutData)
                }

            }
            catch(e){
                //logger.error(`set type error:${e}`)
                functionNode.setReturnType("")
            }
        }
        for(const functionNode of functionNodes){
            let args = functionNode.getParameters()
            for(const arg of args){
                let sourceType = ""
                let typeNode = arg.getTypeNode()
                try{
                    let saInferType = arg.getType();
                    if(saInferType.getText()!="any"){
                        let tempOutData: OutputData2 = {
                            filePath: filePath,
                            name: arg.getName(),
                            dataType: "par",
                            InferenceType: saInferType.getText(),
                            SlicingCode: "static analysize result",
                            TypeRanking: []
                        }
                        totalOutputDatas.push(tempOutData)
                    }
                    else{
                        arg.setType("mask")
                        let CodeData: CodeData = {
                            node: arg,
                            type: "",
                            filePath: filePath,
                            dataType: DataType.FunctionParam,
                        }
                        let slicing_ans = Slicer.Slicing(CodeData)
                        let sliciedCode = slicing_ans.code.replace(": mask",": <mask>")
                        //logger.info(sliciedCode)
                        arg.setType(sourceType)
                        let Ans = await generationType(sliciedCode, slicing_ans.typeRecommended, filePath)
                        let tempOutData: OutputData2 = {
                            filePath: filePath,
                            name: arg.getName(),
                            dataType: "par",
                            InferenceType: Ans,
                            SlicingCode: sliciedCode,
                            TypeRanking: slicing_ans.typeRecommended
                        }
                        totalOutputDatas.push(tempOutData)
                    }

                }
                catch(e){
                    //logger.error(`set type error:${e}`)
                    arg.setType("any")
                }

            }
        }
    }
    // console.log(totalOutputDatas)
    if(outputPath!=""){
        writeDataToFile(outputPath, totalOutputDatas)
    }
    else{
        console.log("Output path error")
    }
}
main()


//writeSourceCodeToFile(outputPath, totalOutputData);