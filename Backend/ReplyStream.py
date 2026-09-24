"""Incremental visible model output; thought blocks never reach UI or speech."""
import re

class VisibleReply:
    def __init__(self, on_delta=None, max_sentences=None):
        self.on_delta = on_delta
        self.pending = ""
        self.hidden = False
        self.text = ""
        self.max_sentences = max_sentences
        self.complete = False

    def feed(self, piece):
        self.pending += piece
        self._drain()

    def _drain(self, final=False):
        while self.pending:
            tag = "</think>" if self.hidden else "<think>"
            position = self.pending.find(tag)
            if position >= 0:
                if not self.hidden:
                    self._emit(self.pending[:position])
                self.pending = self.pending[position + len(tag):]
                self.hidden = not self.hidden
                continue
            # Retain a suffix that could become a tag in the next token.
            keep = 0
            for length in range(1, min(len(tag), len(self.pending) + 1)):
                if self.pending.endswith(tag[:length]):
                    keep = length
            safe = self.pending[:-keep] if keep else self.pending
            if not self.hidden:
                self._emit(safe)
            self.pending = self.pending[-keep:] if keep else ""
            if final:
                # Incomplete tags / unclosed thought blocks stay private.
                self.pending = ""
            break

    def _emit(self, text):
        if self.complete or not text:
            return
        combined = self.text + text
        if self.max_sentences:
            endings = list(re.finditer(r"[.!?۔؟](?:[\"”’) ]*)(?:\s+)", combined))
            # Numbered list markers are not sentences.
            endings = [match for match in endings
                       if not re.fullmatch(r"\s*\d+", combined[:match.start()].rsplit("\n", 1)[-1])]
            if len(endings) >= self.max_sentences:
                end = endings[self.max_sentences - 1].end()
                text = combined[len(self.text):end]
                self.complete = True
        self.text += text
        if self.on_delta and text:
            self.on_delta(text)

    def finish(self):
        self._drain(final=True)
        return self.text.strip()


def spoken_boundary(text):
    """Wait for sentence endings / newlines, not tokens or decimal points."""
    match = re.search(r"[.!?۔؟](?:[\"”’) ]*)(?:\s+)|\n", text)
    return match.end() if match else 0
