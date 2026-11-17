from labor_law_rag.citations import extract_citations

LAWS = ["근로기준법", "근로기준법 시행령"]


def test_fixture_slices_are_right(law_index):
    assert law_index.text("근로기준법 제60조 제2항").startswith("② 사용자는 계속하여")
    assert law_index.text("근로기준법 제76조의2").startswith("사용자 또는 근로자는")


def test_extract_citations_variants(law_index):
    t = "근로기준법 제60조제2항에 따라 ... 같은 법 제60조에 의하면"
    assert extract_citations(t, LAWS, law_index) == ["근로기준법 제60조 제2항", "근로기준법 제60조 제1항"]


def test_branch_article_and_decree(law_index):
    t = "근로기준법 제76조의2 및 동법 시행령 제33조제1항"
    assert extract_citations(t, LAWS, law_index) == ["근로기준법 제76조의2", "근로기준법 시행령 제33조 제1항"]


def test_decree_name_not_split_into_law(law_index):
    assert extract_citations("근로기준법 시행령 제33조", LAWS, law_index) == ["근로기준법 시행령 제33조 제1항"]


def test_unknown_article_is_ignored(law_index):
    assert extract_citations("근로기준법 제999조, 산업안전보건법 제5조", LAWS, law_index) == []


def test_same_law_without_prior_law_is_ignored(law_index):
    assert extract_citations("같은 법 제60조", LAWS, law_index) == []
