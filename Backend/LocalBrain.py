"""In-process llama.cpp inference. Never connects to a local or remote server."""
from __future__ import annotations
import ast
import operator
import re
import threading
from pathlib import Path
from Backend.Config import Config
from Backend.Tasks import checkpoint
from Backend.ReplyStream import VisibleReply

class ModelUnavailable(RuntimeError):
    pass

# Question forms that reach chat ("i ask you are you able to ...") must never be
# answered with a language-model denial or an invented claim of having acted.
CAPABILITY_QUESTION = re.compile(
    r"\b(?:are you able to|can you|could you|would you|will you|do you know how to|is it possible to|able to)\b", re.I)
CAPABILITY_TASK = re.compile(
    r"\b(?:open|close|play|search|find|youtube|google|browser|website|internet|online|video|music|"
    r"file|folder|window|app|type|click|scroll|volume|reminder|note|screenshot|control|desktop|computer|tasks?)\b", re.I)

def capability_reply() -> str:
    return ("Yes. I can open apps and websites such as YouTube, search the web and YouTube, play music by name, "
            "manage files, notes and reminders, and control your desktop. Say 'open YouTube' or 'play relaxing music' "
            "and I will do it.")

class LocalBrain:
    def __init__(self, config: Config):
        self.config = config
        self._model = None
        self._loaded_path = ""
        self._lock = threading.Lock()
        self.cancelled = threading.Event()

    def ready(self) -> bool:
        path = Path(self.config.settings.llm_path)
        return path.is_file() and path.stat().st_size > 1024 * 1024

    def reply(self, text: str, history: list[dict] | None = None, *, on_delta=None) -> str:
        simple = self._simple_reply(text)
        if simple:
            checkpoint()
            if on_delta:
                on_delta(simple)
            return simple
        if not self.ready():
            raise ModelUnavailable("The local chat model is not installed. Open Settings and download the local models. File, app, note, and reminder commands already work.")
        with self._lock:
            checkpoint()
            self.cancelled.clear()
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise ModelUnavailable("The local AI engine is missing. Run scripts/setup_local.ps1.") from exc
            settings = self.config.settings
            if self._model is None or self._loaded_path != settings.llm_path:
                self._model = Llama(model_path=settings.llm_path, n_ctx=2048, n_threads=settings.llm_threads,
                                    n_threads_batch=settings.llm_threads, verbose=False, use_mmap=True)
                self._loaded_path = settings.llm_path
            system = (
                f"You are {settings.assistant_name}, a helpful local desktop assistant for {settings.user_name}. "
                "Answer directly in 1 or 2 short sentences unless the user asks for detail or a draft. Reply in the user's language. "
                "You are the chat and voice half of an assistant whose command engine really acts on this computer: "
                "it opens apps and websites (YouTube, Google, WhatsApp Web, GitHub and more), searches the web and YouTube, "
                "plays music by name, controls windows, mouse and keyboard, and manages files, notes and reminders. "
                "When the user asks whether you can do a desktop task, answer yes and give the exact command to say, "
                "for example: 'Yes. Say: open YouTube' or 'Yes. Say: play relaxing music'. "
                "Never say you are only a text-based AI. You have no live internet knowledge; for current facts "
                "suggest 'search for ...'. You produce text only, and the command engine performs actions when the "
                "user says a command, so do not claim an action is already done. "
                "If you are unsure, say so. Do not invent results."
            )
            messages = [{"role": "system", "content": system}]
            for item in (history or [])[-6:]:
                if item.get("role") in {"user", "assistant"}:
                    messages.append({"role": item["role"], "content": str(item["content"])[:700]})
            # The current user message is passed explicitly by the command engine.
            messages.append({"role": "user", "content": text[:1800]})
            detailed = bool(re.search(
                r"\b(detail(?:ed|s)?|draft|write|essay|story|code|program|steps|step.by.step|"
                r"list|plan|compare|table|long|continue|more|explain fully)\b|تفصیل|لکھ|فہرست", text, re.I))
            stream = VisibleReply(on_delta, max_sentences=None if detailed else 2)
            generation = self._model.create_chat_completion(messages=messages, stream=True,
                max_tokens=384 if detailed else 160, temperature=0.45, top_p=0.9)
            try:
                for event in generation:
                    checkpoint()
                    if self.cancelled.is_set():
                        return "Stopped."
                    stream.feed(event["choices"][0].get("delta", {}).get("content", "") or "")
                    if stream.complete:
                        break
            finally:
                close = getattr(generation, "close", None)
                if close:
                    close()
            checkpoint()
            answer = stream.finish()
            return answer or "I could not produce a reply. Please try a shorter question."

    def stop(self):
        self.cancelled.set()

    def _simple_reply(self, text: str) -> str | None:
        lowered = text.casefold().strip().rstrip(".?!")
        if lowered in {"hello", "hi", "hey", "salam", "assalam alaikum", "السلام علیکم"}:
            return f"Hello {self.config.settings.user_name}. I am ready. Ask me to open a file, find a document, or set a reminder."
        if lowered in {"who are you", "what is your name", "your name"}:
            return f"I am {self.config.settings.assistant_name}, your local desktop assistant. Your commands and conversations are processed on this computer."
        if CAPABILITY_QUESTION.search(text) and CAPABILITY_TASK.search(text):
            return capability_reply()
        expression = re.sub(r"^(?:what is|calculate|compute)\s+", "", lowered).replace("×", "*").replace("÷", "/")
        if re.fullmatch(r"[\d\s.+*/()%\-]{1,100}", expression):
            try:
                tree = ast.parse(expression, mode="eval")
                if len(list(ast.walk(tree))) > 40:
                    return None
                ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                       ast.Div: operator.truediv, ast.Mod: operator.mod, ast.USub: operator.neg}
                def value(node):
                    if isinstance(node, ast.Constant) and type(node.value) in {int, float} and abs(node.value) < 1e15:
                        return node.value
                    if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
                        return ops[type(node.op)](value(node.operand))
                    if isinstance(node, ast.BinOp) and type(node.op) in ops:
                        result = ops[type(node.op)](value(node.left), value(node.right))
                        if abs(result) > 1e18:
                            raise ValueError("Too large")
                        return result
                    raise ValueError("Unsupported expression")
                return f"The answer is {value(tree.body):g}."
            except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
                return None
        return None
