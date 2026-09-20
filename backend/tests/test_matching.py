"""Tests for the deterministic matcher.

The ambiguity handling is the part most likely to go wrong quietly, so it gets
the most attention here: a false hit on `Go` or `C` silently moves every score.
"""

import pytest

from app.matching import MIN_SKILLS_FOR_RATING, find_skills, rate_match

RESUME = """Alex Milligan — Senior Engineer
10 years of experience building backend services.
Python, FastAPI, PostgreSQL, Docker, Kubernetes, CI/CD, AWS.
"""


# --------------------------------------------------------------------- skill finding


def test_finds_plain_skills():
    found = find_skills("We use Python, PostgreSQL and Kubernetes.")
    assert set(found) == {"Python", "PostgreSQL", "Kubernetes"}


def test_aliases_map_to_one_canonical_name():
    assert set(find_skills("postgres and k8s")) == {"PostgreSQL", "Kubernetes"}
    assert set(find_skills("PostgreSQL and kubernetes")) == {"PostgreSQL", "Kubernetes"}


@pytest.mark.parametrize(
    "text",
    [
        "Let's go to the office on Tuesday.",
        "This is a great opportunity to go far.",
        "We want someone who can go deep on problems.",
    ],
)
def test_ambiguous_word_in_prose_is_not_a_skill(text):
    assert "Go" not in find_skills(text)


@pytest.mark.parametrize(
    "text",
    [
        "Our stack: Go, Python, Rust.",
        "Kubernetes, Terraform, Go and Python.",
        "Experience with golang required.",
    ],
)
def test_ambiguous_word_in_a_list_is_a_skill(text):
    assert "Go" in find_skills(text)


def test_longer_alias_wins_over_shorter():
    # `node.js` must not be read as `node` plus stray punctuation.
    assert "Node.js" in find_skills("We run Node.js services.")


def test_c_is_not_found_inside_cplusplus():
    found = find_skills("Systems work in C++.")
    assert "C++" in found
    assert "C" not in found


def test_substrings_of_longer_words_are_not_matched():
    # "gopher", "java" inside "javascript", "rusty"
    found = find_skills("The gopher was rusty.")
    assert found == {}


# ------------------------------------------------------------------------- weighting


def test_requirements_outweigh_passing_mentions():
    """A skill in the requirements moves the score more than one merely named."""
    posting = (
        "Requirements: must have Kubernetes.\n"
        "We also happen to use Redis, Python and Terraform here."
    )

    covers_requirement = rate_match(
        posting_raw_text=posting,
        posting_extracted=None,
        resume_text="I know Kubernetes.",
    )
    covers_one_mention = rate_match(
        posting_raw_text=posting,
        posting_extracted=None,
        resume_text="I know Redis.",
    )
    assert covers_requirement.score is not None
    assert covers_one_mention.score is not None
    # Same number of skills covered, but the required one is worth more.
    assert covers_requirement.score > covers_one_mention.score


def test_raw_text_requirement_cue_is_labelled_as_a_guess():
    """Cue-detected requirements must not claim the certainty of extraction."""
    from_raw = rate_match(
        posting_raw_text="Requirements: Python, Docker, AWS.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    from_extraction = rate_match(
        posting_raw_text="",
        posting_extracted={"requirements": ["Python", "Docker", "AWS"]},
        resume_text=RESUME,
    )
    assert {h.source for h in from_raw.matched} == {"likely required"}
    assert {h.source for h in from_extraction.matched} == {"required"}


def test_extracted_requirements_are_weighted_above_raw_mentions():
    result = rate_match(
        posting_raw_text="We sometimes touch Redis.",
        posting_extracted={
            "requirements": ["Strong Python", "Production Kubernetes"],
            "nice_to_have": ["Redis"],
        },
        resume_text="Python and Kubernetes in production.",
    )
    sources = {hit.skill: hit.source for hit in result.matched}
    assert sources["Python"] == "required"
    assert sources["Kubernetes"] == "required"
    assert result.score is not None and result.score >= 80


# ----------------------------------------------------------------------- experience


