"""Sıralı, read-only ajan: keşif -> okuma -> kanıt -> ayrı cevap kontrolü."""
import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field

import tools
from evidence import EvidenceError, EvidenceStore
from protocol import (
    Assessment, Draft, DraftClaim, ModelGateway, ProtocolError, Recovery, Review, RouteDecision,
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
NUMBER_PATTERN = re.compile(r"(?<![\w.])[+-]?\d[\d_]*(?:[.,]\d[\d_]*)?(?![\w.])")
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

    def model_dump(self):
        return asdict(self)


def _findings(draft, store):
    """Model yalnız kanıt kimliklerini seçer; konum ve alıntıyı bu kod oluşturur."""
    return [
        {"answer": claim.answer, "evidence": store.block_citations(claim.evidence_ids)}
        for claim in draft.claims
    ]


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
        evidence_text = "\n".join(
            citation["quote"] for citation in store.block_citations(claim.evidence_ids)
        )
        allowed = question_numbers | _number_tokens(evidence_text)
        unsupported = sorted(_number_tokens(claim.answer) - allowed)
        if unsupported:
            issues.append(
                f"İddia {index} içindeki sayısal değer(ler) bağlı kanıtta veya soruda yok: "
                + ", ".join(unsupported)
            )
    return issues


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

    answer_text = "\n".join(claim.answer for claim in draft.claims)
    if any(compact(condition) in compact(answer_text) for condition in relevant):
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
    for flow in flows:
        guards = flow["guard_statements"]
        guard_present = any(
            re.sub(r"\s+", "", guard) in compact_answer for guard in guards
        )
        exception_present = any(name in answer for name in flow["caught_exceptions"])
        handler_present = any(
            re.sub(r"\s+", "", statement) in compact_answer
            for statement in flow["handler_statements"]
        )
        if guard_present and exception_present and handler_present:
            return []
    expected = flows[0]
    return [
        "Exception tabanlı kontrol mekanizması eksik: guard ifadesi "
        f"`{' | '.join(expected['guard_statements'])}`, eşleşen exception "
        f"`{' | '.join(expected['caught_exceptions'])}` ve handler sonucu "
        f"`{' | '.join(expected['handler_statements'])}` birlikte açıklanmalıdır."
    ]


def _strip_model_line_locations(answer):
    """Modelin yazdığı satır konumlarını siler; kesin konumu controller ekler."""
    value = str(answer)
    patterns = (
        r"\(\s*\d+\s*[-–]\s*\d+\s+(?:satırlar?|lines?)(?:\s+arası)?\s*\)",
        r"\b\d+\s*[-–]\s*\d+\s+(?:satırlar?|lines?)(?:\s+arası)?",
        r"\b(?:satır|line)\s+\d+(?:\s*[-–]\s*\d+)?(?:[.'’]?(?:da|de))?",
        r"\b\d+\s*\.\s*(?:satır|line)(?:[.'’]?(?:da|de))?",
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
        explicit_file = (
            target in listed_paths or target in listed_names
        ) and ("/" in target or "." in target)
        if explicit_file:
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


def run_agent(issue_text, gateway=None, json_output=False):
    """Aşamalar atlanamaz; araştırma hedefleri ve kaynak seçimi modele aittir."""
    gateway = gateway or ModelGateway(
        MODEL_NAME, think=MODEL_THINK, fast_model_name=FAST_MODEL_NAME,
    )
    store = EvidenceStore()
    stages = []
    listing_call = {"tool": "list_files", "directory_path": "."}
    listing_performed = False

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
        payload = {
            "status": result.status, "question": issue_text,
            "findings": result.findings, "reason": result.reason,
            "model_calls": len(result.model_trace), "tool_calls": len(result.tool_calls),
        }
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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
        initial_search_targets = _initial_search_targets(working_question, listing)
        initial_search_actions = _initial_search_actions(working_question, listing)
        route = gateway.ask(
            "ROUTE", RouteDecision,
            "Classify the repository question and choose the minimum sufficient initial navigation actions, usually one. "
            "Choose find_definition ONLY when the user merely asks where a symbol is declared or what value it has. "
            "Choose trace_call when the user asks where a model/function is actually called, or how a configured "
            "value is forwarded into a real/runtime invocation; this requires following the value through code. "
            "If the question asks how/why code behaves, what it returns, whether outputs are same/different, or what "
            "happens when an input/property changes, choose explain_behavior even when a named symbol is present. "
            "Preserve concrete filenames, identifiers, call names and literal model/config strings from the question; "
            "never replace a requested entity with a guessed filename. Treat generic task nouns and spelling noise as "
            "meaning to interpret, not separate repository entities or search queries. "
            "Use find_file for an explicit filename/path, find_symbol for a definition, find_references for usages, "
            "find_calls for call sites, and search_code for literal text/config/model strings. "
            "Do not use find_tests as an initial navigation action; tests are secondary behavior evidence. "
            "For runtime behavior or call tracing choose code_only or code_first; documentation is not implementation evidence. "
            "For installation/README questions choose docs_first. Break every requested subquestion into a requirement. "
            "Write entities, requirements and decision_summary in Turkish. "
            "Do not answer the question in this stage.",
            {"question": working_question, "project_listing": listing,
             "allowed_search_targets": initial_search_targets,
             "allowed_search_actions": initial_search_actions},
            allowed_queries=initial_search_targets,
            allowed_actions=initial_search_actions,
        )
        decision(
            "AJAN KARARI — ROUTE",
            [f"Niyet: {route.intent}", f"Kaynak politikası: {route.source_policy}",
             f"Varlıklar: {', '.join(route.entities)}", f"Gerekçe: {route.decision_summary}"]
            + [f"Gerekli kanıt: {item}" for item in route.requirements]
            + [f"İlk arama: {item.tool}({item.query!r})" for item in route.searches],
        )
        requests = route.searches
        candidate_ids = []
        research_rounds = 0
        recovery_rounds = 0
        research_needed = True
        draft_stage = "DRAFT"
        review_issues = []
        review_feedback = {}
        behavior_validation_attempted = set()
        allow_test_candidates = False

        def collect_behavior_test_candidates():
            """Okunmuş callable'lar için varsa bir kez ikincil test kanıtı getir."""
            if route.intent != "explain_behavior":
                return []
            question_entities = {
                item for item in _initial_search_targets(working_question, listing)
                if item.isidentifier()
            }
            targets = [
                name for name in store.observed_callable_names()
                # İlgisiz bir yardımcı fonksiyon daha sonra okunmuş olsa bile
                # test recovery'si soruda adlandırılan davranıştan sapamaz.
                if name in question_entities
                if name not in behavior_validation_attempted
                and tool_call_signature("find_tests", {"query": name}) not in store.searches
                and "(Satır " in tools.find_tests(name)
            ][:2]
            if not targets:
                return []
            stage("RECOVER")
            decision("AJAN KARARI — RECOVER", [
                "Kaynak davranışı henüz kesinleşmedi; ilgili repository testleri aranacak.",
                *(f"Doğrulama araması: find_tests({name!r})" for name in targets),
            ])
            stage("SEARCH")
            ids = []
            for name in targets:
                behavior_validation_attempted.add(name)
                print(f"- {name!r} için davranış testi aranıyor (find_tests).")
                ids.extend(store.search(SearchRequest(tool="find_tests", query=name)))
            return list(dict.fromkeys(ids))

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
                    candidate_ids = list(dict.fromkeys(candidate_ids))

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
                follows_existing_symbols = route.intent in ("find_references", "trace_call")
                terminal_calls = (
                    store.trace_terminal_calls() if route.intent == "trace_call" else []
                )
                if terminal_calls:
                    # Controller, constructor parametresi -> self alanı -> gerçek
                    # çağrı argümanı zincirini AST ile zaten doğruladı. Küçük
                    # modelin bu somut kanıta rağmen yanlışlıkla stop demesine
                    # izin vermeden doğrudan kanıta bağlı taslak aşamasına geç.
                    decision("KANIT DURUMU — ASSESS", [
                        "Terminal çağrı bulundu.",
                        *(
                            f"{item['file']}:{item['line']} → {item['call']}"
                            for item in terminal_calls
                        ),
                        "Sonraki eylem: answer",
                    ])
                    research_needed = False
                    break
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
                assessment = gateway.ask(
                    "ASSESS", Assessment,
                    "Check whether the actually read source establishes EVERY required fact. "
                    "Write established_facts and missing_information in Turkish. "
                    "FIRST interpret the observed code and record the established facts relevant to this question. "
                    "Only AFTER that identify missing information and decide whether to answer or search. "
                    "An identifier appearing in code is not automatically missing information. "
                    "Do not investigate unrelated branches or helper functions when the requested behavior is already visible. "
                    "Do not confuse a use/reference with a definition or a value. "
                    "If sufficient, choose answer with empty searches and empty missing_information. "
                    "If a necessary fact is missing, choose search and select the exact identifier from search_targets "
                    "whose definition is needed. Never search a prose description of a fact. "
                    "Use find_symbol for a missing definition/value, find_references for symbol usages, "
                    "find_calls for call sites, find_file for an explicit path, and search_code for literal text. "
                    "For a trace_call route, use find_references for an already-read value, find_symbol for an "
                    "unread symbol seen in a call, and find_calls for a callable whose definition is already read. "
                    "Do not divert into standard-library/module internals. "
                    "If no search action is available, inspect the current source for the concrete call and answer; "
                    "choose stop only when that call is not established. "
                    "Choose read to inspect an unread candidate/continuation, or stop if no supported path remains. "
                    "Do not follow unrelated dependencies. Never answer using memory or an unobserved source.",
                    {"question": working_question, "requirements": route.requirements,
                     "route": route.model_dump(),
                     "source": store.source_context(),
                     "observed_exception_flows": store.observed_exception_flows(),
                     "search_targets": search_targets,
                     "trace_frontier": trace_frontier,
                     "observed_calls": store.observed_calls() if route.intent == "trace_call" else [],
                     "available_search_actions": search_actions,
                     "previous_searches": [call for call in store.tool_calls if call["tool"] != "read_file"],
                     "unread_candidates": (
                         [] if terminal_trace
                         else store.candidate_context(list(store.candidates))[:12]
                     )},
                    allowed_queries=search_targets,
                    allowed_actions=search_actions,
                    forced_action="search" if trace_frontier else None,
                    allowed_decisions=(
                        ["answer", "stop"] if terminal_trace
                        else ["answer", "read", "stop"] if bounded_file_inspection
                        else None
                    ),
                )
                decision(
                    "KANIT DURUMU — ASSESS",
                    [f"Eksik: {assessment.missing_information or 'yok'}",
                     f"Sonraki eylem: {assessment.action}"],
                )
                if assessment.action in ("search", "stop") and not assessment.searches:
                    test_candidate_ids = collect_behavior_test_candidates()
                    if test_candidate_ids:
                        candidate_ids = test_candidate_ids
                        requests = []
                        allow_test_candidates = True
                        continue
                if assessment.action == "answer":
                    if not store.lines:
                        return finish("insufficient_evidence", reason="Kaynak okunmadan cevap aşamasına geçilemez.")
                    if assessment.missing_information.strip() or assessment.searches:
                        return finish("insufficient_evidence", reason="Model yeterlilik kararında eksik bilgi bildirdi.")
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
            if route.intent == "trace_call":
                terminal_calls = store.trace_terminal_calls()
                if not terminal_calls:
                    return finish("insufficient_evidence", reason="Kanıt zincirinde terminal çağrı bulunamadı.")
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
                )])
            else:
                draft = gateway.ask(
                    draft_stage, Draft,
                    "Answer the user's question concisely in Turkish, covering every requested fact. "
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
                    "When the question asks for the condition or mechanism, state the exact observed predicate/branch "
                    "and explain its effect. Do not attribute that behavior to a helper merely because the helper is called; "
                    "the helper must contain or determine the relevant condition in the supplied source. "
                    "For an exception-based mechanism, name the protected statement that triggers the matching handler "
                    "and the value/action produced by that handler; saying only 'there is try/except' is insufficient. "
                    "When a repository test is supplied, interpret its assertions as secondary behavioral evidence. "
                    "In unittest semantics assertEqual(left, right) requires equal results and assertNotEqual(left, right) "
                    "requires different results; do not state the opposite. Treat an old review issue as a rejected claim, "
                    "not as a fact to repeat. "
                    "Do not invent file paths, line numbers or quotes in the answer; these are attached by the controller. "
                    "If revising, remove/correct unsupported statements using ONLY the supplied source.",
                    {"question": working_question, "source": store.source_context(),
                     "observed_conditions": store.observed_conditions(),
                     "observed_exception_flows": store.observed_exception_flows(),
                     "review_feedback": review_feedback},
                    allowed_ids=list(store.blocks),
                )
            decision("AJAN TASLAĞI", [
                claim.answer
                for claim in draft.claims
            ])
            findings = _findings(draft, store)
            stage("GROUNDING")
            numeric_issues = _numeric_grounding_issues(draft, store, working_question)
            condition_issues = _condition_grounding_issues(draft, store, working_question)
            mechanism_issues = _mechanism_grounding_issues(draft, store, working_question)
            grounding_issues = numeric_issues + condition_issues + mechanism_issues
            decision(
                "KANIT BAĞLAMA — GROUNDING",
                grounding_issues or ["Sayısal iddialar kendi kanıtlarıyla eşleşiyor."],
            )
            if grounding_issues:
                review = Review(
                    question_checklist=[{
                        "requested_fact": "Deterministik kanıt gereksinimi",
                        "covered": False,
                        "explanation": "; ".join(grounding_issues),
                    }],
                    source_interpretation="Deterministik kanıt kontrolü başarısız oldu.",
                    issues=grounding_issues, supported=False, complete=False,
                )
            else:
                stage("VERIFY")
                # Değerlendirme, planner'ın konuşmasını değil yalnız soruyu ve seçilen kaynakları görür.
                review = gateway.ask(
                    "VERIFY", Review,
                    "You are a careful and balanced reviewer. Check every answer against the attached source quotes. "
                    "Reject unsupported values, swapped filenames, wrong conditions, fabricated behavior or unjustified certainty. "
                    "FIRST split the ORIGINAL question into every separately requested fact, including coordinated or "
                    "comma-separated clauses. Record every part in question_checklist; never collapse the checklist to "
                    "the subject name. A scenario, changed input, condition, or example inside the question is context "
                    "for the requested conclusion, not automatically a separate requested deliverable. "
                    "Check whether the findings answer each part of the question independently of any earlier route plan. "
                    "A function signature alone does not establish body behavior. "
                    "For behavior/comparison questions, independently trace whether the varied input property is preserved, "
                    "discarded, normalized or canonicalized before checking the proposed conclusion. "
                    "Check sequential operations separately. Reject an explanation that calls an earlier parse/call failed "
                    "when the source instead accepts its result and a later type check, guard or branch rejects it. "
                    "Respect lexical try/except control flow. An exception from a protected statement transfers to a "
                    "matching handler and skips later statements in the try body; do not claim an exception escapes when "
                    "its type is listed by that handler. "
                    "If the question asks for a condition or code mechanism, require the answer to identify the actual "
                    "predicate/branch and its effect. Reject causal attribution to an adjacent helper/callee when the "
                    "relevant condition is instead implemented directly in the caller. "
                    "For an exception-based mechanism, require the triggering protected statement, matching exception "
                    "type, and handler result. A generic mention of try/except is incomplete. "
                    "Use supplied test assertions as secondary evidence, while keeping implementation code primary. "
                    "In unittest semantics assertEqual(left, right) requires equal results and assertNotEqual(left, right) "
                    "requires different results; reject any conclusion that reverses those meanings. "
                    "For trace_call questions, configuration and object construction are intermediate hops, not the "
                    "terminal invocation. Require the finding to identify the concrete call that receives the value. "
                    "Evaluate the evidence blocks together: a symbol's definition and its use may jointly support a claim. "
                    "Accept direct logical consequences of the attached code; the conclusion does not need to appear verbatim. "
                    "Reject a numeric value when neither that claim's evidence nor the original question contains it. "
                    "Mark an answer unsupported only for a concrete contradiction, missing premise, or omitted requested fact. "
                    "The answer may be Turkish; interpret its meaning and negation accurately. "
                    "Set supported=true only if every assertion follows from the combined cited code. "
                    "Set complete=true only if the original question is fully answered. "
                    "Every clause must be supported by the attached quotes, not unseen repository content. "
                    "A condition and a numeric assignment can establish behavior when connected by the same symbol. "
                    "They do NOT establish the author's rationale. "
                    "A rationale needs an explicit source comment/docstring or must be labeled unknown. "
                    "Identify gaps in issues FIRST, before deciding supported and complete. "
                    "Do not repair the answer or assume unseen source. List concrete issues; no issues means an empty list.",
                    {"question": working_question, "findings": findings,
                     "observed_exception_flows": store.observed_exception_flows()},
                )
            decision(
                "KONTROL — VERIFY" if not grounding_issues else "KONTROL — GROUNDING",
                [f"Kapsam: {item.requested_fact} → {'var' if item.covered else 'eksik'} "
                 f"({item.explanation})" for item in review.question_checklist]
                + [f"Kaynak yorumu: {review.source_interpretation}",
                 f"Destekli: {review.supported}; eksiksiz: {review.complete}"]
                + [f"Sorun: {item}" for item in review.issues],
            )
            uncovered = [
                item.requested_fact for item in review.question_checklist if not item.covered
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
            review_feedback = {
                "source_interpretation": review.source_interpretation,
                "question_checklist": [item.model_dump() for item in review.question_checklist],
                "issues": review_issues,
            }
            if recovery_rounds >= MAX_RECOVERY_ROUNDS:
                return finish("insufficient_evidence", reason="; ".join(review_issues))

            if condition_issues or mechanism_issues:
                # İstenen predicate zaten okunmuş AST'den controller tarafından
                # çıkarıldı. Eksik olan yeni kaynak değil, taslağın ifadesidir;
                # modeli gereksiz repository aramasına göndermeden düzelt.
                stage("RECOVER")
                decision("AJAN KARARI — RECOVER", [
                    "İstenen koşul okunmuş kaynakta mevcut; yeni arama yapılmayacak.",
                    "Mevcut kanıt ve eksiksiz AST koşuluyla taslak düzeltilecek.",
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

            # Bir callable'ın kaynak gövdesi okunduğu halde davranış taslağı
            # reddedildiyse, varsa repository testini bağımsız ikinci kanıt
            # olarak getir. Hedef adları yalnız okunmuş AST'den gelir; soruya
            # veya belirli bir beklenen cevaba bağlı değildir.
            test_candidate_ids = collect_behavior_test_candidates()
            if test_candidate_ids:
                candidate_ids = test_candidate_ids
                if candidate_ids:
                    recovery_rounds += 1
                    requests = []
                    research_needed = True
                    draft_stage = "REDRAFT"
                    allow_test_candidates = True
                    # Yeni bağımsız kanıt geldikten sonra önceki model yorumunu
                    # yeni taslağa gerçekmiş gibi taşıma; kaynaklardan yeniden çıkar.
                    review_issues = []
                    continue

            stage("RECOVER")
            # Davranış açıklamasında yalnız gerçekten çözülmemiş isimler yeni
            # kanıt gerektirir. Zaten okunmuş fonksiyon/sabitleri tekrar aramak
            # bir yorum hatasını ilgisiz kaynak gezintisine dönüştürüyordu.
            include_definitions = route.intent in ("find_references", "trace_call")
            search_targets = store.search_targets(include_definitions=include_definitions)
            search_actions = store.search_actions(include_definitions=include_definitions)
            review_text = " ".join(review_issues)
            mentioned_targets = [
                target for target in search_targets
                if re.search(rf"(?<!\w){re.escape(target)}(?!\w)", review_text)
            ]
            if route.intent == "explain_behavior" and not mentioned_targets:
                search_targets = []
                search_actions = []
            recovery = gateway.ask(
                "RECOVER", Recovery,
                "Decide how to repair the failed answer. If the review reveals a missing repository fact, "
                "choose search and select the exact unresolved identifier from search_targets. "
                "Use find_references when the missing fact is where/how an already-read symbol is used, "
                "find_calls for a callable's call sites, find_symbol when a definition/value is missing, "
                "find_tests for secondary behavior evidence, find_file for a named path, and search_code for literal text. "
                "Never search for a Python standard-library module as though it were defined in the repository. "
                "Do not search a prose sentence and do not repeat an earlier search. "
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
                allowed_queries=search_targets,
                allowed_actions=search_actions,
                allowed_decisions=(
                    ["revise", "stop"]
                    if route.intent == "explain_behavior" and not search_targets
                    else None
                ),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Staged read-only local coding agent")
    parser.add_argument("issue", help="Araştırılacak soru")
    parser.add_argument(
        "--json", action="store_true",
        help="Kısa kullanıcı çıktısı yerine alıntılar dahil ayrıntılı JSON yazdır.",
    )
    args = parser.parse_args()
    result = run_agent(args.issue, json_output=args.json)
    # İnceleme notu taşıyan fakat cevap üreten çalışma CLI açısından tamamlanmıştır.
    raise SystemExit(_cli_exit_code(result.status))
