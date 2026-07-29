from smolagents import Tool


class ExtractPdfTextTool(Tool):
    name = "extract_pdf_text"
    description = (
        "Download a PDF and extract readable text with page numbers. "
        "Use this whenever the primary source is a PDF. "
        "Pass semicolon-separated keywords to return the most relevant pages. "
        "Do not search raw PDF bytes manually."
    )

    inputs = {
        "url": {
            "type": "string",
            "description": "Direct HTTP/HTTPS URL of the PDF."
        },
        "keywords": {
            "type": "string",
            "description": (
                "Semicolon-separated search terms, for example "
                "'fish bag; volume; m^3'. Use an empty string for all pages."
            )
        },
    }

    output_type = "string"

    def forward(self, url: str, keywords: str) -> str:
        import re
        import subprocess

        try:
            import pymupdf as fitz
        except ImportError:
            import fitz

        # 使用 curl，避免当前环境中 requests 的代理问题
        command = [
            "curl",
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "--compressed",
            "--max-time",
            "60",
            "-A",
            "Mozilla/5.0",
            url,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            timeout=70,
        )

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"PDF download failed: {error}")

        pdf_bytes = result.stdout

        if b"%PDF" not in pdf_bytes[:1024]:
            preview = pdf_bytes[:200].decode("utf-8", errors="replace")
            raise ValueError(
                "The downloaded resource is not a PDF. "
                f"Beginning of response: {preview!r}"
            )

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []

        for page_index, page in enumerate(document):
            text = page.get_text("text").strip()

            # 对扫描型页面尝试OCR；没有安装Tesseract时自动跳过
            if len(text) < 40:
                try:
                    text_page = page.get_textpage_ocr(
                        language="eng",
                        dpi=200,
                        full=True,
                    )
                    text = page.get_text(
                        "text",
                        textpage=text_page,
                    ).strip()
                except Exception:
                    pass

            pages.append((page_index + 1, text))

        query_terms = [
            term.strip().lower()
            for term in re.split(r"[;,]", keywords)
            if term.strip()
        ]

        if query_terms:
            scored_pages = []

            for page_number, text in pages:
                lowered = text.lower()
                score = sum(lowered.count(term) for term in query_terms)
                scored_pages.append((score, page_number, text))

            matched = [item for item in scored_pages if item[0] > 0]

            if matched:
                # 返回最相关的8页
                selected = sorted(
                    matched,
                    key=lambda item: (-item[0], item[1]),
                )[:8]
                selected = sorted(selected, key=lambda item: item[1])
                pages_to_return = [
                    (page_number, text)
                    for _, page_number, text in selected
                ]
            else:
                pages_to_return = pages
        else:
            pages_to_return = pages

        output = [
            f"PDF URL: {url}",
            f"Total pages: {len(pages)}",
            f"Keywords: {keywords or '(none)'}",
        ]

        for page_number, text in pages_to_return:
            output.append(f"\n--- PAGE {page_number} ---\n{text}")

        # 防止整篇PDF占用过多上下文
        combined = "\n".join(output)
        return combined[:45000]