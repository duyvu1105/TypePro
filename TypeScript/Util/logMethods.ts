import chalk from "chalk";
import * as fs from "fs";


export enum LogLevel {
  DEBUG = 10,
  INFO = 20,
  WARNING = 30,
  ERROR = 40,
  CRITICAL = 50,
}


const levelNames: Record<LogLevel, string> = {
  [LogLevel.DEBUG]: "DEBUG",
  [LogLevel.INFO]: "INFO",
  [LogLevel.WARNING]: "WARNING",
  [LogLevel.ERROR]: "ERROR",
  [LogLevel.CRITICAL]: "CRITICAL",
};

const levelColors: Record<LogLevel, (s: string) => string> = {
  [LogLevel.DEBUG]: chalk.greenBright,
  [LogLevel.INFO]: chalk.blue,
  [LogLevel.WARNING]: chalk.yellow,
  [LogLevel.ERROR]: chalk.red,
  [LogLevel.CRITICAL]: chalk.bgRed.white,
};

export interface LoggerOptions {
  level?: LogLevel;          
  format?: string;            
  timeFormat?: string;        
  filePath?: string;           
  fileAppend?: boolean;       
}

export class Logger {
  private level: LogLevel;
  private format: string;
  private timeFormatOptions: Intl.DateTimeFormatOptions;


  private fileStream?: fs.WriteStream;
  private filePath?: string;
  private fileAppend: boolean = true;

  constructor(options?: LoggerOptions) {
    this.level = options?.level ?? LogLevel.DEBUG;
    this.format = options?.format ?? "{time} | {level} | {file}:{line} | {message}";
    this.timeFormatOptions = {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    };

    if (options?.filePath) {
      this.enableFileLogging(options.filePath, options.fileAppend ?? true);
    }
  }

 
  private getCallerInfo(): { file: string; line: number } {
    const err = new Error();
    const stack = err.stack?.split("\n") || [];
 
    const callerLine = stack[3] || stack[2] || "";
    const match = callerLine.match(/\((.*):([0-9]+):[0-9]+\)$/);
    if (match) {
      return { file: match[1], line: Number(match[2]) };
    }
    return { file: "unknown", line: 0 };
  }


  enableFileLogging(path: string, append: boolean = true) {

    if (this.fileStream) {
      try {
        this.fileStream.end();
      } catch { /* ignore */ }
    }
    this.filePath = path;
    this.fileAppend = append;
    try {
      this.fileStream = fs.createWriteStream(path, { flags: append ? "a" : "w" });
      this.fileStream.on("error", (err) => {

        console.error(`Logger file stream error (${path}):`, err);
      });
    } catch (err) {
      console.error("Failed to create log file stream:", err);
      this.fileStream = undefined;
    }
  }


  disableFileLogging() {
    if (this.fileStream) {
      try {
        this.fileStream.end();
      } catch { /* ignore */ }
    }
    this.fileStream = undefined;
    this.filePath = undefined;
  }


  private log(level: LogLevel, message: string, ...args: any[]) {
    if (level < this.level) return;

    const now = new Date();
    const timeStr = now.toLocaleString("sv-SE", this.timeFormatOptions).replace("T", " ");
    const levelName = levelNames[level];

    const formattedMsg = args.length
      ? message.replace(/%s/g, () => String(args.shift()))
      : message;

    const { file, line } = this.getCallerInfo();

    let output = this.format
      .replace("{time}", timeStr)
      .replace("{level}", levelName)
      .replace("{file}", file)
      .replace("{line}", line.toString())
      .replace("{message}", formattedMsg);


    const colorFn = levelColors[level] || ((s: string) => s);
    console.log(colorFn(output));

    if (this.fileStream) {

      const plain = output.replace(/\x1b\[[0-9;]*m/g, "");
      try {
        this.fileStream.write(plain + "\n");
      } catch (err) {

        console.error("Failed to write log to file:", err);
      }
    }
  }

  debug(message: string, ...args: any[]) {
    this.log(LogLevel.DEBUG, message, ...args);
  }
  info(message: string, ...args: any[]) {
    this.log(LogLevel.INFO, message, ...args);
  }
  warning(message: string, ...args: any[]) {
    this.log(LogLevel.WARNING, message, ...args);
  }
  error(message: string, ...args: any[]) {
    this.log(LogLevel.ERROR, message, ...args);
  }
  critical(message: string, ...args: any[]) {
    this.log(LogLevel.CRITICAL, message, ...args);
  }


  setLevel(level: LogLevel) {
    this.level = level;
  }
}

