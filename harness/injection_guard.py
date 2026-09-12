"""
Защита от промпт-инъекций.
Эвристики — вспомогательный сигнал. Основная защита архитектурная
(см. agent_loop: neutralize_data_block + блокировка read-after-write).

_TAG_RE покрывает широкий набор ролевых тегов, используемых разными
линейками моделей (OpenAI tool calling, Anthropic function calling,
Ollama, локальные fine-tuned варианты), а не только «канонический»
список. Любой тег из этого набора в данных экранируется, чтобы
модель не могла «выйти» из data-блока.
"""

from __future__ import annotations

import re
import unicodedata


# Невидимые и управляющие Unicode-символы.
# Покрывает: zero-width (200B-200F), bidi embedding/override (202A-202E),
# word joiner и invisible operators (2060-206F, включая directional
# isolates 2066-2069), soft hyphen (00AD), variation selectors
# (FE00-FE0F, E0100-E01EF), interlinear annotation (FFF9-FFFB),
# Mongolian vowel separator (180E).
_INVISIBLE = re.compile(
    "["
    "\u00ad"                    # soft hyphen
    "\u180e"                    # Mongolian vowel separator
    "\u200b-\u200f"             # zero-width space/joiners/marks
    "\u202a-\u202e"             # bidi embedding/override
    "\u2060-\u206f"             # word joiner, invisible ops, directional isolates
    "\ufe00-\ufe0f"             # variation selectors
    "\ufeff"                    # BOM / zero-width no-break space
    "\ufff9-\ufffb"             # interlinear annotation
    "\U000E0100-\U000E01EF"     # variation selectors supplement
    "]"
)

# Гомоглифы: кириллица, греческий, fullwidth → ASCII.
# Это вспомогательный сигнал: полный набор UNICODE TR39 confusables
# слишком велик для str.maketrans. NFKC-нормализация закрывает
# большинство математических и fullwidth форм; таблица ниже
# добавляет частые кириллические и греческие замены.
_HOMOGLYPHS = str.maketrans({
    # Cyrillic → Latin
    "а":"a","в":"b","е":"e","к":"k","м":"m","н":"h","о":"o","р":"p",
    "с":"c","т":"t","у":"y","х":"x","і":"i","ј":"j","ѕ":"s","һ":"h",
    "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P",
    "С":"C","Т":"T","У":"Y","Х":"X","І":"I","Ј":"J","Ѕ":"S","Һ":"H",
    # Greek → Latin
    "α":"a","ο":"o","ρ":"p","ν":"v","τ":"t",
    "Α":"A","Ο":"O","Ρ":"P","Ν":"N","Τ":"T",
    # Fullwidth → ASCII (NFKC покрывает большую часть, это — подстраховка)
    "ａ":"a","ｅ":"e",
    # Dotless i и small Roman numerals
    "ı":"i","ⅰ":"i","ⅱ":"ii","ⅲ":"iii",
})

# Ролевые теги, которые могут быть использованы как маркеры ролей.
# Расширено относительно «канонического» списка:
#   * OpenAI-стиль: system, assistant, user, tool, tool_result
#   * Anthropic-стиль: function_calls, function_results, tool_use, tool_uses
#   * Qwen/Mistral fine-tune: tool_call, tool_calls, tool_response,
#     tool_responses, tool_output, tool_outputs
#   * Разные fine-tuned модели: instruction, result, response, output,
#     prompt, context, thought, function_call, function_result
#
# `\b` после группы — чтобы `<toolbar>`, `<toolbox>`, `<systemd>`,
# `<tools>` не экранировались как ролевые теги. `_` — word-символ,
# поэтому `tool\b` НЕ матчит `tool_call`: для tool-подобных тегов
# все нужные варианты перечислены явно.
#
# Известный over-reach, оставленный сознательно: `<user-agent>` и
# `<response-time>` всё равно матчатся — `-` после `user`/`response`
# даёт word boundary, дальше `[^>]*` добирает `-agent`/`-time`.
# Эти теги встречаются реже в обычном содержимом workspace, а
# over-aggressive escaping безопаснее under-aggressive.
_TAG_RE = re.compile(
    r"</?(?:"
    # tool_* — все варианты явно, длинные перед коротким `tool`.
    r"tool_responses|tool_response|"
    r"tool_results|tool_result|"
    r"tool_outputs|tool_output|"
    r"tool_calls|tool_call|"
    r"tool_uses|tool_use|"
    r"tool|"
    # function_* — аналогично.
    r"function_calls|function_call|"
    r"function_results|function_result|"
    # Остальные ролевые маркеры. Длинные перед короткими для читателя.
    r"results|result|"
    r"system|assistant|user|instruction|"
    r"response|output|prompt|context|thought"
    r")\b[^>]*>",
    re.IGNORECASE,
)

