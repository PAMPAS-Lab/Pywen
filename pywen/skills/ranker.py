"""Relevance-based skill ranking.

When the number of loaded skills exceeds a threshold (``top_k``), this
module selects the most relevant ones based on the user's query.

Ranking strategy (with automatic fallback):

1. If ``sentence-transformers`` is installed: semantic embedding similarity.
2. Otherwise: keyword matching based on term overlap.
3. If the skill count is within ``top_k``, the full list is returned
   unchanged (no ranking needed).
"""
from __future__ import annotations

from typing import List

from .models import SkillMetadata


def rank_skills_by_relevance(
    skills: List[SkillMetadata],
    query: str,
    top_k: int = 10,
) -> List[SkillMetadata]:
    """Return the top-k most relevant skills for the given query.

    Args:
        skills: Candidate skills.
        query:  User input or task description.
        top_k:  Maximum number of skills to return.

    Returns:
        Skills sorted by descending relevance (at most *top_k*).
    """
    if top_k >= len(skills):
        return skills

    if not query.strip():
        return skills[:top_k]

    # Prefer semantic embedding ranking
    try:
        return _rank_by_embedding(skills, query, top_k)
    except ImportError:
        pass  # sentence-transformers not installed
    except Exception:
        pass  # Runtime error — fall back gracefully

    # Fallback: keyword matching
    return _rank_by_keywords(skills, query, top_k)


def _rank_by_embedding(
    skills: List[SkillMetadata],
    query: str,
    top_k: int,
) -> List[SkillMetadata]:
    """Rank skills using sentence-transformers semantic similarity."""
    from sentence_transformers import SentenceTransformer, util  # type: ignore

    model = SentenceTransformer("all-MiniLM-L6-v2")

    query_emb = model.encode(query, convert_to_tensor=True)
    skill_texts = [f"{s.name}: {s.description}" for s in skills]
    skill_embs = model.encode(skill_texts, convert_to_tensor=True)

    scores = util.cos_sim(query_emb, skill_embs)[0]
    ranked_indices = scores.argsort(descending=True).tolist()[:top_k]
    return [skills[i] for i in ranked_indices]


def _rank_by_keywords(
    skills: List[SkillMetadata],
    query: str,
    top_k: int,
) -> List[SkillMetadata]:
    """Rank skills by counting how many query words appear in name/description.

    Short words (≤2 chars) and common English stop-words are filtered out
    before counting to avoid false matches on articles, prepositions, etc.
    """
    # Common English stop-words and short/long word filter
    _STOP_WORDS: set[str] = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "shall",
        "should", "may", "might", "must", "can", "could", "i", "you", "he",
        "she", "it", "we", "they", "me", "him", "her", "us", "them", "my",
        "your", "his", "its", "our", "their", "this", "that", "these", "those",
        "of", "in", "to", "for", "on", "with", "at", "by", "from", "as",
        "into", "about", "like", "through", "after", "over", "between", "out",
        "against", "during", "without", "before", "under", "around", "among",
        "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
        "neither", "each", "every", "all", "any", "few", "more", "most",
        "other", "some", "such", "no", "only", "own", "same", "than", "too",
        "very", "just", "because", "now", "also", "how", "when", "where",
        "which", "who", "what", "why",
    }
    query_words = {w for w in query.lower().split() if len(w) > 2 and w not in _STOP_WORDS}

    def score(skill: SkillMetadata) -> int:
        text = f"{skill.name} {skill.description}".lower()
        return sum(1 for w in query_words if w in text)

    sorted_skills = sorted(skills, key=score, reverse=True)
    return sorted_skills[:top_k]
