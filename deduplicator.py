from dotenv import load_dotenv
load_dotenv()

import os
import json
import anthropic
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from sentence_transformers import SentenceTransformer, util


@st.cache_resource
def _load_embedding_model():
    print("Embedding model loaded.")
    return SentenceTransformer("all-MiniLM-L6-v2")


model = _load_embedding_model()


def deduplicate_by_url(items: list) -> list:
    """Return list keeping only the first occurrence of each unique URL."""
    seen = set()
    result = []
    for item in items:
        url = item.get("url", "")
        if url not in seen:
            seen.add(url)
            result.append(item)
    return result


def deduplicate_by_embedding(items: list, threshold: float = 0.85) -> list:
    """Cluster articles by semantic similarity of their headlines.

    Within each cluster keep the item with the highest final_score (or the
    first item if scores are equal).  Merge all source_name values from the
    cluster onto the kept item as sources_list and set source_count.
    """
    if not items:
        return []

    headlines = [item.get("headline", "") for item in items]
    embeddings = model.encode(headlines, convert_to_tensor=True)
    sim_matrix = util.cos_sim(embeddings, embeddings)

    n = len(items)
    duplicate_of = {}   # j -> i  (j is a duplicate of cluster i)

    for i in range(n):
        if i in duplicate_of:
            continue
        for j in range(i + 1, n):
            if j in duplicate_of:
                continue
            if sim_matrix[i][j].item() > threshold:
                duplicate_of[j] = i

    # Build clusters: cluster_id -> [indices]
    clusters = {}
    for idx in range(n):
        root = idx
        while root in duplicate_of:
            root = duplicate_of[root]
        clusters.setdefault(root, []).append(idx)

    kept = []
    for root, indices in clusters.items():
        cluster_items = [items[i] for i in indices]

        # Keep item with highest final_score; fall back to first
        best = max(cluster_items, key=lambda x: x.get("final_score", 0))

        # Collect all source names from the cluster
        sources_list = list({
            item.get("source_name", "")
            for item in cluster_items
            if item.get("source_name", "")
        })
        best = dict(best)   # shallow copy — don't mutate the original
        best["sources_list"]  = sources_list
        best["source_count"]  = len(sources_list)
        kept.append(best)

    # Preserve original ranking order by sorting on the kept item's position
    order = {id(items[i]): i for i in range(n)}
    kept.sort(key=lambda x: order.get(id(x), 0))
    return kept


def deduplicate_by_claude(items: list, api_key: str, batch_size: int = 20) -> list:
    """Use Claude to find articles covering the same specific political event.

    All batches are sent to Claude concurrently (max_workers=5).  The merge
    step runs sequentially afterwards to avoid shared-state race conditions.
    """
    if not items:
        return []

    client = anthropic.Anthropic(api_key=api_key)

    # Build batch index lists upfront
    all_batches = [
        list(range(batch_start, min(batch_start + batch_size, len(items))))
        for batch_start in range(0, len(items), batch_size)
    ]

    def _call_batch(batch_indices: list) -> tuple[list, list]:
        """Call Claude for one batch. Returns (batch_indices, groups)."""
        batch_items = [items[i] for i in batch_indices]
        numbered = "\n".join(
            f"{n + 1}. {item.get('headline', '')}"
            for n, item in enumerate(batch_items)
        )
        prompt = (
            "You are deduplicating political news headlines. "
            "Identify groups that cover the SAME SPECIFIC POLITICAL EVENT, not just the same topic. "
            "Same event: same announcement, same meeting, same protest, same statement. "
            "A cabinet reshuffle and who will be reshuffled are the same event. "
            "BJP strategy and Congress strategy are different events. "
            'Return only valid JSON: {"groups": [[index list], [index list]]}. '
            "Only include groups with 2 or more items. "
            'If none found return {"groups": []}. '
            f"Headlines:\n{numbered}"
        )
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
        except Exception as e:
            print(f"Warning: Claude API error on batch starting {batch_indices[0]}: {e}")
            return batch_indices, []

        # Strip markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            groups = json.loads(raw).get("groups", [])
        except (json.JSONDecodeError, AttributeError):
            print(f"Warning: JSON parse failed for batch starting {batch_indices[0]}. Skipping.")
            return batch_indices, []

        return batch_indices, groups

    # Run all batches concurrently
    batch_results: list[tuple[list, list]] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_call_batch, bi): bi for bi in all_batches}
        for future in as_completed(futures):
            batch_results.append(future.result())

    # Sort by batch start index for deterministic merge order
    batch_results.sort(key=lambda x: x[0][0] if x[0] else 0)

    # Apply merge logic sequentially (mutates shared absorbed / result_items)
    absorbed = set()
    result_items = [dict(item) for item in items]

    for batch_indices, groups in batch_results:
        for group in groups:
            global_indices = []
            for pos in group:
                gi = batch_indices[pos - 1]
                if gi not in absorbed:
                    global_indices.append(gi)

            if len(global_indices) < 2:
                continue

            best_gi = max(global_indices, key=lambda gi: result_items[gi].get("final_score", 0))

            existing = set(result_items[best_gi].get("sources_list", []))
            for gi in global_indices:
                if gi != best_gi:
                    src = result_items[gi].get("source_name", "")
                    if src:
                        existing.add(src)
                    for s in result_items[gi].get("sources_list", []):
                        if s:
                            existing.add(s)
                    absorbed.add(gi)

            result_items[best_gi]["sources_list"] = list(existing)
            result_items[best_gi]["source_count"] = len(existing)

    return [result_items[i] for i in range(len(items)) if i not in absorbed]


