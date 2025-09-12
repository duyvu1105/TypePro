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


var totalOutputData: OutputData[] = []
var totalFileVIndex: Map<string, number> = new Map()
const repoPath = "./newRepos/"
const outputPath = "./repoOutput/all_data_test2.json"
const mask = "mask"
const logger = new Logger({
    level: LogLevel.DEBUG,
    format: "{time} [{level}] ▶ {message}",
});

function writeSourceCodeToFile(
    filename: string,
    dataList: OutputData[]
): void {
    try {
        const jsonString = JSON.stringify(dataList, null, 2);
        writeFileSync(filename, jsonString, 'utf8');
        console.log(`Written ${filename}`);
    } catch (error: any) {
        console.error('error:', error.message);
    }
}
function readJsonSync<T = unknown>(filePath: string): T[] {
    const fullPath = path.resolve(__dirname, filePath);
    const content = readFileSync(fullPath, 'utf-8');
    return JSON.parse(content) as T[];
}

export function existsSync(targetPath: string): boolean {
    try {
        fs.accessSync(targetPath, fs.constants.F_OK);
        return true;
    } catch {
        return false;
    }
}

function getFileIndex(fileName: string, type: string, name: string) {
    let key = `${fileName}_${type}_${name}`;
    if (totalFileVIndex.has(key)) {
        let srcindex = totalFileVIndex.get(key);
        if (srcindex != undefined) {
            totalFileVIndex.set(key, srcindex + 1);
        }
        return srcindex;
    }
    else {
        totalFileVIndex.set(key, 1);
        return 0;
    }
}

