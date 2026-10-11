"""Transcribe scanned pages (page images with no text layer) with Claude.

Each page is rendered to PNG and transcribed with the plugin's vision_prompt, reusing
SlidesToLectures' vision step. Results are cached per page in <materials dir>/.cache/, so re-runs
only call the API for pages not yet transcribed; delete a cached file to redo that page.

Needs ANTHROPIC_API_KEY (or another credential the Anthropic SDK can find).
"""

import asyncio
import re

import pymupdf
from slidestolectures.vision import CONCURRENCY, render

from .extract import short
from .report import PrintReporter

HEADING = re.compile(r"^#+ +(.+)$", re.MULTILINE)
# Run-in labels such as **Theorem 6.** or <u>Definition</u>. : capitalized, ending in a period inside
# or just after the markup, at the start of a line or after a sentence.
LABEL = re.compile(
    r"(?:^|(?<=[.:]\s))(?:\*\*|<u>)([A-Z][^*<\n]{0,38}?)(?:\.(?:\*\*|</u>)|(?:\*\*|</u>)\.)", re.MULTILINE
)
MAX_LABELS = 3


def cache_path(cache_dir, section):
    page = section.locator.removeprefix("page ")
    return cache_dir / re.sub(r"[^A-Za-z0-9._-]+", "_", section.source) / f"page-{page}.md"


def plain(text):
    return " ".join(re.sub(r"[*_$`]|</?u>", "", text).split()).strip(" .:")


def apply(section, text):
    """Fill in a scanned section's body and title from its transcription.

    Pages of notes often start mid-sentence, so the title is the page's first heading, else its bold
    labels ("Theorem 6, Definition, Theorem 7"), else "Page N". Headings in the body are demoted
    below the "## [N]" section headings.
    """
    labels = list(dict.fromkeys(label for m in LABEL.finditer(text) if (label := plain(m.group(1)))))
    if m := HEADING.search(text):
        section.title = short(plain(m.group(1)))
    elif labels:
        section.title = short(", ".join(labels[:MAX_LABELS]) + (", …" if len(labels) > MAX_LABELS else ""))
    else:
        section.title = section.locator.capitalize()
    section.body = re.sub(r"^#{1,2} ", "### ", text, flags=re.MULTILINE)


async def transcribe(client, sem, model, prompt, image, label, reporter):
    """SlidesToLectures' vision request for one page image, reporting the response's token usage."""
    async with sem:
        response = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
    usage = response.usage
    reporter.usage(
        "anthropic",
        response.model or model,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"{label}: stopped with {response.stop_reason}")
    reporter.log(f"  {label}")
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def _run(plugin, scanned, input_dir, cache_dir, model, reporter):
    import anthropic

    sem = asyncio.Semaphore(CONCURRENCY)
    prompt = plugin.vision_prompt()
    docs = {}
    done = 0

    async with anthropic.AsyncAnthropic() as client:

        async def page(lecture, n, section):
            nonlocal done
            cached = cache_path(cache_dir, section)
            if not cached.exists():
                doc = docs.setdefault(section.source, pymupdf.open(input_dir / section.source))
                image = render(doc[int(section.locator.removeprefix("page ")) - 1])
                label = f"[{n}] {lecture.name} {section.locator}"
                text = await transcribe(client, sem, model, prompt, image, label, reporter)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(text + "\n")
            apply(section, cached.read_text().strip())
            done += 1
            reporter.step("vision", done, len(scanned))

        try:
            await asyncio.gather(*(page(*item) for item in scanned))
        finally:
            for doc in docs.values():
                doc.close()


def run(plugin, scanned, input_dir, cache_dir, model=None, reporter=None):
    """Transcribe scanned, a list of (lecture, N, Section), filling in each section.

    Progress (per page), messages and each request's Claude usage go to reporter (default: print
    messages).
    """
    reporter = reporter or PrintReporter()
    todo = sum(not cache_path(cache_dir, s).exists() for _, _, s in scanned)
    reporter.log(f"{len(scanned)} scanned pages, {todo} to transcribe with Claude")
    asyncio.run(_run(plugin, scanned, input_dir, cache_dir, model or plugin.vision_model, reporter))
