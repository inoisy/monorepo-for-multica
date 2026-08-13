export interface RawFetchResult {
  html: string;
  contentType: string;
  needsRendering: boolean;
}

export interface IHttpFetcher {
  fetch(url: string): Promise<RawFetchResult>;
}

export interface IRenderer {
  render(url: string, timeout?: number): Promise<string>;
}

export interface IExtractor {
  extract(html: string, url: string): Promise<string>;
}
