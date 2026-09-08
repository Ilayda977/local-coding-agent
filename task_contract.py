"""Immutable task scope and small action schemas for the read-only controller.

No repository answers live here. The model identifies the subject and inputs;
the controller assigns requirement IDs and prevents later scope replacement.
"""
from typing import Literal
from pydantic import Field, model_validator
from protocol import StrictModel, SearchRequest


class Requirement(StrictModel):
    user_excerpt: str = Field(min_length=1, max_length=500,
        description='Exact substring containing a requested part of the original question. Do not answer or paraphrase it.')


class TaskContract(StrictModel):
    target: str = Field(min_length=1, max_length=160)
    target_kind: Literal['symbol', 'file', 'concept']
    target_user_excerpt: str = Field(min_length=1, max_length=240)
    inputs_and_assumptions: list[str] = Field(max_length=6,
        description='Exact substrings of user-supplied inputs/hypotheses only; no repository facts. Empty if none.')
    requirements: list[Requirement] = Field(min_length=1, max_length=5)

    def validate_context(self, data):
        question = data['question']
        for excerpt in [self.target_user_excerpt] + self.inputs_and_assumptions + [r.user_excerpt for r in self.requirements]:
            if excerpt not in question:
                raise ValueError('Task excerpts must be exact substrings of the original question.')
        descriptions = [r.user_excerpt for r in self.requirements]
        if len(set(descriptions)) != len(descriptions):
            raise ValueError('Do not duplicate requested results.')

    def snapshot(self, question):
        return {'question': question, 'target': self.target, 'target_kind': self.target_kind,
                'inputs_and_assumptions': self.inputs_and_assumptions.copy(),
                'requirements': [dict(id=f'Q{i}', user_excerpt=r.user_excerpt,
                                      requested_result=r.user_excerpt)
                                 for i, r in enumerate(self.requirements, 1)]}


class Anchor(StrictModel):
    evidence_id: str = Field(min_length=1,
        description='ID of an actually read block supporting the answer. The controller supplies the exact source quote.')


class AnswerItem(StrictModel):
    requirement_id: str
    answer: str = Field(min_length=1, max_length=600)
    mechanism: str = Field(min_length=1, max_length=400,
                           description='Short checkable code explanation: relevant condition, input substitution, operation or return. Not private thoughts.')
    anchors: list[Anchor] = Field(min_length=1, max_length=3)


def check_answers(items, data):
    expected = [r['id'] for r in data['contract']['requirements']]
    if sorted(item.requirement_id for item in items) != sorted(expected):
        raise ValueError('Answer each frozen requirement ID exactly once; no new requirements.')
    sources = {b['id']: b['quote'] for b in data['source']}
    for item in items:
        for anchor in item.anchors:
            if anchor.evidence_id not in sources:
                raise ValueError('Every evidence ID must identify an actually read block.')


def constrain_answer_schema(schema, data):
    """Expose actual IDs to Ollama's grammar as well as checking them in Python."""
    schema['$defs']['AnswerItem']['properties']['requirement_id']['enum'] = [
        r['id'] for r in data['contract']['requirements']]
    ids = [b['id'] for b in data['source']]
    if ids:
        schema['$defs']['Anchor']['properties']['evidence_id']['enum'] = ids
    return schema


class NextAction(StrictModel):
    action: Literal['search', 'read', 'answer', 'stop']
    summary: str = Field(min_length=1, max_length=220)
    searches: list[SearchRequest] = Field(default_factory=list, max_length=2)
    candidate_ids: list[str] = Field(default_factory=list, max_length=2)
    answers: list[AnswerItem] = Field(default_factory=list, max_length=5)
    confidence: float = Field(default=0.0, ge=0, le=1)

    @classmethod
    def constrain_schema(cls, schema, data):
        constrain_answer_schema(schema, data)
        ids = [c['id'] for c in data['candidates']]
        if ids:
            schema['properties']['candidate_ids']['items']['enum'] = ids
        else:
            schema['properties']['candidate_ids']['maxItems'] = 0
        actions = ['search', 'stop']
        if ids:
            actions.append('read')
        if data['target_read']:
            actions.append('answer')
        schema['properties']['action']['enum'] = actions
        return schema

    @model_validator(mode='after')
    def single_action(self):
        for name, payload in [('search', self.searches), ('read', self.candidate_ids), ('answer', self.answers)]:
            if bool(payload) != (self.action == name):
                raise ValueError('Populate only the payload of the selected action.')
        return self

    def validate_context(self, data):
        if self.action == 'answer':
            if not data['target_read']:
                raise ValueError('Read the target implementation before answering its behavior.')
            check_answers(self.answers, data)
        if self.action == 'read':
            available = {c['id'] for c in data['candidates']}
            if len(set(self.candidate_ids)) != len(self.candidate_ids) or any(c not in available for c in self.candidate_ids):
                raise ValueError('Choose distinct unread candidate IDs from the current list.')
        if self.action == 'search':
            previous = {(c['tool'], c.get('query')) for c in data['previous_searches']}
            if any((r.tool, r.query) in previous for r in self.searches):
                raise ValueError('This search was already performed; use its observation or a different query.')


class IndependentReading(StrictModel):
    sufficient: bool
    missing: str = Field(max_length=300)
    answers: list[AnswerItem] = Field(max_length=5)

    @classmethod
    def constrain_schema(cls, schema, data):
        return constrain_answer_schema(schema, data)

    def validate_context(self, data):
        if self.sufficient:
            if self.missing:
                raise ValueError('Sufficient source cannot have missing evidence.')
            check_answers(self.answers, data)
        elif not self.missing.strip() or self.answers:
            raise ValueError('When insufficient, state the missing source and leave answers empty.')


class Verdict(StrictModel):
    requirement_id: str
    agrees: bool
    explanation: str = Field(min_length=1, max_length=240)


class AnswerAudit(StrictModel):
    checks: list[Verdict] = Field(min_length=1, max_length=5)

    @classmethod
    def constrain_schema(cls, schema, data):
        ids = [r['id'] for r in data['contract']['requirements']]
        schema['$defs']['Verdict']['properties']['requirement_id']['enum'] = ids
        schema['properties']['checks'].update(minItems=len(ids), maxItems=len(ids))
        return schema

    def validate_context(self, data):
        expected = [r['id'] for r in data['contract']['requirements']]
        if sorted(c.requirement_id for c in self.checks) != sorted(expected):
            raise ValueError('Audit every frozen requirement exactly once.')
