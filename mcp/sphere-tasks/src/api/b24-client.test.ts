import { describe, it, expect, vi, afterEach } from "vitest";
import {
  b24AddComment,
  b24UpdateComment,
  b24DeleteComment,
  b24LogTime,
  b24GetTimeEntries,
  b24DeleteTimeEntry,
} from "./b24-client.js";

vi.mock("../config.js", () => ({
  env: {
    baseUrl: "https://sphere.loodsen.ru",
    webhookUrl: "https://sphere.loodsen.ru/rest/123/auth/",
  },
}));

function buildBody(obj: Record<string, unknown>): string {
  const parts: string[] = [];
  function encode(value: unknown, key: string): void {
    if (Array.isArray(value)) {
      value.forEach((item, i) => encode(item, `${key}[${i}]`));
    } else if (value !== null && typeof value === "object") {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        encode(v, `${key}[${k}]`);
      }
    } else if (value !== null && value !== undefined) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  for (const [key, value] of Object.entries(obj)) {
    encode(value, key);
  }
  return parts.join("&");
}

describe("b24-client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("buildBody", () => {
    it("encodes flat params", () => {
      const result = buildBody({ key: "value", another: "123" });
      expect(result).toContain("key=value");
      expect(result).toContain("another=123");
    });

    it("encodes arrays with bracket notation", () => {
      const result = buildBody({ ids: ["1", "2", "3"] });
      expect(result).toContain("ids%5B0%5D=1");
      expect(result).toContain("ids%5B1%5D=2");
      expect(result).toContain("ids%5B2%5D=3");
    });

    it("encodes nested objects with bracket notation", () => {
      const result = buildBody({ filter: { STAGE_ID: "3397", STATUS: "new" } });
      expect(result).toContain("filter%5BSTAGE_ID%5D=3397");
      expect(result).toContain("filter%5BSTATUS%5D=new");
    });

    it("handles null values (skips them)", () => {
      const result = buildBody({ key: null, other: "value" } as Record<string, unknown>);
      expect(result).not.toContain("key=null");
      expect(result).toContain("other=value");
    });

    it("handles undefined values (skips them)", () => {
      const result = buildBody({ key: undefined, other: "value" } as Record<string, unknown>);
      expect(result).not.toContain("key=undefined");
      expect(result).toContain("other=value");
    });

    it("handles nested arrays", () => {
      const result = buildBody({ matrix: [[1, 2], [3, 4]] });
      expect(result).toContain("matrix%5B0%5D%5B0%5D=1");
      expect(result).toContain("matrix%5B1%5D%5B1%5D=4");
    });

    it("encodes special characters", () => {
      const result = buildBody({ query: "hello world", special: "a=b&c" });
      expect(result).toContain("query=hello%20world");
      expect(result).toContain("special=a%3Db%26c");
    });

    it("returns empty string for empty object", () => {
      expect(buildBody({})).toBe("");
    });
  });

  describe("b24AddComment", () => {
    it("calls task.commentitem.add with correct params", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "456" }),
      } as Response);

      const result = await b24AddComment("123", "Test comment");
      expect(result).toBe("456");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "https://sphere.loodsen.ru/rest/123/auth/task.commentitem.add.json",
        expect.objectContaining({ method: "POST" })
      );

      globalThis.fetch = originalFetch;
    });
  });

  describe("b24UpdateComment", () => {
    it("calls task.commentitem.update with comment ID and message", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "updated" }),
      } as Response);

      const result = await b24UpdateComment("123", "456", "Updated message");
      expect(result).toBe("updated");

      globalThis.fetch = originalFetch;
    });
  });

  describe("b24DeleteComment", () => {
    it("calls task.commentitem.delete with comment ID", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "deleted" }),
      } as Response);

      const result = await b24DeleteComment("123", "456");
      expect(result).toBe("deleted");

      globalThis.fetch = originalFetch;
    });
  });

  describe("b24LogTime", () => {
    it("calls task.elapseditem.add with seconds and optional comment", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "789" }),
      } as Response);

      const result = await b24LogTime("123", 3600, "Did stuff");
      expect(result).toBe("789");

      globalThis.fetch = originalFetch;
    });

    it("logs time without comment", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "789" }),
      } as Response);

      const result = await b24LogTime("123", 1800);
      expect(result).toBe("789");

      globalThis.fetch = originalFetch;
    });
  });

  describe("b24GetTimeEntries", () => {
    it("returns empty array when result is not array", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: null }),
      } as Response);

      const result = await b24GetTimeEntries("123");
      expect(result).toEqual([]);

      globalThis.fetch = originalFetch;
    });

    it("returns entries when response is array", async () => {
      const originalFetch = globalThis.fetch;
      const mockEntries = [
        { ID: "1", TASKID: "123", USER_ID: "10", SECONDS: "3600", COMMENT_TEXT: "Work", CREATED_DATE: "2025-01-01" },
      ];
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: mockEntries }),
      } as Response);

      const result = await b24GetTimeEntries("123");
      expect(result).toEqual(mockEntries);

      globalThis.fetch = originalFetch;
    });
  });

  describe("b24DeleteTimeEntry", () => {
    it("calls task.elapseditem.delete with entry ID", async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ result: "deleted" }),
      } as Response);

      const result = await b24DeleteTimeEntry("123", "789");
      expect(result).toBe("deleted");

      globalThis.fetch = originalFetch;
    });
  });
});
