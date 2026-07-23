export class PdfTextExtractionError extends Error {
  constructor(message = "Couldn't read this PDF") {
    super(message);
    this.name = "PdfTextExtractionError";
  }
}

const MAX_EXTRACTED_TEXT_LENGTH = 50_000;

function getTextItemString(item: unknown): string {
  if (!item || typeof item !== "object" || !("str" in item)) {
    return "";
  }

  const { str } = item as { str?: unknown };
  return typeof str === "string" ? str : "";
}

function appendWithinLimit(
  chunks: string[],
  text: string,
  currentLength: number,
): number {
  const remainingLength = MAX_EXTRACTED_TEXT_LENGTH - currentLength;
  if (!text || remainingLength <= 0) {
    return currentLength;
  }

  const chunk = text.slice(0, remainingLength);
  chunks.push(chunk);
  return currentLength + chunk.length;
}

/**
 * Extracts selectable text from a PDF entirely in the browser.
 */
export async function extractPdfText(file: File): Promise<string> {
  if (typeof window === "undefined") {
    throw new PdfTextExtractionError(
      "PDF text extraction is only available in the browser.",
    );
  }

  try {
    const pdfjs = await import("pdfjs-dist");
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();

    const documentLoadingTask = pdfjs.getDocument({
      data: new Uint8Array(await file.arrayBuffer()),
    });
    const pdfDocument = await documentLoadingTask.promise;

    try {
      const chunks: string[] = [];
      let extractedLength = 0;
      let hasExtractedText = false;

      for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
        if (extractedLength >= MAX_EXTRACTED_TEXT_LENGTH) {
          break;
        }

        const page = await pdfDocument.getPage(pageNumber);
        const textContent = await page.getTextContent();
        let hasPageText = false;

        for (const item of textContent.items) {
          const itemText = getTextItemString(item);
          if (!itemText) {
            continue;
          }

          if (hasPageText) {
            extractedLength = appendWithinLimit(chunks, " ", extractedLength);
          } else if (hasExtractedText) {
            extractedLength = appendWithinLimit(chunks, "\n", extractedLength);
          }

          extractedLength = appendWithinLimit(chunks, itemText, extractedLength);
          hasPageText = true;
          hasExtractedText = true;

          if (extractedLength >= MAX_EXTRACTED_TEXT_LENGTH) {
            break;
          }
        }
      }

      return chunks.join("");
    } finally {
      await pdfDocument.destroy();
    }
  } catch (error) {
    if (error instanceof PdfTextExtractionError) {
      throw error;
    }

    throw new PdfTextExtractionError();
  }
}