_FENCE_RE = re.compile(r"`{3,}")

# Подозрительные конструкции в пользовательском вводе.
_SUSPICIOUS = [
    re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior|above)", re.I),
    re.compile(r"forget\s+(?:everything|all|previous)", re.I),
    re.compile(r"new\s+(?:system\s+)?(?:instructions?|prompt|rules)", re.I),
    re.compile(r"reveal\s+(?:your\s+)?(?:system\s+)?prompt", re.I),
    re.compile(r"show\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?prompt", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:a|an)\b", re.I),
    re.compile(r"act\s+as\s+(?:a|an)\s+(?:dan|jailbreak|developer\s+mode)", re.I),
]

# Опасные шаблоны в СОДЕРЖИМОМОМ файла, который модель предлагает записать.
# Расширения уже отсекаются на уровне fs_guard; здесь ловим обфускацию
# через .txt/.md.
_DANGEROUS_PAYLOAD = [
    re.compile(r"\bcurl\s+[^\n]{0,200}\|\s*(?:ba|z|da)?sh\b", re.I),
    re.compile(r"\bwget\s+[^\n]{0,200}\|\s*(?:ba|z|da)?sh\b", re.I),
    re.compile(r"\bchmod\s+\+x\b", re.I),
    re.compile(r"\brm\s+-rf\s+/(?!\w)", re.I),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;:"),                    # fork bomb
    re.compile(r"\beval\s*\(", re.I),
    re.compile(r"\bos\.system\s*\(", re.I),
    re.compile(r"\bsubprocess\.(?:run|Popen|call|check_output)\s*\(", re.I),
    re.compile(r"\bbase64\s+-d\b[^\n]{0,100}\|\s*(?:ba|z)?sh\b", re.I),
]


class InjectionGuard:

    # ---------------------- normalization ---------------------------------

    def normalize(self, text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", text)
        text = _INVISIBLE.sub("", text)
        text = text.translate(_HOMOGLYPHS)
        return text

    # ---------------------- input screening -------------------------------

    def is_suspicious(self, text: str) -> bool:
        """Сигнал, что пользовательский ввод содержит классические инъекции."""
        if not text:
            return False
        # Наличие невидимых символов в исходном тексте — подозрительно.
        if _INVISIBLE.search(text):
            return True
        n = self.normalize(text)
        return any(p.search(n) for p in _SUSPICIOUS)

    # ---------------------- data block neutralization ---------------------

    def neutralize_data_block(self, text: str) -> str:
        """
        Жёсткая нейтрализация ДАННЫХ, вставляемых в контекст как tool_result.

        Модель не должна увидеть:
        * XML-подобные теги ролей (system, assistant, user, tool_result,
          function_calls, tool_use, tool_call, ... — широкий набор)
        * тройные бэктики (могут «закрыть» data-блок)

        Обычные HTML-теги, начинающиеся на ролевые префиксы
        (<toolbar>, <toolbox>, <systemd>, <tools>), НЕ экранируются
        благодаря `\\b` после группы альтернатив — fidelity сохранена.
        """
        if not text:
            return ""
        text = _TAG_RE.sub(
            lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"),
            text,
        )
        text = _FENCE_RE.sub("'''", text)
        return text

    # ---------------------- payload screening -----------------------------

    def scan_payload(self, content: str) -> str | None:
        """Возвращает строку-причину или None, если содержимое безопасно."""
        if not content:
            return None
        n = self.normalize(content)
        for p in _DANGEROUS_PAYLOAD:
            if p.search(n):
                return p.pattern
        return None