def deduplicate_all(items: list, api_key: str) -> list:
    """Run the full three-stage deduplication pipeline and apply source boost."""
    # Step 1 — URL
    after_url = deduplicate_by_url(items)
    print(f"After URL dedup   : {len(after_url)} items")

    # Step 2 — embedding
    after_embed = deduplicate_by_embedding(after_url, threshold=0.85)
    print(f"After embedding dedup: {len(after_embed)} items")

    # Step 3 — Claude
    after_claude = deduplicate_by_claude(after_embed, api_key=api_key)
    print(f"After Claude dedup: {len(after_claude)} items")

    # Step 4 — source count boost
    for item in after_claude:
        if "final_score" in item:
            item["final_score"] = apply_source_count_boost(
                item["final_score"], item.get("source_count", 1)
            )

    return after_claude


def apply_source_count_boost(score: float, source_count: int) -> float:
    """Return an importance score boosted by how many sources covered the story."""
    if source_count >= 6:
        return min(score * 1.25, 10.0)
    if source_count >= 3:
        return min(score * 1.10, 10.0)
    return score


if __name__ == "__main__":
    import sys

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        sys.exit(1)

    samples = [
        # Four articles covering the same cabinet reshuffle
        {
            "headline": "Karnataka CM Siddaramaiah drops 5 ministers in major cabinet reshuffle",
            "url": "https://thehindu.com/karnataka-cabinet-reshuffle",
            "source_name": "The Hindu",
            "final_score": 8.5,
        },
        {
            "headline": "Siddaramaiah reshuffles Karnataka cabinet, five senior ministers dropped",
            "url": "https://ndtv.com/karnataka-cabinet-reshuffle",
            "source_name": "NDTV",
            "final_score": 7.9,
        },
        {
            "headline": "Karnataka cabinet overhaul: CM removes five ministers ahead of elections",
            "url": "https://indianexpress.com/karnataka-cabinet",
            "source_name": "Indian Express",
            "final_score": 8.1,
        },
        # Same story, Hindi-style transliterated headline
        {
            "headline": "Karnataka mantrimandal mein badlav, 5 mantri hataaye gaye",
            "url": "https://aajtak.com/karnataka-cabinet",
            "source_name": "Aaj Tak",
            "final_score": 6.2,
        },
        # Two genuinely different stories
        {
            "headline": "Farmers block Bengaluru-Mysuru highway demanding loan waiver",
            "url": "https://deccanherald.com/farmer-protest",
            "source_name": "Deccan Herald",
            "final_score": 7.2,
        },
        {
            "headline": "BJP announces candidate list for upcoming Karnataka bypolls",
            "url": "https://timesofindia.com/bjp-candidates",
            "source_name": "Times of India",
            "final_score": 7.5,
        },
    ]

    print(f"\n{'='*55}")
    print(f"Before deduplication : {len(samples)} articles")

    # --- Stage 1 & 2: URL + embedding ---
    after_url   = deduplicate_by_url(samples)
    print(f"After URL dedup      : {len(after_url)} articles")
    after_embed = deduplicate_by_embedding(after_url, threshold=0.85)
    print(f"After embedding dedup: {len(after_embed)} articles")

    # --- Stage 3: Claude dedup ---
    print("\nRunning deduplicate_by_claude...")
    after_claude = deduplicate_by_claude(after_embed, api_key=api_key)
    print(f"After Claude dedup   : {len(after_claude)} articles\n")

    for art in after_claude:
        sc = art.get("source_count", 1)
        boosted = apply_source_count_boost(art["final_score"], sc)
        print(
            f"  [{art['final_score']:.1f} -> {boosted:.2f}]  "
            f"sources({sc}): {art.get('sources_list', [])}\n"
            f"  {art['headline']}\n"
        )

    # Print sources_list of the merged cabinet reshuffle item
    reshuffle = next(
        (a for a in after_claude if "cabinet" in a["headline"].lower() or "mantrimandal" in a["headline"].lower()),
        None,
    )
    if reshuffle:
        print(f"Cabinet reshuffle merged sources: {reshuffle.get('sources_list', [])}")

    # --- Full pipeline: deduplicate_all ---
    print(f"\n{'='*55}")
    print("Running deduplicate_all (full pipeline)...")
    final = deduplicate_all(samples, api_key=api_key)
    print(f"\nFinal article count  : {len(final)}")
    for art in final:
        print(
            f"  [score {art['final_score']:.2f}]  "
            f"sources({art.get('source_count', 1)}): {art.get('sources_list', [])}\n"
            f"  {art['headline']}\n"
        )
