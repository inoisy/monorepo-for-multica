declare module 'turndown' {
  interface Options {
    headingStyle?: 'setext' | 'atx';
    hr?: string;
    bulletListMarker?: '-' | '+' | '*';
    codeBlockStyle?: 'indented' | 'fenced';
    fence?: '```' | '~~~';
    emDelimiter?: '_' | '*';
    strongDelimiter?: '__' | '**';
    linkStyle?: 'inlined' | 'referenced';
    linkReferenceStyle?: 'full' | 'collapsed' | 'shortcut';
  }

  class TurndownService {
    constructor(options?: Options);
    turndown(html: string): string;
    use(plugin: (service: TurndownService) => void): this;
    addRule(key: string, rule: { filter: string | string[] | ((node: HTMLElement) => boolean); replacement: (content: string, node: HTMLElement) => string }): this;
    keep(filter: string | string[]): this;
    remove(filter: string | string[]): this;
  }

  export = TurndownService;
}
