"""Read local documents as data and retain page-addressable retrieval chunks.

Offsets refer to the normalized ``ParsedPage.text``, not PDF byte offsets.
The parser performs no OCR, follows no document instructions and uses no network.
"""
from dataclasses import dataclass
from pathlib import Path
import re


MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 2000
MAX_DOCUMENT_CHARACTERS = 5_000_000
MAX_CHUNKS = 25_000
_NUMBER = r"零〇一二三四五六七八九十百千万两\d"
_CHAPTER = re.compile(rf"^(第[{_NUMBER}]+[编部章节篇])(?:\s*.*)?$")
_ARTICLE = re.compile(rf"^(第[{_NUMBER}]+条)")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_LIST_ITEM = re.compile(r"^(?:[-*+]\s+|[（(]?[一二三四五六七八九十\d]+[、.)）]\s*)")
_PAGE_NUMBER = re.compile(r"^\s*[-—–－]?\s*(\d{1,4}|[ivxlcdmIVXLCDM]{1,8})\s*[-—–－]?\s*$")


class DocumentParseError(ValueError):
    """The source cannot safely be parsed as one of the supported document types."""


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    page_label: str | None
    text: str
    needs_ocr: bool = False


@dataclass(frozen=True)
class TextChunk:
    text: str
    chapter: str | None
    page_number: int
    page_label: str | None
    start_offset: int
    end_offset: int
    ordinal: int


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    pages: list[ParsedPage]
    chunks: list[TextChunk]
    warnings: list[str]
    source_type: str = "pdf"


def _heading(text: str) -> tuple[str, str] | None:
    first = text.split("\n", 1)[0].strip()
    markdown = _MARKDOWN_HEADING.match(first)
    if markdown and len(first) <= 100:
        return "chapter", markdown.group(2).strip()
    article = _ARTICLE.match(first)
    if article:
        return "article", article.group(1)
    if len(first) <= 100 and _CHAPTER.match(first):
        return ("section" if re.match(rf"^第[{_NUMBER}]+节", first) else "chapter"), first
    return None


