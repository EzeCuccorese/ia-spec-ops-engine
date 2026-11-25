import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownView } from "../components/MarkdownView";

describe("MarkdownView", () => {
  it("renders headings and clickable wikilinks without interpreting raw HTML", () => {
    const onLink = vi.fn();
    render(
      <MarkdownView
        text={"# Title\n\nSee [[other-note]] and <script>alert(1)</script>"}
        onWikilinkClick={onLink}
      />
    );
    expect(screen.getByText("Title").tagName).toBe("H1");
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeTruthy();
    fireEvent.click(screen.getByText("[[other-note]]"));
    expect(onLink).toHaveBeenCalledWith("other-note");
  });
});
