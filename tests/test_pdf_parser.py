"""Tests for PDF page extraction and section splitting (Task 5)."""

from app.rag.pdf_parser import PageText, extract_pages, split_sections


def test_extract_pages(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert len(pages) == 2
    # page numbers are 1-based
    assert [p.page for p in pages] == [1, 2]
    assert "Introduction" in pages[0].text
    assert "Method" in pages[1].text
    # all pages carry non-empty text
    assert all(isinstance(p.text, str) and p.text.strip() for p in pages)


def test_split_sections(sample_pdf):
    pages = extract_pages(sample_pdf)
    sections = split_sections(pages)

    titles = [s.title for s in sections]
    assert "1 Introduction" in titles
    assert "2 Method" in titles
    # text before the first numbered heading becomes "Front Matter"; the
    # standalone "Related Work" line at the end is an unnumbered heading
    assert titles == ["Front Matter", "1 Introduction", "2 Method", "Related Work"]

    front, intro, method = sections[:3]
    # Front Matter holds the title/abstract, not the "1 Introduction" heading
    assert "Sample Research Paper" in front.text
    assert "Abstract" in front.text
    assert "Introduction" not in front.text

    # a section keeps its own heading line and starts on its heading's page
    assert intro.text.lstrip().startswith("1 Introduction")
    assert intro.page == 1
    # the introduction spans page 2 as well (multi-page section)
    assert "next page" in intro.text
    assert "keeps flowing here" in intro.text

    assert method.text.lstrip().startswith("2 Method")
    assert method.page == 2
    # Method section does not swallow the introduction's spillover text
    assert "keeps flowing here" not in method.text


def test_prose_lines_are_not_headings():
    """Body lines that merely *start* like a numbered heading must not split.

    Empirically mis-split samples (each once matched ``^\\d+\\s+[A-Z]``):
    a citation year, a wrapped sentence, and a mid-sentence continuation.
    """
    prose = [
        "2023 A Survey of Embodied AI",  # 4-digit year, not a section number
        "3 The authors acknowledge...",  # ends with sentence punctuation
        "10 All experiments use three seeds",  # prose: lowercase content words
        "We also verified longer wrapped sentences keep flowing here and the",
        "parser must never tear them out of their surrounding paragraph.",
    ]
    pages = [PageText(page=1, text="\n".join(["1 Introduction", *prose]))]
    sections = split_sections(pages)

    # exactly one section: the real heading, with all prose lines inside it
    assert [s.title for s in sections] == ["1 Introduction"]
    for line in prose:
        assert line in sections[0].text


def test_heading_shape_still_matches_real_headings():
    """Real numbered (sub)section headings survive the added constraints —
    including a strict numbering sequence (major, then its subsections)."""
    lines = [
        "1 Introduction",
        "Body text.",
        "2 Background",
        "More body text.",
        "3 Experiments",
        "Experiment body text.",
        "3.1 Setup",
        "Setup body text.",
        "3.2 Experimental Results and Discussion",
        "Results body text.",
        "4 Conclusion and Future Work",
        "End.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "1 Introduction",
        "2 Background",
        "3 Experiments",
        "3.1 Setup",
        "3.2 Experimental Results and Discussion",
        "4 Conclusion and Future Work",
    ]


def test_affiliation_block_is_not_sections():
    """A 2-3 line run of same-scheme consecutive 'number + capitalised word'
    lines is an author-affiliation list, not the section structure."""
    lines = [
        "Diffusion Policy: Visuomotor Policy Learning via Action Diffusion",
        "Cheng Chi1, Siyuan Feng2, Yilun Du3, Shuran Song1",
        "1 Columbia University",
        "2 Toyota Research Institute",
        "3 MIT",
        "Abstract—This paper introduces Diffusion Policy.",
        "I. INTRODUCTION",
        "Policy learning from demonstration, in its simplest form, is supervised regression.",
        "II. DIFFUSION POLICY FORMULATION",
        "The section body continues here.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "I. INTRODUCTION",
        "II. DIFFUSION POLICY FORMULATION",
    ]
    # the affiliations stayed in the front matter, next to the authors
    assert "1 Columbia University" in sections[0].text
    assert "3 MIT" in sections[0].text


def test_superscript_author_forms_are_not_headings():
    """Digit glued to a letter ('1Columbia University', '1Cheng Chi') never
    parses as a heading — the scheme patterns require a separator."""
    lines = [
        "Paper Title Goes Here",
        "1Cheng Chi, 2Shuang Guo, 3Fei Hu",
        "1Columbia University",
        "2Toyota Research Institute",
        "3MIT",
        "Abstract text of the paper.",
        "1 Introduction",
        "Real body text follows the heading.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == ["Front Matter", "1 Introduction"]
    assert "1Columbia University" in sections[0].text


def test_numbering_must_start_at_one_and_increase():
    """Regressions and skips mark a line as non-heading: stray equation lines
    never hijack the section structure."""
    lines = [
        "Paper Title Here",
        "Abstract text.",
        "1 Introduction",
        "We begin with the flow matching objective.",
        "2 T (t), T(t) =",
        "x1 + (1 − t)x0 and related formulas appear in this line.",
        "1 Motivation",  # repeated 1 → regression
        "Body keeps going with the motivation details here.",
        "5 Experiments",  # skipped 2–4 → non-heading
        "And more body text follows along.",
        "2 Method",  # correct next major → heading
        "Method body text.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == ["Front Matter", "1 Introduction", "2 Method"]
    intro = sections[1].text
    assert "2 T (t), T(t) =" in intro
    assert "1 Motivation" in intro
    assert "5 Experiments" in intro
    # the fake '5' never became a heading, so the real '2 Method' still did
    assert "2 Method" not in intro


def test_dotted_arabic_headings_detected():
    """'1. Introduction' / '3.1. Pre-Trained …' style (RT-2) with strict skips."""
    lines = [
        "RT-2 Paper Title",
        "Abstract text.",
        "1. Introduction",
        "Introduction body.",
        "2. Related Work",
        "Related work body.",
        "3. Vision-Language-Action Models",
        "VLA body.",
        "3.1. Pre-Trained Vision-Language Models",
        "Subsection body.",
        "3.2. Robot-Action Fine-tuning",
        "More subsection body.",
        "4. Experiments",
        "Experiments body.",
        "6. Conclusions",  # skipped 5 → non-heading
        "Conclusions body that stays inside section 4.",
        "3. Summary",  # regression below 5 → non-heading
        "Summary body that also stays inside section 4.",
        "5. Limitations",  # the correct next major → heading again
        "Limitations body.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "1. Introduction",
        "2. Related Work",
        "3. Vision-Language-Action Models",
        "3.1. Pre-Trained Vision-Language Models",
        "3.2. Robot-Action Fine-tuning",
        "4. Experiments",
        "5. Limitations",
    ]
    experiments = sections[-2].text
    assert "6. Conclusions" in experiments
    assert "3. Summary" in experiments


def test_roman_and_letter_headings_detected():
    """RSS-style 'I. INTRODUCTION' with 'A./B./C.' subsections; the letter
    counter restarts under each new roman section."""
    lines = [
        "Paper Title",
        "Abstract goes here.",
        "I. INTRODUCTION",
        "Intro body text.",
        "II. DIFFUSION POLICY FORMULATION",
        "Section body.",
        "A. Denoising Diffusion Probabilistic Models",
        "Subsection body.",
        "B. DDPM Training",
        "More body.",
        "C. Simulation Environments and datasets",
        "Body with one lowercase word in the heading above.",
        "III. EVALUATION",
        "Eval body.",
        "A. Key Findings",
        "Findings body.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "I. INTRODUCTION",
        "II. DIFFUSION POLICY FORMULATION",
        "A. Denoising Diffusion Probabilistic Models",
        "B. DDPM Training",
        "C. Simulation Environments and datasets",
        "III. EVALUATION",
        "A. Key Findings",
    ]


def test_bibliography_author_lines_are_not_headings():
    """Reference-list author lines ('A. Herzog, J. Hsu, …', 'H. Wallach,')
    must never become sections even though they start like letter headings.
    The standalone 'References' line itself is a known unnumbered heading,
    so the bibliography becomes its own section — with the author lines
    kept inside it, not split out."""
    lines = [
        "Paper Title",
        "Abstract text.",
        "1 Introduction",
        "Body of the introduction.",
        "References",
        "A. Herzog, J. Hsu, et al. Do as I can, not as I say.",
        "H. Wallach, H. Larochelle, A. Beygelzimer,",
        "R. A. Fisher. Design of experiments.",
        "2 Conclusion",
        "Closing body.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "1 Introduction",
        "References",
        "2 Conclusion",
    ]
    # the author lines stay inside the References section, unsplit
    assert "A. Herzog, J. Hsu, et al. Do as I can, not as I say." in sections[2].text
    assert "H. Wallach, H. Larochelle, A. Beygelzimer," in sections[2].text


def test_sample_pdf_prose_lines_stay_in_body(sample_pdf):
    """The mis-split-prone body lines baked into the fixture stay in the body."""
    sections = split_sections(extract_pages(sample_pdf))
    assert [s.title for s in sections] == [
        "Front Matter",
        "1 Introduction",
        "2 Method",
        "Related Work",
    ]
    body = "\n".join(s.text for s in sections)
    assert "2023 A Survey of Embodied AI" in body
    assert "3 The authors acknowledge..." in body
    assert "10 All experiments use three seeds" in body


def test_unnumbered_heading_recognized(sample_pdf):
    """A standalone 'Related Work' line (baked into the fixture) splits its
    own section without disturbing the numbered headings before it."""
    sections = split_sections(extract_pages(sample_pdf))

    assert [s.title for s in sections] == [
        "Front Matter",
        "1 Introduction",
        "2 Method",
        "Related Work",
    ]
    related = sections[-1]
    # the heading line is kept as the first line of its section's text
    assert related.text.lstrip().startswith("Related Work")
    assert "Prior work on unnumbered section headings is scarce." in related.text


def test_allcaps_heading_recognized():
    """All-caps lines (>=2 words, no trailing punctuation) split sections;
    a numbered all-caps heading keeps its number in the title."""
    lines = [
        "Paper Title",
        "Abstract text.",
        "1 Introduction",
        "Intro body.",
        "2 Method",
        "Method body.",
        "3 RELATED WORK",  # numbered + all-caps content
        "Related work body text.",
        "EVALUATION RESULTS",  # pure all-caps, not in the known-word list
        "Evaluation body text.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "1 Introduction",
        "2 Method",
        "3 RELATED WORK",
        "EVALUATION RESULTS",
    ]
    assert "RELATED WORK" in sections[3].title


def test_body_sentence_with_keyword_not_heading():
    """Prose lines that merely *contain* a section keyword never split —
    the match must be the whole line."""
    lines = [
        "Paper Title",
        "Abstract text.",
        "1 Introduction",
        "The introduction of new methods improved results.",
        "This line discusses related work in passing while flowing on.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == ["Front Matter", "1 Introduction"]
    assert "The introduction of new methods improved results." in sections[1].text
    assert "related work in passing" in sections[1].text


def test_known_heading_case_insensitive():
    """Known section nouns match whole-line, case-insensitively, with
    internal whitespace collapsed; unnumbered headings never touch the
    numbered sequence ('2 Conclusion' still lands after them)."""
    lines = [
        "Paper Title",
        "Abstract text.",
        "1 Introduction",
        "Intro body.",
        "Related   Work",  # collapsed to "Related Work" before matching
        "We survey prior approaches in detail.",
        "Experiments",  # title case
        "We evaluate the proposed approach.",
        "2 Conclusion",  # numbering unharmed by the unnumbered headings
        "Conclusion body.",
    ]
    sections = split_sections([PageText(page=1, text="\n".join(lines))])
    assert [s.title for s in sections] == [
        "Front Matter",
        "1 Introduction",
        "Related Work",
        "Experiments",
        "2 Conclusion",
    ]
