import {Logger, LogLevel} from "./Util/logMethods" 
import {TSSlicer} from "./Slicing/SlicingClass"
import {Project, SyntaxKind} from "ts-morph"
import {getAllTsFiles} from "./Util/tools"
import {CodeData, DataType} from "./Util/typedefined"
import {LLMAgent} from "./LLMAgent"
const mask =  "mask"
const logger = new Logger({
    level: LogLevel.DEBUG,
    format: "{time} [{level}] ▶ {message}",
});

const projectPath = ""
const needFixType = ["any","unknown"]

function getFileDataNode(filePath:string){
    const project = new Project();
    const sourceFile = project.addSourceFileAtPath(filePath);
    let allVarNodes = sourceFile.getDescendantsOfKind(SyntaxKind.VariableDeclaration);
    allVarNodes = []
    for(const vNode of allVarNodes){
        let typeNode = vNode.getTypeNode()
        if(vNode.getName()!="splitterEdgeProps"){
            continue
        }
        let mType = ""
        if(typeNode){
            mType = typeNode.getText()
        }
        else{
            mType = vNode.getType().getText()
        }
        if(true){
            try{
                vNode.setType(mask)
                let tempData:CodeData = {node:vNode,type:"",filePath:filePath,dataType:DataType.Var}
                let slicer:TSSlicer = new TSSlicer(filePath)
                let slicedAns = slicer.Slicing(tempData)
                slicedAns.code = slicedAns.code.replace(`: ${mask}`,`: <${mask}>`)
                if(slicedAns.typeRecommended.length>0){
                    logger.debug(`type recommend size:${slicedAns.typeRecommended.length}  varDecNode:${vNode.getText()} mType:${mType}`)
                    console.log(slicedAns.typeRecommended)
                }
                vNode.setType("any")
                logger.debug(slicedAns.code)
            }
            catch(e){
            }
        }
    }
    let functions = sourceFile.getDescendantsOfKind(SyntaxKind.FunctionDeclaration);
    let methods = sourceFile.getDescendantsOfKind(SyntaxKind.MethodDeclaration);
    let allFNode = [...functions, ...methods]
    for(const fNode of allFNode){
        let fName = fNode.getName()
        try{
            fNode.setReturnType(mask)
            let tempData:CodeData = {node:fNode, type:"", filePath:filePath, dataType:DataType.Function}
            let slicer = new TSSlicer(filePath)
            let slicedAns = slicer.Slicing(tempData)
            slicedAns.code = slicedAns.code.replace(`: ${mask}`, `: <${mask}>`)
            logger.debug(slicedAns.code)
        }
        catch(e){
            console.log(e)
        }
        
    }
}

let allFiles = getAllTsFiles(projectPath)

console.log(allFiles)
for(const file of allFiles){
    getFileDataNode(file)
}