function addDataOutput(data: DataSetData, prompt: string, prediction: string[], slicedCode: string) {
    let tempOuttData: OutputData;
    tempOuttData = {
        cat: data.cat,
        file: data.file,
        url: data.url,
        commit_hash: data.commit_hash,
        gttype: data.gttype,
        loc: data.loc,
        name: data.name,
        scope: data.scope,
        totalPrompt: prompt,
        prediction: prediction,
        slicedCode: slicedCode
    };
    totalOutputData.push(tempOuttData);
}
async function predictAndWriteData(data: DataSetData, slicedData: SlicedData, filePath: string = "", isAsyncFunction: boolean = false) {
    let sliced_code = slicedData.code.replace(mask, `<${mask}>`)
    // logToFile(logPath, sliced_code+"\n============================================================================\n");
    logger.debug(sliced_code)
    let LLMA = new LLMAgent();
    LLMA.setFilePath(filePath)
    let prediction = await LLMA.GenerationType(sliced_code, slicedData.typeRecommended);
    let totalPrompt = LLMA.getTotalPrompt()
    let predictions: string[] = []
    let dataType = data.scope;
    if (prediction != undefined) {

        predictions.push(prediction);
        logger.debug(`${prediction},\n${sliced_code}`)
        addDataOutput(data, totalPrompt, predictions, sliced_code);
    } else {
        logger.error("undefined")
    }
}
async function findTargetNode(data: DataSetData) {
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(repoPath + data.file);
    var slicer = new TSSlicer(repoPath + data.file)
    logger.info(`start :${data.file} name: ${data.name}, type: ${data.scope}`)
    let rightType = data.gttype;
    if (data.scope == "var") {
        var vDecNodes = sourceFile.getDescendantsOfKind(SyntaxKind.VariableDeclaration).filter(node => node.getName() == data.name)
        let targetIndex = getFileIndex(data.file, data.scope, data.name)
        if (targetIndex != undefined && vDecNodes.length > targetIndex) {
            let tempCodeData: CodeData = {
                node: vDecNodes[targetIndex],
                type: "var",
                filePath: repoPath + data.file,
                dataType: DataType.Var,
            }

            let srcType = "any"
            let srcTypeNode = tempCodeData.node.getTypeNode();
            if (srcTypeNode) {
                srcType = srcTypeNode.getText()
            }
            tempCodeData.node.setType(mask)
            let ans = slicer.Slicing(tempCodeData)
            try {
                tempCodeData.node.setType("")
            }
            catch (e) {
                logger.error(`set type error:${e}`)
                tempCodeData.node.setType(srcType)
            }
            logger.debug(`sliced data:${ans.code.replace(mask, `<${mask}>`)}`)
            await predictAndWriteData(data, ans, repoPath + data.file)
        }
        else {
            logger.error(`find target node failed length:${vDecNodes.length}`)
            logger.error(`fileName:${data.file} name:${data.name}`)
        }
    }
    else if (data.scope == "arg") {
        let allParams = sourceFile.getDescendantsOfKind(SyntaxKind.Parameter).filter(node => node.getName() == data.name)
        let targetIndex = getFileIndex(data.file, data.scope, data.name)
        if (targetIndex != undefined && allParams.length > targetIndex) {
            let tempCodeData: CodeData = {
                node: allParams[targetIndex],
                type: "par",
                filePath: repoPath + data.file,
                dataType: DataType.FunctionParam,
            }
            let srcType = "any"
            let srcTypeNode = tempCodeData.node.getTypeNode()
            if (srcTypeNode) {
                srcType = srcTypeNode.getText()
            }


            tempCodeData.node.setType(mask)

            let ans = slicer.Slicing(tempCodeData)
            try {
                tempCodeData.node.setType("")
            }
            catch (e) {
                logger.error(`set type error:${e}`)
                tempCodeData.node.setType(srcType)
            }
            await predictAndWriteData(data, ans, repoPath + data.file)

        }
        else {
            logger.error(`${allParams.length}`)
            logger.error(`${data.file} ${data.name}`)
        }

    }
    else {
        let allFunc: any[] = []
        sourceFile.forEachDescendant(node => {
            if (node.getKind() === SyntaxKind.FunctionDeclaration) {
                let decNode = node as FunctionDeclaration
                if (decNode.getName() == data.name) {
                    allFunc.push(node)
                }
            } else if (node.getKind() === SyntaxKind.MethodDeclaration) {
                let decNode = node as MethodDeclaration
                if (decNode.getName() == data.name) {
                    allFunc.push(node)
                }
            }
        })
        let targetIndex = getFileIndex(data.file, data.scope, data.name)
        if (targetIndex != undefined && allFunc.length > targetIndex) {
            let tempCodeData: CodeData = {
                node: allFunc[targetIndex],
                type: "ret",
                filePath: repoPath + data.file,
                dataType: DataType.Function,
            }
            if (true) {
                let tempTypeNode = tempCodeData.node.getReturnTypeNode();
                if (tempTypeNode) {
                    logger.info(`${tempTypeNode.getText()}`)
                }
                else {
                    logger.info(`${tempCodeData.node.getText()}`)
                }
            }
            let srcType = "any"
            let srcTypeNode = tempCodeData.node.getReturnTypeNode()
            if (srcTypeNode) {
                srcType = srcTypeNode.getText()
            }
            tempCodeData.node.setReturnType(mask)
            let ans = slicer.Slicing(tempCodeData)
            try {
                tempCodeData.node.setReturnType("")
            }
            catch (e) {
                logger.error(`${e}`)
                tempCodeData.node.setReturnType(srcType)
            }

            await predictAndWriteData(data, ans, repoPath + data.file, (tempCodeData.node.getText().startsWith("async ")
                || tempCodeData.node.getText().startsWith("export async ") || tempCodeData.node.getText().startsWith("public async ")
                || tempCodeData.node.getText().startsWith("private async ")))
        }
    }
}

function runSyncCommand(command: string): string {
    try {
        const output = execSync(command, { encoding: 'utf-8' });
        console.log('', output);
        return output;
    } catch (error) {
        console.error('', error);
        return '';
    }
}

async function main() {
    let dataset_path = "";
    const datas = readJsonSync<DataSetData>(dataset_path);
    let allRepos: string[] = []
    let commit_hashs: string[] = []
    let count1 = 0
    let start_run = false;
    let lastrepo = ""
    for (const d of datas) {
        let repoName = d.url.split('/').slice(-1).join('/')
        let repoPath = "./Repos/" + repoName
        if (!start_run) continue
        if (lastrepo != repoName) {
            lastrepo = repoName

            logger.info(`start: ${repoName}`)
            runSyncCommand("python ./Scripts/run.py " + repoPath)
            await new Promise(res => setTimeout(res, 100));

            await findTargetNode(d)

        }
        logger.info(`${count1}`)
    }
        writeSourceCodeToFile(outputPath, totalOutputData);
    }

// main()