def normalize_text(raw: str) -> str:
    """Merge layout wrapping while retaining paragraph, list and legal headings."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").replace("\x00", "")
    paragraphs: list[str] = []
    pending = ""

    def flush() -> None:
        nonlocal pending
        if pending:
            paragraphs.append(pending)
            pending = ""

    for raw_line in raw.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            flush()
            continue
        if _heading(line) is not None or _LIST_ITEM.match(line):
            flush()
            pending = line
            continue
        if re.fullmatch(rf"第[{_NUMBER}]+[编部章节篇]", pending) and len(line) <= 60 and not line.endswith(("。", "！", "？", "；", ";")):
            # Many PDFs place the chapter number and title on separate lines.
            pending += " " + line
            flush()
            continue
        if pending and (_heading(pending) is not None and not _ARTICLE.match(pending)):
            flush()
        if pending and pending.endswith(("。", "！", "？", ";", "；", "!", "?")):
            flush()
        if pending:
            # Keep English word boundaries; Chinese layout wraps need no space.
            separator = " " if re.search(r"[A-Za-z0-9]$", pending) and re.match(r"[A-Za-z0-9]", line) else ""
            pending += separator + line
        else:
            pending = line
    flush()
    return "\n\n".join(paragraphs)


def _table_text(rows: list[list[str | None]]) -> str:
    """Repeat column headings per row so a retrieved cell retains its meaning."""
    cleaned = [[re.sub(r"\s+", " ", cell or "").strip() for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return " | ".join(cell for cell in cleaned[0] if cell)
    headers = cleaned[0]
    lines = ["表格列：" + " | ".join(headers)]
    for row in cleaned[1:]:
        cells = [f"{headers[index] if index < len(headers) and headers[index] else '列' + str(index + 1)}：{cell}"
                 for index, cell in enumerate(row) if cell]
        if cells:
            lines.append("；".join(cells))
    return "\n\n".join(lines)


def _mostly_within(block, rectangle) -> bool:
    left, top, right, bottom = block[:4]
    overlap = max(0, min(right, rectangle[2]) - max(left, rectangle[0])) * max(0, min(bottom, rectangle[3]) - max(top, rectangle[1]))
    area = max(0, right - left) * max(0, bottom - top)
    return area > 0 and overlap / area >= 0.8


def _footer(block, width: float, height: float) -> str | None:
    if block[1] < height * 0.87:
        return None
    value = str(block[4]).strip()
    match = _PAGE_NUMBER.fullmatch(value)
    # Book layouts commonly put dashed footers at alternating outer margins.
    # Bare numbers are less reliable and must be very low and centered.
    dashed = re.fullmatch(r"[-—–－]\s*(?:\d{1,4}|[ivxlcdmIVXLCDM]{1,8})\s*[-—–－]", value)
    if not dashed and (block[1] < height * 0.91 or abs((block[0] + block[2]) / 2 - width / 2) > width * 0.25):
        return None
    return match.group(1) if match else None


def _parse_pdf(path: Path) -> tuple[list[ParsedPage], list[str]]:
    try:
        import pymupdf
    except ImportError:
        raise DocumentParseError("PDF 解析依赖 PyMuPDF 尚未安装") from None

    warnings: list[str] = []
    pages: list[ParsedPage] = []
    try:
        document = pymupdf.open(path)
    except Exception:
        raise DocumentParseError("PDF 无法打开，文件可能已损坏") from None
    try:
        if document.needs_pass:
            raise DocumentParseError("不支持加密或需要密码的 PDF")
        if not 1 <= document.page_count <= MAX_PDF_PAGES:
            raise DocumentParseError("PDF 页数为空或超过允许上限")
        explicit_labels = bool(document.get_page_labels())
        character_count = 0
        for index in range(document.page_count):
            page = document.load_page(index)
            blocks = [block for block in page.get_text("blocks", sort=True) if len(block) < 7 or block[6] == 0]
            footers = [label for block in blocks if (label := _footer(block, page.rect.width, page.rect.height))]
            label = str(page.get_label()).strip() if explicit_labels else ""
            page_label = label or (footers[0] if len(set(footers)) == 1 else None)
            tables = []
            try:
                # Extract while the page is alive; TableFinder objects are not retained.
                for table in page.find_tables().tables:
                    text = _table_text(table.extract())
                    if text:
                        tables.append((tuple(table.bbox), text))
            except Exception:
                warnings.append(f"PDF 第 {index + 1} 页表格结构提取失败，保留普通文本，需人工检查")
            fragments = []
            for block in blocks:
                if _footer(block, page.rect.width, page.rect.height):
                    continue
                if any(_mostly_within(block, bbox) for bbox, _ in tables):
                    continue
                fragments.append((block[1], block[0], str(block[4]).strip(), False))
            fragments.extend((bbox[1], bbox[0], text, True) for bbox, text in tables)
            fragments.sort(key=lambda fragment: (round(fragment[0], 1), fragment[1]))
            segments, pending = [], []
            for _, _, fragment_text, is_table in fragments:
                if is_table:
                    if pending:
                        segments.append(normalize_text("\n".join(pending)))
                        pending = []
                    segments.append(fragment_text)
                elif fragment_text:
                    pending.append(fragment_text)
            if pending:
                segments.append(normalize_text("\n".join(pending)))
            text = "\n\n".join(segment for segment in segments if segment)
            has_images = bool(page.get_images())
            needs_ocr = has_images and len(re.sub(r"\W", "", text)) < 20
            if needs_ocr:
                warnings.append(f"PDF 第 {index + 1} 页疑似扫描或图片页，待识别；未执行 OCR")
            elif has_images:
                warnings.append(f"PDF 第 {index + 1} 页含图片，图中文字或附件未识别")
            elif not text:
                warnings.append(f"PDF 第 {index + 1} 页无可提取文本")
            pages.append(ParsedPage(index + 1, page_label, text, needs_ocr))
            character_count += len(text)
            if character_count > MAX_DOCUMENT_CHARACTERS:
                raise DocumentParseError("文档提取文本超过允许上限")
    except DocumentParseError:
        raise
    except Exception:
        raise DocumentParseError("PDF 文本解析失败，未生成不完整片段") from None
    finally:
        document.close()
    return pages, warnings


def _chunk_range(text: str, start: int, end: int, size: int, overlap: int):
    while start < end:
        stop = min(start + size, end)
        if stop < end:
            middle = start + max(1, size // 2, overlap + 1)
            boundaries = list(re.finditer(r"[。！？；;\n]", text[middle:stop]))
            if boundaries:
                stop = middle + boundaries[-1].end()
        left, right = start, stop
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            yield left, right
        if stop >= end:
            break
        following = max(left + 1, right - overlap)
        # Avoid a tail consisting only of an overlapped short section.
        start = following if following > start else stop


def chunk_pages(pages: list[ParsedPage], *, chunk_size: int = 700, overlap: int = 100) -> list[TextChunk]:
    """Chunk each page independently, carrying chapter context across pages."""
    if type(chunk_size) is not int or chunk_size < 32 or chunk_size > 4000:
        raise DocumentParseError("片段长度必须为 32 至 4000 个字符")
    if type(overlap) is not int or not 0 <= overlap < chunk_size:
        raise DocumentParseError("重叠长度必须非负且小于片段长度")
    result: list[TextChunk] = []
    chapter = section = article = None
    for page in pages:
        text = page.text
        spans: list[tuple[int, int, str | None]] = []
        section_start = 0
        for match in re.finditer(r"(?:\A|(?<=\n\n))([^\n]+)", text):
            detected = _heading(match.group(1))
            if detected is None:
                continue
            label = " / ".join(part for part in (chapter, section, article) if part) or None
            if match.start() > section_start:
                spans.append((section_start, match.start(), label))
            kind, title = detected
            if kind == "chapter":
                chapter, section, article = title, None, None
            elif kind == "section":
                section, article = title, None
            else:
                article = title
            section_start = match.start()
        label = " / ".join(part for part in (chapter, section, article) if part) or None
        spans.append((section_start, len(text), label))
        for start, end, context in spans:
            for left, right in _chunk_range(text, start, end, chunk_size, overlap):
                if len(result) >= MAX_CHUNKS:
                    raise DocumentParseError("文档片段数量超过允许上限，请调整片段长度或重叠")
                result.append(TextChunk(text[left:right], context, page.page_number,
                                        page.page_label, left, right, len(result)))
    return result


def parse_document(path: str | Path, *, title: str | None = None,
                   chunk_size: int = 700, overlap: int = 100) -> ParsedDocument:
    source = Path(path)
    try:
        size = source.stat().st_size
    except OSError:
        raise DocumentParseError("资料文件不存在或不可读取") from None
    if not source.is_file() or not 0 < size <= MAX_DOCUMENT_BYTES:
        raise DocumentParseError("资料文件为空或超过 50 MiB 上限")
    extension = source.suffix.lower()
    warnings: list[str] = []
    if extension == ".pdf":
        pages, warnings = _parse_pdf(source)
        source_type = "pdf"
    elif extension in {".md", ".markdown", ".txt"}:
        try:
            raw = source.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            raise DocumentParseError("文本资料必须使用 UTF-8 编码") from None
        if len(raw) > MAX_DOCUMENT_CHARACTERS:
            raise DocumentParseError("文档文本超过允许上限")
        pages = [ParsedPage(1, None, normalize_text(raw))]
        source_type = "markdown" if extension != ".txt" else "text"
        if source_type == "markdown" and re.search(r"!\[[^\]]*\]\([^)]*\)|<img\b", raw, re.IGNORECASE):
            warnings.append("Markdown 含图片引用，图片附件未识别；未读取或下载图片")
    else:
        raise DocumentParseError("仅支持文本型 PDF、Markdown 和 TXT")
    chunks = chunk_pages(pages, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        warnings.append("资料没有可入库的文本片段；扫描页或图片附件需另行识别")
    document_title = title.strip() if title and title.strip() else source.stem
    return ParsedDocument(document_title, pages, chunks, warnings, source_type)
