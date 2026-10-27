import { act, fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { CopyButton } from "./CopyButton";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("CopyButton", () => {
  it("copies the text, says so, then comes back to its label", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<CopyButton text="mlk_secret" label="Copy the key" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    expect(writeText).toHaveBeenCalledWith("mlk_secret");
    expect(screen.getByRole("button")).toHaveClass("copy-copied");
    expect(screen.getByRole("button")).toHaveTextContent("Copied");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("button")).toHaveTextContent("Copy the key");
    expect(screen.getByRole("button")).not.toHaveClass("copy-copied");
  });

  it("says the copy failed when the browser offers no clipboard", () => {
    vi.stubGlobal("navigator", {});
    render(<CopyButton text="mlk_secret" label="Copy the key" />);

    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByRole("button")).toHaveClass("copy-failed");
    expect(screen.getByRole("status")).toHaveTextContent(/select the text and copy it by hand/);
  });

  it("says the copy failed when the browser refuses it", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("refus")) } });
    render(<CopyButton text="mlk_secret" label="Copy the key" />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    expect(screen.getByRole("button")).toHaveTextContent("Copy failed");
  });
});
