"""Question generation with Claude, grounded in the uploaded books for a subject and grade."""

import base64
import json
import logging

import anthropic
from django.conf import settings

from .models import KnowledgeSource, Question

logger = logging.getLogger(__name__)

# The API accepts requests up to 32 MB; base64 adds about a third, so keep raw files well under that.
MAX_TOTAL_SOURCE_BYTES = 22 * 1024 * 1024

SYSTEM_PROMPT = """\
You are an experienced school teacher and exam setter. You write assessment questions for students \
strictly from the textbook material provided to you.

Ground every question in the provided books: do not introduce facts, figures or definitions that are \
not supported by them. Match the vocabulary and depth to the stated grade. Each question must have a \
single, unambiguous correct answer (for long/creative questions, give a model answer or marking points). \
Avoid near-duplicate questions, and spread questions across the requested topic rather than clustering \
on one paragraph.

For multiple-choice questions give exactly four options, with plausible distractors, and make "answer" \
the exact text of the correct option. For true/false questions, "answer" is "True" or "False". For all \
other types, "options" is an empty list.

In "source_reference", name the chapter, section or page the question is based on, as it appears in the book.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source_reference": {"type": "string"},
                },
                "required": ["text", "options", "answer", "explanation", "source_reference"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

LANGUAGES = {"en": "English", "bn": "Bangla (বাংলা)"}


class GenerationError(Exception):
    """A problem the user can act on; the message is shown in the admin."""


def _source_block(source):
    with source.file.open("rb") as fh:
        data = fh.read()
    if source.is_pdf:
        doc_source = {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode("ascii"),
        }
    else:
        doc_source = {"type": "text", "media_type": "text/plain", "data": data.decode("utf-8", errors="replace")}
    return {"type": "document", "source": doc_source, "title": source.title}


def _build_request(sources, *, subject, grade, topic, question_type, difficulty, count, language):
    total = sum(s.file.size for s in sources)
    if total > MAX_TOTAL_SOURCE_BYTES:
        raise GenerationError(
            f"The active books for {subject} / {grade} add up to {total / 1024 / 1024:.0f} MB, which is too "
            "large to send in one request. Deactivate some books or upload individual chapters instead."
        )

    documents = [_source_block(s) for s in sources]
    # Cache the books: repeated generations for the same subject and grade reuse them at a fraction of the cost.
    documents[-1]["cache_control"] = {"type": "ephemeral"}

    type_label = Question.QuestionType(question_type).label
    instructions = (
        f"Subject: {subject}\n"
        f"Grade: {grade}\n"
        f"Topic / chapter: {topic or 'Any part of the provided books'}\n"
        f"Question type: {type_label}\n"
        f"Difficulty: {Question.Difficulty(difficulty).label}\n"
        f"Number of questions: {count}\n"
        f"Write the questions, options, answers and explanations in {LANGUAGES[language]}.\n\n"
        f"Write exactly {count} {type_label.lower()} questions from the books above."
    )
    return [{"role": "user", "content": [*documents, {"type": "text", "text": instructions}]}]


def generate_questions(*, subject, grade, topic, question_type, difficulty, count, language, user):
    """Ask Claude for questions and save them as drafts. Returns the saved Question objects."""
    sources = list(KnowledgeSource.objects.filter(subject=subject, grade=grade, is_active=True))
    if not sources:
        raise GenerationError(
            f"No active books are uploaded for {subject} / {grade}. "
            "Add one under Question bank → Books & knowledge sources first."
        )

    messages = _build_request(
        sources, subject=subject, grade=grade, topic=topic, question_type=question_type,
        difficulty=difficulty, count=count, language=language,
    )

    try:
        client = anthropic.Anthropic()
        with client.beta.messages.stream(
            model=settings.QUESTION_GENERATION_MODEL,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise GenerationError("The Claude API key is missing or invalid. Set ANTHROPIC_API_KEY on the server.")
    except anthropic.PermissionDeniedError:
        raise GenerationError("The Claude API key doesn't have access to this model.")
    except anthropic.RateLimitError:
        raise GenerationError("Claude is busy right now (rate limit). Please try again in a minute.")
    except anthropic.BadRequestError as exc:
        logger.warning("Claude rejected the question request: %s", exc)
        raise GenerationError(f"Claude couldn't process this request: {exc.message}")
    except anthropic.APIStatusError as exc:
        logger.warning("Claude API error %s: %s", exc.status_code, exc)
        raise GenerationError("Claude returned a server error. Please try again shortly.")
    except anthropic.APIConnectionError:
        raise GenerationError("Couldn't reach the Claude API. Check the server's internet connection.")
    except anthropic.AnthropicError as exc:
        logger.warning("Claude client error: %s", exc)
        raise GenerationError("The Claude API isn't configured on this server. Set ANTHROPIC_API_KEY.")

    logger.info(
        "Question generation %s: %s in / %s out tokens, %s cached",
        response._request_id, response.usage.input_tokens, response.usage.output_tokens,
        response.usage.cache_read_input_tokens,
    )

    if response.stop_reason == "refusal":
        raise GenerationError("Claude declined to generate questions for this material.")
    if response.stop_reason == "max_tokens":
        raise GenerationError("The answer was cut off. Try asking for fewer questions at a time.")

    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        items = json.loads(text)["questions"]
    except (ValueError, KeyError, TypeError):
        logger.warning("Unparseable question output (request %s): %r", response._request_id, text[:500])
        raise GenerationError("Claude's reply couldn't be read. Please try again.")

    questions = [
        Question(
            subject=subject,
            grade=grade,
            topic=topic,
            question_type=question_type,
            difficulty=difficulty,
            text=item["text"].strip(),
            options=[o.strip() for o in item["options"]] if question_type == Question.QuestionType.MCQ else [],
            answer=item["answer"].strip(),
            explanation=item["explanation"].strip(),
            source_reference=item["source_reference"].strip()[:255],
            status=Question.Status.DRAFT,
            ai_generated=True,
            created_by=user,
        )
        for item in items
        if item.get("text", "").strip()
    ]
    return Question.objects.bulk_create(questions)
