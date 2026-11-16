"""API tests for the QA route (retrieval + [i]-mapped citations)."""

from __future__ import annotations

from conftest import GOOD_METADATA_JSON, FakeGateway


def _upload(client, name: str, content: bytes):
    return client.post(
        "/api/papers/upload",
        files={"file": (name, content, "application/pdf")},
    )


def test_qa_returns_answer_with_citations(api_client, sample_pdf):
    """Answer text is the gateway's reply; [n] markers map back to excerpts."""
    gw = FakeGateway(
        fast=GOOD_METADATA_JSON,
        # adjacent markers AND a repeated one: exercises the [1][2] parsing
        # edge and de-duplication of citation indexes
        strong="分块策略在方法部分说明 [1]，引言也有概述 [2][1]。",
    )
    with api_client(gw) as client:
        assert _upload(client, "sample.pdf", sample_pdf.read_bytes()).status_code == 200

        r = client.post(
            "/api/qa",
            json={"question": "How does the paper chunk sections?", "paper_id": None},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["answer"] == "分块策略在方法部分说明 [1]，引言也有概述 [2][1]。"
        # [1] and [2] referenced (the repeated [1] must not duplicate), so
        # exactly the first two retrieved excerpts become citations
        assert len(body["citations"]) == 2
        for citation in body["citations"]:
            assert citation["paper_id"] == 1
            assert citation["page"] >= 1
            assert citation["quote"]

        # answered on the strong tier with the QA token budget
        assert gw.calls[-1]["tier"] == "strong"
        assert gw.calls[-1]["max_tokens"] == 2048


def test_qa_empty_question_returns_400(api_client):
    with api_client(FakeGateway()) as client:
        r = client.post("/api/qa", json={"question": "   ", "paper_id": None})
        assert r.status_code == 400


def test_qa_no_hits_skips_llm(api_client):
    """Zero retrieved excerpts → 200 with the no-content answer; no LLM call."""
    gw = FakeGateway()  # any tier raising proves the gateway is never touched
    with api_client(gw) as client:
        r = client.post("/api/qa", json={"question": "什么东西都不相关"})
        assert r.status_code == 200
        assert r.json() == {"answer": "未找到相关内容", "citations": []}
        assert gw.calls == []


def test_qa_unmarked_answer_attaches_all_excerpts(api_client, sample_pdf):
    """No [n] markers in the answer → every retrieved excerpt is attached."""
    gw = FakeGateway(
        fast=GOOD_METADATA_JSON,
        strong="这段回答没有引用任何编号。",  # no [n] markers at all
    )
    with api_client(gw) as client:
        assert _upload(client, "sample.pdf", sample_pdf.read_bytes()).status_code == 200
        r = client.post(
            "/api/qa", json={"question": "What is the paper about?", "paper_id": 1}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["citations"], "unmarked answer must still carry citations"
        assert len(body["citations"]) <= 8
        # paper_id filter worked: only the one ingested paper is cited
        assert {c["paper_id"] for c in body["citations"]} == {1}


def test_qa_store_unavailable_returns_503(api_client):
    with api_client(FakeGateway()) as client:
        client.app.state.store = None
        r = client.post("/api/qa", json={"question": "hello?"})
        assert r.status_code == 503
