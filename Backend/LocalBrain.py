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
                "You have no live internet knowledge. For current facts suggest 'search for ...'. "
                "Your role here is to answer or draft text. Do not claim you opened files, changed settings, sent messages, "
                "or performed other desktop actions. A separate command engine handles real actions. "
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
            return "I am Jarvis, your local desktop assistant. Your commands and conversations are processed on this computer."
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
