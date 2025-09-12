// Please install OpenAI SDK first: `npm install openai`
import OpenAI from "openai";
const baseURL = '';
const apiKey = '';
import { Project, SyntaxKind } from "ts-morph";
import { ProjectDataLoader } from "./DataLoader/ProjectDataLoader"
import { ThirdPackageLoader } from "./DataLoader/ThirdPackageLoader"
import { Logger, LogLevel } from "./Util/logMethods"
import { isQuotedUnionBySplit } from "./Util/tools"
const logger = new Logger({
    level: LogLevel.DEBUG,
    format: "{time} [{level}] ▶ {message}",
});
export class LLMAgent {
    private openai: OpenAI;
    private total_prompt: string = "";
    private basePrompt = "Next, you will be provided with a piece of TypeScript code slice. You will infer the variable type or function return type in TypeScript and fill in the type annotation in <mask>. Output just only the type ,which you infer, nothing else,\n"
    private example_prompt = "Example output: mask: string\n"
    private filePath: string = ""
    private projectDataLoader: ProjectDataLoader;
    constructor() {
        this.openai = new OpenAI({ baseURL: baseURL, apiKey: apiKey });
        this.projectDataLoader = new ProjectDataLoader();
    }
    async Generation(prompts: string[], CODE: string) {
        let totalPrompt = this.basePrompt + this.example_prompt
        prompts.forEach(prompt => {
            totalPrompt += `${prompt}\n`
        });
        totalPrompt += `The code you need to make a prediction is:\n${CODE}`
        // const openai = new OpenAI({ baseURL: baseURL, apiKey: apiKey });
        this.total_prompt = totalPrompt
        const completion = await this.openai.chat.completions.create({
            messages: [{ role: "user", content: totalPrompt }],
            model: "gpt-3.5-turbo",
            // model: "deepseek-chat",
            // model: "gpt-4o-mini",
            // model: "claude-3-haiku-20240307",
            // model: "qwen3-coder-plus",
            max_tokens: 50,
            temperature: 0.2,
            top_p: 0.3,
        });
        logger.debug(`total prompt:\n${totalPrompt}`)
        // logToFile(logFile, `total prompt:\n${totalPrompt}`)
        try {
            if (completion.choices.length > 0) {
                logger.info(`final return ans:${completion.choices[0].message.content}`)
                //       logToFile(logFile, `final return ans:\n${completion.choices[0].message.content}`)
                return completion.choices[0].message.content
            }
            else
                return ""
        }
        catch (e) {
            return ""
        }
        //return completion.choices[0].message.content
    }
    public setFilePath(filePath: string) {
        this.filePath = filePath
    }
    public async GenerationType(CODE: string, typePrompt: string[] = []) {

        if (CODE.length > 2048 * 5) {
            return "too long for CODE"
        }
        let extra_prompt = "The possible types analyzed from the import information are: "
        for (const t of typePrompt) {
            extra_prompt = extra_prompt + "\n" + t
        }
        let otherPrompt = typePrompt.length > 0 ? [extra_prompt] : []
        let ans = await this.Generation(otherPrompt, CODE)
        let ansFix = ans?.replace("mask:", "")
        ansFix = ansFix?.replace("mask:", "")
        ansFix = ansFix?.replace("<mask>", "").replace("<mask>:", "")
        ansFix = ansFix?.replace("(mask)", "").replace("(mask):", "")
        if (ansFix?.startsWith(" {") || ansFix?.startsWith("{")) {
            logger.debug("initial genneration:" + ansFix)
            let newAns = await this.parseImportInfos(CODE, ansFix)
            if (newAns != null) {
                ansFix = newAns.replace("mask:", "")
            }
        }
        else {
            if (ansFix != undefined) {
                ansFix = await this.getSimiliarData(CODE, ansFix ? ansFix : "");
            }
        }
        return this.fixAns(ansFix);
    }

    private fixAns(ans: any): string {
        let replaceData = {}
        ans = ans.replace("mask:", "")
        ans = ans.replace("<mask>", "").replace("<mask>:", "")
        ans = ans.replace("(mask)", "").replace("(mask):", "")
        ans = ans.trim();
        ans = ans.replace("RefObject", "MutableRefObject")
        if (isQuotedUnionBySplit(ans)) {
            ans = "string"
        }
        // ans = ans.replace("Record<string, any>", "object")
        if (ans == "any") {
            ans = "object"
        } else if (ans.startsWith("(") && ans.endsWith(")")) {
            ans = ans.slice(1, -1)
        }
        return ans
    }
    async parseImportInfos(code: string, generation: string) {
        const project = new Project();
        const sourceFile = project.createSourceFile("temp.ts", code);
        var importInfos = sourceFile.getDescendantsOfKind(SyntaxKind.ImportDeclaration)
        let tpPackageLoader = new ThirdPackageLoader(importInfos)
        var interfaceInfo = sourceFile.getDescendantsOfKind(SyntaxKind.InterfaceDeclaration)
        let ans0: Set<any> = new Set();
        if (this.filePath != "") {
            ans0 = this.projectDataLoader.targetFileData(this.filePath, generation)
        }

        let ans: any[] = []
        if (ans0.size == 0) {
            ans = this.projectDataLoader.parseImportInfo(importInfos, generation);
        }
        else {
            ans0.forEach(item => ans.push(item))
        }
        let ans2 = tpPackageLoader.getRecomendType(generation)
        let extra_prompt = "The possible types analyzed from the import information are: "
        if (ans.length > 0 || ans2.length > 0) {
            for (const t of ans) {
                extra_prompt = extra_prompt + "\n" + t.code
            }
            for (const t of ans2) {
                extra_prompt = extra_prompt + "\n" + t
            }
            let extra_prompts = [extra_prompt];
            let newAns = await this.Generation(extra_prompts, code)
            return newAns
        }
        else {
            return generation
        }

    }

    async getSimiliarData(CODE: string, generation: string): Promise<string> {
        const project = new Project();
        const sourceFile = project.createSourceFile("temp.ts", CODE);
        var importInfos = sourceFile.getDescendantsOfKind(SyntaxKind.ImportDeclaration)
        let ans = this.projectDataLoader.findWordSimilarity(CODE, generation)
        let tpPackageLoader = new ThirdPackageLoader(importInfos)
        let ans2 = tpPackageLoader.getRecomendType(generation)
        if (ans.length > 0 || ans2.length > 0) {
            let extra_prompt = "The possible types analyzed from the import information are: "
            for (const t of ans) {
                extra_prompt = extra_prompt + "\n" + t
            }
            for (const t of ans2) {
                extra_prompt = extra_prompt + "\n" + t
            }
            let extra_prompts = [extra_prompt];
            let newAns = await this.Generation(extra_prompts, CODE)
            if (newAns != undefined) {
                return newAns
            }
            else {
                return generation
            }
        }
        return generation;
    }
    public getTotalPrompt() {
        return this.total_prompt;
    }
    private ansFix(res: string) {
        let newRes = res.replace("mask:", "")
    }
}

async function main() {
    let LLMA: LLMAgent = new LLMAgent()
}
// main()