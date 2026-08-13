import { describe, it, expect } from "vitest";
import type { B24CommentRaw, B24AttachmentRaw } from "./b24-client.js";
import { mapCommentsToTyped } from "./task-fetcher-api.js";
import { stripBBCode } from "../utils/format.js";

describe("task-fetcher-api", () => {
  describe("stripBBCode", () => {
    it("strips USER tag and preserves name", () => {
      expect(stripBBCode("[USER=123]John Doe[/USER]")).toBe("@John Doe");
    });

    it("strips URL tag and preserves label", () => {
      expect(stripBBCode("[URL=https://example.com]Click here[/URL]")).toBe("Click here");
    });

    it("strips B (bold) tag and preserves content", () => {
      expect(stripBBCode("[B]bold text[/B]")).toBe("bold text");
    });

    it("strips I (italic) tag and preserves content", () => {
      expect(stripBBCode("[I]italic text[/I]")).toBe("italic text");
    });

    it("strips U (underline) tag and preserves content", () => {
      expect(stripBBCode("[U]underlined text[/U]")).toBe("underlined text");
    });

    it("strips QUOTE tag and preserves content", () => {
      expect(stripBBCode("[QUOTE]quoted text[/QUOTE]")).toBe("quoted text");
    });

    it("strips CODE tag and preserves content", () => {
      expect(stripBBCode("[CODE]const x = 1;[/CODE]")).toBe("const x = 1;");
    });

    it("strips SPOILER tag and preserves content", () => {
      expect(stripBBCode("[SPOILER]hidden text[/SPOILER]")).toBe("hidden text");
    });

    it("strips IMG tag and replaces with placeholder", () => {
      expect(stripBBCode("[IMG]https://example.com/image.png[/IMG]")).toBe("[изображение]");
    });

    it("strips SIZE tag and preserves inner content", () => {
      expect(stripBBCode("[SIZE=16]large text[/SIZE]")).toBe("large text");
    });

    it("strips COLOR tag and preserves inner content", () => {
      expect(stripBBCode("[COLOR=red]red text[/COLOR]")).toBe("red text");
    });

    it("strips FONT tag and preserves inner content", () => {
      expect(stripBBCode("[FONT=Arial]arial text[/FONT]")).toBe("arial text");
    });

    it("strips BR tag", () => {
      expect(stripBBCode("line1[BR]line2")).toBe("line1line2");
    });

    it("strips DISK FILE ID tag silently", () => {
      expect(stripBBCode("[DISK FILE ID=abc123]")).toBe("");
    });

    it("handles nested tags", () => {
      expect(stripBBCode("[B]bold and [I]italic[/I][/B]")).toBe("bold and italic");
    });

    it("collapses 3+ newlines to 2", () => {
      expect(stripBBCode("para1\n\n\n\npara2")).toBe("para1\n\npara2");
    });

    it("trims whitespace", () => {
      expect(stripBBCode("  [B]text[/B]  ")).toBe("text");
    });

    it("returns empty string for null/undefined/empty", () => {
      expect(stripBBCode("")).toBe("");
      expect(stripBBCode(null as unknown as string)).toBe("");
      expect(stripBBCode(undefined as unknown as string)).toBe("");
    });

    it("preserves plain text without tags", () => {
      expect(stripBBCode("plain text without any tags")).toBe("plain text without any tags");
    });

    it("handles case-insensitive tags", () => {
      expect(stripBBCode("[B]bold[/B]")).toBe("bold");
      expect(stripBBCode("[b]bold[/b]")).toBe("bold");
      expect(stripBBCode("[USER=1]John[/USER]")).toBe("@John");
      expect(stripBBCode("[user=1]John[/user]")).toBe("@John");
    });

    it("handles URL with complex href", () => {
      expect(stripBBCode("[URL=https://example.com/path?foo=bar]Link[/URL]")).toBe("Link");
    });

    it("handles multiple tags in one string", () => {
      expect(stripBBCode("[B]bold[/B] and [I]italic[/I] and [URL=http://x]x[/URL]")).toBe("bold and italic and x");
    });
  });

  describe("mapCommentsToTyped", () => {
    it("maps basic comment correctly", () => {
      const raw: B24CommentRaw = {
        ID: "1",
        AUTHOR_ID: "10",
        AUTHOR_NAME: "John Doe",
        POST_MESSAGE: "Test comment",
        POST_DATE: "2025-01-01T10:00:00Z",
      };
      const result = mapCommentsToTyped([raw]);
      expect(result).toEqual([{
        author: "John Doe",
        text: "Test comment",
        date: "2025-01-01T10:00:00Z",
        images: [],
      }]);
    });

    it("uses AUTHOR_ID as fallback for author", () => {
      const raw: B24CommentRaw = {
        ID: "2",
        AUTHOR_ID: "99",
        AUTHOR_NAME: "",
        POST_MESSAGE: "No author name",
        POST_DATE: "2025-01-01T10:00:00Z",
      };
      const result = mapCommentsToTyped([raw]);
      expect(result[0].author).toBe("99");
    });

    it("strips BBCode from comment text", () => {
      const raw: B24CommentRaw = {
        ID: "3",
        AUTHOR_ID: "1",
        AUTHOR_NAME: "Jane",
        POST_MESSAGE: "[B]Bold comment[/B] with [URL=http://x]link[/URL]",
        POST_DATE: "2025-01-01T10:00:00Z",
      };
      const result = mapCommentsToTyped([raw]);
      expect(result[0].text).toBe("Bold comment with link");
    });

    it("maps attachments to images", () => {
      const raw: B24CommentRaw = {
        ID: "4",
        AUTHOR_ID: "1",
        AUTHOR_NAME: "Jane",
        POST_MESSAGE: "Comment with image",
        POST_DATE: "2025-01-01T10:00:00Z",
        ATTACHED_OBJECTS: {
          att1: {
            ATTACHMENT_ID: "1",
            NAME: "screenshot.png",
            SIZE: "1024",
            FILE_ID: "100",
            DOWNLOAD_URL: "/download.php?file=100",
            VIEW_URL: "/view.php?file=100",
          } as B24AttachmentRaw,
        },
      };
      const result = mapCommentsToTyped([raw]);
      expect(result[0].images).toHaveLength(1);
      expect(result[0].images[0].alt).toBe("screenshot.png");
    });

    it("returns empty array for empty input", () => {
      expect(mapCommentsToTyped([])).toEqual([]);
    });

    it("maps multiple comments", () => {
      const raw: B24CommentRaw[] = [
        { ID: "1", AUTHOR_ID: "1", AUTHOR_NAME: "A", POST_MESSAGE: "First", POST_DATE: "2025-01-01T00:00:00Z" },
        { ID: "2", AUTHOR_ID: "2", AUTHOR_NAME: "B", POST_MESSAGE: "Second", POST_DATE: "2025-01-02T00:00:00Z" },
      ];
      const result = mapCommentsToTyped(raw);
      expect(result).toHaveLength(2);
      expect(result[0].author).toBe("A");
      expect(result[1].author).toBe("B");
    });
  });
});