def test_stated_years_are_read_from_both_sides():
    result = rate_match(
        posting_raw_text="Requires 8+ years of experience with Python, Docker and AWS.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert result.required_years == 8
    assert result.resume_years == 10
    assert result.years_basis == "stated on the resume"


def test_short_experience_lowers_the_score():
    posting = "Requires 10 years of experience. Python, Docker, AWS, Kubernetes."
    seasoned = rate_match(
        posting_raw_text=posting,
        posting_extracted=None,
        resume_text="12 years of experience. Python, Docker, AWS, Kubernetes.",
    )
    junior = rate_match(
        posting_raw_text=posting,
        posting_extracted=None,
        resume_text="2 years of experience. Python, Docker, AWS, Kubernetes.",
    )
    assert seasoned.score is not None and junior.score is not None
    assert seasoned.score > junior.score


def test_years_inferred_from_dates_when_not_stated():
    result = rate_match(
        posting_raw_text="Requires 5 years of experience. Python, Docker, AWS.",
        posting_extracted=None,
        resume_text="Engineer since 2015. Python, Docker, AWS.",
    )
    assert result.resume_years is not None
    assert result.years_basis == "inferred from dates on the resume"


def test_missing_experience_signal_does_not_penalise():
    """A resume with no dates is scored on skills alone, not marked down."""
    with_years = rate_match(
        posting_raw_text="Python, Docker, AWS, Kubernetes are all required.",
        posting_extracted=None,
        resume_text="10 years of experience. Python, Docker, AWS, Kubernetes.",
    )
    without_years = rate_match(
        posting_raw_text="Python, Docker, AWS, Kubernetes are all required.",
        posting_extracted=None,
        resume_text="Python, Docker, AWS, Kubernetes.",
    )
    assert with_years.score == without_years.score == 100


# -------------------------------------------------------------------------- rating


def test_full_coverage_scores_top():
    result = rate_match(
        posting_raw_text="Python, Docker, AWS and Kubernetes.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert result.score == 100
    assert result.rating == "Strong"
    assert result.missing == []


def test_no_overlap_scores_zero():
    result = rate_match(
        posting_raw_text="We need Rails, PHP and Laravel.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert result.score == 0
    assert result.rating == "Weak"


def test_missing_skills_are_reported():
    result = rate_match(
        posting_raw_text="Requirements: Python, Terraform, Kubernetes, Rust.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert {hit.skill for hit in result.missing} == {"Terraform", "Rust"}
    assert "Terraform" in result.explanation


def test_no_resume_returns_no_score():
    result = rate_match(
        posting_raw_text="Python, Docker, AWS.",
        posting_extracted=None,
        resume_text=None,
    )
    assert result.score is None
    assert result.confidence == "none"
    assert "resume" in result.explanation.lower()


def test_thin_posting_returns_no_score():
    """Better to say nothing than to rate a posting off one keyword."""
    result = rate_match(
        posting_raw_text="Great team, great culture, competitive salary. Some Python.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert result.score is None
    assert result.rating == "Not enough detail"


def test_confidence_rises_with_recognised_skills():
    thin = rate_match(
        posting_raw_text="Python, Docker, AWS.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    rich = rate_match(
        posting_raw_text="Python, Docker, AWS, Kubernetes, PostgreSQL, Redis, Terraform.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert thin.confidence == "medium"
    assert rich.confidence == "high"


def test_rating_is_stable_across_runs():
    """Same inputs, same number -- the point of not using a model."""
    args = dict(
        posting_raw_text="Requirements: Python, Kubernetes, Terraform. 8+ years of experience.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    scores = {rate_match(**args).score for _ in range(5)}
    assert len(scores) == 1


def test_min_skills_threshold_is_respected():
    below = "Python and Docker only."
    assert len(find_skills(below)) < MIN_SKILLS_FOR_RATING
    assert (
        rate_match(posting_raw_text=below, posting_extracted=None, resume_text=RESUME).score is None
    )


# --------------------------------------------------------------------------- caching


def test_cached_results_survive_caller_mutation():
    """Results are cached by content; a caller editing them must not poison it."""
    args = dict(
        posting_raw_text="Requirements: Python, Docker, AWS, Kubernetes.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    first = rate_match(**args)
    matched_count = len(first.matched)
    first.matched.clear()
    first.missing.clear()

    second = rate_match(**args)
    assert len(second.matched) == matched_count


def test_different_text_is_a_different_cache_entry():
    """Two postings must not share a cached result just because one was seen first."""
    python_role = rate_match(
        posting_raw_text="Requirements: Python, Docker, AWS.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    php_role = rate_match(
        posting_raw_text="Requirements: PHP, Laravel, MySQL.",
        posting_extracted=None,
        resume_text=RESUME,
    )
    assert python_role.score == 100
    assert php_role.score == 0


def test_extracted_changes_produce_a_different_rating():
    """The cache key covers the extracted payload, not just the raw text."""
    raw = "We work with Python, Docker and AWS."
    without = rate_match(posting_raw_text=raw, posting_extracted=None, resume_text=RESUME)
    with_extra = rate_match(
        posting_raw_text=raw,
        posting_extracted={"requirements": ["Rust", "Go", "Terraform"]},
        resume_text=RESUME,
    )
    assert without.score == 100
    assert with_extra.score is not None and with_extra.score < 100
