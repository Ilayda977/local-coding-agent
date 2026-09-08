"""Sıralı, read-only ajan: keşif -> okuma -> kanıt -> ayrı cevap kontrolü."""
import ast
import builtins
import argparse
import json
import keyword
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

import tools
from navigation import ROUTE_INSTRUCTION, ASSESS_INSTRUCTION, REPAIR_INSTRUCTION, FILE_SUFFIXES
from evidence import EvidenceError, EvidenceStore
from protocol import (
    Assessment, CitationSelection, Draft, DraftClaim, ModelGateway, ProtocolError, Recovery, Review, RouteDecision,
    SearchRequest, Selection, TraceDraft,
    extract_json_object, tool_call_signature,
)

MODEL_NAME = os.environ.get("LOCAL_CODING_AGENT_MODEL", "qwen2.5-coder:7b")
FAST_MODEL_NAME = os.environ.get("LOCAL_CODING_AGENT_FAST_MODEL", "").strip() or None
MODEL_THINK = os.environ.get("LOCAL_CODING_AGENT_THINK", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
MAX_RESEARCH_ROUNDS = 3
# Bir tur eksik kaynağı araştırmak, ikinci tur ise bulunan kanıtla hatalı
# ifadeyi düzeltmek için ayrılır. Döngü bu sabitle kesin olarak sınırlıdır.
MAX_RECOVERY_ROUNDS = 2
# Cümle sonundaki nokta sayıyı geçersiz yapmaz. Ancak ondalık devamı
# veya bir identifier içindeki rakamlar kısmi sayı olarak eşleşmemelidir.
NUMBER_PATTERN = re.compile(r"(?<![\w.])[+-]?\d[\d_]*(?:[.,]\d[\d_]*)?(?!\w)(?![.,]\d)")
SEARCH_TARGET_PATTERN = re.compile(r"(?u)[\w]+(?:[./:-][\w]+)*")
# Bunlar çoğunlukla arama konusu değil, kullanıcının istediği işlemi anlatan
# doğal dil sözcükleridir. Tırnak/code içinde yazılırlarsa yine korunurlar.
SEARCH_NOISE_TERMS = {
    "bu", "şu", "repo", "repoda", "repository", "nerede", "nereye", "hangi",
    "ve", "veya", "ile", "içinde", "içindeki", "bul", "bulunur", "bulunduğu",
    "açıkla", "göster", "ara", "aranır", "çağrılıyor", "çağrılır", "çağrıldığı",
    "model", "modeli", "dosya", "dosyası", "fonksiyon", "fonksiyonu", "tanım",
    "tanımı", "değişken", "değişkeni", "kod", "kodu", "where", "is", "called",
    "find", "explain", "file", "function", "variable", "definition",
    "soru", "sorun", "görev", "yardım", "issue", "problem", "task", "help",
}
UNDERSPECIFIED_REQUEST_TERMS = {
    "soru", "sorun", "görev", "yardım", "issue", "problem", "task", "help",
    "kod", "code", "repo", "repository",
}
STAGE_DESCRIPTIONS = {
    "LIST": "Proje dosyaları listeleniyor.",
    "ROUTE": "Soru anlaşılır ve uygun araştırma yolu seçilir.",
    "SEARCH": "İlgili kod kaynağı aranır.",
    "SELECT": "En ilgili kaynak seçilir.",
    "READ": "Seçilen kodun sınırlı bölümü okunur.",
    "ASSESS": "Okunan kanıtın yeterli olup olmadığı kontrol edilir.",
    "DRAFT": "Kullanıcı cevabı hazırlanır.",
    "REDRAFT": "Yeni kanıtla cevap yeniden hazırlanır.",
    "REVISE": "Cevap mevcut kanıta göre düzeltilir.",
    "CITE": "Cevap değiştirilmeden hatalı maddenin kanıt bağlantısı seçilir.",
    "GROUNDING": "Sayısal iddialar kanıta bağlanır.",
    "VERIFY": "Cevap ayrı bir kontrol aşamasından geçirilir.",
    "RECOVER": "Eksik veya hatalı cevap için onarım yolu seçilir.",
    "RESULT": "Sonuç hazırlandı.",
}


@dataclass
class AgentResult:
    status: str
    question: str
    findings: list = field(default_factory=list)
    reason: str = ""
    stages: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    model_trace: list = field(default_factory=list)
    diagnosis: dict | None = None

    def model_dump(self):
        return asdict(self)


def _findings(draft, store):
    """Model yalnız kanıt kimliklerini seçer; konum ve alıntıyı bu kod oluşturur."""
    return [
        {"answer": claim.answer, "evidence": store.block_citations(claim.evidence_ids)}
        for claim in draft.claims
    ]


EXCLUDED_REFERENCE_SYMBOLS = {
    "handler", "guard", "block", "caller", "callee", "helper",
    "argument", "arguments", "parameter", "parameters", "statement", "statements",
    "true", "false", "none", "return", "raise", "try", "except", "finally",
}


def _reference_grounding_issues(draft, store):
    """Denetim yalnız kaynak aidiyeti içindir; anlam doğruluğu ayrıca incelenir."""
    issues = []
    for claim in draft.claims:
        citations = store.block_citations(claim.evidence_ids)
        source = "\n".join(item["quote"] for item in citations)
        files = {item["file"] for item in citations}
        for file in re.findall(r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.py\b", claim.answer):
            if file not in files and file not in source:
                issues.append(f"Dosya referansı bağlı kanıtta yok: {file}")
        for ref in re.findall(r"`([^`]+)`", claim.answer):
            symbol = ref.removesuffix("()")
            if (symbol.isidentifier() and not keyword.iskeyword(symbol)
                    and symbol not in vars(builtins)
                    and symbol.casefold() not in EXCLUDED_REFERENCE_SYMBOLS
                    and not re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", source)):
                issues.append(f"Kod adı bağlı kanıtta yok: {symbol}")
    return list(dict.fromkeys(issues))


def _short(text, limit=320):
    """Terminal karar özetlerini tek satır ve okunabilir uzunlukta tutar."""
    value = " ".join(str(text).split())
    return value if len(value) <= limit else value[:limit - 3] + "..."


def _number_tokens(text):
    """Kanıt eşleştirmesi için sayıları yazım farklarından arındırır."""
    return {match.group(0).lstrip("+").replace("_", "").replace(",", ".")
            for match in NUMBER_PATTERN.finditer(text)}


def _numeric_grounding_issues(draft, store, question):
    """Bir iddiadaki sayının o iddiaya bağlı kaynakta/soruda bulunmasını zorlar."""
    question_numbers = _number_tokens(question)
    issues = []
    for index, claim in enumerate(draft.claims, 1):
        citations = store.block_citations(claim.evidence_ids)
        evidence_text = "\n".join(
            citation["quote"] for citation in citations
        )
        # Konum metadatası kodun değeri değildir. Satır numaralarını controller
        # ayrıca gösterir; bunlar sayısal bir davranış iddiasını destekleyemez.
        allowed = question_numbers | _number_tokens(evidence_text)
        unsupported = sorted(_number_tokens(claim.answer) - allowed)
        if unsupported:
            issues.append(
                f"İddia {index} içindeki sayısal değer(ler) bağlı kanıtta veya soruda yok: "
                + ", ".join(unsupported)
            )
    return issues


def _numeric_citation_repair_hints(draft, store, question):
    """Eksik sayılar okunmuş başka bloklarda varsa yeniden atıf için aday sun.

    Aynı sayının bulunması anlamsal kanıt değildir; atfı model seçer ve yeniden
    grounding/VERIFY yapılır. Bir değer hiç okunmamışsa bu kestirme kullanılmaz.
    """
    blocks = store.source_context()
    hints = []
    for index, claim in enumerate(draft.claims, 1):
        citations = store.block_citations(claim.evidence_ids)
        cited = '\n'.join(item['quote'] for item in citations)
        missing = _number_tokens(claim.answer) - _number_tokens(cited) - _number_tokens(question)
        for number in sorted(missing):
            candidates = [item['id'] for item in blocks
                          if number in _number_tokens(item['quote'])]
            if not candidates:
                return []
            hints.append({'claim': index, 'value': number, 'candidate_evidence_ids': candidates})
    return hints


def _repair_numeric_citations(draft, store, question, gateway, hints):
    """Yalnız hatalı maddelerin atıflarını bir kez seçtir; metni değiştirme."""
    repaired = draft.model_copy(deep=True)
    for index in sorted({hint['claim'] for hint in hints}):
        claim = repaired.claims[index - 1]
        hint_text = ' '.join(
            f"The number '{h['value']}' occurs in {h['candidate_evidence_ids']}. "
            'These are candidates only; select them only if their code supports this claim.'
            for h in hints if h['claim'] == index
        )
        selection = gateway.ask(
            'CITE', CitationSelection,
            'Select read evidence IDs supporting the ENTIRE claim. Return only evidence_ids. '
            'Include both value definition and usage when both are needed. A matching number '
            'alone is not proof. Do not rewrite the claim. Return [] if the claim is unsupported. '
            + hint_text,
            {'question': question, 'claim': claim.answer, 'current_evidence_ids': claim.evidence_ids,
             'source': store.source_context()}, allowed_ids=list(store.blocks),
        )
        store.block_citations(selection.evidence_ids)
        claim.evidence_ids = list(dict.fromkeys(selection.evidence_ids))
    if _numeric_grounding_issues(repaired, store, question):
        raise EvidenceError('Kanıt bağlantısı onarılamadı; aynı onarım tekrarlanmadı.')
    return repaired


def _condition_grounding_issues(draft, store, question):
    """Açıkça koşul istenince ilgili AST koşulunun eksiksiz aktarılmasını zorlar."""
    if not re.search(r"\b(?:koşul\w*|condition\w*|predicate\w*)\b", question, re.IGNORECASE):
        return []
    conditions = store.observed_conditions()
    if not conditions:
        return ["İstenen koşul okunmuş Python kaynağından çıkarılamadı."]
    question_names = set(SEARCH_TARGET_PATTERN.findall(question))
    scored = [
        (len(question_names & set(SEARCH_TARGET_PATTERN.findall(condition))), condition)
        for condition in conditions
    ]
    best_score = max(score for score, _ in scored)
    relevant = [condition for score, condition in scored if score == best_score]

    def compact(value):
        return re.sub(r"\s+", "", value).replace('"', "'")

    def condition_satisfied(condition, text):
        comp_ans = compact(text)
        if compact(condition) in comp_ans:
            return True
        parts = [p.strip() for p in re.split(r"\s+and\s+", condition, flags=re.IGNORECASE)]
        if len(parts) > 1 and all(compact(part) in comp_ans for part in parts):
            return True
        return False

    answer_text = "\n".join(claim.answer for claim in draft.claims)
    if any(condition_satisfied(condition, answer_text) for condition in relevant):
        return []
    return [
        "İstenen kod koşulu eksik veya değiştirilmiş aktarıldı; ilgili okunmuş koşullardan "
        f"biri eksiksiz verilmelidir: {' | '.join(relevant)}"
    ]


def _mechanism_grounding_issues(draft, store, question):
    """Exception tabanlı guard mekanizmasının eksik/yanlış atfını engeller."""
    if not re.search(r"\b(?:mekanizma\w*|mechanism\w*)\b", question, re.IGNORECASE):
        return []
    flows = [flow for flow in store.observed_exception_flows() if flow["guard_statements"]]
    if not flows:
        return []
    answer = " ".join(claim.answer for claim in draft.claims)
    compact_answer = re.sub(r"\s+", "", answer)

    def handler_statement_is_explained(statement):
        """Kod biçimi ile doğal dildeki eşdeğer handler sonucunu eşleştirir."""
        compact_statement = re.sub(r"\s+", "", statement)
        if compact_statement in compact_answer:
            return True
        try:
            node = ast.parse(statement).body[0]
        except SyntaxError:
            return False
        if isinstance(node, ast.Return):
            value = ast.unparse(node.value) if node.value is not None else "None"
            value_present = re.search(
                rf"(?<!\w){re.escape(value)}(?!\w)", answer, re.IGNORECASE,
            )
            return bool(value_present and re.search(
                r"\b(?:döndür\w*|return\w*)\b", answer, re.IGNORECASE,
            ))
        if isinstance(node, ast.Raise):
            raised = ast.unparse(node.exc) if node.exc is not None else ""
            return bool(raised and raised in answer and re.search(
                r"\b(?:fırlat\w*|yükselt\w*|raise\w*)\b", answer, re.IGNORECASE,
            ))
        return False

    for flow in flows:
        guards = flow["guard_statements"]
        guard_present = any(
            re.sub(r"\s+", "", guard) in compact_answer for guard in guards
        )
        exception_present = any(name in answer for name in flow["caught_exceptions"])
        handler_present = any(handler_statement_is_explained(statement)
                              for statement in flow["handler_statements"])
        if guard_present and exception_present and handler_present:
            return []
    expected = flows[0]
    return [
        "Exception tabanlı kontrol mekanizması eksik: guard ifadesi "
        f"`{' | '.join(expected['guard_statements'])}`, handler'ın yakaladığı uygun exception "
        f"(handler grubu: `{' | '.join(expected['caught_exceptions'])}`) ve handler sonucu "
        f"`{' | '.join(expected['handler_statements'])}` birlikte açıklanmalıdır. Handler grubundaki "
        "her exception türünün aynı protected statement tarafından fırlatıldığını varsayma."
    ]


def _strip_model_line_locations(answer):
    """Modelin yazdığı satır konumlarını siler; kesin konumu controller ekler."""
    value = str(answer)
    patterns = (
        r"\b\d+\s*[-–]\s*\d+\s+(?:satırlar?|lines?)(?:\s+arası)?\s*\)",
        r"\b\d+\s*[-–]\s*\d+\s+(?:satırlar?|lines?)(?:\s+arası)?",
        r"\b(?:satır|line)\s+\d+(?:\s*[-–]\s*\d+)?(?:[.'’a-zıiüuöçğş]*)?",
        r"\b\d+\s*\.\s*(?:satır|line)(?:[.'’a-zıiüuöçğş]*)?",
    )
    for pattern in patterns:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(\s*\)", "", value)
    value = re.sub(r"\s+([,.;:])", r"\1", value)
    return re.sub(r"\s{2,}", " ", value).strip()


def _normalized_intent_token(token):
    """Yalnız yinelenmiş harften doğan açık görev-sözcüğü yazım hatasını düzeltir."""
    folded = token.casefold()
    if folded in SEARCH_NOISE_TERMS:
        return token
    for index in range(1, len(folded)):
        if folded[index] != folded[index - 1]:
            continue
        candidate = folded[:index] + folded[index + 1:]
        if candidate in SEARCH_NOISE_TERMS:
            return candidate
    return token


def _normalize_question(question):
    """Teknik varlıklara dokunmadan yaygın görev sözcüğü yazım hatalarını düzeltir."""
    return SEARCH_TARGET_PATTERN.sub(
        lambda match: _normalized_intent_token(match.group(0)), question,
    )


def _request_validation_error(question):
    """Teknik hedef içermeyen yer tutucu isteklerin araştırma döngüsüne girmesini önler."""
    value = str(question).strip()
    if not value:
        return "Repository'de araştırılacak bir soru veya teknik hedef belirtilmedi."
    tokens = [item.casefold() for item in SEARCH_TARGET_PATTERN.findall(value)]
    if tokens and all(item in UNDERSPECIFIED_REQUEST_TERMS for item in tokens):
        return (
            "İstek yalnızca genel bir görev sözcüğü içeriyor; aranacak dosya, sembol, "
            "literal değer veya açıklanacak kod davranışı belirtilmedi."
        )
    return ""


def _allowed_route_intents(question):
    """Cevabı değil, sorunun istediği araştırma türünü genel dil ipuçlarıyla sınırlar."""
    value = str(question)
    if re.search(
        r"\b(?:çağrıl\w*|aktarıl\w*|iletil\w*|kullanım\s+yeri|call\w*|forward\w*|passed)\b",
        value, re.IGNORECASE,
    ):
        return ["trace_call"]
    if re.search(
        r"\b(?:nasıl|neden|niçin|davran\w*|döndür\w*|olduğunda|değiştiğinde|"
        r"mekanizma\w*|koşul\w*|kanıtla|how|why|behavio\w*|return\w*|when|condition\w*)\b",
        value, re.IGNORECASE,
    ):
        return ["explain_behavior"]
    return [
        "locate_file", "find_definition", "find_references", "trace_call",
        "explain_behavior", "configuration_lookup", "documentation", "general_code_search",
    ]


def _initial_search_targets(question, listing):
    """Router'a yalnız soruda geçen teknik hedefleri verir; dosya adı tahmin ettirmez."""
    question = _normalize_question(question)
    quoted_targets = []
    for quoted in re.findall(r"[`'\"]([^`'\"]+)[`'\"]", question):
        if quoted.strip():
            quoted_targets.append(quoted.strip())
    quoted_folded = {item.casefold() for item in quoted_targets}
    targets = list(quoted_targets)
    for target in SEARCH_TARGET_PATTERN.findall(question):
        # Kod-benzeri yazım (MODEL_NAME, settings.py, model-v2) her zaman
        # korunur. Düz doğal dil görev sözcükleri arama sorgusu değildir.
        code_like = (
            target.isupper()
            or any(character in target for character in "_./:-")
            or any(character.isdigit() for character in target)
        )
        if (target.casefold() in SEARCH_NOISE_TERMS
                and target.casefold() not in quoted_folded
                and not code_like):
            continue
        targets.append(target)
    # Sıra kullanıcı ifadesini korur; casefold yalnız doğal marka/literal aramasına alternatif verir.
    expanded = []
    for target in targets:
        expanded.extend((target, target.casefold()))
    return list(dict.fromkeys(item for item in expanded if item))[:80]


def _initial_search_actions(question, listing):
    """Soru sözdizimine göre güvenli başlangıç aracı–hedef çiftlerini üretir."""
    targets = _initial_search_targets(question, listing)
    listed_paths = {
        line.strip() for line in listing.splitlines()[1:]
        if line.strip() and not line.startswith(" ")
    }
    listed_names = {path.rsplit("/", 1)[-1] for path in listed_paths}
    actions = []
    for target in targets:
        is_file = (
            (target in listed_paths or target in listed_names) and ("/" in target or "." in target)
        ) or PurePosixPath(target.replace("\\", "/")).suffix.casefold() in FILE_SUFFIXES
        if is_file:
            actions.append({"tool": "find_file", "query": target})
            continue

        # Her gerçek soru hedefi literal kod araması olabilir. Sembol araçları
        # yalnız identifier görünümündeki teknik adlara açılır; doğal marka
        # adları veya cümle sözcükleri dosya/simge tahminine çevrilmez.
        actions.append({"tool": "search_code", "query": target})
        mixed_case = not (target.islower() or target.isupper() or target.istitle())
        symbol_like = target.isidentifier() and (
            "_" in target or target.isupper() or mixed_case
        )
        if symbol_like:
            actions.extend((
                {"tool": "find_symbol", "query": target},
                {"tool": "find_references", "query": target},
                {"tool": "find_calls", "query": target},
            ))
    return list({(item["tool"], item["query"]): item for item in actions}.values())


def _preferred_trace_actions(actions, frontier):
    """Çağrı zincirinde her hedef için en anlamlı tek repository aracını seçer."""
    preferred = []
    priority = ("find_symbol", "find_calls", "find_references", "search_code")
    for query in frontier:
        available = [item for item in actions if item["query"] == query]
        for tool_name in priority:
            selected = next((item for item in available if item["tool"] == tool_name), None)
            if selected:
                preferred.append(selected)
                break
    return preferred


def _cli_exit_code(status):
    """Cevap üreten taslak başarılı CLI çalışmasıdır; tamamlanamayanlar hatadır."""
    return 0 if status == "review_required" else 1

BUILTIN_NOISE = {
    "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
    "OSError", "Exception", "BaseException", "RuntimeError",
    "None", "True", "False", "dict", "list", "str", "int", "float", "bool", "tuple", "set"
}

def _prioritize_route_searches(searches, question):
    """Router'ın ürettiği gürültülü veya gereksiz aramaları eler ve yürütme önceliğine göre sıralar."""
    if not searches or len(searches) <= 1:
        return searches

    valid_searches = []
    symbol_or_file_present = any(s.tool in {"find_symbol", "find_file"} for s in searches)

    for s in searches:
        if symbol_or_file_present:
            if s.query in BUILTIN_NOISE:
                print(f"[ROUTE ÖNCELİKLENDİRME] Gürültülü yerleşik tip araması elendi: {s.query!r}")
                continue
            if s.tool == "search_code" and len(s.query.split()) >= 3:
                print(f"[ROUTE ÖNCELİKLENDİRME] Çok sözcüklü nesir araması elendi: {s.query!r}")
                continue
        valid_searches.append(s)

    if not valid_searches:
        valid_searches = searches

    def priority(s):
        if s.tool == "find_symbol":
            if s.query.islower() or "." in s.query or "_" in s.query:
                return 1
            return 2
        if s.tool == "find_file":
            return 3
        if s.tool in {"find_calls", "find_references", "find_tests"}:
            return 4
        return 5

    ordered = sorted(valid_searches, key=priority)
    
    if ordered != searches:
        print(f"[ROUTE ÖNCELİKLENDİRME] Son arama listesi: {[f'{s.tool}({s.query!r})' for s in ordered]}")
    
    return ordered


def run_staged_agent(issue_text, gateway=None, json_output=False):
    """Aşamalar atlanamaz; araştırma hedefleri ve kaynak seçimi modele aittir."""
    gateway = gateway or ModelGateway(
        MODEL_NAME, think=MODEL_THINK, fast_model_name=FAST_MODEL_NAME,
    )
    store = EvidenceStore()
    stages = []
    listing_call = {"tool": "list_files", "directory_path": "."}
    listing_performed = False
    confidence = 0.0

    def print(*args, **kwargs):
        # --json yalnız tek makine-okunabilir sonuç üretir, aşama metni karıştırmaz.
        if not json_output:
            builtins.print(*args, **kwargs)

    def stage(name):
        stages.append(name)
        print(f"\n[{name}] {STAGE_DESCRIPTIONS.get(name, '')}")

    def decision(title, lines):
        """Gizli düşünce zinciri değil, modelin şemalı karar alanlarını gösterir."""
        print(f"[{title}]")
        for line in lines:
            print(f"- {_short(line)}")

    def finish(status, findings=None, reason=""):
        result = AgentResult(
            status=status, question=issue_text, findings=findings or [], reason=reason,
            stages=stages.copy(),
            tool_calls=([listing_call] if listing_performed else []) + store.tool_calls,
            model_trace=gateway.trace.copy(),
        )
        if result.findings:
            evidence = [citation for finding in result.findings for citation in finding["evidence"]]
            result.diagnosis = {
                "issue_summary": issue_text,
                "evidence": evidence,
                "root_cause": "\n".join(item["answer"] for item in result.findings),
                "relevant_files": sorted({item["file"] for item in evidence}),
                "confidence": confidence,
            }
        payload = {
            "status": result.status, "question": issue_text,
            "findings": result.findings, "reason": result.reason,
            "model_calls": len(result.model_trace), "tool_calls": len(result.tool_calls),
            "diagnosis": result.diagnosis,
        }
        if json_output:
            builtins.print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif result.findings:
            print("\n[SONUÇ]")
            for finding in result.findings:
                print(f"- {finding['answer']}")
            print("\n[KANIT KONUMLARI]")
            seen = set()
            for finding in result.findings:
                for citation in finding["evidence"]:
                    location = (
                        citation["file"], citation["start_line"], citation["end_line"]
                    )
                    if location in seen:
                        continue
                    seen.add(location)
                    start, end = citation["start_line"], citation["end_line"]
                    line_text = str(start) if start == end else f"{start}-{end}"
                    print(f"- {citation['file']}:{line_text}")
            print("\n[NOT] Cevap kod kanıtlarıyla kontrol edildi; yine de insan incelemesi önerilir.")
            print(f"[CONFIDENCE] {confidence} — modelin öz değerlendirmesi; doğruluk garantisi değil.")
            print(f"[ÖZET] {len(result.model_trace)} model çağrısı, "
                  f"{len(result.tool_calls)} araç çağrısı.")
        else:
            print("\n[SONUÇ ÜRETİLEMEDİ]")
            print(f"- Neden: {result.reason or 'Yeterli ve doğrulanmış kanıt bulunamadı.'}")
            print(f"- Durum: {result.status}")
        return result

    working_question = _normalize_question(issue_text)
    print(f"\n[ISSUE ALINDI] {issue_text}")
    if isinstance(gateway, ModelGateway):
        gateway.progress = None if json_output else lambda: builtins.print(".", end="", flush=True)
        gateway.report = None if json_output else lambda item: print(
            f"\n[SÜRE] {item['stage']}: {item['seconds']:.1f} sn | "
            f"çıktı: {item.get('output_tokens', '?')} token"
        )
        model_text = gateway.model_name
        if gateway.fast_model_name:
            model_text += f" | hızlı karar modeli: {gateway.fast_model_name}"
        print(f"[MODEL] {model_text} | thinking: "
              f"{'açık' if gateway.think else 'kapalı'}")
    if working_question != issue_text:
        print(f"[SORU NORMALİZASYONU] {working_question}")
    validation_error = _request_validation_error(working_question)
    if validation_error:
        print("\n[GEÇERSİZ İSTEK]")
        print(f"- {validation_error}")
        print('- Örnek: "MODEL_NAME nerede tanımlanıyor ve nerede kullanılıyor?"')
        return finish("invalid_request", reason=validation_error)
    try:
        # Kullanıcının istediği başlangıç sırası; modelin erken cevap vermesi mümkün değil.
        stage("LIST")
        listing = tools.list_files(".")
        listing_performed = True
        if listing.startswith("HATA:"):
            raise EvidenceError(listing)
        print(listing)

        stage("ROUTE")
        allowed_intents = _allowed_route_intents(working_question)
        route = gateway.ask(
            "ROUTE", RouteDecision,
            ROUTE_INSTRUCTION,
            {"question": working_question, "project_listing": listing},
            allowed_intents=allowed_intents,
        )
        decision(
            "AJAN KARARI — ROUTE",
            [f"Niyet: {route.intent}", f"Kaynak politikası: {route.source_policy}",
             f"Varlıklar: {', '.join(route.entities)}", f"Gerekçe: {route.decision_summary}"]
            + [f"Gerekli kanıt: {item}" for item in route.requirements]
            + [f"İlk arama: {item.tool}({item.query!r})" for item in route.searches],
        )
        requests = _prioritize_route_searches(route.searches, working_question)
        candidate_ids = []
        research_rounds = 0
        recovery_rounds = 0
        research_needed = True
        draft_stage = "DRAFT"
        review_issues = []
        review_feedback = {}
        review_facts = None  # İlk bağımsız denetimden sonra kapsam turdan tura kaybolmaz.
        behavior_validation_attempted = set()
        allow_test_candidates = False

        while True:
            while research_needed:
                if research_rounds >= MAX_RESEARCH_ROUNDS:
                    return finish("budget_exhausted", reason="Araştırma turu bütçesi doldu; cevap uydurulmadı.")
                research_rounds += 1
                if requests:
                    stage("SEARCH")
                    candidate_ids = []
                    for request in requests:
                        print(f"- {request.query!r} hedefi aranıyor ({request.tool}).")
                        candidate_ids.extend(store.search(request))
                        if store.tool_calls:
                            call = store.tool_calls[-1]
                            if call.get("tool") == request.tool and "matched_count" in call:
                                print(f"  {call['matched_count']} eşleşme, {call['candidate_count']} okunmamış aday, "
                                      f"{call['already_read_count']} zaten okunmuş.")
                    candidate_ids = list(dict.fromkeys(candidate_ids))
                    if not candidate_ids and not store.lines:
                        candidate_ids = store.listed_file_candidates(listing)
                        if candidate_ids:
                            print('[ARAMA GERİ BİLDİRİMİ] Eşleşme yok; model listelenmiş dosyalardan '
                                  'ilgili olanı seçebilir. Dosya içeriği henüz okunmadı.')

                if candidate_ids:
                    candidate_ids = store.candidates_for_policy(
                        candidate_ids, "any" if allow_test_candidates else route.source_policy,
                    )
                    candidate_ids = store.prioritize_question_scopes(
                        candidate_ids, working_question,
                    )
                    allow_test_candidates = False
                    if not candidate_ids:
                        return finish(
                            "insufficient_evidence",
                            reason=f"{route.source_policy} politikasına uygun kaynak adayı bulunamadı.",
                        )
                    stage("SELECT")
                    selection = gateway.ask(
                        "SELECT", Selection,
                        "Select the candidate IDs whose implementation is most directly relevant to the question. "
                        "A selection requests a bounded implementation/context read, not just the signature line. "
                        "Prefer the implementation over mentions in tests/docs, unless those are needed for this question.",
                        {"question": working_question, "requirements": route.requirements,
                         "route": route.model_dump(),
                         "candidates": store.candidate_context(candidate_ids)},
                        allowed_ids=candidate_ids,
                    )
                    selected = store.candidate_context(selection.candidate_ids)
                    decision("AJAN KARARI — SELECT", [
                        f"{item['id']} → {item['file']}:{item['line']} ({item['preview']})"
                        for item in selected
                    ])
                    stage("READ")
                    new_lines = []
                    before_reads = len(store.tool_calls)
                    for candidate_id in selection.candidate_ids:
                        new_lines.extend(store.read(candidate_id))
                    for call in store.tool_calls[before_reads:]:
                        print(
                            f"- {call['file_path']} dosyasının "
                            f"{call['start_line']}-{call['end_line']} satırları okundu."
                        )
                    if not new_lines:
                        return finish("insufficient_evidence", reason="Seçilen kaynaklar yeni bilgi sağlamadı.")

                stage("ASSESS")
                follows_existing_symbols = (
                    route.intent in ("find_references", "trace_call")
                    or bool(set(route.entities) & set(store.observed_assigned_names()))
                    or bool(set(route.entities) & set(store.observed_callable_names()))
                    or any(name in working_question for name in store.observed_assigned_names())
                )
                observed_exception_flows = store.observed_exception_flows()
                terminal_calls = (
                    store.trace_terminal_calls() if route.intent == "trace_call" else []
                )
                trace_frontier = store.trace_frontier() if route.intent == "trace_call" else []
                terminal_trace = (
                    route.intent == "trace_call"
                    and not trace_frontier
                    and research_rounds >= MAX_RESEARCH_ROUNDS
                )
                bounded_file_inspection = (
                    route.intent == "locate_file"
                    and bool(store.lines)
                    and any(call["tool"] == "find_file" for call in store.tool_calls)
                )
                if trace_frontier:
                    search_targets = trace_frontier
                    all_trace_actions = store.search_actions(include_definitions=True)
                    trace_actions = [
                        action for action in all_trace_actions
                        if action["query"] in trace_frontier
                    ]
                    search_actions = _preferred_trace_actions(trace_actions, trace_frontier)
                elif terminal_trace:
                    # Zincirin son tanımı okunduğunda yüzlerce ilgisiz AST ismini
                    # bağlama eklemek küçük modeli dağıtır. Son tur yalnız mevcut
                    # çağrı kanıtını değerlendirir; yeni arama yapamaz.
                    search_targets = []
                    search_actions = []
                elif bounded_file_inspection:
                    # Açıkça istenen dosya bulunup bağlamı okundu. Dosyanın
                    # içindeki her ismi yeni bir repository aramasına çevirmek
                    # hem amacı saptırır hem küçük modelin karar şemasını şişirir.
                    # Model mevcut kısmı değerlendirebilir veya sınırlı devam
                    # adayını okuyabilir; yeni sembol araması bu rota için yoktur.
                    search_targets = []
                    search_actions = []
                else:
                    search_targets = (
                        store.search_targets(include_definitions=follows_existing_symbols)
                        if store.lines else None
                    )
                    search_actions = (
                        store.search_actions(include_definitions=follows_existing_symbols)
                        if store.lines else None
                    )
                valid_search_actions = None
                assess_allowed_decisions = None
                if search_actions is not None:
                    valid_search_actions = [
                        action for action in search_actions
                        if tool_call_signature(action["tool"], {"query": action["query"].strip()}) not in store.searches
                    ]
                    if valid_search_actions:
                        def _rank_search_action(action):
                            q = action["query"]
                            is_in_question = q in working_question
                            is_entity = q in route.entities
                            is_ref_for_defined = (
                                action["tool"] == "find_references"
                                and (q in store.observed_assigned_names() or q in store.observed_callable_names())
                            )
                            return (
                                0 if is_ref_for_defined else
                                1 if (is_in_question and is_entity) else
                                2 if is_in_question else
                                3 if is_entity else
                                4
                            )
                        valid_search_actions.sort(key=_rank_search_action)
                        valid_search_actions = valid_search_actions[:12]
                    else:
                        assess_allowed_decisions = ["answer", "interpret", "stop"]
                        if any(not store.is_read(k) for k in store.candidates):
                            assess_allowed_decisions.append("read")

                assessment = gateway.ask(
                    "ASSESS", Assessment,
                    ASSESS_INSTRUCTION,
                    {"question": working_question, "navigation_intent": route.intent,
                     "source": store.source_context(),
                     "observed_exception_flows": observed_exception_flows,
                     "terminal_call_hints": terminal_calls,
                     "search_targets": search_targets[:16] if search_targets is not None else None,
                     "trace_frontier": trace_frontier,
                     "observed_calls": store.observed_calls() if route.intent == "trace_call" else [],
                     "available_search_actions": (
                         valid_search_actions[:12] if valid_search_actions is not None
                         else search_actions
                     ),
                     "previous_searches": [call for call in store.tool_calls if call["tool"] != "read_file"],
                     "unread_candidates": (
                         [] if terminal_trace
                         else store.candidate_context(list(store.candidates))[:12]
                     )},
                    allowed_actions=valid_search_actions,
                    allowed_decisions=assess_allowed_decisions,
                )
                decision(
                    "KANIT DURUMU — ASSESS",
                    [f"İstek kontrolü: {item.requested_fact} → {item.status} "
                     f"(kanıt: {', '.join(item.evidence_ids) or 'yok'}); "
                     f"modelin iddiası: {item.observed_answer or 'bilinmiyor'}" for item in assessment.checks]
                    + [f"Eksik: {assessment.missing_information or 'yok'}",
                     f"Sonraki eylem: {assessment.action}"],
                )
                if assessment.action in ("answer", "interpret"):
                    if not store.lines:
                        return finish("insufficient_evidence", reason="Kaynak okunmadan cevap aşamasına geçilemez.")
                    for check in assessment.checks:
                        if check.evidence_ids:
                            store.block_citations(check.evidence_ids)
                    if assessment.action == 'interpret' and not any(check.evidence_ids for check in assessment.checks):
                        return finish('insufficient_evidence', reason='Yorumlanacak kaynak seçilmedi.')
                    unread_values = store.unread_claim_values(assessment.checks)
                    if unread_values:
                        print('[KANIT EKSİĞİ] Modelin iddiasında kullandığı değerin tanımı '
                              'okunmamış. Taslak üretilmeden ilgili tanım seçilip okunacak.')
                        candidate_ids = unread_values
                        requests = []
                        continue
                    if assessment.action == 'answer' and (assessment.missing_information.strip() or assessment.searches):
                        return finish("insufficient_evidence", reason="Model yeterlilik kararında eksik bilgi bildirdi.")
                    if assessment.action == 'interpret':
                        print('[YORUMLAMA] Yeni arama yerine okunmuş koddan taslak çıkarılacak; doğrulama atlanmaz.')
                    research_needed = False
                    break
                if assessment.action == "stop":
                    return finish("insufficient_evidence", reason=assessment.missing_information or "Kanıt yetersiz.")
                requests = assessment.searches if assessment.action == "search" else []
                if requests and all(
                    tool_call_signature(request.tool, {"query": request.query.strip()}) in store.searches
                    for request in requests
                ):
                    return finish("insufficient_evidence", reason="Aynı arama yeniden seçildi; ilerlemeyen döngü durduruldu.")
                candidate_ids = (
                    [key for key in store.candidates if not store.is_read(key)][:12]
                    if assessment.action == "read" else []
                )
                if not requests and not candidate_ids:
                    return finish("insufficient_evidence", reason="Yeni bir araştırma eylemi seçilmedi.")

            store.assert_unchanged()
            stage(draft_stage)
            if route.intent == "trace_call" and store.trace_terminal_calls():
                terminal_calls = store.trace_terminal_calls()
                trace_draft = gateway.ask(
                    draft_stage, TraceDraft,
                    "Select the concrete terminal runtime call that receives the routed configuration/value. "
                    "Then answer in Turkish and distinguish its earlier configuration and forwarding steps. "
                    "Object construction alone is not the terminal external/model invocation. "
                    "Do not write filenames or line numbers in the answer; the controller attaches exact locations. "
                    "If revising, remove every rejected location/number claim instead of searching for it. "
                    "Do not invent a call outside terminal_calls.",
                    {"question": working_question, "requirements": route.requirements,
                     "route": route.model_dump(), "terminal_calls": terminal_calls,
                     "source": store.source_context(), "review_feedback": review_feedback},
                    allowed_ids=[item["id"] for item in terminal_calls],
                )
                selected_call = next(
                    item for item in terminal_calls if item["id"] == trace_draft.terminal_call_id
                )
                decision("AJAN ÇAĞRI SEÇİMİ", [
                    f"{selected_call['id']} → {selected_call['file']}:{selected_call['line']} "
                    f"({selected_call['call']})"
                ])
                draft = Draft(claims=[DraftClaim(
                    answer=_strip_model_line_locations(trace_draft.answer),
                    evidence_ids=list(store.blocks),
                )], confidence=trace_draft.confidence)
            else:
                draft = gateway.ask(
                    draft_stage, Draft,
                    REPAIR_INSTRUCTION if draft_stage == 'REVISE' else (
                    "Answer the user's question concisely in Turkish, covering every requested fact. "
                    "Write one separate claim for EACH answer_requirements ID, using that requirement_id exactly once. "
                    "Each claim must actually answer that requested fact, including ALL parts if it contains multiple requests. "
                    "The assessment_hint is an unverified model note, NOT evidence: check it against source before using it. "
                    "Do not omit a requested effect, condition or outcome merely because another claim states a value. "
                    "Do not promise to explain or say 'let's look at the code'. Provide the concrete answer directly. "
                    "Give the actual conclusion, not a promise or plan to explain it. "
                    "Do not add invented illustrative examples unless requested. "
                    "Each claim must select the source BLOCK IDs that actually support it. "
                    "Select evidence FIRST, then write only what those selected lines establish. "
                    "Select both the definition block and the behavior block when a value is used elsewhere. "
                    "If explaining WHY, cite a documented rationale separately from the behavior; "
                    "do not infer the author's intent from domain knowledge. If no rationale is documented, say so. "
                    "For behavior/comparison questions, identify the input property being varied and follow the code's "
                    "operations in order. Explicitly decide whether each operation preserves, discards, normalizes or "
                    "canonicalizes that property; the final same/different, true/false conclusion must follow that mechanism. "
                    "Keep sequential operations distinct: if an earlier call succeeds but a later type check, guard or "
                    "branch rejects its result, do not describe the earlier call as failed. Claim an exception/failure "
                    "only when the observed exception path or return check applies. "
                    "Respect lexical try/except control flow: an exception raised by any protected statement transfers "
                    "to a matching handler, skips the remaining try statements, and follows that handler's return. "
                    "When the question asks for the condition, predicate or filter ('koşul nedir?'), you MUST quote the exact code expression in backticks (e.g. `not entry.name.startswith('.') and entry.name not in EXCLUDED_DIRECTORIES`) directly from the observed source or observed_conditions, in addition to explaining its effect in Turkish. "
                    "When the question asks for the mechanism ('mekanizma nedir?'), you MUST explicitly state the exception that is raised or caught (e.g. 'ValueError fırlatır'), quote the exact guard statement in backticks (e.g. `resolved_path.relative_to(PROJECT_ROOT)`) from the code or observed_exception_flows, and state the resulting return value or action (e.g. `None` / `return None`). ALL THREE parts (guard statement, exception name, and return value) must be present in the answer. "
                    "Do not attribute that behavior to a helper merely because the helper is called; "
                    "the helper must contain or determine the relevant condition in the supplied source. "
                    "For an exception-based mechanism, name the protected statement that triggers the matching handler "
                    "and the value/action produced by that handler; saying only 'there is try/except' is insufficient. "
                    "A handler may catch a broader tuple than one protected statement can raise. For a concrete scenario, "
                    "distinguish the applicable exception from the broader caught tuple; never claim every caught type is "
                    "raised by the same statement unless the supplied source establishes that. "
                    "When a repository test is supplied, interpret its assertions as secondary behavioral evidence. "
                    "In unittest semantics assertEqual(left, right) requires equal results and assertNotEqual(left, right) "
                    "requires different results; do not state the opposite. Treat an old review issue as a rejected claim, "
                    "not as a fact to repeat. "
                    "Do not invent file paths, line numbers or quotes in the answer; these are attached by the controller. "
                    "Never make claims (positive or negative) about a file that has not been read in the supplied source blocks. "
                    "Use backticks for repository symbol names. Include confidence as your self-assessment between 0 and 1. "
                    "If revising, remove/correct unsupported statements using ONLY the supplied source."),
                    {"question": working_question, "source": store.source_context(),
                     "answer_requirements": [
                         {"id": f"Q{index}", "requested_fact": check.requested_fact,
                          **({'assessment_hint': check.observed_answer} if draft_stage == 'DRAFT' else {})}
                         for index, check in enumerate(assessment.checks, 1)
                     ],
                     "observed_conditions": store.observed_conditions(),
                     "observed_exception_flows": store.observed_exception_flows(),
                     "review_feedback": review_feedback},
                    allowed_ids=list(store.blocks),
                )
            decision("AJAN TASLAĞI", [
                f"{claim.answer} [kanıt: {', '.join(claim.evidence_ids)}]"
                for claim in draft.claims
            ])
            findings = _findings(draft, store)
            confidence = draft.confidence
            stage("GROUNDING")
            numeric_issues = _numeric_grounding_issues(draft, store, working_question)
            citation_hints = _numeric_citation_repair_hints(draft, store, working_question) if numeric_issues else []
            if citation_hints:
                stage('CITE')
                draft = _repair_numeric_citations(draft, store, working_question, gateway, citation_hints)
                decision('KANIT BAĞLANTISI', [
                    f"Madde {index}: {', '.join(claim.evidence_ids)}"
                    for index, claim in enumerate(draft.claims, 1)
                ])
                findings = _findings(draft, store)
                numeric_issues = _numeric_grounding_issues(draft, store, working_question)
            condition_issues = _condition_grounding_issues(draft, store, working_question)
            mechanism_issues = _mechanism_grounding_issues(draft, store, working_question)
            grounding_issues = numeric_issues + condition_issues + mechanism_issues + _reference_grounding_issues(draft, store)
            decision(
                "KANIT BAĞLAMA — GROUNDING",
                grounding_issues or ["Sayısal iddialar kendi kanıtlarıyla eşleşiyor."],
            )
            if grounding_issues:
                bounded_grounding_issues = [_short(item, 300) for item in grounding_issues]
                review = Review(
                    question_checklist=[{
                        "requested_fact": "Deterministik kanıt gereksinimi",
                        "covered": False,
                        "explanation": _short("; ".join(grounding_issues), 250),
                    }],
                    source_interpretation="Deterministik kanıt kontrolü başarısız oldu.",
                    issues=bounded_grounding_issues, supported=False, complete=False,
                )
            else:
                stage("VERIFY")
                trace_review_instruction = (
                    "For this trace_call question, configuration and object construction are intermediate hops, "
                    "not the terminal invocation. Require the finding to identify the concrete call that receives "
                    "the value. "
                    if route.intent == "trace_call" else ""
                )
                # Değerlendirme, planner'ın konuşmasını değil yalnız soruyu ve seçilen kaynakları görür.
                review = gateway.ask(
                    "VERIFY", Review,
                    "Check the ORIGINAL question against the cited code and proposed answer. "
                    "Return question_checklist, issues, supported, complete. No repaired answer. "
                    "On the first review split the ORIGINAL question into distinct requested facts; add no new questions. "
                    "If review_facts is supplied, check EVERY listed fact exactly once; do not merge or drop facts. "
                    "For each fact give covered, a SHORT explanation and answer_ids selecting the numbered answer items. "
                    "Do not copy quotes. A fact only in source but omitted from the answer is NOT covered: answer_ids=[]. "
                    "Check that the selected answer actually answers that fact, not merely mentions the same symbol. "
                    "Do not merge a requested value, identifier and resulting behavior into one checklist item. "
                    "complete must be false if any requested fact is omitted or only promised. "
                    "A promise to explain is not an answer. A variable name is not its concrete value. "
                    "Check every requested result and mechanism, not just whether the topic is mentioned. "
                    "Trace input type, executed operations, branches and early returns in order. "
"Do not confuse a successful operation with rejection by a later check. "
                    "A caught exception tuple does not establish which exception a specific operation raises. "
                    "Use standard language semantics; do not guess unknown external behavior. "
                    "Distinguish hypothetical examples from claims about repository constants. "
                    "For ambiguous input types require an explicit assumption or both interpretations. "
                    "Reject concrete unsupported/contradictory claims or missing requested facts, briefly in issues. "
                    "If review_feedback contains previous issues, strictly verify that the new answer actually resolves them. "
                    "Accept only if supported and complete; use issues=[] on acceptance. "
                    + trace_review_instruction,
                    {"question": working_question, "findings": findings,
                     "require_answer_coverage": True,
                     "review_facts": review_facts,
                     "answer_items": [{'id': index, 'answer': item['answer']}
                                      for index, item in enumerate(findings, 1)],
                     "route_intent": route.intent,
                     "review_feedback": {
                         key: [
                             item for item in val
                             if not any(marker in item for marker in ("bağlı kanıtta yok", "Deterministik kanıt", "sayısal değer", "İstenen kod koşulu", "Exception tabanlı", "kontrol mekanizması"))
                         ] if isinstance(val, list) else val
                         for key, val in review_feedback.items()
                     },
                     "observed_exception_flows": store.observed_exception_flows()},
                    allowed_review_facts=review_facts,
                )
                if review_facts is None:
                    review_facts = [item.requested_fact for item in review.question_checklist] or None
            decision(
                "KONTROL — VERIFY" if not grounding_issues else "KONTROL — GROUNDING",
                [f"Kapsam: {item.requested_fact} → {'var' if item.covered else 'eksik'} "
                 f"({item.explanation})" for item in review.question_checklist]
                + ([f"Kaynak yorumu: {review.source_interpretation}"] if review.source_interpretation else [])
                + [f"Destekli: {review.supported}; eksiksiz: {review.complete}"]
                + [f"Sorun: {item}" for item in review.issues],
            )
            uncovered = [
                item.requested_fact for item in review.question_checklist
                if not item.covered and item.requested_fact != "Deterministik kanıt gereksinimi"
            ]
            if uncovered:
                review.complete = False
                review.issues.extend(
                    f"Sorunun bu kısmı cevaplanmadı: {item}" for item in uncovered
                    if not any(item in issue for issue in review.issues)
                )
            store.assert_unchanged()
            if review.supported and review.complete and not review.issues:
                stage("RESULT")
                return finish(
                    "review_required", findings=findings,
                    reason="Kaynak kimlikleri/alıntılar doğrulandı ve ayrı model kontrolünden geçti. "
                           "Açıklama bir model taslağıdır; insan incelemesi gerekir, doğrulanmış cevap sayılmaz.",
                )
            review_issues = list(dict.fromkeys(
                review.issues or ["Cevap desteklenmiyor veya soruyu bütünüyle karşılamıyor."]
            ))
            review_feedback = {"untrusted_correction_requests": [_short(item, 300) for item in review_issues]}
            if recovery_rounds >= MAX_RECOVERY_ROUNDS:
                return finish("insufficient_evidence", reason="; ".join(review_issues))

            if condition_issues or mechanism_issues:
                # İstenen predicate zaten okunmuş AST'den controller tarafından
                # çıkarıldı. Eksik olan yeni kaynak değil, taslağın ifadesidir;
                # modeli gereksiz repository aramasına göndermeden düzelt.
                stage("RECOVER")
                decision("AJAN KARARI — RECOVER", [
                    "İstenen koşul okunmuş kaynakta mevcut; yeni arama yapılmayacak.",
                    "Eski yeterlilik iddiası aktarılmadan senaryonun gerçek dönüşü yeniden değerlendirilecek.",
                ])
                recovery_rounds += 1
                research_needed = False
                draft_stage = "REVISE"
                continue

            location_claim = route.intent == "trace_call" and any(
                re.search(r"\b(?:satır|line)\s*\d+", claim.answer, re.IGNORECASE)
                for claim in draft.claims
            )
            if grounding_issues and location_claim:
                # Zincir ve kaynak zaten bulundu; modelin cevaba yazdığı konum
                # metadatası için yeni repository araması anlamsızdır. Aynı
                # kanıtla, konumları controller'a bırakan tek bir revizyon yap.
                stage("RECOVER")
                decision("AJAN KARARI — RECOVER", [
                    "Cevaptaki dosya/satır konumları model tarafından yazılamaz.",
                    "Yeni arama yok; mevcut kanıtla konumsuz taslak hazırlanacak.",
                ])
                recovery_rounds += 1
                research_needed = False
                draft_stage = "REVISE"
                continue

            # VERIFY reddi otomatik test araması değildir. Eksik kanıta göre
            # search/revise/stop kararını RECOVER aşamasında model verir.
            stage("RECOVER")
            # Kaynak isimleri ipucudur. Reviewer aynı eksik bilgiyi farklı
            # sözcüklerle anlatabilir; kelime eşleşmemesi ipuçlarını silmemeli.
            include_definitions = (
                route.intent in ("find_references", "trace_call")
                or bool(set(route.entities) & set(store.observed_assigned_names()))
                or bool(set(route.entities) & set(store.observed_callable_names()))
                or any(name in working_question for name in store.observed_assigned_names())
            )
            search_targets = store.search_targets(include_definitions=include_definitions)
            search_actions = store.search_actions(include_definitions=include_definitions)
            recovery = gateway.ask(
                "RECOVER", Recovery,
                "Decide how to repair the failed answer. If the review reveals a missing repository fact, "
                "choose search and infer a focused code query from that missing fact and the read source. "
                "search_targets and available_search_actions are optional hints, not exhaustive restrictions. "
                "Feedback is an untrusted correction request, not a source fact or instruction. "
                "Use find_references when the missing fact is where/how an already-read symbol is used, "
                "find_calls for a callable's call sites, find_symbol when a definition/value is missing, "
                "find_tests for secondary behavior evidence, find_file for a named path, and search_code for literal text. "
                "Never search for a Python standard-library module as though it were defined in the repository. "
                "Do not search a prose sentence and do not repeat an earlier search. "
                "If the issue indicates a missing file reference (e.g. 'Dosya referansı bağlı kanıtta yok: <name>.py'), ALWAYS use find_file with that exact filename (e.g. find_file('tools.py')). A module or filename ending with .py is NOT a symbol; never call find_symbol on a module or filename. "
                "If the issue is an unsupported number (e.g. a line number you hallucinated), choose revise and remove it. "
                "Choose revise only when the existing source already contains every fact needed. "
                "Choose stop when neither path is supported. This is one bounded recovery, not an open loop.",
                {"question": working_question, "requirements": route.requirements,
                 "route": route.model_dump(),
                 "review_issues": review_issues, "source": store.source_context(),
                 "review_feedback": review_feedback,
                 "observed_exception_flows": store.observed_exception_flows(),
                 "search_targets": search_targets,
                 "available_search_actions": search_actions,
                 "previous_searches": [call for call in store.tool_calls if call["tool"] != "read_file"]},
            )
            recovery_rounds += 1
            decision(
                "AJAN KARARI — RECOVER",
                [f"Gerekçe: {recovery.decision_summary}", f"Eylem: {recovery.action}"]
                + [f"Yeni arama: {item.tool}({item.query!r})" for item in recovery.searches],
            )
            if recovery.action == "stop":
                return finish("insufficient_evidence", reason="; ".join(review_issues))
            if recovery.action == "revise":
                if recovery.searches:
                    return finish("insufficient_evidence", reason="Revise kararı arama isteği içeremez.")
                research_needed = False
                draft_stage = "REVISE"
                continue
            requests = recovery.searches
            allow_test_candidates = any(request.tool == "find_tests" for request in requests)
            if not requests:
                return finish("insufficient_evidence", reason="Recovery arama eylemi sorgu üretmedi.")
            if all(
                tool_call_signature(request.tool, {"query": request.query.strip()}) in store.searches
                for request in requests
            ):
                return finish("insufficient_evidence", reason="Recovery aynı aramayı tekrarladı; döngü durduruldu.")
            candidate_ids = []
            research_needed = True
            draft_stage = "REDRAFT"
    except (ProtocolError, EvidenceError, OSError, UnicodeError) as error:
        return finish("stopped", reason=str(error))


def run_agent(issue_text, gateway=None, json_output=False):
    """Public entry point: task-scoped Phase 1/2 controller."""
    from repository_agent import run_repository_agent
    gateway = gateway or ModelGateway(MODEL_NAME, think=MODEL_THINK)
    if isinstance(gateway, ModelGateway):
        gateway.progress = None if json_output else lambda: builtins.print('.', end='', flush=True)
        gateway.report = None if json_output else lambda item: builtins.print(
            f"\n[SÜRE] {item['stage']}: {item['seconds']:.1f} sn", flush=True)
        if not json_output:
            builtins.print(f'[MODEL] {gateway.model_name} | thinking: {gateway.think}')
    return AgentResult(**run_repository_agent(issue_text, gateway, json_output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Staged read-only local coding agent")
    parser.add_argument("issue", help="Araştırılacak soru")
    parser.add_argument("--repo", type=Path, default=tools.PROJECT_ROOT,
                        help="Seçili repository; varsayılan bu projenin kökü.")
    parser.add_argument("--model", default=MODEL_NAME, help="Ollama model adı.")
    parser.add_argument('--legacy-staged', action='store_true', help='Önceki aşamalı akışı karşılaştırma için kullan.')

    parser.add_argument(
        "--json", action="store_true",
        help="Kısa kullanıcı çıktısı yerine alıntılar dahil ayrıntılı JSON yazdır.",
    )
    args = parser.parse_args()
    tools.PROJECT_ROOT = args.repo.resolve()
    if not tools.PROJECT_ROOT.is_dir():
        parser.error("--repo var olan bir klasör olmalıdır.")
    runner = run_staged_agent if args.legacy_staged else run_agent
    result = runner(args.issue, json_output=args.json, gateway=ModelGateway(
        args.model, think=MODEL_THINK, fast_model_name=FAST_MODEL_NAME,
    ))
    # İnceleme notu taşıyan fakat cevap üreten çalışma CLI açısından tamamlanmıştır.
    raise SystemExit(_cli_exit_code(result.status))
